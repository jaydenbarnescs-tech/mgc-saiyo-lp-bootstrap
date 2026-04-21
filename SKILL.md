---
name: mgc-saiyo-lp-bootstrap
description: Creates a brand-new Japanese 採用LP (recruitment landing page) for a client from a single reference URL. Fires whenever the user mentions 採用LP (or "recruitment LP" / "saiyo LP") alongside a URL and a client name in the same message — examples that trigger: "作って 採用LP for 株式会社CLOQ https://cloq.jp/", "採用LP cloq https://cloq.jp/", "採用LPを作って https://cloq.jp/ 株式会社CLOQ", "Build a recruitment LP for ABC, ref https://example.jp/", "新しいクライアントのLP作って 株式会社X https://x.jp/". Runs end-to-end without mid-flow questions: multi-page crawl of the reference site (extracts 会社概要 / 募集要項 / logo / colors via <dl>/<img>/CSS walks), composes a structural LpContent draft, performs mandatory audience-pivot rewrite of hero / about / strengths / cta so the content targets job seekers not clients, inserts via Supabase MCP into project pglaffdnhixmabcjdxbi, creates an initial Google Sheet in Jayden's Drive (replaced by a fresh one in the client's own Drive when they claim ownership), registers the LP in the public.lps master registry so the deterministic OAuth-driven first-setup URL /lp/{slug}/admin?first is activated, and returns the live URL plus the /admin?first handover URL for the client to click-through Google sign-in. Target: under 2 minutes from prompt to shipping. Do NOT fire this for editing an existing LP (that happens in the admin editor at /lp/{slug}/admin) or for updating copy / images / layout on a live LP.
---

# mgc-saiyo-lp-bootstrap

Bootstrap a complete 採用LP for a client from a single reference URL. Target: under 2 minutes from prompt to live URL.

## THE ONE RULE — read this first, every time

**Speed over perfection. Ship aggressive, refine in editor.**

This skill exists because the per-LP admin editor at `/lp/{slug}/admin` already handles polishing, theme tweaks, content editing, image swaps, Google Sheets sync, custom domain attach, analytics dashboard, and PDF export. The editor is fast and the user (Jayden) uses it constantly. So this skill's job is **not** to produce a perfect LP — it's to produce a 90%-correct LP in 90 seconds, seed it with realistic demo data so it looks alive the moment the client opens their dashboard, then hand off to the editor for the last 10%.

As of 2026-04-09 the admin dashboard has been rebuilt as a self-contained Lovable file at `src/app/lp/[slug]/admin/AdminDashboard.tsx` with 5 sections (ダッシュボード / 応募管理 / LP編集 / 管理者 / 設定), real analytics via `lp_page_views` + `lp_form_events` tables, a tracking pixel baked into every public LP page, a dedicated analytics aggregation endpoint, and a two-state LP編集 landing screen. This means a freshly handed-over client sees a populated dashboard with PV trends, traffic sources, conversion funnel, device breakdown, and sample entries — not a blank slate.

Default behavior: scrape aggressively, fill gaps with sensible defaults, ship to editor, refine there. **Do NOT ask for confirmation mid-flow.** Build, hand off, let user fix in editor. The only acceptable interruptions are: missing required inputs (no URL, no client name) or slug collision.

This is the philosophical opposite of the old `saiyo-lp-skill` which had "always ask, never assume" as rule #1. That rule existed because the old skill generated static HTML — fixing a mistake meant rebuilding. The new system has a live editor; that rule is obsolete.

---

## CRITICAL CONSTRAINTS — never violate these

These are non-negotiable. They come from hard lessons in the predecessor `saiyo-lp-skill` plus the cloq build. Every single one cost an hour+ to discover the first time and WILL silently break the skill if ignored.

### 1. NEVER touch Matsuo-san's services or directories

The Oracle Cloud VM runs multiple services in parallel. Some are Matsuo-san's (completely separate product, different codebase, different clients). Writing to any of these paths WILL break production for Matsuo-san's team and is treated as a severity-1 incident.

**Forbidden paths** (read-only at most, never write, never restart, never `git pull`):
- `/home/ubuntu/mgc-connector-hub/` — Matsuo-san's connector hub
- `/home/ubuntu/nippo-sync-koko/` — Matsuo-san's Koko variant of nippo-sync (NOT the same as `/home/ubuntu/nippo-sync/` which is Jayden's)
- `/home/ubuntu/line-harness-oss/` — Matsuo-san's LINE CRM harness

**Forbidden systemd services** (never `systemctl restart/stop/start`, never tail their logs with intent to modify):
- `mgc-connector-hub.service` (port 8443)
- `line-crm.service` (port 3002)
- `n8n-koko.service` (port 5679) — NOT the same as `n8n.service` which is ours

**Jayden's paths (safe to write)**:
- `/home/ubuntu/nippo-sync/` — Jayden's nippo-sync repo
- `/home/ubuntu/mgc-saiyo-lp-bootstrap/` — this skill
- `/home/ubuntu/mgc-pass-proxy/` — the MGC proxy server
- `/home/ubuntu/mgc-research-agent/`, `/home/ubuntu/mgc-docs/`, `/home/ubuntu/mgc-accelerator-hub/`, `/home/ubuntu/mgc-translation-*/`

**Jayden's services (safe to touch)**:
- `nippo-sync.service` (if it exists as a local dev server; prod runs on Vercel)
- `mgc-pass-proxy.service`
- `n8n.service` (port 5678 — the main one)

When in doubt: `systemctl status <name>` is read-only and always safe. Writing, restarting, or modifying is only for the explicit list above.

### 2. NEVER add the `spreadsheets` OAuth scope back

Our Google OAuth consent screen is in **Production mode** (published, no verification, no 100-user cap, no warning banner) specifically because every scope we request is **non-sensitive**:
- `drive.file`
- `userinfo.email`
- `openid`

Adding `https://www.googleapis.com/auth/spreadsheets` — or ANY scope Google classifies as "sensitive" — instantly kicks us into Google's verification track, which requires demo videos, privacy policy review, and 4+ weeks of back-and-forth. Existing clients get an "unverified app" warning banner and we're capped at 100 test users until verified. **This is the single most expensive mistake we can make with OAuth.**

`drive.file` is sufficient for everything we do because:
- `spreadsheets.create` is covered (drive.file grants create for app-created files)
- `spreadsheets.values.append` + `batchUpdate` + `get` are all covered on files the app created
- `drive.permissions.create` (for sharing with invited admins) is covered on app-created files

The ONE thing `drive.file` can't do is touch files that WEREN'T created by our app. That's fine — we never need to.

**Precedent**: commit `d933495` — dropped `spreadsheets` from the scopes, republished consent screen, zero verification required.

### 3. NEVER use fire-and-forget `(async () => {...})()` in any Vercel API route

Vercel serverless functions kill unawaited async work the moment the function returns its response. An IIFE like `;(async () => { await sheetSync() })()` will silently never run in production even though the Vercel logs say the function returned 200. The `await` inside the IIFE never completes because the process is already being torn down.

