#!/usr/bin/env python3
"""
compose_lpcontent.py — map ContentBundle + DesignTokens + preset → LpContent JSON.

This is the schema mapper for the saiyo-lp-bootstrap skill. It takes:
  - The output of crawl_reference.py (content scraped from the client site)
  - The output of extract_design.py (CSS-extracted theme)
  - Industry preset (welfare items, data pills, hero EN titles)
  - Client identity (slug + company name)

…and produces a valid LpContent JSON matching src/lib/lp-content-types.ts in
the nippo-sync repo. The output is ready to insert into public.lp_content.

Speed > polish: this fills every section so the LP renders cleanly on first
load. Quality is "good enough to demo" — Jayden polishes in the admin editor.

⚠️ AUDIENCE PIVOT LIMITATION
This script does naive paragraph copying for hero/about/strengths content. If
the source site is a B2B service business (consulting, agency, SaaS, etc.),
the homepage paragraphs are targeted at CLIENTS, not job seekers, and copying
them verbatim produces a 採用LP with the wrong 対象. The skill orchestrator
(Claude in the calling conversation) is responsible for reviewing the composed
hero / about / strengths sections and rewriting them with a job-seeker frame
BEFORE inserting the lp_content into Supabase. The provenance flag
`audience_pivot_review_needed: true` is set on every output as a reminder.

Usage:
    cat input.json | python3 compose_lpcontent.py

Input JSON shape (stdin):
    {
      "slug": "cloq",
      "client_name": "株式会社CLOQ",
      "primary_url": "https://cloq.jp/",
      "industry": "製造業",
      "content_bundle": { ...crawl_reference.py output... },
      "design_tokens": { ...extract_design.py output... },
      "preset": { ...row from public.industry_presets... }
    }

Output JSON: full LpContent on stdout.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────

DEFAULT_THEME = {
    "primary": "#1B2B5A",
    "accent": "#E85D3A",
    "accent2": "#f59e0b",
}

DEFAULT_HERO_EN = "Recruitment"
DEFAULT_HERO_JP = "つくる力で、未来を変えていく。"
DEFAULT_HERO_LABEL = "Recruiting 2026"

COMPANY_FORM_PREFIXES = (
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "社団法人", "財団法人", "一般社団法人", "公益社団法人",
    "NPO法人", "学校法人", "医療法人",
)


def log(msg: str) -> None:
    print(f"[compose] {msg}", file=sys.stderr, flush=True)


# ─── Helpers ──────────────────────────────────────────────────────────────

def strip_company_form(name: str) -> str:
    """Remove 株式会社 etc. prefix/suffix from a company name."""
    s = name.strip()
    for p in COMPANY_FORM_PREFIXES:
        if s.startswith(p):
            s = s[len(p):].strip()
            break
        if s.endswith(p):
            s = s[: -len(p)].strip()
            break
    return s


def derive_logo_letter(company_name: str) -> str:
    """Pick a single character for the logo box."""
    stripped = strip_company_form(company_name)
    # Prefer first English letter if any
    m = re.search(r"[A-Za-z]", stripped)
    if m:
        return m.group(0).upper()
    # Otherwise first non-space character
    if stripped:
        return stripped[0]
    return company_name[0] if company_name else "M"


def split_into_sentences(text: str) -> list[str]:
    """Split Japanese text by full-width period or English period."""
    if not text:
        return []
    # Split on 。 ! ？ . but keep the punctuation attached to the preceding sentence
    parts = re.split(r"(?<=[。．！？\.\!])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def truncate(s: str, max_chars: int, suffix: str = "…") -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - len(suffix)].rstrip() + suffix


def dl_lookup(pairs: list[dict], keywords: list[str]) -> str | None:
    """Find a dl pair whose term contains any of the given keywords.

    Used to pull specific values out of bundle.company_info or
    bundle.job_details (the structured <dl> data extracted from
    会社概要 / 募集要項 sections by crawl_reference.py).
    """
    if not pairs:
        return None
    for p in pairs:
        term = p.get("term", "")
        if any(kw in term for kw in keywords):
            return p.get("description")
    return None


def dl_to_welfare_items(job_details: list[dict]) -> list[dict]:
    """Convert relevant 募集要項 dl pairs into welfare display items.

    Maps the standard 募集要項 keys to (term, description) pairs that
    fit the welfare section's schema. Skips operational keys like
    勤務地 / 業務内容 / 求める人物像 that belong elsewhere.
    """
    if not job_details:
        return []
    welfare_keywords = (
        "給与", "賞与", "昇給", "手当",
        "勤務時間", "残業",
        "休日", "休暇", "有給",
        "保険", "福利厚生", "待遇", "制度", "退職金",
    )
    skip_keywords = ("業務内容", "勤務地", "求める", "応募", "選考", "問い合わせ")
    out: list[dict] = []
    seen_terms: set[str] = set()
    for p in job_details:
        term = (p.get("term") or "").strip()
        if not term or term in seen_terms:
            continue
        if any(s in term for s in skip_keywords):
            continue
        if not any(k in term for k in welfare_keywords):
            continue
        seen_terms.add(term)
        out.append({"term": term, "description": p.get("description", "")})
    return out


def dl_to_requirements(job_details: list[dict]) -> list[dict]:
    """Convert all 募集要項 dl pairs into the JobDetail.requirements shape.

    Unlike dl_to_welfare_items, this keeps everything (業務内容, 勤務地,
    求める人物像, etc.) so the dedicated /lp/{slug}/jobs/{n} detail page
    has the complete 募集要項 table.
    """
    if not job_details:
        return []
    skip = ("お問い合わせ",)
    out: list[dict] = []
    for p in job_details:
        term = (p.get("term") or "").strip()
        if not term:
            continue
        if any(s in term for s in skip):
            continue
        out.append({"term": term, "description": p.get("description", "")})
    return out


def first_image(bundle: dict, exclude_urls: set[str] | None = None) -> str:
    """Return the URL of the first image in the bundle's image_pool, optionally skipping some."""
    exclude_urls = exclude_urls or set()
    for img in bundle.get("image_pool", []):
        url = img.get("url", "")
        if url and url not in exclude_urls:
            return url
    return ""


