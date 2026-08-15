#!/usr/bin/env python3
"""Derive the current production stage and the single next action for an episode.

A new conversation cannot infer progress from five separate JSON files without
guessing, so this module is the one place that answers "where are we, what now".
It only reads project files; it never advances the workflow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_files import normalize_asset_drafts


STAGE_ORDER = (
    "no_project",
    "no_episode",
    "episode_created",
    "assets_pending",
    "assets_ready",
    "script_pending_approval",
    "script_approved",
    "keyframe_plan_pending",
    "keyframe_plan_approved",
    "execution_legacy",
    "keyframes_in_progress",
    "keyframes_done",
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def list_episodes(project_root: Path) -> list[dict[str, Any]]:
    """List episode directories with their IDs and titles, oldest first."""
    root = Path(project_root).resolve()
    episodes: list[dict[str, Any]] = []
    episode_root = root / "episodes"
    if not episode_root.is_dir():
        return episodes
    for path in sorted(episode_root.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        episode_id = path.name.split("_", 1)[0]
        title = path.name.split("_", 1)[1] if "_" in path.name else path.name
        state = _read_json(path / "episode-state.json")
        episodes.append(
            {
                "episode_id": str(state.get("episode_id") or episode_id),
                "title": str(state.get("episode_title") or title),
                "path": path.relative_to(root).as_posix(),
            }
        )
    return episodes


def _pending_frames(manifest: dict[str, Any]) -> list[dict[str, str]]:
    pending: list[dict[str, str]] = []
    for shot in manifest.get("shots", []):
        for frame in shot.get("frames", []):
            if frame.get("status") != "confirmed":
                pending.append(
                    {
                        "shot_id": str(shot.get("shot_id")),
                        "frame_kind": str(frame.get("frame_kind")),
                        "status": str(frame.get("status")),
                    }
                )
    return pending


def episode_status(project_root: Path, episode_id: str) -> dict[str, Any]:
    """Return the derived stage, blockers, and the next command to run."""
    root = Path(project_root).resolve()
    matches = [path for path in (root / "episodes").glob(f"{episode_id}_*") if path.is_dir()]
    if not matches:
        raise ValueError(f"找不到剧集目录：{episode_id}")
    if len(matches) > 1:
        raise ValueError(f"剧集 ID 不唯一：{episode_id}")
    episode_dir = matches[0]
    state = _read_json(episode_dir / "episode-state.json")
    drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
    production = _read_json(episode_dir / "asset-production-manifest.json")
    unregistered = [
        {"name": str(asset.get("name")), "kind": str(asset.get("kind")), "status": str(asset.get("status"))}
        for asset in production.get("assets", [])
        if asset.get("status") != "registered"
    ]
    has_script = (episode_dir / "formal-script.md").is_file()
    has_storyboard = (episode_dir / "storyboard.md").is_file()
    script_approved = state.get("script_and_storyboard_status") == "user_confirmed"
    keyframe_plan = _read_json(episode_dir / "keyframe-manifest.json")
    execution = _read_json(episode_dir / "keyframe-execution-manifest.json")

    result: dict[str, Any] = {
        "episode_id": episode_id,
        "title": str(state.get("episode_title") or ""),
        "episode_path": episode_dir.relative_to(root).as_posix(),
        "new_asset_drafts": drafts,
        "unregistered_planned_assets": unregistered,
        "has_formal_script": has_script,
        "has_storyboard": has_storyboard,
        "script_and_storyboard_approved": script_approved,
    }

    if drafts and not production:
        unclassified = [draft["name"] for draft in drafts if not draft["kind"]]
        result["stage"] = "episode_created"
        result["summary"] = (
            "已检测到本集新增资产；确认大纲后先建资产生产单。"
            + (f" 以下资产还没有类别：{'、'.join(unclassified)}。" if unclassified else "")
        )
        result["next_actions"] = [
            "向用户展示故事梗概、人物小传和本集大纲，等待确认。",
            "确认后运行：butler.py plan-assets --episode "
            f"{episode_id} --new '名称:characters|scenes|props:视觉说明'",
        ]
        return result

    if unregistered:
        result["stage"] = "assets_pending"
        result["summary"] = f"还有 {len(unregistered)} 项新增资产未登记。"
        result["next_actions"] = [
            f"butler.py dispatch-asset --episode {episode_id} --name {unregistered[0]['name']}",
            "对返回的 view_image_paths 逐张读图，再用同一 prompt 生成参考图。",
            f"butler.py provide-asset --episode {episode_id} --name {unregistered[0]['name']} --image front=<路径>",
            f"用户确认后：butler.py confirm-asset --episode {episode_id} --name {unregistered[0]['name']}",
        ]
        return result

    if not (has_script and has_storyboard):
        missing = [
            name
            for name, present in (("formal-script.md", has_script), ("storyboard.md", has_storyboard))
            if not present
        ]
        result["stage"] = "assets_ready"
        result["summary"] = f"素材已就绪；还缺 {'、'.join(missing)}。"
        result["next_actions"] = [
            f"用 $seedance-storyboard-generator 读 {result['episode_path']}/storyboard-package.md，写剧本和导演版分镜。",
            f"validate_director_storyboard.py --storyboard {result['episode_path']}/storyboard.md --target-seconds <本集时长>",
        ]
        return result

    if not script_approved:
        result["stage"] = "script_pending_approval"
        result["summary"] = "剧本和分镜已写好，等待用户确认。"
        result["next_actions"] = [
            f"validate_director_storyboard.py --storyboard {result['episode_path']}/storyboard.md --target-seconds <本集时长>",
            "校验通过后展示给用户；获确认后运行："
            f"butler.py approve-script --episode {episode_id}",
        ]
        return result

    if not keyframe_plan:
        result["stage"] = "script_approved"
        result["summary"] = "剧本和分镜已确认；下一步规划每镜关键帧数量。"
        result["next_actions"] = [
            f"butler.py plan-keyframes --episode {episode_id} --shots-file <shots.json>",
        ]
        return result

    if keyframe_plan.get("status") != "user_confirmed":
        result["stage"] = "keyframe_plan_pending"
        result["summary"] = "关键帧方案等待用户确认；过程帧需逐镜明确同意。"
        result["next_actions"] = [
            f"butler.py approve-keyframes --episode {episode_id} [--middle-shot <镜号>]",
        ]
        return result

    if not execution:
        result["stage"] = "keyframe_plan_approved"
        result["summary"] = "关键帧方案已确认；下一步建立 v2 执行单。"
        result["next_actions"] = [
            f"butler.py create-execution --episode {episode_id} --details-file <details.json>",
        ]
        return result

    if execution.get("schema_version") != 2:
        result["stage"] = "execution_legacy"
        result["summary"] = "本集执行单是旧版，不能用于出图。"
        result["next_actions"] = [
            "人工归档 keyframe-execution.md 与 keyframe-execution-manifest.json。",
            "确认新版剧本与分镜后，重新走 plan-keyframes → approve-keyframes → create-execution。",
        ]
        return result

    pending = _pending_frames(execution)
    result["pending_frames"] = pending
    if pending:
        first = pending[0]
        result["stage"] = "keyframes_in_progress"
        result["summary"] = f"还有 {len(pending)} 帧未确认。"
        result["next_actions"] = [
            f"butler.py dispatch-keyframe --episode {episode_id} --shot {first['shot_id']} --frame {first['frame_kind']}",
            "对返回的 view_image_paths 逐张读图，再用同一 prompt 出图。",
            f"butler.py record-image --episode {episode_id} --dispatch <dispatch_id> --output <生成图路径>",
            f"butler.py record-qa --episode {episode_id} --dispatch <dispatch_id> --status pass --check scene=pass:0.9",
        ]
        return result

    result["stage"] = "keyframes_done"
    result["summary"] = "本集全部关键帧已确认，可交给图生视频工具。"
    result["next_actions"] = [
        "按 keyframe-execution.md 的图生视频提示词逐镜生成视频并剪辑。",
        f"成片定稿后：butler.py record-continuity --episode {episode_id} --confirm",
    ]
    return result


def project_status(project_root: Path) -> dict[str, Any]:
    """Return project-level readiness plus the status of the latest episode."""
    root = Path(project_root).resolve()
    settings = root / "project-settings"
    if not (settings / "project.yaml").is_file() and not (settings / "asset-index.json").is_file():
        return {
            "stage": "no_project",
            "summary": "当前目录还不是短剧项目。",
            "next_actions": ["butler.py init --name <项目名> [--format 16:9] [--seconds 120]"],
        }
    index = _read_json(settings / "asset-index.json")
    episodes = list_episodes(root)
    payload: dict[str, Any] = {
        "project_root": str(root),
        "registered_assets": len(index.get("assets", [])),
        "episodes": episodes,
    }
    if not episodes:
        payload.update(
            {
                "stage": "no_episode",
                "summary": "项目已初始化，还没有剧集。",
                "next_actions": [
                    "butler.py new-episode --episode EP001 --title <剧集名> --story <一段故事> "
                    "--asset '咕噜' --asset '小鸟:characters' --asset '森林:scenes'"
                ],
            }
        )
        return payload
    latest = episodes[-1]
    payload["latest_episode"] = episode_status(root, latest["episode_id"])
    payload["stage"] = payload["latest_episode"]["stage"]
    payload["summary"] = f"{latest['episode_id']}《{latest['title']}》：{payload['latest_episode']['summary']}"
    payload["next_actions"] = payload["latest_episode"]["next_actions"]
    return payload
