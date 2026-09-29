"""Load the Genie space config and emit `manage_genie create_or_update` arguments.

Genie spaces are NOT a Databricks Asset Bundle resource, so this slice lives outside
resources/. This script is the reproducible loader: it validates
genie/hotel_booking_space.yaml and prints the exact arguments to pass to the
`manage_genie` MCP tool (action=create_or_update). It is intentionally NOT a REST
client -- space creation runs through the workspace-scoped manage_genie MCP tool, and
general instructions + curated SQL examples are applied in the Genie UI (the
create_or_update surface does not expose them) then captured by
`manage_genie action=export` into hotel_booking_space.serialized.json.

Usage:
    python genie/build_space.py [--config genie/hotel_booking_space.yaml]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

REQUIRED_KEYS = ("display_name", "table_identifiers", "description", "sample_questions")


def load_config(path: pathlib.Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        raise SystemExit(f"config missing required keys: {missing}")
    tables = cfg["table_identifiers"]
    if not isinstance(tables, list) or not tables:
        raise SystemExit("table_identifiers must be a non-empty list")
    for t in tables:
        if t.count(".") != 2:
            raise SystemExit(f"table identifier not fully qualified (catalog.schema.table): {t}")
    return cfg


def create_or_update_args(cfg: dict) -> dict:
    args = {
        "action": "create_or_update",
        "display_name": cfg["display_name"],
        "table_identifiers": cfg["table_identifiers"],
        "description": " ".join(cfg["description"].split()),
        "sample_questions": cfg["sample_questions"],
    }
    if cfg.get("warehouse_id"):
        args["warehouse_id"] = cfg["warehouse_id"]
    return args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="genie/hotel_booking_space.yaml")
    ns = ap.parse_args()
    cfg = load_config(pathlib.Path(ns.config))
    print(json.dumps(create_or_update_args(cfg), indent=2))
    print(
        "\n# Next steps (orchestrator, via MCP + Genie UI):\n"
        "#  1. Pass the JSON above to manage_genie (action=create_or_update).\n"
        "#  2. In the Genie UI, add the `instructions` text and each `curated_sql`\n"
        "#     example from the config as general instructions / example queries.\n"
        "#  3. Run manage_genie action=export -> genie/hotel_booking_space.serialized.json",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
