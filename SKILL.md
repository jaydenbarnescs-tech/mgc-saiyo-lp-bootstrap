---
name: mgc-saiyo-lp-bootstrap
description: Creates a brand-new Japanese 採用LP (recruitment landing page) for a client from a single reference URL. Fires whenever the user mentions 採用LP (or "recruitment LP" / "saiyo LP") alongside a URL and a client name in the same message — examples that trigger: "作って 採用LP for 株式会社CLOQ https://cloq.jp/", "採用LP cloq https://cloq.jp/", "採用LPを作って https://cloq.jp/ 株式会社CLOQ", "Build a recruitment LP for ABC, ref https://example.jp/", "新しいクライアントのLP作って 株式会社X https://x.jp/". Runs end-to-end without mid-flow questions: multi-page crawl of the reference site (extracts 会社概要 / 募集要項 / logo / colors via <dl>/<img>/CSS walks), composes a structural LpContent draft, performs mandatory audience-pivot rewrite of hero / about / strengths / cta so the content targets job seekers not clients, inserts via Supabase MCP into project pglaffdnhixmabcjdxbi, creates an initial Google Sheet in Jayden's Drive (replaced by a fresh one in the client's own Drive when they claim ownership), registers the LP in the public.lps master registry so the deterministic OAuth-driven first-setup URL /lp/{slug}/admin?first is activated, and returns the live URL plus the /admin?first handover URL for the client to click-through Google sign-in. Target: under 2 minutes from prompt to shipping. Do NOT fire this for editing an existing LP (that happens in the admin editor at /lp/{slug}/admin) or for updating copy / images / layout on a live LP.
---

# mgc-saiyo-lp-bootstrap

Bootstrap a complete 採用LP for a client from a single reference URL. Target: under 2 minutes from prompt to live URL.

## THE ONE RULE — read this first, every time

**Speed over perfection. Ship aggressive, refine in editor.**

This skill exists because the per-LP admin editor at `/lp/{slug}/admin` already handles polishing, theme tweaks, content editing, image swaps, and Google Sheets sync. The editor is fast and the user (Jayden) uses it constantly. So this skill's job is **not** to produce a perfect LP — it's to produce a 90%-correct LP in 90 seconds, then hand off to the editor for the last 10%.

Default behavior: scrape aggressively, fill gaps with sensible defaults, ship to editor, refine there. **Do NOT ask for confirmation mid-flow.** Build, hand off, let user fix in editor. The only acceptable interruptions are: missing required inputs (no URL, no client name) or slug collision.

This is the philosophical opposite of the old `saiyo-lp-skill` which had "always ask, never assume" as rule #1. That rule existed because the old skill generated static HTML — fixing a mistake meant rebuilding. The new system has a live editor; that rule is obsolete.

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

The user's first action after seeing this message should be: open the live URL, glance at the LP, approve → send the `/admin?first` URL to the client via email/Slack/LINE/iMessage. The OG preview will auto-unfurl to "株式会社{client} 採用LP · 初期設定" with the client's own hero image (metadata is generated server-side in `generateMetadata` on the admin page). The client clicks the link, clicks Google sign-in, authorizes, and is done — they land in the dashboard with a brand-new sheet in their Drive, all admin rights, and ownership of the LP. Total time: ~30 seconds from click to working dashboard.

---

## Required infrastructure (must exist before this skill runs)

These are already in place as of 2026-04-09. The skill assumes them.

