"""Retired compatibility module for the removed CV-generation feature."""

from __future__ import annotations

from typing import Any

from .errors import GenerationError


def generate_profile(*args: Any, **kwargs: Any) -> None:
    """Fail explicitly for integrations which still call the old generator."""
    raise GenerationError("简历生成功能已移除；昭濂个人履历库仅用于记录与管理履历资料。")