def pick_image(bundle: dict, index: int) -> str:
    """Return the Nth image in image_pool (0-indexed), or empty string."""
    pool = bundle.get("image_pool", [])
    if 0 <= index < len(pool):
        return pool[index].get("url", "")
    return ""


def looks_like_real_job(title: str) -> bool:
    """Filter out generic noise that the crawler might pick as a job title."""
    if not title:
        return False
    if len(title) < 2 or len(title) > 30:
        return False
    noise = ("募集要項", "募集中", "詳細", "応募", "エントリー", "Recruit",
             "RECRUIT", "Career", "About", "MORE", "VIEW", "もっと")
    return not any(n in title for n in noise)


# ─── Section composers ────────────────────────────────────────────────────

def compose_meta(bundle: dict, company_name: str) -> dict:
    description_source = (
        bundle.get("representative_message")
        or (bundle.get("business_descriptions") or [""])[0]
        or (bundle.get("paragraph_pool") or [""])[0]
        or company_name
    )
    description = truncate(description_source, 160)
    return {
        "title": f"採用情報｜{company_name}",
        "description": description,
    }


def compose_header(bundle: dict, company_name: str) -> dict:
    """Header: company name + logo_letter fallback + optional logo_image.

    If the crawler extracted a real logo image from the source site
    (via extract_logo() — WordPress custom-logo class, brand link
    patterns, header <img> alt match, or favicon fallback), include it
    as header.logo_image. The renderer prefers logo_image over the
    letter fallback, rendering the actual company logo in the header.
    """
    header = {
        "company_name": company_name,
        "logo_letter": derive_logo_letter(company_name),
    }
    logo_url = bundle.get("logo_url")
    if logo_url:
        header["logo_image"] = logo_url
    return header