| Thing | Where | Purpose |
|---|---|---|
| nippo-sync repo | `/home/ubuntu/nippo-sync/` (Jayden's) | Hosts the `/lp/[slug]` route + admin editor |
| Supabase project | `pglaffdnhixmabcjdxbi` (`nippo-sync`) | Stores `lps`, `lp_content`, `industry_presets`, `lp_assets` |
| Master registry | `public.lps` table | Source of truth for LP existence; insert here first with `created_via='skill'` |
| Content storage | `public.lp_content` table | JSONB content blob keyed by `lp_slug` |
| Admin access | `public.lp_admins` table | Auto-create owner row for `jayden.barnes@mgc-global01.com` so the dashboard works on first visit |
| Upsert path | Supabase MCP `execute_sql` (preferred) or `apply_migration` for transactional safety | No HTTP endpoint or migration secret needed when running from Claude — direct DB access via MCP |
| Storage bucket | `lp-assets` (public read) | Where all skill-generated images land |
| Industry preset | `industry_presets` table, `製造業/default` row | Welfare items, data pills, hero EN titles for fallback |

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

10.5. **Create Google Sheet for entries auto-sync** — read Jayden's existing Google OAuth tokens from `lp_admins` (he's already authorized for nippo-sync overall, so the tokens carry over to new slugs):
    1. Fetch `google_access_token` for `jayden.barnes@mgc-global01.com`. If `google_token_expiry` < now, refresh it via `https://oauth2.googleapis.com/token` using `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` from Doppler (`nippo-syncro-kun/dev`) plus the stored refresh_token.
    2. POST to `https://sheets.googleapis.com/v4/spreadsheets` with `{"properties": {"title": "{client_name} - 採用エントリー", "locale": "ja_JP", "timeZone": "Asia/Tokyo"}, "sheets": [{"properties": {"title": "Entries"}}]}`. The sheet lands in jayden.barnes@mgc-global01.com's Drive.
    3. PUT the LP_ENTRY_HEADERS row to `/spreadsheets/{id}/values/Entries!A1?valueInputOption=USER_ENTERED`. Headers: `["ID","応募日時","LP Slug","会社名","お名前","メール","電話","職種","志望動機","ステータス","内部メモ","Source"]`
    4. INSERT into `public.lp_sheet_configs` with `connection_type='oauth'`, `auto_sync=true`, `worksheet_name='Entries'`, `last_sync_status='success'`, `last_synced_count=0`. After this, every form submission to `/api/lp-entry` will auto-append to the sheet via the existing handler logic.
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

13. **Hand off** — return to user:
    - Live URL: `https://nippo-sync.vercel.app/lp/{slug}`
    - Admin URL: `https://nippo-sync.vercel.app/lp/{slug}/admin`
    - **First-setup URL for client** (from step 12.5): `https://nippo-sync.vercel.app/lp/{slug}/admin?first` — send this via email/Slack/LINE/iMessage. The OG preview unfurls as "株式会社{client} 採用LP · 初期設定" with the client's hero image. On click → Google sign-in → ~30 seconds later the client is the owner, has a brand-new Google Sheet in their own Drive, and Jayden is demoted to member (tokens preserved so the old sheet is still accessible if needed). The URL is safe to click/preview — only a fully completed OAuth round-trip burns the one-shot lock.
    - Provenance report (which fields are scraped vs preset vs AI, including `logo: scraped|fallback_letter`)
    - Image source breakdown (scraped/enhanced/generated/unsplashed counts)
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

The Vercel API credentials (`VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`) are already in the Vercel project env vars as of turn 9. The defaults in code are `prj_le2vOYHWk48qXpSiVzaMGIzDs2Dc` / `team_InumbXmdUdRp3WpMs47TFd8s`.

**DO NOT attempt to automate custom domain setup as part of the skill's workflow**, even if the user mentions a specific domain in their prompt. Reasons: (a) only the owner (client, post-handover) should be attaching domains to their LP, (b) DNS changes belong to the client's registrar and aren't something we can touch, (c) the Vercel API call is tied to a session cookie so it can only run post-login. If the user says "set up the domain recruit.cloq.jp", Claude should mention it in the handoff polish checklist as a recommended manual step the client should do from their dashboard.

**RULE 7 — Industry preset auto-update is OPT-IN.** After polishing, the system suggests "save these as the new {industry} default preset?" but never auto-saves.

**RULE 8 — Reference URL is the client's OWN site by default.** A second `style_url` is optional and only affects design tokens (theme colors, font hints), never content.

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
├── SKILL.md                       ← this file
├── README.md                      ← human-facing overview
├── references/
│   ├── lp-content-schema.md       ← copy of LpContent type for offline reference
│   ├── content-extraction.md      ← multi-page crawl strategy + selectors
│   ├── image-pipeline.md          ← detailed image strategy + nano-banana prompts
│   ├── ai-gap-fill.md             ← prompts for generating missing sections
│   └── industry-presets.md        ← how to load + apply presets
└── scripts/
    ├── bootstrap.py               ← orchestrator (entry point)
    ├── crawl_reference.py         ← multi-page web_fetch crawler → ContentBundle
    ├── extract_design.py          ← Aura wrapper with CSS-fallback
    ├── compose_lpcontent.py       ← merges ContentBundle + DesignTokens + preset → LpContent
    ├── image_pipeline.py          ← runs the image strategy mix
    └── upsert_lp.py               ← POST to /api/admin/lp-content-upsert
```

---

## Out of scope (do NOT add to this skill)

- Editing existing LPs (use `/lp/{slug}/admin`)
- Custom domain mapping (separate `lp_domains` table, future work)
- Multi-language LPs (current schema is JP-only)
- Non-recruitment site types (would be a sibling skill: `mgc-corp-site-bootstrap`)
- Direct image manipulation outside the strategy table (scraping logos, etc.)
