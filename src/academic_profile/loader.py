from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .constants import DATA_CATEGORIES
from .errors import AcademicProfileError


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AcademicProfileError(f"Required YAML file not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AcademicProfileError(f"Invalid YAML in {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AcademicProfileError(f"Top-level YAML value must be a mapping: {path}")
    return value


def load_master_data(data_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"basics": load_yaml(data_dir / "basics.yaml")}
    categories = list(DATA_CATEGORIES)
    registry_path = data_dir / "categories.yaml"
    if registry_path.exists():
        try:
            from .categories import load_registry
            registry = load_registry(data_dir.parent)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise AcademicProfileError(f"Invalid category registry in {registry_path}: {exc}") from exc
        if isinstance(registry, dict) and isinstance(registry.get("categories"), list):
            for item in registry["categories"]:
                category_id = item.get("id") if isinstance(item, dict) else None
                if isinstance(category_id, str) and category_id not in categories:
                    categories.append(category_id)
    for category in categories:
        if not category.replace("_", "").isalnum() or not category[:1].isalpha():
            raise AcademicProfileError(f"Invalid category identifier: {category!r}")
        document = load_yaml(data_dir / f"{category}.yaml")
        records = document.get("records", [])
        if not isinstance(records, list):
            raise AcademicProfileError(
                f"{data_dir / f'{category}.yaml'}: 'records' must be a list"
            )
        result[category] = records
    return result


def load_profile(profile_dir: Path, name: str) -> dict[str, Any]:
    profile = load_yaml(profile_dir / f"{name}.yaml")
    declared_name = profile.get("profile")
    if declared_name != name:
        raise AcademicProfileError(
            f"Profile name mismatch in {profile_dir / f'{name}.yaml'}: "
            f"expected {name!r}, got {declared_name!r}"
        )
    return profile


def load_contact(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return load_yaml(path)
