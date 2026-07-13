from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable


FINGERPRINT_VERSION = 1
FINGERPRINT_PREFIX = "cf1_"
FINGERPRINT_PATTERN = re.compile(r"^cf1_[0-9a-f]{64}$")
REVIEW_STATUSES = {"reviewed", "expected"}

# Fingerprint v1 hashes a bounded canonical object containing finding type,
# project-relative path, severity, and identity-defining scanner evidence. It
# deliberately excludes explanations, actions, timestamps, absolute host
# context, and review/display fields. Only the SHA-256 digest is exposed.
IDENTITY_FIELDS = (
    "pattern", "script", "operation", "reason", "ecosystem", "package",
    "dependencyGroup", "requestedSpecification", "resolvedVersion",
    "sourceType", "sourceIdentifier", "fileSizeBytes", "sizeLimitBytes",
    "line", "metadata",
)
SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def finding_fingerprint(finding: dict[str, Any]) -> str:
    identity: dict[str, Any] = {
        "version": FINGERPRINT_VERSION,
        "type": _text(finding.get("type") or finding.get("finding_type") or "unknown").lower(),
        "path": _relative_path(finding.get("path") or finding.get("file_path") or ""),
        "severity": _text(finding.get("severity") or "low").lower(),
    }
    evidence = {field: _canonical(finding.get(field)) for field in IDENTITY_FIELDS}
    evidence = {key: value for key, value in evidence.items() if value not in (None, "", [], {})}
    if "pattern" not in evidence:
        legacy_pattern = _legacy_pattern(finding.get("explanation"))
        if legacy_pattern:
            evidence["pattern"] = legacy_pattern
    if "script" not in evidence:
        legacy_script = _legacy_script(finding.get("explanation"))
        if legacy_script:
            evidence["script"] = legacy_script
    if evidence:
        identity["evidence"] = evidence
    encoded = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return FINGERPRINT_PREFIX + hashlib.sha256(encoded).hexdigest()


def valid_fingerprint(value: str) -> bool:
    return bool(FINGERPRINT_PATTERN.fullmatch(str(value or "")))


def enrich_scan(scan: dict[str, Any], reviews: Iterable[dict[str, Any]]) -> dict[str, Any]:
    review_map = {
        str(review.get("fingerprint") or ""): _review_metadata(review)
        for review in reviews
        if valid_fingerprint(str(review.get("fingerprint") or ""))
        and review.get("status") in REVIEW_STATUSES
    }
    findings: list[dict[str, Any]] = []
    for raw in scan.get("findings", []):
        if not isinstance(raw, dict):
            continue
        finding = dict(raw)
        try:
            fingerprint = finding_fingerprint(finding)
        except ValueError:
            fingerprint = None
        finding["fingerprint"] = fingerprint
        finding["review"] = review_map.get(fingerprint) if fingerprint else None
        findings.append(finding)
    enriched = dict(scan)
    enriched["findings"] = findings
    enriched["reviewSummary"] = review_summary(findings)
    return enriched


def review_summary(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    findings_list = list(findings)
    reviewed = [finding for finding in findings_list if isinstance(finding.get("review"), dict)]
    unreviewed = [finding for finding in findings_list if not isinstance(finding.get("review"), dict)]
    highest = max(
        (_severity(finding.get("severity")) for finding in unreviewed),
        key=SEVERITY_ORDER.get,
        default="none",
    )
    return {
        "rawFindingCount": len(findings_list),
        "reviewedFindingCount": len(reviewed),
        "unreviewedFindingCount": len(unreviewed),
        "highestUnreviewedSeverity": highest,
    }


def _review_metadata(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(review.get("status") or "reviewed"),
        "note": str(review.get("note") or ""),
        "created_at": str(review.get("created_at") or ""),
        "updated_at": str(review.get("updated_at") or ""),
    }


def _canonical(value: Any, depth: int = 0) -> Any:
    if value is None or depth > 4:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        items = [_canonical(item, depth + 1) for item in value[:50]]
        return [item for item in items if item not in (None, "", [], {})]
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: str(item[0]))[:50]
        canonical = {str(key): _canonical(item, depth + 1) for key, item in items}
        return {key: item for key, item in canonical.items() if item not in (None, "", [], {})}
    return None


def _relative_path(value: Any) -> str:
    text = _text(value).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text:
        return ""
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError("Finding paths must be project-relative.")
    parts = text.split("/")
    if ".." in parts or "\x00" in text:
        raise ValueError("Finding paths must not escape the project.")
    return "/".join(part for part in parts if part not in ("", "."))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:1000]


def _severity(value: Any) -> str:
    severity = _text(value or "low").lower()
    return severity if severity in SEVERITY_ORDER else "high"


def _legacy_pattern(value: Any) -> str:
    match = re.search(r"\bPattern:\s*(.+?)\s*$", str(value or ""))
    return _text(match.group(1)) if match else ""


def _legacy_script(value: Any) -> str:
    match = re.search(r"defines a '([^']+)' lifecycle script", str(value or ""))
    return _text(match.group(1)) if match else ""
