#!/usr/bin/env python3
"""
analytics_bootstrap.py — step 12.7 of the mgc-saiyo-lp-bootstrap pipeline.

Verifies that the analytics infrastructure is alive for a given LP slug and
emits SQL payloads for the calling LLM to apply via Supabase MCP.

Responsibilities (in order):
  1. Verify the tracking pixel is present in the production LP HTML
     (main LP, job detail /jobs/0, entry form). Exits non-zero if missing.
  2. Verify POST /api/lp/{slug}/track returns 204 Accepted for a
     synthetic page_view event. Exits non-zero if not 204.
  3. Emit the migration SQL to create lp_page_views + lp_form_events
     tables (idempotent CREATE TABLE IF NOT EXISTS) so the caller can
     apply it via Supabase MCP apply_migration if the verification
     step reports missing tables.
  4. Emit the seed SQL: 15 realistic lp_entries + ~3000 lp_page_views
     + ~800 form_view + ~280 form_start rows, all tagged with a
     fake-backfill user_agent so they can be bulk-deleted later.
  5. Print a JSON summary for the caller to parse.

Usage:
    python3 analytics_bootstrap.py --slug cloq
    python3 analytics_bootstrap.py --slug cloq --no-seed
    python3 analytics_bootstrap.py --slug cloq --verify-only
    python3 analytics_bootstrap.py --slug cloq --base-url https://nippo-sync.vercel.app

Exit codes:
    0 — all checks passed, SQL emitted to stdout as JSON
    1 — tracking pixel missing from production HTML
    2 — /api/lp/{slug}/track returned non-204
    3 — unknown slug / HTTP 404 on LP page
    4 — other unexpected error

The caller (Claude in the bootstrap workflow) is expected to:
  a. If verify_pixel=false or track_endpoint_ok=false → halt and report
  b. Call Supabase MCP execute_sql with the `check_tables_sql` payload
     to see if tables exist
  c. If not, call apply_migration with `migration_sql` payload
  d. Call execute_sql with `seed_sql` payload (skip if --no-seed)
  e. Summarize results in the handoff message
"""

import argparse
import json
import re
import sys
import time
from urllib import request, error


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_BASE_URL = "https://nippo-sync.vercel.app"
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")
PIXEL_MARKER_LP = "lp_sid_"          # appears in both main LP + job detail
PIXEL_MARKER_FORM = "track('form_view')"  # only on entry form


# ═══════════════════════════════════════════════════════════════════════
# SQL payloads — kept here so the caller can copy-paste or apply via MCP
# ═══════════════════════════════════════════════════════════════════════

MIGRATION_SQL = r"""
-- Migration: lp_analytics_page_views
-- Creates tables + indexes + RLS policies for LP analytics pipeline
-- Idempotent — safe to re-run

CREATE TABLE IF NOT EXISTS public.lp_page_views (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_slug         text NOT NULL,
  viewed_at       timestamptz NOT NULL DEFAULT now(),
  session_id      text,
  path            text NOT NULL,
  referrer        text,
  referrer_domain text,
  user_agent      text,
  device_type     text,
  country         text
);

CREATE INDEX IF NOT EXISTS idx_lp_page_views_slug_viewed_at
  ON public.lp_page_views (lp_slug, viewed_at DESC);

CREATE INDEX IF NOT EXISTS idx_lp_page_views_session
  ON public.lp_page_views (lp_slug, session_id, viewed_at);

CREATE TABLE IF NOT EXISTS public.lp_form_events (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_slug      text NOT NULL,
  event_type   text NOT NULL,  -- 'form_view' | 'form_start' | 'form_submit'
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  session_id   text,
  path         text
);

CREATE INDEX IF NOT EXISTS idx_lp_form_events_slug_type_time
  ON public.lp_form_events (lp_slug, event_type, occurred_at DESC);

-- RLS: public can INSERT (tracking pixel), admins SELECT via service role
ALTER TABLE public.lp_page_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lp_form_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "lp_page_views_public_insert" ON public.lp_page_views;
CREATE POLICY "lp_page_views_public_insert"
  ON public.lp_page_views FOR INSERT
  TO anon, authenticated
  WITH CHECK (true);

DROP POLICY IF EXISTS "lp_form_events_public_insert" ON public.lp_form_events;
CREATE POLICY "lp_form_events_public_insert"
  ON public.lp_form_events FOR INSERT
  TO anon, authenticated
  WITH CHECK (true);
"""

