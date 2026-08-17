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
MASTER_IDENTITY_ROLES = {"background", "character_identity", "prop_identity"}
CONTINUITY_DIMENSIONS = {"space", "character_identity", "prop_identity", "composition"}
SCOPE_PRIORITY = {"episode": 0, "continuity_run": 1, "shot": 2}
CHARACTER_VIEWS = ("front", "side", "back", "expression-sheet")
SCENE_VIEWS = ("front", "reverse", "side", "wide", "top", "day", "night", "dusk", "dawn")
TIME_OF_DAY = ("day", "night", "dusk", "dawn")
STRICT_TIME_OF_DAY = frozenset({"night", "dusk", "dawn"})
TIME_VIEW_ALIASES = {
    "night": ("night",),
    "dusk": ("dusk", "sunset"),
    "dawn": ("dawn", "sunrise"),
    "day": ("day", "front", "wide"),
}
TIME_KEYWORDS = (
    ("night", ("深夜", "夜里", "夜晚", "晚上", "半夜", "月夜", "夜空", "月光", "夜灯", "怕黑", "night", "moonlit")),
    ("dusk", ("黄昏", "傍晚", "日落", "dusk", "sunset")),
    ("dawn", ("黎明", "拂晓", "日出", "dawn", "sunrise")),
    ("day", ("白天", "日光", "阳光", "白昼", "daytime", "daylight")),
)
SCHEDULING_METADATA = ("relationship_group", "subject_tier", "priority", "continuity_relevant")
PHASE_NAMES = ("background", "primary_subjects", "secondary_subjects")


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


def infer_time_of_day(*texts: object) -> str | None:
    """Return a canonical time of day when the storyboard text is explicit."""
    blob = " ".join(str(text or "") for text in texts)
    if not blob.strip():
        return None
    for time_of_day, keywords in TIME_KEYWORDS:
        if any(keyword in blob for keyword in keywords):
            return time_of_day
    return None


def shot_time_of_day(shot: dict[str, Any], frame_spec: dict[str, Any] | None = None) -> str | None:
    """Prefer an explicit shot field, then infer from scene and prompts."""
    explicit = shot.get("time_of_day")
    if explicit in TIME_OF_DAY:
        return str(explicit)
    prompts = shot.get("frame_prompts") or {}
    return infer_time_of_day(
        shot.get("scene"),
        shot.get("storyboard_image_prompt"),
        shot.get("start_state"),
        shot.get("motion"),
        shot.get("end_state"),
        *(prompts.values() if isinstance(prompts, dict) else ()),
        (frame_spec or {}).get("prompt"),
    )


def apply_background_time_views(
    asset_uses: list[dict[str, Any]], time_of_day: str | None
) -> list[dict[str, Any]]:
    """Pin background plates to the shot's time of day without inventing camera views."""
    if time_of_day not in TIME_OF_DAY:
        return [dict(item) for item in asset_uses]
    applied: list[dict[str, Any]] = []
    for item in asset_uses:
        copied = dict(item)
        if copied.get("role") == "background":
            copied["time_of_day"] = time_of_day
            copied["view_hint"] = time_of_day
        applied.append(copied)
    return applied


def background_time_mismatch(
    shot: dict[str, Any],
    input_images: list[dict[str, Any]] | None,
    frame_spec: dict[str, Any] | None = None,
) -> str | None:
    """Return a stop reason when a night/dusk/dawn shot is locked to a daytime plate."""
    time_of_day = shot_time_of_day(shot, frame_spec)
    if time_of_day not in STRICT_TIME_OF_DAY:
        return None
    aliases = TIME_VIEW_ALIASES[time_of_day]
    for item in input_images or []:
        if item.get("role") != "background":
            continue
        selected = str(item.get("selected_view") or "")
        path = str(item.get("path") or "")
        stem = Path(path).stem.lower()
        if selected in aliases or stem in aliases or any(stem.endswith(f"-{alias}") for alias in aliases):
            continue
        name = item.get("name") or item.get("asset_id") or "场景"
        return (
            f"场景「{name}」当前视图是 {selected or stem or '未标注'}，本镜需要 {time_of_day}。"
            f"请先 dispatch-asset 补 {time_of_day}=<对应时段场景图> 并 confirm-asset，不要用白天母版出夜戏。"
        )
    return None


