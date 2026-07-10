import csv
import io
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import app as app_module


def _minimal_groups():
    return [("Agreement", [{"name": "STATUS"}, {"name": "AGREEMENT_AUTHOR"}])]


def test_export_csv_includes_status_tracking_columns(monkeypatch):
    entered_at = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0)
    entered_at_text = entered_at.isoformat().replace("+00:00", "Z")

    rows = [
        (
            1,
            datetime(2026, 7, 2).date(),
            {
                "STATUS": "Draft",
                "AGREEMENT_AUTHOR": "author.user@ontario.ca",
                "_status_entered_at": entered_at_text,
                "_status_history": [
                    {
                        "status": "Draft",
                        "changed_at": entered_at_text,
                        "changed_by": "author.user@ontario.ca",
                    },
                    {
                        "status": "Pending",
                        "changed_at": entered_at_text,
                        "changed_by": "another.user@ontario.ca",
                    }
                ],
            },
        )
    ]

    @contextmanager
    def _db_cursor_rows():
        class Cursor:
            def execute(self, query, params=None):
                self.query = query

            def fetchall(self):
                return rows

        yield Cursor()

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_rows)

    with app_module.app.test_request_context("/export/csv"):
        response = app_module.export_csv.__wrapped__()

    text = response.get_data(as_text=True)
    reader = csv.DictReader(io.StringIO(text))
    exported = list(reader)

    assert response.status_code == 200
    assert "current_status_entered_at" in reader.fieldnames
    assert "status_history_json" in reader.fieldnames
    assert "status_transition_path" in reader.fieldnames
    assert "days_in_current_status" in reader.fieldnames
    assert exported[0]["current_status_entered_at"] == entered_at_text
    assert '"status": "Draft"' in exported[0]["status_history_json"]
    assert '"changed_by"' not in exported[0]["status_history_json"]
    assert exported[0]["status_transition_path"] == "Draft -> Pending"
    assert exported[0]["days_in_current_status"] == "3"


def test_export_csv_leaves_status_columns_empty_when_untracked(monkeypatch):
    rows = [
        (
            2,
            datetime(2026, 7, 2).date(),
            {"STATUS": "", "AGREEMENT_AUTHOR": "a"},
        )
    ]

    @contextmanager
    def _db_cursor_rows():
        class Cursor:
            def execute(self, query, params=None):
                self.query = query

            def fetchall(self):
                return rows

        yield Cursor()

    monkeypatch.setattr(app_module, "load_field_groups", _minimal_groups)
    monkeypatch.setattr(app_module, "db_cursor", _db_cursor_rows)

    with app_module.app.test_request_context("/export/csv"):
        response = app_module.export_csv.__wrapped__()

    text = response.get_data(as_text=True)
    reader = csv.DictReader(io.StringIO(text))
    exported = list(reader)

    assert exported[0]["current_status_entered_at"] == ""
    assert exported[0]["status_history_json"] == ""
    assert exported[0]["status_transition_path"] == ""
    assert exported[0]["days_in_current_status"] == ""
