---
name: mgc-saiyo-lp-bootstrap
description: Creates a brand-new Japanese 採用LP (recruitment landing page) for a client from a single reference URL. Fires whenever the user mentions 採用LP (or "recruitment LP" / "saiyo LP") alongside a URL and a client name in the same message — examples that trigger: "作って 採用LP for 株式会社CLOQ https://cloq.jp/", "採用LP cloq https://cloq.jp/", "採用LPを作って https://cloq.jp/ 株式会社CLOQ", "Build a recruitment LP for ABC, ref https://example.jp/", "新しいクライアントのLP作って 株式会社X https://x.jp/". Runs end-to-end without mid-flow questions: multi-page crawl of the reference site (extracts 会社概要 / 募集要項 / logo / colors via <dl>/<img>/CSS walks), composes a structural LpContent draft, performs mandatory audience-pivot rewrite of hero / about / strengths / cta so the content targets job seekers not clients, inserts via Supabase MCP into project pglaffdnhixmabcjdxbi, creates the Google Sheet for entries auto-sync, generates an owner-claim link for first-time client handover, and returns a live URL at nippo-sync.vercel.app/lp/{slug} plus the claim URL to send to the client. Target: under 2 minutes from prompt to shipping. Do NOT fire this for editing an existing LP (that happens in the admin editor at /lp/{slug}/admin) or for updating copy / images / layout on a live LP.
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
3. **Claim URL** — `https://nippo-sync.vercel.app/lp/{slug}/claim?token={uuid}` — the one-click owner-claim link to send to the client. 14-day expiry, single-use, with DEMOTE semantics (doesn't wipe Jayden's tokens so the sheet sync keeps working)
4. **Google Sheet URL** — the auto-sync sheet for entries, sitting in Jayden's Google Drive
5. **Provenance report** — every field labeled `scraped` | `scraped_dl` | `preset` | `default` | `ai_generated` | `fallback_letter` so the user knows what's real vs placeholder
6. **Polish checklist** — 2-4 specific things Claude recommends touching up manually before sending to the client (e.g. "the data pills are industry-preset defaults, swap in real numbers if you have them", "voices.items uses placeholder names — replace with real employees after they start")

The user's first action after seeing this message should be: open the live URL, glance at the LP, approve → send the claim URL to the client.

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
12.5. **Generate owner-claim link for client handover** — INSERT a row into `public.lp_claim_tokens` so the user can send a single URL to the client for first-time ownership. The claim flow will DEMOTE Jayden's pre-seeded admin rows to `member` (preserving Google OAuth tokens so the sheet sync keeps working) and make the client the sole `owner`.
    ```sql
    insert into public.lp_claim_tokens (lp_slug, role, note, created_by, reset_admins, expires_at)
    values ('{slug}', 'owner', '{client_name}様への初回オーナー権限の引き渡しリンク',
            'jayden.barnes@mgc-global01.com', true, now() + interval '14 days')
    returning token;
    ```
    The returned UUID is substituted into `https://nippo-sync.vercel.app/lp/{slug}/claim?token={uuid}` — the client visits this URL, enters their work email, becomes the sole owner, and lands in the admin dashboard with a success toast. They can then delete test entries via the per-entry delete button (owner-only) and add secondary admins via the existing invite UI.

13. **Hand off** — return to user:
    - Live URL: `https://nippo-sync.vercel.app/lp/{slug}`
    - Admin URL: `https://nippo-sync.vercel.app/lp/{slug}/admin`
    - **Claim link for client** (from step 12.5): `https://nippo-sync.vercel.app/lp/{slug}/claim?token={uuid}`
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

**RULE 10 — Handover uses the claim link, not OAuth.** For first-time client handover, the skill MUST generate a row in `public.lp_claim_tokens` and return the `/lp/{slug}/claim?token={uuid}` URL in the handoff message (workflow step 12.5 + 13). Do NOT rely on the client's Google OAuth as the primary owner-creation path — that requires them to have a Google account AND to understand what "最初にサインインした方がオーナーになります" means. The claim link is simpler: one URL, enter your email, you're the owner. The `reset_admins=true` flag in the token row triggers a DEMOTE of Jayden's pre-seeded admin rows (NOT a DELETE — that would wipe google_refresh_token and break the sheet sync). The demoted rows stay as `member` with tokens intact, so auto-sync to the Google Sheet keeps working after handover. The client can revoke demoted members manually via the admin dashboard if they want full separation. Tokens expire in 14 days and are single-use — after the client claims, the same URL returns the "already used" error screen.

**RULE 7 — Industry preset auto-update is OPT-IN.** After polishing, the system suggests "save these as the new {industry} default preset?" but never auto-saves.

**RULE 8 — Reference URL is the client's OWN site by default.** A second `style_url` is optional and only affects design tokens (theme colors, font hints), never content.

---

## Verification gate (skill is "done" when these all pass)

- [ ] `provenance.audience_pivot_review_needed` is `false` in the final payload (i.e. Claude actually did step 8.5)
- [ ] `provenance.logo` is `scraped` (or `fallback_letter` only when the source site genuinely has no usable logo — flag this to the user explicitly)
- [ ] A claim link was generated via step 12.5 and included in the handoff message — without this the client can't take ownership

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