**Rule**: any async side effect in an `/api/*` route must be either:
- `await`'d inline (preferred — adds ~500ms-1s latency but actually reliable)
- Wrapped in `waitUntil()` from `@vercel/functions` (use when latency is critical and you genuinely don't care about the result)

**Never** use bare IIFEs for side effects. Precedents:
- `b261c5b` — sheet sync was fire-and-forget, silently never ran for real submissions; only the manual `/sync` endpoint ever wrote to the sheet, which is why Jayden saw test entries but new submissions never appeared in the Google Sheet until debugging
- `d3ef7e1` — notification email had the same bug; entries succeeded in the DB but no email was ever sent

When adding new API routes in this skill or in nippo-sync, grep for `;(async` and `catch(() => {})` patterns — those are landmines.

### 4. NEVER name static LP fallback files `index.html` in `/public/lp/{slug}/`

Next.js static files in `/public/` take precedence over dynamic app router routes. If you drop `/public/lp/{slug}/index.html` or `/public/lp/{slug}/entry/index.html`, Vercel's static file handler serves it BEFORE the `/app/lp/[slug]/route.ts` or `/app/lp/[slug]/entry/route.ts` handler ever gets a chance. The dynamic route appears to never fire. You redeploy. Same result. You check the file, it's right. Nothing works.

**Rule**: always name static LP fallbacks `_legacy-index.html.bak` or something else that doesn't end in `index.html`. Keep them in the repo as safety fallbacks that the route handler can `readFile` on error — but never let them BE the route.

**Precedent**: commits `4645fca` (yamaguchi static file was intercepting the Phase 5 dynamic route) and `166d3b8` (cloq entry form was hardcoded to yamaguchi because `public/lp/yamaguchi/entry/index.html` took precedence over the dynamic `/app/lp/[slug]/entry/route.ts`).

**Corollary for `next.config.js` rewrites**: any `afterFiles` rewrite for `/lp/:slug/:sub → /lp/:slug/:sub/index.html` will ALSO intercept the app router. Use `fallback` (runs after dynamic routes fail) instead of `afterFiles` (runs before dynamic routes). Precedent: `df6d566`.

### 5. NEVER tell the user "done" after deploy without curl verification

After every `git push` that changes LP rendering or a public route, verify with:
```bash
curl -sI https://nippo-sync.vercel.app/lp/{slug}          # expect 200
curl -s https://nippo-sync.vercel.app/lp/{slug} | grep {client_name_marker}   # expect match
curl -s https://nippo-sync.vercel.app/lp/{slug} | grep 'og:title'             # expect real client title, not 日報シンクロくん
```

If any check fails, roll back BEFORE reporting success. Don't trust Vercel's "deployment successful" message — that just means the build compiled, not that the route actually works.

### 6. NEVER commit real PII without consent

If the user provides real employee names, photos, or quotes during a build, confirm before pushing to the public Vercel URL. The LPs are publicly indexable (except admin pages which have `robots: noindex`). Once it's on the internet and crawled, it's on the internet forever.

### 7. NEVER use bare-variable Tailwind v4 shorthand (`w-[--sidebar-width]`)

Tailwind v4 changed how arbitrary CSS variables are parsed. The bare-variable shorthand `w-[--sidebar-width]` that worked in v3 silently produces `width: --sidebar-width` (literal string) in v4, causing the element to collapse to 0 width. The correct syntax is `w-[var(--sidebar-width)]` — explicit `var()` wrapper.

This bit us twice in the same session when porting the Lovable admin dashboard: first the desktop sidebar overlapped the content area (bare shorthand in the shadcn Sidebar component's `collapsible="icon"` branch), then my "fix" to use `collapsible="none"` hid the mobile drawer behind an always-visible 256px sidebar. The root cause was the same bug in 6 different class names inside `shadcn/sidebar.tsx`: `w-[--sidebar-width]` (×4) and `w-[--sidebar-width-icon]` (×2).

**Fix if you ever copy a shadcn sidebar from v3 docs into a v4 project**: run this regex replacement across the file:
```python
re.sub(r'\[--sidebar-width\]', '[var(--sidebar-width)]', src)
re.sub(r'\[--sidebar-width-icon\]', '[var(--sidebar-width-icon)]', src)
```

**General rule**: inside arbitrary-value brackets, always wrap CSS variables in `var()` explicitly. `w-[var(--x)]`, not `w-[--x]`. Claude should flag any `[--` pattern in Tailwind classes as a red flag during code review. Precedent commit: `780f440`.

### 8. NEVER jump directly into `LpContentEditor` from the admin sidebar

The `LP編集` section MUST be a two-state component: (a) a landing card with overview stats + hero CTA + section list by default, (b) the full `LpContentEditor` component only after the user explicitly clicks `編集を開始`. Direct jumps confuse users — they land in a dense WordPress-style editor with no context, no escape route, no "why am I here".

Additionally, the editor's back button MUST be in the **header-left** (right after the hamburger), styled with the navy/blue color token, labeled `← ダッシュボードに戻る` (not just `× 閉じる`). The `onClose` callback MUST return to the landing screen, NOT to a different section. This gives a clean back-and-forth: landing → editor → landing → any other section.

Any future admin feature that wraps an existing heavy editor component in the sidebar MUST follow the same pattern. The rule is "cards and landing screens are cheap, context is not." Precedent commit: `dc7d513`.

### 9. NEVER use independent subqueries to generate correlated random columns

PostgreSQL's optimizer treats `(SELECT ... ORDER BY random() LIMIT 1)` subqueries inside an INSERT as scalar constants — they're evaluated ONCE for the whole statement, not once per row. This means two independent random subqueries in the same INSERT will both pick a single value and apply it to every row. We hit this in `analytics_bootstrap.py`'s seed SQL: `referrer` and `referrer_domain` were two independent `(SELECT … FROM referrer_pool ORDER BY random() LIMIT 1)` subqueries, and all 3,172 cloq rows ended up with `referrer='google'` AND `referrer_domain='bing.com'` — both stuck on a single pick, AND mismatched against each other.

**Fix pattern**: precompute random values in a CTE one row at a time using `CROSS JOIN LATERAL generate_series(...)` (which forces per-row evaluation), then derive correlated columns from those values via `CASE` expressions:

```sql
WITH exploded AS (
  SELECT day, gs.i FROM days CROSS JOIN LATERAL generate_series(1, day_count) gs(i)
),
with_random AS (
  SELECT day, i, random() AS r_ref FROM exploded
)
INSERT INTO target (referrer, referrer_domain)
SELECT
  CASE WHEN r_ref < 0.4 THEN 'https://google.com/search' WHEN r_ref < 0.55 THEN 'https://t.co/x' ... END,
  CASE WHEN r_ref < 0.4 THEN 'google.com'                WHEN r_ref < 0.55 THEN 'twitter.com'    ... END
FROM with_random;
```

This guarantees both per-row variety AND consistency between columns. Documented as H54 in Category 16. Precedent: 2026-04-10 cloq reseed.


---

## Trigger

The skill activates when the user clearly wants a new 採用LP built from a reference URL. The reliable signals are:

1. **The keyword** — any of: `採用LP`, `採用ランディング`, `採用ページ作って`, `recruitment LP`, `recruitment landing`, `saiyo LP`, `saiyo-lp`, `new LP for`
2. **A URL** — the reference site, typically the client's own corporate site (`https://...`)
3. **A client name** — Japanese (`株式会社CLOQ`), English (`cloq`, `CLOQ`), or the slug form inferable from the URL hostname

All three need to be present or inferable from context. If two out of three are there (e.g. keyword + URL but no client name), infer the missing piece rather than asking: derive the client name from the page's `<title>` or `og:site_name` on first fetch.

**Examples that FIRE the skill (build immediately, no clarifying questions):**

- `作って 採用LP for 株式会社CLOQ from https://cloq.jp/`
- `採用LP cloq https://cloq.jp/`
- `採用LPを作って https://cloq.jp/ 株式会社CLOQ`
- `Build a 採用LP, reference: https://cloq.jp/, style ref: https://taf-jp.com/recruitment/`
- `Make a recruitment LP for ABC建設, their site is https://example.jp/`
- `新しいクライアントのLP作ってほしい 株式会社X https://x.jp/`
- `saiyo-lp for https://cloq.jp`  (infer client name from `<title>`)

**Examples that DO NOT fire:**

- `cloq の LPを編集して` — "edit the LP" means use the admin editor at `/lp/cloq/admin`, not rebuild
- `cloqのLPの求人を追加して` — adding/changing openings happens in the admin editor
- `https://cloq.jp/ の情報を教えて` — URL without `採用LP` keyword is a research request
- `採用LPのテンプレートを作って` — no specific client or URL, this is a meta request about the skill itself

**One-shot mandate**: once the skill fires, run the entire workflow start-to-finish without stopping to ask questions. The only acceptable mid-flow interruptions are (a) slug collision against an existing `lps` row (abort, ask for overwrite or new slug) or (b) Supabase insert genuinely fails (report the error). Every other ambiguity is resolved by picking the most plausible interpretation and noting it in the provenance report.

---

## What the user gets back when the skill finishes

When the skill completes successfully, Claude returns a single message with:

1. **Live URL** — `https://nippo-sync.vercel.app/lp/{slug}` — open in a browser, renders immediately
2. **Admin URL** — `https://nippo-sync.vercel.app/lp/{slug}/admin` — for Jayden (the existing pre-seeded owner) to polish
3. **First-setup URL** — `https://nippo-sync.vercel.app/lp/{slug}/admin?first` — the deterministic one-shot owner-claim link to send to the client. No token, no expiry — always the same URL per slug, always ready until a successful sign-in has occurred. The client's primary path is **Google sign-in** via the big blue button on the screen, which routes through `/api/sheets/connect/{slug}/authorize?first=1` → Google consent → the OAuth callback. On success the callback atomically: (a) DEMOTEs Jayden's pre-seeded admin rows to `member` (preserving google_refresh_token), (b) UPSERTs the client as owner with their fresh tokens, (c) **creates a brand-new Google Sheet in the client's own Drive** (not reusing Jayden's existing sheet), (d) copies existing lp_entries into the new sheet, (e) sets `lps.handed_over_at`. A secondary "email only" fallback is available behind a collapsible link for clients without Google — it locks the LP but doesn't create a new sheet; the client has to connect Google Sheets from the dashboard later. **Crucially: the one-shot lock is ONLY set inside the same atomic transaction as the DB mutations, so just clicking the URL or cancelling the Google consent screen does NOT burn it.** Only a fully successful round-trip does.
4. **Google Sheet URL** — the auto-sync sheet for entries, sitting in Jayden's Google Drive
5. **Provenance report** — every field labeled `scraped` | `scraped_dl` | `preset` | `default` | `ai_generated` | `fallback_letter` so the user knows what's real vs placeholder
6. **Polish checklist** — 2-4 specific things Claude recommends touching up manually before sending to the client (e.g. "the data pills are industry-preset defaults, swap in real numbers if you have them", "voices.items uses placeholder names — replace with real employees after they start")
7. **Analytics status** — confirmation that (a) `lp_page_views` + `lp_form_events` tables exist + are indexed, (b) the tracking pixel is live in production on `/lp/{slug}`, `/lp/{slug}/jobs/*`, `/lp/{slug}/entry`, (c) `/api/lp/{slug}/track` responds 204, (d) the demo seed has been applied (15 entries + ~3,000 PV + ~800 form_view + ~280 form_start over the last 30 days, all marked with `user_agent LIKE '%fake-backfill%'` so the client can bulk-delete in one SQL statement before real traffic starts). The client's dashboard will show populated charts from minute 1 — no "0 PV, 0 entries" empty-shell first impression.
8. **Demo data cleanup note** — a one-line instruction for the user on how to clear the seeded data when real traffic starts flowing: the dashboard's 全削除 button handles `lp_entries`, and `DELETE FROM lp_page_views WHERE user_agent LIKE '%fake-backfill%' AND lp_slug='{slug}'` handles the rest.

The user's first action after seeing this message should be: open the live URL, glance at the LP, approve → send the `/admin?first` URL to the client via email/Slack/LINE/iMessage. The OG preview will auto-unfurl to "株式会社{client} 採用LP · 初期設定" with the client's own hero image (metadata is generated server-side in `generateMetadata` on the admin page). The client clicks the link, clicks Google sign-in, authorizes, and is done — they land in the dashboard with a brand-new sheet in their Drive, all admin rights, and ownership of the LP. Total time: ~30 seconds from click to working dashboard.

---

## Required infrastructure (must exist before this skill runs)

These are already in place as of 2026-04-09. The skill assumes them.

| Thing | Where | Purpose |
|---|---|---|
| nippo-sync repo | `/home/ubuntu/nippo-sync/` (Jayden's) | Hosts the `/lp/[slug]` route + admin editor |
| nippo-sync prod | `https://nippo-sync.vercel.app` (Vercel project `prj_le2vOYHWk48qXpSiVzaMGIzDs2Dc`, team `team_InumbXmdUdRp3WpMs47TFd8s`) | Where the LPs actually live |
| Supabase project | `pglaffdnhixmabcjdxbi` (`nippo-sync`) | Single source of truth for all LP data |
| `public.lps` table | Master registry — one row per LP | `slug` PK, `client_name`, `status`, `reference_url`, `custom_domain`, `handed_over_at` (one-shot lock), `handed_over_by_email`, `domain_last_status`, `domain_last_checked_at`, `domain_last_error`, `created_via='skill'` |
| `public.lp_content` table | JSONB content blob keyed by `lp_slug` | The rendered LP pulls from this. Has a trigger that auto-inserts into `lp_content_revisions` on UPDATE — every edit is audit-logged, so rollback is possible |
| `public.lp_admins` table | Who can manage each LP | Insert Jayden as `owner` + `jayden.barnes.cs@gmail.com` as `member` on bootstrap. Stores `google_refresh_token` / `google_access_token` / `google_token_expiry` — this is where sheet sync auth lives |
| `public.lp_entries` table | Form submissions from applicants | Append-only; bulk-delete button in dashboard for clearing test data |
| `public.lp_page_views` table | Page view tracking for analytics dashboard | `lp_slug`, `viewed_at`, `session_id`, `path`, `referrer`, `referrer_domain`, `user_agent`, `device_type`, `country`. RLS allows public INSERT (tracking pixel). Indexed on `(lp_slug, viewed_at DESC)` and `(lp_slug, session_id, viewed_at)` for unique-visitor queries |
| `public.lp_form_events` table | Form lifecycle tracking for conversion funnel | `lp_slug`, `event_type` ∈ {`form_view`, `form_start`, `form_submit`}, `occurred_at`, `session_id`, `path`. RLS allows public INSERT. Form submits are also tracked here in addition to `lp_entries` because the form may fail to insert but we still want to know the user tried |
| `public.lp_sheet_configs` table | Google Sheet per LP | One row per slug; points at the sheet ID + URL + owner_email. Gets overwritten on client handover to point at a fresh sheet in the client's Drive |
| `public.lp_content_revisions` | Auto-populated audit log | Populated by a trigger on `lp_content` UPDATE — no manual writes needed |
| `public.industry_presets` | Welfare items, data pills, hero EN titles for fallback | Row `製造業/default` is the current fallback; eventually add `default/default` + per-industry rows |
| `lp-assets` Storage bucket | Public-read, where all skill-generated images land | Long-term goal: every image URL in `lp_content` points here, not at the client's site |
| Supabase MCP access | `execute_sql` + `apply_migration` | No HTTP endpoint or migration secret needed from Claude — direct DB access |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Vercel env + Doppler `nippo-syncro-kun/dev` | For OAuth during handover + sheet creation |
| `VERCEL_TOKEN` | Vercel env (encrypted, all 3 targets) + Doppler `nippo-syncro-kun/dev` | Required by `/api/lp/[slug]/admin/domain-attach` to call Vercel Domains API |
| `AUTH_SECRET` | Vercel env | HMAC signing key for OAuth state tokens + session cookies |
| Google Cloud Console | OAuth consent screen + client credentials | Redirect URI: `https://nippo-sync.vercel.app/api/sheets/connect/callback`. Scopes: `drive.file`, `userinfo.email`, `openid`. Consent screen should be PUBLISHED (not in testing mode) so new clients can sign in without being on the allowlist |

---

## Workflow — single shot, no checkpoints, target <2min

The skill orchestrator is `scripts/bootstrap.py` on the VM at `/home/ubuntu/mgc-saiyo-lp-bootstrap/`. Claude invokes it via `Custom Proxy:server_exec` with the parsed args.

1. **Parse intent** from user message → `{client_name, primary_url, style_url?, industry_hint?}`
2. **Resolve slug** — kebab-case from client name (strip 株式会社, 有限会社, スペース, etc.), validate `^[a-z0-9-]{1,64}$`, abort with clear error if collision in `lps` table (unless user said "overwrite")
3. **Insert lps row** — `status='draft'`, `created_via='skill'`, with `reference_url`, `style_reference_url`, `client_name`
4. **Parallel kick-off**:
   - Job A: Aura `extract_design` on `primary_url` (background)
   - Job B: Aura `extract_design` on `style_url` if provided (background)
   - Job C: `crawl_reference.py` on `primary_url` — multi-page web_fetch crawl
5. **Multi-page content crawl** — homepage + sub-pages matching `/about`, `/company`, `/recruit`, `/saiyo`, `/news`, `/message`, `/profile`, `/business`, `/service` (cap 8 sub-pages). Build a `ContentBundle`:
   ```
   {
     company_name, address, tel, email,
     representative_message,
     business_descriptions[],
     existing_jobs[]?,
     existing_employee_voices[]?,
     existing_news[],
     paragraph_pool[],
     image_pool[]      // all candidate images with URL + dimensions
   }
   ```
6. **Industry detection** — from ContentBundle text + Aura design vibe, infer industry → load matching `industry_presets` row (fallback `製造業/default`, eventually `default/default`)
7. **Await Aura results** with 90-second timeout. **If Aura succeeds**, use its colors + asset URLs. **If Aura fails or times out** (this WILL happen — cloq.jp times out at 120s), fall back to `extract_design.py`'s CSS parser:
   - `web_fetch` the page
   - Parse `<style>` tags + external CSS for the most common color values
   - Extract `<img>` srcs
   - Extract Open Graph image
   - Extract favicon (bundle.favicon_url via extract_favicon())
   - Extract company logo (bundle.logo_url via extract_logo()) — strategies in priority order:
     1. `<img class="custom-logo">` — WordPress theme standard
     2. `<a class="*logo*|brand|site-title"> <img>` — brand link pattern
     3. `<img class="*logo*">` — generic logo class
     4. `<img alt="{company_name}">` inside `<header>` — alt-text match
     5. `<img src="*logo*">` — src pattern match (excluding favicon variants)
     6. highest-resolution `<link rel="icon">` — favicon fallback
     7. `<link rel="apple-touch-icon">` — final fallback
8. **Compose LpContent draft** (`compose_lpcontent.py`) — produces a structural draft, NOT the final content:

   **Fields the composer fills correctly without review** (use as-is):
   - `meta.title`, `header.company_name`, `header.logo_letter` ← ContentBundle.company_name
   - `header.logo_image` ← bundle.logo_url (real company logo extracted by `extract_logo()` — WordPress custom-logo class, brand-link <img>, header <img> with matching alt, favicon fallback). When present, the renderer shows the actual logo image in the header; `logo_letter` remains as a graceful fallback
   - `theme.primary/accent/accent2` ← Aura or CSS fallback (from extract_design.py)
   - `footer.address` ← scraped via 〒 regex
   - `footer.founded` ← bundle.founded (extracted from 設立 / 創業 in 会社概要 dl)
   - `footer.representative` ← bundle.representative (extracted from 代表者 / 代表取締役 in 会社概要 dl)
   - `footer.business` ← bundle.business_type (主な事業内容 in 会社概要 dl)
   - `welfare.items` ← bundle.job_details when 募集要項 dl is present (real welfare items, not preset defaults)
   - `openings.items[0]` + `.detail.requirements` ← bundle.job_details when 募集要項 dl is present (real role + 8-line 募集要項 table)

   **Fields that need Claude review BEFORE insert** (see step 8.5 — audience pivot):
   - `hero.jp_tagline`, `hero.subtext`
   - `about.headline`, `about.paragraphs`
   - `strengths.items` (especially the title + body of each)
   - `cta.headline`, `cta.sub`

   **Fields with placeholders** (flagged for user polish in admin editor):
   - `voices.items` ← single placeholder; real photos via follow-up nano-banana step
   - `data.items` ← industry preset defaults
   - `map_embed_src` ← empty

8.5. **Audience pivot review** — THIS IS THE STEP YOU CANNOT SKIP. Read the composer output and rewrite the audience-sensitive sections (hero, about, strengths, cta) BEFORE inserting into Supabase. See RULE 9 for the full rationale, but the short version:

   The composer naively copies paragraphs from the source site into hero/about/strengths. If the source is a B2B service business (consulting firm, agency, SaaS company), those paragraphs are pitching services to **CLIENTS**, not pitching the company as an employer to **JOB SEEKERS**. Verbatim copying produces a 採用LP with the wrong 対象 — the strengths section reads like sales copy.

   Claude's job at this step:
   1. Read ContentBundle.business_descriptions, .representative_message, and .paragraph_pool to understand what the company DOES and what they VALUE.
   2. Read bundle.job_details for the 求める人物像 + 福利厚生 → these are the real job-seeker hooks.
   3. Rewrite hero.jp_tagline, hero.subtext, about.headline, about.paragraphs, strengths.items, cta.* to be from a job-seeker's perspective: "what you'll learn here", "what this team values", "how this company works", "what's in it for you". NOT "what we sell to clients".
   4. Set provenance.audience_pivot_review_needed = false in the final payload.
9. **Image pipeline** — see image strategy table below
10. **Insert via Supabase MCP** (single transaction preferred) — use `Supabase:execute_sql` against project `pglaffdnhixmabcjdxbi`:
    1. `INSERT INTO public.lps` if not already done in step 3
    2. `INSERT INTO public.lp_content (lp_slug, content, published) VALUES (...)` with the AUDIENCE-REVIEWED LpContent as a `$LPCONTENT$...$LPCONTENT$::jsonb` dollar-quoted literal (avoids escaping the Japanese + nested quotes mess)
    3. `INSERT INTO public.lp_admins (lp_slug, email, role)` for `jayden.barnes@mgc-global01.com` as `owner` AND `jayden.barnes.cs@gmail.com` as `member`. Without this row the `/lp/{slug}/admin` page treats the LP as nonexistent (the `fetchCompanyAndExists` function checks lp_admins as one of the existence signals).
    4. `UPDATE public.lps SET status = 'live' WHERE slug = '{slug}'`

10.5. **Create Google Sheet for entries auto-sync — BEST-EFFORT, not required** — read Jayden's existing Google OAuth tokens from `lp_admins` and try to create an initial sheet in Jayden's Drive. This gives Jayden a sheet to watch for any test entries between bootstrap and the client's handover — but it's **intentionally replaced** by a fresh sheet in the client's own Drive when they claim ownership via `/admin?first` (see step 12.5). So if this step fails for any reason (Jayden hasn't re-OAuthed recently, Google API 503, scope issue, quota), **continue the bootstrap anyway and log it in provenance as `sheet_initial: "failed"`**. The client will create their own sheet on handover regardless.

    Pre-flight check: `SELECT google_refresh_token FROM lp_admins WHERE email='jayden.barnes@mgc-global01.com' LIMIT 1`. If NULL, skip this step entirely and log `sheet_initial: "skipped_no_tokens"` in provenance. Do NOT try to refresh — just skip.

    If tokens exist:
    1. Fetch `google_access_token` for `jayden.barnes@mgc-global01.com`. If `google_token_expiry` < now, refresh it via `https://oauth2.googleapis.com/token` using `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` from Doppler (`nippo-syncro-kun/dev`) plus the stored refresh_token.
    2. POST to `https://sheets.googleapis.com/v4/spreadsheets` with `{"properties": {"title": "{client_name} - 採用エントリー", "locale": "ja_JP", "timeZone": "Asia/Tokyo"}, "sheets": [{"properties": {"title": "Entries"}}]}`. The sheet lands in jayden.barnes@mgc-global01.com's Drive.
    3. PUT the LP_ENTRY_HEADERS row to `/spreadsheets/{id}/values/Entries!A1?valueInputOption=USER_ENTERED`. Headers: `["ID","応募日時","LP Slug","会社名","お名前","メール","電話","職種","志望動機","ステータス","内部メモ","Source"]`
    4. INSERT into `public.lp_sheet_configs` with `connection_type='oauth'`, `auto_sync=true`, `worksheet_name='Entries'`, `last_sync_status='success'`, `last_synced_count=0`. After this, every form submission to `/api/lp-entry` will auto-append to the sheet via the existing handler logic.

    **The old bootstrap sheets in Jayden's Drive become orphaned after each client handover.** They're not deleted — just no longer linked in `lp_sheet_configs`. Jayden can manually clean them up from his Drive once a quarter or so.
11. **Verify** — GET `https://nippo-sync.vercel.app/lp/{slug}`, confirm 200 + content renders
12. **Verify the admin entrypoint** — GET `https://nippo-sync.vercel.app/lp/{slug}/admin`, confirm it returns the ConnectScreen (sign-in prompt) and NOT the "LPが見つかりません" 404 screen. If the latter, the lp_admins insert in step 10.3 was skipped — go back and insert it.
12.5. **First-setup URL is deterministic and OAuth-driven — no code changes needed** — as of `nippo-sync@53a7338` the client-handover URL is always `https://nippo-sync.vercel.app/lp/{slug}/admin?first`, no token, no expiry. Every LP in `public.lps` has this URL available immediately after the registry insertion in step 3 (the `lps` row creation).

    The screen's primary CTA is a **Google sign-in button** that routes through `/api/sheets/connect/{slug}/authorize?first=1`. The authorize endpoint encodes the firstFlag into a 4-part HMAC-signed state token (`slug.nonce.1.sig`), which the OAuth callback at `/api/sheets/connect/callback` decodes to distinguish the first-claim handover flow from regular sign-ins.

    On successful Google sign-in, the callback runs a single atomic transaction:
    1. `SELECT ... FOR UPDATE` on `public.lps` (race-safe against concurrent claims)
    2. Verify `handed_over_at IS NULL` (one-shot lock check)
    3. DEMOTE existing owners to `member` via `UPDATE role='member'` (preserves `google_refresh_token` so the old sheet stays accessible to Jayden as a demoted member)
    4. UPSERT the OAuth user as `owner` with their fresh access/refresh tokens
    5. **Create a brand-new spreadsheet in the OAuth user's own Drive** via `createSpreadsheet(tokens.access_token, sheetTitle)` — explicitly NOT reusing Jayden's existing sheet
    6. Copy existing `lp_entries` into the new sheet (best-effort, non-fatal if it fails)
    7. UPSERT `lp_sheet_configs` to point at the NEW sheet, overwriting the old pointer
    8. SET `lps.handed_over_at = now()` + `handed_over_by_email` (the lock)

    **Critical safety property**: the one-shot lock is committed INSIDE the same transaction as all the other mutations. If ANY step fails (token exchange, sheet creation, DB insert, or even the user cancelling the Google consent screen), the lock stays `NULL` and the `?first` URL remains valid for retry. A click on the ?first URL alone cannot burn the lock — only a fully successful OAuth round-trip does. OG crawlers, accidental clicks, cancelled consent screens, and "I'll come back later" tab-closes are all safe.

    An email-only fallback (`POST /api/lp/{slug}/admin-first-setup`) is available behind a collapsible "Googleアカウントがない場合" link for clients without Google, with a confirm() dialog warning about typos locking them out forever. That path DELETEs `lp_sheet_configs` on claim (since it can't create a new sheet without the client's Google tokens) — the client then sees a "Connect Google Sheets" prompt on the dashboard and can set up their own sheet later.

    **No code changes needed for this step.** Just include the URL in the handoff message in step 13.

12.7. **Analytics bootstrap + demo seed** (RULE 20 + RULE 21) — run `scripts/analytics_bootstrap.py --slug {slug} --seed-demo` via `Custom Proxy:server_exec`. This script does 4 things:

    1. **Verify analytics infrastructure exists** — checks `lp_page_views` + `lp_form_events` tables, their indexes, and the RLS policies. If any are missing, applies the `lp_analytics_page_views` migration via Supabase MCP.
    2. **Verify tracking pixel is wired in production** — curls `/lp/{slug}` + `/lp/{slug}/jobs/0` + `/lp/{slug}/entry` and greps for `lp_sid_{slug}` and `track('form_view')`. If any are missing, the nippo-sync build has drifted from the spec — report to user and halt (do NOT try to auto-patch lp-render.ts from the skill, it's owned code).
    3. **Verify `/api/lp/{slug}/track` endpoint responds 204** by POSTing a `{"event_type":"page_view","session_id":"bootstrap-test","path":"/lp/{slug}"}` payload, then DELETEs the test row from `lp_page_views`.
    4. **Seed realistic demo data** — 15 entries + ~3,000 page views + ~800 form_views + ~280 form_starts over the last 30 days. All seeded rows are tagged with `user_agent LIKE '%fake-backfill%'` so the client can bulk-delete them with a single SQL in 2 seconds OR ignore them via the 全削除 button. Seeding takes <5 seconds because it's all done with one INSERT ... SELECT generate_series query per table.

    The script is idempotent — if run twice it will skip the migration (tables already exist) and append another 15 entries (realistic for a growing LP, and the client can still bulk-delete). **DO NOT skip this step even if the user said "no test data" — the analytics verification in 12.7.1-12.7.3 is mandatory.** You can skip 12.7.4 (seed) with `--no-seed` flag if the user explicitly opted out.

13. **Hand off** — return to user:
    - Live URL: `https://nippo-sync.vercel.app/lp/{slug}`
    - Admin URL: `https://nippo-sync.vercel.app/lp/{slug}/admin`
    - **First-setup URL for client** (from step 12.5): `https://nippo-sync.vercel.app/lp/{slug}/admin?first` — send this via email/Slack/LINE/iMessage. The OG preview unfurls as "株式会社{client} 採用LP · 初期設定" with the client's hero image. On click → Google sign-in → ~30 seconds later the client is the owner, has a brand-new Google Sheet in their own Drive, and Jayden is demoted to member (tokens preserved so the old sheet is still accessible if needed). The URL is safe to click/preview — only a fully completed OAuth round-trip burns the one-shot lock.
    - Provenance report (which fields are scraped vs preset vs AI, including `logo: scraped|fallback_letter`)
    - Image source breakdown (scraped/enhanced/generated/unsplashed counts)
    - **Demo data disclosure** — "このダッシュボードは、引き渡し時点で **デモ用のサンプルデータ**（過去30日分の閲覧数、応募者15件）で埋められています。本物のアクセスが流れ始める前に、応募管理の **🗑️ 全削除** ボタンと Supabase の `DELETE FROM lp_page_views WHERE user_agent LIKE '%fake-backfill%' AND lp_slug='{slug}'` でクリアしてください。" (only if 12.7.4 seed ran — skip this line if `--no-seed` was used)
    - **Analytics verification** — confirm the 4 checks from step 12.7 all passed (tables, pixel, endpoint 204, seed 15+3000+800+280 or whatever the actual counts are)
    - Suggestion: "After polishing, run `/save-preset {industry}` to update the preset"

---

## Image strategy mix

| Slot | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| `hero.bg_image` | Best scraped client photo → nano-banana enhance to 16:9 cinematic recruitment vibe | Scraped photo as-is | nano-banana fresh generate |
| `about.photo` | Scraped client about/company photo → nano-banana light enhance | Scraped as-is | nano-banana fresh |
| `voices[].photo` × 3 | Scraped staff photos → nano-banana enhance for consistency | nano-banana fresh generate (consistent style across all 3) | Unsplash (last resort) |
| `openings[].image` × N | Scraped client workplace photos → nano-banana enhance per job context | nano-banana fresh | Unsplash (last resort) |
| Decoratives (textures, dividers, news thumbs) | Unsplash | — | — |

**All final image URLs MUST point to the lp-assets Supabase Storage bucket.** Upload everything (scraped, enhanced, generated, unsplashed) into `lp-assets/{slug}/...` and write `lp_assets` pointer rows. We own our assets.

---

## Hard rules

**RULE 1 — Speed over perfection.** The editor exists for the last 10%. Default is "ship aggressive, refine in editor." Do NOT ask for confirmation mid-flow.

**RULE 2 — Aura is best-effort.** It will time out or fail on some sites (confirmed: cloq.jp times out at 120s). When Aura fails, use the CSS fallback in `extract_design.py`. Never block on Aura.

**RULE 3 — Never overwrite an existing lps row** without explicit "overwrite" from user. Slug collision = abort with helpful message.

**RULE 4 — Always create the lps row first** (workflow step 3). Even if everything downstream fails, the draft exists for retry. Idempotent on slug.

**RULE 5 — Every AI-generated field is logged** in the provenance report. User must always know what's hallucinated and what's real.

**RULE 6 — Images SHOULD go through lp-assets bucket (v1 goal).** The long-term target is that every image in `lp_content` is hosted on the `lp-assets` Supabase Storage bucket so we own our assets. For v0, raw scraped URLs from the client's site are acceptable as long as they're flagged in provenance — image migration runs as a follow-up step after the LP is verified live.

**RULE 7 — Industry preset auto-update is OPT-IN.** After polishing, the system suggests "save these as the new {industry} default preset?" but never auto-saves.

**RULE 8 — Reference URL is the client's OWN site by default.** A second `style_url` is optional and only affects design tokens (theme colors, font hints), never content.

**RULE 9 — Audience pivot is mandatory before insert.** The composer is a structural draft, not the final content. Whenever the source site is a B2B service business (consulting, agency, SaaS, anything that sells *to other businesses*), its homepage paragraphs are pitching services to *clients*, NOT recruiting *job seekers*. Verbatim copying produces sales copy in the strengths section instead of employer branding. Claude MUST review and rewrite hero/about/strengths/cta from a job-seeker frame at workflow step 8.5 BEFORE the Supabase insert. The composer always sets `provenance.audience_pivot_review_needed: true` as a reminder — Claude flips it to false only after rewriting. The cloq pivot is the canonical example: client-facing "we deeply understand your hiring problem, we PDCA your funnel" was rewritten as candidate-facing "you'll get hands-on実務スキル, work in a flat 本音-driven team, in a 在宅可・服装自由 environment".

**RULE 10 — Handover uses the `/admin?first` URL with Google OAuth as the primary path.** For first-time client handover, the skill returns the deterministic URL `/lp/{slug}/admin?first` in the handoff message (workflow step 13). The URL is always the same for a given slug and is always ready from the moment the `lps` row exists (step 3). The screen's primary CTA is a Google sign-in button — not an email form — because Google auth gives us three things the email flow can't: (a) verified email with zero typo risk, (b) fresh tokens to create a new sheet in the CLIENT's Drive (not Jayden's), and (c) permissions to drive the existing Google Sheets connector automatically. The OAuth callback atomically DEMOTEs Jayden's pre-seeded admin rows to `member` (preserving `google_refresh_token` so the old sheet is still accessible), UPSERTs the client as owner with THEIR tokens, creates a brand-new sheet in the client's Drive via `createSpreadsheet(clientAccessToken)`, copies existing entries, and sets the one-shot lock. An email-only fallback exists as a collapsible secondary option for clients without Google accounts — it deletes `lp_sheet_configs` since it can't create a new sheet without OAuth tokens, and the client connects Google Sheets from the dashboard later. **Never describe the first-setup URL as "an email form" — always describe it as "Google sign-in with email fallback".**

**RULE 11 — `/admin?first` is one-shot but only burns on a SUCCESSFUL sign-in, not on a click.** The `lps.handed_over_at` lock is committed INSIDE the same atomic transaction as the demote/upsert/create-sheet mutations in the OAuth callback. If ANY step fails — token exchange error, sheet creation API error, DB insert error, user cancelling Google consent, network timeout, browser tab close mid-flow — the lock stays `NULL` and the URL remains valid for retry. This means: OG crawlers (Slack, iMessage, LINE) fetching the URL for link previews are safe; accidental clicks are safe; "let me check this later" tab-closes are safe. Only a fully successful OAuth round-trip burns the lock. Once burned, the URL returns the "引き渡し済みです" amber lock screen with the timestamp and handed_over_by_email — there is no reset API, no reset SQL shortcut, no dashboard button. Subsequent handoffs happen via the normal invite flow in the admin dashboard (owner → member invitation). If the user asks to "reset" or "regenerate" the first-setup link for an already-claimed LP, Claude MUST refuse and explain that this is by design — the only recovery paths are: (a) the current owner invites a new admin via the dashboard, or (b) Jayden edits the `lps.handed_over_at` column directly via Supabase MCP as an emergency override (document this clearly to the user, never do it silently).

**RULE 12 — Custom domain setup is one-click via the dashboard, not a manual SQL/DNS ritual.** As of `nippo-sync@53a7338` the client's dashboard has a full Vercel domain automation flow in the Settings panel. The skill itself does NOT set up custom domains during bootstrap — we don't know the client's domain yet, and it's an owner-only action. Instead, Claude tells the user during handoff that the client can set up a custom domain themselves via the dashboard:

1. Client enters the domain in the カスタムドメイン field and clicks 保存
2. Client clicks the **🚀 Vercelに登録する** button — the endpoint `POST /api/lp/{slug}/admin/domain-attach` calls Vercel's `/v10/projects/{id}/domains` API to register the domain
3. The UI shows a DNS card with the exact CNAME or A record the client needs to add at their DNS provider (お名前.com, Cloudflare, Route53, etc.), with per-field copy buttons. For domains that were previously on another Vercel account, an extra TXT verification record is also shown (via the `vercel_verification` array from the /v9 response)
4. Client adds the record, waits for propagation (5-30 min typical), clicks **🔍 DNS設定を確認する** — the endpoint polls Vercel's `/v6/domains/{domain}/config` for the REAL DNS status. CRITICAL: the `/v9` `verified` field is misleading — it returns `true` for any attached domain regardless of actual DNS. The authoritative field is `configuredBy` from `/v6`, which returns `'A' | 'CNAME' | 'HTTP' | null`
5. Once `configuredBy` is non-null, the UI turns green showing the specific record type that's working, and Vercel auto-issues an SSL cert via Let's Encrypt within ~1 minute
6. Until DNS is active, the dashboard surfaces the nippo-sync URL as the canonical share URL via the existing HTTP health check

The Vercel API credentials (`VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`) are already in the Vercel project env vars. The defaults in code are `prj_le2vOYHWk48qXpSiVzaMGIzDs2Dc` / `team_InumbXmdUdRp3WpMs47TFd8s`.

**DO NOT attempt to automate custom domain setup as part of the skill's workflow**, even if the user mentions a specific domain in their prompt. Reasons: (a) only the owner (client, post-handover) should be attaching domains to their LP, (b) DNS changes belong to the client's registrar and aren't something we can touch, (c) the Vercel API call is tied to a session cookie so it can only run post-login. If the user says "set up the domain recruit.cloq.jp", Claude should mention it in the handoff polish checklist as a recommended manual step the client should do from their dashboard.

**RULE 13 — Full SEO stack is already baked into `lp-render.ts` — never re-implement, never inherit root layout defaults.** As of 2026-04-21 every LP rendered by `lp-render.ts` automatically gets the full SEO set below. Do NOT add these manually — they're already there. Adding them again will duplicate tags.

**What's already baked in for every LP (main page + job detail pages):**

| Tag / Element | Details |
|---|---|
| `<title>` / `<meta name="description">` | Pulled from `lp_content.meta.title` / `meta.description` |
| `<link rel="canonical">` | Points to canonical domain (recruitly.jp subdomain if registered, otherwise nippo-sync.vercel.app/lp/{slug}) |
| Open Graph — 5 tags | `og:type`, `og:url`, `og:title`, `og:description`, `og:site_name`, `og:image` (conditional on hero bg) |
| Twitter Card — 4 tags | `summary_large_image`, `twitter:title`, `twitter:description`, `twitter:image` |
| `og:url` | Matches canonical URL — critical for preventing duplicate content between vercel and recruitly.jp |
| `lang="ja"` | Always set on `<html>` |
| Organization JSON-LD | Main LP only — `@type: Organization` with `name`, `url`, `logo`, `sameAs` from `lp_content` |
| JobPosting JSON-LD | Job detail pages (`/jobs/[index]`) only — full schema with salary, location, employment type |
| BreadcrumbList JSON-LD | Job detail pages only — `採用情報 → {job title}` with correct canonical URLs |
| `<link rel="icon">` | Conditional on `lp_content.header.logo_image` |

**What's baked in at the app level (not per-render):**
- `robots.txt` at `/public/robots.txt` — allows `/lp/*`, disallows `/lp/*/admin`, `/lp/*/entry`, `/lp/*/privacy`, `/dashboard`, `/api/*`
- `sitemap.xml` at `src/app/sitemap.ts` — dynamic, queries all published LPs from Supabase, includes main LP + all job detail pages with canonical URLs
- Admin pages: `robots: { index: false, follow: false }` via `generateMetadata()` in `app/lp/[slug]/admin/page.tsx`

**Never add new top-level LP routes** without also setting explicit OG + canonical tags — otherwise they'll inherit the root layout's `'日報シンクロくん'` default. Verify with `curl $URL | grep og:title` before shipping.

**RULE 15 — recruitly.jp subdomain deployment: timing, process, and required code changes.**

MGC hosts client LPs under `{slug}.recruitly.jp` (e.g. `cloq.recruitly.jp`). This is separate from the client's own custom domain flow (RULE 12) — recruitly.jp is MGC's own domain used as a professional branded URL before (or instead of) the client setting up their own domain.

**When to deploy:** Only after the client has confirmed the LP is ready to go live. Do NOT set up the subdomain speculatively during bootstrap — the vercel URL (`nippo-sync.vercel.app/lp/{slug}`) is sufficient for review and iteration.

**Who creates the DNS record:** Currently Jayden asks 松尾さん to add the CNAME at recruitly.jp's DNS provider (muubuu). In future Jayden will have direct access to muubuu to do this himself. The record needed is:
```
{slug}.recruitly.jp  CNAME  cname.vercel-dns.com
```

**Code changes required in nippo-sync (2 files, then git push):**

1. **`src/lib/lp-domains.ts`** — add the slug → canonical domain mapping:
```typescript
const CUSTOM_DOMAINS: Record<string, string> = {
  cloq: 'https://cloq.recruitly.jp',
  {slug}: 'https://{slug}.recruitly.jp',  // ← add this
}
```
This makes all canonical URLs, `og:url`, Organization JSON-LD, Breadcrumb JSON-LD, and internal links (job cards, nav, CTA buttons) automatically point to the recruitly.jp domain instead of the vercel URL.

2. **`src/middleware.ts`** — add routing for the new subdomain so requests to `{slug}.recruitly.jp` are rewritten to `/lp/{slug}`:
```typescript
if (host === '{slug}.recruitly.jp') {
  if (pathname.startsWith('/_next/') || pathname.startsWith('/api/')) {
    return NextResponse.next()
  }
  const mapped =
    pathname === '/' || pathname === ''  ? '/lp/{slug}'
    : pathname === '/admin'             ? '/lp/{slug}/admin'
    : pathname === '/privacy'           ? '/lp/{slug}/privacy'
    : pathname === '/entry'             ? '/lp/{slug}/entry'
    : pathname.startsWith('/jobs/')     ? `/lp/{slug}${pathname}`
    : null
  if (mapped) {
    const url = req.nextUrl.clone()
    url.pathname = mapped
    return NextResponse.rewrite(url)
  }
  return new NextResponse(BRANDED_404_HTML, { status: 404, headers: { 'content-type': 'text/html; charset=utf-8' } })
}
```
(Copy the cloq block as a template and swap `cloq` → `{slug}`. Also create a branded 404 HTML constant for the new client matching their brand colors.)

3. **Vercel domain registration** — after pushing the code, register the domain in Vercel so it routes correctly. The domain-attach endpoint at `POST /api/lp/{slug}/admin/domain-attach` handles this, OR do it manually via the Vercel dashboard under the nippo-sync project → Domains → Add.

**Full checklist:**
1. ✅ Client confirms LP is ready
2. ✅ Ask 松尾さん (or use muubuu directly when access granted) to add CNAME: `{slug}.recruitly.jp → cname.vercel-dns.com`
3. ✅ Update `src/lib/lp-domains.ts` — add slug → domain entry
4. ✅ Update `src/middleware.ts` — add routing block for new subdomain
5. ✅ `git push origin main` → Vercel auto-deploys
6. ✅ Register domain in Vercel (dashboard or domain-attach API)
7. ✅ Wait for DNS propagation (5–30 min typical)
8. ✅ Verify: `curl -sI https://{slug}.recruitly.jp` → HTTP 200, then `curl -s https://{slug}.recruitly.jp | grep canonical` → should show `https://{slug}.recruitly.jp`

**RULE 14 — Images should be 融合 of original style + generated content, NOT reused homepage photos.** The cloq build violated this on first pass — I grabbed images from cloq.jp's existing pages and stuck them on the 採用LP as-is. That's lazy and produces a LP that looks like a 切り貼り (cut-and-paste) of the client's existing site. The correct approach:

1. **KEEP the style** from the reference site: colors, typography, layout feel, logo placement, section hierarchy. These come from `extract_design.py` + Aura + the scraped CSS tokens. Don't touch.
2. **GENERATE new images** based on the company's actual concepts via nano-banana-proxy skill. The prompt should reference what makes THIS company THIS company: their industry, their values (from `bundle.representative_message` + `business_descriptions`), their culture (from scraped job_details 求める人物像). A recruitment consultancy's 採用LP hero should show "recruitment consulting with candidates in a modern Kyoto office", not their homepage's generic business banner.
3. **USE scraped photos only when they're genuinely workspace-specific** — actual building exteriors, actual desks with people working, actual team photos. NOT marketing hero banners, NOT stock-photo-looking abstracts, NOT the site's og:image. The test: "would this photo make sense in a job-seeker context?" Building photo = yes. Homepage hero banner = no.
4. **Position images** (one per opening) should be **generated fresh per role** via nano-banana. A "採用支援スタッフ" role gets an image of a support staffer working with candidates; a "採用クリエイター" role gets an image of a writer at a laptop drafting copy. NOT a generic homepage image used twice.
5. **About photo** can be a real company building photo if one exists, otherwise generate.
6. **Voices[].photo** — always generated placeholders unless the client provides real employee photos with consent. Flag as `voices_photo: "ai_placeholder"` in provenance.

The image pipeline hasn't been folded into `scripts/` yet — it's a manual step invoking the `nano-banana-proxy` skill after the text content is inserted. Until it's folded in: document it in the polish checklist at handoff and actually RUN the generation before declaring the LP ready to hand over. **Never ship a LP with pure scraped-homepage-reuse images.**

**RULE 15 — NEVER use the `spreadsheets` OAuth scope or any other sensitive scope.** See Critical Constraints #2 above. This is a non-negotiable: adding it back kicks us into Google's verification track and costs weeks of calendar time. `drive.file` + `userinfo.email` + `openid` is the complete allowed list. If a future feature seems to need `spreadsheets` scope, find a way to do it with `drive.file` instead — the app is always the creator of any sheet it touches, and `drive.file` is sufficient for every operation on app-created files.

**RULE 16 — NEVER use fire-and-forget IIFE patterns in Vercel API routes.** See Critical Constraints #3. Any async side effect in `/api/*` must be `await`'d inline or wrapped in `waitUntil()`. The Vercel lambda kills unawaited async the moment the function returns.

**RULE 17 — NEVER name static LP fallbacks `index.html`.** See Critical Constraints #4. Always use `_legacy-index.html.bak` or similar. Static files in `/public/` override dynamic app router routes.

**RULE 18 — drive.file revoke recovery via `/api/admin/reset-lp-claim`.** When a client revokes the app's grant in their Google account permissions page (https://myaccount.google.com/permissions), ALL drive.file file-authorizations are wiped for that user. The sheet itself remains in their Drive but every subsequent API call returns 404 even though the file is right there. This is a Google security property, not a bug.

**Recovery path** (one-shot, gated by migration secret):
```bash
curl -X POST "https://nippo-sync.vercel.app/api/admin/reset-lp-claim?slug={slug}" \
  -H "x-migration-secret: $(doppler secrets get MIGRATION_SECRET --project nippo-syncro-kun --config dev --plain)"
```

This deletes the `lp_admins` owner row + `lp_sheet_configs` row for the slug. `lp_entries` are left intact. The next sign-in runs the claim flow fresh and creates a new sheet that the refreshed Google grant can access.

**BUT**: if `lps.handed_over_at` is already set, the ?first URL is burned and only `lp_admins` DELETE + ALSO setting `handed_over_at = NULL` will allow a fresh claim. Be explicit with the user about this emergency override and log why it was needed.

Precedent: commit `65c6992` — endpoint added during Phase 3 debugging after Jayden revoked access during testing.

**RULE 19 — The admin dashboard is a self-contained Lovable file — treat it as owned code, not UI primitives.** `src/app/lp/[slug]/admin/AdminDashboard.tsx` inlines everything: Button, Input, Select, DropdownMenu, Sheet, Sidebar (full shadcn implementation with TooltipProvider/SidebarContext/keyboard shortcut), useIsMobile hook, cn() helper, STATUS_LABELS, all 5 section components, the AdminContext with 20+ state fields + 15+ action callbacks, PDF export helpers, CSV export, and the AdminDashboard wrapper function. It's ~2400 lines and that's fine. Do NOT split it into separate files "for cleanliness" — the whole point of the Lovable pattern is that the dashboard is one self-contained unit that can be regenerated from Lovable, pasted in, and wired through AdminContext without hunting across 40 imports. When a client wants a design refresh, Jayden goes to Lovable, generates a new `Index.tsx`, and we do the same surgical wiring (add `'use client'`, wire props through AdminContext, import LpContentEditor into LpEditSection, find-replace mock data). Splitting would break this workflow. Precedent commits: `dc43c56` (wiring), `dc7d513` (analytics + landing).

**RULE 20 — Real analytics pipeline is now mandatory infrastructure, not an optional feature.** Every new LP bootstrap MUST ensure the tracking pixel is injected, the aggregation endpoint returns valid data, and the client's dashboard shows populated charts from day 1. The stack has 4 parts that MUST all exist and be wired correctly:

1. **Database**: `public.lp_page_views` + `public.lp_form_events` tables (created in migration `lp_analytics_page_views`, apply via Supabase MCP if missing)
2. **Tracking pixel**: baked into `src/lib/lp-render.ts` (2 `</body>` injections: main LP + job detail) + `src/app/lp/[slug]/entry/route.ts` (1 injection: entry form with full lifecycle — page_view, form_view, form_start, form_submit via monkey-patched `fetch`). The pixel generates `session_id` from `sessionStorage` and fires keepalive POST requests to `/api/lp/{slug}/track` so it survives the page unload for form_submit.
3. **Tracking endpoint**: `POST /api/lp/[slug]/track` accepts `{event_type, path, session_id, referrer}`, auto-detects device from UA, extracts referrer domain, captures country from `x-vercel-ip-country` header, writes to the appropriate table, always returns 204 (tracking errors must never block the LP). CORS preflight is handled.
4. **Aggregation endpoint**: `GET /api/lp/[slug]/admin/analytics?days=30` (auth via `lp_admin_<slug>` cookie) returns `{views_by_day, traffic_sources, device_split, funnel, totals}`. Traffic sources are bucketed into Japanese labels (Google検索 / Bing検索 / Twitter/X / LinkedIn / Facebook / Instagram / その他 / 直接アクセス). Timestamps are bucketed in `Asia/Tokyo` timezone. The dashboard's `DashboardSection` auto-loads on mount via `useAdmin().loadAnalytics(30)` and wires the result to recharts AreaChart (PV trend with unique visitors overlay), BarChart (traffic sources), funnel cards with dropoff %, and device split cards.

The skill must never ship a LP where any of these 4 parts is missing. Use `scripts/analytics_bootstrap.py` during bootstrap to verify all 4 exist and seed test data. Precedent commit: `dc7d513`.

**RULE 21 — Seed realistic test data on every new LP bootstrap.** A freshly handed-over dashboard that says "0 PV, 0 entries, no traffic" is a bad first impression — the client sees a broken-looking shell and assumes the product is empty. Instead, seed the dashboard with ~2-4 weeks of realistic demo data so the charts look alive the moment they sign in. The seed should include:

- **15 entries** in `lp_entries` with varied statuses (new/seen/contacted/rejected/hired ratio ~4:3:3:3:2), realistic Japanese names, dates spread across the last 27 days, mix of phones, some with messages and some without, positions matching the openings actually in their `lp_content`, some with internal notes
- **~3,000 page views** in `lp_page_views` backfilled over 30 days with a growth trend (40→180 views/day), weekend dips (30% less on Sat/Sun), realistic referrer distribution (Google 40%, direct 30%, Twitter 15%, LinkedIn 10%, Bing/other 5%), device split (mobile 55%, desktop 30%, tablet 15%), paths split between main LP (60%) + /jobs/0 (25%) + /jobs/1 (15%)
- **~800 form_views** in `lp_form_events` (~25% of page viewers see the form — those who scroll past it)
- **~280 form_starts** (~35% of form_views start typing)
- The `form_submits` are the 15 `lp_entries` from above, so conversion = ~0.5% which is realistic for a warm LP

**CRUCIAL**: label all seeded rows so the client can bulk-delete them and so the handover transaction can wipe them automatically. Tagging convention:
- `lp_page_views.user_agent LIKE '%fake-backfill%'`
- `lp_form_events.session_id` references back to those page views (no direct marker, found via JOIN)
- `lp_entries.source = 'lp_form_demo'` (NOT the default `'lp_form'`)

These tags are used by THREE consumers: (1) the OAuth callback handover transaction (`src/app/api/sheets/connect/callback/route.ts`), (2) the email-only fallback transaction (`src/app/api/lp/[slug]/admin-first-setup/route.ts`), and (3) the dashboard's 全削除 button + the `analytics_bootstrap.py` cleanup SQL. All three filter on the same tags, so adding new seed data in the future MUST use these exact tags or it won't get cleaned up.

**Handover automatically resets the analytics.** As of 2026-04-10, both handover paths run the cleanup SQL inside the same atomic transaction as `UPDATE lps SET handed_over_at`. Either everything commits (claim succeeds + demo wiped + client sees empty dashboard ready for real traffic) or nothing commits (claim fails + demo stays for retry). This means: the seed data is visible during the build session for sanity-checking the dashboard, persists through any pre-handover testing, but is automatically wiped the moment the client signs in. No manual cleanup step needed. Precedent: `dc7d513` (initial seed) + `9b22739` (handover cleanup + LATERAL fix).

**RULE 22 — LP編集 section MUST be a two-state landing screen, never a direct jump.** See Critical Constraint #8. The landing card shows: hero CTA with 編集を開始 + 公開中のLPを開く buttons, 4-stat quick grid (PV / 応募率 / 応募総数 / 新規応募 — all from real data via useAdmin), 6-tile section overview (ヒーロー/募集職種/福利厚生/会社情報/メンバーの声/FAQ with icons and descriptions), usage tips card explaining the difference between 「変更をプレビュー」 (in-editor, shows unsaved changes) vs 「公開中のLPを開く」 (live site, shows last saved state). The editor component renders only after clicking 編集を開始 and returns to the landing on `← ダッシュボードに戻る`, NOT to a different section. This prevents the "I opened LP編集 and got dropped into a WordPress clone with no context" confusion.

**RULE 23 — `LpContentEditor` header buttons have strict placement and labeling.** There are exactly 3 navigation/preview buttons in the header and they serve different purposes — the user was confused by the old ambiguous labels, so the fix is in the labels, not the placement. As of `dc7d513`:

1. **`← ダッシュボードに戻る`** (header-left, right after hamburger): styled navy/blue (`#2c3338` bg, `#72aee6` text), returns to `LpEditSection` landing via `onClose()`. Guards unsaved changes with confirm.
2. **`👁 変更をプレビュー`** (header-right, amber): opens in-editor preview modal showing the CURRENT editor state including unsaved changes. Device-switchable (desktop/mobile).
3. **`🌐 公開中のLPを開く`** (header-right, blue): opens the live public LP in a new tab (`target="_blank"`) showing the last SAVED state, NOT unsaved edits. Corresponds to what the client actually serves right now.

Inside opening cards, the per-card **`編集 →`** buttons (blue, right-aligned, one per job) open the nested OpeningDetailEditor for that specific job's /jobs/N detail page. These are separate from the main 3 header buttons and do not navigate away — they expand a nested form inline.

Never merge or rename these without updating this rule. Confusing labels cost hours of user support because the distinction between "preview with unsaved changes" vs "see the actually-live site" is subtle but important. Precedent commit: `dc7d513`.

---

## Verification gate (skill is "done" when these all pass)

- [ ] `provenance.audience_pivot_review_needed` is `false` in the final payload (i.e. Claude actually did step 8.5)
- [ ] `provenance.logo` is `scraped` (or `fallback_letter` only when the source site genuinely has no usable logo — flag this to the user explicitly)
- [ ] The `/lp/{slug}/admin?first` URL is included in the handoff message (no token generation needed — the URL is deterministic once the lps row exists). Without this the client can't take ownership.

- [ ] Skill triggers on the example phrases
- [ ] cloq.jp end-to-end produces a live LP at `/lp/cloq` within 2 minutes
- [ ] Provenance report correctly identifies scraped vs preset vs AI fields
- [ ] All images served from `lp-assets` bucket
- [ ] `lp_content_revisions` row created from the bootstrap (via the trigger that already exists)
- [ ] Yamaguchi LP still works unchanged

---

## Known hiccups and lessons learned — the cloq build retrospective

This is the full list of every issue we hit across the 10-turn session that built cloq, from first crawl to final handover-ready state. Each row is a real thing that broke or surprised us, with the fix commit and whether it's now automatic in the pipeline or still needs manual vigilance. **Read this once before running the skill on a new client so we don't re-learn the same lessons the hard way.**

### Category 1 — Content extraction (crawl_reference.py)

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 1 | **Aura timed out on cloq.jp** | 120s hard timeout, no design tokens | Aura's hosted pipeline struggles on certain WordPress sites | `extract_design.py` CSS fallback | ✅ Fallback runs automatically via RULE 2 |
| 2 | **`<dl>` pairs wrapped in `<div>` broke extraction** | `bundle.company_info` and `job_details` were empty; no 設立/代表者/業務内容 in the footer | cloq.jp's theme wraps every `<dt>`/`<dd>` pair in a `<div>` wrapper. The naive `dl > dt + dd` CSS selector missed all of them | `crawl_reference.py:collect_dl_pairs()` walks document order regardless of wrapper depth via `.find_all(['dt','dd'])` | ✅ Automatic |
| 3 | **Footer fields (founded, representative, business_type) missing** | Footer showed generic defaults instead of "代表取締役 山口 浩希 / 2026年3月2日 / 人材紹介事業" | Composer didn't know about these fields — they weren't in `ContentBundle` | `crawl_reference.py` exposes `bundle.founded / .representative / .capital / .business_type`; `compose_lpcontent.py:compose_footer()` reads them | ✅ Automatic, tracked in provenance |
| 4 | **Logo wasn't extracted, only a 34×34 letter badge** | Header showed a gradient "C" instead of the real CLOQ logo | `SKIP_IMAGE_PATTERNS` in `collect_images()` filtered anything with 'logo' in the src, and there was no dedicated logo extractor | `extract_logo()` + `extract_favicon()` helpers with a 7-strategy ladder (WordPress `custom-logo` class → brand-link `<a>` → generic `logo` class → header `<img alt=company>` → src match → largest favicon → apple-touch-icon), plus `header.logo_image` schema field and renderer ternary | ✅ Automatic, tracked as `provenance.logo: scraped / fallback_letter` |
| 5 | **Only 1 placeholder opening was produced on first build** | Composer returned a single generic opening; yamaguchi has 2 fully-detailed positions with 8-line 募集要項 + Q&As + day-in-life | Composer didn't know how to promote dl-extracted `job_details` into `openings[0].detail.requirements` | `compose_openings()` now builds a real opening from `bundle.job_details` with 8-line requirements, cleaned title, point-extraction from 「方」 clauses | ✅ Automatic for a SINGLE opening. Multi-position clients (like cloq's 2 roles) still need Claude to hand-craft the second+ role with yamaguchi-level detail — composer only fills `openings[0]` structurally |
| 6 | **Representative message had boilerplate leakage** | `about.paragraphs` contained generic "we value customer satisfaction" filler from the reference site | Source site mixes marketing copy with the representative message; no stripping | Still manual — Claude rewrites via audience pivot (step 8.5) | ⚠️ Manual via RULE 9 |

