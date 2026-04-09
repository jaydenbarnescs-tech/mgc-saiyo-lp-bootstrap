#!/usr/bin/env python3
"""
extract_design.py — CSS-based design token extractor.

Fetches a webpage, parses all inline + external CSS, and extracts:
  - Top 3 brand colors (primary / accent / accent2) by frequency
  - Primary font family
  - Favicon URL
  - Open Graph image URL

This is the CSS fallback for the saiyo-lp-bootstrap skill. The skill orchestrator
also tries Aura.build's extraction in parallel (which produces a richer DESIGN.md
when it works), but falls back to this script when Aura times out or errors.

Usage:
    python3 extract_design.py https://cloq.jp/

Outputs JSON to stdout. Logs to stderr.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; mgc-saiyo-lp-bootstrap/1.0; "
    "+https://nippo-sync.vercel.app)"
)
TIMEOUT = 15
MAX_CSS_FILES = 5  # cap external stylesheets to fetch

# ─── Patterns ─────────────────────────────────────────────────────────────

HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)")
HSL_RE = re.compile(r"hsla?\(\s*(\d+)\s*,\s*(\d+)%\s*,\s*(\d+)%\s*(?:,\s*([\d.]+)\s*)?\)")
FONT_RE = re.compile(r"font-family\s*:\s*([^;}\n]+)")

# Properties that indicate brand colors (used for weighted scoring)
BRAND_PROPS = {
    "background": 3,
    "background-color": 3,
    "border-color": 2,
    "border": 1,
    "color": 1,
    "fill": 2,
    "stroke": 2,
    "--primary": 5, "--accent": 5, "--brand": 5,  # CSS custom properties
    "--c1": 5, "--c2": 5, "--c3": 5,
}


def log(msg: str) -> None:
    print(f"[design] {msg}", file=sys.stderr, flush=True)


# ─── Color utilities ──────────────────────────────────────────────────────

def normalize_hex(hex_str: str) -> Optional[str]:
    """Normalize a hex string (3, 4, 6, or 8 chars) to #rrggbb."""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    elif len(h) == 4:
        h = "".join(c * 2 for c in h[:3])  # drop alpha
    elif len(h) == 8:
        h = h[:6]  # drop alpha
    elif len(h) != 6:
        return None
    try:
        int(h, 16)
        return "#" + h.lower()
    except ValueError:
        return None


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def hsl_to_hex(h: int, s: int, l: int) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))


