#!/usr/bin/env python3
"""Compose still-image prompts from a confirmed director storyboard.

The storyboard is the default visual source.  User refinements append; they do
not replace identity, style, or time-of-day locks.  This module never calls an
image provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from keyframe_consistency import STRICT_TIME_OF_DAY, TIME_VIEW_ALIASES, infer_time_of_day
from validate_director_storyboard import parse_storyboard


NO_TEXT_LOCK = "无文字、字幕、Logo、水印、对话气泡。"
IDENTITY_LOCK = "外貌、服装以角色参考图为准，不得替换角色。"
BACKGROUND_LOCK = "场景参考图提供整体空间、光线和远景，当背景用，不要另造场地。"
SET_PROP_LOCK = (
    "场景母版里已经出现的固定物都按道具处理，各件保持母版中的形状和相对位置；"
    "禁止新增母版没有的固定物，也禁止把多件固定物糊成一块新结构。"
)
TIME_LOCKS = {
    "night": "背景时间为深夜，窗外为夜空，禁止白天、日出、日落、黄昏或橙色天空。",
    "dusk": "背景时间为黄昏，禁止改成白天或深夜。",
    "dawn": "背景时间为黎明，禁止改成白天或深夜。",
    "day": "背景时间为白天。",
}
FIELD_FROM_SHOT = {
    "start_state": "still_start",
    "end_state": "still_end",
    "motion": "motion",
    "dialogue": "dialogue",
    "voice_strategy": "voice_strategy",
    "sound_effects": "sound_effects",
    "transition_in": "transition_in",
    "transition_out": "transition_out",
    "camera_movement": "camera_movement",
}


def load_parsed_storyboard(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return parse_storyboard(path)


def storyboard_shot(parsed: dict[str, Any] | None, shot_id: str) -> dict[str, Any] | None:
    if not parsed:
        return None
    wanted = str(shot_id).zfill(2)
    for shot in parsed.get("shots") or []:
        if str(shot.get("shot_id", "")).zfill(2) == wanted:
            return shot
    return None


def _still_for_frame(shot: dict[str, Any], frame_kind: str) -> str:
    if frame_kind == "end":
        return str(shot.get("still_end") or shot.get("still_start") or "").strip()
    return str(shot.get("still_start") or "").strip()


def _asset_lock(names: Iterable[str]) -> str:
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    if not cleaned:
        return IDENTITY_LOCK
    return f"必须使用已确认资产：{'、'.join(cleaned)}。{IDENTITY_LOCK}"


def _time_lock(shot: dict[str, Any], frame_kind: str, extra_texts: Iterable[str]) -> str:
    still = _still_for_frame(shot, frame_kind)
    time_of_day = infer_time_of_day(
        shot.get("image_prompt"),
        still,
        shot.get("still_start"),
        shot.get("still_end"),
        *extra_texts,
    )
    if time_of_day not in TIME_LOCKS:
        return ""
    return TIME_LOCKS[time_of_day]


def _join_parts(parts: Iterable[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return " ".join(ordered)


def compose_still_prompt(
    parsed: dict[str, Any],
    shot: dict[str, Any],
    frame_kind: str,
    *,
    shot_size: str = "",
    camera_movement: str = "",
    asset_names: Iterable[str] | None = None,
    refinements: Iterable[str] | None = None,
    extra_texts: Iterable[str] | None = None,
) -> str:
    """Pack this still, visual locks, named assets, and user notes into one prompt."""
    still = _still_for_frame(shot, frame_kind)
    image_prompt = str(shot.get("image_prompt") or "").strip()
    names = list(asset_names) if asset_names is not None else list(shot.get("asset_names") or [])
    camera = str(camera_movement or shot.get("camera_movement") or "").strip()
    size = str(shot_size or "").strip()
    if frame_kind == "end":
        framing = "本帧按落幅构图。"
    elif frame_kind == "middle":
        framing = "本帧按动作中段构图。"
    else:
        framing = "本帧按起幅构图。"
    notes = [str(note).strip() for note in (refinements or []) if str(note).strip()]
    parts = [
        str(parsed.get("format") or "").strip(),
        f"本帧画面：{still}" if still else "",
        f"景别：{size}。" if size else "",
        f"运镜参考：{camera}，{framing}" if camera else framing,
        _asset_lock(names),
        BACKGROUND_LOCK,
        SET_PROP_LOCK,
        f"分镜视觉锁，姿势以本帧画面为准：{image_prompt}" if image_prompt else "",
        _time_lock(shot, frame_kind, extra_texts or ()),
        NO_TEXT_LOCK,
        f"用户精修：{'；'.join(notes)}" if notes else "",
    ]
    prompt = _join_parts(parts)
    if not prompt:
        raise ValueError("无法从分镜拼出关键帧提示词")
    return prompt


ROLE_LABELS = {
    "character_identity": "角色",
    "background": "场景",
    "prop_identity": "道具",
    "lighting": "光线",
    "composition": "构图",
    "style": "风格",
    "continuity_anchor": "连续性辅助",
    "continuity": "连续性辅助",
    "edit_target": "上一阶段",
}
FRAME_STORY_LABELS = {"start": "首帧", "middle": "过程帧", "end": "尾帧"}


def _brief_still(parsed_shot: dict[str, Any] | None, shot: dict[str, Any], frame_kind: str) -> str:
    source = parsed_shot or shot
    still = _still_for_frame(source, frame_kind)
    if still:
        return still
    if frame_kind == "end":
        return str(shot.get("end_state") or shot.get("start_state") or "").strip()
    return str(shot.get("start_state") or "").strip()


def _brief_asset_name(item: dict[str, Any], role: str) -> str:
    name = str(item.get("name") or item.get("reference") or "").strip()
    if name:
        return name
    if role in {"continuity_anchor", "continuity"}:
        return "上一镜辅助"
    if role == "edit_target":
        return "上一阶段画面"
    path = str(item.get("path") or "").strip()
    return Path(path).name if path else ""


def _brief_assets(shot: dict[str, Any], input_images: Iterable[dict[str, Any]] | None) -> list[dict[str, str]]:
    by_path: dict[str, dict[str, Any]] = {}
    catalog = list(shot.get("resolved_asset_uses") or []) or list(shot.get("asset_uses") or [])
    for item in catalog:
        path = str(item.get("path") or "").strip()
        if path:
            by_path[path] = item
    assets: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        role = str(item.get("role") or "")
        name = _brief_asset_name(item, role)
        if not name:
            return
        key = f"{name}|{item.get('path') or ''}"
        if key in seen:
            return
        seen.add(key)
        assets.append(
            {
                "name": name,
                "role": ROLE_LABELS.get(role, role or "参考"),
                "view": str(item.get("selected_view") or item.get("view_hint") or "").strip(),
                "path": str(item.get("path") or "").strip(),
            }
        )

    def merge(item: dict[str, Any]) -> dict[str, Any]:
        source = by_path.get(str(item.get("path") or "").strip()) or {}
        merged = dict(source)
        for key, value in item.items():
            if value not in (None, ""):
                merged[key] = value
        return merged

    if input_images:
        for item in input_images:
            add(merge(item))
        if assets:
            return assets
    for item in catalog:
        add(item)
    if assets:
        return assets
    for name in shot.get("asset_references") or []:
        if str(name).strip():
            add({"name": str(name).strip(), "role": "参考"})
    return assets


def build_frame_brief(
    parsed: dict[str, Any] | None,
    shot: dict[str, Any],
    frame_kind: str,
    *,
    input_images: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pre-generation memory card: this frame's story, masters, and must-watch notes."""
    parsed_shot = storyboard_shot(parsed, str(shot.get("shot_id") or ""))
    still = _brief_still(parsed_shot, shot, frame_kind)
    motion = str((parsed_shot or {}).get("motion") or shot.get("motion") or "").strip()
    dialogue = str((parsed_shot or {}).get("dialogue") or shot.get("dialogue") or "").strip()
    label = FRAME_STORY_LABELS.get(frame_kind, frame_kind)
    shot_id = str(shot.get("shot_id") or "").zfill(2)
    story_parts = [f"镜头 {shot_id} {label}。"]
    if still:
        story_parts.append(still)
    if motion:
        story_parts.append(f"动作：{motion}")
    if dialogue and dialogue not in {"无", "本镜无台词。", "本镜无台词", "本镜有对白。", "本镜有对白"}:
        story_parts.append(f"台词：{dialogue}")
    story = " ".join(story_parts).strip()
    assets = _brief_assets(shot, input_images)
    notes = shot.get("prompt_refinements") or {}
    extra = notes.get(frame_kind) if isinstance(notes, dict) else []
    if isinstance(extra, str):
        extra = [extra]
    must_watch = [
        IDENTITY_LOCK,
        BACKGROUND_LOCK,
        SET_PROP_LOCK,
        _time_lock(parsed_shot or shot, frame_kind, (shot.get("scene"), shot.get("start_state"), shot.get("end_state"))),
        "姿势和走位以本帧画面为准，不要用上一帧站位。",
        NO_TEXT_LOCK,
        f"用户精修：{'；'.join(str(note).strip() for note in extra if str(note).strip())}" if extra else "",
        "出图 prompt 必须与派发单完全一致。",
    ]
    must_watch = [item for item in must_watch if item]
    asset_lines = []
    for item in assets:
        detail = item["role"]
        if item["view"]:
            detail = f"{detail} / {item['view']}"
        line = f"- {item['name']}（{detail}）"
        if item["path"]:
            line += f"：{item['path']}"
        asset_lines.append(line)
    text = "\n".join(
        [
            "1. 本图故事",
            story or "（本帧缺少画面说明）",
            "",
            "2. 本镜引用素材",
            *(asset_lines or ["- （本帧未列出引用素材）"]),
            "",
            "3. 制作时必须注意",
            *[f"- {item}" for item in must_watch],
        ]
    )
    return {"story": story, "assets": assets, "must_watch": must_watch, "text": text}