CHECK_TABLES_SQL = """
SELECT
  to_regclass('public.lp_page_views') IS NOT NULL AS page_views_exists,
  to_regclass('public.lp_form_events') IS NOT NULL AS form_events_exists,
  (SELECT count(*) FROM pg_indexes
   WHERE tablename = 'lp_page_views'
     AND indexname IN ('idx_lp_page_views_slug_viewed_at', 'idx_lp_page_views_session'))::int AS pv_index_count,
  (SELECT count(*) FROM pg_indexes
   WHERE tablename = 'lp_form_events'
     AND indexname = 'idx_lp_form_events_slug_type_time')::int AS fe_index_count;
"""


# ═══════════════════════════════════════════════════════════════════════
# Seed SQL template — parameterized by {slug}
# ═══════════════════════════════════════════════════════════════════════
#
# Design notes:
# - 15 entries with varied statuses, dates across 27 days, realistic names
# - All page_views + form_events are tagged user_agent LIKE '%fake-backfill%'
#   so bulk-deletion is a one-liner AND dashboard 全削除 can exclude them
# - Growth trend: 40 → 180 views/day over 30 days with weekend dips
# - Referrer distribution matches realistic small-business recruitment LP
# - Funnel: ~25% of views see the form, ~35% of those start typing
# - The 15 form_submits are the same 15 lp_entries seeded above
#
# The {slug} placeholder is substituted by Python's str.format() — the
# slug is validated against SLUG_RE before substitution so SQL injection
# is impossible.

