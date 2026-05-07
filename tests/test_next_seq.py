from contextlib import contextmanager

import app as app_module


@contextmanager
def _cursor_with_rows(rows):
    class Cursor:
        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchall(self):
            return rows

    yield Cursor()


def test_next_seq_scoped_by_cluster_and_fy(monkeypatch):
    rows = [
        ("CAC-20260401-RN10027001",),
        ("CAC-20260402-RN10027002",),
        ("CAC-20260403-RN10028001",),
        ("CSC-20260401-RN20027077",),
    ]
    monkeypatch.setattr(app_module, "db_cursor", lambda: _cursor_with_rows(rows))

    client = app_module.app.test_client()
    response = client.get("/api/next-seq?cluster_abbr=CAC&cluster_num=100&fy=27")

    assert response.status_code == 200
    assert response.get_json()["seq"] == 3


def test_next_seq_expands_past_three_digits(monkeypatch):
    rows = [
        ("CAC-20260401-RN10027998",),
        ("CAC-20260402-RN10027999",),
    ]
    monkeypatch.setattr(app_module, "db_cursor", lambda: _cursor_with_rows(rows))

    client = app_module.app.test_client()
    response = client.get("/api/next-seq?cluster_abbr=CAC&cluster_num=100&fy=27")

    assert response.status_code == 200
    assert response.get_json()["seq"] == 1000


def test_next_seq_fallback_prefix_supports_variable_length(monkeypatch):
    rows = [
        ("CAC-20260401-RN10027999",),
        ("CAC-20260401-RN100271000",),
    ]
    monkeypatch.setattr(app_module, "db_cursor", lambda: _cursor_with_rows(rows))

    client = app_module.app.test_client()
    response = client.get("/api/next-seq?prefix=CAC-20260401-RN10027")

    assert response.status_code == 200
    assert response.get_json()["seq"] == 1001
