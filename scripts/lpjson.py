#!/usr/bin/env python3
"""CLI/server helper for recruitment LP bootstrap manifests."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from lp_manifest_schema import (
    INSTAGRAM_RE,
    KIND,
    dump_json_file,
    load_json_file,
    normalize_legacy_bootstrap,
    validate_manifest,
)

USER_AGENT = "Mozilla/5.0 (compatible; mgc-saiyo-lp-bootstrap/1.0; +https://nippo-sync.vercel.app)"
DEFAULT_BASE_URL = "https://nippo-sync.vercel.app"


ALIASES = {
    "slug": "slug",
    "client": "client_name",
    "instagram": "lp_content.header.social_links.instagram",
    "map.region": "lp_content.map.region",
    "map.locality": "lp_content.map.locality",
    "map.street": "lp_content.map.street",
    "map.postal_code": "lp_content.map.postal_code",
    "company.overview": "company_profile.overview_ja",
    "image_style": "image_generation.global_style_prompt",
}


class ImgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.images: list[dict[str, Any]] = []
        self.links: list[dict[str, str]] = []
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "img":
            src = attrs_dict.get("src") or attrs_dict.get("data-src") or attrs_dict.get("data-original") or ""
            if src:
                self.images.append({
                    "src": src,
                    "alt": attrs_dict.get("alt", ""),
                    "width": attrs_dict.get("width", ""),
                    "height": attrs_dict.get("height", ""),
                    "srcset": attrs_dict.get("srcset", ""),
                })
        if tag.lower() == "link":
            self.links.append(attrs_dict)
        if tag.lower() == "meta":
            self.meta.append(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()


def parse_path(path: str) -> list[str | int]:
    path = ALIASES.get(path, path)
    path = re.sub(r"^job\[(\d+)\]\.", r"lp_content.openings.items[\1].", path)
    out: list[str | int] = []
    for part in path.split("."):
        if not part:
            continue
        if part.isdigit():
            out.append(int(part))
            continue
        pos = 0
        m = re.match(r"^[A-Za-z0-9_-]+", part)
        if not m:
            raise ValueError(f"invalid path segment: {part}")
        out.append(m.group(0))
        pos = len(m.group(0))
        while pos < len(part):
            m = re.match(r"\[(\d+)\]", part[pos:])
            if not m:
                raise ValueError(f"invalid path segment: {part}")
            out.append(int(m.group(1)))
            pos += len(m.group(0))
    return out


def get_path(data: Any, path: str) -> Any:
    cur = data
    for part in parse_path(path):
        if isinstance(part, int):
            cur = cur[part]
        else:
            cur = cur[part]
    return cur


def set_path(data: Any, path: str, value: Any, *, create: bool = False) -> bool:
    parts = parse_path(path)
    cur = data
    for i, part in enumerate(parts[:-1]):
        next_part = parts[i + 1]
        if isinstance(part, int):
            if not isinstance(cur, list):
                raise TypeError(f"expected list at {'.'.join(map(str, parts[:i])) or '<root>'}")
            if create:
                while len(cur) <= part:
                    cur.append([] if isinstance(next_part, int) else {})
            cur = cur[part]
        else:
            if not isinstance(cur, dict):
                raise TypeError(f"expected object at {'.'.join(map(str, parts[:i])) or '<root>'}")
            if part not in cur:
                if not create:
                    raise KeyError(f"path does not exist: {path}")
                cur[part] = [] if isinstance(next_part, int) else {}
            cur = cur[part]
    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(cur, list):
            raise TypeError(f"expected list at {'.'.join(map(str, parts[:-1])) or '<root>'}")
        if create:
            while len(cur) <= last:
                cur.append(None)
        old = cur[last]
        cur[last] = value
    else:
        if not isinstance(cur, dict):
            raise TypeError(f"expected object at {'.'.join(map(str, parts[:-1])) or '<root>'}")
        if last not in cur and not create:
            raise KeyError(f"path does not exist: {path}")
        old = cur.get(last)
        cur[last] = value
    return old != value


def atomic_write(path: str, data: Any, *, backup: bool = True) -> str | None:
    target = Path(path)
    backup_path = None
    if backup and target.exists():
        backup_path = f"{path}.bak"
        shutil.copy2(path, backup_path)
    fd, temp_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent or Path(".")))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return backup_path


def load_value(raw: str, as_json: bool) -> Any:
    if as_json:
        return json.loads(raw)
    return raw


def validate_command(args: argparse.Namespace) -> int:
    try:
        data = load_json_file(args.file)
    except (FileNotFoundError, JSONDecodeError) as e:
        print(json.dumps({"ok": False, "errors": [{"path": args.file, "message": str(e)}]}, ensure_ascii=False, indent=2))
        return 2
    result = validate_manifest(data, strict=args.strict, for_apply=args.for_apply, allow_unreviewed=args.allow_unreviewed)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_validation(result))
    if result["errors"]:
        return 1
    if args.strict and result["warnings"]:
        return 3
    return 0


def format_validation(result: dict[str, Any]) -> str:
    lines = ["OK" if result.get("ok") else "FAILED"]
    if result.get("errors"):
        lines.append("\nErrors:")
        lines.extend(f"- {i['path']}: {i['message']}" for i in result["errors"])
    if result.get("warnings"):
        lines.append("\nWarnings:")
        lines.extend(f"- {i['path']}: {i['message']}" for i in result["warnings"])
    return "\n".join(lines)


def http_json(url: str, *, method: str = "GET", body: Any | None = None, secret: str | None = None) -> Any:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if secret:
        headers["x-migration-secret"] = secret
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except JSONDecodeError:
            parsed = {"error": raw}
        parsed["_http_status"] = e.code
        return parsed


def secret_from_args(args: argparse.Namespace) -> str:
    secret = args.secret or os.environ.get("MIGRATION_RUNNER_SECRET")
    if not secret:
        raise RuntimeError("MIGRATION_RUNNER_SECRET is required")
    return secret


def fetch_html(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        final_url = resp.geturl()
        charset = resp.headers.get_content_charset() or "utf-8"
        return final_url, resp.read().decode(charset, "replace")


def absolute_url(base: str, url: str) -> str:
    return urllib.parse.urljoin(base, url)


def image_id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:03d}"


def looks_like_logo(url: str, alt: str = "") -> bool:
    text = f"{url} {alt}".lower()
    return any(word in text for word in ("logo", "favicon", "apple-touch-icon", "ロゴ", "icon", "insta", "instagram"))


def guess_business_line(manifest: dict[str, Any], text: str) -> str:
    text_l = text.lower()
    for line in manifest.get("company_profile", {}).get("business_lines", []) or []:
        line_id = str(line.get("id") or "")
        label = str(line.get("label") or "")
        terms = [line_id, label] + [str(x) for x in line.get("services_or_products", []) or []] + [str(x) for x in line.get("visual_needs", []) or []]
        if any(t and t.lower() in text_l for t in terms):
            return line_id
    if any(t in text for t in ("工場", "加工", "機械", "部品", "製造")):
        return "metal_processing"
    if any(t in text for t in ("居酒屋", "料理", "キッチン", "ホール", "飲食")):
        return "izakaya"
    return ""


def download_image(url: str, out_dir: Path, name: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        ext = ".img"
    local = out_dir / f"{name}{ext}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read()
        mime = resp.headers.get("content-type", "")
    local.write_bytes(payload)
    return {
        "local_path": str(local),
        "mime_type": mime,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def collect_official_images(manifest: dict[str, Any], out_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = manifest.get("source", {})
    urls = []
    for key in ("primary_url", "recruit_url", "style_url"):
        value = source.get(key)
        if value and value not in urls:
            urls.append(value)
    images: list[dict[str, Any]] = []
    logos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_url in urls:
        try:
            final_url, html = fetch_html(page_url)
        except Exception as e:
            manifest.setdefault("notes", []).append(f"media official fetch failed: {page_url}: {e}")
            continue
        parser = ImgParser()
        parser.feed(html)
        page_title = parser.title
        candidates = []
        for img in parser.images:
            src = img.get("src", "")
            if not src:
                continue
            candidates.append((absolute_url(final_url, src), img.get("alt", ""), img.get("width"), img.get("height")))
            srcset = img.get("srcset") or ""
            if srcset:
                first = srcset.split(",")[0].strip().split(" ")[0]
                if first:
                    candidates.append((absolute_url(final_url, first), img.get("alt", ""), img.get("width"), img.get("height")))
        for meta in parser.meta:
            prop = meta.get("property") or meta.get("name")
            content = meta.get("content")
            if prop in {"og:image", "twitter:image"} and content:
                candidates.append((absolute_url(final_url, content), prop, "", ""))
        for link in parser.links:
            rel = link.get("rel", "")
            href = link.get("href")
            if href and any(token in rel for token in ("icon", "apple-touch-icon")):
                candidates.append((absolute_url(final_url, href), rel, "", ""))
        for url, alt, width, height in candidates:
            if url in seen or not re.search(r"\.(png|jpe?g|webp|gif)(?:[?#].*)?$", url, re.I):
                continue
            seen.add(url)
            prefix = "logo" if looks_like_logo(url, alt) else "official"
            item_id = image_id(prefix, len(logos if prefix == "logo" else images) + 1)
            record = {
                "id": item_id,
                "source_type": "official_site",
                "url": url,
                "local_path": "",
                "source_page_url": final_url,
                "source_domain": urllib.parse.urlparse(final_url).netloc,
                "mime_type": "",
                "width": int(width) if str(width).isdigit() else None,
                "height": int(height) if str(height).isdigit() else None,
                "sha256": "",
                "extracted_context": {"alt": alt, "nearby_text": "", "page_title": page_title},
                "same_company_confidence": "high",
                "rights_status": "client_owned_assumed",
                "approved_for_reference": prefix != "logo",
                "approved_for_direct_use": False,
                "ai_analysis": {
                    "subject": "",
                    "people_count": 0,
                    "setting": "",
                    "business_line": "",
                    "visible_uniforms": "",
                    "visible_products_or_equipment": "",
                    "recommended_lp_use": [],
                    "risks": [],
                    "prompt_notes": "",
                    "method": "pending",
                },
            }
            try:
                record.update(download_image(url, out_dir, item_id))
            except Exception as e:
                record["download_error"] = str(e)
            if prefix == "logo":
                logos.append(record)
            else:
                images.append(record)
    return images, logos


def google_image_candidates(query: str, limit: int) -> list[dict[str, str]]:
    search = "https://www.google.com/search?tbm=isch&q=" + urllib.parse.quote(query)
    try:
        _, html = fetch_html(search)
    except Exception:
        return []
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    patterns = [
        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
        r'\["(https?://[^"]+\.(?:jpg|jpeg|png|webp))",\d+,\d+\]',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.I):
            url = match.group(1).replace("\\u003d", "=").replace("\\u0026", "&")
            if url in seen:
                continue
            seen.add(url)
            candidates.append({"url": url, "source_page_url": search, "title": query})
            if len(candidates) >= limit:
                return candidates
    return candidates


def collect_web_images(manifest: dict[str, Any], out_dir: Path, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    client_name = manifest.get("client_name", "")
    domains = []
    for key in ("primary_url", "recruit_url"):
        value = manifest.get("source", {}).get(key)
        if value:
            domains.append(urllib.parse.urlparse(value).netloc.replace("www.", ""))
    queries = [client_name, f"{client_name} Instagram", f"{client_name} 採用"]
    results: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        for cand in google_image_candidates(query, limit):
            if cand["url"] in seen:
                continue
            seen.add(cand["url"])
            source_domain = urllib.parse.urlparse(cand["url"]).netloc
            confidence = "medium"
            if any(d and d in source_domain for d in domains):
                confidence = "high"
            record = {
                "id": image_id("web", len(results) + len(rejected) + 1),
                "source_type": "web_image_search",
                "url": cand["url"],
                "local_path": "",
                "source_page_url": cand.get("source_page_url", ""),
                "source_domain": source_domain,
                "mime_type": "",
                "width": None,
                "height": None,
                "sha256": "",
                "extracted_context": {"alt": "", "nearby_text": query, "page_title": cand.get("title", "")},
                "same_company_confidence": confidence,
                "rights_status": "unknown_web",
                "approved_for_reference": confidence == "high",
                "approved_for_direct_use": False,
                "ai_analysis": {"subject": "", "people_count": 0, "setting": "", "business_line": "", "visible_uniforms": "", "visible_products_or_equipment": "", "recommended_lp_use": [], "risks": ["web result requires human verification"], "prompt_notes": "", "method": "pending"},
            }
            try:
                record.update(download_image(cand["url"], out_dir, record["id"]))
            except Exception as e:
                record["download_error"] = str(e)
            if confidence == "high":
                results.append(record)
            else:
                rejected.append(record)
            if len(results) >= limit:
                return results, rejected
    return results[:limit], rejected


def analyze_images(manifest: dict[str, Any], *, refresh_applicability: bool = False) -> dict[str, Any]:
    media = manifest.setdefault("media_research", {})
    images = media.setdefault("source_images", [])
    for img in images:
        context = " ".join([
            str(img.get("url", "")),
            str(img.get("extracted_context", {}).get("alt", "")),
            str(img.get("extracted_context", {}).get("nearby_text", "")),
            str(img.get("extracted_context", {}).get("page_title", "")),
        ])
        business_line = guess_business_line(manifest, context)
        risks = list(img.get("ai_analysis", {}).get("risks") or [])
        if img.get("source_type") == "web_image_search":
            risks.append("verify same-company match before use")
        if looks_like_logo(img.get("url", ""), img.get("extracted_context", {}).get("alt", "")):
            risks.append("logo/icon asset; do not use as hero")
        subject = "official workplace/reference image"
        if any(t in context for t in ("logo", "ロゴ")):
            subject = "company logo or icon"
        elif any(t in context for t in ("工場", "加工", "機械", "部品", "製造")):
            subject = "metal processing workplace or manufacturing-related image"
        elif any(t in context for t in ("居酒屋", "料理", "キッチン", "ホール", "飲食", "enguchi")):
            subject = "restaurant or izakaya-related image"
        analysis = img.setdefault("ai_analysis", {})
        analysis.update({
            "subject": analysis.get("subject") or subject,
            "people_count": analysis.get("people_count") or 0,
            "setting": analysis.get("setting") or ("workplace" if business_line else ""),
            "business_line": analysis.get("business_line") or business_line,
            "visible_uniforms": analysis.get("visible_uniforms") or "",
            "visible_products_or_equipment": analysis.get("visible_products_or_equipment") or "",
            "recommended_lp_use": analysis.get("recommended_lp_use") or recommended_uses(subject, business_line),
            "risks": sorted(set(risks)),
            "prompt_notes": analysis.get("prompt_notes") or context[:240],
            "method": "metadata_heuristic",
        })
        if refresh_applicability or "applicability" not in img:
            img["applicability"] = infer_image_applicability(manifest, img)
    return manifest


def company_entity_for_business_line(manifest: dict[str, Any], business_line: str) -> dict[str, str]:
    profile = manifest.get("company_profile", {})
    for line in profile.get("business_lines", []) if isinstance(profile, dict) else []:
        if isinstance(line, dict) and line.get("id") == business_line:
            return {
                "entity_id": str(line.get("entity_id") or business_line or manifest.get("slug") or "client"),
                "entity_name": str(line.get("entity_name") or line.get("label") or manifest.get("client_name") or ""),
                "company_scope": str(line.get("company_scope") or "client_company"),
            }
    return {
        "entity_id": str(manifest.get("slug") or "client"),
        "entity_name": str(manifest.get("client_name") or ""),
        "company_scope": "client_company",
    }


def business_line_for_opening(title: str) -> str:
    if any(t in title for t in ("居酒屋", "キッチン", "ホール", "調理", "飲食")):
        return "izakaya"
    if any(t in title for t in ("金属", "加工", "機械", "梱包", "出荷", "製造", "工場")):
        return "metal_processing"
    return ""


def role_tags_for_title(title: str) -> list[str]:
    tags: list[str] = []
    is_packing = any(t in title for t in ("梱包", "出荷", "検品", "仕分け"))
    if any(t in title for t in ("機械", "オペレーター")) or ("加工" in title and not is_packing):
        tags.append("machine_operator")
    if is_packing:
        tags.append("packing_shipping")
    if any(t in title for t in ("キッチン", "調理", "仕込み")):
        tags.append("kitchen")
    if any(t in title for t in ("ホール", "接客", "配膳")):
        tags.append("hall")
    return tags or ["general"]


def role_fit_for_image(opening_title: str, context: str) -> str:
    tags = role_tags_for_title(opening_title)
    context_lower = context.lower()
    if "machine_operator" in tags and any(t in context for t in ("機械", "加工", "machine", "mazak", "operator")):
        return "primary"
    if "packing_shipping" in tags and any(t in context for t in ("梱包", "出荷", "検品", "仕分け", "forklift", "parts")):
        return "primary"
    if "kitchen" in tags and any(t in context for t in ("キッチン", "調理", "仕込み", "料理", "kitchen", "food")):
        return "primary"
    if "hall" in tags and any(t in context for t in ("ホール", "接客", "counter", "seating", "service", "storefront")):
        return "primary"
    if any(t in context_lower for t in ("logo", "icon", "instagram")):
        return "not_applicable"
    return "supporting"


def infer_image_applicability(manifest: dict[str, Any], img: dict[str, Any]) -> dict[str, Any]:
    analysis = img.get("ai_analysis", {}) if isinstance(img.get("ai_analysis"), dict) else {}
    business_line = str(analysis.get("business_line") or "")
    subject = str(analysis.get("subject") or "")
    context = " ".join([
        subject,
        str(analysis.get("prompt_notes") or ""),
        str(analysis.get("visible_products_or_equipment") or ""),
        str(img.get("url") or ""),
        str(img.get("extracted_context", {}).get("alt", "") if isinstance(img.get("extracted_context"), dict) else ""),
    ])

    if looks_like_logo(str(img.get("url") or ""), str(img.get("extracted_context", {}).get("alt", "") if isinstance(img.get("extracted_context"), dict) else "")):
        return {
            "company_scope": "brand_or_social_asset",
            "entity_id": str(manifest.get("slug") or "client"),
            "entity_name": str(manifest.get("client_name") or ""),
            "business_line": "brand_asset",
            "applicable_opening_indexes": [],
            "applicable_opening_titles": [],
            "job_role_fit": [],
            "confidence": img.get("same_company_confidence") or "unknown",
            "needs_human_review": False,
            "not_applicable_reason": "UI/logo/social icon asset; do not use as a job or hero reference.",
            "evidence": ["Source URL or alt text indicates a logo/icon/social asset."],
        }

    entity = company_entity_for_business_line(manifest, business_line)
    openings = manifest.get("lp_content", {}).get("openings", {}).get("items", []) or []
    applicable_indexes: list[int] = []
    job_role_fit: list[dict[str, str | int]] = []
    for idx, opening in enumerate(openings):
        if not isinstance(opening, dict):
            continue
        title = str(opening.get("title") or "")
        if business_line and business_line_for_opening(title) != business_line:
            continue
        fit = role_fit_for_image(title, context)
        if fit == "not_applicable":
            continue
        applicable_indexes.append(idx)
        job_role_fit.append({
            "opening_index": idx,
            "opening_title": title,
            "fit": fit,
            "role_tags": ", ".join(role_tags_for_title(title)),
            "reason": "Matched by business line and visual/job-role cues.",
        })

    applicable_titles = [
        str(openings[i].get("title") or "")
        for i in applicable_indexes
        if isinstance(openings[i], dict)
    ]
    return {
        **entity,
        "business_line": business_line or "unknown",
        "applicable_opening_indexes": applicable_indexes,
        "applicable_opening_titles": applicable_titles,
        "job_role_fit": job_role_fit,
        "confidence": img.get("same_company_confidence") or "unknown",
        "needs_human_review": not bool(business_line and applicable_indexes and img.get("same_company_confidence") == "high"),
        "evidence": [
            f"source_domain={img.get('source_domain', '')}",
            f"source_page_url={img.get('source_page_url', '')}",
            f"subject={subject}",
        ],
    }


def recommended_uses(subject: str, business_line: str) -> list[str]:
    if "logo" in subject:
        return ["header.logo_image", "favicon_url"]
    if business_line == "metal_processing":
        return ["hero reference", "metal processing job cards", "factory/workplace style reference"]
    if business_line == "izakaya":
        return ["restaurant job cards", "kitchen/hall style reference"]
    return ["general visual reference"]


def plan_generations(manifest: dict[str, Any]) -> dict[str, Any]:
    image_generation = manifest.setdefault("image_generation", {})
    global_style = image_generation.get("global_style_prompt") or "Japanese recruitment landing page, warm approachable tone, realistic workplace photography."
    source_images = manifest.get("media_research", {}).get("source_images", [])
    approved_ids = [img.get("id") for img in source_images if img.get("approved_for_reference")]
    existing = {job.get("target_section") for job in image_generation.get("jobs", []) if isinstance(job, dict)}
    jobs = image_generation.setdefault("jobs", [])
    def target_metadata(target: str, business_line: str) -> dict[str, Any]:
        entity = company_entity_for_business_line(manifest, business_line)
        meta: dict[str, Any] = {
            "target_entity_id": entity.get("entity_id"),
            "target_entity_name": entity.get("entity_name"),
        }
        m = re.search(r"lp_content\.openings\.items\[(\d+)\]", target)
        if m:
            idx = int(m.group(1))
            openings = manifest.get("lp_content", {}).get("openings", {}).get("items", []) or []
            title = ""
            if idx < len(openings) and isinstance(openings[idx], dict):
                title = str(openings[idx].get("title") or "")
            meta.update({
                "target_opening_index": idx,
                "target_opening_title": title,
                "target_role_tags": role_tags_for_title(title),
            })
        return meta

    def add_job(job_id: str, target: str, business_line: str, prompt: str) -> None:
        if target in existing:
            return
        refs = [img.get("id") for img in source_images if img.get("approved_for_reference") and img.get("ai_analysis", {}).get("business_line") == business_line]
        if not refs:
            refs = approved_ids[:3]
        jobs.append({
            "id": job_id,
            "target_section": target,
            "target_business_line": business_line,
            "source_image_ids": refs[:4],
            "prompt": f"{global_style} {prompt}",
            "negative_prompt": "unrelated company logos, unsafe work, wrong uniforms, watermark, text overlay, generic stock photo, luxury branding",
            "size": "16:9",
            "status": "planned",
            "uses_identifiable_people": False,
            "permission_status": "not_applicable_fictional_people",
            **target_metadata(target, business_line),
        })
    add_job("gen-hero-001", "lp_content.hero.bg_image", "metal_processing", "Realistic Japanese metal processing workplace, clean machines, careful operator posture, approachable recruiting mood.")
    for i, opening in enumerate(manifest.get("lp_content", {}).get("openings", {}).get("items", []) or []):
        title = opening.get("title", "")
        line = "izakaya" if any(t in title for t in ("居酒屋", "キッチン", "ホール")) else "metal_processing"
        add_job(f"gen-opening-{i+1:03d}", f"lp_content.openings.items[{i}].image", line, f"Recruiting image for {title}, consistent uniforms and workplace context, natural candid scene.")
    for job in jobs:
        if not isinstance(job, dict):
            continue
        line = str(job.get("target_business_line") or "")
        target = str(job.get("target_section") or "")
        for key, value in target_metadata(target, line).items():
            job.setdefault(key, value)
    return manifest


def media_collect(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    out_dir = Path(args.out_dir or f"media/{data.get('slug', 'lp')}")
    media = data.setdefault("media_research", {})
    current_images = {img.get("url"): img for img in media.setdefault("source_images", []) if isinstance(img, dict)}
    current_logos = {img.get("url"): img for img in media.setdefault("logos", []) if isinstance(img, dict)}
    rejected = media.setdefault("rejected_images", [])
    if args.official:
        images, logos = collect_official_images(data, out_dir)
        for img in images:
            current_images[img["url"]] = img
        for logo in logos:
            current_logos[logo["url"]] = logo
    if args.web:
        limit = args.limit or media.get("collection_policy", {}).get("web_image_limit", 10) or 10
        images, reject = collect_web_images(data, out_dir, int(limit))
        for img in images:
            current_images[img["url"]] = img
        rejected.extend(reject)
    media["source_images"] = list(current_images.values())
    media["logos"] = list(current_logos.values())
    atomic_write(args.file, data, backup=not args.no_backup)
    print(json.dumps({"ok": True, "source_images": len(media["source_images"]), "logos": len(media["logos"]), "rejected": len(rejected)}, ensure_ascii=False, indent=2))
    return 0


def media_analyze(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    analyze_images(data, refresh_applicability=args.refresh_applicability)
    if args.write:
        atomic_write(args.file, data, backup=not args.no_backup)
    print(json.dumps({"ok": True, "analyzed": len(data.get("media_research", {}).get("source_images", []))}, ensure_ascii=False, indent=2))
    return 0


def media_list(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    images = data.get("media_research", {}).get("source_images", [])
    if args.approved:
        images = [img for img in images if img.get("approved_for_reference")]
    if args.summary:
        images = [
            {
                "id": img.get("id"),
                "url": img.get("url"),
                "subject": img.get("ai_analysis", {}).get("subject"),
                "business_line": img.get("applicability", {}).get("business_line") or img.get("ai_analysis", {}).get("business_line"),
                "entity_name": img.get("applicability", {}).get("entity_name"),
                "applicable_opening_titles": img.get("applicability", {}).get("applicable_opening_titles", []),
                "confidence": img.get("applicability", {}).get("confidence") or img.get("same_company_confidence"),
                "needs_human_review": img.get("applicability", {}).get("needs_human_review"),
            }
            for img in images
        ]
    print(json.dumps(images, ensure_ascii=False, indent=2))
    return 0


def media_approve(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    found = False
    for img in data.get("media_research", {}).get("source_images", []):
        if img.get("id") == args.image_id:
            if args.reference:
                img["approved_for_reference"] = True
            if args.direct_use:
                img["approved_for_direct_use"] = True
            found = True
            break
    if not found:
        raise SystemExit(f"image not found: {args.image_id}")
    atomic_write(args.file, data, backup=not args.no_backup)
    print(json.dumps({"ok": True, "image_id": args.image_id}, ensure_ascii=False, indent=2))
    return 0


def media_plan_generations(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    plan_generations(data)
    if args.write:
        atomic_write(args.file, data, backup=not args.no_backup)
    print(json.dumps({"ok": True, "jobs": len(data.get("image_generation", {}).get("jobs", []))}, ensure_ascii=False, indent=2))
    return 0


def media_attach_generated(args: argparse.Namespace) -> int:
    data = load_json_file(args.file)
    job = next((j for j in data.get("image_generation", {}).get("jobs", []) if j.get("id") == args.job_id), None)
    if not job:
        raise SystemExit(f"generation job not found: {args.job_id}")
    asset_id = args.asset_id or f"asset-{args.job_id.replace('gen-', '')}"
    asset = {
        "id": asset_id,
        "generation_job_id": args.job_id,
        "local_path": args.asset_path,
        "target_section": job["target_section"],
        "prompt_used": job.get("prompt", ""),
        "reference_image_ids": job.get("source_image_ids", []),
        "review_status": args.review_status,
    }
    data.setdefault("image_generation", {}).setdefault("generated_assets", []).append(asset)
    set_path(data, job["target_section"], args.asset_path, create=True)
    atomic_write(args.file, data, backup=not args.no_backup)
    print(json.dumps({"ok": True, "asset": asset}, ensure_ascii=False, indent=2))
    return 0


def server() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_server_request(req)
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        if isinstance(req, dict) and "id" in req:
            resp["id"] = req["id"]
        print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


def handle_server_request(req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    if op == "get":
        return {"ok": True, "value": get_path(load_json_file(req["file"]), req["path"])}
    if op == "set":
        data = load_json_file(req["file"])
        changed = set_path(data, req["path"], req.get("value"), create=bool(req.get("create")))
        backup = atomic_write(req["file"], data)
        return {"ok": True, "changed": changed, "backup": backup}
    if op == "validate":
        result = validate_manifest(load_json_file(req["file"]), strict=bool(req.get("strict")))
        return {"ok": result["ok"], **result}
    if op == "list":
        value = get_path(load_json_file(req["file"]), req["path"])
        return {"ok": True, "value": value}
    if op == "media_analyze":
        data = load_json_file(req["file"])
        analyze_images(data, refresh_applicability=bool(req.get("refresh_applicability")))
        if req.get("write", True):
            atomic_write(req["file"], data)
        return {"ok": True, "analyzed": len(data.get("media_research", {}).get("source_images", []))}
    raise ValueError(f"unsupported op: {op}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect/edit/validate/pull/push LP bootstrap manifests.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("normalize")
    p.add_argument("input")
    p.add_argument("--out", required=True)

    p = sub.add_parser("get")
    p.add_argument("file")
    p.add_argument("path")

    p = sub.add_parser("set")
    p.add_argument("file")
    p.add_argument("path")
    p.add_argument("value")
    p.add_argument("--json", action="store_true")
    p.add_argument("--create", action="store_true")
    p.add_argument("--no-backup", action="store_true")

    p = sub.add_parser("list")
    p.add_argument("file")
    p.add_argument("path")

    p = sub.add_parser("validate")
    p.add_argument("file")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--for-apply", action="store_true")
    p.add_argument("--allow-unreviewed", action="store_true")
    p.add_argument("--format", choices=["pretty", "json"], default="pretty")

    p = sub.add_parser("diff")
    p.add_argument("before")
    p.add_argument("after")

    p = sub.add_parser("pull")
    p.add_argument("slug")
    p.add_argument("--out", required=True)
    p.add_argument("--base-url", default=os.environ.get("LP_BOOTSTRAP_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--secret")

    p = sub.add_parser("push")
    p.add_argument("file")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--mode", choices=["create", "update", "upsert"], default="upsert")
    p.add_argument("--base-url", default=os.environ.get("LP_BOOTSTRAP_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--secret")

    p = sub.add_parser("server")
    p.add_argument("--stdio", action="store_true")

    media = sub.add_parser("media")
    media_sub = media.add_subparsers(dest="media_cmd", required=True)
    p = media_sub.add_parser("collect")
    p.add_argument("file")
    p.add_argument("--official", action="store_true")
    p.add_argument("--web", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--out-dir")
    p.add_argument("--no-backup", action="store_true")
    p = media_sub.add_parser("analyze")
    p.add_argument("file")
    p.add_argument("--write", action="store_true")
    p.add_argument("--refresh-applicability", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p = media_sub.add_parser("list")
    p.add_argument("file")
    p.add_argument("--approved", action="store_true")
    p.add_argument("--summary", action="store_true")
    p = media_sub.add_parser("approve")
    p.add_argument("file")
    p.add_argument("image_id")
    p.add_argument("--reference", action="store_true")
    p.add_argument("--direct-use", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p = media_sub.add_parser("plan-generations")
    p.add_argument("file")
    p.add_argument("--write", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p = media_sub.add_parser("attach-generated")
    p.add_argument("file")
    p.add_argument("job_id")
    p.add_argument("asset_path")
    p.add_argument("--asset-id")
    p.add_argument("--review-status", default="needs_review")
    p.add_argument("--no-backup", action="store_true")

    args = parser.parse_args()

    if args.cmd == "normalize":
        dump_json_file(args.out, normalize_legacy_bootstrap(load_json_file(args.input)))
        return 0
    if args.cmd == "get":
        print(json.dumps(get_path(load_json_file(args.file), args.path), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "set":
        data = load_json_file(args.file)
        changed = set_path(data, args.path, load_value(args.value, args.json), create=args.create)
        backup = atomic_write(args.file, data, backup=not args.no_backup)
        print(json.dumps({"ok": True, "changed": changed, "backup": backup}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "list":
        print(json.dumps(get_path(load_json_file(args.file), args.path), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "validate":
        return validate_command(args)
    if args.cmd == "diff":
        before = Path(args.before).read_text(encoding="utf-8").splitlines()
        after = Path(args.after).read_text(encoding="utf-8").splitlines()
        print("\n".join(difflib.unified_diff(before, after, fromfile=args.before, tofile=args.after, lineterm="")))
        return 0
    if args.cmd == "pull":
        secret = secret_from_args(args)
        url = f"{args.base_url.rstrip('/')}/api/admin/lp-bootstrap-export?slug={urllib.parse.quote(args.slug)}"
        result = http_json(url, secret=secret)
        if result.get("error"):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        dump_json_file(args.out, result)
        print(json.dumps({"ok": True, "out": args.out, "slug": result.get("slug")}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "push":
        if not args.apply and not args.dry_run:
            args.dry_run = True
        manifest = load_json_file(args.file)
        secret = secret_from_args(args)
        url = f"{args.base_url.rstrip('/')}/api/admin/lp-bootstrap-import"
        result = http_json(url, method="POST", secret=secret, body={"manifest": manifest, "dry_run": args.dry_run, "apply": args.apply, "overwrite": args.overwrite, "mode": args.mode})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "server":
        if not args.stdio:
            raise SystemExit("only --stdio server mode is supported")
        return server()
    if args.cmd == "media":
        if args.media_cmd == "collect":
            return media_collect(args)
        if args.media_cmd == "analyze":
            return media_analyze(args)
        if args.media_cmd == "list":
            return media_list(args)
        if args.media_cmd == "approve":
            return media_approve(args)
        if args.media_cmd == "plan-generations":
            return media_plan_generations(args)
        if args.media_cmd == "attach-generated":
            return media_attach_generated(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
