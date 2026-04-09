#!/usr/bin/env python3
"""
crawl_reference.py — multi-page content scraper for the saiyo-lp-bootstrap skill.

Given a corporate site URL, fetches the homepage + a curated set of likely
sub-pages (about, recruit, news, etc.) and extracts a `ContentBundle` JSON
containing everything the compose step needs.

Usage:
    python3 crawl_reference.py https://cloq.jp/ [--max-pages 8]

Outputs JSON to stdout. Logs to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

# ─── Constants ────────────────────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (compatible; mgc-saiyo-lp-bootstrap/1.0; "
    "+https://nippo-sync.vercel.app)"
)
TIMEOUT = 15
MAX_PAGES_DEFAULT = 8

# Sub-page link patterns to follow (case-insensitive substring match in href)
SUBPAGE_PATTERNS = [
    "/about", "/company", "/profile",
    "/recruit", "/saiyo", "/career", "/jobs",
    "/news", "/info", "/topics",
    "/business", "/service", "/services",
    "/message", "/greeting",
    "/access", "/contact", "/inquiry",
]

COMPANY_FORM_PREFIXES = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "社団法人", "財団法人")
COMPANY_FORM_SUFFIXES = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "社団法人", "財団法人")

POSTAL_RE = re.compile(r"〒?\s*\d{3}[-－]?\d{4}\s*[^\s\n、]+(?:[市区町村郡都道府県]\S*)+(?:\d+[-－]?\d*[-－]?\d*)?")
TEL_RE = re.compile(r"(?:TEL|tel|電話|Tel)[\s:：]*([0-9０-９\-－()（）\s]{8,18}\d)")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Image filtering
MIN_IMAGE_DIMENSION = 200  # px (assumes width/height attrs or natural size)
SKIP_IMAGE_PATTERNS = ("logo", "icon", "favicon", "spinner", "loader", "sprite", "btn-")


def log(msg: str) -> None:
    print(f"[crawl] {msg}", file=sys.stderr, flush=True)


# ─── Fetching ─────────────────────────────────────────────────────────────

def strip_noise(soup: BeautifulSoup) -> None:
    """Remove script, style, and other non-content tags in place."""
    for tag in soup.find_all(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()


def fetch(url: str) -> Optional[tuple[str, str]]:
    """Returns (final_url, html_text) or None on failure."""
    try:
        r = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.9"},
            allow_redirects=True,
        )
        if r.status_code != 200:
            log(f"  {url} → {r.status_code}")
            return None
        ct = r.headers.get("content-type", "")
        if "html" not in ct:
            log(f"  {url} → not html ({ct})")
            return None
        # Force utf-8 if the server didn't specify
        if r.encoding is None or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return (r.url, r.text)
    except Exception as e:
        log(f"  {url} → error: {e}")
        return None


def discover_subpages(homepage_url: str, html: str) -> list[str]:
    """Find internal links matching SUBPAGE_PATTERNS, deduped + capped."""
    soup = BeautifulSoup(html, "html.parser")
    base = urllib.parse.urlparse(homepage_url)
    base_origin = f"{base.scheme}://{base.netloc}"

    found: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        # Resolve to absolute URL
        absolute = urllib.parse.urljoin(homepage_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.netloc != base.netloc:
            continue  # external link
        path_lower = parsed.path.lower()
        # Match against subpage patterns
        if not any(p in path_lower for p in SUBPAGE_PATTERNS):
            continue
        # Strip query strings + fragments for dedup
        canonical = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        if canonical in seen or canonical == homepage_url.rstrip("/"):
            continue
        seen.add(canonical)
        found.append(canonical)

    return found


# ─── Extraction helpers ───────────────────────────────────────────────────

def extract_company_name(soup: BeautifulSoup, fallback: str) -> str:
    # Try og:site_name first
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()
    # Try meta application-name
    am = soup.find("meta", attrs={"name": "application-name"})
    if am and am.get("content"):
        return am["content"].strip()
    # Try <title>, strip common suffixes
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # Strip "｜...", "| ...", "- ..." suffixes
        for sep in ("｜", "|", "-", "–", "—"):
            if sep in title:
                # Take the part that contains a company-form word, or the longest
                parts = [p.strip() for p in title.split(sep) if p.strip()]
                company_parts = [p for p in parts if any(f in p for f in COMPANY_FORM_PREFIXES)]
                if company_parts:
                    return company_parts[0]
                # Otherwise the longest non-trivial chunk
                if parts:
                    return max(parts, key=len)
        return title
    return fallback


def extract_address(text: str) -> Optional[str]:
    m = POSTAL_RE.search(text)
    if m:
        return m.group(0).strip()
    return None


def extract_tel(text: str) -> Optional[str]:
    m = TEL_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def extract_email(text: str) -> Optional[str]:
    # Skip obvious noise like wordpress @example
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0)
        if "example" in addr or "domain.com" in addr:
            continue
        return addr
    return None


def collect_paragraphs(soup: BeautifulSoup, min_chars: int = 30) -> list[str]:
    """All <p> text content above a minimum length, in document order."""
    out: list[str] = []
    for p in soup.find_all(["p", "div"]):
        # Avoid divs that contain other block elements (we'd dup their text)
        if p.name == "div" and p.find(["p", "div", "ul", "ol", "table"]):
            continue
        text = p.get_text(separator=" ", strip=True)
        if len(text) >= min_chars and text not in out:
            out.append(text)
    return out


def collect_images(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Collect candidate images: src + alt + width/height + context."""
    out: list[dict] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        absolute = urllib.parse.urljoin(page_url, src)
        if absolute in seen:
            continue
        seen.add(absolute)
        src_lower = absolute.lower()
        if any(p in src_lower for p in SKIP_IMAGE_PATTERNS):
            continue
        # Try to get a width hint
        try:
            width = int(img.get("width") or 0)
        except (ValueError, TypeError):
            width = 0
        try:
            height = int(img.get("height") or 0)
        except (ValueError, TypeError):
            height = 0
        # Skip tiny declared sizes
        if width and width < MIN_IMAGE_DIMENSION:
            continue
        out.append({
            "url": absolute,
            "alt": (img.get("alt") or "").strip(),
            "width": width or None,
            "height": height or None,
            "page": page_url,
        })
    return out


