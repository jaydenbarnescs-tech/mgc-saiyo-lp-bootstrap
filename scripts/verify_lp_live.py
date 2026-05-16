#!/usr/bin/env python3
"""Read-only verification for a published recruitment LP."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

DEFAULT_BASE_URL = "https://nippo-sync.vercel.app"
USER_AGENT = "Mozilla/5.0 (compatible; mgc-saiyo-lp-bootstrap/1.0; +https://nippo-sync.vercel.app)"


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            d = {k: v or "" for k, v in attrs}
            key = d.get("property") or d.get("name")
            if key:
                self.meta[key] = d.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def fetch(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, e.read().decode("utf-8", "replace")


def check(url: str, expected_status: int = 200, must_contain: str | None = None) -> dict:
    status, final_url, body = fetch(url)
    result = {"url": url, "final_url": final_url, "status": status, "ok": status == expected_status}
    if must_contain:
        result["contains"] = must_contain in body
        result["ok"] = bool(result["ok"] and result["contains"])
    return result | {"body": body[:5000]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live LP and related routes.")
    parser.add_argument("slug")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--client-name")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    args = parser.parse_args()

    base = f"{args.base_url.rstrip('/')}/lp/{args.slug}"
    checks = []
    home = check(base, 200, args.client_name)
    checks.append({k: v for k, v in home.items() if k != "body"})
    parser_html = TitleParser()
    parser_html.feed(home.get("body", ""))
    checks.append({
        "url": base,
        "check": "metadata",
        "ok": bool(parser_html.title and parser_html.title != "日報シンクロくん" and parser_html.meta.get("description")),
        "title": parser_html.title,
        "description": parser_html.meta.get("description", ""),
        "og_title": parser_html.meta.get("og:title", ""),
        "og_image": parser_html.meta.get("og:image", ""),
    })

    for i in range(max(args.jobs, 0)):
        job = check(f"{base}/jobs/{i}", 200)
        body = job.pop("body", "")
        job["has_jobposting_jsonld"] = '"JobPosting"' in body or "'JobPosting'" in body
        job["ok"] = bool(job["ok"] and job["has_jobposting_jsonld"])
        checks.append(job)

    entry = check(f"{base}/entry", 200)
    entry.pop("body", None)
    checks.append(entry)

    admin = check(f"{base}/admin?first", 200)
    admin_body = admin.pop("body", "")
    admin["not_not_found"] = "404" not in admin_body[:1000] and "Not Found" not in admin_body[:1000]
    admin["ok"] = bool(admin["ok"] and admin["not_not_found"])
    checks.append(admin)

    ok = all(c.get("ok") for c in checks)
    result = {"ok": ok, "slug": args.slug, "checks": checks}
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("OK" if ok else "FAILED")
        for c in checks:
            status = "ok" if c.get("ok") else "fail"
            print(f"- {status}: {c.get('check') or c.get('url')} {c.get('status', '')}".rstrip())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