def _select_view(
    asset: dict[str, Any], requested: str | None, *, required_variants: tuple[str, ...] | None = None
) -> tuple[dict[str, Any], str | None]:
    views = {view.get("variant"): view for view in asset.get("views", []) if view.get("variant") and view.get("path")}
    if not views and asset.get("destination"):
        views = {"reference": {"variant": "reference", "path": asset["destination"]}}
    order = required_variants or _view_order(asset, requested)
    for variant in order:
        view = views.get(variant)
        if not view:
            continue
        if required_variants:
            return view, None
        if requested and variant != requested:
            return view, f"requested view '{requested}' unavailable; fell back to '{variant}'"
        return view, None
    if required_variants:
        name = asset.get("name") or asset.get("asset_id") or "unknown"
        wanted = requested or required_variants[0]
        raise KeyframeConsistencyError(
            f"场景「{name}」没有已确认的 {wanted} 视图，不能出该时段关键帧。"
            f"请先 dispatch-asset 补 {wanted}=<夜晚或对应时段场景图> 并 confirm-asset。"
        )
    fallback = next(iter(views.values()), None)
    if fallback:
        reason = f"standard views unavailable; fell back to '{fallback['variant']}'"
        if requested:
            reason = f"requested view '{requested}' unavailable; {reason}"
        return fallback, reason
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
        time_of_day = asset_use.get("time_of_day") if asset_use.get("time_of_day") in TIME_OF_DAY else None
        if role == "background" and time_of_day:
            requested = time_of_day
        required_variants = TIME_VIEW_ALIASES.get(str(requested)) if requested in TIME_OF_DAY else None
        if required_variants and requested not in STRICT_TIME_OF_DAY:
            # Daytime plates may be registered as front/wide; still prefer an explicit day view.
            available = {view.get("variant") for view in asset.get("views", []) if view.get("variant") and view.get("path")}
            if not available and asset.get("destination"):
                available = {"reference"}
            required_variants = tuple(variant for variant in required_variants if variant in available) or None
        view, fallback_reason = _select_view(asset, requested, required_variants=required_variants)
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
            raise KeyframeConsistencyError(f"用户覆盖目标不适用于镜头素材：{target}")
        scope = override.get("scope")
        if scope not in SCOPE_PRIORITY:
            raise KeyframeConsistencyError(f"用户覆盖 scope 不合法：{scope}")
        scope_ids = override.get("scope_ids", [])
        if not isinstance(scope_ids, list):
            raise KeyframeConsistencyError("用户覆盖 scope_ids 必须是列表")
        if scope != "episode" and not scope_ids:
            raise KeyframeConsistencyError("用户覆盖非 episode scope_ids 不能为空")
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
    for field in SCHEDULING_METADATA:
        if item.get(field) is not None:
            result[field] = item[field]
    return result