def compose_hero(bundle: dict, design_tokens: dict, preset: dict, company_name: str) -> dict:
    # EN title from preset (manufacturing has Manufacturing/Craftsmanship/Future/Innovation)
    en_titles = (preset or {}).get("hero_en_titles") or []
    en_title = en_titles[0] if en_titles else DEFAULT_HERO_EN

    # JP tagline: try to find a short punchy paragraph (< 40 chars)
    paragraphs = bundle.get("paragraph_pool") or []
    jp_tagline = DEFAULT_HERO_JP
    for p in paragraphs[:5]:
        if 10 <= len(p) <= 40 and "。" not in p[:-1]:  # single sentence, short
            jp_tagline = p
            break

    # Subtext: a longer descriptive paragraph (60-200 chars)
    subtext = ""
    for p in paragraphs:
        if 60 <= len(p) <= 200:
            subtext = p
            break
    if not subtext and paragraphs:
        subtext = truncate(paragraphs[0], 180)
    if not subtext:
        subtext = f"{company_name}の採用情報をご覧いただきありがとうございます。"

    # Background image: og_image > first scraped image
    bg_image = (
        (design_tokens or {}).get("og_image")
        or first_image(bundle)
        or ""
    )

    return {
        "label": DEFAULT_HERO_LABEL,
        "en_title": en_title,
        "jp_tagline": jp_tagline,
        "subtext": subtext,
        "bg_image": bg_image,
        "cta_label": "採用職種を見る",
        "cta_anchor": "#openings",
    }


def compose_about(bundle: dict, company_name: str, exclude_images: set[str]) -> dict:
    sub = f"{strip_company_form(company_name) or company_name}を知る"

    rep = bundle.get("representative_message") or ""
    biz = bundle.get("business_descriptions") or []
    paragraphs_pool = bundle.get("paragraph_pool") or []

    # Headline: first sentence of rep message, or short business description
    headline_source = rep or (biz[0] if biz else "")
    if headline_source:
        sentences = split_into_sentences(headline_source)
        headline = truncate(sentences[0] if sentences else headline_source, 50)
    else:
        headline = f"{company_name}の想い"

    # Paragraphs: 2-3 chunks of rep message + business description
    paragraphs: list[str] = []
    if rep:
        # Split rep into 2 chunks of ~150 chars each
        sentences = split_into_sentences(rep)
        chunk = ""
        for s in sentences:
            if len(chunk) + len(s) > 200:
                if chunk:
                    paragraphs.append(chunk.strip())
                chunk = s
            else:
                chunk += s
            if len(paragraphs) >= 2:
                break
        if chunk and len(paragraphs) < 3:
            paragraphs.append(chunk.strip())
    if not paragraphs and biz:
        paragraphs.append(truncate(biz[0], 250))
    if not paragraphs and paragraphs_pool:
        paragraphs.append(truncate(paragraphs_pool[0], 250))
    if not paragraphs:
        paragraphs = [f"{company_name}は、お客様のために最善を尽くす企業です。"]

    return {
        "sub": sub,
        "photo": pick_image(bundle, 1) or pick_image(bundle, 0),
        "headline": headline,
        "paragraphs": paragraphs[:3],
        "button_label": "私たちの強み",
        "button_anchor": "#strengths",
    }


def compose_strengths(bundle: dict) -> dict:
    """Pick 3 strength items from paragraph_pool."""
    paragraphs = bundle.get("paragraph_pool") or []
    items: list[dict] = []

    # Skip the first 1-2 paragraphs (often used in hero/about) and pick the next 3
    candidates = paragraphs[1:8] if len(paragraphs) > 1 else paragraphs
    for p in candidates:
        if len(items) >= 3:
            break
        if len(p) < 40:
            continue
        sentences = split_into_sentences(p)
        if not sentences:
            continue
        title = truncate(sentences[0], 30)
        body = " ".join(sentences[1:]) if len(sentences) > 1 else p
        body = truncate(body, 200)
        items.append({"title": title, "body": body})

    # Pad with generic placeholders if we couldn't find 3
    placeholders = [
        {"title": "確かな技術力", "body": "長年培ってきた技術と経験で、お客様の期待を超える品質をお届けします。"},
        {"title": "誠実な対応", "body": "一つひとつの仕事に真摯に向き合い、信頼関係を大切にしています。"},
        {"title": "未来への挑戦", "body": "現状に満足せず、常に新しい可能性を追求し続けています。"},
    ]
    while len(items) < 3:
        items.append(placeholders[len(items)])

    return {"sub": "選ばれ続ける3つの理由", "items": items}


