#!/usr/bin/env python3
"""Shared schema helpers for recruitment LP bootstrap manifests."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1
KIND = "recruitly.lp_bootstrap_manifest"
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")
POSTAL_RE = re.compile(r"^\d{3}-?\d{4}$")
INSTAGRAM_RE = re.compile(r"^https://(www\.)?instagram\.com/[A-Za-z0-9_.]+/?(?:[?#].*)?$")
HTTP_RE = re.compile(r"^https?://", re.I)
REQUIRED_LP_SECTIONS = [
    "meta",
    "header",
    "hero",
    "about",
    "strengths",
    "data",
    "voices",
    "openings",
    "welfare",
    "cta",
    "footer",
    "map_embed_src",
]
EMPLOYMENT_TYPES = {"FULL_TIME", "PART_TIME", "CONTRACTOR", "TEMPORARY", "OTHER"}
SALARY_UNITS = {"MONTH", "YEAR", "HOUR", "DAY"}
SECRET_KEY_HINTS = {
    "SUPABASE_SERVICE_ROLE_KEY",
    "DATABASE_URL",
    "POSTGRES_URL",
    "GOOGLE_CLIENT_SECRET",
    "refresh_token",
    "access_token",
    "VERCEL_TOKEN",
    "MIGRATION_RUNNER_SECRET",
}
APPROVED_BOOTSTRAP_EMAILS = {
    "jayden.barnes@mgc-global01.com",
    "jayden.barnes.cs@gmail.com",
}


@dataclass
class ValidationIssue:
    path: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def now_iso_date() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def is_object(value: Any) -> bool:
    return isinstance(value, dict)


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_https_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def looks_like_url(value: Any) -> bool:
    return isinstance(value, str) and bool(HTTP_RE.match(value))


def parse_iso_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def normalize_legacy_bootstrap(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap current bootstrap.py output in the canonical manifest shape."""
    slug = str(data.get("slug") or "").strip().lower()
    client_name = str(data.get("client_name") or "").strip()
    primary_url = data.get("primary_url")
    lp_content = copy.deepcopy(data.get("lp_content") or {})
    provenance = copy.deepcopy(data.get("provenance") or {})

    footer = lp_content.get("footer") if isinstance(lp_content.get("footer"), dict) else {}
    website = footer.get("website") or primary_url
    if isinstance(footer, dict) and website and "website" not in footer:
        footer["website"] = website
        lp_content["footer"] = footer

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "slug": slug,
        "client_name": client_name,
        "industry": data.get("industry") or "",
        "source": {
            "primary_url": primary_url,
            "recruit_url": data.get("recruit_url") or primary_url,
            "style_url": data.get("style_url"),
            "brief_source": data.get("brief_source") or "",
        },
        "company_profile": {
            "overview_ja": "",
            "business_lines": [],
            "recruiting_audience": [],
            "appropriate_visuals": [],
            "inappropriate_visuals": [],
            "visual_preferences": [],
        },
        "media_research": {
            "collection_policy": {
                "official_site_first": True,
                "web_image_limit": 10,
                "require_same_company_confidence": "high",
                "production_use_requires_license_or_generation": True,
                "require_image_applicability": True,
                "require_opening_image_fit": True,
            },
            "source_images": [],
            "logos": [],
            "rejected_images": [],
        },
        "image_generation": {
            "global_style_prompt": "",
            "people_policy": {
                "preserve_uniform_and_work_context": True,
                "copy_identifiable_people_only_with_client_permission": True,
                "default_to_fictional_people_when_permission_unknown": True,
            },
            "jobs": [],
            "generated_assets": [],
        },
        "setup": {
            "published": True,
            "lps_status": "live",
            "created_via": "skill",
            "admin_seed": {
                "owner_email": "jayden.barnes@mgc-global01.com",
                "member_emails": ["jayden.barnes.cs@gmail.com"],
            },
            "first_setup_enabled": True,
            "create_initial_sheet": False,
            "seed_analytics": True,
            "notify_indexing": True,
        },
        "lp_content": lp_content,
        "provenance": {
            "generated_by": "mgc-saiyo-lp-bootstrap",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "audience_pivot_reviewed": not bool(provenance.get("audience_pivot_review_needed")),
            "field_sources": provenance,
        },
        "notes": [],
    }


