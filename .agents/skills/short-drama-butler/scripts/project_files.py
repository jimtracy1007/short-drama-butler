#!/usr/bin/env python3
"""Create portable project files and Storyboard Generator handoff packages."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asset_migration import build_plan, execute_plan, rollback
from extract_docx_text import extract_text


KIND_PREFIXES = {"characters": "C", "scenes": "S", "props": "P"}
KEYFRAME_STRATEGIES = {
    "start_only": ("首帧", ["start"]),
    "start_end": ("首帧、尾帧", ["start", "end"]),
    "start_middle_end": ("首帧、过程帧、尾帧", ["start", "middle", "end"]),
}
EPISODE_OVERRIDE_KEYS = {
    "audience",
    "format",
    "episode_target_seconds",
    "shot_count",
    "content_guidelines",
    "visual_canon_precedence",
    "video_workflow",
    "storyboard_skill",
}


def _yaml_string(value: object) -> str:
    """Serialize a scalar safely for the deliberately flat project YAML."""
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize_project(
    project_root: Path,
    project_name: str,
    source_document: Path | None,
    audience: str = "",
    frame_format: str = "",
    episode_target_seconds: int | None = None,
    content_guidelines: str = "",
    shot_count: str = "",
    visual_canon_precedence: str = "",
    video_workflow: str = "",
    storyboard_skill: str = "",
) -> None:
    """Create the standard project layout and move the source document once."""
    root = project_root.resolve()
    initialization_markers = (
        root / "project-settings" / "project.yaml",
        root / "project-settings" / "asset-index.json",
    )
    episode_root = root / "episodes"
    if any(marker.exists() for marker in initialization_markers) or (
        episode_root.is_dir() and any(episode_root.iterdir())
    ):
        raise FileExistsError("项目已初始化；请使用整理、更新或创建剧集流程，不能重新初始化并覆盖项目记忆")
    if source_document is not None:
        source_document = source_document.resolve()
        if source_document.parent != root or source_document.suffix.lower() != ".docx":
            raise ValueError("固定设定文档必须是项目根目录下的 .docx 文件")
        if not source_document.is_file():
            raise FileNotFoundError(source_document)
        source_text = extract_text(source_document)

    for directory in ("project-settings", "source-material", "assets", "episodes", "templates"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if source_document is not None:
        canonical_document = root / "source-material" / "固定设定.docx"
        if canonical_document.exists():
            raise FileExistsError(f"目标设定文档已存在：{canonical_document}")
        source_hash = _sha256(source_document)
        source_document.replace(canonical_document)
        (root / "project-settings" / "source-document.json").write_text(
            json.dumps(
                {
                    "original_path": source_document.name,
                    "canonical_path": canonical_document.relative_to(root).as_posix(),
                    "sha256": source_hash,
                    "moved_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "project-settings" / "fixed-settings-source.txt").write_text(source_text, encoding="utf-8")
    (root / "project-settings" / "project.yaml").write_text(
        "\n".join(
            [
                f"project_name: {_yaml_string(project_name)}",
                f"audience: {_yaml_string(audience)}",
                f"format: {_yaml_string(frame_format)}",
                f"episode_target_seconds: {_yaml_string(episode_target_seconds)}",
                f"shot_count: {_yaml_string(shot_count)}",
                f"content_guidelines: {_yaml_string(content_guidelines)}",
                f"visual_canon_precedence: {_yaml_string(visual_canon_precedence)}",
                f"video_workflow: {_yaml_string(video_workflow)}",
                f"storyboard_skill: {_yaml_string(storyboard_skill)}",
                f"source_document: {_yaml_string('source-material/固定设定.docx' if source_document is not None else '')}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "project-settings" / "character-bible.md").write_text(
        "# 角色圣经\n\n"
        "## 使用规则\n\n"
        "- 已确认图片优先于文字描述；冲突必须记录在 `setting-conflicts.md`。\n"
        "- 每个角色区分：不可改动设定、可补充设定、本集状态。\n"
        "- 没有完整文字小传的素材只能标为待确认，不能自动成为锁定主角。\n",
        encoding="utf-8",
    )
    (root / "project-settings" / "setting-conflicts.md").write_text(
        "# 设定冲突待确认\n\n"
        "记录文档、素材图或新剧集需求的冲突；确认过的角色图为最终视觉准则。\n",
        encoding="utf-8",
    )
    write_asset_index(root, [])
    (root / "templates" / "episode-brief.md").write_text(
        "# 本集剧情需求\n\n"
        "- 主题：\n- 主角：\n- 新增角色 / 场景 / 道具：\n- 本集状态：\n- 不可改动设定：\n",
        encoding="utf-8",
    )


def build_asset_index(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group several reference views into one logical Cxx/Sxx/Pxx asset."""
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        asset_id = record["asset_id"]
        asset = grouped.setdefault(
            asset_id,
            {
                "asset_id": asset_id,
                "name": record.get("name", asset_id),
                "kind": record["kind"],
                "scope": record["scope"],
                "destination": record["destination"],
                "aliases": [],
                "views": [],
            },
        )
        for alias in record.get("aliases", []):
            if alias not in asset["aliases"] and alias != asset["name"]:
                asset["aliases"].append(alias)
        view = {"variant": record.get("variant", "reference"), "path": record["destination"]}
        asset["views"].append(view)
        if view["variant"] == "front":
            asset["destination"] = view["path"]
    return list(grouped.values())


