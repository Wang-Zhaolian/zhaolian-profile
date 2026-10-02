from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

from .constants import (
    DATA_CATEGORIES,
    PROFILE_NAMES,
    PUBLICATION_STATUSES,
    REFERENCE_FIELDS,
    REFERENCE_LIST_FIELDS,
    RECORD_STATES,
)
from .dates import date_key, validate_date_string
from .loader import load_master_data, load_profile, load_yaml


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():7} {self.code:20} {self.location}: {self.message}"


def _record_with_localized_required(item_schema: dict[str, Any], record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    normalized = dict(record)
    for field in item_schema.get("required", []):
        if field in normalized:
            continue
        alternate = next(
            (record.get(f"{field}_{language}") for language in ("zh", "en")
             if record.get(f"{field}_{language}") not in (None, "", [])),
            None,
        )
        if alternate is not None:
            normalized[field] = alternate
    return normalized


def _schema_issues(data_dir: Path, schema_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for name in ("basics", *DATA_CATEGORIES):
        data_path = data_dir / f"{name}.yaml"
        schema_path = schema_dir / f"{name}.schema.yaml"
        if not schema_path.exists():
            issues.append(
                ValidationIssue("error", "schema_missing", str(schema_path), "Schema file is missing")
            )
            continue
        if not data_path.exists():
            issues.append(
                ValidationIssue("error", "data_missing", str(data_path), "Data file is missing")
            )
            continue
        try:
            instance = load_yaml(data_path)
            schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append(
                ValidationIssue("error", "yaml", str(data_path), str(exc))
            )
            continue
        if name != "basics":
            records = instance.get("records", [])
            if isinstance(records, list):
                item_schema = schema.get("properties", {}).get("records", {}).get("items", {})
                instance = {
                    **instance,
                    "records": [
                        _record_with_localized_required(item_schema, record)
                        for record in records
                        if not isinstance(record, dict)
                        or record.get("record_state", "ready") != "draft"
                    ],
                }
        for error in sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda item: list(item.absolute_path),
        ):
            path = ".".join(str(part) for part in error.absolute_path) or "<root>"
            issues.append(
                ValidationIssue(
                    "error", "schema", f"{data_path}:{path}", error.message
                )
            )
    return issues


def _record_location(category: str, record: dict[str, Any], index: int) -> str:
    return f"{category}[{record.get('id', index)}]"


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_repository(
    data_dir: Path,
    profile_dir: Path,
    schema_dir: Path,
) -> list[ValidationIssue]:
    issues = _schema_issues(data_dir, schema_dir)
    try:
        data = load_master_data(data_dir)
    except Exception as exc:
        issues.append(ValidationIssue("error", "yaml", str(data_dir), str(exc)))
        return issues

    ids: dict[str, str] = {}
    ids_by_category: dict[str, set[str]] = {name: set() for name in DATA_CATEGORIES}
    for category in DATA_CATEGORIES:
        for index, record in enumerate(data[category]):
            location = _record_location(category, record, index)
            record_state = record.get("record_state", "ready")
            if record_state not in RECORD_STATES:
                issues.append(
                    ValidationIssue(
                        "error", "record_state", f"{location}.record_state",
                        f"Allowed values: {', '.join(sorted(RECORD_STATES))}",
                    )
                )
            record_id = record.get("id")
            if record_id:
                if record_id in ids:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "duplicate_id",
                            location,
                            f"ID {record_id!r} already used at {ids[record_id]}",
                        )
                    )
                ids[record_id] = location
                ids_by_category[category].add(record_id)

            # Drafts are saved work in progress. Missing or incomplete details
            # in a draft must not prevent ready records from being exported.
            if record_state == "draft":
                continue

            for field in ("start_date", "end_date", "expected_graduation", "date", "last_used"):
                value = record.get(field)
                if value is not None and not validate_date_string(str(value)):
                    issues.append(
                        ValidationIssue(
                            "error", "invalid_date", f"{location}.{field}", f"Invalid date {value!r}"
                        )
                    )
            start, end = record.get("start_date"), record.get("end_date")
            if start and end and validate_date_string(str(start)) and validate_date_string(str(end)):
                if date_key(str(end)) < date_key(str(start)):
                    issues.append(
                        ValidationIssue(
                            "error", "date_order", location, "end_date is earlier than start_date"
                        )
                    )

            for field in ("url", "doi", "arxiv", "repository", "demo", "presentation"):
                if field not in record:
                    continue
                value = record.get(field)
                if value == "":
                    issues.append(
                        ValidationIssue("error", "empty_url", f"{location}.{field}", "URL cannot be empty")
                    )
                elif value and field != "doi" and not _valid_url(str(value)):
                    issues.append(
                        ValidationIssue(
                            "error", "invalid_url", f"{location}.{field}", f"Invalid HTTP(S) URL: {value}"
                        )
                    )
            for evidence_index, evidence in enumerate(record.get("evidence", [])):
                if not isinstance(evidence, str) or not evidence.strip():
                    issues.append(
                        ValidationIssue(
                            "error",
                            "empty_evidence",
                            f"{location}.evidence[{evidence_index}]",
                            "Evidence path or URL cannot be empty",
                        )
                    )

    for category, fields in REFERENCE_FIELDS.items():
        for index, record in enumerate(data[category]):
            if record.get("record_state", "ready") != "ready":
                continue
            location = _record_location(category, record, index)
            for field, target in fields.items():
                reference = record.get(field)
                if reference and reference not in ids_by_category[target]:
                    issues.append(
                        ValidationIssue(
                            "error", "missing_reference", f"{location}.{field}",
                            f"{reference!r} does not exist in {target}",
                        )
                    )

    for category, fields in REFERENCE_LIST_FIELDS.items():
        for index, record in enumerate(data[category]):
            if record.get("record_state", "ready") != "ready":
                continue
            location = _record_location(category, record, index)
            for field, target in fields.items():
                for reference in record.get(field, []):
                    if reference not in ids_by_category[target]:
                        issues.append(
                            ValidationIssue(
                                "error", "missing_reference", f"{location}.{field}",
                                f"{reference!r} does not exist in {target}",
                            )
                        )

    for index, publication in enumerate(data["publications"]):
        if publication.get("record_state", "ready") != "ready":
            continue
        if publication.get("status") not in PUBLICATION_STATUSES:
            issues.append(
                ValidationIssue(
                    "error", "publication_status", _record_location("publications", publication, index),
                    f"Allowed values: {', '.join(sorted(PUBLICATION_STATUSES))}",
                )
            )

    profile_names = set(PROFILE_NAMES)
    profile_names.update(path.stem for path in profile_dir.glob("*.yaml"))
    for name in sorted(profile_names):
        try:
            profile = load_profile(profile_dir, name)
        except Exception as exc:
            issues.append(ValidationIssue("error", "profile", str(profile_dir / f"{name}.yaml"), str(exc)))
            continue
        seen_sections: set[str] = set()
        for index, section in enumerate(profile.get("sections", [])):
            section_id = section.get("id")
            if not section_id:
                issues.append(
                    ValidationIssue("error", "profile_section", f"{name}.sections[{index}]", "Missing section id")
                )
            elif section_id in seen_sections:
                issues.append(
                    ValidationIssue("error", "profile_section", name, f"Duplicate section {section_id!r}")
                )
            seen_sections.add(section_id)
            for category in section.get("categories", [section_id]):
                if category != "research_interests" and category not in DATA_CATEGORIES:
                    issues.append(
                        ValidationIssue("error", "profile_category", name, f"Unknown category {category!r}")
                    )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
