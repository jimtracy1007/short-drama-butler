#!/usr/bin/env python3
"""Derive the current production stage and the single next action for an episode.

A new conversation cannot infer progress from five separate JSON files without
guessing, so this module is the one place that answers "where are we, what now".
It only reads project files; it never advances the workflow.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from keyframe_prompt import load_parsed_storyboard, missing_time_scene_views
from project_files import (
    episode_creation_gate,
    normalize_asset_drafts,
    pending_episode_assets,
    story_outline_is_confirmed,
)
from story_detect import asset_is_lockable


STAGE_ORDER = (
    "no_project",
    "no_episode",
    "story_outline_pending",
    "episode_created",
    "assets_pending",
    "assets_ready",
    "script_pending_approval",
    "script_approved",
    "deferred_assets_pending",
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


GENERATE_STATUSES = {"planned", "failed", "needs_regeneration"}
QA_STAGE_STATUSES = {"generated", "pending_review"}


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


def _current_stage(frame: dict[str, Any]) -> dict[str, Any] | None:
    current_id = frame.get("current_plan_id")
    plan = next((item for item in frame.get("plans") or [] if item.get("plan_id") == current_id), None)
    if not plan:
        return None
    for stage in plan.get("stages") or []:
        if stage.get("status") in {"generating", "generated", "pending_review"}:
            return stage
    return None


def _awaiting_qa(frame: dict[str, Any]) -> bool:
    if frame.get("status") == "pending_review":
        return True
    stage = _current_stage(frame)
    return bool(stage and stage.get("status") in QA_STAGE_STATUSES)


def _blocked_by_unconfirmed_predecessor(manifest: dict[str, Any], frame: dict[str, Any]) -> bool:
    contract = (frame.get("frame_spec") or {}).get("continuity_contract")
    if not contract:
        return False
    predecessor = contract.get("predecessor") or {}
    shot_id = str(predecessor.get("shot_id") or "").zfill(2)
    frame_kind = str(predecessor.get("frame_kind") or "")
    for shot in manifest.get("shots") or []:
        if str(shot.get("shot_id") or "").zfill(2) != shot_id:
            continue
        for candidate in shot.get("frames") or []:
            if str(candidate.get("frame_kind")) == frame_kind:
                return candidate.get("status") != "confirmed"
    return True


def _frame_ref(shot: dict[str, Any], frame: dict[str, Any]) -> dict[str, str]:
    return {
        "shot_id": str(shot.get("shot_id")),
        "frame_kind": str(frame.get("frame_kind")),
        "status": str(frame.get("status")),
    }


REGEN_STATUSES = {"failed", "needs_regeneration"}


def keyframe_work(manifest: dict[str, Any]) -> dict[str, Any]:
    """Pick the next generate or review batch. Every still is a sub-agent."""
    regen: list[dict[str, str]] = []
    for shot in manifest.get("shots") or []:
        for frame in shot.get("frames") or []:
            if frame.get("status") in REGEN_STATUSES and not _blocked_by_unconfirmed_predecessor(manifest, frame):
                regen.append(_frame_ref(shot, frame))
    if regen:
        shot_ids = {item["shot_id"] for item in regen}
        return {
            "mode": "spawn_subagents",
            "shot_id": next(iter(shot_ids)) if len(shot_ids) == 1 else "",
            "frames": regen,
            "in_flight": [],
        }

    for shot in manifest.get("shots") or []:
        incomplete = [frame for frame in shot.get("frames") or [] if frame.get("status") != "confirmed"]
        if not incomplete:
            continue
        generate = [
            frame
            for frame in incomplete
            if frame.get("status") in GENERATE_STATUSES and not _blocked_by_unconfirmed_predecessor(manifest, frame)
        ]
        in_flight = [frame for frame in incomplete if frame.get("status") == "generating" and not _awaiting_qa(frame)]
        review = [frame for frame in incomplete if _awaiting_qa(frame)]
        if generate:
            return {
                "mode": "spawn_subagents",
                "shot_id": str(shot.get("shot_id")),
                "frames": [_frame_ref(shot, frame) for frame in generate],
                "in_flight": [_frame_ref(shot, frame) for frame in in_flight],
            }
        if in_flight:
            return {
                "mode": "wait_subagents",
                "shot_id": str(shot.get("shot_id")),
                "frames": [_frame_ref(shot, frame) for frame in in_flight],
            }
        if review:
            return {
                "mode": "review",
                "shot_id": str(shot.get("shot_id")),
                "frames": [_frame_ref(shot, frame) for frame in review],
            }
    return {"mode": "done", "frames": []}


def _keyframe_actions(episode_id: str, work: dict[str, Any]) -> list[str]:
    frames = list(work.get("frames") or [])
    in_flight = list(work.get("in_flight") or [])
    if work.get("mode") == "spawn_subagents":
        dispatches = [
            f"butler.py dispatch-keyframe --episode {episode_id} --shot {item['shot_id']} --frame {item['frame_kind']}"
            for item in frames
        ]
        total = len(frames) + len(in_flight)
        refining = any(item.get("status") in REGEN_STATUSES for item in frames + in_flight)
        kind = "（含精修/重做）" if refining else ""
        shots = "、".join(dict.fromkeys(item["shot_id"] for item in frames))
        where = f"镜头 {shots}" if shots else "本批"
        return [
            (
                f"{where} 有 {total} 帧要出图{kind}："
                f"同时派 {len(frames)} 个子 agent，每帧一个；主 agent 不自己出图、不读参考图，"
                "等全部 record-image 后一起审核。"
            ),
            *dispatches,
            "子 agent 只做 dispatch-keyframe → 先原样输出 brief.text → 读参考图 → 按冻结 prompt 出图 → record-image，不要 record-qa。",
            "主 agent 审核身份、场景结构、时段和分镜姿势；空间结构不一致必须 fail。通过后才 record-qa。",
        ]
    if work.get("mode") == "wait_subagents":
        waiting = "、".join(f"{item['shot_id']}/{item['frame_kind']}" for item in frames)
        return [f"等待子 agent 完成 {waiting} 的 record-image，主 agent 不要重派同一帧，也不要自己出图。"]
    if work.get("mode") == "review":
        names = "、".join(f"{item['shot_id']}/{item['frame_kind']}" for item in frames)
        return [
            f"主 agent 审核 {names}：对照场景母版查墙体/开口/固定家具，对照角色母版查身份，对照分镜查姿势。",
            "通过则 butler.py record-qa --episode "
            f"{episode_id} --dispatch <dispatch_id> --status pass --check scene=pass:0.9 --check character=pass:0.9；"
            "空间结构不一致或开关错位则 fail，再 refine-keyframe；失败几张就派几个子 agent 重出，主 agent 不要自己出图。",
        ]
    return []


def _next_episode_id(project_root: Path) -> str:
    numbers = []
    for episode in list_episodes(project_root):
        match = re.match(r"EP(\d+)$", str(episode.get("episode_id", "")), re.I)
        if match:
            numbers.append(int(match.group(1)))
    return f"EP{max(numbers, default=0) + 1:03d}"


def _reuse_action(episode_id: str, reuse_candidates: list[dict[str, Any]]) -> str:
    names = "、".join(str(item.get("name")) for item in reuse_candidates)
    return (
        f"用中文问用户这些其他范围素材本集是否沿用：{names}。"
        f"用户说用则 butler.py reuse-asset --episode {episode_id} --name <名称> --action use；"
        "不用则 --action skip。确认前不要写分镜。"
    )


def _asset_actions(episode_id: str, asset: dict[str, Any]) -> list[str]:
    if asset.get("status") == "draft":
        return [f"butler.py plan-assets --episode {episode_id}"]
    return [
        f"butler.py dispatch-asset --episode {episode_id} --name {asset['name']}",
        "对返回的 view_image_paths 逐张读图（已确认角色/场景母版为身份锁，不得只参考上一张草图），再用同一 prompt 生成参考图。",
        f"butler.py provide-asset --episode {episode_id} --name {asset['name']} --image front=<路径>",
        f"用户确认后：butler.py confirm-asset --episode {episode_id} --name {asset['name']}",
    ]


def _missing_time_actions(project_root: Path, episode_dir: Path, episode_id: str) -> tuple[list[dict[str, str]], list[str]]:
    parsed = load_parsed_storyboard(episode_dir / "storyboard.md")
    missing = missing_time_scene_views(project_root, parsed)
    if not missing:
        return [], []
    actions = [
        (
            f"先为「{item['name']}」补 {item['needed_view']} 时段母版："
            f"butler.py dispatch-asset --episode {episode_id} --name {item['name']}，"
            f"provide-asset 时带 {item['needed_view']}=<图>，再 confirm-asset。"
            "没有对应时段场景图就出关键帧，只会画错再精修。"
        )
        for item in missing
    ]
    return missing, actions


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
    story_outline_confirmed = story_outline_is_confirmed(root, episode_id)
    drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
    reuse_candidates = list(state.get("reuse_candidates") or [])
    production = _read_json(episode_dir / "asset-production-manifest.json")
    unregistered = [
        {"name": str(asset.get("name")), "kind": str(asset.get("kind")), "status": str(asset.get("status"))}
        for asset in production.get("assets", [])
        if asset.get("status") != "registered"
    ]
    pre_storyboard = pending_episode_assets(root, episode_id, "before_storyboard")
    pre_keyframes = pending_episode_assets(root, episode_id, "before_keyframes")
    incidental = [draft for draft in drafts if draft["timing"] == "incidental"]
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
        "reuse_candidates": reuse_candidates,
        "unregistered_planned_assets": unregistered,
        "before_storyboard_assets_pending": pre_storyboard,
        "before_keyframes_assets_pending": pre_keyframes,
        "incidental_assets": incidental,
        "has_formal_script": has_script,
        "has_storyboard": has_storyboard,
        "script_and_storyboard_approved": script_approved,
        "story_outline_status": str(
            state.get("story_outline_status")
            or ("user_confirmed" if story_outline_confirmed else "draft_pending")
        ),
        "story_outline_confirmed": story_outline_confirmed,
        "user_notice": str(state.get("detected_asset_notice") or ""),
    }

    if not story_outline_confirmed:
        result["stage"] = "story_outline_pending"
        if state.get("story_outline_status") == "user_pending":
            result["summary"] = "AI 故事概要等待用户确认；不能计划、派发或登记本集素材。"
            result["next_actions"] = [
                f"展示 {result['episode_path']}/story-outline.md 给用户确认；不要重复生成故事。",
                f"用户确认后运行：butler.py approve-story --episode {episode_id}。",
            ]
        else:
            result["summary"] = "AI 故事概要尚未获用户确认；不能计划、派发或登记本集素材。"
            result["next_actions"] = [
                f"用 $seedance-storyboard-generator 读取 {result['episode_path']}/storyboard-package.md，生成故事梗概、人物小传和本集大纲。",
                f"将 AI 故事稿写入临时文件后运行：butler.py record-story-outline --episode {episode_id} --file <outline.md>。",
                f"展示 story-outline.md 给用户；用户确认后运行：butler.py approve-story --episode {episode_id}。",
            ]
        return result

    if pre_storyboard:
        result["stage"] = "assets_pending"
        result["summary"] = (
            f"还有 {len(pre_storyboard)} 项分镜前素材未登记。"
            + (
                "确认其他范围素材前，不能写正式剧本或分镜。"
                if reuse_candidates
                else ""
            )
        )
        result["next_actions"] = _asset_actions(episode_id, pre_storyboard[0])
        if reuse_candidates:
            result["next_actions"].append(_reuse_action(episode_id, reuse_candidates))
        return result

    if reuse_candidates or any(asset.get("status") == "draft" for asset in pre_storyboard):
        unclassified = [draft["name"] for draft in drafts if not draft["kind"] and draft["timing"] == "before_storyboard"]
        result["stage"] = "episode_created"
        result["summary"] = (
            "已检测到分镜前新增或越界素材；确认大纲并完成资产生产前，不能写正式剧本或分镜。"
            + (f" 以下名称还没有类别：{'、'.join(unclassified)}。" if unclassified else "")
            + (
                f" 以下素材属于其他范围，不能自动锁定：{'、'.join(str(item.get('name')) for item in reuse_candidates)}。"
                if reuse_candidates
                else ""
            )
        )
        result["next_actions"] = [
            "把 user_notice 原样告诉用户，用中文确认发现了哪些新角色/场景/道具。不要让用户填写 --asset 或任何命令。",
            "有待确认名称时，先问清是角色、场景还是道具；确认前不要写分镜。",
        ]
        if any(asset.get("status") == "draft" for asset in pre_storyboard):
            result["next_actions"].append(
                f"用户确认大纲后运行：butler.py plan-assets --episode {episode_id}"
            )
        if reuse_candidates:
            result["next_actions"].append(_reuse_action(episode_id, reuse_candidates))
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
        if pre_keyframes:
            result["stage"] = "deferred_assets_pending"
            result["summary"] = (
                f"剧本和分镜已确认；还有 {len(pre_keyframes)} 项关键帧前素材未登记。"
            )
            result["next_actions"] = _asset_actions(episode_id, pre_keyframes[0])
            return result
        result["stage"] = "script_approved"
        result["summary"] = "剧本和分镜已确认；下一步规划每镜关键帧数量。"
        result["next_actions"] = [
            f"butler.py plan-keyframes --episode {episode_id}",
        ]
        missing, extra = _missing_time_actions(root, episode_dir, episode_id)
        if missing:
            result["missing_time_views"] = missing
            result["summary"] = "剧本和分镜已确认；先补夜景/黄昏/黎明场景母版，再规划关键帧。"
            result["next_actions"] = extra + result["next_actions"]
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
            f"butler.py create-execution --episode {episode_id}",
            "不要手写缩水版提示词；系统从分镜本帧画面、视觉锁和已确认资产拼装。",
        ]
        missing, extra = _missing_time_actions(root, episode_dir, episode_id)
        if missing:
            result["missing_time_views"] = missing
            result["next_actions"] = extra + result["next_actions"]
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
    missing, extra = _missing_time_actions(root, episode_dir, episode_id)
    if missing:
        result["missing_time_views"] = missing
    if pending:
        first = pending[0]
        work = keyframe_work(execution)
        result["keyframe_work"] = work
        result["stage"] = "keyframes_in_progress"
        result["summary"] = f"还有 {len(pending)} 帧未确认。"
        result["next_actions"] = _keyframe_actions(episode_id, work) or [
            f"butler.py dispatch-keyframe --episode {episode_id} --shot {first['shot_id']} --frame {first['frame_kind']}",
        ]
        if missing:
            result["summary"] = (
                f"还有 {len(pending)} 帧未确认；先补夜景/黄昏/黎明场景母版，再出关键帧。"
            )
            result["next_actions"] = extra + result["next_actions"]
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
                    "用户若已有故事：butler.py new-episode --story <用户原话>。",
                    "用户若说不知道写啥：butler.py propose-story，根据返回的已有角色和上集承接先出 2-3 个故事，等用户点头后再 new-episode。",
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


def propose_story_context(project_root: Path) -> dict[str, Any]:
    """Pack project memory so the agent can invent today's episode without asking the user for a plot.

    This function does not write a story.  It only lists lockable names, the last
    confirmed continuity, and whether a new episode is allowed yet.
    """
    root = Path(project_root).resolve()
    status = project_status(root)
    next_episode_id = _next_episode_id(root)
    gate = episode_creation_gate(root, next_episode_id)
    index = _read_json(root / "project-settings" / "asset-index.json")
    characters: list[str] = []
    scenes: list[str] = []
    props: list[str] = []
    for asset in index.get("assets", []):
        if not asset_is_lockable(asset, next_episode_id, project_root=root):
            continue
        name = str(asset.get("name") or asset.get("asset_id") or "").strip()
        if not name:
            continue
        kind = str(asset.get("kind", ""))
        if kind == "characters":
            characters.append(name)
        elif kind == "scenes":
            scenes.append(name)
        elif kind == "props":
            props.append(name)
    bible_path = root / "project-settings" / "character-bible.md"
    bible = bible_path.read_text(encoding="utf-8") if bible_path.is_file() else ""
    continuity = None
    pending_continuity = None
    for episode in reversed(list_episodes(root)):
        path = root / episode["path"] / "episode-continuity.md"
        if not path.is_file():
            continue
        contents = path.read_text(encoding="utf-8")
        record = {
            "episode_id": episode["episode_id"],
            "title": episode["title"],
            "path": path.relative_to(root).as_posix(),
            "excerpt": contents.strip(),
        }
        if any(line.strip() == "- 状态：已确认" for line in contents.splitlines()):
            continuity = record
            break
        if pending_continuity is None:
            pending_continuity = record
    if not gate["allowed"]:
        return {
            "allowed": False,
            "stage": status.get("stage"),
            "next_episode_id": next_episode_id,
            "existing_characters": characters,
            "existing_scenes": scenes,
            "existing_props": props,
            "last_confirmed_continuity": continuity,
            "pending_continuity": pending_continuity,
            "user_notice": (
                "上一集的连续性还没确认，现在不能开新一集。"
                "请先确认上集记录，或明确说这是一集独立故事。"
            ),
            "agent_instructions": [
                "不要让用户选新故事，也不要调用 new-episode。",
                "先展示上一集连续性记录，请用户确认；或在用户明确说独立集后用 --standalone。",
            ],
            "reason": gate["reason"],
        }
    return {
        "allowed": True,
        "stage": status.get("stage"),
        "next_episode_id": next_episode_id,
        "existing_characters": characters,
        "existing_scenes": scenes,
        "existing_props": props,
        "character_bible": "project-settings/character-bible.md",
        "character_bible_excerpt": bible[:4000],
        "last_confirmed_continuity": continuity,
        "user_notice": (
            "今天先给你 2-3 个本集故事，用已有角色和场景来写；你点哪个，我再开这一集。"
            if characters or scenes
            else "项目里还没有锁定角色。今天先给你 2-3 个故事方向，你点哪个我再开项目记忆和这一集。"
        ),
        "agent_instructions": [
            "用户说不知道写啥、你出个故事、随便做一集时走这里，不要反问用户要剧情。",
            "先用现有角色和场景写 2-3 个不超过 80 字的本集故事，优先承接 last_confirmed_continuity。",
            "只使用 existing_characters / existing_scenes / existing_props 里的锁定名称；pending 或其他集专属素材不能写进故事当已有角色。",
            "不得发明已有角色的新外形；新配角或新场景要在故事里点名，方便稍后检出为待确认草案。",
            "用中文把选项列给用户，等用户点头或改一版后，再 butler.py new-episode --story <选定故事>。",
            "在用户确认故事之前，不要建集、不要出图。",
        ],
    }
