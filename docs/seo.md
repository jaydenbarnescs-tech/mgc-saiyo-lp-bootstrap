# SEO Reference — MGC 採用LP

This document is the authoritative SEO reference for the MGC 採用LP product. It explains every SEO decision, where each piece of code lives, why each choice was made, and what to do when something breaks or a new client LP fails to index. The audience is a future Claude or developer picking this up cold.

---

## Table of Contents

1. [Overview and Goals](#1-overview-and-goals)
2. [robots meta tag (`ROBOTS_SNIPPET_META`)](#2-robots-meta-tag-robots_snippet_meta)
3. [Google Site Verification (GSC ownership)](#3-google-site-verification-gsc-ownership)
4. [Sitemaps](#4-sitemaps)
5. [robots.txt](#5-robotstxt)
6. [Open Graph and canonical tags](#6-open-graph-and-canonical-tags)
7. [JobPosting JSON-LD (Google for Jobs)](#7-jobposting-json-ld-google-for-jobs)
8. [Google Indexing API (the fast-track)](#8-google-indexing-api-the-fast-track)
9. [Why /jobs/0 wasn't indexing — root cause analysis (CLOQ)](#9-why-jobs0-wasnt-indexing--root-cause-analysis-cloq)
10. [Google Jobs widget vs. GSC 有効 — they are different](#10-google-jobs-widget-vs-gsc-有効--they-are-different)
11. [favicon_url vs logo_image — the logo split](#11-favicon_url-vs-logo_image--the-logo-split)
12. [What to do when a new LP is live but not indexing](#12-what-to-do-when-a-new-lp-is-live-but-not-indexing)
13. [GSC property setup for a new custom domain](#13-gsc-property-setup-for-a-new-custom-domain)
14. [Admin pages and noindex](#14-admin-pages-and-noindex)
15. [Complete SEO checklist for a new client launch](#15-complete-seo-checklist-for-a-new-client-launch)

---

## 1. Overview and Goals

The LP product serves Japanese recruitment landing pages. Each client gets:

- A **root LP** at their custom domain (e.g. `https://cloq.recruitly.jp/`) — the company's recruitment landing page.
- One or more **job detail pages** at `/jobs/0`, `/jobs/1`, etc. — individual job posting pages.

The primary SEO goals are:

1. **Get job pages indexed by Google quickly** — days, not weeks.
2. **Appear in Google for Jobs** — the dedicated job listing surface that shows above regular search results.
3. **Produce rich search snippets** — large images, full text, not truncated previews.
4. **Signal canonical URLs correctly** — both `cloq.recruitly.jp/` and `nippo-sync.vercel.app/lp/cloq` serve the same content via middleware rewrite. Google must understand which URL is authoritative.

The CLOQ launch taught us that the root page indexed in a few days, but `/jobs/0` stayed at "Discovered - currently not indexed" for weeks. Every SEO decision in this codebase was made to prevent that from happening again.

---

## 2. robots meta tag (`ROBOTS_SNIPPET_META`)

### What it is

```html
<meta name="robots" content="max-image-preview:large,max-snippet:-1,max-video-preview:-1">
```

### Where it lives

`template/lib/lp-render.ts`, defined as the module-level constant `ROBOTS_SNIPPET_META`:

```typescript
const ROBOTS_SNIPPET_META =
  '<meta name="robots" content="max-image-preview:large,max-snippet:-1,max-video-preview:-1">'
```

### Where it is emitted

Both HTML-rendering functions in `lp-render.ts` emit this tag inside `<head>`:

- `renderLpHtml()` — the root LP page (`/` on a custom domain, `/lp/{slug}` on Vercel)
- `renderJobDetailHtml()` — every job detail page (`/jobs/{i}`)

Both insertions look like this in the template literal:

```
<title>${esc(...)}</title>
<link rel="canonical" href="...">
${ROBOTS_SNIPPET_META}
```

### What each directive does and why

| Directive | Effect | Why we set it |
|---|---|---|
| `max-image-preview:large` | Allows Google to show the largest possible image thumbnail in search results | Job listings with company photos get a richer visual appearance; without this, Google defaults to small or no images |
| `max-snippet:-1` | No character limit on text snippets in search results | Full job descriptions appear as snippet text rather than truncated 160-char blurbs |
| `max-video-preview:-1` | No limit on video preview length | Harmless for current pages (no video), future-proofs if video is added |

### What this tag is NOT

This tag does **not** control whether Google indexes the page. The `noindex` directive is a separate thing — this tag says nothing about indexing, only about how rich the snippet can be. Every LP page (root + job detail) should be indexed; this tag just maximises the visual richness of the search result when it is indexed.

Admin pages use `noindex` (see [section 12](#12-admin-pages-and-noindex)).

---

## 3. Google Site Verification (GSC ownership)

### Why this exists

Before you can use Google Search Console (GSC) to inspect URLs, submit sitemaps, or call the Indexing API on behalf of a domain, you must prove ownership of that domain in GSC. The verification meta tag is how we do that.

### Method: HTML tag (not HTML file)

We use the **HTML tag method** (`<meta name="google-site-verification" content="TOKEN">`), not the HTML file method.

The HTML file method requires serving a specific file at a specific path (e.g. `google1234abcd.html`). With our architecture — where `/lp/{slug}/*` route handlers return server-rendered HTML — adding a new static file path would require either a dedicated route handler per client or a convention for naming files. The HTML tag method is simpler: add the token to `lp-domains.ts`, deploy once, done.

### Code path

**Step 1 — Token storage.** In `template/lib/lp-domains.ts`:

```typescript
export type CustomDomainConfig = {
  host: string
  brandName?: string
  brandColor?: string
  googleSiteVerification?: string | string[]  // single token or array of tokens
}

const CUSTOM_DOMAINS: Record<string, CustomDomainConfig> = {
  cloq: {
    host: 'cloq.recruitly.jp',
    brandName: 'CLOQ',
    brandColor: '#2673b8',
    googleSiteVerification: [
      'ZaoolhQMn9GQT24xPBvtSeTpd50ybnSTzLpPpBFXrwo',  // client (CLOQ)
      'AMVEOMf-qfKg3AOLbo_biuWuOvJE_WIAZiMYy2W-FsE',  // Jayden (MGC)
    ],
  },
}
```

**Step 2 — Token retrieval.** `getGoogleVerificationTokens(slug)` normalises the field (string | string[] | undefined) to a flat string array:

```typescript
export function getGoogleVerificationTokens(slug: string): string[] {
  const v = CUSTOM_DOMAINS[slug]?.googleSiteVerification
  if (!v) return []
  const arr = Array.isArray(v) ? v : [v]
  return arr.map((t) => t?.trim()).filter((t): t is string => !!t)
}
```

**Step 3 — Rendering.** `renderVerificationMetas(slug)` in `lp-render.ts` calls `getGoogleVerificationTokens` and maps each token to its own `<meta>` tag:

```typescript
function renderVerificationMetas(slug: string): string {
  return getGoogleVerificationTokens(slug)
    .map((t) => `<meta name="google-site-verification" content="${esc(t)}" />`)
    .join('\n')
}
```

This is then included in both `renderLpHtml` and `renderJobDetailHtml`.

### Multi-token support: why multiple tokens

GSC supports multiple concurrent owners, each verified independently with their own token. This is important because:

- **The client (CLOQ)** verifies with their own token → they become an Owner in GSC and can inspect URLs, see search performance, etc.
- **Jayden (MGC)** verifies with his token → he is also an Owner and can manage things on MGC's behalf without the client needing to share credentials.
- **The service account** (used by the Indexing API) does not verify via a meta tag. The service account is added as an Owner through GSC → Settings → Users & Permissions → Add User. It cannot verify via HTML tag because it has no browser session.

Each person/system that needs GSC Owner access gets their own verification token in the `googleSiteVerification` array.

### Verification token vs. HTML file token

These are **different tokens from different GSC screens**. Do not confuse them:

- **HTML tag token** — obtained from: GSC → Settings → Ownership verification → HTML tag. Looks like a base64-encoded string (40–50 chars).
- **HTML file token** — obtained from: GSC → Settings → Ownership verification → HTML file. A different string, placed inside a standalone HTML file.

If you're adding a new owner, direct them to: GSC → Settings → Users & Permissions → Add User (if they already have an existing verified property) or GSC → Add property → HTML tag verification (if they're verifying fresh).

---

## 4. Sitemaps

Two sitemaps exist. The distinction matters because Google Search Console properties are scoped to either a domain or a URL prefix — the per-slug sitemap is what GSC for a custom-domain property actually reads.

### 4a. Global sitemap (nippo-sync)

**Location:** `src/app/sitemap.ts` in the nippo-sync Next.js app (separate from the template directory).

**URL:** `https://nippo-sync.vercel.app/sitemap.xml`

**Format:** Next.js `MetadataRoute.Sitemap` — the framework converts the array return value to XML automatically.

**What it includes:**
- Queries `public.lp_content` for all published LPs.
- For each LP: emits the root URL + all `/jobs/{i}` URLs.
- `lastModified` uses `lp_content.updated_at` from the DB: `new Date(updated_at)` if the field exists, otherwise `undefined`.

**Why it exists:** This sitemap covers the `nippo-sync.vercel.app` GSC property. It gives Google a complete picture of all LP pages on the Vercel host, which helps discovery even before custom domains are set up.

### 4b. Per-slug sitemap

**Location:** `template/app/lp/[slug]/sitemap-xml/route.ts`

**Internal path:** `/lp/{slug}/sitemap-xml`

**External path (custom domain):** `/sitemap.xml` — the middleware rewrites `/sitemap.xml` on a custom domain to `/lp/{slug}/sitemap-xml`.

**What it includes:**
- Root URL (`priority: "1.0"`)
- All `/jobs/{i}` URLs (`priority: "0.8"`)
- `lastmod` from `lp_content.updated_at` (DB-accurate); falls back to today's date only when the row is missing.

**Response headers:**
```
Content-Type: application/xml; charset=utf-8
Cache-Control: public, max-age=3600, s-maxage=3600
```

1-hour CDN cache. Sitemaps don't need sub-minute freshness, and caching reduces DB reads when Google crawls frequently.

**Code walkthrough:**

```typescript
// Fetch updated_at and job count from DB
const rows = await sql<...>`
  select content, published, updated_at
  from public.lp_content
  where lp_slug = ${slug}
  limit 1
`
if (rows.length > 0 && rows[0].published) {
  jobCount = rows[0].content?.openings?.items?.length ?? 0
  const isoDay = rows[0].updated_at
    ? new Date(rows[0].updated_at).toISOString().split('T')[0]
    : null
  if (isoDay) lastmod = isoDay
}
```

The key design point: `lastmod` is **not** `new Date().toISOString()`. Setting lastmod to today on every request is a known antipattern — Google documentation explicitly warns that if `<lastmod>` doesn't correlate with actual content changes, Google will start ignoring it. We use the DB timestamp, which only changes when someone saves in the admin. This means Google sees the same date on repeated crawls until content actually changes, which trains Google to trust the signal.

### Why accurate lastmod matters

Google's crawler has finite capacity. For low-authority domains (new clients with few backlinks), Google decides how often to recrawl based on signals. A site that always claims its lastmod is "today" looks like it's crying wolf. A site that shows a stable date from weeks ago, then updates it when content changes, looks like a reliable signal. The accurate-lastmod approach trains Google to recrawl on actual change events.

---

## 5. robots.txt

**Location:** `template/app/lp/[slug]/robots.txt/route.ts`

**Internal path:** `/lp/{slug}/robots.txt`

**External path (custom domain):** `/robots.txt` — middleware maps this.

**Content:**
```
User-agent: *
Allow: /
Disallow: /admin
Disallow: /entry
Disallow: /privacy

Sitemap: https://{custom-host}/sitemap.xml
```

**Design decisions:**

- `Allow: /` is explicit (though it's the default) for clarity.
- `/admin` is disallowed — password-protected, no indexing value, and leaking admin UI to Google would be noise.
- `/entry` is disallowed — the application form. There's no SEO value in indexing a form page, and it may contain session state.
- `/privacy` is disallowed — the privacy policy page is functional but not a keyword-relevant page for job seekers.
- The `Sitemap:` directive points to the canonical custom-domain sitemap. This is how Google discovers the sitemap without needing GSC configuration — it reads robots.txt first, finds the sitemap URL, and queues it.

**Cache headers:** Same as the sitemap — `public, max-age=3600, s-maxage=3600`.

---

## 6. Open Graph and canonical tags

### Canonical tag

Every LP page (root and job detail) emits:

```html
<link rel="canonical" href="{canonical_url}">
```

For the root page in `renderLpHtml`:
```html
<link rel="canonical" href="${canonicalBase}">
```

For job detail pages in `renderJobDetailHtml`:
```html
<link rel="canonical" href="${canonicalBase}/jobs/${jobIndex}">
```

`canonicalBase` is resolved by `getLpCanonicalBase(slug)` from `lp-domains.ts`:

```typescript
export function getLpCanonicalBase(slug: string): string {
  const cfg = CUSTOM_DOMAINS[slug]
  return cfg ? `https://${cfg.host}` : `https://nippo-sync.vercel.app/lp/${slug}`
}
```

**Why canonical matters here:** The middleware serves identical HTML from both `cloq.recruitly.jp/` and `nippo-sync.vercel.app/lp/cloq`. Without a canonical tag, Google might index both URLs and split PageRank between them. The canonical tag tells Google: "this content belongs at `cloq.recruitly.jp/`, treat the Vercel URL as a duplicate." All ranking signal consolidates on the custom domain URL.

For slugs without a custom domain, canonical points to the Vercel URL — which is fine because there is only one URL.

### Open Graph tags

Every page emits a full Open Graph block:

```html
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical_url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="{company_name}">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{hero_bg_image}">  <!-- if present -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{hero_bg_image}">  <!-- if present -->
```

`og:url` matches the canonical URL — this is important because some platforms (LINE, Slack) use `og:url` to deduplicate previews, not the actual URL in the browser.

`og:locale` is `ja_JP` — this is a signal to social platforms and search engines that the content is Japanese, which helps with Japanese-language search ranking and correct language detection.

For job detail pages, the OG image prefers `d.hero_bg` (the job-specific hero image if set) and falls back to `c.hero.bg_image` (the LP-wide hero image).

### Organization JSON-LD (root page only)

The root LP page emits an `Organization` schema block:

```html
<script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "{company_name}",
  "url": "{canonical_base}",
  "logo": "{logo_image}",   // if set
  "sameAs": ["{website}"]   // if set
}</script>
```

This helps Google Knowledge Graph understand the company entity and can contribute to a company knowledge panel. `sameAs` links the LP to the company's primary website, which establishes entity association.

---

## 7. JobPosting JSON-LD (Google for Jobs)

This is the most important SEO element for the product. Google for Jobs is a specialised search surface that shows job listings above regular results — it has its own dedicated UI in Google Search with filters by location, job type, and salary. Appearing in Google for Jobs requires valid `JobPosting` structured data.

### Where it is emitted

`template/lib/lp-render.ts`, inside `renderJobDetailHtml()`, around line 620–700. It is emitted as an inline `<script type="application/ld+json">` block in the `<head>` of every `/jobs/{i}` page.

The root LP does **not** emit `JobPosting` JSON-LD — only individual job detail pages do. The root page emits `Organization` schema instead.

### Full schema structure

```json
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "製造スタッフ",
  "description": "<p>...</p>",
  "identifier": {
    "@type": "PropertyValue",
    "name": "株式会社CLOQ",
    "value": "cloq-0"
  },
  "directApply": true,
  "datePosted": "2026-04-01",
  "validThrough": "2026-07-01",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "株式会社CLOQ",
    "sameAs": "https://cloq.example.jp"
  },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "addressRegion": "大阪府",
      "addressLocality": "大阪市",
      "streetAddress": "西区...",
      "postalCode": "550-0001",
      "addressCountry": "JP"
    }
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "JPY",
    "value": {
      "@type": "QuantitativeValue",
      "minValue": 200000,
      "maxValue": 280000,
      "unitText": "MONTH"
    }
  }
}
```

### Field-by-field rationale

**`@type: "JobPosting"`** — Required. Tells Google this is a job posting eligible for the Google for Jobs surface.

**`title`** — The job title from `job.title`. Displayed prominently in Google for Jobs results. Required.

**`description`** — Full HTML job description. Minimum of ~100 characters required by Google. We use `composeJobDescriptionHtml(c, job, d)` from `lp-description.ts` to assemble structured HTML from intro, requirements, salary, and welfare data. An admin-set override `d.description_html` takes priority if present. The description is HTML-in-JSON — angle brackets are escaped as `<` to avoid breaking the JSON.

**`identifier`** — A stable unique ID for this job posting:
```json
{
  "@type": "PropertyValue",
  "name": "{company_name}",
  "value": "{slug}-{jobIndex}"
}
```
The `value` is `"{slug}-{jobIndex}"` (e.g. `"cloq-0"`). This is slug-scoped, so it's globally unique without needing a separate ID column in the DB. The identifier helps Google deduplicate the posting across re-crawls and across aggregators that may pick up the listing.

**`directApply`** — Signals to Google that applicants can apply directly on this page without being redirected to an external ATS. Since 2024, Google for Jobs shows an "Apply directly on company site" badge for `directApply: true` listings, which improves CTR. The value is `d.direct_apply !== false` — defaults `true` because the `/entry` route on this same domain handles all applications. Set `direct_apply: false` in the DB when the apply flow redirects off-domain to an external ATS. **Misrepresenting this as `true` when it's actually an external redirect is a Google policy violation that can suppress the entire domain from Google for Jobs.**

**`datePosted`** — When the job was posted. Only emitted if `d.posted_date` is set in the admin — we deliberately do not default to today's date. The reason: if we defaulted to today, every crawl would see a fresh `datePosted`, making the listing look like it's constantly being re-posted, which is a spam signal. Real `datePosted` values are set once when the admin creates or publishes the job.

**`validThrough`** — When the posting expires. This field is critical for Google for Jobs eligibility — Google documentation says postings without `validThrough` may be deprioritised in the jobs surface approximately 30 days after `datePosted`. The logic in code:

```typescript
const _validThrough =
  d.valid_through || (d.posted_date ? addDaysIso(d.posted_date, 90) : null)
```

Priority order:
1. `d.valid_through` — admin-set explicit date. Use this if the client knows their closing date.
2. `posted_date + 90 days` — automatic 90-day fallback. Stable across saves (computed from `posted_date`, not from today), so the value doesn't churn on every re-save. 90 days is long enough to keep listings active through typical hire cycles.
3. Omit `validThrough` entirely if neither is available.

The `addDaysIso` helper:
```typescript
function addDaysIso(isoDate: string, days: number): string | null {
  const t = Date.parse(isoDate)
  if (!Number.isFinite(t)) return null
  return new Date(t + days * 86400_000).toISOString().split('T')[0]
}
```

**`employmentType`** — e.g. `"FULL_TIME"`, `"PART_TIME"`, `"CONTRACTOR"`. Only emitted if `d.employment_type` is set. Google for Jobs uses this for job type filters.

**`hiringOrganization`** — Company name + `sameAs` pointing to the company's primary website (from `c.footer.website`). The `sameAs` link helps Google associate the job with the company entity.

**`jobLocation`** — Structured address from the LP's map configuration (`c.map`). Includes `addressRegion`, `addressLocality`, `streetAddress`, `postalCode`, and `addressCountry: "JP"`. Google for Jobs uses this for location-based filtering — jobs without location data don't appear in geographically-filtered searches.

**`baseSalary`** — Structured salary data in JPY. Prefers min/max range (`d.salary_min`, `d.salary_max`) over a single value (`d.salary_amount`). `unitText` defaults to `"MONTH"` (monthly salary, as is standard in Japan). Google for Jobs shows salary ranges in search results when provided, improving click quality.

### BreadcrumbList JSON-LD (also on job pages)

Job detail pages emit a second JSON-LD block alongside the `JobPosting`:

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "採用情報", "item": "https://cloq.recruitly.jp/" },
    { "@type": "ListItem", "position": 2, "name": "製造スタッフ", "item": "https://cloq.recruitly.jp/jobs/0" }
  ]
}
```

This helps Google understand the site hierarchy and can produce breadcrumb display in search results (e.g. `cloq.recruitly.jp > 採用情報 > 製造スタッフ`).

### How to verify

1. Go to [https://search.google.com/test/rich-results](https://search.google.com/test/rich-results)
2. Enter the job page URL (e.g. `https://cloq.recruitly.jp/jobs/0`)
3. The tool should detect a `JobPosting` result with green checkmarks on all required fields.
4. If there are errors, they'll list which required fields are missing or malformed.

Common issues:
- **`description` too short** — the composed description must be at least ~100 characters. Check `composeJobDescriptionHtml` output.
- **`datePosted` missing** — not a hard error but Google may downrank. Set `d.posted_date` in the admin.
- **`jobLocation` address incomplete** — if `c.map` has no fields set, the address object will only contain `addressCountry: "JP"`. Google can still index the posting but won't show it in location-filtered searches.

---

## 8. Google Indexing API (the fast-track)

For full setup details, see `docs/indexing-api.md` (if it exists) or the code comments in `template/lib/google-indexing.ts`.

### What it is

The Indexing API is a Google API that lets you directly tell Google "this URL was just updated, please crawl it now". Normally Google discovers URL changes through its crawl schedule — for a low-authority new domain, this can take days to weeks. The Indexing API bypasses that queue.

Critically, Google's documentation states that the Indexing API is specifically designed for pages with `JobPosting` or `BroadcastEvent` structured data. For those page types, Google gives Indexing API notifications priority treatment — recrawl typically happens within minutes.

### Where it's called

1. **`template/app/api/lp/[slug]/admin/content/route.ts`** — the main admin save endpoint. Every time an admin saves LP content via `PUT /api/lp/{slug}/admin/content`, this fires:

```typescript
await notifyIndexingApiForLp({
  slug,
  openingsCount: body.content.openings?.items?.length ?? 0,
  published,
}).catch((e) => console.warn('[lp-admin/content PUT] indexing notify failed:', e))
```

2. **`template/app/api/admin/lp-content-upsert/route.ts`** — the bootstrap/migration endpoint used by the skill to seed new LPs programmatically:

```typescript
await notifyIndexingApiForLp({
  slug,
  openingsCount: content.openings?.items?.length ?? 0,
  published: true,
}).catch((e) => console.warn('[lp-content-upsert] indexing notify failed:', e))
```

### Implementation: `google-indexing.ts`

**File:** `template/lib/google-indexing.ts`

The module uses `google-auth-library`'s `JWT` class to authenticate with the service account, then POSTs to `https://indexing.googleapis.com/v3/urlNotifications:publish`.

Key design decisions:

- **Fire-and-forget with catch**: both call sites use `.catch()` on the notify promise. If the Indexing API call fails (misconfigured service account, GSC ownership not granted, network error), it logs a warning but never blocks the save response. The save must always succeed regardless of indexing status.

- **No-op when LP is unpublished or has no jobs:**
```typescript
if (!published || openingsCount <= 0) {
  return { ok: 0, failed: 0, skipped: true }
}
```

- **Skips gracefully when `GOOGLE_SERVICE_ACCOUNT_JSON` is not set:**
```typescript
if (!token) {
  console.warn('[indexing] no GOOGLE_SERVICE_ACCOUNT_JSON — skipping')
  return { ok: 0, failed: 0, skipped: true }
}
```
This means the app works correctly in development (where the env var isn't set) without throwing errors.

- **Per-URL 5-second timeout**: `AbortSignal.timeout(5000)` per URL. Prevents a slow Google API response from hanging the save request.

- **Parallel requests via `Promise.allSettled`**: all job URLs are notified concurrently. Individual failures are logged but don't prevent other URLs from being notified.

### Required setup (one-time, human)

1. In Google Cloud Console: enable the "Indexing API" on the project that owns `GOOGLE_SERVICE_ACCOUNT_JSON`.
2. In Google Search Console: add the service account's `client_email` as an **Owner** of the GSC property for the custom domain. Read-only access is NOT sufficient — the Indexing API requires Owner access.
3. The env var `GOOGLE_SERVICE_ACCOUNT_JSON` must be set in Vercel with the full JSON of the service account key file.

### How to verify it's working

Check Vercel logs → Functions → the save route (`/api/lp/{slug}/admin/content`). After a save, you should see:

```
[indexing] slug=cloq urls=2 ok=2 failed=0 skipped=false
```

If you see `skipped=true`, either the LP is unpublished, has no jobs, or `GOOGLE_SERVICE_ACCOUNT_JSON` is missing.

If you see `failed=1` or similar, check the warning message — it will include the HTTP status code from Google's API and the error body. Common causes:
- `403` — service account is not an Owner of the GSC property.
- `400` — malformed URL (usually means canonical base resolved incorrectly).
- `401` — JWT auth failed (usually the service account JSON is malformed or the private key has newline issues).

---

## 9. Why /jobs/0 wasn't indexing — root cause analysis (CLOQ)

This section documents what happened with CLOQ's launch so the same situation can be recognised and fixed faster next time.

### Timeline

- CLOQ's root page (`cloq.recruitly.jp/`) was indexed by Google within a few days of launch.
- CLOQ's job pages (`cloq.recruitly.jp/jobs/0`, etc.) showed "Discovered - currently not indexed" in GSC for several weeks.

### Why the root page indexed quickly

Google has strong heuristics for indexing root pages. The root page was:
- Referenced in the sitemap.
- Accessible at the apex of a custom domain (Google tends to crawl and index the root of any new domain it discovers).
- Linked from the sitemap, which was submitted via GSC.

### Why the job pages didn't index

Three compounding factors:

**1. No inbound links.** External sites had zero links pointing to `/jobs/0`. Google's crawler prioritises pages with inbound authority. Brand-new subdomains with no backlinks must rely entirely on sitemaps and explicit crawl signals.

**2. Sitemap was present but not yet acted on.** The per-slug sitemap listed `/jobs/0`, but Google had queued it in its "Discovered" state without crawling. For low-authority domains, Google may queue URLs for weeks before crawling them.

**3. No explicit "this page is ready" signal.** Normal new URLs sit in Google's backlog. There was no mechanism to say "this page is important, crawl it now."

### The fix

The Indexing API is the direct solution. It fires a `URL_UPDATED` notification for each job page whenever the admin saves. Google responds to these notifications within minutes for `JobPosting` URLs (it's specifically documented as a priority use case). After wiring up the Indexing API, every admin save pushes all job URLs directly into Google's priority crawl queue.

---

## 10. Google Jobs widget vs. GSC 有効 — they are different

This distinction cost days of confusion during the CLOQ launch. **GSC 有効 and the Google Jobs widget are two completely separate pipelines.**

### GSC 求人情報レポート — "有効"

The GSC Enhancements report for job postings (`検索での見え方 → 求人情報`) shows whether the `JobPosting` JSON-LD on a page passes Google's schema validation. A status of **有効 (Valid)** only means:

- The page has been crawled
- The structured data parses without errors
- Required fields are present

It does **not** mean the job is being shown in the Google Jobs widget. These are independent decisions.

### Google Jobs widget — why a 有効 job might not appear

Even with 有効 schema, Google applies a separate ranking/eligibility filter for the Jobs widget. Known suppressors (confirmed from CLOQ investigation, 2026-04-28):

| Issue | Effect | Fix |
|---|---|---|
| Missing `postalCode` | Excluded from location-filtered searches; deprioritised in widget | Set `c.map.postal_code` in LP content |
| Missing `baseSalary.maxValue` | GSC flags as "改善できるアイテム"; widget may suppress | Set `d.salary_max` on each job |
| Missing `hiringOrganization.sameAs` | Google can't entity-match the company; lower trust signal | Set `c.footer.website` (auto-wired to `sameAs`) |
| Missing `hiringOrganization.logo` | No employer logo in widget card | Set `c.header.favicon_url` or `c.header.logo_image` (auto-wired) |
| `directApply: true` when flow redirects off-domain | Policy violation; can suppress domain-wide | Set `d.direct_apply = false` in DB |
| Deduplication by Indeed/aggregators | Google shows ONE version — usually Indeed | Ensure your schema is more complete than Indeed's listing |
| April 2026 GSC logging bug | Impressions/clicks for job listings not recording in GSC | Known Google bug; check widget independently |

### GSC "改善できるアイテム" (Can be improved)

These are not errors — the page stays 有効 — but they are strong widget-ranking signals. When GSC shows `postalCode` or `maxValue` as improvable items:

1. Go to GSC → 検索での見え方 → 求人情報 → 改善できるアイテム
2. Click the item to see affected URLs
3. Fix the data in the LP admin
4. Click **修正を検証** — this tells Google to re-crawl and re-evaluate. Status changes to "検証: 開始 {date}"

Do not skip the 修正を検証 step — without it Google won't re-evaluate the page even after you fix the data.

---

## 11. favicon_url vs logo_image — the logo split

The LP has two separate logo fields that serve different purposes. This mirrors how real company websites work.

| Field | Used for | Size/format |
|---|---|---|
| `header.logo_image` | LP page header `<img>` tag; `hiringOrganization.logo` fallback | Any — typically the full logo with wordmark |
| `header.favicon_url` | Browser tab icon (32×32, 192×192), apple-touch-icon (180×180), `hiringOrganization.logo` (preferred) | Square, no text — ideally the company's icon mark |

### Why favicon_url takes precedence for `hiringOrganization.logo`

Google for Jobs renders a small square employer logo in the widget card. A full portrait logo with wordmark (e.g. 412×454 px) renders poorly — the wordmark is illegible at small sizes. The square icon mark (192×192, no text) is what Google expects and what company websites serve as their favicon. Using `favicon_url` for `hiringOrganization.logo` matches Google's own expectation.

The code `c.header.favicon_url ?? c.header.logo_image` means: use the square icon if available, fall back to the full logo if not.

### How to populate these for a new client

During bootstrap:
1. Crawl the client's real website
2. Find the WordPress site icon URL pattern: `cropped-{hash}-192x192.png` or similar square crop in `<link rel="icon" sizes="192x192">`
3. Set `header.favicon_url` to that square icon URL
4. Set `header.logo_image` to the full logo (the one in their `<img>` navbar header)

If the client's site only has one logo (no separate favicon), use that same URL for both fields. The favicon links will still output correctly.

### Hosting on Supabase storage

It's better to host these files in the `lp-assets` Supabase bucket than to hotlink from the client's WordPress CDN — WordPress URLs are fragile (they change on media re-upload). Upload process:

```bash
# Temporarily grant anon upload (via execute_sql as postgres):
CREATE POLICY "temp_anon_upload" ON storage.objects FOR INSERT TO anon WITH CHECK (bucket_id = 'lp-assets');

# Upload:
curl -X POST "https://{project}.supabase.co/storage/v1/object/lp-assets/{slug}/icon-192.png" \
  -H "Authorization: Bearer {anon_key}" \
  -H "Content-Type: image/png" \
  --data-binary @/tmp/icon-192.png

# Remove the temporary policy:
DROP POLICY "temp_anon_upload" ON storage.objects;
```

Public URL: `https://{project}.supabase.co/storage/v1/object/public/lp-assets/{slug}/icon-192.png`

---

## 12. What to do when a new LP is live but not indexing

Work through these steps in order. Don't skip ahead.

### Step 1: Verify the page actually renders

```bash
curl -s -o /dev/null -w "%{http_code}" https://cloq.recruitly.jp/jobs/0
```

Should return `200`. If it returns anything else, the indexing problem is a server problem, not an SEO problem — fix the rendering first.

Also verify the HTML contains real content (not a loading spinner or JS-only shell):

```bash
curl -s https://cloq.recruitly.jp/jobs/0 | grep -o '<title>.*</title>'
```

This product returns fully server-rendered HTML, so there should be no hydration problem.

### Step 2: Check GSC URL inspection

Go to [https://search.google.com/search-console/](https://search.google.com/search-console/) → select the property → URL Inspection → enter the job URL.

**Scenario A: "URL is not on Google"**
- Google has never seen this URL.
- Check: is the sitemap submitted? (GSC → Sitemaps)
- Check: does robots.txt allow crawling? (`curl https://{host}/robots.txt`)
- Fix: use the "Request indexing" button in GSC URL inspection, AND trigger an Indexing API ping by saving in admin.

**Scenario B: "Discovered - currently not indexed"**
- Google found the URL (from sitemap or a link) but hasn't crawled it yet.
- This is the CLOQ problem. The URL is in Google's queue but hasn't been prioritised.
- Fix: trigger the Indexing API by saving the LP in admin. Check Vercel logs for `[indexing] slug=... ok=N` to confirm the ping went through.
- Also use: GSC URL inspection → "Request indexing" button. This queues a manual crawl from the GSC UI.
- Give it 30–60 minutes after the Indexing API ping, then re-check.

**Scenario C: "Crawled - currently not indexed"**
- Google crawled the page and decided not to index it. This is a content quality or technical issue.
- Check: Rich Results Test for JobPosting errors (`https://search.google.com/test/rich-results`). Missing required fields can disqualify the page.
- Check: is there a `noindex` meta tag? (`curl -s https://{host}/jobs/0 | grep 'noindex'`)
- Check: does the canonical point to itself? (`curl -s https://{host}/jobs/0 | grep 'canonical'`) — it should be `href="https://{host}/jobs/0"`, not a different URL.
- Check: is the page content thin? Google may reject pages with very little text. Ensure `description`, `d.intro`, and requirement fields are filled in.

**Scenario D: "URL is on Google"**
- The page is indexed. If it's not appearing for expected searches, that's a ranking problem, not an indexing problem — different category.

### Step 3: Check Indexing API logs

In Vercel → Functions, filter by the admin content route:

```
/api/lp/[slug]/admin/content
```

Look for lines like:
```
[indexing] slug=cloq urls=2 ok=2 failed=0 skipped=false
```

If `skipped=true`: either the LP is unpublished, has no jobs, or `GOOGLE_SERVICE_ACCOUNT_JSON` is missing.
If `failed=N`: check the preceding warning lines for the error detail from the Google API.

### Step 4: Check sitemap is reachable and accurate

```bash
curl https://{host}/sitemap.xml
```

Should return XML with all job URLs listed. If it returns an error or is missing jobs:
- Check the DB has `published = true` for this slug.
- Check `lp_content.content.openings.items` has the expected items.

In GSC: Sitemaps → check the sitemap was submitted and shows the correct URL count.

---

## 13. GSC property setup for a new custom domain

When a new client goes live with a custom domain, follow these steps.

### Option A: Domain property (recommended long-term)

A domain property in GSC covers all subdomains (`www.`, `cloq.`, etc.) and both HTTP/HTTPS automatically. Requires a DNS TXT record for verification.

Best for: clients who own their domain and can modify DNS, and who have multiple subdomains or expect long-term use.

Verification: GSC → Add property → Domain property → enter `recruitly.jp` → copy TXT record → add to DNS. This requires access to the domain registrar's DNS settings.

### Option B: URL-prefix property (current approach for CLOQ)

A URL-prefix property is scoped to a specific URL prefix. Easier to set up — HTML tag verification, no DNS change required.

Verification: GSC → Add property → URL-prefix property → enter `https://cloq.recruitly.jp/` → verify via HTML tag method.

### Step-by-step for Option B (new client)

**1. Generate a GSC verification token**

- Go to [https://search.google.com/search-console/](https://search.google.com/search-console/)
- Add property → URL-prefix → `https://{custom-host}/`
- Select "HTML tag" verification method
- Copy the token from the `content` attribute (NOT the whole tag, just the value)

**2. Add the token to `lp-domains.ts`**

In `template/lib/lp-domains.ts`, add or update the slug's entry:

```typescript
const CUSTOM_DOMAINS: Record<string, CustomDomainConfig> = {
  newclient: {
    host: 'newclient.example.jp',
    brandName: 'NEWCLIENT',
    brandColor: '#123456',
    googleSiteVerification: [
      'CLIENT_TOKEN_HERE',  // client verified this
      'JAYDEN_TOKEN_HERE',  // Jayden (MGC) verified this
    ],
  },
}
```

If the client wants to verify themselves (recommended so they have Owner access), they need to go through the same GSC flow and give you their token to add.

**3. Deploy to Vercel**

After deploying, verify the meta tags appear:

```bash
curl -s https://{custom-host}/ | grep 'google-site-verification'
```

Should show one `<meta>` tag per token.

**4. Complete GSC verification**

In GSC, click "Verify" — it will fetch the page and confirm the meta tag is present.

**5. Add the service account as Owner**

In GSC → Settings → Users & Permissions → Add User:
- Email: the `client_email` from `GOOGLE_SERVICE_ACCOUNT_JSON`
- Role: **Owner** (not Editor or Viewer — the Indexing API requires Owner)

This step is required for the Indexing API to work. If you skip it, every Indexing API call will return 403.

**6. Submit the sitemap**

In GSC → Sitemaps → Add a new sitemap → enter `https://{custom-host}/sitemap.xml`.

**7. Trigger the first indexing ping**

Save the LP content in the admin UI. This fires `notifyIndexingApiForLp`, which pings Google for all job URLs. Check Vercel logs to confirm `ok=N` for the expected number of job pages.

---

## 14. Admin pages and noindex

The admin UI lives under `/admin` on every custom domain. It is password-protected (via cookie-based session from `lp-admin-session.ts`), but the pages are technically accessible if someone knows the URL. To prevent Google from indexing admin pages:

1. **`robots.txt` has `Disallow: /admin`** — this tells crawlers not to visit admin paths at all.

2. If the admin pages ever render HTML directly (rather than being API-only), they should include `<meta name="robots" content="noindex">` in their `<head>`.

The current admin UI is largely JavaScript-driven (fetches content via API, renders client-side), so there is minimal static HTML for Google to index — but the robots.txt disallow is the primary guard.

---

## 15. Complete SEO checklist for a new client launch

Use this checklist when onboarding a new client LP. Each item maps to a section above.

**Infrastructure**
- [ ] Custom domain added in Vercel project → Domains
- [ ] Client configured DNS (CNAME/ANAME to `cname.vercel-dns.com`)
- [ ] Slug + host added to `CUSTOM_DOMAINS` in `template/lib/lp-domains.ts`
- [ ] Deployed to Vercel; page renders with `curl -s https://{host}/ | grep '<title>'`

**GSC ownership**
- [ ] GSC property created for `https://{custom-host}/` (URL-prefix method)
- [ ] Client verification token added to `googleSiteVerification` array + deployed
- [ ] Jayden verification token added to `googleSiteVerification` array + deployed
- [ ] Both owners verified in GSC (click "Verify" button)
- [ ] Service account added as **Owner** in GSC → Users & Permissions (not Full User!)
- [ ] Sitemap submitted in GSC → Sitemaps: `https://{custom-host}/sitemap.xml`

**LP content — Google for Jobs widget signals (set all or widget may suppress)**
- [ ] `header.favicon_url` — square icon (192×192, no wordmark), from client's real site favicon
- [ ] `header.logo_image` — full logo with wordmark, from client's real site header
- [ ] `footer.website` — client's primary website URL (wires to `hiringOrganization.sameAs`)
- [ ] `map.postal_code` — 〒 postal code (e.g. "537-0021") — missing = excluded from location search
- [ ] `map.region`, `map.locality`, `map.street` — full address for `jobLocation`
- [ ] Per-job: `detail.salary_min` + `detail.salary_max` — missing `maxValue` = GSC "改善できるアイテム"
- [ ] Per-job: `detail.posted_date` — ISO date set at creation (not auto-derived from today)
- [ ] Per-job: `detail.employment_type` — e.g. `"FULL_TIME"`
- [ ] Per-job: `detail.direct_apply` — leave unset (defaults true) if apply flow stays on-domain; set `false` if it redirects to an external ATS

**Indexing**
- [ ] LP content saved in admin (triggers first Indexing API ping)
- [ ] Vercel logs confirm `[indexing] slug=... ok=N failed=0`
- [ ] Rich Results Test for at least one `/jobs/{i}` URL — all required fields green
- [ ] GSC → 検索での見え方 → 求人情報: check for "改善できるアイテム" warnings; click 修正を検証 if any
- [ ] GSC URL inspection on root page and at least one job page — "URL is on Google" within 24–48h
- [ ] Google Jobs widget check: search `{job title} {city} 求人` in Google — job card should appear within a few days

---

*Last updated: 2026-04-28. Reflects CLOQ Google Jobs widget investigation: added §10 (有効 vs widget distinction), §11 (favicon_url/logo split), updated §7 (directApply conditionalisation, hiringOrganization.logo), updated §15 checklist with full widget signal requirements.*
