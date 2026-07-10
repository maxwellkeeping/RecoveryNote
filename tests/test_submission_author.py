from contextlib import contextmanager
import json

import app as app_module


def _minimal_groups():
    return [
        (
            "Agreement",
            [
                {"name": "AGREEMENT_AUTHOR", "label": "AGREEMENT AUTHOR", "required": True},
                {"name": "COMMENTS", "label": "COMMENTS", "required": False},
            ],
        )
    ]


def _minimal_groups_with_status():
    return [
        (
            "Agreement",
            [
                {"name": "AGREEMENT_AUTHOR", "label": "AGREEMENT AUTHOR", "required": True},
                {"name": "STATUS", "label": "STATUS", "required": True},
                {"name": "COMMENTS", "label": "COMMENTS", "required": False},
            ],
        )
    ]


def test_submit_sets_author_from_logged_in_user(monkeypatch):
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
                    return (101,)
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_submit)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "_current_submission_author",
        lambda: "creator.user",
    )

    with app_module.app.test_request_context(
        "/submit",
        method="POST",
        data={"AGREEMENT_AUTHOR": "tampered.user", "COMMENTS": "hello"},
    ):
        response = app_module.submit.__wrapped__()

    assert response.status_code == 302
    assert state["inserted_payload"]["AGREEMENT_AUTHOR"] == "creator.user"


def test_update_keeps_original_author(monkeypatch):
    state = {
        "existing": {
            "AGREEMENT_AUTHOR": "initial.creator",
            "COMMENTS": "before",
            "_created_at": "2026-06-01",
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

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "_current_submission_author",
        lambda: "different.user",
    )

    with app_module.app.test_request_context(
        "/update/7",
        method="POST",
        data={"AGREEMENT_AUTHOR": "tampered.user", "COMMENTS": "after"},
    ):
        response = app_module.update.__wrapped__(7)

    assert response.status_code == 302
    assert state["updated_payload"]["AGREEMENT_AUTHOR"] == "initial.creator"


def test_current_submission_author_prefers_entra_email(monkeypatch):
    class DummyUser:
        id = 77
        username = "fallback.local.user"

    @contextmanager
    def _db_cursor_entra_identity():
        class Cursor:
            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchone(self):
                if "FROM oauth_identities" in self.query:
                    return ("person.user@ontario.ca", "Person User")
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "current_user", DummyUser())
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_entra_identity)

    assert app_module._current_submission_author() == "person.user@ontario.ca"


def test_submit_uses_entra_email_as_author(monkeypatch):
    class DummyUser:
        id = 88
        username = "fallback.local.user"

    state = {"inserted_payload": None}

    @contextmanager
    def _db_cursor_entra_submit():
        class Cursor:
            def __init__(self):
                self.query = ""

            def execute(self, query, params):
                self.query = query
                if "INSERT INTO submissions" in query:
                    state["inserted_payload"] = json.loads(params[0])

            def fetchone(self):
                if "FROM oauth_identities" in self.query:
                    return ("creator.entra@ontario.ca", "Creator Entra")
                if "INSERT INTO submissions" in self.query:
                    return (202,)
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "current_user", DummyUser())
    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_entra_submit)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])

    with app_module.app.test_request_context(
        "/submit",
        method="POST",
        data={"AGREEMENT_AUTHOR": "tampered.user", "COMMENTS": "hello"},
    ):
        response = app_module.submit.__wrapped__()

    assert response.status_code == 302
    assert state["inserted_payload"]["AGREEMENT_AUTHOR"] == "creator.entra@ontario.ca"


def test_current_submission_author_prefers_session_entra_author(monkeypatch):
    class DummyUser:
        id = 91
        username = "fallback.local.user"

    @contextmanager
    def _db_cursor_unused():
        class Cursor:
            def execute(self, query, params):
                self.query = query

            def fetchone(self):
                return ("should.not@be.used", "Should Not Be Used")

        yield Cursor()

    monkeypatch.setattr(app_module, "current_user", DummyUser())
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_unused)

    with app_module.app.test_request_context("/"):
        app_module.session["entra_author"] = "session.user@ontario.ca"
        assert app_module._current_submission_author() == "session.user@ontario.ca"


def test_submit_initializes_status_tracking(monkeypatch):
    state = {"inserted_payload": None}

    @contextmanager
    def _db_cursor_capture_submit_status():
        class Cursor:
            def __init__(self):
                self.last_query = ""

            def execute(self, query, params):
                self.last_query = query
                if "INSERT INTO submissions" in query:
                    state["inserted_payload"] = json.loads(params[0])

            def fetchone(self):
                if "INSERT INTO submissions" in self.last_query:
                    return (303,)
                return None

        yield Cursor()

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups_with_status)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_submit_status)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "status.user")

    with app_module.app.test_request_context(
        "/submit",
        method="POST",
        data={"STATUS": "Draft", "COMMENTS": "hello"},
    ):
        response = app_module.submit.__wrapped__()

    payload = state["inserted_payload"]
    assert response.status_code == 302
    assert payload["_status_entered_at"]
    assert isinstance(payload.get("_status_history"), list)
    assert payload["_status_history"][-1]["status"] == "Draft"
    assert payload["_status_history"][-1]["changed_by"] == "status.user"


def test_update_appends_history_when_status_changes(monkeypatch):
    state = {
        "existing": {
            "AGREEMENT_AUTHOR": "initial.creator",
            "STATUS": "Draft",
            "COMMENTS": "before",
            "_created_at": "2026-06-01",
            "_status_entered_at": "2026-06-01T12:00:00Z",
            "_status_history": [
                {
                    "status": "Draft",
                    "changed_at": "2026-06-01T12:00:00Z",
                    "changed_by": "initial.creator",
                }
            ],
            "_attachments": [],
        },
        "updated_payload": None,
    }

    @contextmanager
    def _db_cursor_capture_update_status():
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

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups_with_status)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_capture_update_status)
    monkeypatch.setattr(app_module, "save_attachments", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "_current_submission_author", lambda: "status.editor")

    with app_module.app.test_request_context(
        "/update/7",
        method="POST",
        data={"STATUS": "Active", "COMMENTS": "after"},
    ):
        response = app_module.update.__wrapped__(7)

    payload = state["updated_payload"]
    assert response.status_code == 302
    assert payload["_status_entered_at"] != "2026-06-01T12:00:00Z"
    assert payload["_status_history"][0]["status"] == "Draft"
    assert payload["_status_history"][-1]["status"] == "Active"
    assert payload["_status_history"][-1]["changed_by"] == "status.editor"
