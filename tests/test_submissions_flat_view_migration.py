from contextlib import contextmanager

import app as app_module


class _CursorStub:
    def __init__(self, queries):
        self._queries = queries
        self._last_query = ""

    def execute(self, query, params=None):
        self._last_query = query
        self._queries.append(query)

    def fetchone(self):
        query_lower = self._last_query.lower()
        if "select 1 from lookup_configs" in query_lower:
            # Skip JSON bootstrap insert path in this unit test.
            return (1,)
        if "select count(*) from users" in query_lower:
            # Skip default user seed path in this unit test.
            return (1,)
        return None


@contextmanager
def _fake_db_cursor(queries):
    yield _CursorStub(queries)


def test_submissions_flat_view_appends_status_columns(monkeypatch):
    queries = []

    monkeypatch.setattr(app_module, "db_cursor", lambda: _fake_db_cursor(queries))

    app_module.init_db()

    view_sql = next(
        q for q in queries if "CREATE OR REPLACE VIEW submissions_flat" in q
    )

    client_pos = view_sql.find("AS client_contact_name")
    comments_pos = view_sql.find("AS comments")
    entered_pos = view_sql.find("AS status_entered_at")
    history_pos = view_sql.find("AS status_history")

    assert client_pos != -1
    assert comments_pos != -1
    assert entered_pos != -1
    assert history_pos != -1
    assert client_pos < comments_pos < entered_pos < history_pos