def compose_data(preset: dict, company_name: str) -> dict:
    items = (preset or {}).get("data_pills") or [
        {"value": 30, "unit": "年", "label": "創業年数"},
        {"value": 100, "unit": "名", "label": "社員数"},
        {"value": 90, "unit": "%", "label": "有給取得率"},
        {"value": 120, "unit": "日", "label": "年間休日"},
        {"value": 35, "unit": "歳", "label": "平均年齢"},
    ]
    return {
        "sub": f"数字で見る{strip_company_form(company_name) or company_name}",
        "items": items,
    }


def compose_voices(bundle: dict) -> dict:
    """v0: 1 placeholder voice. Real photos come from a follow-up image step."""
    photo = pick_image(bundle, 2) or pick_image(bundle, 0)
    return {
        "sub": "先輩たちのリアルな声",
        "items": [
            {
                "photo": photo,
                "dept": "Manufacturing",
                "name": "佐藤 太郎",
                "meta": "2020年入社 / 製造部",
                "quote": "毎日新しい発見があり、自分の成長を実感できる職場です。チームみんなで助け合いながら、お客様に最高の製品をお届けしています。",
            },
        ],
    }


def compose_openings(bundle: dict, company_name: str) -> dict:
    """Build openings.items, preferring the structured 募集要項 dl when present.

    Three sources, in priority order:
      1. bundle.job_details — full 募集要項 from /recruit/ as a single rich
         item with detail.requirements populated. THIS IS THE GOOD PATH.
      2. bundle.existing_jobs — heading-based scrape (often noisy on
         consultancy / service-business sites). Filtered through
         looks_like_real_job().
      3. Single placeholder 総合職 so the LP isn't blank.
    """
    job_details = bundle.get("job_details") or []
    items: list[dict] = []

    # Path 1: structured 募集要項 dl
    if job_details:
        # Title comes from the 業務内容 / 職種 / ポジション field
        title = (
            dl_lookup(job_details, ["業務内容", "職種", "ポジション", "募集職種"])
            or "募集職種"
        )
        # Clean the title: 業務内容 is often a phrase like
        # "法人様の採用設計・採用支援スタッフ" — split on the separator and
        # take whichever part actually looks like a role name (ends in
        # スタッフ / 担当 / マネージャー / エンジニア / 職 / etc.). If neither
        # part looks role-like, take the LAST part as that's where job titles
        # usually live in JP descriptions ("X の Y 担当").
        ROLE_SUFFIXES = ("スタッフ", "担当", "マネージャー", "リーダー", "エンジニア",
                          "デザイナー", "オペレーター", "アシスタント", "ディレクター",
                          "プランナー", "コンサルタント", "職")
        for sep in ("／", "/", "・", "、"):
            if sep in title:
                parts = [p.strip() for p in title.split(sep) if p.strip()]
                # Prefer parts ending in a role suffix
                role_parts = [p for p in parts if any(p.endswith(s) for s in ROLE_SUFFIXES)]
                if role_parts:
                    title = role_parts[-1]
                else:
                    title = parts[-1]
                break
        title = truncate(title, 30, suffix="")
        # Employment type comes from 雇用形態
        badge = dl_lookup(job_details, ["雇用形態"]) or "正社員"
        if len(badge) > 10:
            badge = "正社員"
        # Card description: pitch the role using whatever extra context the
        # 募集要項 provided. Avoid duplicating the (now-cleaned) title.
        biz_desc = dl_lookup(job_details, ["業務内容"]) or ""
        if biz_desc and biz_desc != title:
            description = f"{biz_desc}。{company_name}で一緒に働く仲間を募集しています。"
        else:
            description = f"{company_name}で活躍する{title}を募集しています。詳細は募集要項をご覧ください。"
        description = truncate(description, 180)

        # Detail page: full 募集要項 table + 3 quick highlight points
        requirements = dl_to_requirements(job_details)
        points: list[dict] = []
        person_spec = dl_lookup(job_details, ["求める人物像", "求める人材"])
        if person_spec:
            # Split on standard list separators first, then fall back to
            # phrase-boundary words like 「方」 which JP recruit pages use to
            # delimit individual desired traits ("X な方  Y な方  Z な方").
            parts: list[str] = []
            for sep in ("／", "/", "、", "・"):
                if sep in person_spec:
                    parts = [p.strip() for p in person_spec.split(sep) if p.strip()]
                    break
            if not parts and "方" in person_spec:
                # Split after each 「方」 keeping the word
                import re as _re
                parts = [p.strip() for p in _re.split(r"(?<=方)\s+", person_spec) if p.strip()]
            if not parts:
                parts = [person_spec]
            points = [{"title": truncate(p, 40, suffix="")} for p in parts[:3]]

        items.append({
            "image": pick_image(bundle, 3) or pick_image(bundle, 0),
            "badge": badge,
            "title": title,
            "description": description,
            "detail": {
                "en_title": "RECRUITMENT",
                "tagline": dl_lookup(job_details, ["業務内容"]) or title,
                "intro": f"{company_name}で募集中のポジションです。詳細は以下の募集要項をご確認ください。",
                "hero_bg": pick_image(bundle, 3) or pick_image(bundle, 0),
                "points": points,
                "requirements": requirements,
            },
        })

    # Path 2: noisy heading-scrape fallback
    if not items:
        raw_jobs = bundle.get("existing_jobs") or []
        real_jobs = [j for j in raw_jobs if looks_like_real_job(j.get("title", ""))]
        for i, job in enumerate(real_jobs[:6]):
            items.append({
                "image": pick_image(bundle, 3 + i) or pick_image(bundle, 0),
                "badge": "正社員",
                "title": job["title"],
                "description": f"{company_name}で活躍する{job['title']}を募集しています。詳細はお問い合わせください。",
            })

    # Path 3: blank-LP fallback
    if not items:
        items.append({
            "image": pick_image(bundle, 3) or pick_image(bundle, 0),
            "badge": "正社員",
            "title": "総合職",
            "description": f"{company_name}で一緒に働く仲間を募集しています。詳細はお問い合わせください。",
        })

    return {"sub": "現在募集中のポジション", "items": items}