def extract_section_by_keywords(soup: BeautifulSoup, keywords: list[str]) -> Optional[str]:
    """Find a heading containing any keyword, return the text of the next siblings."""
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = tag.get_text(strip=True)
        if not heading_text:
            continue
        if any(kw in heading_text for kw in keywords):
            # Collect text from following siblings until the next heading
            collected: list[str] = []
            for sib in tag.find_next_siblings():
                if sib.name in ("h1", "h2", "h3", "h4"):
                    break
                text = sib.get_text(separator=" ", strip=True)
                if text:
                    collected.append(text)
                if len(" ".join(collected)) > 1500:
                    break
            if collected:
                return " ".join(collected)[:2000]
    return None


def extract_news_items(soup: BeautifulSoup) -> list[dict]:
    """Find news/info list items with date + title."""
    out: list[dict] = []
    date_re = re.compile(r"(20\d{2})[年./\-](\d{1,2})[月./\-](\d{1,2})")
    # Look for anchors that contain a date pattern
    for a in soup.find_all("a", href=True):
        text = a.get_text(separator=" ", strip=True)
        if not text or len(text) < 10:
            continue
        m = date_re.search(text)
        if not m:
            continue
        date_str = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
        title = date_re.sub("", text).strip(" 　-・|｜").strip()
        if not title or len(title) > 200:
            continue
        out.append({"date": date_str, "title": title, "url": a["href"]})
        if len(out) >= 10:
            break
    return out


def is_recruit_page(url: str) -> bool:
    return any(p in url.lower() for p in ("/recruit", "/saiyo", "/career", "/jobs"))


def is_message_page(url: str) -> bool:
    return any(p in url.lower() for p in ("/message", "/greeting"))


def is_business_page(url: str) -> bool:
    return any(p in url.lower() for p in ("/business", "/service"))



