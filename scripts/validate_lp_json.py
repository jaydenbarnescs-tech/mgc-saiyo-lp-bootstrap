#!/usr/bin/env python3
"""Validate a recruitment LP bootstrap manifest."""
from __future__ import annotations

import argparse
import json
import sys
from json import JSONDecodeError

from lp_manifest_schema import load_json_file, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an LP bootstrap manifest JSON file.")
    parser.add_argument("file")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--for-apply", action="store_true", help="Validate requirements for production apply.")
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    args = parser.parse_args()

    try:
      data = load_json_file(args.file)
    except FileNotFoundError:
        result = {"ok": False, "errors": [{"path": args.file, "message": "file not found", "severity": "error"}], "warnings": []}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except JSONDecodeError as e:
        result = {"ok": False, "errors": [{"path": args.file, "message": f"invalid JSON: {e}", "severity": "error"}], "warnings": []}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result = validate_manifest(
        data,
        strict=args.strict,
        for_apply=args.for_apply,
        allow_unreviewed=args.allow_unreviewed,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"OK: {args.file}")
        else:
            print(f"FAILED: {args.file}")
        if result["errors"]:
            print("\nErrors:")
            for issue in result["errors"]:
                print(f"- {issue['path']}: {issue['message']}")
        if result["warnings"]:
            print("\nWarnings:")
            for issue in result["warnings"]:
                print(f"- {issue['path']}: {issue['message']}")

    if result["errors"]:
        return 1
    if args.strict and result["warnings"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
