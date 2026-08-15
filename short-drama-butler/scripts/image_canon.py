#!/usr/bin/env python3
"""Resolve existing confirmed images that must be attached before generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keyframe_consistency import (
    ASSET_ROLES,
    KeyframeConsistencyError,
    MAX_INPUT_IMAGES,
    resolve_keyframe_asset_uses,
)


KIND_ROLE = {
    "characters": "character_identity",
    "character": "character_identity",
    "scenes": "background",
    "scene": "background",
    "props": "prop_identity",
    "prop": "prop_identity",
}


class ImageCanonError(ValueError):
    """Raised when image generation cannot legally proceed."""


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward until project memory files are found."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        settings = candidate / "project-settings"
        if (settings / "project.yaml").is_file() or (settings / "asset-index.json").is_file():
            return candidate
    raise ImageCanonError("找不到项目记忆：请在含 project-settings/ 的短剧项目目录中运行")


def load_asset_index(project_root: Path) -> list[dict[str, Any]]:
    index_path = Path(project_root).resolve() / "project-settings" / "asset-index.json"
    if not index_path.is_file():
        return []
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ImageCanonError("资产索引 assets 必须是列表")
    return assets


def confirmed_image_assets(project_root: Path) -> list[dict[str, Any]]:
    """Return indexed assets whose registered views actually exist on disk."""
    root = Path(project_root).resolve()
    confirmed: list[dict[str, Any]] = []
    for asset in load_asset_index(root):
        if asset.get("scope") == "pending":
            continue
        views = [view for view in asset.get("views", []) if view.get("path")]
        if not views and asset.get("destination"):
            views = [{"variant": "reference", "path": asset["destination"]}]
        existing = []
        for view in views:
            relative = Path(str(view["path"]))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            if (root / relative).is_file():
                existing.append({**view, "path": relative.as_posix()})
        if existing:
            confirmed.append({**asset, "views": existing})
    return confirmed


def _tokens(asset: dict[str, Any]) -> list[str]:
    values = [asset.get("name"), asset.get("asset_id"), *asset.get("aliases", [])]
    return [str(value) for value in values if value]


def _mentioned_assets(assets: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    mentioned: list[dict[str, Any]] = []
    for asset in sorted(assets, key=lambda item: max((len(token) for token in _tokens(item)), default=0), reverse=True):
        if any(token and token in text for token in _tokens(asset)):
            mentioned.append(asset)
    return mentioned


def _resolve_use(project_root: Path, asset: dict[str, Any], role: str) -> dict[str, Any] | None:
    reference = asset.get("name") or asset.get("asset_id")
    if not reference or role not in ASSET_ROLES:
        return None
    try:
        resolved = resolve_keyframe_asset_uses(
            project_root,
            [{"reference": str(reference), "role": role, "required": True}],
        )
    except KeyframeConsistencyError:
        return None
    return resolved[0] if resolved else None


def resolve_production_reference_images(
    project_root: Path,
    *,
    name: str,
    kind: str,
    visual_brief: str = "",
    max_images: int = MAX_INPUT_IMAGES,
) -> list[dict[str, Any]]:
    """Pick existing canon images that a new asset generation must attach."""
    root = Path(project_root).resolve()
    confirmed = confirmed_image_assets(root)
    skip_names = {name.strip()}
    available = [
        asset
        for asset in confirmed
        if asset.get("name") not in skip_names and asset.get("asset_id") not in skip_names
    ]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(asset: dict[str, Any], role: str) -> None:
        if len(selected) >= max_images:
            return
        resolved = _resolve_use(root, asset, role)
        path = resolved.get("path") if resolved else None
        if not path or path in seen:
            return
        seen.add(path)
        selected.append(resolved)

    haystack = f"{name} {visual_brief}"
    for asset in _mentioned_assets(available, haystack):
        add(asset, KIND_ROLE.get(str(asset.get("kind")), "style"))

    def preferred(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        global_assets = [asset for asset in assets if asset.get("scope") == "global"]
        return global_assets or assets

    needs_character_style = KIND_ROLE.get(kind) == "character_identity" and not any(
        item.get("role") in {"character_identity", "style"} for item in selected
    )
    needs_scene_style = KIND_ROLE.get(kind) == "background" and not any(
        item.get("role") in {"background", "style"} for item in selected
    )
    if needs_character_style:
        for asset in preferred([item for item in available if KIND_ROLE.get(str(item.get("kind"))) == "character_identity"]):
            add(asset, "style")
            if any(item.get("role") == "style" for item in selected):
                break
    if needs_scene_style:
        for asset in preferred([item for item in available if KIND_ROLE.get(str(item.get("kind"))) == "background"]):
            add(asset, "style")
            if any(item.get("role") == "style" for item in selected):
                break
    if not selected:
        for asset in preferred(available):
            add(asset, "style")
            if selected:
                break
    return selected


def assert_reference_images_required(
    input_images: list[dict[str, Any]],
    *,
    confirmed_asset_count: int,
    allow_first_canon: bool = False,
) -> None:
    """Refuse text-only generation once the project already has confirmed images."""
    paths = [item.get("path") for item in input_images if item.get("path")]
    if paths:
        return
    if confirmed_asset_count <= 0 and allow_first_canon:
        return
    raise ImageCanonError("项目已有确认素材，禁止不附带参考图的纯文生图")
