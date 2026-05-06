"""Unit tests for copy preparation and lookup active/inactive filtering."""

import json

import app as app_module


def test_prepare_copy_values_resets_fields_and_sets_draft():
    source = {
        "AGREEMENT_ID": "CAC-20260501-RN26001001",
        "STATUS": "Active",
        "END_DATE_YYYY_MM_DD": "2027-03-31",
        "TERMINATION_REASON": "Expired",
        "COMMENTS": "Keep this context.",
        "_created_at": "2026-05-01",
        "_attachments": [{"name": "a.txt", "stored": "a.txt"}],
    }

    copied = app_module.prepare_copy_values(source)

    assert copied.get("AGREEMENT_ID") is None
    assert copied.get("_created_at") is None
    assert copied.get("_attachments") is None
    assert copied["STATUS"] == "Draft"
    assert copied["PREVIOUS_AGREEMENT"] == "CAC-20260501-RN26001001"
    assert copied["END_DATE_YYYY_MM_DD"] == ""
    assert copied["TERMINATION_REASON"] == ""
    assert copied["COMMENTS"] == "Keep this context."


def test_prepare_copy_values_uses_configured_copy_clear_fields(tmp_path, monkeypatch):
    fg_path = tmp_path / "field_groups.json"
    fg_path.write_text(
        json.dumps({"copy_clear_fields": ["COMMENTS", "END DATE (YYYY-MM-DD)"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "FG_PATH", str(fg_path))

    source = {
        "AGREEMENT_ID": "A-1",
        "COMMENTS": "This should clear",
        "END_DATE_YYYY_MM_DD": "2027-03-31",
        "TERMINATION_REASON": "Should stay because not configured",
    }

    copied = app_module.prepare_copy_values(source)

    assert copied["COMMENTS"] == ""
    assert copied["END_DATE_YYYY_MM_DD"] == ""
    assert copied["TERMINATION_REASON"] == "Should stay because not configured"


def test_get_copy_clear_fields_falls_back_to_default_when_missing_config(tmp_path, monkeypatch):
    fg_path = tmp_path / "field_groups.json"
    fg_path.write_text(json.dumps({"headers": []}), encoding="utf-8")
    monkeypatch.setattr(app_module, "FG_PATH", str(fg_path))

    fields = app_module.get_copy_clear_fields()

    assert "END_DATE_YYYY_MM_DD" in fields
    assert "TERMINATION_REASON" in fields


def test_active_lookup_value_filters_simple_list():
    lookup_val = ["Draft", "Active", "Closed"]
    inactive_map = {"STATUS": ["Closed"]}

    active = app_module._active_lookup_value("STATUS", lookup_val, inactive_map)

    assert active == ["Draft", "Active"]


def test_active_lookup_value_filters_cascade_values():
    lookup_val = {
        "PROCUREMENT-SOFTWARE": ["SOFTWARE-ORACLE", "SOFTWARE-MS"],
        "MAINFRAME": ["MF-BASIC"],
    }
    inactive_map = {
        "SERVICE": ["MAINFRAME"],
        "SERVICE::PROCUREMENT-SOFTWARE": ["SOFTWARE-MS"],
    }

    active = app_module._active_lookup_value("SERVICE", lookup_val, inactive_map)

    assert "MAINFRAME" not in active
    assert active["PROCUREMENT-SOFTWARE"] == ["SOFTWARE-ORACLE"]


def test_map_lookups_save_mapping_post(tmp_path, monkeypatch):
    lookup_path = tmp_path / "field_lookups.json"
    mapping_path = tmp_path / "lookup_mappings.json"
    lookup_path.write_text(json.dumps({"STATUS": ["Draft", "Active"]}), encoding="utf-8")
    mapping_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(app_module, "LOOKUP_PATH", str(lookup_path))
    monkeypatch.setattr(app_module, "LOOKUP_MAP", str(mapping_path))
    monkeypatch.setattr(
        app_module,
        "load_field_groups",
        lambda: [("Agreement", [{"source_label": "STATUS"}])],
    )

    with app_module.app.test_request_context(
        "/map-lookups", method="POST", data={"_action": "save_mapping", "STATUS": "STATUS"}
    ):
        response = app_module.map_lookups.__wrapped__()

    assert response.status_code == 302
    saved = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert saved == {"STATUS": "STATUS"}


def test_map_lookups_hide_and_unhide_option(tmp_path, monkeypatch):
    lookup_path = tmp_path / "field_lookups.json"
    mapping_path = tmp_path / "lookup_mappings.json"
    lookup_path.write_text(json.dumps({"STATUS": ["Draft", "Active"]}), encoding="utf-8")
    mapping_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(app_module, "LOOKUP_PATH", str(lookup_path))
    monkeypatch.setattr(app_module, "LOOKUP_MAP", str(mapping_path))
    monkeypatch.setattr(
        app_module,
        "load_field_groups",
        lambda: [("Agreement", [{"source_label": "STATUS"}])],
    )

    with app_module.app.test_request_context(
        "/map-lookups",
        method="POST",
        data={"_action": "lookup_hide", "lookup_key": "STATUS", "lookup_value": "Active"},
    ):
        response = app_module.map_lookups.__wrapped__()
    assert response.status_code == 302
    hidden_cfg = json.loads(lookup_path.read_text(encoding="utf-8"))
    assert hidden_cfg["_inactive"]["STATUS"] == ["Active"]

    with app_module.app.test_request_context(
        "/map-lookups",
        method="POST",
        data={
            "_action": "lookup_unhide",
            "lookup_key": "STATUS",
            "lookup_value": "Active",
        },
    ):
        response = app_module.map_lookups.__wrapped__()
    assert response.status_code == 302
    unhidden_cfg = json.loads(lookup_path.read_text(encoding="utf-8"))
    assert "_inactive" not in unhidden_cfg or "STATUS" not in unhidden_cfg.get("_inactive", {})


def test_map_lookups_add_cascade_child_option(tmp_path, monkeypatch):
    lookup_path = tmp_path / "field_lookups.json"
    mapping_path = tmp_path / "lookup_mappings.json"
    lookup_path.write_text(
        json.dumps(
            {
                "SERVICE": {"PROCUREMENT-SOFTWARE": ["SOFTWARE-ORACLE"]},
                "_cascade_fields": {"ITS SERVICE TYPE": "ITS SERVICE"},
            }
        ),
        encoding="utf-8",
    )
    mapping_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(app_module, "LOOKUP_PATH", str(lookup_path))
    monkeypatch.setattr(app_module, "LOOKUP_MAP", str(mapping_path))
    monkeypatch.setattr(
        app_module,
        "load_field_groups",
        lambda: [("Service", [{"source_label": "ITS SERVICE TYPE"}])],
    )

    with app_module.app.test_request_context(
        "/map-lookups",
        method="POST",
        data={
            "_action": "lookup_add",
            "lookup_key": "SERVICE",
            "cascade_parent": "PROCUREMENT-SOFTWARE",
            "lookup_value": "SOFTWARE-NEW",
        },
    ):
        response = app_module.map_lookups.__wrapped__()

    assert response.status_code == 302
    cfg = json.loads(lookup_path.read_text(encoding="utf-8"))
    assert "SOFTWARE-NEW" in cfg["SERVICE"]["PROCUREMENT-SOFTWARE"]