SEED_SQL_TEMPLATE = r"""
-- Seed 15 realistic test entries for {slug}
-- All seeded entries use source = 'lp_form_demo' so handover cleanup
-- can DELETE them in one statement without touching real submissions.
INSERT INTO public.lp_entries (lp_slug, created_at, name, email, phone, position, message, status, notes, source)
VALUES
  ('{slug}', now() - interval '1 hour',  '山田 健太',   'yamada.kenta@example.com',   '090-1234-5678', '募集職種A', '御社のビジョンに共感しました。業界経験3年、新しい挑戦をしたいです。', 'new',       NULL, 'lp_form_demo'),
  ('{slug}', now() - interval '3 hours', '佐藤 美咲',   'sato.misaki@example.com',    '080-2345-6789', '募集職種B', 'デザイナーとして5年の経験があります。ポートフォリオあります。', 'new',       NULL, 'lp_form_demo'),
  ('{slug}', now() - interval '8 hours', '鈴木 翔太',   'suzuki.shota@example.com',   '070-3456-7890', '募集職種A', 'HRテックに興味があり、業務の最適化に貢献したいです。', 'seen',      '返信済み。カジュアル面談調整中', 'lp_form_demo'),
  ('{slug}', now() - interval '1 day',   '田中 愛子',   'tanaka.aiko@example.com',    NULL,            '募集職種B', NULL, 'new', NULL, 'lp_form_demo'),
  ('{slug}', now() - interval '2 days',  '高橋 大輔',   'takahashi.d@example.com',    '090-4567-8901', '募集職種A', '前職は営業5年。人と関わる仕事が好きです。', 'contacted', '1次面談予定',                      'lp_form_demo'),
  ('{slug}', now() - interval '3 days',  '伊藤 さくら', 'ito.sakura@example.com',     '080-5678-9012', '募集職種B', 'コピーライティングとUI/UXデザインが得意です。', 'contacted', 'ポートフォリオ確認中',             'lp_form_demo'),
  ('{slug}', now() - interval '5 days',  '渡辺 達也',   'watanabe.t@example.com',     '070-6789-0123', '募集職種A', '京都在住。スタートアップ経験あり。',     'rejected',  '経験不足',                          'lp_form_demo'),
  ('{slug}', now() - interval '6 days',  '中村 優奈',   'nakamura.y@example.com',     '090-7890-1234', '募集職種A', '人材紹介会社で3年。個人の成長に寄り添いたい。', 'contacted', '2次面談調整中',            'lp_form_demo'),
  ('{slug}', now() - interval '8 days',  '小林 翼',     'kobayashi.t@example.com',    NULL,            '募集職種B', 'Adobe系全般使えます。',                   'hired',     '入社日調整中',                       'lp_form_demo'),
  ('{slug}', now() - interval '10 days', '加藤 麻衣',   'kato.mai@example.com',       '080-8901-2345', '募集職種A', '大学時代にインターン経験あり。',           'rejected',  '別候補者を採用',                     'lp_form_demo'),
  ('{slug}', now() - interval '13 days', '吉田 龍之介', 'yoshida.r@example.com',      '070-9012-3456', '募集職種B', 'フリーランスで採用LPを30本以上制作。',       'hired',     '業務委託契約開始',                   'lp_form_demo'),
  ('{slug}', now() - interval '16 days', '山本 恵子',   'yamamoto.k@example.com',     '090-0123-4567', '募集職種A', NULL,                                      'seen',      NULL,                                'lp_form_demo'),
  ('{slug}', now() - interval '19 days', '松本 雄一',   'matsumoto.y@example.com',    '080-1122-3344', '募集職種A', '営業→HR転身希望。',                       'rejected',  'スキルミスマッチ',                   'lp_form_demo'),
  ('{slug}', now() - interval '23 days', '木村 由美',   'kimura.yumi@example.com',    '070-2233-4455', '募集職種B', '動画編集も可能。',                         'seen',      NULL,                                'lp_form_demo'),
  ('{slug}', now() - interval '27 days', '林 健一',     'hayashi.k@example.com',      NULL,            '募集職種A', NULL,                                      'new',       NULL,                                'lp_form_demo');

-- Backfill 30 days of page views with growth trend + weekend dips +
-- realistic referrer mix. The key fix vs the old seed: we use
-- per-row random() values inside a CTE so PostgreSQL evaluates them
-- ONCE PER ROW instead of once per statement. With the old subquery
-- approach (SELECT ... ORDER BY random() LIMIT 1) the optimizer
-- collapsed the subquery and every row got the same referrer.
-- Distribution target:
--   Google検索   ~40%
--   直接アクセス  ~22%
--   Twitter/X    ~15%
--   LinkedIn     ~10%
--   Bing検索      ~5%
--   Facebook      ~5%
--   Instagram     ~3%
WITH day_series AS (
  SELECT generate_series(0, 29) AS days_ago
),
counts AS (
  SELECT
    days_ago,
    floor(
      40 + (29 - days_ago) * 4.5
      + (random() * 30 - 10)
      - CASE WHEN EXTRACT(DOW FROM (now() - (days_ago || ' days')::interval)) IN (0, 6) THEN 20 ELSE 0 END
    )::int AS view_count
  FROM day_series
),
exploded AS (
  SELECT c.days_ago, gs.i
  FROM counts c
  CROSS JOIN LATERAL generate_series(1, c.view_count) AS gs(i)
),
with_random AS (
  SELECT
    days_ago, i,
    random() AS r_ref,
    random() AS r_path,
    random() AS r_dev
  FROM exploded
)
INSERT INTO public.lp_page_views (lp_slug, viewed_at, session_id, path, referrer, referrer_domain, user_agent, device_type)
SELECT
  '{slug}',
  (now() - (days_ago || ' days')::interval - (random() * interval '1 day'))::timestamptz,
  md5(random()::text || days_ago || i)::text,
  CASE
    WHEN r_path < 0.60 THEN '/lp/{slug}'
    WHEN r_path < 0.85 THEN '/lp/{slug}/jobs/0'
    ELSE '/lp/{slug}/jobs/1'
  END,
  -- referrer URL — same r_ref bucket as referrer_domain
  CASE
    WHEN r_ref < 0.40 THEN 'https://www.google.com/search?q=' || (ARRAY['採用','求人','京都%20採用','正社員','転職'])[1 + floor(random() * 5)::int]
    WHEN r_ref < 0.55 THEN 'https://t.co/' || substring(md5(random()::text), 1, 8)
    WHEN r_ref < 0.65 THEN 'https://www.linkedin.com/feed/'
    WHEN r_ref < 0.70 THEN 'https://www.bing.com/search'
    WHEN r_ref < 0.75 THEN 'https://www.facebook.com/'
    WHEN r_ref < 0.78 THEN 'https://www.instagram.com/'
    ELSE NULL
  END,
  -- referrer_domain — must match the same r_ref bucket
  CASE
    WHEN r_ref < 0.40 THEN 'google.com'
    WHEN r_ref < 0.55 THEN 'twitter.com'
    WHEN r_ref < 0.65 THEN 'linkedin.com'
    WHEN r_ref < 0.70 THEN 'bing.com'
    WHEN r_ref < 0.75 THEN 'facebook.com'
    WHEN r_ref < 0.78 THEN 'instagram.com'
    ELSE NULL
  END,
  'Mozilla/5.0 (fake-backfill)',
  CASE
    WHEN r_dev < 0.55 THEN 'mobile'
    WHEN r_dev < 0.85 THEN 'desktop'
    ELSE 'tablet'
  END
FROM with_random;

-- Form events for funnel: ~25% of viewers see the form
INSERT INTO public.lp_form_events (lp_slug, event_type, occurred_at, session_id, path)
SELECT '{slug}', 'form_view', pv.viewed_at + interval '30 seconds', pv.session_id, pv.path
FROM public.lp_page_views pv
WHERE pv.lp_slug = '{slug}' AND pv.user_agent LIKE '%fake-backfill%' AND random() < 0.25;

-- ~35% of form-viewers start typing
INSERT INTO public.lp_form_events (lp_slug, event_type, occurred_at, session_id, path)
SELECT '{slug}', 'form_start', fv.occurred_at + interval '15 seconds', fv.session_id, fv.path
FROM public.lp_form_events fv
WHERE fv.lp_slug = '{slug}'
  AND fv.event_type = 'form_view'
  AND random() < 0.35;
"""

