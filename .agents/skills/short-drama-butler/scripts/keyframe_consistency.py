#!/usr/bin/env python3
"""Pure planning helpers for traceable, five-image keyframe generation.

The module reads registered asset metadata when resolving names, but it never
writes project files and never calls an image or video provider.  Persistence
and provider adaptation deliberately belong to ``project_files.py`` callers.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


MAX_INPUT_IMAGES = 5
ASSET_ROLES = {"background", "character_identity", "prop_identity", "lighting", "composition", "style"}
CONTINUITY_DIMENSIONS = {"space", "character_identity", "prop_identity", "composition"}
SCOPE_PRIORITY = {"episode": 0, "continuity_run": 1, "shot": 2}
CHARACTER_VIEWS = ("front", "side", "back", "expression-sheet")
SCENE_VIEWS = ("front", "reverse", "side", "wide", "top")


class KeyframeConsistencyError(ValueError):
    """Raised when a proposed keyframe input cannot be safely planned."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_file(root: Path, relative_path: str, field: str = "path") -> tuple[Path, str]:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise KeyframeConsistencyError(f"{field}必须是项目内相对路径：{relative_path}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise KeyframeConsistencyError(f"{field}逃出项目根目录：{relative_path}") from error
    if not candidate.is_file():
        raise KeyframeConsistencyError(f"找不到素材图片：{relative_path}")
    return candidate, candidate.relative_to(root).as_posix()


def _asset_matches(assets: Iterable[dict[str, Any]], reference: str) -> list[dict[str, Any]]:
    return [
        asset
        for asset in assets
        if reference == asset.get("asset_id")
        or reference == asset.get("name")
        or reference in asset.get("aliases", [])
    ]


def _view_order(asset: dict[str, Any], requested: str | None) -> tuple[str, ...]:
    kind = asset.get("kind")
    if kind in {"character", "characters"}:
        standard = CHARACTER_VIEWS
    elif kind in {"scene", "scenes"}:
        standard = SCENE_VIEWS
    else:
        standard = ("reference", "front", "side", "back")
    if requested:
        return (requested,) + tuple(view for view in standard if view != requested)
    return standard


def _select_view(asset: dict[str, Any], requested: str | None) -> tuple[dict[str, Any], str | None]:
    views = {view.get("variant"): view for view in asset.get("views", []) if view.get("variant") and view.get("path")}
    if not views and asset.get("destination"):
        views = {"reference": {"variant": "reference", "path": asset["destination"]}}
    for variant in _view_order(asset, requested):
        view = views.get(variant)
        if view:
            if requested and variant != requested:
                return view, f"requested view '{requested}' unavailable; fell back to '{variant}'"
            return view, None
    raise KeyframeConsistencyError(f"资产没有可用视图：{asset.get('asset_id', asset.get('name', 'unknown'))}")


