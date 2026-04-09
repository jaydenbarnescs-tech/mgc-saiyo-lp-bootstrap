---
name: mgc-saiyo-lp-bootstrap
description: Use this skill whenever the user wants to create a 採用LP (Japanese recruitment landing page) for a client by referencing an existing website. Triggers on the keyword "採用LP" combined with a URL in the same message. Examples that fire this skill - "作って 採用LP for 株式会社CLOQ from https://cloq.jp/", "採用LP cloq https://cloq.jp/", "Build a 採用LP, reference: https://cloq.jp/, style ref: https://taf-jp.com/recruitment/". The skill scrapes the reference site (multi-page crawl + Aura design extraction), composes a complete LpContent JSON, posts it to nippo-sync's /api/admin/lp-content-upsert endpoint, and hands off a live URL at nippo-sync.vercel.app/lp/{slug} in under 2 minutes. Do NOT trigger this skill for editing an existing LP - that work happens in the per-LP admin editor at /lp/{slug}/admin.
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

The skill activates when **all three** are present in the user's message:

1. The keyword `採用LP` (Japanese characters, exact match)
2. A URL (the reference site — typically the client's own corporate site)
3. A client name (Japanese OK, e.g. `株式会社CLOQ`, or English like `cloq`)

Examples that fire:

- `作って 採用LP for 株式会社CLOQ from https://cloq.jp/`
- `採用LP cloq https://cloq.jp/`
- `Build a 採用LP, reference: https://cloq.jp/, style ref: https://taf-jp.com/recruitment/`
- `Make a 採用LP for ABC建設, their site is https://example.jp/`

If only `採用LP` is present without a URL, ask for the reference URL once, then proceed.
If only a URL is present without `採用LP`, do NOT trigger — could be any other request.

---

## Required infrastructure (must exist before this skill runs)

These are already in place as of 2026-04-09. The skill assumes them.

| Thing | Where | Purpose |
|---|---|---|
| nippo-sync repo | `/home/ubuntu/nippo-sync/` (Jayden's) | Hosts the `/lp/[slug]` route + admin editor |
| Supabase project | `pglaffdnhixmabcjdxbi` (`nippo-sync`) | Stores `lps`, `lp_content`, `industry_presets`, `lp_assets` |
| Bootstrap endpoint | `POST /api/admin/lp-content-upsert?slug={slug}` | Where the composed LpContent gets posted |
| Auth header | `x-migration-secret: $MIGRATION_RUNNER_SECRET` | Required for the upsert endpoint |
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
   - Extract favicon
8. **Compose LpContent** (`compose_lpcontent.py`):
   - **Visual** (`theme`, font hints) ← Aura or CSS fallback
   - **meta.title**, **header.company_name**, **header.logo_letter** ← ContentBundle.company_name
   - **hero.subtext** + **hero.jp_tagline** ← AI-generated from ContentBundle paragraphs (recruitment tone)
   - **hero.en_title** ← preset's `hero_en_titles[0]` or AI-generated single English word
   - **hero.bg_image** ← filled by Phase 9
   - **about.headline** + **about.paragraphs** ← lightly rewrite ContentBundle.representative_message + business_descriptions
   - **strengths.items** ← parse 3 value props from ContentBundle, or AI-generate from business_descriptions
   - **data.items** ← industry preset (placeholder numbers, flagged for user edit)
   - **voices.items** ← industry preset employee voices, photos filled by Phase 9
   - **openings.items** ← ContentBundle.existing_jobs if found, otherwise industry preset job_templates
   - **welfare.items** ← industry preset welfare_items
   - **cta** + **footer** ← ContentBundle.address/tel + AI-generated CTA copy
   - **theme** ← Aura colors
9. **Image pipeline** — see image strategy table below
10. **POST** `/api/admin/lp-content-upsert?slug={slug}` with the full composed LpContent JSON
11. **Update** `lps.status = 'live'`
12. **Verify** — GET `https://nippo-sync.vercel.app/lp/{slug}`, confirm 200 + content renders
13. **Hand off** — return to user:
    - Live URL: `https://nippo-sync.vercel.app/lp/{slug}`
    - Admin URL: `https://nippo-sync.vercel.app/lp/{slug}/admin`
    - Provenance report (which fields are scraped vs preset vs AI)
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

**RULE 6 — All images go through lp-assets bucket.** Never reference an external URL (proxy server, original site, Unsplash CDN) directly in lp_content. We own our assets.

**RULE 7 — Industry preset auto-update is OPT-IN.** After polishing, the system suggests "save these as the new {industry} default preset?" but never auto-saves.

**RULE 8 — Reference URL is the client's OWN site by default.** A second `style_url` is optional and only affects design tokens (theme colors, font hints), never content.

---

## Verification gate (skill is "done" when these all pass)

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
