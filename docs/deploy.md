# MGC 採用LP — Deploy Workflow Reference

> **Audience**: A future Claude working on this skill.
> **Last updated**: 2026-04-26
> **Status**: ⛔ **OBSOLETE (retired 2026-06-16).** The `template/` snapshot this document is built around has been **removed**. The sole source of truth is now the deployed **nippo-sync** repo (`~/Developer/nippo-sync-local/src/`, GitHub `jaydenbarnescs-tech/nippo-sync`, branch `main`) — that is literally what Vercel builds. **Do NOT follow the `template/`-copy procedures below.** Edit `src/` directly after `git fetch origin`, then commit + push to `main` (Vercel auto-deploys). See **SKILL.md RULE 24**.

---

## Table of Contents

1. [Mental model: two locations, one source of truth](#1-mental-model-two-locations-one-source-of-truth)
2. [Directory map](#2-directory-map)
3. [Template update workflow](#3-template-update-workflow)
4. [Localhost-first deploy workflow (required)](#4-localhost-first-deploy-workflow-required)
5. [Deploying to production (Vercel)](#5-deploying-to-production-vercel)
6. [Syncing the template from nippo-sync back to skill](#6-syncing-the-template-from-nippo-sync-back-to-skill)
7. [Bootstrap workflow for a new client LP](#7-bootstrap-workflow-for-a-new-client-lp)
8. [Rollback and incident response](#8-rollback-and-incident-response)
9. [File-by-file reference](#9-file-by-file-reference)
10. [Quick-reference cheat sheet](#10-quick-reference-cheat-sheet)

---

## 1. Mental model: two locations, one source of truth

The LP product code lives in two places on this machine, and they serve different purposes.

### The skill's `template/` — source of truth for LP code

```
/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap/template/
```

This is a pinned snapshot (as of 2026-04-26) of every LP-related file. It is the **canonical definition** of what the LP product is. When you want to make an intentional improvement to the LP product, you start here. Nothing in this directory belongs to the daily-report system, Slack auth, or any other nippo feature. It is LP-only.

### nippo-sync — live deployment target

```
/Users/jayden.csai/Developer/nippo-sync-local/src/
```

This is the full Next.js monorepo that also contains the daily-report features, Slack OAuth, admin dashboards, and other nippo functionality. The LP files are a subset of this codebase. When you push a commit to `main` on this repo, Vercel auto-deploys it to production within ~60–90 seconds.

### Why the separation exists

| Risk | How the separation prevents it |
|------|-------------------------------|
| nippo-sync changes accidentally overwrite LP code | LP code only changes when you deliberately copy from `template/` |
| LP changes accidentally overwrite nippo-sync non-LP code | `cp` commands are file-specific; `cp -r template/ src/` is forbidden |
| nippo-sync breaks; need to restore LP code | Restore by copying from `template/` — no git archaeology needed |
| "Which version is deployed?" is ambiguous | If `template/` == what was last copied to nippo-sync, they're in sync |

**The invariant**: after any complete deploy cycle, `template/` should be identical to what is running in production for every LP file. Keep them in sync. If you notice they've drifted, fix it immediately (see [Section 6](#6-syncing-the-template-from-nippo-sync-back-to-skill)).

---

## 2. Directory map

### Skill directory (source of truth)

```
/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap/

template/                                      ← LP code snapshot — edit here first
├── middleware.ts                              ← custom domain routing / rewrite logic
├── lib/
│   ├── lp-render.ts                          ← HTML renderer (the main LP output function)
│   ├── lp-content-types.ts                   ← TypeScript types for LpContent JSON
│   ├── lp-domains.ts                         ← slug → custom domain mapping (edit per client)
│   ├── lp-admin-session.ts                   ← admin cookie / session helpers
│   ├── lp-description.ts                     ← meta description generation
│   ├── google-indexing.ts                    ← Google Indexing API integration
│   ├── google-oauth.ts                       ← Google OAuth flow for admin login
│   ├── pg.ts                                 ← Postgres/Supabase connection pool
│   └── sheets.ts                             ← Google Sheets sync helpers
└── app/
    ├── lp/[slug]/                            ← public-facing LP pages
    │   ├── route.ts                          ← main LP page (GET → renderLp())
    │   ├── entry/route.ts                    ← job application form submission
    │   ├── jobs/[index]/route.ts             ← individual job page
    │   ├── privacy/route.ts                  ← privacy policy page
    │   ├── robots.txt/route.ts               ← robots.txt response
    │   ├── sitemap-xml/route.ts              ← XML sitemap
    │   └── admin/
    │       ├── page.tsx                      ← admin shell (React server component)
    │       ├── AdminDashboard.tsx            ← main admin UI (client component)
    │       ├── ConnectScreen.tsx             ← first-time Sheets connect UI
    │       ├── FirstSetupScreen.tsx          ← initial LP claim/setup UI
    │       └── LpContentEditor.tsx           ← content editing modal
    └── api/
        ├── lp/[slug]/                        ← per-LP API routes
        │   ├── admin-first-setup/route.ts    ← claim LP ownership
        │   ├── admin/analytics/route.ts      ← read analytics events
        │   ├── admin/content/route.ts        ← read/write LP content
        │   ├── admin/domain-attach/route.ts  ← attach custom domain
        │   ├── admin/domain-check/route.ts   ← verify domain DNS status
        │   ├── admin/entries/route.ts        ← list job applications
        │   ├── admin/entries/[id]/route.ts   ← single application detail
        │   ├── admin/invites/route.ts        ← invite additional admins
        │   ├── admin/settings/route.ts       ← LP-level settings
        │   ├── admin/signout/route.ts        ← sign out of admin
        │   ├── admin/sync/route.ts           ← trigger Sheets sync
        │   ├── admin/upload/route.ts         ← image upload to storage
        │   └── track/route.ts               ← analytics event ingestion
        ├── lp-entry/route.ts                ← global entry handler (redirects)
        ├── admin/lp-content-upsert/route.ts ← internal: upsert lp_content rows
        ├── admin/reset-lp-claim/route.ts    ← internal: reset ownership claim
        └── sheets/connect/
            ├── [slug]/authorize/route.ts    ← start Sheets OAuth for slug
            ├── accept/route.ts              ← OAuth accept handler
            └── callback/route.ts            ← OAuth callback handler

scripts/                                       ← Laptop-local bootstrap scripts
├── bootstrap.py                              ← crawl + compose full lp_content JSON
├── crawl_reference.py                        ← crawl reference company site
├── extract_design.py                         ← visual design extraction
├── compose_lpcontent.py                      ← assemble lp_content from parts
├── image_pipeline.py                         ← process and upload hero images
└── analytics_bootstrap.py                    ← seed analytics tables for new LP

docs/                                          ← This documentation
└── deploy.md                                 ← You are here
```

### nippo-sync destination paths

Each `template/` file maps to a corresponding path under `nippo-sync-local/src/`:

| Template path | nippo-sync path |
|--------------|----------------|
| `template/middleware.ts` | `src/middleware.ts` |
| `template/lib/*.ts` | `src/lib/*.ts` |
| `template/app/lp/[slug]/**` | `src/app/lp/[slug]/**` |
| `template/app/api/lp/[slug]/**` | `src/app/api/lp/[slug]/**` |
| `template/app/api/lp-entry/route.ts` | `src/app/api/lp-entry/route.ts` |
| `template/app/api/admin/lp-content-upsert/route.ts` | `src/app/api/admin/lp-content-upsert/route.ts` |
| `template/app/api/admin/reset-lp-claim/route.ts` | `src/app/api/admin/reset-lp-claim/route.ts` |
| `template/app/api/sheets/connect/**` | `src/app/api/sheets/connect/**` |

---

## 3. Template update workflow

Follow this sequence every time you make an LP improvement. Do not skip steps.

### Step 1 — Edit the file in `template/` first

The template is the source of truth. Your change begins here, not in nippo-sync.

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap

# Open the file you want to change:
code "$SKILL/template/lib/lp-render.ts"
# or: code "$SKILL/template/lib/lp-domains.ts"
# or: code "$SKILL/template/app/lp/[slug]/route.ts"
# etc.
```

Make your edit and save it. At this point only the template has changed; nippo-sync is still on the old version.

### Step 2 — Copy to nippo-sync

Copy **only the files you changed**. Do not do a bulk `cp -r`. nippo-sync contains many files that are not in `template/` and must not be touched.

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap
NIPPO=/Users/jayden.csai/Developer/nippo-sync-local/src

# Copy a single lib file:
cp "$SKILL/template/lib/lp-render.ts" "$NIPPO/lib/lp-render.ts"

# Copy multiple lib files at once:
cp "$SKILL/template/lib/lp-render.ts"         "$NIPPO/lib/"
cp "$SKILL/template/lib/lp-domains.ts"        "$NIPPO/lib/"
cp "$SKILL/template/lib/lp-content-types.ts"  "$NIPPO/lib/"
cp "$SKILL/template/lib/lp-admin-session.ts"  "$NIPPO/lib/"
cp "$SKILL/template/lib/lp-description.ts"    "$NIPPO/lib/"
cp "$SKILL/template/lib/google-indexing.ts"   "$NIPPO/lib/"
cp "$SKILL/template/lib/google-oauth.ts"      "$NIPPO/lib/"
cp "$SKILL/template/lib/pg.ts"                "$NIPPO/lib/"
cp "$SKILL/template/lib/sheets.ts"            "$NIPPO/lib/"

# Copy middleware (rarely changes, but same pattern):
cp "$SKILL/template/middleware.ts" "$NIPPO/middleware.ts"

# Copy a specific API route:
cp "$SKILL/template/app/api/lp/[slug]/admin/content/route.ts" \
   "$NIPPO/app/api/lp/[slug]/admin/content/route.ts"

# Copy all admin UI files (be careful — this replaces all 5 files):
cp "$SKILL/template/app/lp/[slug]/admin/page.tsx"             "$NIPPO/app/lp/[slug]/admin/"
cp "$SKILL/template/app/lp/[slug]/admin/AdminDashboard.tsx"   "$NIPPO/app/lp/[slug]/admin/"
cp "$SKILL/template/app/lp/[slug]/admin/ConnectScreen.tsx"    "$NIPPO/app/lp/[slug]/admin/"
cp "$SKILL/template/app/lp/[slug]/admin/FirstSetupScreen.tsx" "$NIPPO/app/lp/[slug]/admin/"
cp "$SKILL/template/app/lp/[slug]/admin/LpContentEditor.tsx"  "$NIPPO/app/lp/[slug]/admin/"
```

> **NEVER run**: `cp -r "$SKILL/template/" "$NIPPO/"` — this would silently wipe nippo-sync's non-LP files because `template/` does not contain them. Always copy file-by-file or directory-by-directory for LP subtrees only.

### Step 3 — Test locally

Run the full local test procedure from [Section 4](#4-localhost-first-deploy-workflow-required). Do not proceed until all checks pass.

### Step 4 — Deploy to production

Follow [Section 5](#5-deploying-to-production-vercel).

### Step 5 — Sync template back if you improved the file during testing

If you made any further edits to the nippo-sync copy during the local test (fixing a type error, adjusting a curl response, etc.), copy back to the template so they stay in sync:

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap
NIPPO=/Users/jayden.csai/Developer/nippo-sync-local/src

cp "$NIPPO/lib/lp-render.ts" "$SKILL/template/lib/lp-render.ts"
# Repeat for any other files you modified in nippo-sync after the initial copy
```

After this step, `template/` == what is deployed. The invariant is restored.

---

## 4. Localhost-first deploy workflow (required)

**Never push LP changes to production without running a local test first.** This rule is non-negotiable. A broken deploy affects every client on the platform, not just the one you're working on. A local test takes about 30–60 seconds and catches the majority of mistakes.

### Step 1 — Verify `.env.local` exists

```bash
ls -la /Users/jayden.csai/Developer/nippo-sync-local/.env.local
```

If the file is missing, stop. You cannot test without it. The file is never committed to git. Ask Jayden to restore it from 1Password or from the last known good state.

Required environment variables for LP testing:

```
# Supabase
POSTGRES_URL=postgresql://...                    # Direct connection string (not pooler)
NEXT_PUBLIC_SUPABASE_URL=https://...supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...

# Google service account (for Indexing API and Sheets)
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}   # Full JSON as a single-line string

# Google OAuth (for admin login)
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...

# Auth
AUTH_SECRET=...    # Any 32-byte random string; only needs to be consistent per environment
```

If any of these are missing or wrong, the LP renderer will fail to fetch content from Supabase, admin login won't work, or Indexing API calls will return 401.

### Step 2 — Start the dev server

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local
npm run dev
```

Wait for the following line in the console before running any curl checks:

```
▲ Next.js 14.x.x
- Local:        http://localhost:3000
✓ Ready
```

If the server exits immediately, check for:
- TypeScript compilation errors (they appear before "Ready")
- Missing `node_modules` — run `npm install` first
- Port conflict — something else is using 3000; kill it with `lsof -ti:3000 | xargs kill`

### Step 3 — Run the core LP smoke tests

Use the CLOQ LP (slug = `cloq`) as the canonical test target. It is a real, production LP with a fully populated database, so it exercises the actual render path.

```bash
# 1. Main LP page renders and contains the company name
curl -s http://localhost:3000/lp/cloq | grep -i "cloq"
# Expected: one or more matches — the company name appears in the HTML

# 2. Japanese recruitment copy is present (confirms DB content loaded)
curl -s http://localhost:3000/lp/cloq | grep -i "採用"
# Expected: match — if this misses, the DB fetch failed or lp_content is empty

# 3. og:title is the client's title, not a generic nippo string
curl -s http://localhost:3000/lp/cloq | grep "og:title"
# Expected: content="CLOQ採用情報" (or similar)
# FAIL if: content="日報シンクロくん" — that means the render is using fallback/wrong data

# 4. Job pages render JSON-LD structured data
curl -s http://localhost:3000/lp/cloq/jobs/0 | grep "JobPosting"
# Expected: match — the JSON-LD schema block is present

# 5. Sitemap is valid XML
curl -s http://localhost:3000/lp/cloq/sitemap-xml | head -5
# Expected: starts with <?xml version="1.0"

# 6. robots.txt is correct
curl -s http://localhost:3000/lp/cloq/robots.txt
# Expected: contains "User-agent: *" and "Sitemap:" lines

# 7. Admin page loads (HTTP 200 — admin auth is client-side, not a server redirect)
curl -sI http://localhost:3000/lp/cloq/admin | grep "HTTP"
# Expected: HTTP/1.1 200 OK

# 8. Privacy page renders
curl -sI http://localhost:3000/lp/cloq/privacy | grep "HTTP"
# Expected: HTTP/1.1 200 OK

# 9. Track endpoint accepts POST (analytics ingestion)
curl -s -X POST http://localhost:3000/api/lp/cloq/track \
  -H "Content-Type: application/json" \
  -d '{"event":"pageview","path":"/lp/cloq"}' | grep -i "ok\|success\|{}"
# Expected: any 200 response body (not a 500)
```

### Step 4 — Test the specific change you made

Run a targeted check for whatever you just changed.

**If you changed `lp-render.ts`** (e.g. added a new meta tag, changed HTML structure):

```bash
# Verify the new element appears in the rendered output
curl -s http://localhost:3000/lp/cloq | grep "your-new-element-or-attribute"
# Expected: match

# Also check that existing elements weren't broken
curl -s http://localhost:3000/lp/cloq | grep "og:image"
curl -s http://localhost:3000/lp/cloq | grep "canonical"
curl -s http://localhost:3000/lp/cloq | grep "application/ld+json"
```

**If you changed `lp-domains.ts`** (e.g. added a custom domain for a new client):

```bash
# Verify the slug is still recognized under its /lp/ path
curl -sI http://localhost:3000/lp/cloq | grep "HTTP"
# Expected: 200 — existing slugs must not break

# To test custom domain routing locally, temporarily add an entry to /etc/hosts:
# sudo sh -c 'echo "127.0.0.1 cloq.recruitly.jp" >> /etc/hosts'
# Then: curl -sI http://cloq.recruitly.jp:3000/
# Then remove it after testing
# Alternatively: verify the routing logic by reading middleware.ts — it is a simple host match
```

**If you changed an API route** (e.g. `admin/content/route.ts`):

```bash
# Test the API endpoint directly (most require a valid admin session cookie)
# The easiest way to test admin API routes is:
# 1. Open http://localhost:3000/lp/cloq/admin in a browser
# 2. Sign in with Google OAuth (uses real credentials even locally)
# 3. Exercise the feature you changed (save content, sync sheets, etc.)
# 4. Watch the terminal running 'npm run dev' for server logs

# For non-authed endpoints:
curl -s http://localhost:3000/api/lp/cloq/track -X POST \
  -H "Content-Type: application/json" \
  -d '{"event":"pageview","path":"/lp/cloq"}'
```

**If you changed `middleware.ts`**:

```bash
# The middleware controls custom domain rewrites. After changing it, restart the dev server:
# Ctrl+C then npm run dev again — middleware changes sometimes don't hot-reload reliably

# Verify the /lp/ path still works (middleware must not break default routing):
curl -sI http://localhost:3000/lp/cloq | grep "HTTP"
# Expected: 200

# For custom domain logic: use /etc/hosts trick (see lp-domains.ts section above)
# or verify the rewrite conditions by reading the middleware source
```

**If you changed an admin UI component** (e.g. `AdminDashboard.tsx`, `LpContentEditor.tsx`):

```bash
# These are React client components — curl won't help much
# Test in a browser:
# 1. Open http://localhost:3000/lp/cloq/admin
# 2. Sign in
# 3. Exercise the UI change manually
# 4. Check browser console for JS errors
# 5. Check network tab for failed API calls
```

### Step 5 — TypeScript check

Catches type errors before they reach Vercel's build step.

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local
npx tsc --noEmit
```

Expected output: nothing (no output = no errors). If there are errors, fix them before proceeding. Do not push code that fails `tsc`.

Common LP-specific TypeScript errors and fixes:

| Error | Cause | Fix |
|-------|-------|-----|
| `TS18047: X is possibly 'null'` | Missing null guard on a DB result | Add `if (!x) return ...` before using `x` |
| `TS2339: Property 'X' does not exist on type` | LpContent type mismatch | Update `lp-content-types.ts` to add the field |
| `TS2345: Argument of type 'string \| undefined'` | Optional field passed where required | Use `x ?? ""` or add a null check |
| `no-explicit-any` lint warning | Using `any` type | Pre-existing `any` usages are acceptable; new ones should use typed alternatives |

### Step 6 — Lint check

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local
npm run lint
```

Focus on **errors** from files you touched. Warnings in files you didn't touch are pre-existing and can be ignored. Fix any errors before deploying.

### Step 7 — All checks pass — ready to deploy

Only proceed to [Section 5](#5-deploying-to-production-vercel) after:
- [x] All smoke tests pass (Section 4, Step 3)
- [x] Targeted test for your change passes (Step 4)
- [x] `npx tsc --noEmit` produces no output (Step 5)
- [x] `npm run lint` shows no errors in your files (Step 6)

---

## 5. Deploying to production (Vercel)

nippo-sync deploys automatically from the `main` branch via Vercel's GitHub integration. There are no manual deploy commands; pushing to `main` is the deploy.

### Step 1 — Commit your changes with specific file staging

Stage only the LP files you changed. Never use `git add -A` or `git add .` — nippo-sync contains files with secrets and generated artifacts that must not be committed accidentally.

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local

# Stage specific files:
git add src/lib/lp-render.ts
git add src/lib/lp-domains.ts
# Add any other LP files you changed, one at a time

# Verify what you're about to commit:
git diff --staged --stat

# Commit with a descriptive message:
git commit -m "feat(lp): <describe the change briefly>"

# Good commit message examples:
# feat(lp): add structured data for FAQ section
# fix(lp): null guard on lp_content.jobs when array is empty
# feat(lp): map cloq.recruitly.jp custom domain
# chore(lp): update og:image dimensions for Twitter card spec
```

### Step 2 — Push to main

```bash
git push origin main
```

### Step 3 — Watch the Vercel deploy

Open the Vercel deployments page:

```
https://vercel.com/team_InumbXmdUdRp3WpMs47TFd8s/nippo-sync/deployments
```

A new deployment will appear at the top with status "Building". Wait for it to reach **"Ready"** (green). This typically takes 60–90 seconds.

If the build fails:
- Click into the failed deployment to see the build log
- The most common cause is a TypeScript error that `tsc --noEmit` missed due to strict mode differences
- Fix the error in nippo-sync, copy back to `template/`, and push a new commit (do not amend)

### Step 4 — Curl verify production

**You must run these checks after every LP-affecting deploy.** Vercel reporting "deployment successful" means the build compiled — it does not mean the routes return correct content.

```bash
# 1. HTTP status check
curl -sI https://nippo-sync.vercel.app/lp/cloq | grep "HTTP"
# Expected: HTTP/2 200

# 2. Company name in response (confirms DB fetch worked in production)
curl -s https://nippo-sync.vercel.app/lp/cloq | grep "CLOQ"
# Expected: match

# 3. og:title is the client's title, not a generic nippo string
curl -s https://nippo-sync.vercel.app/lp/cloq | grep "og:title"
# Expected: content="CLOQ採用情報" or similar client title
# FAIL if: content="日報シンクロくん"

# 4. If the client has a custom domain, verify that too:
curl -sI https://cloq.recruitly.jp/
# Expected: HTTP/2 200

curl -s https://cloq.recruitly.jp/ | grep "CLOQ"
# Expected: match

# 5. Verify the specific thing you changed:
# (same grep as you ran against localhost — just swap the host)
curl -s https://nippo-sync.vercel.app/lp/cloq | grep "your-new-element"
# Expected: match
```

Only say "done" after all these checks pass. If any check fails, do not announce success — diagnose and fix first.

---

## 6. Syncing the template from nippo-sync back to skill

Occasionally nippo-sync will get changes to LP files that weren't made through the template workflow — for example, Jayden made a quick fix directly in nippo-sync, or a dependency update touched a shared file. When this happens, the template has drifted and must be updated.

### Check for drift

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap
NIPPO=/Users/jayden.csai/Developer/nippo-sync-local/src

# Diff every LP file:
diff "$NIPPO/middleware.ts"                     "$SKILL/template/middleware.ts"
diff "$NIPPO/lib/lp-render.ts"                 "$SKILL/template/lib/lp-render.ts"
diff "$NIPPO/lib/lp-content-types.ts"          "$SKILL/template/lib/lp-content-types.ts"
diff "$NIPPO/lib/lp-domains.ts"                "$SKILL/template/lib/lp-domains.ts"
diff "$NIPPO/lib/lp-admin-session.ts"          "$SKILL/template/lib/lp-admin-session.ts"
diff "$NIPPO/lib/lp-description.ts"            "$SKILL/template/lib/lp-description.ts"
diff "$NIPPO/lib/google-indexing.ts"           "$SKILL/template/lib/google-indexing.ts"
diff "$NIPPO/lib/google-oauth.ts"              "$SKILL/template/lib/google-oauth.ts"
diff "$NIPPO/lib/pg.ts"                        "$SKILL/template/lib/pg.ts"
diff "$NIPPO/lib/sheets.ts"                    "$SKILL/template/lib/sheets.ts"
```

No output = in sync. Any output = drift — read the diff, understand it, then copy back.

### Copy back to template

```bash
# Only for files where the nippo-sync version is newer / better:
cp "$NIPPO/lib/lp-render.ts"   "$SKILL/template/lib/lp-render.ts"
cp "$NIPPO/lib/lp-domains.ts"  "$SKILL/template/lib/lp-domains.ts"
# etc.
```

After copying back, the template is again in sync with production.

---

## 7. Bootstrap workflow for a new client LP

This section describes what the skill does end-to-end when creating a new client LP. It is a reminder of the order of operations — each phase is described in more detail in other skill docs, but the deploy steps follow the same rules as this document.

### Phase 1 — Generate lp_content JSON (laptop-local)

```bash
cd ~/.claude/skills/mgc-saiyo-lp-bootstrap
python3 scripts/bootstrap.py --slug <new-slug> --client-name "<client-name>" --primary-url https://...
```

This crawls the client's website, extracts design tokens and copy, and assembles the `lp_content` JSON structure. Output is a `lp_content.json` file.

### Phase 2 — Insert into Supabase

Claude reads the `lp_content.json` and runs:

```sql
INSERT INTO public.lps (slug, name, ...) VALUES ('<slug>', '...', ...);
INSERT INTO public.lp_content (lp_id, data) VALUES ((SELECT id FROM public.lps WHERE slug = '<slug>'), '...');
```

### Phase 3 — Update lp-domains.ts if client has a custom domain

If the client will use a custom domain (e.g. `brand.recruitly.jp`):

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap

# Edit the template first:
code "$SKILL/template/lib/lp-domains.ts"
# Add: "brand.recruitly.jp": "<slug>",

# Then copy to nippo-sync:
cp "$SKILL/template/lib/lp-domains.ts" \
   /Users/jayden.csai/Developer/nippo-sync-local/src/lib/lp-domains.ts
```

### Phase 4 — Local test for the new LP

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local
npm run dev  # if not already running

# Test the new LP slug:
curl -s http://localhost:3000/lp/<new-slug> | grep -i "<company-name>"
# Expected: match

curl -s http://localhost:3000/lp/<new-slug> | grep "採用"
# Expected: match

curl -s http://localhost:3000/lp/<new-slug> | grep "og:title"
# Expected: client-specific title, not "日報シンクロくん"

curl -s http://localhost:3000/lp/<new-slug>/sitemap-xml | head -5
# Expected: valid XML
```

If any check fails: the most common causes are (a) `lp_content` was not inserted correctly into Supabase, or (b) a required field in the JSON is missing and the renderer throws.

### Phase 5 — Deploy to production

Follow [Section 5](#5-deploying-to-production-vercel) exactly. Git add only the files you changed (typically `lp-domains.ts` if a domain was added — the DB insert doesn't require a code deploy).

### Phase 6 — Production verification

```bash
curl -sI https://nippo-sync.vercel.app/lp/<new-slug>
# Expected: HTTP/2 200

curl -s https://nippo-sync.vercel.app/lp/<new-slug> | grep -i "<company-name>"
# Expected: match

# If custom domain:
curl -sI https://<custom-domain>/
# Expected: HTTP/2 200
```

### Phase 7 — Return URLs to Jayden

Once production is verified:
- Live LP URL: `https://nippo-sync.vercel.app/lp/<slug>` (or custom domain)
- Admin URL: `https://nippo-sync.vercel.app/lp/<slug>/admin`

---

## 8. Rollback and incident response

### Immediate rollback via Vercel (fastest option)

If a production deploy breaks LP rendering:

1. Go to: `https://vercel.com/team_InumbXmdUdRp3WpMs47TFd8s/nippo-sync/deployments`
2. Find the last deployment that had "Ready" status before the problem
3. Click `...` (three dots menu) on that deployment
4. Select **"Promote to Production"**
5. Wait ~10 seconds — production reverts without a git operation

This is the fastest recovery path. Vercel keeps deployment history indefinitely, so you can always roll back to any previous state.

### After rollback — fix properly

After rolling back:
1. Diagnose the issue in `template/` (the source of truth)
2. Fix the bug in `template/` first
3. Copy to nippo-sync
4. Run the full local test procedure (Section 4)
5. Push a new commit (do not amend the broken commit)

### Specific incident types

**LP page returns HTTP 500**

Causes and diagnosis:
- Supabase connection failed: check `POSTGRES_URL` env var in Vercel settings
- Unhandled exception in `lp-render.ts`: check Vercel function logs (Deployments → select deployment → Functions tab)
- Missing `lp_content` row: query `SELECT * FROM public.lp_content WHERE lp_id = (SELECT id FROM public.lps WHERE slug = '<slug>')` in Supabase

**LP renders wrong content (old data, missing section)**

The LP renderer is a pure function: it fetches `lp_content` from Supabase and renders HTML. "Same DB content = same HTML." So if the HTML is wrong:
- First check the DB: `SELECT data FROM public.lp_content WHERE lp_id = (SELECT id FROM public.lps WHERE slug = '<slug>')`
  - If the DB content is wrong → fix the DB, no code deploy needed
  - If the DB content is correct → the renderer has a bug → fix in `template/lib/lp-render.ts`, test locally, deploy

**og:title shows "日報シンクロくん" instead of client name**

This is the most common sign that the LP fetch failed silently and the renderer fell back to defaults. Check:
1. Is `POSTGRES_URL` set correctly in Vercel environment variables?
2. Does a row exist in `public.lps` for this slug?
3. Does a row exist in `public.lp_content` for this lp_id?
4. Are there any errors in the Vercel function log for this route?

**Custom domain returns 404 or wrong LP**

Check `lp-domains.ts` in nippo-sync and in `template/`:
- Is the domain listed? (`"brand.recruitly.jp": "slug"`)
- Is the slug correct?
- Did the change actually deploy? (check Vercel deployment status)
- Is the domain configured in Vercel's custom domain settings for the nippo-sync project?

**lp-domains.ts gets out of sync between template and nippo-sync**

This file is the most frequently edited LP file (every new client may need a custom domain). If you notice they differ:
```bash
diff /Users/jayden.csai/Developer/nippo-sync-local/src/lib/lp-domains.ts \
     /Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap/template/lib/lp-domains.ts
```
The nippo-sync version is what is deployed; the template is the reference. Whichever is newer (you can check git log for nippo-sync or just read both) should be copied to the other.

---

## 9. File-by-file reference

Brief notes on what each template file does and when you'd need to change it.

### `middleware.ts`

Controls custom domain routing. When a request comes in on a custom domain (e.g. `cloq.recruitly.jp`), middleware rewrites the URL to the corresponding `/lp/<slug>` path. It also handles any cross-cutting concerns like CORS headers for the LP routes.

**Change when**: adding a new routing rule, changing how custom domains are resolved, or adding global middleware for LP requests.

**Rarely changes**: the routing logic is stable. Most client customization is in the DB, not here.

### `lib/lp-render.ts`

The main HTML renderer. Takes an `LpContent` object from the database and returns a complete HTML string for the LP page. Contains all the SEO meta tags, Open Graph tags, JSON-LD structured data, and the job listing HTML.

**Change when**: adding new LP sections, fixing HTML/CSS, updating SEO schema, changing Open Graph behavior, adding new content fields to the rendered output.

**Most frequently changed** of all lib files.

### `lib/lp-content-types.ts`

TypeScript interface definitions for `LpContent` and related types (`LpJob`, `LpSection`, etc.). These types are used throughout all LP files.

**Change when**: adding a new field to the content model that will be stored in Supabase and rendered by `lp-render.ts`. Any new field added here must also be:
1. Added to the Supabase `lp_content` JSON schema (no migration needed — it's a JSONB column)
2. Handled in `lp-render.ts`
3. Editable in `LpContentEditor.tsx` (if it should be user-editable)

### `lib/lp-domains.ts`

Maps custom hostnames to LP slugs. Structure: `{ "hostname": "slug" }`.

**Change when**: a new client gets a custom domain, a domain changes, or a domain is removed.

**Both copies must always be identical**: `template/lib/lp-domains.ts` and `nippo-sync-local/src/lib/lp-domains.ts`. This is the most common source of template drift — update both at the same time.

### `lib/lp-admin-session.ts`

Handles admin session cookies. Reads and validates the admin session token stored in a cookie. Contains the session type definition and cookie helpers.

**Change when**: changing session duration, cookie security settings, or session token format.

### `lib/lp-description.ts`

Generates the meta description for LP pages. Typically uses content from `lp_content` to produce a short, SEO-friendly description.

**Change when**: changing how meta descriptions are generated or formatted.

### `lib/google-indexing.ts`

Calls the Google Indexing API to notify Google of new or updated LP URLs. Used after content changes to request fast re-indexing.

**Change when**: Google changes their Indexing API, or you want to add new URL types to the indexing notification.

### `lib/google-oauth.ts`

Handles the Google OAuth flow for admin login. Generates the OAuth redirect URL, exchanges the code for tokens, and validates the user's email against the allowed admin list for the LP.

**Change when**: changing OAuth scopes, adding new admin validation logic, or handling OAuth errors differently.

### `lib/pg.ts`

Postgres connection pool using the `postgres` npm package. All LP database queries go through this module.

**Change when**: changing connection pool settings, switching to a different Postgres client, or adding query logging.

### `lib/sheets.ts`

Google Sheets sync helpers. Reads from and writes to Google Sheets (used for syncing job application data to a client-provided spreadsheet).

**Change when**: changing the sync format, adding new columns, or fixing Sheets API error handling.

### `app/lp/[slug]/route.ts`

The main LP page route handler. Fetches `lp_content` from Supabase for the slug, calls `renderLp()`, and returns the HTML response with appropriate cache headers.

**Change when**: changing cache behavior, adding new response headers, or changing how the slug is resolved.

### `app/lp/[slug]/admin/` (page.tsx + 4 client components)

The admin dashboard UI. `page.tsx` is the React server component shell; the four `.tsx` files are client components rendered inside it.

**Change when**: adding new admin features, fixing UI bugs, changing the editor layout.

### `app/api/lp/[slug]/admin/content/route.ts`

GET and PATCH handler for LP content. GET returns the current `lp_content` JSON; PATCH accepts a partial update and merges it into the stored content.

**Change when**: adding new content fields, changing update validation, or fixing content merge logic.

### `app/api/lp/[slug]/track/route.ts`

Analytics event ingestion. Accepts POST with `{ event, path, ... }` and writes to the analytics table in Supabase.

**Change when**: adding new event fields, changing analytics storage format.

---

## 10. Quick-reference cheat sheet

Copy-paste commands for the most common operations.

### Environment variables

```bash
SKILL=/Users/jayden.csai/.claude/skills/mgc-saiyo-lp-bootstrap
NIPPO=/Users/jayden.csai/Developer/nippo-sync-local/src
```

### Copy a single file: template → nippo-sync

```bash
cp "$SKILL/template/lib/lp-render.ts" "$NIPPO/lib/lp-render.ts"
```

### Copy all lib files: template → nippo-sync

```bash
for f in lp-render lp-content-types lp-domains lp-admin-session lp-description \
          google-indexing google-oauth pg sheets; do
  cp "$SKILL/template/lib/${f}.ts" "$NIPPO/lib/${f}.ts"
done
cp "$SKILL/template/middleware.ts" "$NIPPO/middleware.ts"
```

### Sync a file back: nippo-sync → template

```bash
cp "$NIPPO/lib/lp-render.ts" "$SKILL/template/lib/lp-render.ts"
```

### Check for drift between template and nippo-sync

```bash
for f in middleware.ts lib/lp-render.ts lib/lp-content-types.ts lib/lp-domains.ts \
          lib/lp-admin-session.ts lib/lp-description.ts lib/google-indexing.ts \
          lib/google-oauth.ts lib/pg.ts lib/sheets.ts; do
  if ! diff -q "$NIPPO/$f" "$SKILL/template/$f" > /dev/null 2>&1; then
    echo "DRIFT: $f"
  fi
done
```

### Start dev server

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local && npm run dev
```

### Smoke test (localhost)

```bash
curl -s http://localhost:3000/lp/cloq | grep -i "cloq"
curl -s http://localhost:3000/lp/cloq | grep "og:title"
curl -s http://localhost:3000/lp/cloq/jobs/0 | grep "JobPosting"
curl -s http://localhost:3000/lp/cloq/sitemap-xml | head -3
curl -s http://localhost:3000/lp/cloq/robots.txt
curl -sI http://localhost:3000/lp/cloq/admin | grep "HTTP"
```

### TypeScript check

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local && npx tsc --noEmit
```

### Lint check

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local && npm run lint
```

### Commit and push

```bash
cd /Users/jayden.csai/Developer/nippo-sync-local
git add src/lib/lp-render.ts   # add only files you changed
git commit -m "feat(lp): <description>"
git push origin main
```

### Production smoke test

```bash
curl -sI https://nippo-sync.vercel.app/lp/cloq | grep "HTTP"
curl -s https://nippo-sync.vercel.app/lp/cloq | grep "CLOQ"
curl -s https://nippo-sync.vercel.app/lp/cloq | grep "og:title"
```

### Vercel deployments

```
https://vercel.com/team_InumbXmdUdRp3WpMs47TFd8s/nippo-sync/deployments
```