def compose_welfare(preset: dict, bundle: dict | None = None) -> dict:
    """Welfare prefers real scraped 募集要項 entries over preset defaults.

    The 募集要項 on a /recruit/ page usually contains the actual 給与 /
    休日 / 保険 / 福利厚生 values for the position — using those means
    the LP shows the company's REAL terms, not generic placeholders.
    """
    bundle = bundle or {}
    scraped = dl_to_welfare_items(bundle.get("job_details") or [])

    if scraped:
        # Real welfare data from the recruit page — use it as the primary source
        return {"sub": "待遇・福利厚生", "items": scraped}

    # Fall back to industry preset
    items = (preset or {}).get("welfare_items") or [
        {"term": "給与", "description": "経験・スキルに応じて優遇"},
        {"term": "賞与", "description": "年2回（6月・12月）"},
        {"term": "休日", "description": "完全週休2日制、年間休日120日以上"},
        {"term": "保険", "description": "社会保険完備"},
    ]
    return {"sub": "待遇・福利厚生", "items": items}


def compose_cta(company_name: str) -> dict:
    return {
        "headline": "あなたのチャレンジを待っています",
        "sub": f"{company_name}で、私たちと一緒に未来をつくりませんか？",
        "button_label": "エントリーする",
    }


def compose_footer(bundle: dict, company_name: str) -> dict:
    """Footer pulls structured fields from the 会社概要 dl when available,
    falling back to free-text business_descriptions for the business field."""
    address = bundle.get("address") or ""

    # Founded date — from 設立 / 創業 keys in 会社概要
    founded = bundle.get("founded") or ""

    # Representative — from 代表者 / 代表取締役 keys in 会社概要
    representative = bundle.get("representative") or ""

    # Business summary — prefer the structured 主な事業内容 dl value, fall
    # back to the first free-text business description, then truncate.
    business = bundle.get("business_type") or ""
    if not business:
        biz = bundle.get("business_descriptions") or []
        business = biz[0] if biz else ""
    business = truncate(business, 120)

    return {
        "company_name": company_name,
        "tagline": "",
        "address": address,
        "founded": founded,
        "representative": representative,
        "business": business,
    }


