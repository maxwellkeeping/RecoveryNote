#!/usr/bin/env python
"""Merge an exported lookup JSON payload into DB-backed lookup_configs.

This tool is intended for one-time and repeatable reconciliation when
production/staging lookup files have diverged before DB-backed lookup storage
is fully rolled out.

By default this runs in dry-run mode and prints a merge summary.
Use --apply to persist changes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app as app_module


def _load_json_payload(path: str) -> dict[str, Any]:
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    with source_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("Source JSON must be an object at the top level")
    return payload


def _ensure_lookup_table() -> None:
    with app_module.db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lookup_configs (
                name        VARCHAR(100) PRIMARY KEY,
                payload     JSONB NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _fetch_existing_payload(config_name: str) -> dict[str, Any]:
    with app_module.db_cursor() as cur:
        cur.execute(
            "SELECT payload FROM lookup_configs WHERE name = %s",
            (config_name,),
        )
        row = cur.fetchone()

    if row is None:
        return {}

    payload = row[0]
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _upsert_payload(config_name: str, payload: dict[str, Any]) -> None:
    with app_module.db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO lookup_configs (name, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (name)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
            """,
            (config_name, app_module.psycopg2.extras.Json(payload)),
        )


def _lookup_key_count(payload: dict[str, Any]) -> int:
    return sum(1 for k in payload if not str(k).startswith("_"))


def _norm(value: Any) -> str:
    return app_module._norm_label(value)


def _count_list_additions(existing: list[Any], merged: list[Any]) -> int:
    seen = {_norm(v) for v in existing if _norm(v)}
    added = 0
    for item in merged:
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            added += 1
    return added


def _summarize_merge(
    existing: dict[str, Any], source: dict[str, Any], merged: dict[str, Any]
) -> dict[str, Any]:
    added_lookup_keys = sorted(
        k for k in merged.keys() if k not in existing and not str(k).startswith("_")
    )
    added_metadata_keys = sorted(
        k for k in merged.keys() if k not in existing and str(k).startswith("_")
    )

    list_options_added = 0
    cascade_parents_added = 0
    cascade_children_added = 0
    inactive_values_added = 0
    cascade_field_links_added = 0

    for key, merged_value in merged.items():
        existing_value = existing.get(key)

        if key == "_cascade_fields":
            if isinstance(merged_value, dict):
                if isinstance(existing_value, dict):
                    for child in merged_value.keys():
                        if child not in existing_value:
                            cascade_field_links_added += 1
                else:
                    cascade_field_links_added += len(merged_value)
            continue

        if key == "_inactive":
            if isinstance(merged_value, dict):
                existing_inactive = existing_value if isinstance(existing_value, dict) else {}
                for state_key, merged_state_values in merged_value.items():
                    current_state_values = existing_inactive.get(state_key)
                    if isinstance(merged_state_values, list) and isinstance(
                        current_state_values, list
                    ):
                        inactive_values_added += _count_list_additions(
                            current_state_values, merged_state_values
                        )
                    elif isinstance(merged_state_values, list):
                        inactive_values_added += len(merged_state_values)
            continue

        if str(key).startswith("_"):
            continue

        if isinstance(merged_value, list) and isinstance(existing_value, list):
            list_options_added += _count_list_additions(existing_value, merged_value)
            continue

        if isinstance(merged_value, dict):
            if not isinstance(existing_value, dict):
                cascade_parents_added += len(merged_value)
                for children in merged_value.values():
                    if isinstance(children, list):
                        cascade_children_added += len(children)
                continue

            for parent, merged_children in merged_value.items():
                existing_children = existing_value.get(parent)
                if parent not in existing_value:
                    cascade_parents_added += 1
                    if isinstance(merged_children, list):
                        cascade_children_added += len(merged_children)
                    continue
                if isinstance(merged_children, list) and isinstance(existing_children, list):
                    cascade_children_added += _count_list_additions(
                        existing_children, merged_children
                    )

    return {
        "existing_lookup_keys": _lookup_key_count(existing),
        "source_lookup_keys": _lookup_key_count(source),
        "merged_lookup_keys": _lookup_key_count(merged),
        "added_lookup_keys": added_lookup_keys,
        "added_metadata_keys": added_metadata_keys,
        "list_options_added": list_options_added,
        "cascade_parents_added": cascade_parents_added,
        "cascade_children_added": cascade_children_added,
        "inactive_values_added": inactive_values_added,
        "cascade_field_links_added": cascade_field_links_added,
        "changed": merged != existing,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("Merge summary")
    print("-------------")
    print(f"Existing lookup keys: {summary['existing_lookup_keys']}")
    print(f"Source lookup keys:   {summary['source_lookup_keys']}")
    print(f"Merged lookup keys:   {summary['merged_lookup_keys']}")
    print(f"List options added:   {summary['list_options_added']}")
    print(f"Cascade parents added:{summary['cascade_parents_added']}")
    print(f"Cascade children add: {summary['cascade_children_added']}")
    print(f"Inactive values added:{summary['inactive_values_added']}")
    print(f"Cascade links added:  {summary['cascade_field_links_added']}")

    added_lookup_keys = summary.get("added_lookup_keys", [])
    if added_lookup_keys:
        print("Added lookup keys:")
        for key in added_lookup_keys:
            print(f"  - {key}")

    added_metadata_keys = summary.get("added_metadata_keys", [])
    if added_metadata_keys:
        print("Added metadata keys:")
        for key in added_metadata_keys:
            print(f"  - {key}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a lookup JSON export into PostgreSQL lookup_configs. "
            "Defaults to dry-run; use --apply to persist changes."
        )
    )
    parser.add_argument(
        "source_json",
        help="Path to source JSON file (for example, exported prod field_lookups.json)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist merged payload into lookup_configs",
    )
    parser.add_argument(
        "--config-name",
        default=app_module.LOOKUP_CONFIG_NAME,
        help=f"lookup_configs name key (default: {app_module.LOOKUP_CONFIG_NAME})",
    )
    parser.add_argument(
        "--db-url",
        default="",
        help="Override DATABASE_URL for this command",
    )
    parser.add_argument(
        "--write-merged-json",
        default="",
        help="Optional output path to write merged JSON payload",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    dsn = os.environ.get("DATABASE_URL") or app_module.DATABASE_URL
    if not dsn:
        print("ERROR: DATABASE_URL is required (env var or --db-url).", file=sys.stderr)
        return 2

    source_payload = _load_json_payload(args.source_json)
    _ensure_lookup_table()
    existing_payload = _fetch_existing_payload(args.config_name)
    merged_payload = app_module._merge_lookup_payload(existing_payload, source_payload)

    summary = _summarize_merge(existing_payload, source_payload, merged_payload)
    _print_summary(summary)

    if args.write_merged_json:
        out_path = Path(args.write_merged_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(merged_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote merged payload to {out_path}")

    if not summary["changed"]:
        print("No changes detected; database payload already includes source values.")
        return 0

    if not args.apply:
        print("Dry run complete. Re-run with --apply to persist merged values.")
        return 0

    _upsert_payload(args.config_name, merged_payload)
    print("Merged payload saved to lookup_configs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