def apply_storyboard_to_detail(
    parsed: dict[str, Any] | None,
    detail: dict[str, Any],
    planned_frames: list[str],
) -> dict[str, Any]:
    """Fill empty production fields and replace still prompts from the storyboard."""
    merged = dict(detail)
    shot = storyboard_shot(parsed, str(merged.get("shot_id", "")))
    if not parsed or not shot:
        return merged
    for field, source in FIELD_FROM_SHOT.items():
        if str(merged.get(field, "")).strip():
            continue
        value = str(shot.get(source) or "").strip()
        if field == "end_state" and not value:
            value = str(shot.get("still_start") or "").strip()
        if value:
            merged[field] = value
    if not str(merged.get("scene", "")).strip() and parsed.get("setting"):
        merged["scene"] = parsed["setting"]
    if shot.get("asset_names") and not merged.get("asset_references"):
        merged["asset_references"] = list(shot["asset_names"])
    merged["storyboard_image_prompt"] = shot["image_prompt"]
    refinements = merged.get("prompt_refinements") or {}
    if not isinstance(refinements, dict):
        refinements = {}
    composed: dict[str, str] = {}
    for frame_kind in planned_frames:
        notes = refinements.get(frame_kind) or []
        if isinstance(notes, str):
            notes = [notes]
        composed[frame_kind] = compose_still_prompt(
            parsed,
            shot,
            frame_kind,
            shot_size=str(merged.get("shot_size") or ""),
            camera_movement=str(merged.get("camera_movement") or ""),
            asset_names=merged.get("asset_references") or shot.get("asset_names") or [],
            refinements=notes,
            extra_texts=(merged.get("scene"), merged.get("start_state"), merged.get("end_state")),
        )
    merged["frame_prompts"] = composed
    merged["prompt_refinements"] = {
        frame: list(refinements.get(frame) or []) if not isinstance(refinements.get(frame), str) else [refinements[frame]]
        for frame in planned_frames
        if refinements.get(frame)
    }
    return merged


