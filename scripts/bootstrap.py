#!/usr/bin/env python3
"""
bootstrap.py — orchestrator for the saiyo-lp-bootstrap skill.

Runs the Python pipeline end-to-end:
  1. crawl_reference.py on --primary-url       → content_bundle
  2. extract_design.py on --primary-url        → design_tokens
  3. (parallel: also extract_design on --style-url if given, merge tokens)
  4. compose_lpcontent.py with all of the above → lp_content (LpContent JSON)

Outputs ONE JSON object to stdout containing:
  {
    "slug":         "cloq",
    "client_name":  "株式会社CLOQ",
    "primary_url":  "https://cloq.jp/",
    "industry":     "製造業",
    "lp_content":   { ...full LpContent... },
    "content_bundle": { ... },
    "design_tokens": { ... },
    "provenance":   { ... }
  }

The Claude orchestration layer takes this output and:
  - Inserts into public.lps + public.lp_content via Supabase MCP
  - Optionally enhances images via nano-banana + uploads to lp-assets
  - Posts a status update + the final URL to the user

This script does NOT touch the database. It is a pure transformation:
URL → JSON.

Usage:
    python3 bootstrap.py \\
        --slug cloq \\
        --client-name "株式会社CLOQ" \\
        --primary-url https://cloq.jp/ \\
        --industry 製造業

Optional:
    --style-url   https://reference.com/   (only if you want to override design)
    --max-pages   8                         (cap on sub-pages to crawl)
    --preset-json /path/to/preset.json      (preset row from industry_presets)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", file=sys.stderr, flush=True)


def run_script(args: list[str], stdin: str | None = None) -> dict:
    """Run a sub-script and parse its stdout as JSON. Stderr passes through."""
    log(f"  running: {' '.join(args[:3])} ...")
    try:
        proc = subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT after 120s: {args}")
        return {"_error": "timeout"}

    # Stderr from sub-script → forward to our stderr so the user sees it
    if proc.stderr:
        for line in proc.stderr.splitlines():
            print(line, file=sys.stderr, flush=True)

    if proc.returncode != 0:
        log(f"  exit code {proc.returncode}")
        return {"_error": f"exit_code_{proc.returncode}", "stderr": proc.stderr[:500]}

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        log(f"  JSON parse error: {e}")
        return {"_error": "json_decode", "raw": proc.stdout[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap an LpContent JSON from a client URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--slug", required=True, help="Lowercase slug for the LP, e.g. 'cloq'")
    parser.add_argument("--client-name", required=True, help="株式会社X")
    parser.add_argument("--primary-url", required=True, help="Client's main website URL")
    parser.add_argument("--style-url", help="Optional design reference URL")
    parser.add_argument("--industry", default="", help="e.g. 製造業 (used to look up preset)")
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--preset-json", help="Path to a JSON file with the preset row")
    args = parser.parse_args()

    log(f"Bootstrapping slug={args.slug} client={args.client_name!r} url={args.primary_url}")

    crawl_path = os.path.join(SCRIPT_DIR, "crawl_reference.py")
    design_path = os.path.join(SCRIPT_DIR, "extract_design.py")
    compose_path = os.path.join(SCRIPT_DIR, "compose_lpcontent.py")

    # Run crawl + design extraction in parallel
    log("Step 1+2: parallel crawl + design extraction")
    with ThreadPoolExecutor(max_workers=2) as ex:
        future_crawl = ex.submit(
            run_script,
            ["python3", crawl_path, args.primary_url, "--max-pages", str(args.max_pages)],
        )
        future_design = ex.submit(
            run_script,
            ["python3", design_path, args.primary_url],
        )
        content_bundle = future_crawl.result()
        design_tokens = future_design.result()

    if "_error" in content_bundle:
        log(f"FATAL: crawl failed → {content_bundle.get('_error')}")
        print(json.dumps({"_error": "crawl_failed", "detail": content_bundle}, ensure_ascii=False))
        return 1
    if "_error" in design_tokens:
        log(f"WARN: design extraction failed → {design_tokens.get('_error')}, using defaults")
        design_tokens = {"colors": {}, "source": "fallback_default"}

    # Optional: also extract design from --style-url and merge colors
    if args.style_url:
        log(f"Step 2b: also extracting design from style-url {args.style_url}")
        style_design = run_script(["python3", design_path, args.style_url])
        if "_error" not in style_design and style_design.get("colors"):
            log("  merging style-url colors into design_tokens")
            design_tokens["colors"] = style_design["colors"]
            design_tokens["color_frequencies"] = style_design.get("color_frequencies")
            design_tokens["primary_font"] = style_design.get("primary_font") or design_tokens.get("primary_font")
            design_tokens["source"] = "style_url_override"

    # Load preset
    preset: dict = {}
    if args.preset_json and os.path.exists(args.preset_json):
        with open(args.preset_json) as f:
            preset = json.load(f)
        log(f"Step 3: loaded preset from {args.preset_json}")
    else:
        log(f"Step 3: no preset file given (industry={args.industry!r}); composer will use defaults")

    # Compose
    log("Step 4: composing LpContent")
    compose_input = json.dumps({
        "slug": args.slug,
        "client_name": args.client_name,
        "primary_url": args.primary_url,
        "industry": args.industry,
        "content_bundle": content_bundle,
        "design_tokens": design_tokens,
        "preset": preset,
    }, ensure_ascii=False)

    composed = run_script(["python3", compose_path], stdin=compose_input)
    if "_error" in composed:
        log(f"FATAL: compose failed → {composed.get('_error')}")
        print(json.dumps({"_error": "compose_failed", "detail": composed}, ensure_ascii=False))
        return 1

    # Final output
    output = {
        "slug": args.slug,
        "client_name": args.client_name,
        "primary_url": args.primary_url,
        "industry": args.industry,
        "lp_content": composed["lp_content"],
        "content_bundle": content_bundle,
        "design_tokens": design_tokens,
        "provenance": composed["provenance"],
    }

    log("Done. Final LpContent ready for upsert.")
    log(f"  provenance: {composed['provenance']}")

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
