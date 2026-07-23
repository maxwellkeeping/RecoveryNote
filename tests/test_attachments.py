from contextlib import contextmanager
import json
import os

import app as app_module


def _minimal_groups():
    return [
        (
            "Agreement",
            [
                {
                    "name": "AGREEMENT_AUTHOR",
                    "label": "AGREEMENT AUTHOR",
                    "required": True,
                },
                {"name": "COMMENTS", "label": "COMMENTS", "required": False},
            ],
        )
    ]


def test_remove_attachments_deletes_selected_files(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    submission_dir = upload_root / "7"
    submission_dir.mkdir(parents=True)
    keep_file = submission_dir / "keep.txt"
    remove_file = submission_dir / "remove.txt"
    keep_file.write_text("keep", encoding="utf-8")
    remove_file.write_text("remove", encoding="utf-8")

    monkeypatch.setattr(app_module, "UPLOADS_DIR", str(upload_root))

    existing = [
        {"name": "keep.txt", "stored": "keep.txt"},
        {"name": "remove.txt", "stored": "remove.txt"},
    ]

    kept, removed_count = app_module.remove_attachments(7, existing, ["remove.txt"])

    assert kept == [{"name": "keep.txt", "stored": "keep.txt"}]
    assert removed_count == 1
    assert keep_file.exists()
    assert not remove_file.exists()


def test_update_removes_selected_attachments_before_save(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    submission_dir = upload_root / "7"
    submission_dir.mkdir(parents=True)
    keep_file = submission_dir / "keep.txt"
    remove_file = submission_dir / "remove.txt"
    keep_file.write_text("keep", encoding="utf-8")
    remove_file.write_text("remove", encoding="utf-8")

    state = {
        "existing": {
            "AGREEMENT_AUTHOR": "initial.author",
            "COMMENTS": "before",
            "_created_at": "2026-07-01",
            "_attachments": [
                {"name": "keep.txt", "stored": "keep.txt"},
                {"name": "remove.txt", "stored": "remove.txt"},
            ],
        },
        "updated_payload": None,
        "save_existing": None,
    }

    @contextmanager
    def _db_cursor_capture_update():
        class Cursor:
            def __init__(self):
                self.last_query = ""

            def execute(self, query, params):
                self.last_query = query
                if "UPDATE submissions SET data" in query:
                    state["updated_payload"] = json.loads(params[0])

            def fetchone(self):
                if "SELECT data FROM submissions" in self.last_query:
                    return (state["existing"],)
                return None

        yield Cursor()

    def _save_attachments(submission_id, files, existing=None):
        state["save_existing"] = list(existing or [])
        return existing or []

    monkeypatch.setattr(app_module, "UPLOADS_DIR", str(upload_root))
    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)
    monkeypatch.setattr(app_module, "save_attachments", _save_attachments)
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "editor.user")

    with app_module.app.test_request_context(
        "/update/7",
        method="POST",
        data={
            "AGREEMENT_AUTHOR": "updated.author",
            "COMMENTS": "after",
            "remove_attachments": "remove.txt",
        },
    ):
        response = app_module.update.__wrapped__(7)

    assert response.status_code == 302
    assert state["save_existing"] == [{"name": "keep.txt", "stored": "keep.txt"}]
    assert state["updated_payload"]["_attachments"] == [
        {"name": "keep.txt", "stored": "keep.txt"}
    ]
    assert keep_file.exists()
    assert not remove_file.exists()