def compose_theme(design_tokens: dict) -> dict:
    colors = (design_tokens or {}).get("colors") or {}
    return {
        "primary": colors.get("primary") or DEFAULT_THEME["primary"],
        "accent": colors.get("accent") or DEFAULT_THEME["accent"],
        "accent2": colors.get("accent2") or DEFAULT_THEME["accent2"],
    }


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"_error": f"Invalid JSON on stdin: {e}"}))
        return 1

    slug = input_data.get("slug") or "untitled"
    client_name = input_data.get("client_name") or slug
    bundle = input_data.get("content_bundle") or {}
    design_tokens = input_data.get("design_tokens") or {}
    preset = input_data.get("preset") or {}

    log(f"Composing LpContent for slug={slug}, client={client_name}")
    log(f"  bundle: {len(bundle.get('paragraph_pool') or [])} paragraphs, "
        f"{len(bundle.get('image_pool') or [])} images, "
        f"{len(bundle.get('existing_jobs') or [])} raw jobs")

    # Track which images we've used so we don't repeat them
    used_images: set[str] = set()

    lp_content: dict[str, Any] = {
        "meta": compose_meta(bundle, client_name),
        "header": compose_header(bundle, client_name),
        "hero": compose_hero(bundle, design_tokens, preset, client_name),
        "about": compose_about(bundle, client_name, used_images),
        "strengths": compose_strengths(bundle),
        "data": compose_data(preset, client_name),
        "voices": compose_voices(bundle),
        "openings": compose_openings(bundle, client_name),
        "welfare": compose_welfare(preset, bundle),
        "cta": compose_cta(client_name),
        "map_embed_src": "",
        "footer": compose_footer(bundle, client_name),
        "theme": compose_theme(design_tokens),
    }

    # Provenance: track which fields came from where for the orchestrator's report
    has_company_dl = bool(bundle.get("company_info"))
    has_job_dl = bool(bundle.get("job_details"))
    provenance = {
        "company_name": "scraped" if bundle.get("company_name") else "fallback",
        "address": "scraped" if bundle.get("address") else "missing",
        "tel": "scraped" if bundle.get("tel") else "missing",
        "founded": "scraped_dl" if bundle.get("founded") else "missing",
        "representative": "scraped_dl" if bundle.get("representative") else "missing",
        "business_type": "scraped_dl" if bundle.get("business_type") else (
            "scraped_text" if bundle.get("business_descriptions") else "missing"
        ),
        "rep_message": "scraped" if bundle.get("representative_message") else "missing",
        "openings": (
            "scraped_dl_full" if has_job_dl
            else "scraped_headings" if bundle.get("existing_jobs")
            else "fallback_generic"
        ),
        "welfare": (
            "scraped_dl" if has_job_dl
            else "preset" if preset.get("welfare_items")
            else "default"
        ),
        "data": "preset" if preset.get("data_pills") else "default",
        "logo": (
            "scraped" if bundle.get("logo_url") else "fallback_letter"
        ),
        "theme_colors": (design_tokens or {}).get("source", "default"),
        "voices": "placeholder_v0",
        "map_embed_src": "empty_v0",
        "audience_pivot_review_needed": True,  # see note below
    }

    output = {
        "lp_content": lp_content,
        "provenance": provenance,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