def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json_file(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _add(issues: list[ValidationIssue], path: str, message: str, severity: str = "error") -> None:
    issues.append(ValidationIssue(path, message, severity))


def _walk_for_secret_keys(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            key_path = f"{path}.{k}" if path else str(k)
            if str(k) in SECRET_KEY_HINTS or any(h.lower() in str(k).lower() for h in SECRET_KEY_HINTS):
                _add(issues, key_path, "secret-looking key is not allowed in manifest")
            _walk_for_secret_keys(v, key_path, issues)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_for_secret_keys(item, f"{path}[{i}]", issues)


def _validate_url(value: Any, path: str, issues: list[ValidationIssue], *, required: bool = False, https_only: bool = True) -> None:
    if value in (None, ""):
        if required:
            _add(issues, path, "required URL is missing")
        return
    if not isinstance(value, str):
        _add(issues, path, "URL must be a string")
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _add(issues, path, "URL must be http(s)")
        return
    if https_only and parsed.scheme != "https":
        _add(issues, path, "URL must use HTTPS")


def _opening_business_line(title: Any) -> str:
    title_str = str(title or "")
    if any(token in title_str for token in ("居酒屋", "キッチン", "ホール", "調理", "飲食")):
        return "izakaya"
    if any(token in title_str for token in ("金属", "加工", "機械", "梱包", "出荷", "製造", "工場")):
        return "metal_processing"
    return ""


def _is_brand_or_icon_image(img: dict[str, Any]) -> bool:
    url = str(img.get("url") or "")
    alt = ""
    extracted = img.get("extracted_context")
    if is_object(extracted):
        alt = str(extracted.get("alt") or "")
    subject = str(img.get("ai_analysis", {}).get("subject") or "") if is_object(img.get("ai_analysis")) else ""
    return bool(re.search(r"(?:^|[/_-])(insta|instagram|icon|logo|favicon)(?:[._/-]|$)", url, re.I)) or any(
        token.lower() in f"{alt} {subject}".lower()
        for token in ("logo", "icon", "instagram", "ロゴ")
    )


def _collect_lp_image_urls(c: dict[str, Any]) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []

    def add(path: str, value: Any) -> None:
        if looks_like_url(value):
            urls.append((path, str(value)))

    add("lp_content.header.logo_image", c.get("header", {}).get("logo_image"))
    add("lp_content.header.favicon_url", c.get("header", {}).get("favicon_url"))
    add("lp_content.hero.bg_image", c.get("hero", {}).get("bg_image"))
    add("lp_content.about.photo", c.get("about", {}).get("photo"))
    for i, voice in enumerate(c.get("voices", {}).get("items") or []):
        if is_object(voice):
            add(f"lp_content.voices.items[{i}].photo", voice.get("photo"))
    for i, opening in enumerate(c.get("openings", {}).get("items") or []):
        if is_object(opening):
            add(f"lp_content.openings.items[{i}].image", opening.get("image"))
            detail = opening.get("detail")
            if is_object(detail):
                add(f"lp_content.openings.items[{i}].detail.hero_bg", detail.get("hero_bg"))
                employee = detail.get("employee")
                if is_object(employee):
                    add(f"lp_content.openings.items[{i}].detail.employee.photo", employee.get("photo"))
    return urls


def _validate_content(manifest: dict[str, Any], issues: list[ValidationIssue], *, strict: bool, for_apply: bool) -> None:
    c = manifest.get("lp_content")
    if not is_object(c):
        _add(issues, "lp_content", "lp_content object is required")
        return
    for section in REQUIRED_LP_SECTIONS:
        if section not in c:
            _add(issues, f"lp_content.{section}", "required section is missing")

    if not is_non_empty_string(c.get("meta", {}).get("title")):
        _add(issues, "lp_content.meta.title", "required")
    if not is_non_empty_string(c.get("meta", {}).get("description")):
        _add(issues, "lp_content.meta.description", "required")
    if not is_non_empty_string(c.get("header", {}).get("company_name")):
        _add(issues, "lp_content.header.company_name", "required")

    instagram = c.get("header", {}).get("social_links", {}).get("instagram")
    if instagram and not INSTAGRAM_RE.match(str(instagram)):
        _add(issues, "lp_content.header.social_links.instagram", "invalid Instagram URL")

    hero = c.get("hero", {})
    for key in ("jp_tagline", "subtext", "cta_label", "cta_anchor"):
        if not is_non_empty_string(hero.get(key)):
            _add(issues, f"lp_content.hero.{key}", "required")
    if hero.get("bg_image"):
        _validate_url(hero.get("bg_image"), "lp_content.hero.bg_image", issues, https_only=False)
        if strict and re.search(r"(?:^|[/_-])(insta|instagram|icon|logo|favicon)(?:[._/-]|$)", str(hero.get("bg_image")), re.I):
            _add(issues, "lp_content.hero.bg_image", "hero image looks like an icon/logo asset", "warning")

    about = c.get("about", {})
    if not is_non_empty_string(about.get("headline")):
        _add(issues, "lp_content.about.headline", "required")
    if not isinstance(about.get("paragraphs"), list) or not any(is_non_empty_string(p) for p in about.get("paragraphs", [])):
        _add(issues, "lp_content.about.paragraphs", "at least one paragraph is required")

    if not c.get("strengths", {}).get("items"):
        _add(issues, "lp_content.strengths.items", "at least one strength is required")

    openings = c.get("openings", {}).get("items")
    if not isinstance(openings, list) or not openings:
        _add(issues, "lp_content.openings.items", "at least one opening is required")
    elif isinstance(openings, list):
        for i, opening in enumerate(openings):
            if not is_object(opening):
                _add(issues, f"lp_content.openings.items[{i}]", "opening must be an object")
                continue
            for key in ("title", "badge", "description"):
                if not is_non_empty_string(opening.get(key)):
                    _add(issues, f"lp_content.openings.items[{i}].{key}", "required")
            if opening.get("image"):
                _validate_url(opening.get("image"), f"lp_content.openings.items[{i}].image", issues, https_only=False)
            elif strict:
                _add(issues, f"lp_content.openings.items[{i}].image", "image is required in strict mode")
            detail = opening.get("detail")
            if is_object(detail):
                employment_type = detail.get("employment_type")
                if employment_type and employment_type not in EMPLOYMENT_TYPES:
                    _add(issues, f"lp_content.openings.items[{i}].detail.employment_type", "invalid employment type")
                posted = detail.get("posted_date")
                valid_through = detail.get("valid_through")
                posted_date = parse_iso_date(posted) if posted else None
                valid_date = parse_iso_date(valid_through) if valid_through else None
                if posted and not posted_date:
                    _add(issues, f"lp_content.openings.items[{i}].detail.posted_date", "must be ISO YYYY-MM-DD")
                if valid_through and not valid_date:
                    _add(issues, f"lp_content.openings.items[{i}].detail.valid_through", "must be ISO YYYY-MM-DD")
                if posted_date and valid_date and valid_date <= posted_date:
                    _add(issues, f"lp_content.openings.items[{i}].detail.valid_through", "must be after posted_date")
                salary_unit = detail.get("salary_unit")
                if salary_unit and salary_unit not in SALARY_UNITS:
                    _add(issues, f"lp_content.openings.items[{i}].detail.salary_unit", "invalid salary unit")
                if isinstance(detail.get("salary_min"), (int, float)) and isinstance(detail.get("salary_max"), (int, float)):
                    if detail["salary_min"] > detail["salary_max"]:
                        _add(issues, f"lp_content.openings.items[{i}].detail.salary_min", "salary_min must be <= salary_max")

    footer = c.get("footer", {})
    for key in ("company_name", "address", "business"):
        if not is_non_empty_string(footer.get(key)):
            _add(issues, f"lp_content.footer.{key}", "required")
    _validate_url(footer.get("website"), "lp_content.footer.website", issues, https_only=True)

    lp_map = c.get("map")
    if strict:
        if not is_object(lp_map):
            _add(issues, "lp_content.map", "structured map is required in strict mode")
        else:
            for key in ("region", "locality", "street", "postal_code"):
                if not is_non_empty_string(lp_map.get(key)):
                    _add(issues, f"lp_content.map.{key}", "required in strict mode")
            if lp_map.get("postal_code") and not POSTAL_RE.match(str(lp_map.get("postal_code"))):
                _add(issues, "lp_content.map.postal_code", "postal_code must look like 000-0000")
        if not is_non_empty_string(c.get("map_embed_src")):
            _add(issues, "lp_content.map_embed_src", "Google Maps iframe src is required in strict mode")

    profile = manifest.get("company_profile")
    if strict:
        if not is_object(profile):
            _add(issues, "company_profile", "company_profile is required in strict mode")
        else:
            if not is_non_empty_string(profile.get("overview_ja")):
                _add(issues, "company_profile.overview_ja", "required in strict mode")
            if not profile.get("business_lines"):
                _add(issues, "company_profile.business_lines", "at least one business line is required")
            elif isinstance(profile.get("business_lines"), list) and len(profile.get("business_lines")) > 1:
                if not isinstance(profile.get("entities"), list) or not profile.get("entities"):
                    _add(issues, "company_profile.entities", "multi-business/group contexts should define company/operated-business entities", "warning")
                for i, line in enumerate(profile.get("business_lines")):
                    if not is_object(line):
                        continue
                    for key in ("entity_id", "entity_name", "company_scope"):
                        if not is_non_empty_string(line.get(key)):
                            _add(issues, f"company_profile.business_lines[{i}].{key}", "required for multi-business/group contexts", "warning")
            if not profile.get("appropriate_visuals"):
                _add(issues, "company_profile.appropriate_visuals", "required in strict mode")
            if not profile.get("inappropriate_visuals"):
                _add(issues, "company_profile.inappropriate_visuals", "required in strict mode")

    media = manifest.get("media_research", {})
    if strict and is_object(media):
        source_images = media.get("source_images") or []
        logos = media.get("logos") or []
        direct_use_records = {
            item.get("url"): item
            for item in [*source_images, *logos]
            if is_object(item) and item.get("approved_for_direct_use")
        }
        generated_paths = {
            asset.get("local_path")
            for asset in manifest.get("image_generation", {}).get("generated_assets", []) or []
            if is_object(asset) and asset.get("review_status") == "approved"
        }
        for path, url in _collect_lp_image_urls(c):
            if url in generated_paths:
                continue
            record = direct_use_records.get(url)
            if not record:
                _add(issues, path, "LP image URL is not approved for direct use in media_research", "warning")
            elif record.get("rights_status") in {"unknown", "unknown_web"}:
                _add(issues, path, "LP image direct-use rights are unknown", "warning")
        openings = manifest.get("lp_content", {}).get("openings", {}).get("items") or []
        opening_lines = {
            i: _opening_business_line(opening.get("title"))
            for i, opening in enumerate(openings)
            if is_object(opening)
        }
        opening_has_image = {i: False for i in opening_lines}
        if not logos:
            _add(issues, "media_research.logos", "no logo candidate recorded", "warning")
        business_lines = profile.get("business_lines", []) if is_object(profile) else []
        business_line_ids = {
            line.get("id")
            for line in business_lines
            if is_object(line) and line.get("id")
        }
        for line in business_lines:
            line_id = line.get("id") if is_object(line) else None
            if not line_id:
                continue
            if not any(img.get("approved_for_reference") and img.get("ai_analysis", {}).get("business_line") == line_id for img in source_images if is_object(img)):
                _add(issues, "media_research.source_images", f"no approved reference image for business line {line_id}", "warning")
        for i, img in enumerate(source_images):
            if not is_object(img):
                _add(issues, f"media_research.source_images[{i}]", "image record must be an object")
                continue
            if img.get("approved_for_direct_use") and img.get("rights_status") in {"unknown", "unknown_web"}:
                _add(issues, f"media_research.source_images[{i}].rights_status", "direct-use image cannot have unknown rights", "warning")
            if not img.get("approved_for_reference") or _is_brand_or_icon_image(img):
                continue

            applicability = img.get("applicability")
            if not is_object(applicability):
                _add(issues, f"media_research.source_images[{i}].applicability", "approved reference image must define company/entity/business/job applicability", "warning")
                continue
            for key in ("company_scope", "entity_id", "entity_name", "business_line", "confidence", "evidence"):
                if key == "evidence":
                    if not isinstance(applicability.get(key), list) or not applicability.get(key):
                        _add(issues, f"media_research.source_images[{i}].applicability.{key}", "at least one evidence note is required", "warning")
                elif not is_non_empty_string(applicability.get(key)):
                    _add(issues, f"media_research.source_images[{i}].applicability.{key}", "required", "warning")

            analysis_line = img.get("ai_analysis", {}).get("business_line") if is_object(img.get("ai_analysis")) else None
            app_line = applicability.get("business_line")
            if analysis_line and app_line and analysis_line != app_line:
                _add(issues, f"media_research.source_images[{i}].applicability.business_line", "must match ai_analysis.business_line", "warning")
            if app_line and business_line_ids and app_line not in business_line_ids:
                _add(issues, f"media_research.source_images[{i}].applicability.business_line", f"unknown business line {app_line}", "warning")

            indexes = applicability.get("applicable_opening_indexes")
            if not isinstance(indexes, list) or not indexes:
                _add(issues, f"media_research.source_images[{i}].applicability.applicable_opening_indexes", "approved reference image should map to at least one opening", "warning")
                continue
            for idx in indexes:
                if not isinstance(idx, int) or idx < 0 or idx >= len(openings):
                    _add(issues, f"media_research.source_images[{i}].applicability.applicable_opening_indexes", f"invalid opening index {idx!r}", "warning")
                    continue
                if app_line and opening_lines.get(idx) and opening_lines[idx] != app_line:
                    _add(issues, f"media_research.source_images[{i}].applicability.applicable_opening_indexes", f"image business line {app_line} does not match opening {idx} business line {opening_lines[idx]}", "warning")
                opening_has_image[idx] = True

            if img.get("source_type") == "web_image_search" and not applicability.get("human_verified_same_company"):
                _add(issues, f"media_research.source_images[{i}].applicability.human_verified_same_company", "web image requires explicit same-company verification before reference use", "warning")

        for idx, has_image in opening_has_image.items():
            if not has_image:
                _add(issues, f"lp_content.openings.items[{idx}].image", "no approved reference image applicability maps to this opening", "warning")

    image_generation = manifest.get("image_generation", {})
    if is_object(image_generation):
        source_ids = {
            img.get("id")
            for img in media.get("source_images", [])
            if is_object(img) and img.get("approved_for_reference")
        }
        for i, job in enumerate(image_generation.get("jobs") or []):
            if not is_object(job):
                _add(issues, f"image_generation.jobs[{i}]", "generation job must be an object")
                continue
            for key in ("target_section", "prompt", "negative_prompt"):
                if not is_non_empty_string(job.get(key)):
                    _add(issues, f"image_generation.jobs[{i}].{key}", "required")
            for source_id in job.get("source_image_ids") or []:
                if source_id not in source_ids:
                    _add(issues, f"image_generation.jobs[{i}].source_image_ids", f"source image {source_id!r} is not approved for reference")
            if job.get("uses_identifiable_people") and not job.get("permission_status"):
                _add(issues, f"image_generation.jobs[{i}].permission_status", "required when using identifiable people")
        for i, asset in enumerate(image_generation.get("generated_assets") or []):
            if not is_object(asset):
                _add(issues, f"image_generation.generated_assets[{i}]", "generated asset must be an object")
                continue
            for key in ("id", "generation_job_id", "local_path", "target_section", "prompt_used", "review_status"):
                if not is_non_empty_string(asset.get(key)):
                    _add(issues, f"image_generation.generated_assets[{i}].{key}", "required")
            if for_apply and asset.get("review_status") not in {"approved"}:
                _add(issues, f"image_generation.generated_assets[{i}].review_status", "generated asset must be approved before apply", "warning")


def validate_manifest(
    data: Any,
    *,
    strict: bool = False,
    for_apply: bool = False,
    allow_unreviewed: bool = False,
) -> dict[str, Any]:
    issues: list[ValidationIssue] = []
    if not is_object(data):
        _add(issues, "$", "top-level JSON value must be an object")
        return _result(issues, strict)

    if data.get("schema_version") != SCHEMA_VERSION:
        _add(issues, "schema_version", f"must be {SCHEMA_VERSION}")
    if data.get("kind") != KIND:
        _add(issues, "kind", f"must be {KIND}")
    slug = data.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        _add(issues, "slug", "must match ^[a-z0-9-]{1,64}$")
    if not is_non_empty_string(data.get("client_name")):
        _add(issues, "client_name", "required")
    if not is_object(data.get("setup")):
        _add(issues, "setup", "setup object is required")

    source = data.get("source")
    if is_object(source):
        for key in ("primary_url", "recruit_url", "style_url"):
            _validate_url(source.get(key), f"source.{key}", issues, required=False, https_only=True)
    elif strict:
        _add(issues, "source", "source object is required in strict mode")

    setup = data.get("setup") if is_object(data.get("setup")) else {}
    admin_seed = setup.get("admin_seed") if is_object(setup.get("admin_seed")) else {}
    emails = []
    if admin_seed.get("owner_email"):
        emails.append(admin_seed.get("owner_email"))
    emails.extend(admin_seed.get("member_emails") or [])
    for email in emails:
        if not isinstance(email, str) or "@" not in email:
            _add(issues, "setup.admin_seed", f"invalid admin email {email!r}")
        elif email.lower() not in APPROVED_BOOTSTRAP_EMAILS:
            _add(issues, "setup.admin_seed", f"admin email {email} is outside approved bootstrap list", "warning")

    provenance = data.get("provenance") if is_object(data.get("provenance")) else {}
    if for_apply and not allow_unreviewed and provenance.get("audience_pivot_reviewed") is not True:
        _add(issues, "provenance.audience_pivot_reviewed", "must be true before apply")
    elif strict and provenance.get("audience_pivot_reviewed") is not True:
        _add(issues, "provenance.audience_pivot_reviewed", "audience pivot review still required", "warning")

    _walk_for_secret_keys(data, "", issues)
    _validate_content(data, issues, strict=strict, for_apply=for_apply)
    return _result(issues, strict)


def _result(issues: list[ValidationIssue], strict: bool) -> dict[str, Any]:
    errors = [i.to_dict() for i in issues if i.severity == "error"]
    warnings = [i.to_dict() for i in issues if i.severity == "warning"]
    ok = not errors and not (strict and False)
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "issue_count": len(errors) + len(warnings),
    }