def collect_dl_pairs(soup: BeautifulSoup) -> list[dict]:
    """Extract <dl><dt>key</dt><dd>value</dd></dl> structures.

    Japanese corporate sites overwhelmingly use definition lists for
    会社概要 (company info) and 募集要項 (job requirements). Returns a flat
    list of {term, description} dicts. Multiple <dd>s per <dt> get joined
    with " / " — common for things like 福利厚生 lists.

    Walks dt/dd in document order regardless of intermediate wrapper
    elements (e.g. cloq.jp wraps each pair in a <div>, so direct children
    iteration would miss everything).
    """
    out: list[dict] = []
    for dl in soup.find_all("dl"):
        elements = dl.find_all(["dt", "dd"])
        i = 0
        while i < len(elements):
            if elements[i].name == "dt":
                term = elements[i].get_text(separator=" ", strip=True)
                values: list[str] = []
                j = i + 1
                while j < len(elements) and elements[j].name == "dd":
                    v = elements[j].get_text(separator=" ", strip=True)
                    if v:
                        values.append(v)
                    j += 1
                if term and values:
                    out.append({
                        "term": term,
                        "description": " / ".join(values),
                    })
                i = j
            else:
                i += 1
    return out


def find_dl_value(pairs: list[dict], keywords: list[str]) -> Optional[str]:
    """Find a dl term containing any keyword and return its description."""
    for p in pairs:
        if any(kw in p["term"] for kw in keywords):
            return p["description"]
    return None


# ─── Main ─────────────────────────────────────────────────────────────────

def extract_logo(soup: BeautifulSoup, page_url: str, company_name: str | None = None) -> Optional[str]:
    """Extract the most likely company logo URL from a homepage.

    Strategies in priority order (works on WordPress, custom sites, etc.):
      1. <img class="custom-logo">      — WordPress theme standard
      2. <a class="*logo*"> <img>       — common brand-link pattern
      3. <img class="*logo*">           — generic logo class
      4. <img alt="{company_name}"> in <header>
      5. <img src contains "logo">
      6. <link rel="icon" sizes="192x192">  — largest favicon as fallback
      7. <link rel="apple-touch-icon">      — final fallback

    Returns the ABSOLUTE URL of the logo, or None if nothing matched.
    Favicon fallbacks are only returned if no <img> logo was found,
    and are flagged in the caller's metadata as a fallback source.
    """
    def absolute(src: str) -> str:
        if not src:
            return ""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return urllib.parse.urljoin(page_url, src)
        if src.startswith(("http://", "https://")):
            return src
        return urllib.parse.urljoin(page_url, src)

    # Strategy 1: WordPress custom-logo class
    img = soup.find("img", class_="custom-logo")
    if img and img.get("src"):
        return absolute(img["src"])

    # Strategy 2: <a class="*logo*"> <img>
    for a in soup.find_all("a"):
        cls = " ".join(a.get("class") or []).lower()
        if "logo" in cls or "brand" in cls or "site-title" in cls:
            img = a.find("img")
            if img and img.get("src"):
                return absolute(img["src"])

    # Strategy 3: generic logo class on <img>
    for img in soup.find_all("img"):
        cls = " ".join(img.get("class") or []).lower()
        if "logo" in cls and "icon" not in cls:
            if img.get("src"):
                return absolute(img["src"])

    # Strategy 4: alt text matches company name, inside <header>
    if company_name:
        hdr = soup.find("header")
        if hdr:
            for img in hdr.find_all("img"):
                alt = (img.get("alt") or "").strip()
                # Match on either exact or substring (株式会社 prefix/suffix tolerance)
                if alt and (alt == company_name or alt in company_name or company_name in alt):
                    if img.get("src"):
                        return absolute(img["src"])

    # Strategy 5: src contains "logo" (outside the general image pool filter)
    for img in soup.find_all("img"):
        src = (img.get("src") or "").lower()
        # Avoid favicon/cropped/thumbnail variants
        if "logo" in src and not any(x in src for x in ("favicon", "cropped-", "-32x32", "-16x16")):
            return absolute(img["src"])

    # Strategy 6/7: Favicon fallbacks (ordered by size preference)
    favicon_candidates: list[tuple[int, str]] = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        if not rel:
            continue
        rel_str = " ".join(rel).lower()
        if "icon" in rel_str:
            href = link.get("href")
            if not href:
                continue
            sizes = link.get("sizes", "")
            try:
                size = int(sizes.split("x")[0]) if "x" in sizes else 0
            except ValueError:
                size = 0
            # apple-touch-icon is usually 180px
            if "apple-touch" in rel_str and size == 0:
                size = 180
            favicon_candidates.append((size, absolute(href)))

    if favicon_candidates:
        favicon_candidates.sort(reverse=True)
        return favicon_candidates[0][1]

    return None


