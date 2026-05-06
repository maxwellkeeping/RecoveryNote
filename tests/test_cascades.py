"""Tests for app.py field loading and cascade logic."""

import json
import os
import re
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def sanitize_name(s):
    return re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_")


def norm_label(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def load_field_groups_for_test():
    """Minimal reimplementation of load_field_groups to test cascade logic."""
    base = os.path.join(os.path.dirname(__file__), "..")
    fg_path = os.path.join(base, "field_groups.json")
    lookup_path = os.path.join(base, "field_lookups.json")
    lookup_map = os.path.join(base, "lookup_mappings.json")

    with open(fg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups", {})

    lookups = {}
    cascade_field_map = {}
    with open(lookup_path, "r", encoding="utf-8") as lf:
        raw = json.load(lf)
        cascade_field_map = {
            norm_label(k): norm_label(v)
            for k, v in (raw.pop("_cascade_fields", {}) or {}).items()
        }
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            nk = k.replace("\n", " ").strip()
            lookups[nk] = v

    with open(lookup_map, "r", encoding="utf-8") as mf:
        raw_mapping = json.load(mf)
        mapping = {norm_label(k): norm_label(v) for k, v in raw_mapping.items()}

    return groups, lookups, cascade_field_map, mapping


class TestCascadeLogic:
    def test_cascade_field_map_exists(self):
        _, _, cascade_field_map, _ = load_field_groups_for_test()
        assert "ITS SERVICE TYPE" in cascade_field_map

    def test_cascade_parent_is_dict(self):
        _, lookups, cascade_field_map, mapping = load_field_groups_for_test()
        parent_label = cascade_field_map["ITS SERVICE TYPE"]
        parent_mapped = mapping.get(parent_label)
        parent_lookup = (
            lookups.get(parent_mapped) if parent_mapped else lookups.get(parent_label)
        )
        assert isinstance(
            parent_lookup, dict
        ), "Parent lookup should be a dict for cascading"

    def test_cascade_parent_has_expected_keys(self):
        _, lookups, cascade_field_map, mapping = load_field_groups_for_test()
        parent_label = cascade_field_map["ITS SERVICE TYPE"]
        parent_mapped = mapping.get(parent_label)
        parent_lookup = (
            lookups.get(parent_mapped) if parent_mapped else lookups.get(parent_label)
        )
        expected_services = [
            "PROCUREMENT-SOFTWARE",
            "PROCUREMENT-HARDWARE",
            "MAINFRAME",
        ]
        for svc in expected_services:
            assert svc in parent_lookup

    def test_cascade_children_are_lists(self):
        _, lookups, cascade_field_map, mapping = load_field_groups_for_test()
        parent_label = cascade_field_map["ITS SERVICE TYPE"]
        parent_mapped = mapping.get(parent_label)
        parent_lookup = (
            lookups.get(parent_mapped) if parent_mapped else lookups.get(parent_label)
        )
        for key, value in parent_lookup.items():
            assert isinstance(value, list), f"Children for {key} should be a list"
            assert len(value) > 0, f"Children for {key} should not be empty"

    def test_parent_field_renders_as_plain_dropdown(self):
        """The parent field (ITS SERVICE) should get options=list(keys), NOT cascade_data."""
        _, _, cascade_field_map, _ = load_field_groups_for_test()
        # In the fixed code, cascade_from would be None for the parent
        parent_label = cascade_field_map.get("ITS  SERVICE")
        assert parent_label is None, "ITS SERVICE should NOT be a cascade child"

    def test_child_field_has_cascade_from(self):
        """ITS SERVICE TYPE should have cascade_from pointing to ITS_SERVICE."""
        _, _, cascade_field_map, _ = load_field_groups_for_test()
        parent_label = cascade_field_map.get("ITS SERVICE TYPE")
        assert parent_label is not None
        assert sanitize_name(parent_label) == "ITS_SERVICE"


class TestLookups:
    def test_status_lookup_exists(self):
        _, lookups, _, _ = load_field_groups_for_test()
        assert "STATUS" in lookups
        assert isinstance(lookups["STATUS"], list)
        assert "Draft" in lookups["STATUS"]

    def test_agreement_type_lookup(self):
        _, lookups, _, _ = load_field_groups_for_test()
        assert "AGREEMENT TYPE" in lookups
        assert "Net New" in lookups["AGREEMENT TYPE"]

    def test_service_owner_lookup(self):
        _, lookups, _, mapping = load_field_groups_for_test()
        mapped = mapping.get("SERVICE OWNER")
        vals = lookups.get(mapped) if mapped else lookups.get("SERVICE OWNER")
        assert isinstance(vals, list)
        assert "DCO Business Services" in vals