def test_update_delete_now_removes_attachment_without_full_submit(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    submission_dir = upload_root / "7"
    submission_dir.mkdir(parents=True)
    keep_file = submission_dir / "keep.txt"
    remove_file = submission_dir / "remove.txt"
    keep_file.write_text("keep", encoding="utf-8")
    remove_file.write_text("remove", encoding="utf-8")

    state = {
        "existing": {
            "AGREEMENT_AUTHOR": "initial.author",
            "COMMENTS": "before",
            "_created_at": "2026-07-01",
            "_attachments": [
                {"name": "keep.txt", "stored": "keep.txt"},
                {"name": "remove.txt", "stored": "remove.txt"},
            ],
        },
        "updated_payload": None,
    }

    @contextmanager
    def _db_cursor_capture_update():
        class Cursor:
            def __init__(self):
                self.last_query = ""

            def execute(self, query, params):
                self.last_query = query
                if "UPDATE submissions SET data" in query:
                    state["updated_payload"] = json.loads(params[0])

            def fetchone(self):
                if "SELECT data FROM submissions" in self.last_query:
                    return (state["existing"],)
                return None

        yield Cursor()

    def _save_attachments_should_not_run(*args, **kwargs):
        raise AssertionError("save_attachments should not be called for delete-now")

    def _load_field_groups_should_not_run():
        raise AssertionError("load_field_groups should not be called for delete-now")

    monkeypatch.setattr(app_module, "UPLOADS_DIR", str(upload_root))
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)
    monkeypatch.setattr(app_module, "save_attachments", _save_attachments_should_not_run)
    monkeypatch.setattr(app_module, "load_field_groups", _load_field_groups_should_not_run)

    with app_module.app.test_request_context(
        "/update/7",
        method="POST",
        data={"_delete_attachment": "remove.txt"},
    ):
        response = app_module.update.__wrapped__(7)
        undo_payload = app_module.session.get(app_module.ATTACHMENT_UNDO_SESSION_KEY)

    assert response.status_code == 302
    assert response.location.endswith("/edit/7")
    assert state["updated_payload"]["_attachments"] == [
        {"name": "keep.txt", "stored": "keep.txt"}
    ]
    assert keep_file.exists()
    assert not remove_file.exists()
    assert (submission_dir / ".trash" / "remove.txt").exists()
    assert undo_payload["submission_id"] == 7
    assert undo_payload["attachment"]["stored"] == "remove.txt"


def test_update_undo_delete_restores_attachment(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    submission_dir = upload_root / "7"
    trash_dir = submission_dir / ".trash"
    trash_dir.mkdir(parents=True)
    archived_file = trash_dir / "remove.txt"
    archived_file.write_text("remove", encoding="utf-8")

    state = {
        "existing": {
            "AGREEMENT_AUTHOR": "initial.author",
            "COMMENTS": "before",
            "_created_at": "2026-07-01",
            "_attachments": [{"name": "keep.txt", "stored": "keep.txt"}],
        },
        "updated_payload": None,
    }

    @contextmanager
    def _db_cursor_capture_update():
        class Cursor:
            def __init__(self):
                self.last_query = ""

            def execute(self, query, params):
                self.last_query = query
                if "UPDATE submissions SET data" in query:
                    state["updated_payload"] = json.loads(params[0])

            def fetchone(self):
                if "SELECT data FROM submissions" in self.last_query:
                    return (state["existing"],)
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "UPLOADS_DIR", str(upload_root))
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)

    with app_module.app.test_request_context(
        "/update/7",
        method="POST",
        data={"_undo_attachment_delete": "1"},
    ):
        app_module.session[app_module.ATTACHMENT_UNDO_SESSION_KEY] = {
            "submission_id": 7,
            "attachment": {"name": "remove.txt", "stored": "remove.txt"},
            "archived": "remove.txt",
        }
        response = app_module.update.__wrapped__(7)
        undo_payload = app_module.session.get(app_module.ATTACHMENT_UNDO_SESSION_KEY)

    assert response.status_code == 302
    assert response.location.endswith("/edit/7")
    assert undo_payload is None

    attachments = state["updated_payload"]["_attachments"]
    stored_names = {a["stored"] for a in attachments}
    assert "keep.txt" in stored_names
    assert "remove.txt" in stored_names

    restored_file = submission_dir / "remove.txt"
    assert restored_file.exists()
    assert not archived_file.exists()