def extract_favicon(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    """Extract the site favicon separately from the logo. Returns the
    highest-resolution icon URL available, or None."""
    def absolute(src: str) -> str:
        if not src:
            return ""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return urllib.parse.urljoin(page_url, src)
        if src.startswith(("http://", "https://")):
            return src
        return urllib.parse.urljoin(page_url, src)

    candidates: list[tuple[int, str]] = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        rel_str = " ".join(rel).lower()
        if "icon" not in rel_str:
            continue
        href = link.get("href")
        if not href:
            continue
        sizes = link.get("sizes", "")
        try:
            size = int(sizes.split("x")[0]) if "x" in sizes else 0
        except ValueError:
            size = 0
        if "apple-touch" in rel_str and size == 0:
            size = 180
        candidates.append((size, absolute(href)))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-page reference scraper.")
    parser.add_argument("url", help="Homepage URL to crawl.")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_DEFAULT)
    args = parser.parse_args()

    homepage_url = args.url.rstrip("/")
    log(f"Crawling {homepage_url}")

    home = fetch(homepage_url)
    if not home:
        print(json.dumps({"_error": f"Could not fetch homepage: {homepage_url}"}))
        return 1

    home_url, home_html = home
    home_soup = BeautifulSoup(home_html, "html.parser")
    strip_noise(home_soup)

    # Discover sub-pages
    subpages = discover_subpages(home_url, home_html)[: args.max_pages]
    log(f"Discovered {len(subpages)} sub-pages: {[urllib.parse.urlparse(s).path for s in subpages]}")

    # Fetch sub-pages in parallel
    pages: list[tuple[str, BeautifulSoup, str]] = [(home_url, home_soup, home_html)]
    if subpages:
        with ThreadPoolExecutor(max_workers=4) as ex:
            future_to_url = {ex.submit(fetch, url): url for url in subpages}
            for fut in as_completed(future_to_url):
                result = fut.result()
                if result:
                    final_url, html = result
                    sub_soup = BeautifulSoup(html, "html.parser")
                    strip_noise(sub_soup)
                    pages.append((final_url, sub_soup, html))

    log(f"Successfully fetched {len(pages)} page(s)")

    # All-page text pool
    all_text = "\n".join(soup.get_text(separator=" ", strip=True) for _, soup, _ in pages)

    # Build the content bundle
    # Collect <dl> pairs from each page, tagged by page type for downstream use
    dl_company_info: list[dict] = []   # 会社概要 from /about/
    dl_job_details: list[dict] = []    # 募集要項 from /recruit/
    dl_other: list[dict] = []
    for url, soup, _ in pages:
        pairs = collect_dl_pairs(soup)
        if not pairs:
            continue
        if "/about" in url.lower() or "/company" in url.lower() or "/profile" in url.lower():
            dl_company_info.extend(pairs)
        elif is_recruit_page(url):
            dl_job_details.extend(pairs)
        else:
            dl_other.extend(pairs)

    bundle: dict = {
        "source_url": home_url,
        "pages_fetched": [u for u, _, _ in pages],
        "company_name": extract_company_name(home_soup, fallback=urllib.parse.urlparse(home_url).netloc),
        "address": extract_address(all_text),
        "tel": extract_tel(all_text),
        "email": extract_email(all_text),
        "representative_message": None,
        "business_descriptions": [],
        "existing_jobs": [],
        "existing_news": extract_news_items(home_soup),
        "paragraph_pool": [],
        "image_pool": [],
        # New structured fields from <dl> extraction
        "company_info": dl_company_info,   # all 会社概要 dl pairs
        "job_details": dl_job_details,     # all 募集要項 dl pairs
        "other_dl_pairs": dl_other,
        # Convenience extracted fields
        "founded": find_dl_value(dl_company_info, ["設立", "創業"]),
        "representative": find_dl_value(dl_company_info, ["代表者", "代表取締役"]),
        "capital": find_dl_value(dl_company_info, ["資本金"]),
        "business_type": find_dl_value(dl_company_info, ["事業内容", "業務内容", "主な事業"]),
        # Visual identity — logo and favicon extracted from homepage <img> + <link>
        "logo_url": extract_logo(home_soup, home_url, None),  # filled with company_name below
        "favicon_url": extract_favicon(home_soup, home_url),
    }
    # Re-run logo extraction with company_name hint (strategy 4 uses alt-text matching)
    if not bundle["logo_url"]:
        bundle["logo_url"] = extract_logo(home_soup, home_url, bundle["company_name"])

    # Extract representative message — prefer dedicated /message page, fall back to home
    for url, soup, _ in pages:
        if is_message_page(url):
            paras = collect_paragraphs(soup, min_chars=80)
            if paras:
                bundle["representative_message"] = " ".join(paras[:5])[:2500]
                break
    if not bundle["representative_message"]:
        msg = extract_section_by_keywords(home_soup, ["代表", "メッセージ", "挨拶", "Message", "MESSAGE"])
        if msg:
            bundle["representative_message"] = msg[:2500]

    # Extract business descriptions — prefer dedicated /business page
    business_paras: list[str] = []
    for url, soup, _ in pages:
        if is_business_page(url):
            business_paras.extend(collect_paragraphs(soup, min_chars=60)[:6])
    if not business_paras:
        biz = extract_section_by_keywords(home_soup, ["事業", "サービス", "Business", "BUSINESS", "Service"])
        if biz:
            business_paras = [biz]
    bundle["business_descriptions"] = business_paras[:6]

    # Extract existing jobs (if /recruit page exists)
    for url, soup, _ in pages:
        if is_recruit_page(url):
            # Look for headings that look like job titles
            for tag in soup.find_all(["h2", "h3", "h4"]):
                text = tag.get_text(strip=True)
                if 3 <= len(text) <= 30 and not any(c in text for c in "。、？！"):
                    bundle["existing_jobs"].append({
                        "title": text,
                        "page": url,
                    })
                    if len(bundle["existing_jobs"]) >= 10:
                        break
            if bundle["existing_jobs"]:
                break

    # Paragraph pool — all unique paragraphs from all pages
    all_paras: list[str] = []
    seen_paras: set[str] = set()
    for _, soup, _ in pages:
        for p in collect_paragraphs(soup, min_chars=40):
            if p not in seen_paras and len(all_paras) < 50:
                seen_paras.add(p)
                all_paras.append(p)
    bundle["paragraph_pool"] = all_paras

    # Image pool — all candidate images from all pages
    all_images: list[dict] = []
    for url, soup, _ in pages:
        all_images.extend(collect_images(soup, url))
    bundle["image_pool"] = all_images[:30]

    log(
        f"Bundle: company={bundle['company_name']!r}, "
        f"address={'yes' if bundle['address'] else 'no'}, "
        f"tel={'yes' if bundle['tel'] else 'no'}, "
        f"logo={'yes' if bundle['logo_url'] else 'no'}, "
        f"founded={bundle['founded']!r}, "
        f"representative={bundle['representative']!r}, "
        f"company_info_pairs={len(bundle['company_info'])}, "
        f"job_detail_pairs={len(bundle['job_details'])}, "
        f"message={'yes' if bundle['representative_message'] else 'no'}, "
        f"business_paras={len(bundle['business_descriptions'])}, "
        f"jobs={len(bundle['existing_jobs'])}, "
        f"news={len(bundle['existing_news'])}, "
        f"paragraphs={len(bundle['paragraph_pool'])}, "
        f"images={len(bundle['image_pool'])}"
    )

    print(json.dumps(bundle, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