### Category 2 — Content framing (audience pivot)

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 7 | **Strengths section read like sales copy** | cloq's LP said "we deeply understand your hiring problem, we PDCA your funnel" — talking to CLIENTS, not job seekers | Composer copied client-facing marketing copy verbatim from a B2B service site into employer-branding sections | RULE 9 + workflow step 8.5 — Claude must rewrite hero/about/strengths/cta from a job-seeker frame before insert. `provenance.audience_pivot_review_needed: true` flag as a reminder | ⚠️ **Manual, mandatory**. The flag is the enforcement mechanism — don't insert lp_content with the flag still true |

### Category 3 — Database / existence checks

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 8 | **Admin page returned "LPが見つかりません"** | `/lp/cloq/admin` 404 even though the LP was live | `fetchCompanyAndExists` only checked `lp_entries` (zero entries on a brand-new LP) and `lp_admins` (no rows because bootstrap didn't insert them) | `nippo-sync@b15bee6` adds `public.lps` as a third existence signal + RULE in step 10.3 requiring `lp_admins` insert | ✅ Automatic in step 10.3 |
| 9 | **`lp_admins` insert was missing on first cloq build** | Same symptom as #8 | Bootstrap script didn't insert the Jayden owner row | `nippo-sync@d2dd91a` + workflow step 10.3 requires explicit `INSERT INTO lp_admins` for Jayden (owner) and `.cs@gmail.com` (member) | ✅ Automatic if step 10.3 runs |

### Category 4 — Entry form + dashboard UX

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 10 | **Entry form was hardcoded to yamaguchi** | `/lp/cloq/entry/` showed yamaguchi's positions in the dropdown | `public/lp/yamaguchi/entry/index.html` was a static HTML file, not dynamic | `nippo-sync@166d3b8` created `src/app/lp/[slug]/entry/route.ts` that reads `lp_content.openings.items[].title` and builds the dropdown dynamically. Legacy static file renamed to `_legacy-index.html.bak` | ✅ Automatic for ALL slugs |
| 11 | **ConnectScreen said "first to sign in becomes owner"** | Misleading footer text — made clients think they just needed to Google sign in, not use the claim link | Legacy UX from before the claim flow existed | `nippo-sync@58f98b7` two-path ConnectScreen rewrite: path 1 (blue) = "初めてアクセスする方へ" → use claim link; path 2 (gray) = "既に管理者として招待されている方" → Google OAuth for re-auth | ✅ Automatic — no action needed |
| 12 | **No bulk delete for test entries** | Client had to click each test entry one at a time to clean up | Missing feature | `nippo-sync@58f98b7` added `DELETE /api/lp/[slug]/admin/entries?all=true&confirm={slug}` + red "🗑️ 全削除" button with double-confirm in the dashboard | ✅ Ready for client use |

### Category 5 — Claim token → `?first` URL evolution

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 13 | **Claim token flow required manual SQL** | Bootstrap finished but Claude had to manually `INSERT INTO lp_claim_tokens` to generate a handover URL | Token table was designed for multi-token management, which was overkill for the single-shot handover case | `nippo-sync@eb81779` replaced the entire token flow with a deterministic `/lp/{slug}/admin?first` URL — no token, no expiry, no SQL insert | ✅ URL is always ready from the moment the `lps` row exists |
| 14 | **`reset_admins=true` wiped `google_refresh_token`** | After a test claim, Jayden's sheet sync stopped working because his admin row was `DELETE`d | The old claim flow used `DELETE FROM lp_admins` to reset owners. But `lp_admins` is where Google tokens live — delete wipes the tokens | `nippo-sync@0d54cb4` changed semantics from DELETE to DEMOTE (`UPDATE role='member' WHERE role='owner' AND email<>claimer`). Tokens stay intact on the demoted row | ✅ Automatic in the first-setup endpoint and the OAuth callback |
| 15 | **Clicking the email-form `?first` URL burned the lock on typos** | If the client typed their email wrong, `handed_over_at` was set permanently with the bad email and there was no way to recover | The email form committed the lock as soon as the email was submitted — no atomic transaction, no "did they actually sign in" check | `nippo-sync@28c4cdb` made Google OAuth the primary path. Lock is now committed INSIDE the same atomic transaction as all the mutations in the OAuth callback. Just clicking the URL doesn't burn it — only a fully successful Google round-trip does | ✅ Automatic. RULE 11 enforces this for future edits |
| 16 | **Old sheet was shared between Jayden and client post-handover** | Client's new form submissions landed in Jayden's Drive sheet — no separation | The old claim flow didn't create a new sheet; it just reused `lp_sheet_configs` pointing at Jayden's sheet | `nippo-sync@28c4cdb` OAuth callback now calls `createSpreadsheet(clientAccessToken, sheetTitle)` which creates the sheet in the CLIENT's Drive via their fresh tokens. Then `lp_sheet_configs` is UPSERTed to point at the new sheet ID, overwriting the old pointer | ✅ Automatic on first-claim handover |

### Category 6 — OAuth plumbing

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 17 | **State token was 3-part; firstFlag had nowhere to live** | Callback had no way to distinguish "first-claim handover" from "existing admin sign-in" | Original state format was `slug.nonce.sig` — no room for flags | `nippo-sync@28c4cdb` added a 4-part format: `slug.nonce.firstFlag.sig` where `firstFlag='0'|'1'`. Callback has a `parseState()` helper that accepts both 3-part (legacy) and 4-part (new) for backwards compat | ✅ Automatic |
| 18 | **`prompt=consent` required to always get `refresh_token`** | Google doesn't return a refresh_token on repeat auth unless you force-ask for consent | Google's default auth flow omits `refresh_token` if the user has already consented in the past | `buildAuthUrl()` in `google-oauth.ts` sets `prompt=consent` + `access_type=offline` always. Documented in callback as "this should never fire but handled defensively" | ✅ Automatic |
| 19 | **Self-test wiped Jayden's tokens before the DEMOTE fix** | After turn 6 self-test, `lp_admins.jayden.barnes@mgc-global01.com.google_refresh_token` was NULL — sheet sync for cloq was broken until manual re-OAuth | Self-test ran the old DELETE-based claim path before I'd shipped the DEMOTE fix. Scar was a one-click re-OAuth via `/lp/cloq/admin` → Google sign-in | Never — this is a one-time scar. Jayden re-OAuthed manually in turn 11, verified by `lp_entries` test submission → `last_sync_status='success'` at 09:25:07 | ⚠️ **Pre-flight check**: step 10.5 now does `SELECT google_refresh_token FROM lp_admins WHERE email='jayden.barnes@mgc-global01.com'`. If NULL, step 10.5 skips instead of crashing. |

### Category 7 — OG / link preview metadata

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 20 | **Link previews showed `日報シンクロくん`** | Pasting `/lp/cloq/admin?first` into Slack/iMessage unfurled as "日報シンクロくん" instead of "株式会社CLOQ" | Admin page is a React page that inherited the root `app/layout.tsx` default title; main LP (`/lp/{slug}`) had `<title>` and `<meta description>` but no `og:*` tags | `nippo-sync@93e4a7b` added `generateMetadata()` to the admin page (reads `lps.client_name` + `lps.handed_over_at` + hero bg + company name, branches on `?first` + lock state, sets `robots: noindex, nofollow`). `nippo-sync@93e4a7b` also added full OG + Twitter Card tags to BOTH head blocks in `lp-render.ts` (main LP + jobs detail) pulling from `lp_content.meta/header/hero` | ✅ Automatic for all slugs. RULE 13 enforces this for future routes |
| 21 | **Literal `日報シンクロくん` string leaked via an HTML comment** | Even after fixing the meta tags, a body-scan link preview crawler could still find the legacy brand name in my explanation comment | I wrote `<!-- ... override default "日報シンクロくん" title ... -->` as an explanatory comment, which ships to the browser | `nippo-sync@9f929ee` scrubbed both comments to a generic `<!-- Open Graph / Twitter Card metadata for link unfurling -->` | ✅ Lesson: never write the legacy brand string into any shipped file, even in comments |
| 22 | **Unfurl caches don't refresh automatically** | First time we paste the fixed URL into an existing Slack thread, the old preview still shows because Slack caches for ~30min / iMessage indefinitely / LINE ~1 week | Not a bug, just how link preview caches work | Workarounds: Slack debugger (https://api.slack.com/reflection/og-debugger), add `?first&v=2` throwaway param to bypass iMessage cache, paste in new chat to refresh LINE | ⚠️ **Manual**: mention this to the user when handing off. First paste always wins; subsequent changes need a cache bust |

### Category 8 — Custom domain / Vercel automation

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 23 | **Custom domain was just a text field with no action** | User could save a domain but there was no way to actually make it work without SSH'ing into Vercel or using the CLI | Initial implementation was schema-only | `nippo-sync@28c4cdb` added `POST/GET/DELETE /api/lp/[slug]/admin/domain-attach` that wraps Vercel's `/v10/projects/{id}/domains` API. Dashboard shows a 3-step flow: 保存 → Vercelに登録する → DNS instructions with copy buttons → 確認 button | ✅ Client-driven from dashboard. RULE 12 forbids the skill from auto-attaching |
| 24 | **Vercel's `/v9` `verified: true` is misleading** | UI showed "✓ Vercel Active" on a freshly-attached domain even though DNS didn't point at Vercel yet | Vercel's `/v9/projects/{id}/domains/{name}.verified` means "attached to project without TXT challenge needed", NOT "DNS actually resolves to Vercel's edge". Tested by POSTing `mgc-vercel-api-test-delete-me.com` (bogus domain) → `verified: true` immediately | `nippo-sync@53a7338` switched to `/v6/domains/{domain}/config.configuredBy` which returns `'A' \| 'CNAME' \| 'HTTP' \| null`. That's the real DNS signal. `buildStatus()` now merges both endpoints' responses | ✅ Automatic. RULE 12 documents the gotcha |
| 25 | **`VERCEL_TOKEN` was missing from the Vercel project env** | `domain-attach` endpoint would have returned a 500 the first time it was called on production | Bootstrap never added Vercel API creds to the Vercel project itself, only to Doppler | Added via Vercel API in turn 10: `POST /v10/projects/{id}/env` with `VERCEL_TOKEN` as encrypted, targeting production + preview + development. Now part of the Required Infrastructure table | ✅ Already done; new runs inherit it |
| 26 | **TXT verification records for owned apex domains** | Some domains require an extra TXT `_vercel.{apex}` record when the apex was previously on another Vercel account | Vercel security — they need to prove the client owns the apex before subdomain ownership transfers | `buildDnsInstructions()` + UI render the `vercel_verification` array when present, with copy buttons. Tested this real path with `recruit.mgc-global01.com` which returned a real pending_domain_verification entry | ✅ Automatic |

### Category 9 — Sheet sync / operational scars

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 27 | **Bootstrap sheets in Jayden's Drive get orphaned on every handover** | After each client claims, the old sheet is still in Jayden's Drive but no longer linked in `lp_sheet_configs` — clutter accumulates | By design — the new flow replaces the sheet pointer, doesn't delete the file | Manual: Jayden deletes them from Drive when he feels like it. A quarterly cleanup is fine | ⚠️ Manual housekeeping |
| 28 | **No way to monitor OAuth callback errors post-hoc** | If a handover fails we have no way to see what went wrong from Claude's side | No Vercel logs API in Claude's MCP toolset | Manual: check Vercel logs in the dashboard if handover reports errors | ⚠️ Manual debugging |

### Category 10 — Vercel serverless constraints (from predecessor saiyo-lp-skill + nippo-sync git history)

These pre-date this session but were never in my retrospective. Reading the predecessor's SKILL.md and nippo-sync git log surfaced them.

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 32 | **Fire-and-forget IIFEs silently die on Vercel** | Sheet sync for new form submissions never ran in prod — only the manual `/sync` endpoint worked. Notification emails for applications also never sent | Vercel serverless kills any unawaited async work the moment the lambda returns its response. `;(async () => { ... })()` patterns the inner `await` never completes because the process is already being torn down | `b261c5b` (sheet sync) + `d3ef7e1` (notification email) — both switched from IIFE to awaited-inline. +500ms-1s latency but actually reliable. RULE 16 enforces this going forward | ✅ For existing routes. ⚠️ Manual vigilance for new routes — grep for `;(async` before shipping |
| 33 | **Vercel 4.5MB request body limit breaks image uploads** | Client uploads a >4.5MB photo via ImageField in the admin editor. Server returns HTML from Vercel's edge proxy ("Request Entity Too Large" / 413) instead of JSON. Frontend crashes on `JSON.parse` with "Unexpected token R, 'Request En...'" | Vercel's platform limit on request body size is 4.5MB, inflexible on Hobby + Pro. Multipart upload has to flow through the serverless function | `8090f74` + `fd2bfbd` — signed-URL 2-step upload pattern: (1) client POSTs small JSON `{filename, contentType, size}` to `/api/lp/[slug]/admin/upload-sign`, (2) server validates auth + returns a Supabase Storage signed upload URL via service-role client, (3) client PUTs the actual file directly to Supabase Storage (bypasses Vercel entirely), (4) client POSTs the resulting public URL back to update `lp_content` | ✅ Automatic for images uploaded via the admin editor |

### Category 11 — Email delivery (from predecessor saiyo-lp-skill)

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 34 | **Gmail SMTP rewrites the `From` header** | n8n Send Email node is configured with `fromEmail: "noreply@mgc-global01.com"`, but emails arrive showing From `jayden.barnes.cs@gmail.com`. Client sees "Reply-To: noreply@..." as a demoted secondary | `smtp.gmail.com` with app-password auth forces the envelope From to match the authenticated user — anti-spoofing policy, not a bug | Use display-name override: `"株式会社X 採用通知" <jayden.barnes.cs@gmail.com>`. Recipients see the company brand in inbox preview; the personal Gmail is only visible on expand. Alternatively, configure "Send mail as" in Gmail Settings → Accounts and Import (authorizes the other address, allows native sending) | ⚠️ Manual — the display-name workaround is baked into `n8n-koko` notification workflows, but if you ever build a new notification path, apply the same pattern |
| 35 | **Resend free-tier trial mode rejects multi-recipient sends** | Sending a notification email to 2+ admins via Resend's default `onboarding@resend.dev` sender returns HTTP 403 `validation_error: "You can only send testing emails to your own email address"`. The ENTIRE send fails, not just the extra recipients | Resend's free trial restricts To-list to the Resend account owner's email only. Any other recipient in the list triggers the 403 for the whole request | Three options: (A) verify a custom domain at resend.com/domains with DNS SPF/DKIM/return-path — most work; (B) set `RESEND_TRIAL_MODE_RECIPIENT` env var to override all recipients to the owner email (lossy — all admins get redirected to one mailbox); (C) route notifications through n8n + Gmail SMTP instead (what Phase 4 nippo-sync does). Current production uses option C for notifications and option B for invites. Commit `8662ff2` | ✅ Documented. New notification paths should use n8n SMTP, not Resend |

### Category 12 — Next.js routing gotchas (from predecessor saiyo-lp-skill)

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 36 | **Static files in `/public/` override dynamic app router routes** | Added `/app/lp/[slug]/route.ts` expecting it to dynamically render LPs. Visiting `/lp/yamaguchi` still served the old static content. File is right, route handler appears to never fire | Vercel's static file handler serves `/public/lp/yamaguchi/index.html` BEFORE the app router gets a chance to match. Also applies to subpages: `/public/lp/yamaguchi/entry/index.html` overrides `/app/lp/[slug]/entry/route.ts` | Rename static fallbacks to `_legacy-index.html.bak`. The route handler can still `readFile` them as a safety fallback if the DB row is missing. NEVER use `index.html` as the filename. Commits `4645fca` (yamaguchi fix) + `166d3b8` (cloq entry form fix). RULE 17 enforces this going forward | ✅ Automatic now that both yamaguchi and cloq legacy files are renamed. ⚠️ New LPs must follow the naming convention |
| 37 | **`next.config.js` rewrite order matters** | The admin page `/lp/:slug/admin` was being intercepted by a catch-all static rewrite `/lp/:slug/:sub → /lp/:slug/:sub/index.html` before the app router could match it | `afterFiles` rewrites fire BEFORE dynamic routes. `fallback` rewrites fire AFTER dynamic routes. The admin page needed to match an app router page, so the rewrite had to be in `fallback`, not `afterFiles` | Commit `df6d566` moved the LP static rewrites from `afterFiles` to `fallback`. Now: `/lp/yamaguchi/admin` → app router page (wins), `/lp/yamaguchi/entry` → app router route (wins), legacy static `.bak` files are only served if both static AND dynamic routes miss | ✅ Automatic — but if you add new rewrites to `next.config.js`, prefer `fallback` unless you specifically want to override dynamic routes |

### Category 13 — Admin / invite flow (drive.file constraints)

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 38 | **Invitees can't see the sheet even after sign-in** | Owner claims LP, sheet is created, sheet appears in owner's Drive. Owner invites a teammate via admin dashboard. Teammate signs in, sees the dashboard, but clicking "View Sheet" returns 404 from Drive API | `drive.file` OAuth scope is per-user-per-app — it only grants access to files the app created on behalf of THAT specific user. So the invitee's drive.file token sees nothing, because the sheet wasn't created on behalf of them | Commit `895747e` — when an admin is invited, use the OWNER's drive.file token to call the Drive API permissions endpoint (`POST /files/{id}/permissions`) and explicitly share the sheet with the invitee's email as a writer. `drive.file` is sufficient for this because the file was created by the app on behalf of the owner — drive.file grants read/write/share/delete on app-created files. Helpers in `src/lib/sheets.ts`: `shareSheetWithEmail` and `unshareSheetWithEmail` | ✅ Automatic in the invite flow |
| 39 | **Revoking the app in Google permissions wipes all file authorizations** | Client revokes access via https://myaccount.google.com/permissions ("Apps with access to your account" → Remove). The Google Sheet stays in their Drive, but every Drive API call from the app returns 404 even though the file is right there | `drive.file` is per-user-per-app. When the user revokes the app, ALL file authorizations for that user+app combo are wiped. The files remain but the app has zero grants on them. Re-signing in gives a fresh grant, but the OLD files are still orphaned from the app's perspective — a new grant does NOT re-attach to old files | Recovery endpoint `/api/admin/reset-lp-claim?slug={slug}` (commit `65c6992`) — deletes `lp_admins` owner row + `lp_sheet_configs`, leaves `lp_entries` intact. Next sign-in creates a fresh sheet that the new grant can access. Gated by `x-migration-secret` header. **NOT automatic detection** — the app can't tell the difference between "file doesn't exist" and "you've been revoked". Manual invocation required | ⚠️ Manual recovery. See RULE 18 for the full recovery procedure |

### Category 14 — Pre-session hiccups documented in the predecessor skill

These are from `/home/ubuntu/saiyo-lp-skill/SKILL.md`'s "Gotchas & Hard-Won Lessons" section. They ALL apply to this skill too — I just hadn't read them before the cloq build.

| # | Predecessor lesson | Source | Now captured in this SKILL.md as |
|---|---|---|---|
| 40 | Vercel fire-and-forget IIFE | `saiyo-lp-skill/SKILL.md` Gotcha 1 | Critical Constraint #3 + RULE 16 + Category 10 hiccup 32 |
| 41 | Gmail SMTP From rewrite | `saiyo-lp-skill/SKILL.md` Gotcha 2 | Category 11 hiccup 34 |
| 42 | drive.file per-user-per-app + revoke recovery | `saiyo-lp-skill/SKILL.md` Gotcha 3 | RULE 18 + Category 13 hiccups 38 and 39 |
| 43 | Resend free-tier trial mode | `saiyo-lp-skill/SKILL.md` Gotcha 4 | Category 11 hiccup 35 |
| 44 | Next.js static files override dynamic routes | `saiyo-lp-skill/SKILL.md` Gotcha 5 | Critical Constraint #4 + RULE 17 + Category 12 hiccup 36 |
| 45 | drive.file CAN share files (via Drive API permissions endpoint) | `saiyo-lp-skill/SKILL.md` Gotcha 6 | Category 13 hiccup 38 |
| 46 | One sensitive OAuth scope taints the whole consent screen | `saiyo-lp-skill/SKILL.md` Gotcha 7 | Critical Constraint #2 + RULE 15 |

### Category 15 — Things that worked but could trip us next time

| # | Hiccup | Symptom | Root cause | Fix commit | Automatic now? |
|---|---|---|---|---|---|
| 29 | **Yamaguchi's `handed_over_at` was NULL originally** | The new ?first URL would have been valid against a real production LP that already had admins | Backfill was required when adding `handed_over_at` to `lps` | Migration `20260409_lps_handover_and_domain` backfilled to `MIN(lp_admins.created_at)` for all non-cloq LPs at migration time. Cloq was intentionally left NULL for end-to-end testing | ✅ Migration-time fix; any NEW LP gets `handed_over_at=NULL` by default, which is the correct pre-handover state |
| 30 | **Two cloq builds with different content** | Turn 1-3 had a minimal placeholder version; turn 4 replaced it with the real 2-position version | Initial build was too minimal; had to overwrite to reach yamaguchi quality | `lp_content_revisions` trigger automatically logged both versions. This is working as designed — always audit rev 1 vs rev 2 if something looks off | ✅ Automatic audit log |
| 31 | **Slack OG preview cache locked in the bad preview** | First paste showed "日報シンクロくん"; second paste of the same URL still showed it even after the fix deployed | Slack caches link previews for ~30 min per URL; unfurls don't auto-refresh | Workaround: use Slack's OG debugger or add a cache-bust query param | ⚠️ Manual; mention to user on first paste |

---


### Category 16 — Admin dashboard rebuild (Lovable port + analytics + LP編集 landing)

This category captures the 3-turn session that replaced the old admin dashboard with a Lovable-generated self-contained file, wired real analytics, and fixed the LP編集 direct-jump UX. If you ever need to redo this (e.g. client asks for a visual refresh and brings a new Lovable export), these are the pitfalls.

**H47 — Lovable file uses Tailwind v4-incompatible bare-variable class names.** The exported shadcn Sidebar component used `w-[--sidebar-width]` (bare variable shorthand) in 6 places, which silently collapses to 0 width in Tailwind v4. Symptom: desktop sidebar overlaps content area, mobile drawer eats the entire viewport. **Fix**: regex-replace all `[--sidebar-width]` → `[var(--sidebar-width)]` and `[--sidebar-width-icon]` → `[var(--sidebar-width-icon)]` on paste. Documented in Critical Constraint #7. Precedent: `780f440`.

**H48 — Lovable file uses custom color class names that don't exist in the host project.** The Lovable export referenced `bg-sidebar-bg`, `text-sidebar-fg`, `text-sidebar-active-fg`, `bg-sidebar-active`, `bg-sidebar-hover` — classes that nippo-sync's `globals.css` didn't define (it uses the standard shadcn names `bg-sidebar`, `text-sidebar-foreground`, etc.). **Fix**: either find-replace the class names to match the host project's CSS tokens, OR add aliases to `globals.css` mapping the Lovable names to the standard tokens. I chose the alias approach so the Lovable file stays verbatim and regeneratable. Six aliases added under `@theme inline`: `--color-sidebar-bg`, `--color-sidebar-fg`, `--color-sidebar-active`, `--color-sidebar-active-fg`, `--color-sidebar-hover`, `--color-sidebar-border`. Precedent: commit existed prior to the rebuild session, aliases were already there.

**H49 — The `dc43c56` wire-up commit did NOT add analytics, test data, or the LP編集 landing screen.** Jayden's initial wiring pass (an external commit I didn't make myself) hooked real data for entries/members/settings/Vercel but left: (a) the Dashboard section with hardcoded placeholder `viewsData`/`conversionData`/`sourceData` marked `サンプル`, (b) the LP編集 section as a direct `<LpContentEditor />` render with no landing screen, (c) no analytics tables, endpoint, or tracking pixel anywhere. The client opening the handed-over dashboard would see "0 entries, 0 PV, サンプル charts" — a worse first impression than the old dashboard. **Fix**: the follow-up `dc7d513` commit added (1) `lp_page_views`+`lp_form_events` tables via migration, (2) test data backfill (15 entries + 3,172 PV + 787 form_view + 281 form_start), (3) `POST /api/lp/[slug]/track` tracking endpoint, (4) `GET /api/lp/[slug]/admin/analytics` aggregation endpoint, (5) tracking pixel injection into lp-render.ts (×2 for main+jobs) + entry/route.ts, (6) AdminCtx extension with `analytics`/`loadingAnalytics`/`loadAnalytics()`, (7) DashboardSection rewrite to use real data from context, (8) LpEditSection rewrite as two-state landing. This is why RULE 20 is mandatory now — to prevent another gap between "wired" and "actually working". Precedent: `dc7d513`.

