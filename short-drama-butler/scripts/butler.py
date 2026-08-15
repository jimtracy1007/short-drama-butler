#!/usr/bin/env python3
"""One command line for the whole short-drama workflow.

Every user confirmation gate lives in ``project_files.py``, but an agent will
only route through a gate if calling it is easier than bypassing it.  This CLI
exists so no step ever requires ad-hoc Python, and so ``status`` can always
answer "what do I run next".  It calls no image, video, or editing provider.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from codex_image_dispatch import (
    dispatch_asset,
    dispatch_keyframe,
    inspect_image_generation_context,
)
from image_canon import ImageCanonError, find_project_root
from project_files import (
    approve_keyframe_plan,
    approve_story_outline,
    confirm_episode_asset,
    create_asset_production_plan,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    initialize_project,
    provide_episode_asset_images,
    record_episode_continuity,
    record_script_and_storyboard_approval,
    record_stage_generation,
    record_stage_qa,
    register_user_override,
    request_keyframe_regeneration,
    record_story_outline,
    decide_reuse_asset,
)
from workflow_status import episode_status, list_episodes, project_status, propose_story_context


class ButlerError(RuntimeError):
    """Raised for user-facing CLI misuse."""


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_asset_argument(value: str) -> dict[str, str]:
    """Parse ``名称`` / ``名称:kind`` / ``名称:kind:视觉说明``."""
    parts = value.split(":", 2)
    entry = {"name": parts[0].strip()}
    if not entry["name"]:
        raise ButlerError(f"资产名称不能为空：{value!r}")
    if len(parts) > 1 and parts[1].strip():
        entry["kind"] = parts[1].strip()
    if len(parts) > 2 and parts[2].strip():
        entry["visual_brief"] = parts[2].strip()
    return entry


def _parse_image_argument(values: list[str]) -> dict[str, Path]:
    images: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ButlerError(f"图片参数格式应为 变体=路径，例如 front=out/bird.png：{value!r}")
        variant, path = value.split("=", 1)
        variant, path = variant.strip(), path.strip()
        if not variant or not path:
            raise ButlerError(f"图片参数缺少变体或路径：{value!r}")
        images[variant] = Path(path)
    if not images:
        raise ButlerError("至少需要一张图片")
    return images


def _parse_check_argument(values: list[str]) -> list[dict[str, Any]]:
    """Parse ``category=status:confidence`` QA checks."""
    checks: list[dict[str, Any]] = []
    for value in values:
        if "=" not in value:
            raise ButlerError(f"质检项格式应为 类别=状态:置信度，例如 scene=pass:0.9：{value!r}")
        category, remainder = value.split("=", 1)
        status, _, confidence = remainder.partition(":")
        try:
            confidence_value = float(confidence) if confidence else 1.0
        except ValueError as error:
            raise ButlerError(f"质检置信度必须是数字：{value!r}") from error
        checks.append(
            {
                "category": category.strip(),
                "status": status.strip(),
                "confidence": confidence_value,
                "evidence_paths": [],
            }
        )
    if not checks:
        raise ButlerError("至少需要一项质检结果")
    return checks


def _load_json_file(path: Path) -> Any:
    if not path.is_file():
        raise ButlerError(f"找不到 JSON 文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ButlerError(f"JSON 格式不合法：{path}（{error}）") from error


def _find_dispatch(root: Path, episode_id: str, dispatch_id: str) -> dict[str, Any]:
    """Locate a frozen dispatch so the caller only needs its dispatch_id."""
    matches = [path for path in (root / "episodes").glob(f"{episode_id}_*") if path.is_dir()]
    if not matches:
        raise ButlerError(f"找不到剧集目录：{episode_id}")
    manifest_path = matches[0] / "keyframe-execution-manifest.json"
    if not manifest_path.is_file():
        raise ButlerError("本集还没有关键帧执行单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for shot in manifest.get("shots", []):
        for frame in shot.get("frames", []):
            for plan in frame.get("plans", []):
                for stage in plan.get("stages", []):
                    for dispatch in stage.get("dispatches", []):
                        if dispatch.get("dispatch_id") == dispatch_id:
                            return dispatch
    raise ButlerError(f"执行单中找不到派发记录：{dispatch_id}")


def _command_status(root: Path, args: argparse.Namespace) -> Any:
    if args.episode:
        return episode_status(root, args.episode)
    return project_status(root)


def _command_propose_story(root: Path, args: argparse.Namespace) -> Any:
    return propose_story_context(root)


def _command_init(root: Path, args: argparse.Namespace) -> Any:
    initialize_project(
        args.project_root or Path.cwd(),
        args.name,
        Path(args.source_document) if args.source_document else None,
        audience=args.audience,
        frame_format=args.format,
        episode_target_seconds=args.seconds,
        content_guidelines=args.content_guidelines,
        storyboard_skill=args.storyboard_skill,
    )
    target = (args.project_root or Path.cwd()).resolve()
    return {"initialized": str(target), "next": "butler.py new-episode --story <用户原话>"}


def _next_episode_id(root: Path) -> str:
    numbers = []
    for episode in list_episodes(root):
        match = re.match(r"EP(\d+)$", str(episode.get("episode_id", "")), re.I)
        if match:
            numbers.append(int(match.group(1)))
    return f"EP{max(numbers, default=0) + 1:03d}"


def _title_from_story(story: str) -> str:
    first = re.split(r"[。！？\n]", str(story).strip())[0]
    first = re.sub(r"[，、\s]+$", "", first).strip()
    return first[:16] or "新的一集"


def _command_new_episode(root: Path, args: argparse.Namespace) -> Any:
    references = [_parse_asset_argument(value) for value in args.asset or []]
    episode_id = args.episode or _next_episode_id(root)
    title = args.title or _title_from_story(args.story)
    package = create_episode(
        root,
        episode_id,
        title,
        args.story,
        references,
        episode_overrides=_load_json_file(Path(args.overrides_file)) if args.overrides_file else None,
        standalone=args.standalone,
    )
    status = episode_status(root, episode_id)
    return {
        "storyboard_package": package.relative_to(root).as_posix(),
        "user_notice": status.get("user_notice") or "",
        "status": status,
    }


def _command_plan_assets(root: Path, args: argparse.Namespace) -> Any:
    requests = []
    for value in args.new or []:
        entry = _parse_asset_argument(value)
        if not entry.get("kind"):
            raise ButlerError(f"资产 {entry['name']} 缺少类别；格式为 名称:characters|scenes|props:视觉说明")
        if not entry.get("visual_brief"):
            raise ButlerError(f"资产 {entry['name']} 缺少视觉说明；格式为 名称:类别:视觉说明")
        requests.append(entry)
    if args.requests_file:
        requests.extend(_load_json_file(Path(args.requests_file)))
    plan = create_asset_production_plan(root, args.episode, requests)
    return {
        "asset_production_plan": plan.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_provide_asset(root: Path, args: argparse.Namespace) -> Any:
    manifest = provide_episode_asset_images(
        root, args.episode, args.name, _parse_image_argument(args.image)
    )
    return {
        "manifest": manifest.relative_to(root).as_posix(),
        "next": f"用户确认后：butler.py confirm-asset --episode {args.episode} --name {args.name}",
    }


def _command_confirm_asset(root: Path, args: argparse.Namespace) -> Any:
    registered = confirm_episode_asset(
        root, args.episode, args.name, aliases=args.alias, scope=args.scope
    )
    return {"registered": registered, "status": episode_status(root, args.episode)}


def _command_reuse_asset(root: Path, args: argparse.Namespace) -> Any:
    decision = decide_reuse_asset(root, args.episode, args.name, args.action)
    return {**decision, "status": episode_status(root, args.episode)}


def _command_record_story_outline(root: Path, args: argparse.Namespace) -> Any:
    source = Path(args.file)
    if not source.is_file():
        raise ButlerError(f"找不到 AI 生成的故事概要文件：{source}")
    path = record_story_outline(root, args.episode, source.read_text(encoding="utf-8"))
    return {
        "story_outline": path.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_approve_story(root: Path, args: argparse.Namespace) -> Any:
    path = approve_story_outline(root, args.episode)
    return {
        "story_outline": path.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_approve_script(root: Path, args: argparse.Namespace) -> Any:
    review = record_script_and_storyboard_approval(root, args.episode)
    return {
        "creative_review": review.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_plan_keyframes(root: Path, args: argparse.Namespace) -> Any:
    shots = _load_json_file(Path(args.shots_file))
    plan = create_keyframe_plan(root, args.episode, shots)
    return {
        "keyframe_plan": plan.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_approve_keyframes(root: Path, args: argparse.Namespace) -> Any:
    manifest = approve_keyframe_plan(
        root, args.episode, approved_middle_shot_ids=args.middle_shot or None
    )
    return {
        "keyframe_manifest": manifest.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_create_execution(root: Path, args: argparse.Namespace) -> Any:
    details = _load_json_file(Path(args.details_file))
    execution = create_keyframe_execution_pack(root, args.episode, details)
    return {
        "keyframe_execution": execution.relative_to(root).as_posix(),
        "status": episode_status(root, args.episode),
    }


def _command_record_image(root: Path, args: argparse.Namespace) -> Any:
    dispatch = _find_dispatch(root, args.episode, args.dispatch)
    result = record_stage_generation(
        root,
        args.episode,
        dispatch["plan_id"],
        dispatch["stage_id"],
        {
            "plan_id": dispatch["plan_id"],
            "stage_id": dispatch["stage_id"],
            "dispatch_id": dispatch["dispatch_id"],
            "tool_request_id": args.tool_request_id or dispatch["dispatch_id"],
            "prompt": dispatch["prompt"],
            "input_images": dispatch["input_images"],
            "output_path": args.output,
            "started_at": args.started_at or dispatch["dispatched_at"],
            "completed_at": args.completed_at or dispatch["dispatched_at"],
        },
    )
    return {
        "work_revision": result,
        "next": f"butler.py record-qa --episode {args.episode} --dispatch {args.dispatch} --status pass --check scene=pass:0.9",
    }


def _command_record_qa(root: Path, args: argparse.Namespace) -> Any:
    dispatch = _find_dispatch(root, args.episode, args.dispatch)
    stage = record_stage_qa(
        root,
        args.episode,
        dispatch["plan_id"],
        dispatch["stage_id"],
        {
            "status": args.status,
            "reviewer_type": args.reviewer,
            "checked_at": args.checked_at or dispatch["dispatched_at"],
            "checks": _parse_check_argument(args.check),
            "issues": [args.issue] if args.issue else [],
        },
    )
    return {"stage_status": stage.get("status"), "status": episode_status(root, args.episode)}


def _command_redo_keyframe(root: Path, args: argparse.Namespace) -> Any:
    return request_keyframe_regeneration(root, args.episode, args.shot, args.frame, args.reason)


def _command_register_override(root: Path, args: argparse.Namespace) -> Any:
    override: dict[str, Any] = {
        "path": args.path,
        "role": args.role,
        "scope": args.scope,
        "scope_ids": args.scope_id or [],
    }
    if args.target_asset_id:
        override["target_asset_id"] = args.target_asset_id
    return register_user_override(root, args.episode, override)


def _command_record_continuity(root: Path, args: argparse.Namespace) -> Any:
    path = record_episode_continuity(
        root,
        args.episode,
        events=args.event or [],
        character_states=args.character_state or [],
        ending_frame=args.ending_frame,
        unresolved_threads=args.open_thread or [],
        next_episode_constraints=args.next_requirement or [],
    )
    return {"episode_continuity": path.relative_to(root).as_posix()}


def _command_inspect(root: Path, args: argparse.Namespace) -> Any:
    return inspect_image_generation_context(root)


def _command_dispatch_asset(root: Path, args: argparse.Namespace) -> Any:
    return dispatch_asset(root, args.episode, args.name, args.kind, args.visual_brief)


def _command_dispatch_keyframe(root: Path, args: argparse.Namespace) -> Any:
    return dispatch_keyframe(root, args.episode, args.shot, args.frame, args.stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="butler.py", description=__doc__)
    parser.add_argument("--project-root", type=Path, help="项目根目录；默认从当前目录向上查找")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="当前进度与下一步该运行什么")
    status.add_argument("--episode")
    status.set_defaults(func=_command_status, needs_project=False)

    propose = subparsers.add_parser("propose-story", help="用户没故事时，先打包已有角色和上集承接")
    propose.set_defaults(func=_command_propose_story)

    init = subparsers.add_parser("init", help="初始化项目记忆")
    init.add_argument("--name", required=True)
    init.add_argument("--audience", default="")
    init.add_argument("--format", default="")
    init.add_argument("--seconds", type=int)
    init.add_argument("--content-guidelines", default="")
    init.add_argument("--storyboard-skill", default="")
    init.add_argument("--source-document")
    init.set_defaults(func=_command_init, needs_project=False)

    episode = subparsers.add_parser("new-episode", help="建立一集，并检测新角色/场景/道具")
    episode.add_argument("--episode", help="缺省时自动使用下一集编号，例如 EP001")
    episode.add_argument("--title", help="缺省时从故事里取一句短标题")
    episode.add_argument("--story", required=True, help="用户的原话；不要改写成命令参数")
    episode.add_argument(
        "--asset",
        action="append",
        help="仅供内部补漏；用户说话时不要问这项。故事里提到的名称会自动识别。",
    )
    episode.add_argument("--overrides-file")
    episode.add_argument("--standalone", action="store_true")
    episode.set_defaults(func=_command_new_episode)

    plan_assets = subparsers.add_parser("plan-assets", help="大纲确认后建立资产生产单")
    plan_assets.add_argument("--episode", required=True)
    plan_assets.add_argument("--new", action="append", help="一般不用。用户确认后直接 plan-assets --episode 即可，会用故事里已检出的草案。")
    plan_assets.add_argument("--requests-file")
    plan_assets.set_defaults(func=_command_plan_assets)

    provide = subparsers.add_parser("provide-asset", help="登记已生成的素材图片路径")
    provide.add_argument("--episode", required=True)
    provide.add_argument("--name", required=True)
    provide.add_argument("--image", action="append", required=True, help="变体=路径，例如 front=out/bird.png")
    provide.set_defaults(func=_command_provide_asset)

    confirm = subparsers.add_parser("confirm-asset", help="用户确认后归档并登记素材")
    confirm.add_argument("--episode", required=True)
    confirm.add_argument("--name", required=True)
    confirm.add_argument("--alias", action="append")
    confirm.add_argument("--scope", help="默认 episode-<ID>；确认可复用时才写 global 或 season-<N>")
    confirm.set_defaults(func=_command_confirm_asset)

    reuse = subparsers.add_parser("reuse-asset", help="用户确认后，决定其他范围素材本集是否沿用")
    reuse.add_argument("--episode", required=True)
    reuse.add_argument("--name", required=True)
    reuse.add_argument("--action", required=True, choices=("use", "skip"))
    reuse.set_defaults(func=_command_reuse_asset)

    record_outline = subparsers.add_parser("record-story-outline", help="登记 AI 生成、等待用户确认的故事概要")
    record_outline.add_argument("--episode", required=True)
    record_outline.add_argument("--file", required=True, help="含故事梗概、人物小传、本集大纲的 UTF-8 Markdown 文件")
    record_outline.set_defaults(func=_command_record_story_outline)

    approve_story = subparsers.add_parser("approve-story", help="记录用户确认 AI 故事概要")
    approve_story.add_argument("--episode", required=True)
    approve_story.set_defaults(func=_command_approve_story)

    approve_script = subparsers.add_parser("approve-script", help="记录用户确认剧本与分镜")
    approve_script.add_argument("--episode", required=True)
    approve_script.set_defaults(func=_command_approve_script)

    plan_keyframes = subparsers.add_parser("plan-keyframes", help="按分镜建立关键帧方案")
    plan_keyframes.add_argument("--episode", required=True)
    plan_keyframes.add_argument("--shots-file", required=True)
    plan_keyframes.set_defaults(func=_command_plan_keyframes)

    approve_keyframes = subparsers.add_parser("approve-keyframes", help="记录用户确认关键帧方案")
    approve_keyframes.add_argument("--episode", required=True)
    approve_keyframes.add_argument("--middle-shot", action="append", help="用户明确同意保留过程帧的镜号")
    approve_keyframes.set_defaults(func=_command_approve_keyframes)

    create_execution = subparsers.add_parser("create-execution", help="建立 v2 关键帧执行单")
    create_execution.add_argument("--episode", required=True)
    create_execution.add_argument("--details-file", required=True)
    create_execution.set_defaults(func=_command_create_execution)

    inspect = subparsers.add_parser("inspect", help="列出已确认素材与剧集")
    inspect.set_defaults(func=_command_inspect)

    dispatch_asset_parser = subparsers.add_parser("dispatch-asset", help="新资产出图前的必传参考图")
    dispatch_asset_parser.add_argument("--episode", required=True)
    dispatch_asset_parser.add_argument("--name", required=True)
    dispatch_asset_parser.add_argument("--kind")
    dispatch_asset_parser.add_argument("--visual-brief", default="")
    dispatch_asset_parser.set_defaults(func=_command_dispatch_asset)

    dispatch_keyframe_parser = subparsers.add_parser("dispatch-keyframe", help="关键帧出图前的必传参考图")
    dispatch_keyframe_parser.add_argument("--episode", required=True)
    dispatch_keyframe_parser.add_argument("--shot", required=True)
    dispatch_keyframe_parser.add_argument("--frame", required=True, choices=("start", "middle", "end"))
    dispatch_keyframe_parser.add_argument("--stage")
    dispatch_keyframe_parser.set_defaults(func=_command_dispatch_keyframe)

    record_image = subparsers.add_parser("record-image", help="登记图片工具的产出为工作版本")
    record_image.add_argument("--episode", required=True)
    record_image.add_argument("--dispatch", required=True)
    record_image.add_argument("--output", required=True, help="项目内的生成图路径")
    record_image.add_argument("--tool-request-id")
    record_image.add_argument("--started-at")
    record_image.add_argument("--completed-at")
    record_image.set_defaults(func=_command_record_image)

    record_qa = subparsers.add_parser("record-qa", help="记录该阶段质检结果")
    record_qa.add_argument("--episode", required=True)
    record_qa.add_argument("--dispatch", required=True)
    record_qa.add_argument("--status", required=True, choices=("pass", "fail", "uncertain"))
    record_qa.add_argument("--reviewer", default="automated", choices=("automated", "user"))
    record_qa.add_argument("--check", action="append", required=True, help="类别=状态:置信度")
    record_qa.add_argument("--issue")
    record_qa.add_argument("--checked-at")
    record_qa.set_defaults(func=_command_record_qa)

    redo = subparsers.add_parser("redo-keyframe", help="用户要求重做已确认帧")
    redo.add_argument("--episode", required=True)
    redo.add_argument("--shot", required=True)
    redo.add_argument("--frame", required=True, choices=("start", "middle", "end"))
    redo.add_argument("--reason", required=True)
    redo.set_defaults(func=_command_redo_keyframe)

    override = subparsers.add_parser("register-override", help="登记用户额外提供的参考图")
    override.add_argument("--episode", required=True)
    override.add_argument("--path", required=True)
    override.add_argument(
        "--role",
        required=True,
        choices=("background", "character_identity", "prop_identity", "lighting", "composition", "style"),
    )
    override.add_argument("--scope", required=True, choices=("shot", "continuity_run", "episode"))
    override.add_argument("--scope-id", action="append")
    override.add_argument("--target-asset-id")
    override.set_defaults(func=_command_register_override)

    continuity = subparsers.add_parser(
        "record-continuity", help="用户确认后写入连续性记录，供下一集继承"
    )
    continuity.add_argument("--episode", required=True)
    continuity.add_argument("--event", action="append", required=True)
    continuity.add_argument("--character-state", action="append")
    continuity.add_argument("--ending-frame", required=True)
    continuity.add_argument("--open-thread", action="append")
    continuity.add_argument("--next-requirement", action="append")
    continuity.set_defaults(func=_command_record_continuity)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            root = (args.project_root or Path.cwd()).resolve()
        else:
            try:
                root = find_project_root(args.project_root)
            except ImageCanonError:
                if args.command != "status":
                    raise
                root = (args.project_root or Path.cwd()).resolve()
        payload = args.func(root, args)
        _emit(payload)
        if isinstance(payload, dict) and payload.get("allowed") is False:
            raise SystemExit(2)
    except (ButlerError, ImageCanonError, ValueError, FileNotFoundError, FileExistsError) as error:
        _emit({"ok": False, "error": str(error)})
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