def hex_to_hsl(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    h_, l_, s_ = colorsys.rgb_to_hls(r, g, b)
    return (h_ * 360, s_ * 100, l_ * 100)


# WordPress core ships these as default palette swatches in every theme.
# They appear in CSS even when unused — filter them out so they don't get
# picked as brand colors.
WP_DEFAULT_PALETTE = {
    "#abb8c3", "#8ed1fc", "#0693e3", "#00d084", "#7bdcb5",
    "#fcb900", "#ff6900", "#f78da7", "#eb144c", "#cf2e2e",
    "#9b51e0",
}


def is_brand_worthy(hex_color: str) -> bool:
    """Filter out white, near-black, greys, low-saturation, and known defaults."""
    if hex_color in WP_DEFAULT_PALETTE:
        return False
    h, s, l = hex_to_hsl(hex_color)
    # Lightness extremes (near-white)
    if l > 95:
        return False
    # Low saturation = grey (but allow very dark colors as primary)
    if s < 18 and l > 85:
        return False
    if s < 5 and l > 20:
        return False
    return True


def color_distance(a: str, b: str) -> float:
    """Rough perceptual distance between two hex colors. Higher = more different."""
    ha, sa, la = hex_to_hsl(a)
    hb, sb, lb = hex_to_hsl(b)
    # Hue distance is circular
    dh = min(abs(ha - hb), 360 - abs(ha - hb))
    return dh + abs(sa - sb) * 0.6 + abs(la - lb) * 0.6


def darkness(hex_color: str) -> float:
    _, _, l = hex_to_hsl(hex_color)
    return 100 - l  # darker = higher


# ─── CSS parsing ──────────────────────────────────────────────────────────

def extract_colors_from_css(css: str) -> Counter:
    """Returns a Counter of {hex_color: weight} based on usage context."""
    counts: Counter = Counter()

    # Walk the CSS roughly: split into rules and look at property:value pairs
    # We don't need a full CSS parser — frequency-weighted regex is enough.
    for match in re.finditer(r"([a-zA-Z-]+)\s*:\s*([^;}\n]+)", css):
        prop = match.group(1).lower()
        value = match.group(2)
        weight = BRAND_PROPS.get(prop, 1) if prop in BRAND_PROPS else 0
        if weight == 0:
            # Still count if it looks like a CSS variable definition
            if prop.startswith("--"):
                weight = 2
            else:
                continue

        # Hex
        for hm in HEX_RE.finditer(value):
            h = normalize_hex(hm.group(0))
            if h:
                counts[h] += weight

        # RGB / RGBA
        for rm in RGB_RE.finditer(value):
            try:
                hex_color = rgb_to_hex(int(rm.group(1)), int(rm.group(2)), int(rm.group(3)))
                counts[hex_color] += weight
            except ValueError:
                pass

        # HSL / HSLA
        for hm in HSL_RE.finditer(value):
            try:
                hex_color = hsl_to_hex(int(hm.group(1)), int(hm.group(2)), int(hm.group(3)))
                counts[hex_color] += weight
            except ValueError:
                pass

    return counts


def pick_brand_colors(counts: Counter) -> tuple[str, str, str]:
    """Choose primary / accent / accent2 from a color frequency counter."""
    # Filter to brand-worthy colors
    candidates = [(c, n) for c, n in counts.most_common() if is_brand_worthy(c)]

    if not candidates:
        return ("#1B2B5A", "#E85D3A", "#f59e0b")  # yamaguchi defaults

    # Primary = the highest-weight dark-ish color
    dark_candidates = [(c, n) for c, n in candidates if hex_to_hsl(c)[2] < 50]
    primary = (dark_candidates[0][0] if dark_candidates else candidates[0][0])

    # Accent = the highest-weight color that's distant from primary, prefer warm/saturated
    accent = None
    for c, _ in candidates:
        if c == primary:
            continue
        if color_distance(c, primary) > 60:
            h, s, _ = hex_to_hsl(c)
            if s > 25:  # saturated enough to be an accent
                accent = c
                break
    if not accent:
        accent = candidates[1][0] if len(candidates) > 1 else "#E85D3A"

    # Accent2 = next distant from BOTH primary and accent
    accent2 = None
    for c, _ in candidates:
        if c in (primary, accent):
            continue
        if color_distance(c, primary) > 40 and color_distance(c, accent) > 40:
            accent2 = c
            break
    if not accent2:
        accent2 = "#f59e0b"

    return (primary, accent, accent2)


ICON_FONT_KEYWORDS = (
    "fontawesome", "font awesome", "fa-",
    "material icons", "materialicons", "material symbols", "materialsymbols",
    "ionicons", "feather", "dashicons", "fontello", "icomoon",
    "glyphicon", "octicons", "iconmoon", "elegant icons",
)


def extract_primary_font(css: str) -> Optional[str]:
    """Find the most common font-family declaration, excluding icon fonts."""
    families: Counter = Counter()
    for match in FONT_RE.finditer(css):
        # Take the first font in the stack (the preferred one)
        first = match.group(1).split(",")[0].strip().strip('"').strip("'")
        if not first or first.startswith("var(") or first.startswith("inherit"):
            continue
        # Normalize: lowercase + strip spaces so "FontAwesome" matches "fontawesome"
        first_lower = first.lower()
        first_stripped = first_lower.replace(" ", "")
        if any(kw.replace(" ", "") in first_stripped for kw in ICON_FONT_KEYWORDS):
            continue
        families[first] += 1
    if not families:
        return None
    return families.most_common(1)[0][0]


# ─── Fetching ─────────────────────────────────────────────────────────────

def fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        if r.encoding is None or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        log(f"  fetch error {url}: {e}")
        return None


def collect_all_css(homepage_url: str, html: str) -> str:
    """Inline <style> tags + external <link rel=stylesheet> from same origin."""
    soup = BeautifulSoup(html, "html.parser")

    css_chunks: list[str] = []

    # Inline <style>
    for style in soup.find_all("style"):
        if style.string:
            css_chunks.append(style.string)

    # External stylesheets — only same-origin (CDN fonts are noise)
    base = urllib.parse.urlparse(homepage_url)
    base_origin = f"{base.scheme}://{base.netloc}"
    external_urls: list[str] = []
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel") or []
        if "stylesheet" not in rels:
            continue
        href = link.get("href")
        if not href:
            continue
        absolute = urllib.parse.urljoin(homepage_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.netloc == base.netloc:
            external_urls.append(absolute)
        if len(external_urls) >= MAX_CSS_FILES:
            break

    if external_urls:
        log(f"  fetching {len(external_urls)} external stylesheet(s)")
        with ThreadPoolExecutor(max_workers=4) as ex:
            for fut in as_completed({ex.submit(fetch, u): u for u in external_urls}):
                css = fut.result()
                if css:
                    css_chunks.append(css)

    return "\n".join(css_chunks)


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="CSS-based design token extractor.")
    parser.add_argument("url", help="Homepage URL to extract from.")
    args = parser.parse_args()

    url = args.url
    log(f"Extracting design from {url}")

    html = fetch(url)
    if not html:
        print(json.dumps({"_error": f"Could not fetch {url}"}))
        return 1

    soup = BeautifulSoup(html, "html.parser")

    # Collect all CSS
    css = collect_all_css(url, html)
    log(f"  collected {len(css)} bytes of CSS")

    # Extract colors
    counts = extract_colors_from_css(css)
    primary, accent, accent2 = pick_brand_colors(counts)
    log(f"  brand colors: primary={primary} accent={accent} accent2={accent2}")

    # Extract primary font
    primary_font = extract_primary_font(css)
    log(f"  primary font: {primary_font}")

    # Favicon
    favicon = None
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel") or []
        if any(r.lower() in ("icon", "shortcut icon", "apple-touch-icon") for r in rels):
            href = link.get("href")
            if href:
                favicon = urllib.parse.urljoin(url, href)
                break

    # Open Graph image
    og_image = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        og_image = urllib.parse.urljoin(url, og["content"])

    # Logo (heuristic: <img> in header with "logo" in src or class or alt)
    logo_url = None
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = (img.get("alt") or "").lower()
        cls = " ".join(img.get("class") or []).lower()
        if "logo" in src.lower() or "logo" in alt or "logo" in cls:
            logo_url = urllib.parse.urljoin(url, src)
            break

    output = {
        "source_url": url,
        "colors": {
            "primary": primary,
            "accent": accent,
            "accent2": accent2,
        },
        "color_frequencies": dict(counts.most_common(10)),
        "primary_font": primary_font,
        "favicon": favicon,
        "og_image": og_image,
        "logo_url": logo_url,
        "source": "css_fallback",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
