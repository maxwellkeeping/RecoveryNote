from contextlib import contextmanager
import json

import app as app_module


def _groups_with_agreement_id():
    return [
        (
            "Agreement",
            [
                {"name": "AGREEMENT_ID", "label": "AGREEMENT ID", "required": True},
                {"name": "AGREEMENT_AUTHOR", "label": "AGREEMENT AUTHOR", "required": True},
                {"name": "COMMENTS", "label": "COMMENTS", "required": False},
            ],
        )
    ]


class _AdminUser:
    id = 1
    username = "admin.user"
    is_admin = True


class _StandardUser:
    id = 2
    username = "standard.user"
    is_admin = False


def test_submit_allows_admin_agreement_id_override(monkeypatch):
    state = {"inserted_payload": None}

    @contextmanager
    def _db_cursor_capture_submit():
        class Cursor:
            def __init__(self):
                self.last_query = ""

            def execute(self, query, params):
                self.last_query = query
                if "INSERT INTO submissions" in query:
                    state["inserted_payload"] = json.loads(params[0])

            def fetchone(self):
                if "INSERT INTO submissions" in self.last_query:
                    return (501,)
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "current_user", _AdminUser())
    monkeypatch.setattr(app_module, "load_field_groups", _groups_with_agreement_id)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_submit)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "creator.user")

    with app_module.app.test_request_context(
        "/submit",
        method="POST",
        data={
            "AGREEMENT_ID": "CUSTOM-ADMIN-ID-001",
            "AGREEMENT_AUTHOR": "",
            "COMMENTS": "manual override",
            "_agreement_id_manual_override": "1",
        },
    ):
        response = app_module.submit.__wrapped__()

    assert response.status_code == 302
    assert state["inserted_payload"]["AGREEMENT_ID"] == "CUSTOM-ADMIN-ID-001"


def test_update_prevents_non_admin_agreement_id_override(monkeypatch):
    state = {
        "existing": {
            "AGREEMENT_ID": "CAC-20260723-RN10027001",
            "AGREEMENT_AUTHOR": "original.author",
            "COMMENTS": "before",
            "_created_at": "2026-07-23",
            "_attachments": [],
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

    monkeypatch.setattr(app_module, "current_user", _StandardUser())
    monkeypatch.setattr(app_module, "load_field_groups", _groups_with_agreement_id)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "editor.user")

    with app_module.app.test_request_context(
        "/update/9",
        method="POST",
        data={
            "AGREEMENT_ID": "CUSTOM-NONADMIN-ID-999",
            "AGREEMENT_AUTHOR": "",
            "COMMENTS": "after",
        },
    ):
        response = app_module.update.__wrapped__(9)

    assert response.status_code == 302
    assert state["updated_payload"]["AGREEMENT_ID"] == "CAC-20260723-RN10027001"


def test_update_allows_admin_agreement_id_override(monkeypatch):
    state = {
        "existing": {
            "AGREEMENT_ID": "CAC-20260723-RN10027001",
            "AGREEMENT_AUTHOR": "original.author",
            "COMMENTS": "before",
            "_created_at": "2026-07-23",
            "_attachments": [],
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

    monkeypatch.setattr(app_module, "current_user", _AdminUser())
    monkeypatch.setattr(app_module, "load_field_groups", _groups_with_agreement_id)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "editor.user")

    with app_module.app.test_request_context(
        "/update/9",
        method="POST",
        data={
            "AGREEMENT_ID": "CUSTOM-ADMIN-ID-777",
            "AGREEMENT_AUTHOR": "",
            "COMMENTS": "after",
            "_agreement_id_manual_override": "1",
        },
    ):
        response = app_module.update.__wrapped__(9)

    assert response.status_code == 302
    assert state["updated_payload"]["AGREEMENT_ID"] == "CUSTOM-ADMIN-ID-777"
