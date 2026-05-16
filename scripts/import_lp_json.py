#!/usr/bin/env python3
"""Import an LP bootstrap manifest through the protected app API."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from lp_manifest_schema import load_json_file, validate_manifest

DEFAULT_BASE_URL = "https://nippo-sync.vercel.app"
USER_AGENT = "Mozilla/5.0 (compatible; mgc-saiyo-lp-bootstrap/1.0; +https://nippo-sync.vercel.app)"


def post_json(url: str, body: dict, secret: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-migration-secret": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"error": raw}
        result["_http_status"] = e.code
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply an LP bootstrap manifest.")
    parser.add_argument("file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--mode", choices=["create", "update", "upsert"], default="upsert")
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--base-url", default=os.environ.get("LP_BOOTSTRAP_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--secret", default=os.environ.get("MIGRATION_RUNNER_SECRET"))
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and args.dry_run:
        print("Choose either --dry-run or --apply, not both", file=sys.stderr)
        return 2
    if not args.secret:
        print("MIGRATION_RUNNER_SECRET is required", file=sys.stderr)
        return 2

    manifest = load_json_file(args.file)
    validation = validate_manifest(
        manifest,
        strict=True,
        for_apply=args.apply,
        allow_unreviewed=args.allow_unreviewed,
    )
    if validation["errors"]:
        print(json.dumps({"ok": False, "stage": "local_validation", **validation}, ensure_ascii=False, indent=2))
        return 1
    if args.apply and validation["warnings"]:
        print(json.dumps({"ok": False, "stage": "local_validation", "message": "warnings block apply; fix them or use a narrower approved override later", **validation}, ensure_ascii=False, indent=2))
        return 1

    url = f"{args.base_url.rstrip('/')}/api/admin/lp-bootstrap-import"
    result = post_json(
        url,
        {
            "manifest": manifest,
            "dry_run": args.dry_run,
            "apply": args.apply,
            "overwrite": args.overwrite,
            "mode": args.mode,
        },
        args.secret,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