**H50 — Monkey-patching window.fetch is the only reliable way to track form_submit.** The entry form in `src/app/lp/[slug]/entry/route.ts` is rendered as raw HTML from a route.ts handler (not JSX), and the existing submit handler uses a vanilla `fetch('/api/lp-entry', ...)` call with its own error/success handling that we can't cleanly hook. Attempting to wrap the submit button's click listener is fragile (wrong timing, fires before validation, fires on non-submit clicks). The clean solution is to monkey-patch `window.fetch` at pixel-injection time: `var orig = window.fetch; window.fetch = function(url, init){ var p = orig.apply(this, arguments); if (typeof url === 'string' && url.indexOf('/api/lp-entry') !== -1) { p.then(function(r){ if (r && r.ok) track('form_submit'); }); } return p; };`. This fires form_submit ONLY on a real 2xx response from the entry endpoint, never on validation errors or network failures. Precedent: commit `dc7d513` in `src/app/lp/[slug]/entry/route.ts`. Side note: the pixel also needs `keepalive: true` on the tracking fetch so form_submit survives the page navigation that happens right after a successful submit.

**H51 — The `analytics` endpoint must bucket timestamps in `Asia/Tokyo` timezone, not UTC.** First draft used `date_trunc('day', viewed_at)` which produces UTC days. For a Japanese audience viewing a LP at 8 AM JST (= 23:00 UTC previous day), this means views get attributed to "yesterday" in the chart. **Fix**: `date_trunc('day', viewed_at AT TIME ZONE 'Asia/Tokyo')`. Precedent: `dc7d513` in `/api/lp/[slug]/admin/analytics/route.ts`. Generalization: every time-series query that will be shown to a Japanese user MUST be bucketed in JST.