# SQL to delete only the fake-backfill rows (what the client runs to clean up)
CLEANUP_SQL_TEMPLATE = """
-- Cleanup: remove ONLY the demo seed data for {slug}, leave real data alone.
-- This is the same SQL that runs automatically inside the OAuth callback +
-- email fallback transactions when the client claims ownership via /admin?first.
-- Idempotent — safe to re-run any time.
DELETE FROM public.lp_form_events
 WHERE lp_slug = '{slug}'
   AND session_id IN (
     SELECT session_id FROM public.lp_page_views
     WHERE lp_slug = '{slug}' AND user_agent LIKE '%fake-backfill%'
   );

DELETE FROM public.lp_page_views
 WHERE lp_slug = '{slug}' AND user_agent LIKE '%fake-backfill%';

DELETE FROM public.lp_entries
 WHERE lp_slug = '{slug}' AND source = 'lp_form_demo';
"""


# ═══════════════════════════════════════════════════════════════════════
# HTTP helpers
# ═══════════════════════════════════════════════════════════════════════

def http_get(url: str, timeout: int = 15) -> tuple[int, str]:
    """GET url and return (status_code, body_text). Never raises."""
    try:
        req = request.Request(
            url,
            headers={
                "User-Agent": "mgc-saiyo-lp-bootstrap/analytics_bootstrap.py",
            },
        )
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 0, f"[network error: {e}]"


