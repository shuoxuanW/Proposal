"""模板画像：把模板的页序/形状名/样式收敛到 YAML，避免代码写死。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = ROOT / "data" / "templates" / "visual_proposal_profile.yaml"


@dataclass
class TemplateProfile:
    path: Path
    raw: dict[str, Any]

    def base(self, role: str) -> dict[str, Any]:
        return (self.raw.get("base_slides") or {}).get(role, {}) or {}

    @property
    def style(self) -> dict[str, Any]:
        return self.raw.get("appendix_style") or {}

    @property
    def theme(self) -> dict[str, Any]:
        return self.raw.get("theme") or {}

    @property
    def appendix_roles(self) -> list[dict[str, Any]]:
        return self.raw.get("appendix_roles") or []


def load_profile(path: str | Path | None = None) -> TemplateProfile:
    p = Path(path) if path else DEFAULT_PROFILE
    if not p.exists():
        return TemplateProfile(p, {})
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return TemplateProfile(p, data)