def _input_from_override(item: dict[str, Any], replaced: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a required override input while preserving replaced scheduling facts."""
    result = {
        "role": item["role"],
        "path": item["path"],
        "sha256": item["sha256"],
        "override_id": item["override_id"],
        "required": True,
    }
    if item.get("target_asset_id"):
        result["asset_id"] = item["target_asset_id"]
    if replaced:
        for field in SCHEDULING_METADATA:
            if replaced.get(field) is not None:
                result[field] = replaced[field]
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


def _candidate_phase(item: dict[str, Any]) -> int:
    """Return the prescribed generation phase for an input."""
    explicit_phase = item.get("schedule_phase")
    if explicit_phase is not None:
        return int(explicit_phase)
    role = item["role"]
    if role in {"background", "lighting", "composition", "style"}:
        return 0
    if item.get("subject_tier") == "primary":
        return 1
    if role == "character_identity" and item.get("subject_tier") != "secondary":
        return 1
    return 2


def _candidate_sort_key(item: dict[str, Any]) -> tuple[int, str, str, str]:
    return (
        _candidate_phase(item),
        item["role"],
        str(item.get("asset_id") or ""),
        str(item.get("override_id") or ""),
    )


def _group_phase(group: list[dict[str, Any]]) -> int:
    return min(_candidate_phase(item) for item in group)


def _group_sort_key(group: list[dict[str, Any]]) -> tuple[int, tuple[int, str, str, str]]:
    return (_group_phase(group), min(_candidate_sort_key(item) for item in group))


def _stage_kind(entries: list[dict[str, Any]]) -> str:
    content_entries = [item for item in entries if item.get("role") not in {"continuity", "edit_target"}]
    if not content_entries:
        return "background"
    phases = {_candidate_phase(item) for item in content_entries}
    if phases == {0}:
        return "background"
    if 0 in phases and phases - {0}:
        return "composite"
    return PHASE_NAMES[min(phases)]


LIGHTING_LOCK = (
    "时间、光线和窗外氛围以场景母版和本帧提示词为准，不得改成另一种时段。"
)
EMPTY_BACKGROUND_LOCK = (
    "当前阶段仅生成场景空间与灯光底图，不生成任何人物、动物、角色或其他前景主体。"
)
QA_GUIDANCE = (
    "质检只锁身份、空间和时段；分镜要求的走位、姿势、视线变化必须通过，"
    "不得用上一帧站位否决本帧动作。"
)


def _stage_prompt(frame_prompt: str, stage_kind: str) -> str:
    """Keep lighting on every stage; only empty overflow plates omit subjects."""
    prompt = str(frame_prompt or "").strip()
    suffix = LIGHTING_LOCK
    if stage_kind == "background":
        suffix = f"{LIGHTING_LOCK}{EMPTY_BACKGROUND_LOCK}"
    if not prompt:
        return suffix
    return f"{prompt} {suffix}"


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
        "role": "continuity",
        "path": anchor["path"],
        "sha256": anchor["sha256"],
        "revision": anchor["revision"],
        "source": "continuity_anchor",
        "shot_id": anchor["shot_id"],
        "frame_kind": anchor["frame_kind"],
        "required": False,
    }


def _has_subject_identity(entries: list[dict[str, Any]]) -> bool:
    """Return whether a stage has a subject master that can safely use a prior frame."""
    return any(item.get("role") in {"character_identity", "prop_identity", "reference_board"} for item in entries)


def _has_master_lock(entries: list[dict[str, Any]]) -> bool:
    return any(item.get("role") in MASTER_IDENTITY_ROLES or item.get("role") == "reference_board" for item in entries)


def _attach_previous_shot_auxiliary(
    stages: list[list[dict[str, Any]]],
    anchor_input: dict[str, Any] | None,
    unselected_optional: list[dict[str, Any]],
) -> None:
    """Keep previous-shot frames optional.  Never let them evict a required master."""
    if not anchor_input:
        return
    first = stages[0] if stages else None
    all_entries = [item for stage in stages for item in stage]
    shot_has_subjects = _has_subject_identity(all_entries)
    first_is_empty_plate = first is not None and not _has_subject_identity(first)
    if first is not None and shot_has_subjects and first_is_empty_plate:
        unselected_optional.append(
            {**anchor_input, "reason": "previous shot cannot be the only or primary identity reference"}
        )
        return
    if first is not None and _has_master_lock(first) and len(first) < MAX_INPUT_IMAGES:
        first.append(anchor_input)
        return
    if first is not None and _has_master_lock(first):
        reason = "previous-shot auxiliary dropped to keep required masters under 5-image cap"
    else:
        reason = "previous shot cannot be the only or primary identity reference"
    unselected_optional.append({**anchor_input, "reason": reason})


def build_generation_plan(
    plan_id: str,
    frame_spec: dict[str, Any],
    resolved_uses: list[dict[str, Any]],
    applicable_overrides: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
    confirmed_anchor: dict[str, Any] | None,
    approved_boards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic required-first plan without side effects.

    A generate stage can take five references.  Required masters that fit in
    those five share one generate stage even when they belong to different
    phases, unless the frame explicitly requests ``force_staged_edit`` to
    protect a confirmed scene from subject-driven redraw.  Confirmed
    previous-shot frames are optional continuity auxiliaries: they never
    replace required character, scene, or prop masters, and they are dropped
    before any required master when the 5-image cap is full.  Later stages
    reserve one slot for previous_stage edit_target.  Relationship groups are
    atomic; an oversized group returns the explicit
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
        if override.get("target_asset_id"):
            target_key = (str(override["target_asset_id"]), str(override["role"]))
            replaced = [item for item in candidates if _candidate_key(item) == target_key]
            override_input = _input_from_override(override, replaced[0] if replaced else None)
            candidates = [item for item in candidates if _candidate_key(item) != target_key]
        else:
            # A dimension-wide override (for example a user beach background)
            # replaces only that dimension's default anchors, never identities
            # or geometry represented by other roles.
            override_input = _input_from_override(override)
            candidates = [item for item in candidates if item.get("role") != override["role"]]
        candidates.append(override_input)

    for item in candidates:
        if item.get("required") and not item.get("path"):
            raise KeyframeConsistencyError("required 输入缺少路径")
        if item.get("required") and not item.get("sha256"):
            raise KeyframeConsistencyError("required 输入缺少 sha256")
    required = [item for item in candidates if item.get("required")]
    optional = [item for item in candidates if not item.get("required")]

    groups = [sorted(group, key=_candidate_sort_key) for group in _group_candidates(required)]
    groups.sort(key=_group_sort_key)
    normalized_groups: list[list[dict[str, Any]]] = []
    for group in groups:
        # A contact/holding relationship is indivisible.  Its earliest phase
        # governs every member so it cannot be split merely because one member
        # is otherwise classified as secondary.
        group_phase = _group_phase(group)
        group = [{**item, "schedule_phase": group_phase} for item in group]
        relationship_group = group[0].get("relationship_group")
        capacity = MAX_INPUT_IMAGES if not normalized_groups else MAX_INPUT_IMAGES - 1
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
                        "schedule_phase": group_phase,
                        "required": True,
                    }
                ]
            )
        else:
            normalized_groups.append(group)

    stages: list[list[dict[str, Any]]] = []
    stage_phases: list[int] = []
    for group in normalized_groups:
        group_phase = _group_phase(group)
        if stages:
            previous_phases = {_candidate_phase(item) for item in stages[-1]}
            if frame_spec.get("force_staged_edit") is True and 0 in previous_phases and group_phase > 0:
                stages.append(list(group))
                stage_phases.append(group_phase)
                continue
            capacity = MAX_INPUT_IMAGES if len(stages) == 1 else MAX_INPUT_IMAGES - 1
            if len(stages[-1]) + len(group) <= capacity:
                stages[-1].extend(group)
                continue
        stages.append(list(group))
        stage_phases.append(group_phase)

    if not stages:
        stages = [[]]
        stage_phases = [0]
    optional_priority = {"continuity": 0, "background": 1, "character_identity": 2, "prop_identity": 3, "reference_board": 5}
    unselected_optional: list[dict[str, Any]] = []
    for item in sorted(optional, key=lambda candidate: (_candidate_phase(candidate), optional_priority.get(candidate["role"], 4))):
        placed = False
        for index, stage in enumerate(stages):
            if stage_phases[index] != _candidate_phase(item):
                continue
            capacity = MAX_INPUT_IMAGES if index == 0 else MAX_INPUT_IMAGES - 1
            if len(stage) < capacity:
                stage.append(item)
                placed = True
                break
        if not placed:
            unselected_optional.append({**item, "reason": "required inputs consume all planned stage slots"})

    _attach_previous_shot_auxiliary(stages, anchor_input, unselected_optional)

    planned_stages: list[dict[str, Any]] = []
    for index, entries in enumerate(stages, start=1):
        stage_id = f"stage-{index}"
        inputs = list(entries)
        if index > 1:
            inputs.insert(0, {"role": "edit_target", "source": "previous_stage", "stage_id": f"stage-{index - 1}"})
            mode = "edit"
        else:
            mode = "generate"
        if len(inputs) > MAX_INPUT_IMAGES:
            raise KeyframeConsistencyError("阶段输入超过 5 张")
        required_qa_categories: set[str] = set()
        roles = {item.get("role") for item in inputs}
        if roles & {"background", "lighting", "composition", "style"}:
            required_qa_categories.add("scene")
        if "character_identity" in roles or "reference_board" in roles:
            required_qa_categories.add("character")
        if "prop_identity" in roles:
            required_qa_categories.add("prop")
        # Intra-frame edit_target must not drift identity. A previous-shot
        # continuity still image is auxiliary blocking, not a pose lock, so it
        # does not create a required continuity QA gate.
        if "edit_target" in roles:
            required_qa_categories.add("continuity")
        planned_stages.append(
            {
                "stage_id": stage_id,
                "status": "planned",
                "mode": mode,
                "kind": _stage_kind(entries),
                "input_images": inputs,
                # Each stage prompt is immutable once dispatched. Lighting
                # follows the scene master and frame prompt on every stage;
                # only overflow background plates omit subjects.
                "prompt": _stage_prompt(frame_spec.get("prompt", ""), _stage_kind(entries)),
                "allowed_changes": list(frame_spec.get("allowed_changes", [])),
                "invariants": list(frame_spec.get("invariants", [])),
                "required_qa_categories": sorted(required_qa_categories),
                "qa_guidance": QA_GUIDANCE,
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
        "generation_mode": (
            "single_pass"
            if len(planned_stages) == 1 and planned_stages[0]["mode"] == "generate"
            else "staged_edit"
        ),
        "force_staged_edit": frame_spec.get("force_staged_edit") is True,
        "continuity_anchor": anchor_input,
        "stages": planned_stages,
        "unselected_optional": unselected_optional,
    }


def is_obsolete_phase_split_plan(plan: dict[str, Any] | None) -> bool:
    """Return whether an old background-then-character plan should be rebuilt."""
    if not plan or plan.get("force_staged_edit") is True:
        return False
    stages = plan.get("stages") or []
    if len(stages) < 2 or (stages[0] or {}).get("kind") != "background":
        return False
    later = [(stage or {}).get("kind") for stage in stages[1:]]
    if not any(kind in {"primary_subjects", "secondary_subjects", "composite"} for kind in later):
        return False
    master_ids = {
        item.get("asset_id")
        for stage in stages
        for item in stage.get("input_images") or []
        if item.get("role") in MASTER_IDENTITY_ROLES and item.get("asset_id")
    }
    return 0 < len(master_ids) <= MAX_INPUT_IMAGES