def write_asset_index(project_root: Path, assets: list[dict[str, Any]]) -> Path:
    """Write the authoritative, machine-readable asset registry."""
    path = project_root.resolve() / "project-settings" / "asset-index.json"
    path.write_text(json.dumps({"version": 1, "assets": assets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_project_settings(project_root: Path) -> dict[str, str]:
    """Read the flat project YAML written by initialize_project without dependencies."""
    settings: dict[str, str] = {}
    for line in (project_root / "project-settings" / "project.yaml").read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        raw_value = value.strip()
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = raw_value.strip('"')
        settings[key.strip()] = str(parsed)
    return settings


def register_asset(
    assets: list[dict[str, Any]],
    name: str,
    kind: str,
    scope: str,
    destination: str,
    *,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Register a named asset and allocate its stable internal ID.

    Names and aliases are the user-facing API. IDs exist solely for durable
    bookkeeping and are allocated independently for characters, scenes, and props.
    """
    if kind not in KIND_PREFIXES:
        raise ValueError(f"未知素材类别：{kind}")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("素材名称不能为空")
    normalized_aliases = list(dict.fromkeys(alias.strip() for alias in (aliases or []) if alias.strip() and alias.strip() != normalized_name))
    for asset in assets:
        known_names = {str(asset.get("name", "")).strip(), *[str(alias).strip() for alias in asset.get("aliases", [])]}
        if normalized_name in known_names or any(alias in known_names for alias in normalized_aliases):
            raise ValueError(f"素材名称或别名已存在：{normalized_name}")

    prefix = KIND_PREFIXES[kind]
    existing_numbers = [
        int(str(asset.get("asset_id", ""))[len(prefix) :])
        for asset in assets
        if str(asset.get("asset_id", "")).startswith(prefix)
        and str(asset.get("asset_id", ""))[len(prefix) :].isdigit()
    ]
    asset_id = f"{prefix}{max(existing_numbers, default=0) + 1:02d}"
    asset = {
        "asset_id": asset_id,
        "name": normalized_name,
        "aliases": normalized_aliases,
        "kind": kind,
        "scope": scope,
        "destination": destination,
        "views": [{"variant": Path(destination).stem, "path": destination}],
    }
    assets.append(asset)
    return asset


def register_project_asset(
    project_root: Path,
    name: str,
    kind: str,
    scope: str,
    destination: str,
    *,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Register an asset by its user-facing name and persist the updated index."""
    root = project_root.resolve()
    index_path = root / "project-settings" / "asset-index.json"
    assets: list[dict[str, Any]] = []
    if index_path.is_file():
        assets = json.loads(index_path.read_text(encoding="utf-8")).get("assets", [])
    asset = register_asset(assets, name, kind, scope, destination, aliases=aliases)
    write_asset_index(root, assets)
    return asset


def _episode_directory(project_root: Path, episode_id: str) -> Path:
    candidates = list((project_root / "episodes").glob(f"{episode_id}_*"))
    if len(candidates) != 1:
        raise ValueError(f"找不到唯一的剧集目录：{episode_id}")
    return candidates[0]


def _episode_sort_key(episode_id: str) -> tuple[int, int | str]:
    match = re.search(r"(\d+)$", episode_id)
    if match:
        return (0, int(match.group(1)))
    return (1, episode_id)


def _is_confirmed_continuity(contents: str) -> bool:
    """Recognize only the dedicated status field, not an incidental quote."""
    return any(line.strip() == "- 状态：已确认" for line in contents.splitlines())


def _immediately_previous_continuity(project_root: Path, episode_id: str) -> tuple[Path, str, bool] | None:
    """Return the closest earlier episode record, including its confirmation state.

    A pending immediate predecessor must never be skipped in favour of an older
    confirmed episode: that would produce a plausible-looking but stale handoff.
    """
    current_key = _episode_sort_key(episode_id)
    candidates: list[tuple[tuple[int, int | str], Path, str]] = []
    for episode_dir in (project_root / "episodes").iterdir():
        if not episode_dir.is_dir() or "_" not in episode_dir.name:
            continue
        candidate_id = episode_dir.name.split("_", 1)[0]
        if _episode_sort_key(candidate_id) >= current_key:
            continue
        continuity_path = episode_dir / "episode-continuity.md"
        if not continuity_path.is_file():
            continue
        contents = continuity_path.read_text(encoding="utf-8")
        candidates.append((_episode_sort_key(candidate_id), continuity_path, contents))
    if not candidates:
        return None
    _, path, contents = max(candidates, key=lambda item: item[0])
    return path, contents, _is_confirmed_continuity(contents)


def record_episode_continuity(
    project_root: Path,
    episode_id: str,
    *,
    events: list[str],
    character_states: list[str],
    ending_frame: str,
    unresolved_threads: list[str],
    next_episode_constraints: list[str],
) -> Path:
    """Confirm the durable handoff facts that the next episode must inherit."""
    if not events:
        raise ValueError("连续性记录至少需要一项本集关键事件")
    if not ending_frame.strip():
        raise ValueError("连续性记录需要最后一帧描述")
    episode_dir = _episode_directory(project_root.resolve(), episode_id)
    title = episode_dir.name.split("_", 1)[1]

    def section(title: str, items: list[str]) -> list[str]:
        cleaned_items = [item.strip() for item in items if item.strip()]
        return [f"## {title}", "", *(f"- {item}" for item in cleaned_items or ["无"]), ""]

    lines = [
        f"# {episode_id}《{title}》连续性记录",
        "",
        "- 状态：已确认",
        "- 用途：下一集创建与分镜交接时必须继承；不要依赖聊天记忆。",
        "",
    ]
    lines.extend(section("本集关键事件", events))
    lines.extend(section("角色当前状态", character_states))
    lines.extend(["## 最后一帧", "", ending_frame.strip(), ""])
    lines.extend(section("未解线索 / 钩子", unresolved_threads))
    lines.extend(section("下一集必须承接", next_episode_constraints))
    continuity_path = episode_dir / "episode-continuity.md"
    continuity_path.write_text("\n".join(lines), encoding="utf-8")
    return continuity_path


def _production_prompt(kind: str, visual_brief: str, frame_format: str) -> str:
    shared = "遵守项目角色圣经、已确认素材与视觉冲突裁决；不添加文字、Logo 或水印。"
    brief = visual_brief.rstrip("。.!！?？ ")
    if kind == "characters":
        return f"角色三视图参考：{brief}。分别生成清晰的正面、左侧、背面全身图，保持体型、配色、显著特征与材质一致。{shared}"
    if kind == "scenes":
        return f"场景三视图参考：{brief}。以 {frame_format or '项目指定画幅'} 分别输出无人物的正打、反打、侧面全景背景图，保持空间结构、主要入口和光源方向一致。{shared}"
    if kind == "props":
        return f"道具参考图：{brief}。生成干净、可辨识的独立参考图，明确材质、尺度和可被角色操作的部位。{shared}"
    raise ValueError(f"未知素材类别：{kind}")


def create_asset_production_plan(
    project_root: Path,
    episode_id: str,
    asset_requests: list[dict[str, str]],
) -> Path:
    """Create a post-outline visual production brief for this episode's new assets."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    settings = _read_project_settings(root)
    if not asset_requests:
        raise ValueError("资产生产单至少需要一项新增资产")

    manifest_path = episode_dir / "asset-production-manifest.json"
    existing_assets: list[dict[str, Any]] = []
    if manifest_path.is_file():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing_manifest.get("episode_id") not in {None, episode_id}:
            raise ValueError("资产生产单与当前剧集不匹配")
        existing_assets = existing_manifest.get("assets", [])
    names = {str(asset.get("name", "")).strip() for asset in existing_assets}
    assets: list[dict[str, Any]] = list(existing_assets)
    for request in asset_requests:
        name = request.get("name", "").strip()
        kind = request.get("kind", "").strip()
        visual_brief = request.get("visual_brief", "").strip()
        if not name or not visual_brief:
            raise ValueError("每项资产都需要名称和视觉说明")
        if name in names:
            raise ValueError(f"资产生产单已存在同名素材：{name}")
        if kind not in KIND_PREFIXES:
            raise ValueError(f"未知素材类别：{kind}")
        names.add(name)
        scope = request.get("scope", "").strip() or f"episode-{episode_id}"
        assets.append(
            {
                "name": name,
                "kind": kind,
                "scope": scope,
                "visual_brief": visual_brief,
                "prompt": _production_prompt(kind, visual_brief, settings.get("format", "")),
                "status": "planned",
                "image_path": "",
            }
        )

    manifest_path.write_text(
        json.dumps({"episode_id": episode_id, "assets": assets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# {episode_id} 本集资产生产单",
        "",
        "在大纲确认后、正式剧本与分镜前执行。生成图片后先请用户确认，再登记为本集素材并刷新交接包。",
        "",
        f"- 项目画幅：{settings.get('format') or '未设置，请先确认'}",
        f"- 默认范围：episode-{episode_id}（除非用户明确确认可复用）",
        "- 新增素材默认状态：待生成；只有确认并登记后才成为已锁定资产。",
        "",
    ]
    for position, asset in enumerate(assets, start=1):
        lines.extend(
            [
                f"## {position}. {asset['name']}（{asset['kind']}）",
                "",
                f"- 范围：{asset['scope']}",
                f"- 视觉说明：{asset['visual_brief']}",
                f"- 出图提示词：{asset['prompt']}",
                f"- 当前状态：{asset.get('status', 'planned')}",
                "- 生成后：保存图片路径 → 用户确认 → 按名称登记资产 → 刷新 `storyboard-package.md`。",
                "",
            ]
        )
    plan_path = episode_dir / "asset-production-plan.md"
    plan_path.write_text("\n".join(lines), encoding="utf-8")
    return plan_path


def resolve_asset_references(assets: list[dict[str, Any]], references: list[str]) -> list[str]:
    """Resolve user-facing names or aliases to stable internal asset IDs."""
    resolved: list[str] = []
    for reference in references:
        matches = [
            asset
            for asset in assets
            if reference == asset.get("asset_id")
            or reference == asset.get("name")
            or reference in asset.get("aliases", [])
        ]
        if not matches:
            raise ValueError(f"素材索引中找不到：{reference}")
        if len(matches) > 1:
            choices = "、".join(f"{asset.get('name', asset['asset_id'])}（{asset['asset_id']}）" for asset in matches)
            raise ValueError(f"素材名称不唯一：{reference}；请从以下候选项选择：{choices}")
        asset_id = matches[0]["asset_id"]
        if asset_id not in resolved:
            resolved.append(asset_id)
    return resolved


def _episode_state_path(episode_dir: Path) -> Path:
    return episode_dir / "episode-state.json"


def _read_episode_state(episode_dir: Path) -> dict[str, Any]:
    state_path = _episode_state_path(episode_dir)
    if not state_path.is_file():
        raise FileNotFoundError(f"本集缺少内部状态文件：{state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def _write_episode_state(episode_dir: Path, state: dict[str, Any]) -> None:
    _episode_state_path(episode_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def record_script_and_storyboard_approval(project_root: Path, episode_id: str) -> Path:
    """Record the user's approval of the current formal script and storyboard."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    missing = [name for name in ("formal-script.md", "storyboard.md") if not (episode_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"确认前缺少：{', '.join(missing)}")
    state = _read_episode_state(episode_dir)
    approved_at = datetime.now(timezone.utc).isoformat()
    state["script_and_storyboard_status"] = "user_confirmed"
    state["script_and_storyboard_confirmed_at"] = approved_at
    state.pop("keyframe_plan_status", None)
    _write_episode_state(episode_dir, state)
    review_path = episode_dir / "creative-review.md"
    review_path.write_text(
        f"# {episode_id} 剧本与分镜确认记录\n\n"
        "- 状态：已确认\n"
        f"- 确认时间：{approved_at}\n"
        "- 已确认文件：`formal-script.md`、`storyboard.md`\n"
        "- 下一步：先生成并让用户确认 `keyframe-plan.md`；未确认关键帧方案前不得出图。\n",
        encoding="utf-8",
    )
    return review_path


def recommend_keyframe_strategy(duration_seconds: float) -> str:
    """Return the default keyframe strategy for a director-board shot duration."""
    if duration_seconds <= 0:
        raise ValueError("镜头时长必须为正数")
    if duration_seconds <= 5:
        return "start_only"
    if duration_seconds == 10:
        return "start_end"
    raise ValueError("默认导演版分镜只使用 5 秒、10 秒或最后不足 5 秒的余数")


def _validate_keyframe_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        raise ValueError("关键帧方案至少需要一个镜头")
    validated: list[dict[str, Any]] = []
    shot_ids: set[str] = set()
    for shot in shots:
        shot_id = str(shot.get("shot_id", "")).strip()
        action = str(shot.get("action", "")).strip()
        strategy = str(shot.get("strategy", "")).strip()
        try:
            duration_seconds = float(shot.get("duration_seconds", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"镜头 {shot_id or '（未编号）'} 的时长必须为正数") from error
        if not shot_id or not action:
            raise ValueError("每个镜头都需要镜号和动作说明")
        if shot_id in shot_ids:
            raise ValueError(f"关键帧方案存在重复镜号：{shot_id}")
        if duration_seconds <= 0:
            raise ValueError(f"镜头 {shot_id} 的时长必须为正数")
        if strategy not in KEYFRAME_STRATEGIES:
            choices = "、".join(KEYFRAME_STRATEGIES)
            raise ValueError(f"镜头 {shot_id} 的关键帧策略无效；可选：{choices}")
        exception_reason = str(shot.get("exception_reason", "")).strip()
        default_strategy = recommend_keyframe_strategy(duration_seconds)
        if strategy == "start_middle_end":
            if duration_seconds != 10:
                raise ValueError(f"镜头 {shot_id} 的过程帧例外只适用于 10 秒镜头")
            if not exception_reason:
                raise ValueError(f"镜头 {shot_id} 需要过程帧时必须说明特殊原因")
            middle_frame_status = "requires_explicit_user_confirmation"
        elif strategy != default_strategy:
            raise ValueError(
                f"镜头 {shot_id} 默认应使用 {KEYFRAME_STRATEGIES[default_strategy][0]}；"
                "过程帧仅可作为已说明原因的 10 秒例外"
            )
        else:
            middle_frame_status = "not_requested"
        shot_ids.add(shot_id)
        label, frame_kinds = KEYFRAME_STRATEGIES[strategy]
        validated.append(
            {
                "shot_id": shot_id,
                "duration_seconds": duration_seconds,
                "action": action,
                "strategy": strategy,
                "strategy_label": label,
                "frames": frame_kinds,
                "exception_reason": exception_reason,
                "middle_frame_status": middle_frame_status,
            }
        )
    return validated


def _render_keyframe_plan(episode_id: str, shots: list[dict[str, Any]], status: str) -> str:
    total_frames = sum(len(shot["frames"]) for shot in shots)
    rows = "\n".join(
        f"| {shot['shot_id']} | {shot['duration_seconds']:g} 秒 | {len(shot['frames'])} 张（{shot['strategy_label']}） | {shot['action']} |"
        for shot in shots
    )
    exception_rows = [
        f"- 镜头 {shot['shot_id']}：{shot['exception_reason']}（{_middle_frame_status_label(shot['middle_frame_status'])}）"
        for shot in shots
        if shot.get("exception_reason")
    ]
    return (
        f"# {episode_id} 关键帧方案\n\n"
        f"- 状态：{status}\n"
        f"- 镜头数：{len(shots)}\n"
        f"- 计划关键帧总数：{total_frames}\n"
        "- 前置条件：`formal-script.md` 与 `storyboard.md` 已获用户确认。\n"
        "- 默认节奏：5 秒或最后不足 5 秒的余数使用 1 张首帧；10 秒使用首帧、尾帧 2 张。\n"
        "- 过程帧例外：仅限有明确特殊原因的 10 秒镜头；只有用户逐镜明确确认后才保留第三张，否则确认方案时自动改回首帧、尾帧。\n"
        "- 规则：确认本方案前不得生成关键帧；若要调整剧本、分镜或每镜帧数，先改本方案再确认。\n\n"
        "| 镜号 | 时长 | 关键帧数量与类型 | 图生视频要表达的单一动作 |\n"
        "| --- | ---: | --- | --- |\n"
        f"{rows}\n\n"
        "## 过程帧例外\n\n"
        + ("\n".join(exception_rows) if exception_rows else "- 无；本方案全部采用默认帧数。")
        + "\n"
    )


def _middle_frame_status_label(status: str) -> str:
    return {
        "requires_explicit_user_confirmation": "待逐镜确认",
        "user_confirmed": "已逐镜确认",
        "defaulted_to_two_frames": "未获逐镜确认，已按两帧执行",
    }.get(status, "未申请过程帧")


def create_keyframe_plan(project_root: Path, episode_id: str, shots: list[dict[str, Any]]) -> Path:
    """Create a user-reviewable per-shot keyframe plan after script and storyboard approval."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    if state.get("script_and_storyboard_status") != "user_confirmed":
        raise ValueError("剧本和分镜尚未获用户确认，不能规划关键帧")
    validated_shots = _validate_keyframe_shots(shots)
    manifest = {
        "episode_id": episode_id,
        "status": "user_pending",
        "shots": validated_shots,
    }
    (episode_dir / "keyframe-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    plan_path = episode_dir / "keyframe-plan.md"
    plan_path.write_text(_render_keyframe_plan(episode_id, validated_shots, "待用户确认"), encoding="utf-8")
    state["keyframe_plan_status"] = "user_pending"
    state["keyframe_plan_path"] = "keyframe-plan.md"
    _write_episode_state(episode_dir, state)
    return plan_path


def approve_keyframe_plan(
    project_root: Path,
    episode_id: str,
    approved_middle_shot_ids: list[str] | None = None,
) -> Path:
    """Mark the current per-shot keyframe plan user-confirmed and ready for image production."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest_path = episode_dir / "keyframe-manifest.json"
    plan_path = episode_dir / "keyframe-plan.md"
    if not manifest_path.is_file() or not plan_path.is_file():
        raise FileNotFoundError("本集尚未创建关键帧方案")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "user_pending":
        raise ValueError("关键帧方案当前不能确认")
    approved_ids = {str(shot_id).strip() for shot_id in (approved_middle_shot_ids or [])}
    if "" in approved_ids:
        raise ValueError("过程帧确认镜号不能为空")
    proposed_ids = {
        str(shot["shot_id"])
        for shot in manifest.get("shots", [])
        if shot.get("middle_frame_status") == "requires_explicit_user_confirmation"
    }
    unexpected_ids = approved_ids - proposed_ids
    if unexpected_ids:
        raise ValueError(f"未找到待确认过程帧镜头：{'、'.join(sorted(unexpected_ids))}")
    for shot in manifest.get("shots", []):
        if shot.get("middle_frame_status") != "requires_explicit_user_confirmation":
            continue
        if str(shot["shot_id"]) in approved_ids:
            shot["middle_frame_status"] = "user_confirmed"
            continue
        label, frames = KEYFRAME_STRATEGIES["start_end"]
        shot["strategy"] = "start_end"
        shot["strategy_label"] = label
        shot["frames"] = frames
        shot["middle_frame_status"] = "defaulted_to_two_frames"
    approved_at = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "user_confirmed"
    manifest["confirmed_at"] = approved_at
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan_path.write_text(_render_keyframe_plan(episode_id, manifest.get("shots", []), "已确认"), encoding="utf-8")
    state = _read_episode_state(episode_dir)
    state["keyframe_plan_status"] = "user_confirmed"
    state["keyframe_plan_confirmed_at"] = approved_at
    _write_episode_state(episode_dir, state)
    return plan_path


def assert_keyframe_generation_allowed(project_root: Path, episode_id: str) -> bool:
    """Prevent image generation until both the story review and frame-count review are approved."""
    episode_dir = _episode_directory(project_root.resolve(), episode_id)
    state = _read_episode_state(episode_dir)
    if state.get("script_and_storyboard_status") != "user_confirmed":
        raise ValueError("剧本和分镜尚未获用户确认，不能生成关键帧")
    if state.get("keyframe_plan_status") != "user_confirmed":
        raise ValueError("关键帧方案尚未获用户确认，不能生成关键帧")
    return True


KEYFRAME_EXECUTION_FIELDS = (
    "shot_size",
    "camera_movement",
    "scene",
    "start_state",
    "motion",
    "end_state",
    "dialogue",
    "voice_strategy",
    "sound_effects",
    "transition_in",
    "transition_out",
    "storyboard_image_prompt",
)


def _keyframe_filename(shot_id: str, frame_kind: str) -> str:
    """Name a generated frame by its source storyboard shot and narrative position."""
    return f"KF{shot_id}-{frame_kind}.png"


def _validate_execution_details(
    planned_shots: list[dict[str, Any]], details: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    expected_by_id = {str(shot["shot_id"]): shot for shot in planned_shots}
    actual_by_id: dict[str, dict[str, Any]] = {}
    for detail in details:
        shot_id = str(detail.get("shot_id", "")).strip()
        if not shot_id:
            raise ValueError("关键帧执行单的每项都需要镜号")
        if shot_id in actual_by_id:
            raise ValueError(f"关键帧执行单存在重复镜号：{shot_id}")
        if shot_id not in expected_by_id:
            raise ValueError(f"关键帧执行单包含未规划镜头：{shot_id}")
        actual_by_id[shot_id] = detail
    if set(actual_by_id) != set(expected_by_id):
        missing = "、".join(shot_id for shot_id in expected_by_id if shot_id not in actual_by_id)
        raise ValueError(f"关键帧执行单缺少已确认镜头：{missing}")

    validated: list[dict[str, Any]] = []
    for planned in planned_shots:
        shot_id = str(planned["shot_id"])
        detail = actual_by_id[shot_id]
        missing = [field for field in KEYFRAME_EXECUTION_FIELDS if not str(detail.get(field, "")).strip()]
        if missing:
            raise ValueError(f"镜头 {shot_id} 缺少执行字段：{', '.join(missing)}")
        references = detail.get("asset_references", [])
        if not isinstance(references, list) or not all(str(reference).strip() for reference in references):
            raise ValueError(f"镜头 {shot_id} 需要至少一个按名称说明的素材参考")
        frame_prompts = detail.get("frame_prompts", {})
        if not isinstance(frame_prompts, dict) or set(frame_prompts) != set(planned["frames"]):
            expected = "、".join(planned["frames"])
            raise ValueError(f"镜头 {shot_id} 的关键帧提示词必须恰好包含：{expected}")
        if any(not str(prompt).strip() for prompt in frame_prompts.values()):
            raise ValueError(f"镜头 {shot_id} 的关键帧提示词不能为空")
        validated.append(
            {
                "shot_id": shot_id,
                "duration_seconds": planned["duration_seconds"],
                "frame_strategy": planned["strategy"],
                "frame_strategy_label": planned["strategy_label"],
                "frames": planned["frames"],
                "action": planned["action"],
                "asset_references": [str(reference).strip() for reference in references],
                **{field: str(detail[field]).strip() for field in KEYFRAME_EXECUTION_FIELDS},
                "frame_prompts": {frame: str(frame_prompts[frame]).strip() for frame in planned["frames"]},
            }
        )
    return validated


def create_keyframe_execution_pack(
    project_root: Path,
    episode_id: str,
    shot_details: list[dict[str, Any]],
) -> Path:
    """Mirror confirmed storyboard details into a tool-ready, per-shot keyframe execution file."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_keyframe_generation_allowed(root, episode_id)
    manifest_path = episode_dir / "keyframe-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("本集尚未创建关键帧方案")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "user_confirmed":
        raise ValueError("关键帧方案尚未获用户确认，不能创建执行单")
    shots = _validate_execution_details(manifest.get("shots", []), shot_details)
    settings = _read_project_settings(root)
    frame_format = settings.get("format") or "项目指定画幅"

    blocks = [
        f"# {episode_id} 关键帧执行单",
        "",
        "本文件逐镜继承已确认分镜的时长、画面、台词、声音、转场与提示词；只额外补关键帧文件和每张帧图提示词。它不是新的剧本或简化版分镜。",
        "",
        "- 前置确认：正式剧本、导演版分镜和关键帧方案均已获用户确认。",
        f"- 画幅：{frame_format}",
        "- 图生视频规则：每镜只执行本镜动作；对白是否在视频内生成由“声音策略”决定。",
        "",
    ]
    for shot in shots:
        duration = f"{shot['duration_seconds']:g} 秒"
        reference_labels = "、".join(shot["asset_references"])
        video_prompt = (
            f"{duration}，{frame_format}，{shot['shot_size']}，{shot['camera_movement']}。"
            f"场景：{shot['scene']}。起始画面：{shot['start_state']}。"
            f"动作过程：{shot['motion']}。结束画面：{shot['end_state']}。"
            f"声音策略：{shot['voice_strategy']}；台词：{shot['dialogue']}；音效：{shot['sound_effects']}。"
            f"入点：{shot['transition_in']}。出点 / 转场：{shot['transition_out']}。"
            f"参考素材：{reference_labels}。保持角色、场景、道具与已确认素材一致；不要字幕、文字、Logo 或水印。"
        )
        frame_rows = "\n".join(
            f"| {frame} | `keyframes/pending/{_keyframe_filename(shot['shot_id'], frame)}` | {shot['frame_prompts'][frame]} |"
            for frame in shot["frames"]
        )
        blocks.extend(
            [
                f"## KF{shot['shot_id']}｜{shot['frame_strategy_label']}",
                "",
                f"- 时长：{duration}",
                f"- 景别：{shot['shot_size']}",
                f"- 运镜：{shot['camera_movement']}",
                f"- 场景：{shot['scene']}",
                f"- 素材参考：{reference_labels}",
                f"- 画面起点：{shot['start_state']}",
                f"- 动作过程：{shot['motion']}",
                f"- 画面终点：{shot['end_state']}",
                f"- 台词：{shot['dialogue']}",
                f"- 声音策略：{shot['voice_strategy']}",
                f"- 音效：{shot['sound_effects']}",
                f"- 入点：{shot['transition_in']}",
                f"- 出点 / 转场：{shot['transition_out']}",
                "",
                "### 原分镜出图提示词",
                "",
                shot["storyboard_image_prompt"],
                "",
                "### 关键帧文件与出图提示词",
                "",
                "| 帧类型 | 文件 | 出图提示词 |",
                "| --- | --- | --- |",
                frame_rows,
                "",
                "### 图生视频提示词",
                "",
                video_prompt,
                "",
            ]
        )
    execution_path = episode_dir / "keyframe-execution.md"
    execution_path.write_text("\n".join(blocks), encoding="utf-8")
    (episode_dir / "keyframe-execution-manifest.json").write_text(
        json.dumps({"episode_id": episode_id, "status": "ready", "shots": shots}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state = _read_episode_state(episode_dir)
    state["keyframe_execution_status"] = "ready"
    state["keyframe_execution_path"] = "keyframe-execution.md"
    _write_episode_state(episode_dir, state)
    return execution_path


def _write_episode_assets_file(episode_dir: Path, assets_by_id: dict[str, dict[str, Any]], state: dict[str, Any]) -> None:
    asset_ids = state.get("asset_ids", [])
    new_asset_drafts = state.get("new_asset_drafts", [])
    unknown_ids = [asset_id for asset_id in asset_ids if asset_id not in assets_by_id]
    if unknown_ids:
        raise ValueError(f"本集状态引用了不存在的素材：{', '.join(unknown_ids)}")
    (episode_dir / "episode-assets.md").write_text(
        "# 本集素材\n\n"
        "## 可用资产\n\n"
        + ("\n".join(f"- {assets_by_id[asset_id].get('name', asset_id)}（{asset_id}）" for asset_id in asset_ids) or "- 无")
        + "\n\n## 本集新增资产（待生成 / 待确认）\n\n"
        + ("\n".join(f"- {name}（默认本集专属；确认后才可提升为全局资产）" for name in new_asset_drafts) or "- 无")
        + "\n",
        encoding="utf-8",
    )


def _replace_markdown_section(contents: str, heading: str, body: str) -> str:
    marker = f"## {heading}\n\n"
    start = contents.find(marker)
    if start < 0:
        raise ValueError(f"交接包缺少章节：{heading}")
    body_start = start + len(marker)
    next_heading = contents.find("\n## ", body_start)
    if next_heading < 0:
        next_heading = len(contents)
    return contents[:body_start] + body.rstrip() + "\n\n" + contents[next_heading + 1 :]


def _refresh_episode_asset_handoff(project_root: Path, episode_id: str) -> None:
    """Refresh the asset-facing files after a confirmed episode asset changes state."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    index = json.loads((root / "project-settings" / "asset-index.json").read_text(encoding="utf-8"))
    assets_by_id = {asset["asset_id"]: asset for asset in index["assets"]}
    _write_episode_assets_file(episode_dir, assets_by_id, state)

    asset_ids = state.get("asset_ids", [])
    rows = "\n".join(
        f"| {asset['asset_id']} | {asset.get('name', asset['asset_id'])} | {asset['kind']} | {asset['scope']} | `{asset['destination']}` |"
        for asset_id in asset_ids
        for asset in [assets_by_id[asset_id]]
    )
    labels = "\n".join(
        f"- {asset['asset_id']}｜{asset.get('name', asset['asset_id'])}"
        for asset_id in asset_ids
        for asset in [assets_by_id[asset_id]]
    )
    locked_assets = (
        f"{labels or '- 无'}\n\n"
        "| ID | 名称 | 类别 | 范围 | 图片路径 |\n| --- | --- | --- | --- | --- |\n"
        f"{rows or '| — | 无 | — | — | — |'}"
    )
    drafts = "\n".join(
        f"- {name}（默认本集专属）" for name in state.get("new_asset_drafts", [])
    ) or "- 无"
    package_path = episode_dir / "storyboard-package.md"
    contents = package_path.read_text(encoding="utf-8")
    contents = _replace_markdown_section(contents, "已锁定资产", locked_assets)
    contents = _replace_markdown_section(contents, "本集新增资产（待生成 / 待确认）", drafts)
    package_path.write_text(contents, encoding="utf-8")


def _find_manifest_asset(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [asset for asset in manifest.get("assets", []) if asset.get("name") == name]
    if not matches:
        raise ValueError(f"本集资产生产单中找不到：{name}")
    if len(matches) > 1:
        raise ValueError(f"本集资产生产单中名称不唯一：{name}")
    return matches[0]


def _asset_slug(name: str) -> str:
    """Make a stable path segment without exposing user-facing names as IDs."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "asset"


def provide_episode_asset_images(
    project_root: Path,
    episode_id: str,
    name: str,
    image_paths: dict[str, Path],
) -> Path:
    """Record one or more project-local asset views, without yet making them usable."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    if not image_paths:
        raise ValueError("至少需要一张素材图片")
    relative_images: dict[str, str] = {}
    for variant, image_path in image_paths.items():
        if not re.fullmatch(r"[a-z0-9-]+", variant):
            raise ValueError(f"素材视图名称不合法：{variant}")
        image = image_path.resolve()
        if not image.is_file():
            raise FileNotFoundError(f"找不到图片：{image_path}")
        try:
            relative_images[variant] = image.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("图片必须先放入项目目录，再登记为本集资产") from error
    if len(set(relative_images.values())) != len(relative_images):
        raise ValueError("同一张图片不能重复登记为多个视图")
    manifest_path = episode_dir / "asset-production-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("本集尚未创建资产生产单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = _find_manifest_asset(manifest, name)
    if asset.get("status") not in {"planned", "image_provided"}:
        raise ValueError(f"素材当前不能接收图片：{name}（{asset.get('status')}）")
    asset["status"] = "image_provided"
    asset["image_paths"] = relative_images
    asset["image_path"] = relative_images.get("front") or next(iter(relative_images.values()))
    asset.setdefault("history", []).append(
        {"status": "image_provided", "variants": list(relative_images), "at": datetime.now(timezone.utc).isoformat()}
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def provide_episode_asset_image(project_root: Path, episode_id: str, name: str, image_path: Path) -> Path:
    """Backward-compatible single-image registration for non-view-specific assets."""
    return provide_episode_asset_images(project_root, episode_id, name, {"reference": image_path})


def confirm_episode_asset(
    project_root: Path,
    episode_id: str,
    name: str,
    *,
    aliases: list[str] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Confirm a supplied image, register it, and refresh this episode's handoff."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest_path = episode_dir / "asset-production-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("本集尚未创建资产生产单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned_asset = _find_manifest_asset(manifest, name)
    if planned_asset.get("status") != "image_provided":
        raise ValueError("请先登记图片路径，再由用户确认素材")
    image_paths = dict(planned_asset.get("image_paths", {}))
    if not image_paths:
        legacy_image_path = str(planned_asset.get("image_path", "")).strip()
        image_paths = {"reference": legacy_image_path} if legacy_image_path else {}
    if not image_paths or any(not image_path or not (root / image_path).is_file() for image_path in image_paths.values()):
        raise FileNotFoundError("已登记的素材图片不存在")
    final_scope = scope or str(planned_asset.get("scope", "")).strip()
    if not final_scope:
        raise ValueError("素材缺少范围")
    index_path = root / "project-settings" / "asset-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assets: list[dict[str, Any]] = index["assets"]
    registered = register_asset(
        assets,
        name,
        str(planned_asset["kind"]),
        final_scope,
        "pending-destination",
        aliases=aliases,
    )
    plan = build_plan(
        root,
        [
            {
                "source": image_path,
                "asset_id": registered["asset_id"],
                "kind": registered["kind"],
                "scope": final_scope,
                "slug": _asset_slug(name),
                "variant": variant,
            }
            for variant, image_path in image_paths.items()
        ],
    )
    destinations = {record["variant"]: record["destination"] for record in plan["records"]}
    preferred_variant = "front" if "front" in destinations else next(iter(destinations))
    registered["destination"] = destinations[preferred_variant]
    registered["views"] = [
        {"variant": record["variant"], "path": record["destination"]}
        for record in plan["records"]
    ]
    ledger_path = execute_plan(root, plan)
    try:
        write_asset_index(root, assets)
    except Exception:
        rollback(root, ledger_path)
        raise
    planned_asset["status"] = "user_confirmed"
    planned_asset.setdefault("history", []).append({"status": "user_confirmed", "at": datetime.now(timezone.utc).isoformat()})
    planned_asset["image_paths"] = destinations
    planned_asset["image_path"] = destinations[preferred_variant]
    planned_asset["status"] = "registered"
    planned_asset["asset_id"] = registered["asset_id"]
    planned_asset["scope"] = final_scope
    planned_asset.setdefault("history", []).append({"status": "registered", "at": datetime.now(timezone.utc).isoformat()})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state = _read_episode_state(episode_dir)
    if registered["asset_id"] not in state["asset_ids"]:
        state["asset_ids"].append(registered["asset_id"])
    state["new_asset_drafts"] = [draft for draft in state["new_asset_drafts"] if draft != name]
    _write_episode_state(episode_dir, state)
    _refresh_episode_asset_handoff(root, episode_id)
    return registered


def create_episode(
    project_root: Path,
    episode_id: str,
    episode_title: str,
    story_brief: str,
    asset_references: list[str],
    *,
    episode_overrides: dict[str, Any] | None = None,
    standalone: bool = False,
) -> Path:
    """Create an episode folder and its explicit Storyboard Generator handoff."""
    root = project_root.resolve()
    settings = _read_project_settings(root)
    overrides = episode_overrides or {}
    unknown_override_keys = set(overrides) - EPISODE_OVERRIDE_KEYS
    if unknown_override_keys:
        raise ValueError(f"不支持的本集覆盖项：{', '.join(sorted(unknown_override_keys))}")
    effective_settings = {**settings, **{key: str(value) for key, value in overrides.items()}}
    index_path = root / "project-settings" / "asset-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assets_by_id = {asset["asset_id"]: asset for asset in index["assets"]}
    asset_ids: list[str] = []
    new_asset_drafts: list[str] = []
    for reference in asset_references:
        try:
            resolved = resolve_asset_references(index["assets"], [reference])
        except ValueError as error:
            if str(error).startswith("素材索引中找不到："):
                if reference not in new_asset_drafts:
                    new_asset_drafts.append(reference)
                continue
            raise
        for asset_id in resolved:
            if asset_id not in asset_ids:
                asset_ids.append(asset_id)

    previous_continuity = _immediately_previous_continuity(root, episode_id)
    if previous_continuity is not None and not previous_continuity[2] and not standalone:
        pending_path = previous_continuity[0].relative_to(root).as_posix()
        raise ValueError(
            f"前序剧集 {pending_path} 的连续性尚未确认；请先确认，或明确声明本集为独立集"
        )

    episode_dir = root / "episodes" / f"{episode_id}_{episode_title}"
    if episode_dir.exists():
        raise FileExistsError(f"剧集目录已存在：{episode_dir}")
    episode_dir.mkdir(parents=True)
    if overrides:
        (episode_dir / "episode-overrides.yaml").write_text(
            "\n".join(f"{key}: {_yaml_string(value)}" for key, value in overrides.items()) + "\n",
            encoding="utf-8",
        )
    (episode_dir / "story-brief.md").write_text(f"# {episode_title}\n\n{story_brief}\n", encoding="utf-8")
    episode_state = {
        "version": 1,
        "episode_id": episode_id,
        "episode_title": episode_title,
        "story_brief": story_brief,
        "asset_ids": asset_ids,
        "new_asset_drafts": new_asset_drafts,
    }
    _write_episode_state(episode_dir, episode_state)
    (episode_dir / "episode-continuity.md").write_text(
        f"# {episode_id}《{episode_title}》连续性记录\n\n"
        "- 状态：待确认\n"
        "- 用途：本集定稿后记录关键事件、角色状态、最后一帧和下一集承接要求。\n",
        encoding="utf-8",
    )
    _write_episode_assets_file(episode_dir, assets_by_id, episode_state)
    rows = "\n".join(
        f"| {asset['asset_id']} | {asset.get('name', asset['asset_id'])} | {asset['kind']} | {asset['scope']} | `{asset['destination']}` |"
        for asset_id in asset_ids
        for asset in [assets_by_id[asset_id]]
    )
    asset_labels = "\n".join(
        f"- {asset['asset_id']}｜{asset.get('name', asset['asset_id'])}"
        for asset_id in asset_ids
        for asset in [assets_by_id[asset_id]]
    )
    configured_workflow = effective_settings.get("video_workflow") or "未设置；由项目负责人选择图片、视频与剪辑工具"
    configured_skill = effective_settings.get("storyboard_skill")
    context_files = [
        "project-settings/project.yaml",
        "project-settings/character-bible.md",
        "project-settings/asset-index.json",
        "project-settings/setting-conflicts.md",
    ]
    fixed_settings = root / "project-settings" / "fixed-settings-source.txt"
    if fixed_settings.is_file():
        context_files.append("project-settings/fixed-settings-source.txt")
    continuity_section = ""
    if previous_continuity is not None:
        continuity_path, continuity_contents, is_confirmed = previous_continuity
        continuity_relative_path = continuity_path.relative_to(root).as_posix()
        if is_confirmed and not standalone:
            context_files.append(continuity_relative_path)
            continuity_section = (
                "## 上集承接（锁定）\n\n"
                f"来源：`{continuity_relative_path}`。未经用户明确确认，不得改写以下连续性事实。\n\n"
                f"{continuity_contents}\n\n"
            )
    context_list = "、".join(f"`{path}`" for path in context_files)
    package = episode_dir / "storyboard-package.md"
    override_section = ""
    if overrides:
        override_section = "## 本集覆盖参数\n\n" + "\n".join(
            f"- {key}：{value}" for key, value in overrides.items()
        ) + "\n\n"
    package_contents = (
        f"# {episode_id}《{episode_title}》分镜交接包\n\n"
        "## 项目制作参数\n\n"
        f"- 受众：{effective_settings.get('audience') or '未设置，请先确认'}\n"
        f"- 画幅：{effective_settings.get('format') or '未设置，请先确认'}\n"
        f"- 目标时长：{effective_settings.get('episode_target_seconds') or '未设置，请先确认'} 秒\n"
        f"- 镜头数量{effective_settings.get('shot_count') or '由剧情节奏、动作、对白和情绪变化决定'}。\n"
        f"- 内容限制：{effective_settings.get('content_guidelines') or '未设置，请先确认'}。\n"
        f"- 制作流程：{configured_workflow}。\n\n"
        + override_section
        +
        continuity_section
        +
        "## 交接优先级\n\n"
        "本交接包与引用的项目配置是本集创作的最高优先级；它们覆盖分镜 Skill 的任何默认受众、画幅、时长、镜头数和内容尺度。\n\n"
        "## 剧情需求\n\n"
        f"{story_brief}\n\n"
        "## 已锁定资产\n\n"
        f"{asset_labels or '- 无'}\n\n"
        "| ID | 名称 | 类别 | 范围 | 图片路径 |\n| --- | --- | --- | --- | --- |\n"
        f"{rows or '| — | 无 | — | — | — |'}\n\n"
        "## 本集新增资产（待生成 / 待确认）\n\n"
        f"{chr(10).join(f'- {name}（默认本集专属）' for name in new_asset_drafts) or '- 无'}\n\n"
        "## 交给 Storyboard Generator 的任务\n\n"
        + (f"使用 `${configured_skill}`" if configured_skill else "使用项目指定的分镜 Skill")
        + f" 阅读本文件与 {context_list}，先输出故事梗概、人物小传和本集大纲，等待确认后再写 `formal-script.md` 和 `storyboard.md`。"
        "正式剧本使用场次、镜头动作和角色对白；`storyboard.md` 必须使用导演版逐镜说明，不能用 Markdown 表格替代正文。"
        "按剧情节奏、动作、对白和情绪变化智能拆镜：默认只使用 5 秒或 10 秒；总时长无法凑整时，最后一镜使用不足 5 秒的余数，禁止为凑时长添加无意义碎镜头。"
        "5 秒镜头写“关键帧画面”，默认只需一张首帧；10 秒镜头写“首帧 A 画面、尾帧 B 画面”，10 秒镜头默认首帧与尾帧两张。"
        "过程帧只可作为有明确特殊原因的 10 秒例外；先在关键帧方案写明原因并逐镜等待用户确认，未获明确确认时按两张执行。"
        "每镜必须保留：镜号、时长、景别、运镜、画面关键状态 / 动作过程、台词与口型时间段、非说话嘴型控制、声音策略、音效、入点、出点 / 转场、素材参考和分镜出图提示词。"
        "不得把分镜压缩成只有动作的一句提示。用户确认剧本和分镜后，短剧管家才会从该分镜逐镜生成关键帧执行单；执行单继承全部分镜字段，只额外增加首 / 过程 / 尾帧文件与各帧出图提示词。"
        "必须遵守上方交接优先级，不得套用冲突的默认规则。\n"
    )
    package.write_text(
        package_contents,
        encoding="utf-8",
    )
    return package