**H52 — `collapsible="none"` breaks mobile even worse than the overlap bug it fixes.** I hit the bare-variable bug (H47) and reached for `collapsible="none"` as a quick fix — this replaces the shadcn Sidebar's fixed positioning with a plain flex layout so the spacer div actually takes up space. But `"none"` also disables the mobile Sheet drawer, so on mobile the sidebar becomes an always-visible 256px column that eats 2/3 of the viewport. **Real fix is fixing the bare-variable bug at the source** (H47). If you find yourself reaching for `collapsible="none"` as a workaround, stop — you're masking the real bug. Precedent: `83f5266` (the wrong fix) → `780f440` (the right fix).

**H53 — `sonner` `<Toaster>` must be mounted once in `src/app/layout.tsx`, not per-page.** The Lovable export uses `toast()` from sonner throughout but doesn't include the `<Toaster>` provider — it assumes the host project has it mounted. nippo-sync already has `<Toaster richColors position="top-right" />` in `src/app/layout.tsx:25` from a previous session, so nothing needed to be added. But if you're porting this pattern to a NEW host project that doesn't have it, add the Toaster to the root layout, not to AdminDashboard — otherwise toasts from other pages won't render. Also: no `import { Toaster }` needed in AdminDashboard.tsx itself; just `import { toast } from 'sonner'` and fire.

