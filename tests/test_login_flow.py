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


def test_auth_login_redirects_to_local_when_sso_not_configured(monkeypatch):
    monkeypatch.setattr(app_module, "_db_initialized", True)
    monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
    monkeypatch.delenv("ENTRA_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)

    client = app_module.app.test_client()
    response = client.get("/auth/login", follow_redirects=True)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Microsoft sign-in is not configured" in body


def test_allowed_groups_match(monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_GROUP_IDS", "group-a, group-b")
    claims = {"groups": ["group-x", "group-b"]}
    assert app_module._is_user_in_allowed_groups(claims)


def test_allowed_groups_deny(monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_GROUP_IDS", "group-a, group-b")
    claims = {"groups": ["group-x", "group-y"]}
    assert not app_module._is_user_in_allowed_groups(claims)


def test_allowed_groups_match_via_graph_on_overage(monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_GROUP_IDS", "group-a, group-b")
    monkeypatch.setattr(
        app_module,
        "_fetch_user_group_ids_from_graph",
        lambda token: {"group-b"},
    )
    claims = {"_claim_names": {"groups": "src1"}}
    assert app_module._is_user_in_allowed_groups(claims, "fake-token")


def test_allowed_groups_overage_without_match_denied(monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_GROUP_IDS", "group-a, group-b")
    monkeypatch.setattr(
        app_module,
        "_fetch_user_group_ids_from_graph",
        lambda token: {"group-x"},
    )
    claims = {"hasgroups": True}
    assert not app_module._is_user_in_allowed_groups(claims, "fake-token")


def test_allowed_groups_overage_graph_failure_raises(monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_GROUP_IDS", "group-a, group-b")
    monkeypatch.setattr(
        app_module,
        "_fetch_user_group_ids_from_graph",
        lambda token: None,
    )
    claims = {"hasgroups": True}
    try:
        app_module._is_user_in_allowed_groups(claims, "fake-token")
        assert False, "Expected PermissionError"
    except PermissionError as e:
        assert "Graph permissions" in str(e)


def test_entra_scopes_default_and_override(monkeypatch):
    monkeypatch.delenv("ENTRA_SCOPES", raising=False)
    assert app_module._entra_scopes() == "openid profile email User.Read"

    monkeypatch.setenv("ENTRA_SCOPES", "openid profile email User.Read GroupMember.Read.All")
    assert app_module._entra_scopes() == "openid profile email User.Read GroupMember.Read.All"
