"""
Utility script to export openapi.json for frontend TypeScript type generation.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api.app import app


def export_openapi_json(output_path: str = "openapi.json"):
    schema = app.openapi()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    print(f"Exported OpenAPI schema to {os.path.abspath(output_path)}")


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    export_openapi_json(out_path)