**H54 — Seed SQL with two independent `(SELECT … ORDER BY random() LIMIT 1)` subqueries collapses to a single random pick per statement.** First version of `analytics_bootstrap.py`'s seed had `referrer` and `referrer_domain` as two separate `(SELECT … FROM referrer_pool ORDER BY random() LIMIT 1)` subqueries, expecting each row to get its own random pick. PostgreSQL's optimizer evaluated each subquery ONCE for the whole INSERT (treating them as constant scalar subqueries), so all 3,172 cloq rows ended up with `referrer='https://www.google.com/search'` AND `referrer_domain='bing.com'` — a stuck pair, AND mismatched against each other. The 流入元 chart showed Bing 99.7% / Direct 0.3%. **Fix**: precompute a `random()` value per row inside a CTE (`with_random AS (SELECT ..., random() AS r_ref FROM exploded)`) and use it as the bucket selector in `CASE` statements for BOTH `referrer` and `referrer_domain` — guarantees per-row variety AND consistency between the two columns. Distribution after fix: Google 39.5% / Direct 22.7% / Twitter 14.8% / LinkedIn 9.6% / Bing 5.1% / Facebook 4.8% / Instagram 3.5%. Generalization: anywhere you need correlated random picks across multiple columns of the same row in PostgreSQL, **always materialize the random value in a CTE first** — never trust two independent subqueries to give you matching random values. Precedent: cloq reseed during the 2026-04-10 fix session.

