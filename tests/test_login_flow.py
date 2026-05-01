from contextlib import contextmanager

import app as app_module


@contextmanager
def _db_down_cursor():
    raise RuntimeError("database unavailable")
    yield


def test_login_shows_db_error_message(monkeypatch):
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.setattr(app_module, "db_cursor", _db_down_cursor)

    client = app_module.app.test_client()
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Login is temporarily unavailable" in body


@contextmanager
def _db_login_row_cursor():
    class Cursor:
        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchone(self):
            return (1, "admin", app_module.hash_password("admin123"), "admin", True)

    yield Cursor()


def test_login_redirects_to_change_password(monkeypatch):
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.setattr(app_module, "db_cursor", _db_login_row_cursor)

    client = app_module.app.test_client()
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/change-password")
