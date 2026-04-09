# mgc-saiyo-lp-bootstrap

A Claude.ai skill that turns a client URL into a live 採用LP (recruitment landing page) on `nippo-sync.vercel.app/lp/{slug}` in under 2 minutes.

## What it does

Given a client name + their existing website URL, the skill:

1. **Crawls** the homepage + likely sub-pages (about, recruit, news, etc.) to extract company name, address, tel, CEO message, business descriptions, existing job postings, paragraph content, and image URLs.
2. **Extracts** the design system (brand colors, primary font, favicon, OG image, logo) by parsing the site's CSS. Falls back to the yamaguchi defaults when extraction is ambiguous.
3. **Composes** a full `LpContent` JSON matching the schema in `nippo-sync/src/lib/lp-content-types.ts`. Real scraped content fills the hero, about, and strengths sections; industry presets fill data pills and welfare items; placeholders fill voice quotes and missing openings.
4. **Inserts** the result into `public.lps` + `public.lp_content` via the Supabase MCP (or via the HTTP upsert endpoint with a migration secret if running outside Claude).
5. **Verifies** the LP renders at `https://nippo-sync.vercel.app/lp/{slug}`.

The first run won't be polished — that's intentional. Each LP becomes its own editable project at `/lp/{slug}/admin` where the human polishes copy, swaps images, fixes any over-eager scrapes, and saves. Speed > perfection.

## Architecture

```
URL  →  crawl_reference.py  →  ContentBundle JSON
URL  →  extract_design.py   →  DesignTokens JSON
                                       ↓
              compose_lpcontent.py ←  Industry preset + client name
                                       ↓
                                  LpContent JSON
                                       ↓
              [ Claude orchestration layer ]
                  → Supabase MCP upsert
                  → image enhancement (nano-banana)
                  → Slack notification
                  → UptimeRobot monitor
```

The Python scripts are pure transformations: URL → JSON. They have no secrets, no DB access, no MCP. The Claude orchestration layer (this skill running in a claude.ai conversation) handles all side effects.

## Files

| Path | Size | Purpose |
|---|---|---|
| `SKILL.md` | 12 KB | The skill definition that Claude reads to drive the workflow |
| `scripts/crawl_reference.py` | 16 KB | Multi-page content scraper (requests + BeautifulSoup) |
| `scripts/extract_design.py` | 13 KB | CSS-only design token extractor with WordPress palette filtering |
| `scripts/compose_lpcontent.py` | 15 KB | Maps ContentBundle + DesignTokens + preset → LpContent JSON |
| `scripts/bootstrap.py` | 7 KB | CLI orchestrator that runs the three above scripts in sequence |

## CLI usage (bootstrap.py)

```bash
python3 scripts/bootstrap.py \
  --slug cloq \
  --client-name "株式会社CLOQ" \
  --primary-url https://cloq.jp/ \
  --industry "採用コンサルティング"
```

Optional flags:

- `--style-url <URL>` — extract design tokens from a different reference URL than the primary
- `--max-pages <N>` — cap on sub-pages crawled (default 8)
- `--preset-json <path>` — JSON file with a preset row from `public.industry_presets`

Output: a single JSON object on stdout containing:

```json
{
  "slug": "cloq",
  "client_name": "株式会社CLOQ",
  "primary_url": "https://cloq.jp/",
  "industry": "採用コンサルティング",
  "lp_content": { /* full LpContent matching nippo-sync schema */ },
  "content_bundle": { /* raw scraped data */ },
  "design_tokens": { /* extracted theme + asset URLs */ },
  "provenance": { /* which fields came from where */ }
}
```

The Claude orchestration layer takes this output and inserts the `lp_content` field into Supabase via the MCP.

## Triggering the skill

In a claude.ai conversation, mention:

> 採用LPを作って — 株式会社CLOQ — https://cloq.jp/

Claude will recognize the trigger pattern (採用LP keyword + client name + URL) and run the workflow.

## Verified end-to-end

First successful run:

- **Slug:** `cloq`
- **Client:** 株式会社CLOQ
- **Reference:** https://cloq.jp/
- **Live URL:** https://nippo-sync.vercel.app/lp/cloq
- **Result:** Header, about, strengths, hero image, footer address, theme colors all extracted from the real site. 1 placeholder opening (real jobs were filtered as noise). Voices section has 1 placeholder. Map embed is empty. All editable at `/lp/cloq/admin`.

## Industry presets — the scaling lever

The first LP in a new industry (e.g. 製造業) takes the longest because everything is generated from scratch + polished. After polishing, save the welfare items, data pills, and job templates back to `public.industry_presets` so the next LP in the same industry starts with that knowledge baked in. By the 5th LP in an industry, the bootstrap output is so close to the final shape that there's almost nothing left to polish.

## Out of scope (for now)

- Image enhancement via nano-banana — currently the LP uses raw scraped image URLs from the client site. Image migration to the `lp-assets` Supabase Storage bucket happens in a follow-up turn after the LP is verified.
- Custom domain mapping — handled in nippo-sync's Phase 4, not here.
- Multi-language LPs — Japanese only for now.
- Aura.build design extraction — the skill orchestrator can call Aura via MCP in parallel with the CSS fallback, but the Python scripts don't try Aura directly because it requires browser automation and times out on many sites.