**H55 — Handover MUST reset demo analytics inside the same transaction as the `handed_over_at` lock.** Initial design left the demo data in place after handover, which would have meant the client signs in and immediately sees fake Japanese names like 山田健太 + made-up Twitter referrers in their dashboard. The fix is in BOTH handover paths (`src/app/api/sheets/connect/callback/route.ts` and `src/app/api/lp/[slug]/admin-first-setup/route.ts`): three `DELETE` statements run inside the same atomic transaction as the `UPDATE lps SET handed_over_at`, so either everything commits (claim succeeds + demo wiped) or nothing commits (claim fails + demo stays for retry). The deletes target `lp_page_views WHERE user_agent LIKE '%fake-backfill%'`, `lp_form_events WHERE session_id IN (...)`, and `lp_entries WHERE source = 'lp_form_demo'`. **Critical detail**: the seed SQL MUST tag entries with `source = 'lp_form_demo'` (not the default `'lp_form'`) so the cleanup can distinguish them from any real submissions that came in before handover. Real entries are never touched. Precedent: nippo-sync@9b22739, mgc-saiyo-lp-bootstrap analytics_bootstrap.py update.

**H56 — Analytics widgets do NOT belong on the LP編集 landing screen.** First version of LpEditSection landing showed 4 stat cards (PV / 応募率 / 応募総数 / 新規応募) — but PV and 応募率 are analytics that should only live on the Dashboard tab. Putting them on LP編集 confused the section's purpose ("am I editing content or looking at stats?") and required the section to load analytics on mount, which slowed it down. **Fix**: LpEditSection landing now shows ONLY 応募総数 + 新規応募 (entry-related stats from `useAdmin().entries`, no analytics fetch needed). The Dashboard tab is the canonical home for all analytics. Generalization: each tab should have ONE clear purpose, and stat cards should match that purpose. Don't sprinkle analytics across multiple tabs.

