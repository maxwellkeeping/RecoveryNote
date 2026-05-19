from contextlib import contextmanager

import app as app_module


@contextmanager
def _db_cursor_for_admin_reset():
    if not hasattr(_db_cursor_for_admin_reset, "state"):
        _db_cursor_for_admin_reset.state = {}
    state = _db_cursor_for_admin_reset.state

    class Cursor:
        def __init__(self):
            self._fetchone = None
            self._fetchall = []

        def execute(self, query, params=None):
            q = " ".join(query.split())
            if q.startswith(
                "SELECT id, username, password, role, must_change_password FROM users WHERE username = %s"
            ):
                self._fetchone = (1, "admin", state["admin_hash"], "admin", False)
                return
            if q.startswith(
                "SELECT id, username, role, must_change_password FROM users WHERE id = %s"
            ):
                user_id = int(params[0])
                if user_id == 1:
                    self._fetchone = (1, "admin", "admin", False)
                elif user_id == 2:
                    self._fetchone = (2, "user", "user", True)
                else:
                    self._fetchone = None
                return
            if q.startswith(
                "SELECT username FROM users WHERE id = %s"
            ):
                user_id = int(params[0])
                if user_id == 2:
                    self._fetchone = ("user",)
                else:
                    self._fetchone = None
                return
            if q.startswith(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL"
            ):
                return
            if q.startswith("INSERT INTO password_reset_tokens (user_id, token, expires_at)"):
                user_id = int(params[0])
                token = params[1]
                state["token_by_user"][user_id] = token
                state["token_used"][token] = False
                return
            if q.startswith("SELECT prt.id, prt.user_id FROM password_reset_tokens prt"):
                token = params[0]
                if token in state["token_used"] and not state["token_used"][token]:
                    user_id = None
                    for uid, saved_token in state["token_by_user"].items():
                        if saved_token == token:
                            user_id = uid
                            break
                    self._fetchone = (101, user_id) if user_id else None
                else:
                    self._fetchone = None
                return
            if q.startswith(
                "UPDATE users SET password = %s, must_change_password = FALSE WHERE id = %s"
            ):
                state["updated_hash"] = params[0]
                return
            if q.startswith("UPDATE password_reset_tokens SET used_at = NOW() WHERE id = %s"):
                token_id = int(params[0])
                if token_id == 101:
                    # This mock uses a single id for active tokens.
                    for token in list(state["token_used"].keys()):
                        if not state["token_used"][token]:
                            state["token_used"][token] = True
                            break
                return
            if q.startswith("SELECT id, username, role FROM users ORDER BY username"):
                self._fetchall = [(1, "admin", "admin"), (2, "user", "user")]
                return
            raise AssertionError(f"Unexpected SQL: {q}")

        def fetchone(self):
            return self._fetchone

        def fetchall(self):
            return self._fetchall

    yield Cursor()


def _login_admin(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_admin_can_reset_other_user_password(monkeypatch):
    _db_cursor_for_admin_reset.state = {
        "admin_hash": app_module.hash_password("admin123"),
        "token_by_user": {},
        "token_used": {},
        "updated_hash": None,
    }
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_for_admin_reset)
    monkeypatch.setattr(app_module, "_generate_reset_token", lambda: "reset-token-abc")

    client = app_module.app.test_client()
    _login_admin(client)

    response = client.post("/admin/users/reset/2", follow_redirects=True)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Password reset link created for" in body
    assert "Copy Reset Link" in body
    assert "Link generated for" in body
    assert "/reset-password/reset-token-abc" in body
    assert _db_cursor_for_admin_reset.state["token_by_user"][2] == "reset-token-abc"


def test_admin_cannot_reset_own_password_from_admin_page(monkeypatch):
    _db_cursor_for_admin_reset.state = {
        "admin_hash": app_module.hash_password("admin123"),
        "token_by_user": {},
        "token_used": {},
        "updated_hash": None,
    }
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_for_admin_reset)

    client = app_module.app.test_client()
    _login_admin(client)

    response = client.post("/admin/users/reset/1", follow_redirects=True)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "You cannot reset your own password from this page." in body


def test_user_can_complete_reset_with_valid_token(monkeypatch):
    _db_cursor_for_admin_reset.state = {
        "admin_hash": app_module.hash_password("admin123"),
        "token_by_user": {2: "valid-reset-token"},
        "token_used": {"valid-reset-token": False},
        "updated_hash": None,
    }
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_for_admin_reset)

    client = app_module.app.test_client()
    response = client.post(
        "/reset-password/valid-reset-token",
        data={"new_password": "newpass123", "confirm_password": "newpass123"},
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Password reset successfully" in body
    updated_hash = _db_cursor_for_admin_reset.state["updated_hash"]
    assert updated_hash
    assert app_module.verify_password(updated_hash, "newpass123")