def compose_from_execution_shot(
    parsed: dict[str, Any] | None,
    shot: dict[str, Any],
    frame_kind: str,
    refinements: Iterable[str] | None = None,
) -> str | None:
    parsed_shot = storyboard_shot(parsed, str(shot.get("shot_id", "")))
    if not parsed or not parsed_shot:
        return None
    notes = list(refinements or [])
    stored = shot.get("prompt_refinements") or {}
    if isinstance(stored, dict):
        extra = stored.get(frame_kind) or []
        if isinstance(extra, str):
            extra = [extra]
        notes = list(extra) + notes
    return compose_still_prompt(
        parsed,
        parsed_shot,
        frame_kind,
        shot_size=str(shot.get("shot_size") or ""),
        camera_movement=str(shot.get("camera_movement") or ""),
        asset_names=shot.get("asset_references") or parsed_shot.get("asset_names") or [],
        refinements=notes,
        extra_texts=(shot.get("scene"), shot.get("start_state"), shot.get("end_state")),
    )


SHOT_SIZE_LABELS = ("大特写", "特写", "近中景", "中近景", "近景", "中景", "全景", "远景")
PLAN_STRATEGIES = {
    5: ("start_only", ["start"]),
    10: ("start_end", ["start", "end"]),
}


def infer_shot_size(camera: str) -> str:
    for label in SHOT_SIZE_LABELS:
        if label in (camera or ""):
            return label
    return (camera or "中景")[:20]


