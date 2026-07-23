from contextlib import contextmanager
import json

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