def resolve_keyframe_asset_uses(project_root: Path, asset_uses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve registered references to verified project-local asset views.

    Every returned item has a stable ID, selected view, relative path and fresh
    SHA-256.  Ambiguous references, missing paths and traversal attempts fail
    before a planner can emit a generation request.
    """
    root = Path(project_root).resolve()
    index_path = root / "project-settings" / "asset-index.json"
    if not index_path.is_file():
        raise KeyframeConsistencyError("找不到资产索引：project-settings/asset-index.json")
    try:
        assets = json.loads(index_path.read_text(encoding="utf-8")).get("assets", [])
    except json.JSONDecodeError as error:
        raise KeyframeConsistencyError("资产索引不是有效 JSON") from error
    if not isinstance(assets, list):
        raise KeyframeConsistencyError("资产索引 assets 必须是列表")

    resolved: list[dict[str, Any]] = []
    for asset_use in asset_uses:
        reference = asset_use.get("reference")
        role = asset_use.get("role")
        if not isinstance(reference, str) or not reference:
            raise KeyframeConsistencyError("素材用途缺少 reference")
        if role not in ASSET_ROLES:
            raise KeyframeConsistencyError(f"素材用途角色不合法：{role}")
        matches = _asset_matches(assets, reference)
        if not matches:
            raise KeyframeConsistencyError(f"未登记素材：{reference}")
        if len(matches) != 1:
            raise KeyframeConsistencyError(f"素材名称歧义：{reference}")
        asset = matches[0]
        requested = asset_use.get("view_hint") or asset_use.get("facing")
        view, fallback_reason = _select_view(asset, requested)
        source, relative_path = _project_file(root, str(view["path"]))
        item = {
            "asset_id": asset["asset_id"],
            "name": asset.get("name", asset["asset_id"]),
            "kind": asset.get("kind", ""),
            "scope": asset.get("scope", ""),
            "role": role,
            "required": bool(asset_use.get("required", False)),
            "selected_view": view["variant"],
            "path": relative_path,
            "sha256": _sha256(source),
            "fallback_reason": fallback_reason,
        }
        for field in ("relationship_group", "continuity_relevant", "subject_tier", "priority"):
            if field in asset_use:
                item[field] = asset_use[field]
        resolved.append(item)
    return resolved


def validate_continuity_contract(frame_spec: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize the explicit, non-inferred continuity contract."""
    if "continuity_contract" not in frame_spec:
        raise KeyframeConsistencyError("frame_spec 必须明确包含 continuity_contract（或 null）")
    contract = frame_spec["continuity_contract"]
    if contract is None:
        return None
    if not isinstance(contract, dict):
        raise KeyframeConsistencyError("continuity_contract 必须是对象或 null")
    predecessor = contract.get("predecessor")
    if not isinstance(predecessor, dict) or not predecessor.get("shot_id") or not predecessor.get("frame_kind"):
        raise KeyframeConsistencyError("continuity_contract 缺少精确 predecessor")
    dimensions = contract.get("inherit_dimensions")
    if not isinstance(dimensions, list) or not dimensions or not set(dimensions).issubset(CONTINUITY_DIMENSIONS):
        raise KeyframeConsistencyError("inherit_dimensions 必须是允许维度的非空子集")
    asset_ids = contract.get("asset_ids")
    if not isinstance(asset_ids, list) or not asset_ids or not all(isinstance(asset_id, str) and asset_id for asset_id in asset_ids):
        raise KeyframeConsistencyError("continuity_contract 缺少 asset_ids")
    return {
        "predecessor": {"shot_id": str(predecessor["shot_id"]), "frame_kind": str(predecessor["frame_kind"])},
        "inherit_dimensions": list(dimensions),
        "asset_ids": list(asset_ids),
    }


def select_applicable_overrides(
    overrides: list[dict[str, Any]], shot_id: str, asset_ids: Iterable[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Choose one applicable user override per dimension and target.

    Scope wins first (shot > continuity_run > episode); within the same scope,
    later ``created_at`` wins.  The losing entries remain traceable under
    ``superseded`` and never become stage input.
    """
    allowed_assets = set(asset_ids or [])
    applicable: list[dict[str, Any]] = []
    for override in overrides:
        role = override.get("role")
        if role not in ASSET_ROLES:
            raise KeyframeConsistencyError(f"用户覆盖角色不合法：{role}")
        target = override.get("target_asset_id")
        if role in {"character_identity", "prop_identity"} and not target:
            raise KeyframeConsistencyError(f"{role} 覆盖必须指定 target_asset_id")
        if target and allowed_assets and target not in allowed_assets:
            continue
        scope = override.get("scope")
        if scope not in SCOPE_PRIORITY:
            raise KeyframeConsistencyError(f"用户覆盖 scope 不合法：{scope}")
        scope_ids = override.get("scope_ids", [])
        if not isinstance(scope_ids, list):
            raise KeyframeConsistencyError("用户覆盖 scope_ids 必须是列表")
        if scope != "episode" and shot_id not in scope_ids:
            continue
        if not override.get("override_id") or not override.get("path") or not override.get("sha256"):
            raise KeyframeConsistencyError("用户覆盖缺少 override_id、path 或 sha256")
        applicable.append(dict(override))

    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for override in applicable:
        groups[(override["role"], override.get("target_asset_id"))].append(override)
    effective: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    for group in groups.values():
        group.sort(key=lambda item: (SCOPE_PRIORITY[item["scope"]], item.get("created_at", ""), item["override_id"]))
        winner = group[-1]
        effective.append(winner)
        superseded.extend({**item, "status": "superseded", "superseded_by": winner["override_id"]} for item in group[:-1])
    return {"effective": effective, "superseded": superseded}


def resolve_applicable_overrides(
    project_root: Path, overrides: list[dict[str, Any]], shot_id: str, asset_ids: Iterable[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Select overrides and verify their project-local image paths and hashes."""
    root = Path(project_root).resolve()
    selected = select_applicable_overrides(overrides, shot_id, asset_ids)
    for override in selected["effective"]:
        source, relative_path = _project_file(root, override["path"], "用户覆盖 path")
        if _sha256(source) != override["sha256"]:
            raise KeyframeConsistencyError(f"用户覆盖哈希不匹配：{relative_path}")
        override["path"] = relative_path
    return selected


def _input_from_asset(item: dict[str, Any]) -> dict[str, Any]:
    result = {key: item[key] for key in ("role", "path", "sha256")}
    result.update({"asset_id": item["asset_id"], "name": item.get("name", item["asset_id"]), "required": bool(item.get("required", False))})
    if item.get("relationship_group"):
        result["relationship_group"] = item["relationship_group"]
    return result


def _input_from_override(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "role": item["role"],
        "path": item["path"],
        "sha256": item["sha256"],
        "override_id": item["override_id"],
        "required": True,
    }
    if item.get("target_asset_id"):
        result["asset_id"] = item["target_asset_id"]
    return result


def _candidate_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("asset_id") or ""), str(item.get("role") or ""))


def _group_candidates(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    ordered: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        group = candidate.get("relationship_group")
        if group:
            if group not in grouped:
                grouped[group] = []
                ordered.append(grouped[group])
            grouped[group].append(candidate)
        else:
            ordered.append([candidate])
    return ordered


def _stage_kind(entries: list[dict[str, Any]]) -> str:
    roles = {entry["role"] for entry in entries}
    if roles & {"background", "lighting", "composition", "style"}:
        return "background"
    if any(entry.get("subject_tier") == "primary" for entry in entries):
        return "primary_subjects"
    if "character_identity" in roles:
        return "primary_subjects"
    return "secondary_subjects"


def _approved_board(
    approved_boards: Iterable[dict[str, Any]], plan_id: str, group: str, asset_ids: set[str]
) -> dict[str, Any] | None:
    for board in approved_boards:
        if board.get("plan_id") != plan_id or board.get("relationship_group") != group:
            continue
        if not board.get("board_id") or not board.get("path") or not board.get("sha256"):
            continue
        if board.get("approved") is not True:
            continue
        if not asset_ids.issubset(set(board.get("member_asset_ids", []))):
            continue
        return board
    return None


def _validate_anchor(anchor: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    predecessor = contract["predecessor"]
    if anchor.get("shot_id") != predecessor["shot_id"] or anchor.get("frame_kind") != predecessor["frame_kind"]:
        raise KeyframeConsistencyError("连续性锚点与 continuity_contract predecessor 不匹配")
    if anchor.get("status") not in {None, "confirmed"}:
        raise KeyframeConsistencyError("连续性锚点尚未确认")
    for field in ("path", "sha256", "revision"):
        if not anchor.get(field):
            raise KeyframeConsistencyError(f"连续性锚点缺少 {field}")
    return {
        "role": "edit_target",
        "path": anchor["path"],
        "sha256": anchor["sha256"],
        "revision": anchor["revision"],
        "source": "continuity_anchor",
        "shot_id": anchor["shot_id"],
        "frame_kind": anchor["frame_kind"],
    }


def build_generation_plan(
    plan_id: str,
    frame_spec: dict[str, Any],
    resolved_uses: list[dict[str, Any]],
    applicable_overrides: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
    confirmed_anchor: dict[str, Any] | None,
    approved_boards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic required-first plan without side effects.

    A generate stage can take five references.  Once an edit target exists,
    every later stage has exactly one edit target plus at most four new inputs.
    Relationship groups are atomic; an oversized group returns the explicit
    ``reference_board_required`` signal unless a matching approved board exists.
    """
    if not plan_id:
        raise KeyframeConsistencyError("plan_id 不能为空")
    contract = validate_continuity_contract(frame_spec)
    if contract and not confirmed_anchor:
        return {"plan_id": plan_id, "status": "waiting_for_dependency", "continuity_contract": contract}
    anchor_input = _validate_anchor(confirmed_anchor, contract) if contract and confirmed_anchor else None

    overrides = applicable_overrides.get("effective", []) if isinstance(applicable_overrides, dict) else applicable_overrides
    candidates = [_input_from_asset(item) for item in resolved_uses]
    for override in overrides:
        override_input = _input_from_override(override)
        target_key = _candidate_key(override_input)
        if override.get("target_asset_id"):
            candidates = [item for item in candidates if _candidate_key(item) != target_key]
        else:
            # A dimension-wide override (for example a user beach background)
            # replaces only that dimension's default anchors, never identities
            # or geometry represented by other roles.
            candidates = [item for item in candidates if item.get("role") != override["role"]]
        candidates.append(override_input)

    for item in candidates:
        if item.get("required") and not item.get("path"):
            raise KeyframeConsistencyError("required 输入缺少路径")
        if item.get("required") and not item.get("sha256"):
            raise KeyframeConsistencyError("required 输入缺少 sha256")
    required = [item for item in candidates if item.get("required")]
    optional = [item for item in candidates if not item.get("required")]

    groups = _group_candidates(required)
    normalized_groups: list[list[dict[str, Any]]] = []
    for group in groups:
        relationship_group = group[0].get("relationship_group")
        capacity = MAX_INPUT_IMAGES if not anchor_input and not normalized_groups else MAX_INPUT_IMAGES - 1
        if relationship_group and len(group) > capacity:
            asset_ids = {item["asset_id"] for item in group if item.get("asset_id")}
            board = _approved_board(approved_boards, plan_id, relationship_group, asset_ids)
            if board is None:
                return {
                    "plan_id": plan_id,
                    "status": "reference_board_required",
                    "relationship_group": relationship_group,
                    "asset_ids": sorted(asset_ids),
                    "capacity": capacity,
                }
            normalized_groups.append(
                [
                    {
                        "role": "reference_board",
                        "path": board["path"],
                        "sha256": board["sha256"],
                        "board_id": board["board_id"],
                        "relationship_group": relationship_group,
                        "covers_asset_ids": sorted(asset_ids),
                        "required": True,
                    }
                ]
            )
        else:
            normalized_groups.append(group)

    stages: list[list[dict[str, Any]]] = []
    for group in normalized_groups:
        last_stage_capacity = MAX_INPUT_IMAGES if len(stages) == 1 and not anchor_input else MAX_INPUT_IMAGES - 1
        if stages and len(stages[-1]) + len(group) <= last_stage_capacity:
            stages[-1].extend(group)
        else:
            stages.append(list(group))

    if not stages:
        stages = [[]]
    optional_priority = {"continuity": 0, "background": 1, "character_identity": 2, "prop_identity": 3, "reference_board": 5}
    unselected_optional: list[dict[str, Any]] = []
    for item in sorted(optional, key=lambda candidate: optional_priority.get(candidate["role"], 4)):
        placed = False
        for index, stage in enumerate(stages):
            capacity = MAX_INPUT_IMAGES if index == 0 and not anchor_input else MAX_INPUT_IMAGES - 1
            if len(stage) < capacity:
                stage.append(item)
                placed = True
                break
        if not placed:
            unselected_optional.append({**item, "reason": "required inputs consume all planned stage slots"})

    planned_stages: list[dict[str, Any]] = []
    for index, entries in enumerate(stages, start=1):
        stage_id = f"stage-{index}"
        inputs = list(entries)
        if index == 1 and anchor_input:
            inputs.insert(0, anchor_input)
            mode = "edit"
        elif index > 1:
            inputs.insert(0, {"role": "edit_target", "source": "previous_stage", "stage_id": f"stage-{index - 1}"})
            mode = "edit"
        else:
            mode = "generate"
        if len(inputs) > MAX_INPUT_IMAGES:
            raise KeyframeConsistencyError("阶段输入超过 5 张")
        planned_stages.append(
            {
                "stage_id": stage_id,
                "status": "planned",
                "mode": mode,
                "kind": _stage_kind(entries),
                "input_images": inputs,
                "allowed_changes": list(frame_spec.get("allowed_changes", [])),
                "invariants": list(frame_spec.get("invariants", [])),
            }
        )

    planned_required = {
        _candidate_key(entry)
        for stage in planned_stages
        for entry in stage["input_images"]
        if entry.get("role") != "edit_target"
    }
    board_covered_assets = {
        asset_id
        for stage in planned_stages
        for entry in stage["input_images"]
        if entry.get("role") == "reference_board"
        for asset_id in entry.get("covers_asset_ids", [])
    }
    missing = [
        item
        for item in required
        if _candidate_key(item) not in planned_required
        and item.get("asset_id") not in board_covered_assets
        and item.get("role") != "reference_board"
    ]
    if missing:
        raise KeyframeConsistencyError("required 输入未被分配到任何阶段")
    return {
        "plan_id": plan_id,
        "status": "planned",
        "generation_mode": "single_pass" if len(planned_stages) == 1 and not anchor_input else "staged_edit",
        "continuity_anchor": anchor_input,
        "stages": planned_stages,
        "unselected_optional": unselected_optional,
    }