def default_keyframe_strategy(duration_seconds: int) -> tuple[str, list[str]]:
    if duration_seconds <= 5:
        return PLAN_STRATEGIES[5]
    if duration_seconds == 10:
        return PLAN_STRATEGIES[10]
    raise ValueError("默认导演版分镜只使用 5 秒、10 秒或最后不足 5 秒的余数")


def assert_storyboard_shots_complete(parsed: dict[str, Any]) -> None:
    """Fail at plan/execution time if a parsed shot cannot produce a still prompt."""
    errors: list[str] = []
    for shot in parsed.get("shots") or []:
        shot_id = shot.get("shot_id") or "（未编号）"
        duration = int(shot.get("duration_seconds") or 0)
        if not str(shot.get("image_prompt") or "").strip():
            errors.append(f"镜头 {shot_id} 缺少分镜出图提示词")
        if duration <= 5 and not str(shot.get("still_start") or "").strip():
            errors.append(f"镜头 {shot_id} 缺少关键帧画面")
        if duration == 10 and not str(shot.get("still_start") or "").strip():
            errors.append(f"镜头 {shot_id} 缺少首帧 A 画面")
        if duration == 10 and not str(shot.get("still_end") or "").strip():
            errors.append(f"镜头 {shot_id} 缺少尾帧 B 画面")
        if not list(shot.get("asset_names") or []):
            errors.append(f"镜头 {shot_id} 缺少素材参考")
    if errors:
        raise ValueError("；".join(errors))