def http_post_json(url: str, payload: dict, timeout: int = 15) -> tuple[int, str]:
    """POST JSON payload to url. Returns (status_code, body_text)."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "mgc-saiyo-lp-bootstrap/analytics_bootstrap.py",
            },
        )
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, f"[network error: {e}]"


# ═══════════════════════════════════════════════════════════════════════
# Verification checks
# ═══════════════════════════════════════════════════════════════════════

def verify_pixel_main_lp(base_url: str, slug: str) -> dict:
    """Curl /lp/{slug} and grep for the tracking pixel marker."""
    url = f"{base_url}/lp/{slug}"
    status, body = http_get(url)
    marker = f"lp_sid_{slug.replace('-', '')}"  # 'cloq' → 'lp_sid_cloq'
    # More permissive — any lp_sid_ reference with the slug
    has_pixel = PIXEL_MARKER_LP in body and f'"{slug}"' in body
    return {
        "url": url,
        "status": status,
        "has_pixel": has_pixel,
        "body_bytes": len(body),
    }


def verify_pixel_job_detail(base_url: str, slug: str) -> dict:
    """Curl /lp/{slug}/jobs/0 — should exist if at least one opening."""
    url = f"{base_url}/lp/{slug}/jobs/0"
    status, body = http_get(url)
    has_pixel = PIXEL_MARKER_LP in body and f'"{slug}"' in body
    return {
        "url": url,
        "status": status,
        "has_pixel": has_pixel,
        "body_bytes": len(body),
    }


def verify_pixel_entry_form(base_url: str, slug: str) -> dict:
    """Curl /lp/{slug}/entry and check for the form-lifecycle pixel."""
    url = f"{base_url}/lp/{slug}/entry"
    status, body = http_get(url)
    has_pixel = PIXEL_MARKER_FORM in body
    return {
        "url": url,
        "status": status,
        "has_pixel": has_pixel,
        "body_bytes": len(body),
    }


def verify_track_endpoint(base_url: str, slug: str) -> dict:
    """POST a synthetic page_view event and expect 204."""
    url = f"{base_url}/api/lp/{slug}/track"
    session_id = f"analytics-bootstrap-{int(time.time())}"
    payload = {
        "event_type": "page_view",
        "path": f"/lp/{slug}",
        "session_id": session_id,
        "referrer": "",
    }
    status, body = http_post_json(url, payload)
    return {
        "url": url,
        "status": status,
        "ok": status == 204,
        "test_session_id": session_id,  # caller can DELETE this row afterwards
    }


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify + bootstrap LP analytics infrastructure (step 12.7).",
    )
    parser.add_argument("--slug", required=True, help="LP slug (e.g. cloq)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"nippo-sync base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--no-seed", action="store_true",
                        help="Skip demo data seeding (only verify infrastructure)")
    parser.add_argument("--verify-only", action="store_true",
                        help="Alias for --no-seed, for clarity")
    args = parser.parse_args()

    if not SLUG_RE.match(args.slug):
        print(json.dumps({
            "ok": False,
            "error": "invalid_slug",
            "detail": f"slug must match {SLUG_RE.pattern}",
        }, ensure_ascii=False))
        return 4

    skip_seed = args.no_seed or args.verify_only
    slug = args.slug
    base = args.base_url.rstrip("/")

    result: dict = {
        "ok": True,
        "slug": slug,
        "base_url": base,
        "seed_enabled": not skip_seed,
        "checks": {},
        "sql": {},
        "next_actions": [],
    }

    # ─── Check 1: main LP pixel ────────────────────────────────────
    main_check = verify_pixel_main_lp(base, slug)
    result["checks"]["main_lp"] = main_check
    if main_check["status"] == 404:
        result["ok"] = False
        result["error"] = "slug_not_found"
        result["detail"] = f"GET {main_check['url']} returned 404 — run bootstrap.py first"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3
    if not main_check["has_pixel"]:
        result["ok"] = False
        result["error"] = "pixel_missing_main_lp"
        result["detail"] = (
            f"Tracking pixel not found in {main_check['url']}. "
            "lp-render.ts may be missing the pixel injection. "
            "Check that both renderLpHtml() and renderJobDetailHtml() "
            "have the <script> block with lp_sid_{slug} and "
            "/api/lp/${slug}/track fetch. Precedent: nippo-sync@dc7d513."
        )

    # ─── Check 2: job detail pixel ─────────────────────────────────
    job_check = verify_pixel_job_detail(base, slug)
    result["checks"]["job_detail_0"] = job_check
    if job_check["status"] == 200 and not job_check["has_pixel"]:
        result["ok"] = False
        result["error"] = "pixel_missing_job_detail"
        result["detail"] = (
            f"Tracking pixel not found in {job_check['url']}. "
            "renderJobDetailHtml() in lp-render.ts needs the same "
            "pixel block as renderLpHtml()."
        )

    # ─── Check 3: entry form pixel ─────────────────────────────────
    entry_check = verify_pixel_entry_form(base, slug)
    result["checks"]["entry_form"] = entry_check
    if entry_check["status"] == 200 and not entry_check["has_pixel"]:
        result["ok"] = False
        result["error"] = "pixel_missing_entry_form"
        result["detail"] = (
            f"Form-lifecycle pixel not found in {entry_check['url']}. "
            "src/app/lp/[slug]/entry/route.ts needs the form pixel "
            "with track('form_view'), track('form_start'), and the "
            "fetch monkey-patch for form_submit. Precedent: nippo-sync@dc7d513."
        )

    # ─── Check 4: /track endpoint responds 204 ─────────────────────
    track_check = verify_track_endpoint(base, slug)
    result["checks"]["track_endpoint"] = track_check
    if not track_check["ok"]:
        result["ok"] = False
        result["error"] = "track_endpoint_not_204"
        result["detail"] = (
            f"POST {track_check['url']} returned {track_check['status']}, expected 204. "
            "Check that src/app/api/lp/[slug]/track/route.ts exists and handles POST."
        )

    # ─── SQL payloads — always included so caller can act if needed ─
    result["sql"]["check_tables"] = CHECK_TABLES_SQL.strip()
    result["sql"]["migration"] = MIGRATION_SQL.strip()
    result["sql"]["cleanup"] = CLEANUP_SQL_TEMPLATE.format(slug=slug).strip()

    if not skip_seed:
        result["sql"]["seed"] = SEED_SQL_TEMPLATE.format(slug=slug).strip()

    # ─── Also include the clean-up of the test track ping ──────────
    result["sql"]["cleanup_track_test"] = (
        f"DELETE FROM public.lp_page_views "
        f"WHERE session_id = '{track_check['test_session_id']}';"
    )

    # ─── Next actions for the caller (Claude) ──────────────────────
    if result["ok"]:
        result["next_actions"] = [
            "Run sql.check_tables via Supabase MCP execute_sql to verify tables exist",
            "If either *_exists is false: apply_migration with name='lp_analytics_page_views' and query=sql.migration",
            "Execute sql.cleanup_track_test via execute_sql to remove the /track ping",
        ]
        if not skip_seed:
            result["next_actions"].append(
                "Execute sql.seed via execute_sql to populate demo data"
            )
        result["next_actions"].append(
            "Include RULE 21 disclosure in handoff message: "
            "'dashboard pre-seeded with demo data, use 全削除 + sql.cleanup to clear'"
        )
    else:
        result["next_actions"] = [
            "HALT — verification failed, do not seed data or complete handoff",
            f"Fix: {result.get('detail', 'see error field')}",
        ]

    # Emit the full JSON result for the caller to parse
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit codes
    if not result["ok"]:
        err = result.get("error", "")
        if "pixel_missing" in err:
            return 1
        if err == "track_endpoint_not_204":
            return 2
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
