#!/usr/bin/env python3
"""Prepare a Codex-ready image dispatch that always includes existing assets.

This adapter never calls an image provider.  It only inspects project memory,
freezes a legal input set, and prints the files an agent must view_image before
any $imagegen call.  Text-only generation is refused once confirmed images exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from image_canon import (
    ImageCanonError,
    assert_reference_images_required,
    confirmed_image_assets,
    find_project_root,
    resolve_production_reference_images,
)
from project_files import (
    begin_stage_generation,
    current_keyframe_dispatch,
    current_keyframe_plan,
    normalize_asset_drafts,
    prepare_keyframe_generation,
)
from workflow_status import project_status


def _next_planned_stage(plan: dict[str, Any] | None, stage_id: str | None) -> dict[str, Any] | None:
    if not plan:
        return None
    for stage in plan.get("stages") or []:
        if stage.get("status") != "planned":
            continue
        if stage_id and stage.get("stage_id") != stage_id:
            continue
        return stage
    return None


def inspect_image_generation_context(project_root: Path | None = None) -> dict[str, Any]:
    """Summarize project memory that a new conversation must read before drawing."""
    root = find_project_root(project_root)
    confirmed = confirmed_image_assets(root)
    episodes: list[dict[str, str]] = []
    episode_root = root / "episodes"
    if episode_root.is_dir():
        for path in sorted(episode_root.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            state_path = path / "episode-state.json"
            episode_id = path.name.split("_", 1)[0]
            title = path.name.split("_", 1)[1] if "_" in path.name else path.name
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                episode_id = str(state.get("episode_id") or episode_id)
                title = str(state.get("episode_title") or title)
            manifest = path / "keyframe-execution-manifest.json"
            schema = None
            if manifest.is_file():
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                schema = payload.get("schema_version")
            episodes.append(
                {
                    "episode_id": episode_id,
                    "title": title,
                    "path": path.relative_to(root).as_posix(),
                    "keyframe_schema_version": schema,
                }
            )
    return {
        "project_root": str(root),
        "asset_index": "project-settings/asset-index.json",
        "character_bible": "project-settings/character-bible.md",
        "confirmed_asset_count": len(confirmed),
        "confirmed_assets": [
            {
                "asset_id": asset.get("asset_id"),
                "name": asset.get("name"),
                "kind": asset.get("kind"),
                "path": (asset.get("views") or [{}])[0].get("path") or asset.get("destination"),
            }
            for asset in confirmed
        ],
        "episodes": episodes,
        "rules": [
            "Do not call image_gen from text alone when confirmed_asset_count > 0.",
            "Run dispatch-keyframe or dispatch-asset and view_image every returned path first.",
            "Use the returned prompt verbatim; do not invent a new character design.",
            "Legacy keyframe packs without schema_version 2 cannot be used for generation.",
            "Run butler.py status to see the current episode stage and the next command.",
        ],
        "workflow": project_status(root),
    }


def dispatch_keyframe(
    project_root: Path,
    episode_id: str,
    shot_id: str,
    frame_kind: str,
    stage_id: str | None = None,
) -> dict[str, Any]:
    """Prepare and freeze one keyframe stage so Codex must attach the planned images."""
    root = Path(project_root).resolve()
    confirmed_count = len(confirmed_image_assets(root))
    existing = current_keyframe_dispatch(root, episode_id, shot_id, frame_kind, stage_id)
    if existing:
        dispatch = existing
    else:
        current_plan = current_keyframe_plan(root, episode_id, shot_id, frame_kind)
        next_stage = _next_planned_stage(current_plan, stage_id)
        if current_plan and next_stage:
            try:
                dispatch = begin_stage_generation(
                    root, episode_id, current_plan["plan_id"], next_stage["stage_id"]
                )
            except ValueError as error:
                raise ImageCanonError(str(error)) from error
        else:
            try:
                plan = prepare_keyframe_generation(root, episode_id, shot_id, frame_kind)
            except (FileNotFoundError, ValueError) as error:
                raise ImageCanonError(str(error)) from error
            if plan.get("status") == "waiting_for_dependency":
                return {
                    "allowed": False,
                    "kind": "keyframe",
                    "episode_id": episode_id,
                    "shot_id": str(shot_id),
                    "frame_kind": str(frame_kind),
                    "reason": "前序确认帧尚未完成，不能出图",
                    "input_images": [],
                    "view_image_paths": [],
                }
            if plan.get("status") == "reference_board_required":
                return {
                    "allowed": False,
                    "kind": "keyframe",
                    "episode_id": episode_id,
                    "shot_id": str(shot_id),
                    "frame_kind": str(frame_kind),
                    "reason": "不可拆关系组超过 5 图，需先确认参考板",
                    "input_images": [],
                    "view_image_paths": [],
                }
            next_stage = _next_planned_stage(plan, stage_id)
            generating = [
                stage
                for stage in plan.get("stages") or []
                if stage.get("status") == "generating" and stage.get("dispatch")
                and (not stage_id or stage.get("stage_id") == stage_id)
            ]
            if generating:
                dispatch = dict(generating[0]["dispatch"])
            elif not next_stage:
                raise ImageCanonError("当前关键帧没有可派发的阶段")
            else:
                try:
                    dispatch = begin_stage_generation(root, episode_id, plan["plan_id"], next_stage["stage_id"])
                except ValueError as error:
                    raise ImageCanonError(str(error)) from error
    assert_reference_images_required(dispatch.get("input_images") or [], confirmed_asset_count=confirmed_count)
    paths = [item["path"] for item in dispatch.get("input_images") or [] if item.get("path")]
    if not paths:
        raise ImageCanonError("关键帧阶段没有可传参考图，禁止出图")
    return {
        "allowed": True,
        "kind": "keyframe",
        "episode_id": episode_id,
        "shot_id": str(shot_id),
        "frame_kind": str(frame_kind),
        "plan_id": dispatch["plan_id"],
        "stage_id": dispatch["stage_id"],
        "dispatch_id": dispatch["dispatch_id"],
        "prompt": dispatch["prompt"],
        "input_images": dispatch["input_images"],
        "view_image_paths": paths,
        "codex_instructions": [
            "先对 view_image_paths 中的每一张图调用 view_image，把它们读进当前对话。",
            "再调用 image_gen；这些图分别作为人物身份 / 场景 / 道具 / 风格参考，不得只贴提示词。",
            "prompt 必须与本 dispatch 完全一致，不得改写外观或新增角色。",
            "生成后把结果放进项目目录，再用同一 dispatch_id 调用 record_stage_generation。",
        ],
    }


def dispatch_asset(
    project_root: Path,
    episode_id: str,
    name: str,
    kind: str | None = None,
    visual_brief: str = "",
) -> dict[str, Any]:
    """Build the required reference set for a new character, scene, or prop image."""
    root = Path(project_root).resolve()
    episode_dir = _episode_dir(root, episode_id)
    asset = _production_asset(episode_dir, name)
    asset_kind = kind or (asset or {}).get("kind") or _draft_kind(episode_dir, name)
    brief = visual_brief or (asset or {}).get("visual_brief") or ""
    if not asset_kind:
        raise ImageCanonError(
            f"无法确定素材类别：{name}。请补 --kind characters|scenes|props，"
            "或先用 butler.py new-episode / plan-assets 记录该资产类别"
        )
    references = resolve_production_reference_images(
        root,
        name=name,
        kind=str(asset_kind),
        visual_brief=str(brief),
    )
    confirmed_count = len(confirmed_image_assets(root))
    allow_first = confirmed_count == 0
    try:
        assert_reference_images_required(
            references,
            confirmed_asset_count=confirmed_count,
            allow_first_canon=allow_first,
        )
    except ImageCanonError:
        return {
            "allowed": False,
            "kind": "asset",
            "episode_id": episode_id,
            "name": name,
            "reason": "项目已有确认素材，但无法解析出可传参考图",
            "input_images": [],
            "view_image_paths": [],
        }
    paths = [item["path"] for item in references if item.get("path")]
    prompt = (asset or {}).get("prompt") or brief
    return {
        "allowed": True,
        "kind": "asset",
        "episode_id": episode_id,
        "name": name,
        "asset_kind": asset_kind,
        "prompt": prompt,
        "input_images": references,
        "view_image_paths": paths,
        "first_canon": not paths,
        "codex_instructions": (
            [
                "项目还没有确认图片，允许按角色圣经做第一批资产。",
                "生成后必须登记进素材索引，后续出图不得再纯文生图。",
            ]
            if not paths
            else [
                "先对 view_image_paths 中的每一张图调用 view_image。",
                "再调用 image_gen，把这些图作为风格 / 身份 / 场景参考。",
                "新角色必须继承参考图的体型、配色、材质和画风，不得另起一套外观。",
                "生成后先请用户确认，再登记为本集资产。",
            ]
        ),
    }


def _episode_dir(project_root: Path, episode_id: str) -> Path:
    matches = [
        path
        for path in (project_root / "episodes").glob(f"{episode_id}_*")
        if path.is_dir()
    ]
    if not matches:
        raise ImageCanonError(f"找不到剧集目录：{episode_id}")
    if len(matches) > 1:
        raise ImageCanonError(f"剧集 ID 不唯一：{episode_id}")
    return matches[0]


def _draft_kind(episode_dir: Path, name: str) -> str:
    """Fall back to the kind recorded when this episode first detected the name."""
    state_path = episode_dir / "episode-state.json"
    if not state_path.is_file():
        return ""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for draft in normalize_asset_drafts(state.get("new_asset_drafts", [])):
        if draft["name"] == name:
            return draft["kind"]
    return ""


def _production_asset(episode_dir: Path, name: str) -> dict[str, Any] | None:
    manifest_path = episode_dir / "asset-production-manifest.json"
    if not manifest_path.is_file():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for asset in payload.get("assets", []):
        if asset.get("name") == name:
            return asset
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, help="项目根目录；默认从当前目录向上查找")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect", help="读取项目记忆和已确认素材")
    keyframe = subparsers.add_parser("dispatch-keyframe", help="派发一帧并列出必传参考图")
    keyframe.add_argument("--episode", required=True)
    keyframe.add_argument("--shot", required=True)
    keyframe.add_argument("--frame", required=True, choices=("start", "middle", "end"))
    keyframe.add_argument("--stage")
    asset = subparsers.add_parser("dispatch-asset", help="为新角色/场景/道具列出必传参考图")
    asset.add_argument("--episode", required=True)
    asset.add_argument("--name", required=True)
    asset.add_argument("--kind")
    asset.add_argument("--visual-brief", default="")
    args = parser.parse_args()
    try:
        root = find_project_root(args.project_root)
        if args.command == "inspect":
            payload = inspect_image_generation_context(root)
        elif args.command == "dispatch-keyframe":
            payload = dispatch_keyframe(root, args.episode, args.shot, args.frame, args.stage)
        else:
            payload = dispatch_asset(root, args.episode, args.name, args.kind, args.visual_brief)
    except ImageCanonError as error:
        print(json.dumps({"allowed": False, "reason": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from error
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload.get("allowed", True):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