---

## Troubleshooting — quick symptom → cause table

If something goes wrong post-bootstrap, check this list before digging:

| Symptom | Most likely cause | Fix |
|---|---|---|
| `/lp/{slug}/admin` returns "LPが見つかりません" | Step 10.3 skipped — `lp_admins` has no row | `INSERT INTO lp_admins` for Jayden (owner) + `.cs@gmail.com` (member) |
| `/lp/{slug}/entry` dropdown shows wrong positions | You're hitting the legacy static HTML path somehow | Verify `src/app/lp/[slug]/entry/route.ts` exists; check that no `public/lp/{slug}/entry/index.html` exists |
| Sheet sync stops working | `lp_admins.google_refresh_token` is NULL for the current owner | The owner needs to re-OAuth: visit `/lp/{slug}/admin` in an incognito window → click Google sign-in |
| Link preview shows "日報シンクロくん" | OG cache in the unfurler (Slack/iMessage/LINE), not a server bug — check the actual HTML via curl first | Use Slack's OG debugger OR add `?first&v=2` to bust iMessage's cache. Verify server-side with `curl $URL \| grep og:title` |
| "Vercel Active" pill is green but DNS isn't actually working | You're reading the wrong Vercel field (`/v9.verified` is misleading) | Use `/v6/domains/{domain}/config.configuredBy` instead. RULE 12. |
| `?first` URL shows "引き渡し済みです" unexpectedly | `lps.handed_over_at` is set. Check who claimed and when | If genuine: no reset, use invite flow. If emergency: `UPDATE lps SET handed_over_at=NULL WHERE slug='...'` via Supabase MCP — document it explicitly |
| Client can't sign in via Google on `?first` | Usually **not** a consent screen issue — our screen is in Production mode with only non-sensitive scopes, so any Google account can sign in with no warning. Check instead: (a) callback URL matches the registered redirect URI exactly `https://nippo-sync.vercel.app/api/sheets/connect/callback` in Google Cloud Console, (b) client's corporate Google Workspace doesn't block third-party apps (check with their IT), (c) `prompt=consent` is still set in `buildAuthUrl()` so they actually get a fresh refresh_token | Verify redirect URI in Google Cloud Console; if corporate Workspace blocks it, client signs in with personal Gmail instead |
| Custom domain attach returns 402 | Vercel Pro account quota exceeded (100 domains/project cap on Pro) | Upgrade plan or detach unused domains first |
| Sheet sync fires but `last_sync_status='error'` | Usually an expired access token where refresh also failed | Owner re-OAuth; check `last_sync_error` field for the exact Google API message |

---

## Pre-flight check — run this BEFORE the next bootstrap

Before building a NEW client LP, verify the environment is healthy. Run this checklist start-to-finish:

### A. Supabase health (5 checks)

```sql
-- 1. Jayden has fresh Google tokens (for step 10.5 sheet creation)
select
  (google_refresh_token is not null) as has_refresh,
  google_token_expiry > now() as access_valid,
  last_signed_in_at
from public.lp_admins
where email = 'jayden.barnes@mgc-global01.com'
  and lp_slug = 'yamaguchi'  -- known-stable reference
limit 1;
-- Expected: has_refresh=true, access_valid=true (or false + plan to re-OAuth)

-- 2. The lps master registry is reachable
select count(*)::int as total_lps,
       count(*) filter (where status='live')::int as live_lps,
       count(*) filter (where handed_over_at is not null)::int as handed_over
from public.lps;
-- Expected: total_lps >= 2, live_lps >= 2, handed_over varies by client rollout state

-- 3. Industry preset is loaded
select industry, key from public.industry_presets limit 5;
-- Expected: at least one row (製造業/default)

-- 4. lp_content_revisions trigger is working
select count(*)::int as total_revisions from public.lp_content_revisions;
-- Expected: > 0 (each published LP has >= 1 revision)

-- 5. No orphaned admin rows
select lp_slug, email, role
from public.lp_admins a
where not exists (select 1 from public.lps where slug = a.lp_slug);
-- Expected: zero rows

-- 6. Analytics tables exist (RULE 20)
select
  to_regclass('public.lp_page_views') is not null as page_views_exists,
  to_regclass('public.lp_form_events') is not null as form_events_exists;
-- Expected: both true. If either is false, run the migration
-- `lp_analytics_page_views` (see scripts/analytics_bootstrap.py)

-- 7. Page views index exists (query performance — dashboards will timeout without it)
select indexname
from pg_indexes
where tablename = 'lp_page_views'
  and indexname in ('idx_lp_page_views_slug_viewed_at', 'idx_lp_page_views_session');
-- Expected: both rows present
```

### B. Vercel deployment health (3 checks)

```bash
# 1. Production LP is serving
curl -sI https://nippo-sync.vercel.app/lp/yamaguchi | head -1
# Expected: HTTP/2 200

# 2. OG meta tags not leaking 日報シンクロくん
curl -s https://nippo-sync.vercel.app/lp/yamaguchi | grep -c '日報シンクロくん'
# Expected: 0

# 3. Vercel env vars needed by domain-attach are present
# (run from the VM; reads Jayden's Vercel token from Doppler)
VERCEL_TOKEN=$(doppler secrets get VERCEL_TOKEN --project nippo-syncro-kun --config dev --plain)
curl -sk "https://api.vercel.com/v9/projects/prj_le2vOYHWk48qXpSiVzaMGIzDs2Dc/env?teamId=team_InumbXmdUdRp3WpMs47TFd8s" \
  -H "Authorization: Bearer $VERCEL_TOKEN" | python3 -c "
import json, sys
envs = {e['key']: e['target'] for e in json.load(sys.stdin).get('envs', [])}
needed = ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'AUTH_SECRET', 'VERCEL_TOKEN', 'POSTGRES_URL_NON_POOLING', 'NEXT_PUBLIC_BASE_URL']
for k in needed:
  print(f'{"✓" if k in envs else "✗"} {k}')
"
# Expected: all 6 present

# 4. Tracking pixel is injected into public LP HTML (RULE 20)
curl -s https://nippo-sync.vercel.app/lp/yamaguchi | grep -c 'lp_sid_yamaguchi'
# Expected: 1 (pixel on main LP)

curl -s https://nippo-sync.vercel.app/lp/yamaguchi/entry | grep -c "track('form_view')"
# Expected: 1 (form lifecycle pixel)

# 5. Track endpoint accepts page_view and returns 204
curl -sX POST https://nippo-sync.vercel.app/api/lp/yamaguchi/track \
  -H "Content-Type: application/json" \
  -d '{"event_type":"page_view","path":"/lp/yamaguchi","session_id":"preflight-check","referrer":""}' \
  -w '\nHTTP %{http_code}\n' | tail -2
# Expected: HTTP 204

# 6. Analytics endpoint requires auth (expected 401 without cookie)
curl -s -w '\nHTTP %{http_code}\n' https://nippo-sync.vercel.app/api/lp/yamaguchi/admin/analytics?days=30 | tail -2
# Expected: {"error":"Unauthorized"} + HTTP 401

# 7. Clean up the preflight test row from Supabase
# (run via Supabase MCP afterwards:
#  DELETE FROM public.lp_page_views WHERE session_id = 'preflight-check';)
```

### C. Forbidden path safety (5 checks — Critical Constraint #1)

```bash
# Confirm none of Matsuo-san's services are touched by this session
systemctl is-active mgc-connector-hub.service 2>/dev/null && echo "matsuo connector-hub: running (leave alone)" || echo "matsuo connector-hub: not on this VM or stopped"
systemctl is-active line-crm.service 2>/dev/null && echo "matsuo line-crm: running (leave alone)" || echo "matsuo line-crm: not on this VM or stopped"
systemctl is-active n8n-koko.service 2>/dev/null && echo "matsuo n8n-koko: running (leave alone)" || echo "matsuo n8n-koko: not on this VM or stopped"
# Just READ the status. NEVER restart. If any are running, proceed carefully — do NOT `git pull` or `systemctl restart` anything under /home/ubuntu/mgc-connector-hub/, /home/ubuntu/nippo-sync-koko/, or /home/ubuntu/line-harness-oss/
ls -la /home/ubuntu/nippo-sync/ > /dev/null && echo "✓ jayden's nippo-sync present"
ls -la /home/ubuntu/mgc-saiyo-lp-bootstrap/ > /dev/null && echo "✓ bootstrap skill present"
```

### D. If the pre-flight fails

- **A.1 fails (Jayden tokens missing)**: he visits `https://nippo-sync.vercel.app/lp/yamaguchi/admin` → clicks "Googleアカウントでサインイン" → refreshes his `google_refresh_token`. Takes 10 seconds. Step 10.5 of the bootstrap will then create the initial sheet successfully instead of skipping.
- **A.2-5 fail**: something is wrong with Supabase — do NOT proceed with the bootstrap until fixed. Check `Supabase:get_logs` for errors.
- **B fails**: check the Vercel deployment status in the dashboard; look for failed recent deploys. If `NEXT_PUBLIC_BASE_URL` is missing, set it to `https://nippo-sync.vercel.app` and redeploy.
- **C shows Matsuo services running**: that's expected and normal. Just confirm this session does NOT write to their paths or restart their services.

### E. Jayden's migration to Matsuo-san's Vercel Pro team (when ready)

As of this writing, nippo-sync is on Jayden's Hobby account. The `domain-attach` endpoint is fully env-var driven, so the migration is a 6-step config change (no code):

1. Matsuo-san invites Jayden to his Pro team (or transfers ownership — transfer is cleaner)
2. Import/transfer the nippo-sync project to Matsuo-san's team via Vercel dashboard
3. Read the NEW `projectId` + `teamId` from Matsuo-san's team dashboard (Settings → General → Project ID)
4. Generate a NEW `VERCEL_TOKEN` scoped to Matsuo-san's team (https://vercel.com/account/tokens)
5. Swap all 3 env vars on the Vercel deployment via the dashboard:
   - `VERCEL_TOKEN` → new token
   - `VERCEL_PROJECT_ID` → Matsuo-san's project ID
   - `VERCEL_TEAM_ID` → Matsuo-san's team ID
6. Redeploy (Vercel auto-redeploys on env var change)

Zero client-side DNS changes needed — existing custom domains keep working because their CNAMEs point at `cname.vercel-dns.com` regardless of which team owns the project.

---

## How Claude should invoke this skill

When the trigger fires, Claude does NOT manually run all 13 steps from a chat. Instead, Claude calls:

```
Custom Proxy:server_exec(
  command="cd /home/ubuntu/mgc-saiyo-lp-bootstrap && python3 scripts/bootstrap.py --slug {slug} --client-name '{name}' --primary-url '{url}' [--style-url '{url}'] [--overwrite]",
  working_dir="/home/ubuntu/mgc-saiyo-lp-bootstrap"
)
```

The `bootstrap.py` orchestrator runs all 13 steps and returns a JSON status report. Claude then formats the report for the user.

For the FIRST run on a new site, Claude may want to step through manually to verify each phase works — that's fine. After that, always go through bootstrap.py.

---

## File map

```
mgc-saiyo-lp-bootstrap/
├── SKILL.md                       ← this file (workflow + rules + retrospective)
├── README.md                      ← human-facing overview
├── references/                    ← design-time reference docs (not executed)
│   ├── lp-content-schema.md       ← copy of LpContent type
│   ├── content-extraction.md      ← multi-page crawl strategy + selectors
│   ├── image-pipeline.md          ← image strategy + nano-banana prompts
│   ├── ai-gap-fill.md             ← prompts for generating missing sections
│   └── industry-presets.md        ← how to load + apply presets
└── scripts/
    ├── bootstrap.py               ← orchestrator (entry point)
    ├── crawl_reference.py         ← multi-page crawler → ContentBundle (with logo + dl extraction)
    ├── extract_design.py          ← Aura wrapper with CSS-fallback
    ├── compose_lpcontent.py       ← merges ContentBundle + design tokens + preset → LpContent
    ├── image_pipeline.py          ← concept-aware nano-banana-pro-preview generation (folded in 2026-04-09)
    └── analytics_bootstrap.py     ← analytics tables verification + tracking pixel verification + demo data seed (folded in 2026-04-09, step 12.7)
```

**NOT in the repo** (intentionally): no `upsert_lp.py` — we use Supabase MCP `execute_sql` directly from Claude for all DB writes, no wrapper script needed.

---

## Out of scope (do NOT add to this skill)

- **Editing existing LPs** — use the admin editor at `/lp/{slug}/admin`, not this skill
- **Custom domain setup at bootstrap time** — the Vercel domain automation (RULE 12) is a POST-HANDOVER, owner-only flow in the dashboard. Even if the user tells you the client's domain during bootstrap, just note it in the polish checklist; don't try to attach it
- **Running the actual `/admin?first` handover** — that's the client's action, not ours; we just return the URL
- **Manual Jayden re-OAuth** — if `lp_admins.jayden.barnes@mgc-global01.com.google_refresh_token` is NULL at bootstrap time, step 10.5 skips sheet creation and logs it in provenance. Don't try to "fix" Jayden's OAuth from Claude — tell the user to visit `/lp/{any_slug}/admin` and click Google sign-in
- **Multi-language LPs** — current `lp_content` schema is JP-only
- **Non-recruitment site types** — would be a sibling skill: `mgc-corp-site-bootstrap`
- **Deleting the orphaned bootstrap sheets** from Jayden's Drive after handover — those stay as files; Jayden cleans them up manually when he feels like it
- **Resetting `lps.handed_over_at`** for an already-claimed LP — by design, one-shot. See RULE 11.