def shots_from_storyboard(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the default keyframe plan from parsed director-board shots."""
    assert_storyboard_shots_complete(parsed)
    shots: list[dict[str, Any]] = []
    for item in parsed.get("shots") or []:
        duration = int(item["duration_seconds"])
        strategy, _frames = default_keyframe_strategy(duration)
        shots.append(
            {
                "shot_id": item["shot_id"],
                "duration_seconds": duration,
                "action": item.get("title") or item.get("still_start") or item["shot_id"],
                "strategy": strategy,
            }
        )
    if not shots:
        raise ValueError("分镜里没有可规划的镜头")
    return shots


def _index_matches(assets: list[dict[str, Any]], reference: str) -> list[dict[str, Any]]:
    return [
        asset
        for asset in assets
        if reference == asset.get("asset_id")
        or reference == asset.get("name")
        or reference in asset.get("aliases", [])
    ]


def asset_uses_from_names(project_root: Path, names: Iterable[str]) -> list[dict[str, Any]]:
    from image_canon import KIND_ROLE, load_asset_index

    assets = load_asset_index(project_root)
    uses: list[dict[str, Any]] = []
    for name in names:
        reference = str(name).strip()
        if not reference:
            continue
        matches = _index_matches(assets, reference)
        if not matches:
            raise ValueError(f"分镜素材参考未登记：{reference}")
        if len(matches) != 1:
            raise ValueError(f"分镜素材参考名称歧义：{reference}")
        role = KIND_ROLE.get(str(matches[0].get("kind") or ""))
        if role not in {"background", "character_identity", "prop_identity"}:
            raise ValueError(f"分镜素材参考类别无法用于出图：{reference}")
        uses.append({"reference": reference, "role": role, "required": True, "view_hint": "front"})
    if not uses:
        raise ValueError("分镜素材参考为空，无法建立出图输入")
    return uses


def missing_time_scene_views(project_root: Path, parsed: dict[str, Any] | None) -> list[dict[str, str]]:
    """Scenes that a night/dusk/dawn shot needs before keyframes can dispatch."""
    if not parsed:
        return []
    from image_canon import KIND_ROLE, load_asset_index

    assets = load_asset_index(project_root)
    missing: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for shot in parsed.get("shots") or []:
        time_of_day = infer_time_of_day(
            parsed.get("setting"),
            shot.get("image_prompt"),
            shot.get("still_start"),
            shot.get("still_end"),
            shot.get("camera_movement"),
        )
        if time_of_day not in STRICT_TIME_OF_DAY:
            continue
        aliases = set(TIME_VIEW_ALIASES[time_of_day])
        for name in shot.get("asset_names") or []:
            matches = _index_matches(assets, str(name).strip())
            if len(matches) != 1:
                continue
            asset = matches[0]
            if KIND_ROLE.get(str(asset.get("kind") or "")) != "background":
                continue
            views = {
                str(view.get("variant"))
                for view in asset.get("views") or []
                if view.get("variant") and view.get("path")
            }
            key = (str(asset.get("name") or name), time_of_day)
            if views & aliases or key in seen:
                continue
            seen.add(key)
            missing.append(
                {
                    "shot_id": str(shot["shot_id"]),
                    "name": key[0],
                    "time_of_day": time_of_day,
                    "needed_view": time_of_day,
                }
            )
    return missing


def _auto_frame_specs(frames: list[str]) -> dict[str, dict[str, Any]]:
    """Each still is generated from masters; do not chain pose from the previous frame."""
    return {
        frame: {
            "continuity_contract": None,
            "allowed_changes": [],
            "invariants": ["已确认资产身份", "场景结构", "时段"],
        }
        for frame in frames
    }


def details_from_storyboard(
    project_root: Path,
    parsed: dict[str, Any],
    planned_shots: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build execution-pack details from the director board; optional overrides win per field."""
    assert_storyboard_shots_complete(parsed)
    override_by_id = {str(item.get("shot_id", "")).zfill(2): item for item in overrides or []}
    details: list[dict[str, Any]] = []
    for planned in planned_shots:
        shot = storyboard_shot(parsed, str(planned["shot_id"]))
        if not shot:
            raise ValueError(f"分镜缺少镜头 {planned['shot_id']}，无法自动建立执行单")
        names = list(shot.get("asset_names") or [])
        camera = str(shot.get("camera_movement") or "")
        auto = {
            "shot_id": planned["shot_id"],
            "shot_size": infer_shot_size(camera),
            "camera_movement": camera or "按分镜运镜",
            "scene": str(parsed.get("setting") or ""),
            "asset_references": names,
            "asset_uses": asset_uses_from_names(project_root, names),
            "start_state": shot.get("still_start") or "",
            "motion": shot.get("motion") or "",
            "end_state": shot.get("still_end") or shot.get("still_start") or "",
            "dialogue": shot.get("dialogue") or "",
            "voice_strategy": shot.get("voice_strategy") or "",
            "sound_effects": shot.get("sound_effects") or "",
            "transition_in": shot.get("transition_in") or "",
            "transition_out": shot.get("transition_out") or "",
            "storyboard_image_prompt": shot.get("image_prompt") or "",
            "frame_specs": _auto_frame_specs(list(planned["frames"])),
        }
        override = dict(override_by_id.get(str(planned["shot_id"]).zfill(2)) or {})
        for key, value in override.items():
            if key in {"shot_id", "frame_prompts"}:
                continue
            if value in (None, "", [], {}):
                continue
            auto[key] = value
        if "prompt_refinements" in override:
            auto["prompt_refinements"] = override["prompt_refinements"]
        details.append(auto)
    return details

