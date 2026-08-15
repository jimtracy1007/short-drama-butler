#!/usr/bin/env python3
"""Create portable project files and Storyboard Generator handoff packages."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asset_migration import build_plan, execute_plan, rollback
from extract_docx_text import extract_text
from image_canon import resolve_production_reference_images
from story_detect import asset_is_confirmed, asset_is_lockable, detect_story_assets
from keyframe_consistency import (
    ASSET_ROLES,
    MAX_INPUT_IMAGES,
    KeyframeConsistencyError,
    build_generation_plan,
    resolve_applicable_overrides,
    resolve_keyframe_asset_uses,
    validate_continuity_contract,
)


KIND_PREFIXES = {"characters": "C", "scenes": "S", "props": "P"}
KIND_LABELS = {"characters": "新角色", "scenes": "新场景", "props": "新道具"}
ASSET_TIMINGS = ("before_storyboard", "before_keyframes", "incidental")
ASSET_TIMING_LABELS = {
    "before_storyboard": "分镜前确认",
    "before_keyframes": "关键帧前确认",
    "incidental": "随关键帧画面处理，不单独入库",
}
ASSET_TIMING_ALIASES = {
    "分镜前": "before_storyboard",
    "分镜前确认": "before_storyboard",
    "关键帧前": "before_keyframes",
    "关键帧前确认": "before_keyframes",
    "装饰": "incidental",
    "装饰性": "incidental",
    "画面内处理": "incidental",
}
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


def episode_creation_gate(
    project_root: Path, episode_id: str, *, standalone: bool = False
) -> dict[str, Any]:
    """Return whether a new episode may be created, given the previous continuity."""
    root = Path(project_root).resolve()
    previous = _immediately_previous_continuity(root, episode_id)
    if previous is not None and not previous[2] and not standalone:
        pending_path = previous[0].relative_to(root).as_posix()
        return {
            "allowed": False,
            "reason": f"前序剧集 {pending_path} 的连续性尚未确认；请先确认，或明确声明本集为独立集",
            "previous_continuity": pending_path,
        }
    return {"allowed": True, "reason": "", "previous_continuity": ""}


STORY_OUTLINE_REQUIRED_HEADINGS = ("## 故事梗概", "## 人物小传", "## 本集大纲")
STORY_OUTLINE_ASSET_CLASSIFICATION_HEADING = "## 视觉资产分级"


def _story_outline_path(episode_dir: Path) -> Path:
    return episode_dir / "story-outline.md"


def story_outline_is_confirmed(project_root: Path, episode_id: str) -> bool:
    """Return whether this episode has a user-confirmed AI story outline.

    Older completed episodes did not have this explicit gate. They remain
    readable as legacy-confirmed only once a script or storyboard already
    exists; new episodes must carry the explicit state below.
    """
    root = Path(project_root).resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    if "story_outline_status" not in state:
        return (episode_dir / "formal-script.md").is_file() or (episode_dir / "storyboard.md").is_file()
    return state.get("story_outline_status") == "user_confirmed"


def assert_story_outline_confirmed(project_root: Path, episode_id: str) -> None:
    """Refuse visual or script work until the AI story draft is approved."""
    if not story_outline_is_confirmed(project_root, episode_id):
        raise ValueError(
            "本集故事概要尚未获用户确认；请先生成并展示 story-outline.md，"
            "用户确认后运行 butler.py approve-story"
        )


def assert_asset_production_plan_current(project_root: Path, episode_id: str) -> None:
    """Require a production plan that was created after outline approval."""
    root = Path(project_root).resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_story_outline_confirmed(root, episode_id)
    state = _read_episode_state(episode_dir)
    manifest_path = episode_dir / "asset-production-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("本集尚未根据已确认故事概要创建资产生产单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("story_outline_confirmed_at") != state.get("story_outline_confirmed_at"):
        raise ValueError("资产生产单早于当前已确认故事概要；请重新运行 butler.py plan-assets")


def _validate_story_outline_body(content: str) -> str:
    body = content.strip()
    missing = [heading for heading in STORY_OUTLINE_REQUIRED_HEADINGS if heading not in body]
    if missing:
        raise ValueError("故事概要缺少必要章节：" + "、".join(missing))
    return body


def _normalize_asset_timing(value: object, *, default: str = "before_storyboard") -> str:
    timing = str(value or "").strip()
    timing = ASSET_TIMING_ALIASES.get(timing, timing or default)
    if timing not in ASSET_TIMINGS:
        raise ValueError(
            "视觉资产时机不合法："
            f"{timing}（可选：{'、'.join(ASSET_TIMINGS)}）"
        )
    return timing


def _markdown_section(contents: str, heading: str) -> str:
    marker = f"{heading}\n"
    start = contents.find(marker)
    if start < 0:
        return ""
    body_start = start + len(marker)
    next_heading = contents.find("\n## ", body_start)
    if next_heading < 0:
        next_heading = len(contents)
    return contents[body_start:next_heading]


def _outline_asset_classifications(content: str) -> list[dict[str, str]]:
    """Read the small machine-readable asset table embedded in an approved outline."""
    section = _markdown_section(content, STORY_OUTLINE_ASSET_CLASSIFICATION_HEADING)
    if not section:
        return []
    classifications: list[dict[str, str]] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|- ").split("|")]
        if len(cells) < 3 or cells[0] in {"名称", "素材名称"}:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells[:3]):
            continue
        name, kind, timing = cells[:3]
        if kind not in KIND_PREFIXES:
            raise ValueError(f"视觉资产分级中的类别不合法：{name} / {kind}")
        classifications.append(
            {
                "name": name,
                "kind": kind,
                "timing": _normalize_asset_timing(timing),
            }
        )
    return classifications


def _apply_outline_asset_classifications(state: dict[str, Any], content: str) -> None:
    """Apply outline-approved timing without making an asset usable prematurely."""
    drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
    by_name = {draft["name"]: draft for draft in drafts}
    for classification in _outline_asset_classifications(content):
        draft = by_name.get(classification["name"])
        if draft is None:
            draft = dict(classification)
            drafts.append(draft)
            by_name[draft["name"]] = draft
            continue
        if draft.get("kind") and draft["kind"] != classification["kind"]:
            raise ValueError(
                f"视觉资产分级与已检测类别冲突：{draft['name']}"
                f"（{draft['kind']} / {classification['kind']}）"
            )
        draft["kind"] = classification["kind"]
        draft["timing"] = classification["timing"]
    state["new_asset_drafts"] = drafts


def record_story_outline(project_root: Path, episode_id: str, content: str) -> Path:
    """Persist an AI-produced outline for user review without approving it."""
    root = Path(project_root).resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    if state.get("story_outline_status") == "user_confirmed":
        raise ValueError("故事概要已经确认；如需改稿，请先建立新的剧集版本")
    body = _validate_story_outline_body(content)
    _apply_outline_asset_classifications(state, body)
    title = str(state.get("episode_title") or episode_id)
    story_brief = str(state.get("story_brief") or "").strip()
    path = _story_outline_path(episode_dir)
    path.write_text(
        f"# {episode_id}《{title}》故事概要\n\n"
        "- 状态：待确认\n"
        f"- 用户故事意图：{story_brief}\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    state["story_outline_status"] = "user_pending"
    _write_episode_state(episode_dir, state)
    return path


def approve_story_outline(project_root: Path, episode_id: str) -> Path:
    """Record the user's approval of the persisted AI story outline."""
    root = Path(project_root).resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    path = _story_outline_path(episode_dir)
    if state.get("story_outline_status") != "user_pending" or not path.is_file():
        raise ValueError("本集还没有待确认的 AI 故事概要")
    contents = path.read_text(encoding="utf-8")
    _validate_story_outline_body(contents)
    if "- 状态：待确认" not in contents:
        raise ValueError("故事概要状态不是待确认，不能记录批准")
    path.write_text(contents.replace("- 状态：待确认", "- 状态：已确认", 1), encoding="utf-8")
    state["story_outline_status"] = "user_confirmed"
    state["story_outline_confirmed_at"] = datetime.now(timezone.utc).isoformat()
    _write_episode_state(episode_dir, state)
    return path


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


def _format_required_references(references: list[dict[str, Any]]) -> str:
    if not references:
        return "无（项目尚无已确认图片时，才允许按文字圣经出第一批资产）"
    return "；".join(
        f"`{item.get('path')}`（{item.get('name') or item.get('asset_id')} / {item.get('role')}）"
        for item in references
        if item.get("path")
    )


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
    *,
    timing: str | None = None,
) -> Path:
    """Create a post-outline visual production brief for this episode's new assets."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_story_outline_confirmed(root, episode_id)
    state = _read_episode_state(episode_dir)
    outline_confirmed_at = state.get("story_outline_confirmed_at")
    settings = _read_project_settings(root)
    drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
    if timing is None:
        if any(draft["timing"] == "before_storyboard" for draft in drafts):
            timing = "before_storyboard"
        elif any(draft["timing"] == "before_keyframes" for draft in drafts):
            timing = "before_keyframes"
        else:
            raise ValueError("本集没有需要单独制作的新增资产")
    timing = _normalize_asset_timing(timing)
    if timing == "incidental":
        raise ValueError("装饰性元素不创建独立资产生产单；请在对应关键帧画面中处理")
    if timing == "before_keyframes" and state.get("script_and_storyboard_status") != "user_confirmed":
        raise ValueError("延后素材应在用户确认剧本与分镜后、规划关键帧前制作")
    if not asset_requests:
        selected_drafts = [draft for draft in drafts if draft["timing"] == timing]
        unclassified = [draft["name"] for draft in selected_drafts if not draft.get("kind")]
        if unclassified:
            raise ValueError(
                f"还不能确定这些名称的类别：{'、'.join(unclassified)}。"
                "请用中文问用户那是新角色、新场景还是新道具，不要让用户填命令行。"
            )
        if not selected_drafts:
            raise ValueError("本阶段没有待生成的新资产")
        story_brief = str(state.get("story_brief") or "").strip()
        asset_requests = [
            {
                "name": draft["name"],
                "kind": draft["kind"],
                "timing": draft["timing"],
                "visual_brief": (
                    f"{draft['name']}，来自本集故事"
                    + (f"：{story_brief}" if story_brief else "")
                ),
            }
            for draft in selected_drafts
        ]

    manifest_path = episode_dir / "asset-production-manifest.json"
    existing_assets: list[dict[str, Any]] = []
    superseded_plans: list[dict[str, Any]] = []
    if manifest_path.is_file():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing_manifest.get("episode_id") not in {None, episode_id}:
            raise ValueError("资产生产单与当前剧集不匹配")
        superseded_plans = list(existing_manifest.get("superseded_plans") or [])
        if existing_manifest.get("story_outline_confirmed_at") != outline_confirmed_at:
            stale_assets = list(existing_manifest.get("assets") or [])
            unfinished = [asset for asset in stale_assets if asset.get("status") != "registered"]
            if any(asset.get("status") == "image_provided" for asset in unfinished):
                raise ValueError("旧资产生产单已有待确认图片；请先处理或归档，再按新故事概要重建")
            if unfinished:
                superseded_plans.append(
                    {
                        "reason": "story_outline_confirmed_after_plan",
                        "story_outline_confirmed_at": existing_manifest.get("story_outline_confirmed_at"),
                        "assets": unfinished,
                    }
                )
            existing_assets = [asset for asset in stale_assets if asset.get("status") == "registered"]
        else:
            existing_assets = list(existing_manifest.get("assets") or [])
    names = {str(asset.get("name", "")).strip() for asset in existing_assets}
    assets: list[dict[str, Any]] = list(existing_assets)
    for request in asset_requests:
        name = request.get("name", "").strip()
        kind = request.get("kind", "").strip()
        request_timing = _normalize_asset_timing(request.get("timing") or timing)
        visual_brief = request.get("visual_brief", "").strip()
        if not name or not visual_brief:
            raise ValueError("每项资产都需要名称和视觉说明")
        if name in names:
            raise ValueError(f"资产生产单已存在同名素材：{name}")
        if kind not in KIND_PREFIXES:
            raise ValueError(f"未知素材类别：{kind}")
        if request_timing != timing:
            raise ValueError("同一份资产生产单只能包含同一制作时机的素材")
        names.add(name)
        scope = request.get("scope", "").strip() or f"episode-{episode_id}"
        references = resolve_production_reference_images(
            root, name=name, kind=kind, visual_brief=visual_brief
        )
        prompt = _production_prompt(kind, visual_brief, settings.get("format", ""))
        if references:
            attached = "；".join(
                f"`{item['path']}`（{item.get('name') or item.get('asset_id')} / {item['role']}）"
                for item in references
            )
            prompt = f"{prompt} 必传参考图：{attached}。出图前必须把这些图作为参考输入，不得纯文生图。"
        assets.append(
            {
                "name": name,
                "kind": kind,
                "timing": request_timing,
                "scope": scope,
                "visual_brief": visual_brief,
                "prompt": prompt,
                "required_reference_images": references,
                "status": "planned",
                "image_path": "",
            }
        )

    manifest_path.write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "story_outline_confirmed_at": outline_confirmed_at,
                "assets": assets,
                "superseded_plans": superseded_plans,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# {episode_id} 本集资产生产单",
        "",
        (
            "在大纲确认后、正式剧本与分镜前执行。"
            if timing == "before_storyboard"
            else "在剧本与分镜获用户确认后、关键帧方案前执行。"
        )
        + "生成图片后先请用户确认，再登记为本集素材并刷新交接包。",
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
                f"- 制作时机：{ASSET_TIMING_LABELS.get(asset.get('timing', 'before_storyboard'))}",
                f"- 视觉说明：{asset['visual_brief']}",
                f"- 出图提示词：{asset['prompt']}",
                f"- 必传参考图：{_format_required_references(asset.get('required_reference_images') or [])}",
                f"- 当前状态：{asset.get('status', 'planned')}",
                "- 生成后：保存图片路径 → 用户确认 → 按名称登记资产 → 刷新 `storyboard-package.md`。",
                "- 出图前运行 `short-drama-butler/scripts/butler.py dispatch-asset`，先 view_image 必传参考图。",
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


def normalize_asset_drafts(drafts: list[Any]) -> list[dict[str, str]]:
    """Read legacy drafts safely, defaulting their unknown timing to pre-storyboard."""
    normalized: list[dict[str, str]] = []
    for draft in drafts or []:
        if isinstance(draft, str):
            name, kind, timing = draft.strip(), "", "before_storyboard"
        elif isinstance(draft, dict):
            name = str(draft.get("name", "")).strip()
            kind = str(draft.get("kind", "")).strip()
            timing = _normalize_asset_timing(draft.get("timing"))
        else:
            raise ValueError(f"新增资产草案格式不合法：{draft!r}")
        if not name:
            continue
        if kind and kind not in KIND_PREFIXES:
            raise ValueError(f"新增资产类别不合法：{kind}（可选：{'、'.join(KIND_PREFIXES)}）")
        normalized.append({"name": name, "kind": kind, "timing": timing})
    return normalized


def _draft_label(draft: dict[str, str]) -> str:
    kind_label = KIND_LABELS.get(draft.get("kind", ""), "类别待确认")
    timing_label = ASSET_TIMING_LABELS[draft.get("timing", "before_storyboard")]
    return f"{draft['name']}（{kind_label}；{timing_label}；默认本集专属）"


def pending_episode_assets(
    project_root: Path,
    episode_id: str,
    timing: str,
) -> list[dict[str, str]]:
    """Return required-but-unregistered assets for one workflow gate."""
    expected_timing = _normalize_asset_timing(timing)
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    state = _read_episode_state(episode_dir)
    pending: list[dict[str, str]] = []
    names: set[str] = set()
    manifest_path = episode_dir / "asset-production-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for asset in manifest.get("assets", []):
            if asset.get("status") == "registered":
                continue
            if _normalize_asset_timing(asset.get("timing")) != expected_timing:
                continue
            name = str(asset.get("name") or "").strip()
            if not name:
                continue
            names.add(name)
            pending.append(
                {
                    "name": name,
                    "kind": str(asset.get("kind") or ""),
                    "timing": expected_timing,
                    "status": str(asset.get("status") or "planned"),
                }
            )
    for draft in normalize_asset_drafts(state.get("new_asset_drafts", [])):
        if draft["timing"] != expected_timing or draft["name"] in names:
            continue
        pending.append({**draft, "status": "draft"})
    return pending


def assert_assets_confirmed_for_timing(
    project_root: Path,
    episode_id: str,
    timing: str,
) -> None:
    pending = pending_episode_assets(project_root, episode_id, timing)
    if pending:
        names = "、".join(asset["name"] for asset in pending)
        label = ASSET_TIMING_LABELS[_normalize_asset_timing(timing)]
        raise ValueError(f"以下{label}素材尚未登记：{names}")


def _reuse_label(item: dict[str, Any]) -> str:
    return (
        f"{item.get('name')}（{item.get('scope')}；本集不能自动锁定，需用户确认是否沿用）"
    )


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


def decide_reuse_asset(
    project_root: Path,
    episode_id: str,
    name: str,
    action: str,
) -> dict[str, Any]:
    """Record that an out-of-scope indexed asset is used or skipped this episode."""
    if action not in {"use", "skip"}:
        raise ValueError("沿用决定只能是 use 或 skip")
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_story_outline_confirmed(root, episode_id)
    state = _read_episode_state(episode_dir)
    candidates = list(state.get("reuse_candidates") or [])
    match = next(
        (
            item
            for item in candidates
            if str(item.get("name") or "") == name or str(item.get("asset_id") or "") == name
        ),
        None,
    )
    if match is None:
        raise ValueError(f"本集没有待确认沿用的素材：{name}")
    remaining = [
        item
        for item in candidates
        if not (
            item.get("asset_id") == match.get("asset_id") and item.get("name") == match.get("name")
        )
    ]
    if action == "skip":
        state["reuse_candidates"] = remaining
    else:
        index = json.loads((root / "project-settings" / "asset-index.json").read_text(encoding="utf-8"))
        assets_by_id = {asset["asset_id"]: asset for asset in index["assets"]}
        asset = assets_by_id.get(str(match.get("asset_id") or ""))
        if asset is None:
            raise ValueError(f"素材索引中找不到：{name}")
        if str(asset.get("scope") or "") == "pending" or not asset_is_confirmed(
            asset, project_root=root
        ):
            drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
            if not any(draft["name"] == asset.get("name") for draft in drafts):
                drafts.append(
                    {"name": str(asset.get("name") or name), "kind": str(asset.get("kind") or "")}
                )
            state["new_asset_drafts"] = drafts
        else:
            asset_id = str(asset["asset_id"])
            if asset_id not in state.get("asset_ids", []):
                state.setdefault("asset_ids", []).append(asset_id)
        state["reuse_candidates"] = remaining
    _write_episode_state(episode_dir, state)
    _refresh_episode_asset_handoff(root, episode_id)
    return {
        "episode_id": episode_id,
        "name": match.get("name") or name,
        "action": action,
        "asset_ids": list(state.get("asset_ids") or []),
        "reuse_candidates": list(state.get("reuse_candidates") or []),
        "new_asset_drafts": normalize_asset_drafts(state.get("new_asset_drafts", [])),
    }


def record_script_and_storyboard_approval(project_root: Path, episode_id: str) -> Path:
    """Record the user's approval of the current formal script and storyboard."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_story_outline_confirmed(root, episode_id)
    assert_assets_confirmed_for_timing(root, episode_id, "before_storyboard")
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
    assert_assets_confirmed_for_timing(root, episode_id, "before_keyframes")
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
    assert_assets_confirmed_for_timing(project_root.resolve(), episode_id, "before_keyframes")
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

QA_CATEGORIES = {"character", "scene", "prop", "continuity"}


def _manifest_path(episode_dir: Path) -> Path:
    return episode_dir / "keyframe-execution-manifest.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_image(root: Path, value: object, field: str) -> tuple[Path, str]:
    """Return an existing, project-local image path without allowing escape."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是项目内图片路径")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field}必须是项目内相对路径：{value}")
    candidate = (root / relative).resolve()
    try:
        relative_path = candidate.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"{field}逃出项目根目录：{value}") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"找不到{field}：{relative_path}")
    return candidate, relative_path


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_v2_manifest(episode_dir: Path) -> dict[str, Any]:
    path = _manifest_path(episode_dir)
    if not path.is_file():
        raise FileNotFoundError("本集尚未创建关键帧执行单")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") == 2:
        return manifest
    if isinstance(manifest.get("schema_version"), int) and manifest["schema_version"] > 2:
        raise ValueError("关键帧执行单 schema_version 高于本工具支持版本；拒绝读取或改写")
    # A legacy pack is intentionally not inferred or silently upgraded.  The
    # marker makes the block visible while preserving the original shot data.
    manifest["status"] = "legacy_unplanned"
    _write_json(path, manifest)
    raise ValueError("旧版关键帧执行单已标为 legacy_unplanned；请从已确认分镜重新创建 v2 执行单")


def _frame_key(shot_id: str, frame_kind: str) -> str:
    return f"KF{shot_id}-{frame_kind}"


def _find_shot(manifest: dict[str, Any], shot_id: str) -> dict[str, Any]:
    for shot in manifest.get("shots", []):
        if shot.get("shot_id") == shot_id:
            return shot
    raise ValueError(f"执行单不存在镜头：{shot_id}")


def _find_frame(manifest: dict[str, Any], shot_id: str, frame_kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    shot = _find_shot(manifest, shot_id)
    for frame in shot.get("frames", []):
        if frame.get("frame_kind") == frame_kind:
            return shot, frame
    raise ValueError(f"镜头 {shot_id} 不存在 {frame_kind} 帧")


def _find_plan(manifest: dict[str, Any], plan_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for shot in manifest.get("shots", []):
        for frame in shot.get("frames", []):
            for plan in frame.get("plans", []):
                if plan.get("plan_id") == plan_id:
                    return shot, frame, plan
    raise ValueError(f"执行单不存在计划：{plan_id}")


def _require_current_plan(frame: dict[str, Any], plan: dict[str, Any]) -> None:
    """Reject stale plan revisions before a side-effecting transition."""
    if frame.get("current_plan_id") != plan.get("plan_id"):
        raise ValueError("该计划已被新版计划取代，不能继续执行或质检")


def _supersede_runnable_plans(frame: dict[str, Any], replacement_plan_id: str) -> None:
    """Make at most one plan runnable, while retaining all audit history."""
    for plan in frame.get("plans", []):
        if plan.get("plan_id") == replacement_plan_id:
            continue
        if plan.get("status") in {"planned", "waiting_for_dependency", "reference_board_required"}:
            plan["status"] = "superseded"
            plan["superseded_by"] = replacement_plan_id
    frame["current_plan_id"] = replacement_plan_id


def _invalidate_frame_plans(frame: dict[str, Any], reason: str) -> None:
    """Retain audit history but make every previous plan non-runnable."""
    for plan in frame.get("plans", []):
        if plan.get("status") not in {"superseded", "invalidated"}:
            plan["status"] = "invalidated"
            plan["invalidated_reason"] = reason
    frame["current_plan_id"] = None


def _stage(plan: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in plan.get("stages", []):
        if stage.get("stage_id") == stage_id:
            return stage
    raise ValueError(f"计划 {plan.get('plan_id')} 不存在阶段：{stage_id}")


def _next_revision(parent: Path, suffix: str) -> tuple[str, Path]:
    parent.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        revision = f"r{index:03d}"
        candidate = parent / f"{revision}{suffix}"
        if not candidate.exists():
            return revision, candidate
        index += 1


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
        asset_uses = detail.get("asset_uses")
        if not isinstance(asset_uses, list) or not asset_uses:
            raise ValueError(f"镜头 {shot_id} 必须提供结构化 asset_uses")
        for asset_use in asset_uses:
            if not isinstance(asset_use, dict) or not isinstance(asset_use.get("reference"), str) or not asset_use["reference"].strip():
                raise ValueError(f"镜头 {shot_id} 的 asset_uses 每项都需要 reference")
            if asset_use.get("role") not in ASSET_ROLES:
                raise ValueError(f"镜头 {shot_id} 的 asset_uses 角色不合法")
            if not isinstance(asset_use.get("required"), bool):
                raise ValueError(f"镜头 {shot_id} 的 asset_uses 每项都需要布尔 required")
        frame_prompts = detail.get("frame_prompts", {})
        if not isinstance(frame_prompts, dict) or set(frame_prompts) != set(planned["frames"]):
            expected = "、".join(planned["frames"])
            raise ValueError(f"镜头 {shot_id} 的关键帧提示词必须恰好包含：{expected}")
        if any(not str(prompt).strip() for prompt in frame_prompts.values()):
            raise ValueError(f"镜头 {shot_id} 的关键帧提示词不能为空")
        frame_specs = detail.get("frame_specs")
        if not isinstance(frame_specs, dict) or set(frame_specs) != set(planned["frames"]):
            expected = "、".join(planned["frames"])
            raise ValueError(f"镜头 {shot_id} 的 frame_specs 必须恰好包含：{expected}")
        normalized_specs: dict[str, dict[str, Any]] = {}
        for frame_kind in planned["frames"]:
            raw_spec = frame_specs[frame_kind]
            if not isinstance(raw_spec, dict):
                raise ValueError(f"镜头 {shot_id} 的 {frame_kind} frame_spec 必须是对象")
            try:
                contract = validate_continuity_contract(raw_spec)
            except KeyframeConsistencyError as error:
                raise ValueError(f"镜头 {shot_id} 的 {frame_kind} frame_spec 无效：{error}") from error
            for list_field in ("allowed_changes", "invariants"):
                if list_field in raw_spec and (not isinstance(raw_spec[list_field], list) or not all(isinstance(value, str) and value.strip() for value in raw_spec[list_field])):
                    raise ValueError(f"镜头 {shot_id} 的 {frame_kind} {list_field} 必须是非空文本列表")
            normalized_specs[frame_kind] = {
                "prompt": str(frame_prompts[frame_kind]).strip(),
                "allowed_changes": list(raw_spec.get("allowed_changes", [])),
                "invariants": list(raw_spec.get("invariants", [])),
                "continuity_contract": contract,
            }
        validated.append(
            {
                "shot_id": shot_id,
                "duration_seconds": planned["duration_seconds"],
                "frame_strategy": planned["strategy"],
                "frame_strategy_label": planned["strategy_label"],
                "frames": planned["frames"],
                "action": planned["action"],
                "asset_references": [str(reference).strip() for reference in references],
                "asset_uses": [dict(asset_use) for asset_use in asset_uses],
                **{field: str(detail[field]).strip() for field in KEYFRAME_EXECUTION_FIELDS},
                "frame_prompts": {frame: str(frame_prompts[frame]).strip() for frame in planned["frames"]},
                "frame_specs": normalized_specs,
            }
        )
    return validated


def _render_v2_execution(manifest: dict[str, Any], frame_format: str) -> str:
    """Render the human-facing execution sheet from the persisted v2 source."""
    blocks = [
        f"# {manifest['episode_id']} 关键帧执行单",
        "",
        "本文件展示 v2 执行单的当前确认版；JSON 保存逐阶段输入、哈希、质检和全部版本历史。",
        "",
        f"- 状态：{manifest.get('status', 'ready')}",
        f"- 画幅：{frame_format}",
        "- 图生视频规则：每镜只执行本镜动作；对白是否在视频内生成由“声音策略”决定。",
        "",
    ]
    for shot in manifest["shots"]:
        references = "、".join(shot["asset_references"])
        duration = f"{shot['duration_seconds']:g} 秒"
        video_prompt = (
            f"{duration}，{frame_format}，{shot['shot_size']}，{shot['camera_movement']}。"
            f"场景：{shot['scene']}。起始画面：{shot['start_state']}。"
            f"动作过程：{shot['motion']}。结束画面：{shot['end_state']}。"
            f"声音策略：{shot['voice_strategy']}；台词：{shot['dialogue']}；音效：{shot['sound_effects']}。"
            f"入点：{shot['transition_in']}。出点 / 转场：{shot['transition_out']}。"
            f"参考素材：{references}。保持角色、场景、道具与已确认素材一致；不要字幕、文字、Logo 或水印。"
        )
        rows = []
        input_lines = []
        for frame in shot["frames"]:
            confirmed = frame.get("confirmed_revision") or {}
            current_path = confirmed.get("path", "待确认")
            rows.append(f"| {frame['frame_kind']} | `{current_path}` | {frame['frame_spec']['prompt']} | {frame['status']} |")
            input_lines.append(_render_frame_input_line(shot["shot_id"], frame))
        blocks.extend(
            [
                f"## KF{shot['shot_id']}｜{shot['frame_strategy_label']}",
                "",
                f"- 时长：{duration}",
                f"- 景别：{shot['shot_size']}",
                f"- 运镜：{shot['camera_movement']}",
                f"- 场景：{shot['scene']}",
                f"- 素材参考：{references}",
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
                "| 帧类型 | 当前确认文件 | 出图提示词 | 状态 |",
                "| --- | --- | --- | --- |",
                *rows,
                "",
                "### 出图必传参考图",
                "",
                "禁止只根据上方提示词纯文生图。先运行 `short-drama-butler/scripts/butler.py dispatch-keyframe`，并对下列路径逐张 view_image。",
                "",
                *input_lines,
                "",
                "### 图生视频提示词",
                "",
                video_prompt,
                "",
            ]
        )
    return "\n".join(blocks)


def _render_frame_input_line(shot_id: str, frame: dict[str, Any]) -> str:
    label = f"- KF{shot_id}-{frame['frame_kind']}"
    if frame.get("status") == "waiting_for_dependency":
        return f"{label}：等待前序确认帧，不能出图"
    current_id = frame.get("current_plan_id")
    plan = next((item for item in frame.get("plans") or [] if item.get("plan_id") == current_id), None)
    if not plan:
        return f"{label}：尚未派发；出图前必须运行 `butler.py dispatch-keyframe`"
    if plan.get("status") == "waiting_for_dependency":
        return f"{label}：等待前序确认帧，不能出图"
    listed: list[str] = []
    for stage in plan.get("stages") or []:
        paths = [
            f"`{item.get('path')}`（{item.get('role')}）"
            for item in stage.get("input_images") or []
            if item.get("path")
        ]
        if paths:
            listed.append(f"{stage.get('stage_id')}：" + "；".join(paths))
    if not listed:
        return f"{label}：当前计划没有参考图路径，禁止出图"
    return f"{label}：" + " / ".join(listed)


def create_keyframe_execution_pack(
    project_root: Path,
    episode_id: str,
    shot_details: list[dict[str, Any]],
) -> Path:
    """Create a v2, stateful execution pack from an approved keyframe plan."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    assert_keyframe_generation_allowed(root, episode_id)
    existing_manifest = _manifest_path(episode_dir)
    existing_execution = episode_dir / "keyframe-execution.md"
    if existing_manifest.exists() or existing_execution.exists():
        raise FileExistsError(
            "本集已存在关键帧执行单；为保护 legacy/v2 审计历史，拒绝重新创建或覆盖"
        )
    manifest_path = episode_dir / "keyframe-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("本集尚未创建关键帧方案")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "user_confirmed":
        raise ValueError("关键帧方案尚未获用户确认，不能创建执行单")
    shots = _validate_execution_details(manifest.get("shots", []), shot_details)
    # Resolve while creating the pack so v2 never starts from only a display
    # name.  The human-readable names remain in asset_references and Markdown.
    for shot in shots:
        try:
            shot["resolved_asset_uses"] = resolve_keyframe_asset_uses(root, shot["asset_uses"])
        except KeyframeConsistencyError as error:
            raise ValueError(f"镜头 {shot['shot_id']} 的结构化素材用途无法解析：{error}") from error
        resolved_ids = {item["asset_id"] for item in shot["resolved_asset_uses"]}
        for frame_kind, spec in shot["frame_specs"].items():
            contract = spec["continuity_contract"]
            if contract and not set(contract["asset_ids"]).issubset(resolved_ids):
                raise ValueError(f"镜头 {shot['shot_id']} 的 {frame_kind} continuity_contract 引用了未使用素材")
    v2_shots: list[dict[str, Any]] = []
    for shot in shots:
        frames = []
        frame_kinds = shot.pop("frames")
        frame_specs = shot.pop("frame_specs")
        for frame_kind in frame_kinds:
            spec = frame_specs[frame_kind]
            contract = spec["continuity_contract"]
            frames.append(
                {
                    "frame_kind": frame_kind,
                    "status": "waiting_for_dependency" if contract else "planned",
                    "frame_spec": spec,
                    "anchor_query": (
                        {"source": "confirmed_predecessor", **contract["predecessor"]} if contract else None
                    ),
                    "plans": [],
                    "current_plan_id": None,
                    "confirmed_revision": None,
                    "confirmed_revisions": [],
                }
            )
        v2_shots.append({**shot, "frames": frames})
    known_frames = {
        (shot["shot_id"], frame["frame_kind"])
        for shot in v2_shots
        for frame in shot["frames"]
    }
    for shot in v2_shots:
        for frame in shot["frames"]:
            contract = frame["frame_spec"]["continuity_contract"]
            if contract and (contract["predecessor"]["shot_id"], contract["predecessor"]["frame_kind"]) not in known_frames:
                raise ValueError(f"镜头 {shot['shot_id']} 的 {frame['frame_kind']} continuity_contract predecessor 不在本执行单中")
    execution_manifest = {
        "schema_version": 2,
        "episode_id": episode_id,
        "status": "ready",
        "created_at": _utcnow(),
        "user_overrides": [],
        "reference_boards": [],
        "shots": v2_shots,
    }
    execution_path = episode_dir / "keyframe-execution.md"
    _write_execution_pack(root, episode_dir, execution_manifest)
    state = _read_episode_state(episode_dir)
    state["keyframe_execution_status"] = "ready"
    state["keyframe_execution_path"] = "keyframe-execution.md"
    _write_episode_state(episode_dir, state)
    return execution_path


def _write_execution_pack(root: Path, episode_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path = _manifest_path(episode_dir)
    frame_format = _read_project_settings(root).get("format") or "项目指定画幅"
    execution_path = episode_dir / "keyframe-execution.md"
    manifest_temp = manifest_path.with_name(f".{manifest_path.name}.tmp")
    execution_temp = execution_path.with_name(f".{execution_path.name}.tmp")
    manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    execution_temp.write_text(_render_v2_execution(manifest, frame_format), encoding="utf-8")
    manifest_temp.replace(manifest_path)
    execution_temp.replace(execution_path)


def _plan_id(frame: dict[str, Any], shot_id: str) -> str:
    """Reserve a stable plan ID until it has reached a runnable plan state."""
    plans = frame.setdefault("plans", [])
    if plans and plans[-1].get("status") in {"waiting_for_dependency", "reference_board_required"}:
        return str(plans[-1]["plan_id"])
    return f"P-{_frame_key(shot_id, frame['frame_kind'])}-r{len(plans) + 1:03d}"


def _confirmed_anchor(manifest: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not contract:
        return None
    predecessor = contract["predecessor"]
    _, frame = _find_frame(manifest, predecessor["shot_id"], predecessor["frame_kind"])
    confirmed = frame.get("confirmed_revision")
    if not confirmed:
        return None
    return {
        "shot_id": predecessor["shot_id"],
        "frame_kind": predecessor["frame_kind"],
        "status": frame.get("status"),
        **confirmed,
    }


def _persist_override_audit(overrides: list[dict[str, Any]], applicable: dict[str, list[dict[str, Any]]]) -> None:
    """Keep root override records aligned with the scheduler's audit result."""
    by_id = {item.get("override_id"): item for item in overrides}
    for winner in applicable.get("effective", []):
        record = by_id.get(winner.get("override_id"))
        if record:
            record["status"] = "active"
            record.pop("superseded_by", None)
    for loser in applicable.get("superseded", []):
        record = by_id.get(loser.get("override_id"))
        if record:
            record["status"] = "superseded"
            record["superseded_by"] = loser["superseded_by"]


def prepare_keyframe_generation(
    project_root: Path, episode_id: str, shot_id: str, frame_kind: str
) -> dict[str, Any]:
    """Resolve one v2 frame into a persisted pure-scheduler generation plan.

    This function only prepares local state.  It intentionally invokes no image
    provider: callers hand its persisted stages to their adapter and later call
    ``record_stage_generation`` with the adapter result.
    """
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    shot, frame = _find_frame(manifest, str(shot_id), str(frame_kind))
    frame_status = frame.get("status")
    prior_plan = next(
        (plan for plan in frame.get("plans", []) if plan.get("plan_id") == frame.get("current_plan_id")),
        None,
    )
    if frame_status == "planned" and prior_plan and prior_plan.get("status") == "planned":
        return prior_plan
    if frame_status in {"failed", "needs_regeneration"} and prior_plan and prior_plan.get("status") == "planned":
        retryable = [stage for stage in prior_plan.get("stages", []) if stage.get("status") in {"failed", "needs_regeneration"}]
        if retryable:
            retry = retryable[0]
            retry_index = prior_plan["stages"].index(retry)
            if all(stage.get("status") == "qa_passed" for stage in prior_plan["stages"][:retry_index]):
                retry["status"] = "planned"
                retry.pop("error", None)
                retry.pop("regeneration_reason", None)
                frame["status"] = "planned"
                _write_execution_pack(root, episode_dir, manifest)
                return prior_plan
    if frame_status not in {"waiting_for_dependency", "planned", "needs_regeneration"}:
        raise ValueError(f"关键帧当前状态不允许准备生成：{frame_status}")
    contract = frame["frame_spec"]["continuity_contract"]
    anchor = _confirmed_anchor(manifest, contract)
    try:
        resolved_uses = resolve_keyframe_asset_uses(root, shot["asset_uses"])
        applicable = resolve_applicable_overrides(
            root, manifest.get("user_overrides", []), shot["shot_id"], {item["asset_id"] for item in resolved_uses}
        )
    except KeyframeConsistencyError as error:
        raise ValueError(f"关键帧输入无法准备：{error}") from error
    _persist_override_audit(manifest.setdefault("user_overrides", []), applicable)
    plan_id = _plan_id(frame, shot["shot_id"])
    try:
        generated = build_generation_plan(
            plan_id,
            frame["frame_spec"],
            resolved_uses,
            applicable,
            anchor,
            manifest.get("reference_boards", []),
        )
    except KeyframeConsistencyError as error:
        raise ValueError(f"关键帧计划无法生成：{error}") from error
    persisted = {
        **generated,
        "created_at": _utcnow(),
        "resolved_asset_uses": resolved_uses,
        "applicable_overrides": applicable,
    }
    plans = frame.setdefault("plans", [])
    if prior_plan and prior_plan.get("plan_id") == plan_id and prior_plan.get("status") in {"waiting_for_dependency", "reference_board_required"}:
        plans[plans.index(prior_plan)] = persisted
    else:
        plans.append(persisted)
    _supersede_runnable_plans(frame, plan_id)
    if generated["status"] == "waiting_for_dependency":
        frame["status"] = "waiting_for_dependency"
    else:
        frame["status"] = "planned"
    _write_execution_pack(root, episode_dir, manifest)
    return persisted


def request_keyframe_regeneration(
    project_root: Path, episode_id: str, shot_id: str, frame_kind: str, reason: str
) -> dict[str, Any]:
    """Record a user-authorized redo and block all direct continuity dependents.

    This is deliberately the only public route from a confirmed/reviewed frame
    back to planning.  It keeps the former plan and output history immutable,
    then prevents a downstream frame from reusing an obsolete anchor.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("重做请求必须说明原因")
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    _, frame = _find_frame(manifest, str(shot_id), str(frame_kind))
    if frame.get("status") not in {"confirmed", "pending_review", "needs_regeneration", "failed"}:
        raise ValueError(f"关键帧当前状态不允许请求重做：{frame.get('status')}")
    request_id = f"RR-{_frame_key(str(shot_id), str(frame_kind))}-r{len(frame.get('regeneration_requests', [])) + 1:03d}"
    frame.setdefault("regeneration_requests", []).append(
        {"request_id": request_id, "reason": reason.strip(), "requested_at": _utcnow()}
    )
    _invalidate_frame_plans(frame, f"用户请求重做：{reason.strip()}")
    frame["status"] = "needs_regeneration"

    invalidated: list[dict[str, str]] = []
    predecessor = {"shot_id": str(shot_id), "frame_kind": str(frame_kind)}
    for candidate_shot in manifest.get("shots", []):
        for candidate_frame in candidate_shot.get("frames", []):
            contract = candidate_frame.get("frame_spec", {}).get("continuity_contract")
            if not contract or contract.get("predecessor") != predecessor:
                continue
            _invalidate_frame_plans(candidate_frame, f"连续性锚点 {shot_id}/{frame_kind} 正在重做")
            candidate_frame["status"] = "waiting_for_dependency"
            candidate_frame["blocked_by_regeneration"] = request_id
            invalidated.append(
                {"shot_id": str(candidate_shot.get("shot_id")), "frame_kind": str(candidate_frame.get("frame_kind"))}
            )
    _write_execution_pack(root, episode_dir, manifest)
    return {"request_id": request_id, "shot_id": str(shot_id), "frame_kind": str(frame_kind), "invalidated_dependents": invalidated}


def _expected_stage_inputs(plan: dict[str, Any], stage: dict[str, Any]) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    for input_image in stage.get("input_images", []):
        if input_image.get("role") == "edit_target" and input_image.get("source") == "previous_stage":
            previous = _stage(plan, str(input_image["stage_id"]))
            qa_output = previous.get("qa_output")
            if previous.get("status") != "qa_passed" or not qa_output:
                raise ValueError("上一阶段尚未通过 QA，不能使用其作为 edit_target")
            expected.append({"role": "edit_target", "path": qa_output["path"], "sha256": qa_output["sha256"]})
        else:
            expected.append({key: input_image.get(key) for key in ("role", "path", "sha256")})
    return expected


def _rehash_stage_inputs(root: Path, expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-hash every persisted input immediately before adapter dispatch."""
    verified: list[dict[str, Any]] = []
    for image in expected:
        _, path = _project_image(root, image.get("path"), "已批准阶段输入 path")
        if not image.get("sha256") or _sha256(root / path) != image["sha256"]:
            raise ValueError(f"已批准阶段输入哈希不匹配：{path}")
        verified.append({"role": image.get("role"), "path": path, "sha256": image["sha256"]})
    return verified


def current_keyframe_plan(
    project_root: Path,
    episode_id: str,
    shot_id: str,
    frame_kind: str,
) -> dict[str, Any] | None:
    """Return the current plan for a frame without creating a new one."""
    root = Path(project_root).resolve()
    try:
        manifest = _read_v2_manifest(_episode_directory(root, episode_id))
        _, frame = _find_frame(manifest, str(shot_id), str(frame_kind))
    except (FileNotFoundError, ValueError):
        return None
    current_id = frame.get("current_plan_id")
    for plan in frame.get("plans") or []:
        if current_id and plan.get("plan_id") != current_id:
            continue
        return plan
    return None


def current_keyframe_dispatch(
    project_root: Path,
    episode_id: str,
    shot_id: str,
    frame_kind: str,
    stage_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an in-flight dispatch without preparing a new plan."""
    root = Path(project_root).resolve()
    try:
        manifest = _read_v2_manifest(_episode_directory(root, episode_id))
        _, frame = _find_frame(manifest, str(shot_id), str(frame_kind))
    except (FileNotFoundError, ValueError):
        return None
    current_id = frame.get("current_plan_id")
    for plan in frame.get("plans") or []:
        if current_id and plan.get("plan_id") != current_id:
            continue
        for stage in plan.get("stages") or []:
            if stage.get("status") != "generating" or not stage.get("dispatch"):
                continue
            if stage_id and stage.get("stage_id") != stage_id:
                continue
            return dict(stage["dispatch"])
    return None


def begin_stage_generation(
    project_root: Path, episode_id: str, plan_id: str, stage_id: str
) -> dict[str, Any]:
    """Persist the sole planned->generating dispatch before an adapter can run.

    The returned payload is the entire provider-neutral adapter contract.  It
    is intentionally the only public route that exposes a runnable request.
    """
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    _, frame, plan = _find_plan(manifest, plan_id)
    _require_current_plan(frame, plan)
    stage = _stage(plan, stage_id)
    if plan.get("status") != "planned" or stage.get("status") != "planned":
        raise ValueError("该阶段当前不允许派发生成")
    if frame.get("status") not in {"planned", "generating"}:
        raise ValueError("关键帧当前状态不允许派发生成")
    prompt = stage.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("已批准阶段缺少不可变 prompt")
    expected = _rehash_stage_inputs(root, _expected_stage_inputs(plan, stage))
    if not expected:
        raise ValueError("已批准阶段没有参考图输入；禁止纯文生图")
    if len(expected) > MAX_INPUT_IMAGES:
        raise ValueError("已批准阶段输入超过 5 张")
    dispatch_id = f"D-{plan_id}-{stage_id}-r{len(stage.get('dispatches', [])) + 1:03d}"
    dispatch = {
        "dispatch_id": dispatch_id,
        "plan_id": plan_id,
        "stage_id": stage_id,
        "prompt": prompt,
        "input_images": expected,
        "dispatched_at": _utcnow(),
    }
    stage.setdefault("dispatches", []).append(dispatch)
    stage["dispatch"] = dispatch
    stage["status"] = "generating"
    frame["status"] = "generating"
    _write_execution_pack(root, episode_dir, manifest)
    return dict(dispatch)


def _validate_generation_result(
    root: Path,
    plan_id: str,
    stage_id: str,
    result: dict[str, Any],
    dispatch: dict[str, Any],
) -> tuple[Path, str, list[dict[str, Any]]]:
    required = ("plan_id", "stage_id", "dispatch_id", "tool_request_id", "prompt", "input_images", "started_at", "completed_at")
    missing = [field for field in required if not result.get(field)]
    if missing:
        raise ValueError(f"生成结果缺少字段：{', '.join(missing)}")
    if result["plan_id"] != plan_id or result["stage_id"] != stage_id:
        raise ValueError("生成结果的 plan_id 或 stage_id 不匹配")
    if result["dispatch_id"] != dispatch.get("dispatch_id"):
        raise ValueError("生成结果不是当前已派发请求的完成结果")
    if result["prompt"] != dispatch.get("prompt"):
        raise ValueError("生成结果 prompt 与已批准阶段 prompt 不完全一致")
    actual = result["input_images"]
    if not isinstance(actual, list):
        raise ValueError("生成结果 input_images 必须是列表")
    normalized = []
    for image in actual:
        if not isinstance(image, dict):
            raise ValueError("生成结果 input_images 每项必须是对象")
        _, path = _project_image(root, image.get("path"), "生成输入 path")
        if not image.get("sha256") or _sha256(root / path) != image["sha256"]:
            raise ValueError(f"生成输入哈希不匹配：{path}")
        normalized.append({"role": image.get("role"), "path": path, "sha256": image.get("sha256")})
    if normalized != dispatch.get("input_images"):
        raise ValueError("生成结果实际输入与已批准阶段输入不完全一致")
    output, output_path = _project_image(root, result.get("output_path"), "生成 output_path")
    return output, output_path, normalized


def record_stage_generation(
    project_root: Path, episode_id: str, plan_id: str, stage_id: str, generation_result: dict[str, Any]
) -> dict[str, Any]:
    """Persist only the completion of a prior, durable dispatch."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    shot, frame, plan = _find_plan(manifest, plan_id)
    _require_current_plan(frame, plan)
    stage = _stage(plan, stage_id)
    if plan.get("status") != "planned" or stage.get("status") != "generating" or not stage.get("dispatch"):
        raise ValueError("该阶段当前不允许记录生成结果")
    dispatch = stage["dispatch"]
    if generation_result.get("error"):
        if generation_result.get("dispatch_id") != dispatch.get("dispatch_id"):
            raise ValueError("生成失败结果不是当前已派发请求的完成结果")
        stage.update({"status": "failed", "error": str(generation_result["error"]), "failed_at": _utcnow()})
        frame["status"] = "failed"
        _write_execution_pack(root, episode_dir, manifest)
        return stage
    output, source_path, inputs = _validate_generation_result(root, plan_id, stage_id, generation_result, dispatch)
    attempts = stage.setdefault("attempts", [])
    revision, destination = _next_revision(
        episode_dir / "keyframes" / "work" / _frame_key(shot["shot_id"], frame["frame_kind"]),
        f"-{stage['kind']}{output.suffix.lower() or '.png'}",
    )
    shutil.copy2(output, destination)
    record = {
        "revision": revision,
        "tool_request_id": generation_result["tool_request_id"],
        "prompt": generation_result["prompt"],
        "input_images": inputs,
        "source_output_path": source_path,
        "path": destination.relative_to(root).as_posix(),
        "sha256": _sha256(destination),
        "started_at": generation_result["started_at"],
        "completed_at": generation_result["completed_at"],
    }
    attempts.append(record)
    stage.update({"status": "generated", "generation": record, "output": {key: record[key] for key in ("revision", "path", "sha256")}})
    frame["status"] = "generating"
    _write_execution_pack(root, episode_dir, manifest)
    return record


def _validate_qa_result(result: dict[str, Any]) -> None:
    if result.get("status") not in {"pass", "uncertain", "fail"}:
        raise ValueError("QA status 必须是 pass、uncertain 或 fail")
    if result.get("reviewer_type") not in {"automated", "user"}:
        raise ValueError("QA reviewer_type 必须是 automated 或 user")
    if not result.get("checked_at"):
        raise ValueError("QA 结果缺少 checked_at")
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("QA 结果必须包含 checks")
    for check in checks:
        if not isinstance(check, dict) or check.get("category") not in QA_CATEGORIES or check.get("status") not in {"pass", "uncertain", "fail"}:
            raise ValueError("QA checks 包含非法类别或状态")
        confidence = check.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("QA check confidence 必须在 0 至 1 之间")
        if not isinstance(check.get("evidence_paths", []), list):
            raise ValueError("QA check evidence_paths 必须是列表")
    if not isinstance(result.get("issues", []), list):
        raise ValueError("QA issues 必须是列表")


def _stage_uses_board(stage: dict[str, Any]) -> bool:
    return any(item.get("role") == "reference_board" for item in stage.get("input_images", []))


def _automated_qa_covers_required_categories(stage: dict[str, Any], result: dict[str, Any]) -> bool:
    required = set(stage.get("required_qa_categories", []))
    passing = {
        check["category"]
        for check in result["checks"]
        if check["status"] == "pass" and check["confidence"] >= 0.85
    }
    return required.issubset(passing)


def _confirm_final_frame(root: Path, episode_dir: Path, shot: dict[str, Any], frame: dict[str, Any], stage: dict[str, Any]) -> None:
    output = stage["output"]
    source, _ = _project_image(root, output["path"], "QA 通过产图")
    final_dir = episode_dir / "keyframes" / "final" / _frame_key(shot["shot_id"], frame["frame_kind"])
    revision, destination = _next_revision(final_dir, source.suffix.lower() or ".png")
    shutil.copy2(source, destination)
    history = frame.setdefault("confirmed_revisions", [])
    previous = frame.get("confirmed_revision")
    if previous and not history:
        # Preserve a pre-history v2 pointer if this frame is re-confirmed after
        # the history field was introduced.
        history.append(previous)
    previous = history[-1] if history else None
    confirmed = {"revision": revision, "path": destination.relative_to(root).as_posix(), "sha256": _sha256(destination), "confirmed_at": _utcnow()}
    if previous:
        previous["superseded_by"] = revision
        confirmed["supersedes"] = previous["revision"]
    history.append(confirmed)
    frame["confirmed_revision"] = confirmed
    frame["status"] = "confirmed"


def record_stage_qa(
    project_root: Path, episode_id: str, plan_id: str, stage_id: str, qa_result: dict[str, Any]
) -> dict[str, Any]:
    """Record structured QA and perform only the legal frame-state transition."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    shot, frame, plan = _find_plan(manifest, plan_id)
    _require_current_plan(frame, plan)
    stage = _stage(plan, stage_id)
    if stage.get("status") not in {"generated", "pending_review"}:
        raise ValueError("该阶段当前不允许记录 QA")
    _validate_qa_result(qa_result)
    if stage.get("status") == "pending_review" and qa_result["reviewer_type"] != "user":
        raise ValueError("pending_review 阶段只能由用户审核决定")
    stage["qa"] = dict(qa_result)
    automated_pass = (
        qa_result["reviewer_type"] == "automated"
        and qa_result["status"] == "pass"
        and all(check["status"] == "pass" and check["confidence"] >= 0.85 for check in qa_result["checks"])
        and _automated_qa_covers_required_categories(stage, qa_result)
    )
    user_pass = qa_result["reviewer_type"] == "user" and qa_result["status"] == "pass"
    if qa_result["status"] == "uncertain" or (_stage_uses_board(stage) and not user_pass) or (qa_result["status"] == "pass" and not (automated_pass or user_pass)):
        stage["status"] = "pending_review"
        frame["status"] = "pending_review"
    elif qa_result["status"] == "fail":
        stage["status"] = "needs_regeneration"
        stage["regeneration_reason"] = qa_result.get("issues", [])
        frame["status"] = "needs_regeneration"
    else:
        stage["status"] = "qa_passed"
        stage["qa_output"] = dict(stage["output"])
        stages = plan.get("stages", [])
        if stage is stages[-1]:
            _confirm_final_frame(root, episode_dir, shot, frame, stage)
        else:
            frame["status"] = "generating"
    _write_execution_pack(root, episode_dir, manifest)
    return stage


def register_user_override(project_root: Path, episode_id: str, override: dict[str, Any]) -> dict[str, Any]:
    """Safely register a user image as a dimension-scoped local override."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    role = override.get("role")
    if role not in ASSET_ROLES:
        raise ValueError("用户覆盖 role 不合法")
    target_asset_id = override.get("target_asset_id")
    if role in {"character_identity", "prop_identity"} and not target_asset_id:
        raise ValueError(f"{role} 覆盖必须指定 target_asset_id")
    scope = override.get("scope")
    if scope not in {"shot", "continuity_run", "episode"}:
        raise ValueError("用户覆盖 scope 不合法")
    scope_ids = override.get("scope_ids", [])
    if not isinstance(scope_ids, list) or not all(isinstance(value, str) and value for value in scope_ids):
        raise ValueError("用户覆盖 scope_ids 不合法")
    shot_ids = [str(shot.get("shot_id")) for shot in manifest.get("shots", [])]
    if scope == "episode":
        if scope_ids:
            raise ValueError("episode 覆盖不能指定 scope_ids")
        effective_scope_ids = shot_ids
    else:
        if not scope_ids or any(value not in shot_ids for value in scope_ids):
            raise ValueError("用户覆盖 scope_ids 不能为空且必须是本执行单镜号")
        if scope == "continuity_run":
            if len(scope_ids) != 1:
                raise ValueError("continuity_run 覆盖必须从单一明确起始镜号展开")
            start_index = shot_ids.index(scope_ids[0])
            start_shot = manifest["shots"][start_index]
            boundary = tuple(start_shot.get(key) for key in ("scene", "time_of_day", "narrative_segment"))
            effective_scope_ids = []
            for candidate in manifest["shots"][start_index:]:
                candidate_boundary = tuple(candidate.get(key) for key in ("scene", "time_of_day", "narrative_segment"))
                if candidate_boundary != boundary:
                    break
                effective_scope_ids.append(str(candidate["shot_id"]))
            if not effective_scope_ids:
                raise ValueError("continuity_run 未能从分镜边界展开有效镜号")
        else:
            effective_scope_ids = list(scope_ids)
    if target_asset_id:
        index_path = root / "project-settings" / "asset-index.json"
        assets = json.loads(index_path.read_text(encoding="utf-8")).get("assets", []) if index_path.is_file() else []
        asset = next((item for item in assets if item.get("asset_id") == target_asset_id), None)
        expected_kind = "characters" if role == "character_identity" else "props"
        if not asset or asset.get("kind") not in {expected_kind[:-1], expected_kind}:
            raise ValueError(f"用户覆盖 target_asset_id 不存在或类别不匹配：{target_asset_id}")
        for scoped_shot_id in effective_scope_ids:
            scoped_shot = _find_shot(manifest, scoped_shot_id)
            resolved = scoped_shot.get("resolved_asset_uses", [])
            if not any(item.get("asset_id") == target_asset_id and item.get("role") == role for item in resolved):
                raise ValueError(f"用户覆盖目标不适用于镜头 {scoped_shot_id}：{target_asset_id}")
    source, source_relative = _project_image(root, override.get("path"), "用户覆盖 path")
    supplied_hash = override.get("sha256")
    source_hash = _sha256(source)
    if supplied_hash and supplied_hash != source_hash:
        raise ValueError("用户覆盖哈希不匹配")
    overrides = manifest.setdefault("user_overrides", [])
    override_id = str(override.get("override_id") or f"UO-{len(overrides) + 1:03d}")
    if any(item.get("override_id") == override_id for item in overrides):
        raise ValueError(f"用户覆盖 ID 已存在：{override_id}")
    destination_dir = root / "references" / "user"
    revision, destination = _next_revision(destination_dir, source.suffix.lower() or ".png")
    # Include the stable ID in the filename while retaining monotonic revisions.
    named_destination = destination.with_name(f"{override_id}-{revision}{destination.suffix}")
    if named_destination.exists():
        raise FileExistsError(f"用户覆盖目标已存在：{named_destination}")
    shutil.copy2(source, named_destination)
    registered = {
        "override_id": override_id,
        "path": named_destination.relative_to(root).as_posix(),
        "sha256": _sha256(named_destination),
        "role": role,
        "target_asset_id": target_asset_id,
        "scope": scope,
        "scope_ids": effective_scope_ids if scope != "episode" else [],
        "expanded_scope_ids": effective_scope_ids,
        "source": override.get("source", "user_upload"),
        "created_at": override.get("created_at", _utcnow()),
        "source_path": source_relative,
        "status": "active",
    }
    overrides.append(registered)
    for existing in overrides:
        if existing is registered:
            continue
        if (
            existing.get("role") == registered["role"]
            and existing.get("target_asset_id") == registered["target_asset_id"]
            and existing.get("scope") == registered["scope"]
            and existing.get("scope_ids") == registered["scope_ids"]
        ):
            existing["status"] = "superseded"
            existing["superseded_by"] = registered["override_id"]
    _write_execution_pack(root, episode_dir, manifest)
    return registered


def _asset_members(root: Path, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index_path = root / "project-settings" / "asset-index.json"
    assets = json.loads(index_path.read_text(encoding="utf-8")).get("assets", []) if index_path.is_file() else []
    by_id = {asset.get("asset_id"): asset for asset in assets}
    verified: list[dict[str, Any]] = []
    for member in members:
        asset_id = member.get("asset_id")
        asset = by_id.get(asset_id)
        if not asset or asset.get("status") not in {None, "confirmed"}:
            raise ValueError(f"参考板成员不是已确认资产：{asset_id}")
        source, relative = _project_image(root, member.get("path"), "参考板成员 path")
        if _sha256(source) != member.get("sha256"):
            raise ValueError(f"参考板成员哈希不匹配：{relative}")
        known_paths = {view.get("path") for view in asset.get("views", [])} | {asset.get("destination")}
        if relative not in known_paths:
            raise ValueError(f"参考板成员路径未登记到资产：{asset_id}")
        verified.append({"asset_id": asset_id, "path": relative, "sha256": member["sha256"]})
    return verified


def record_reference_board(project_root: Path, episode_id: str, board_result: dict[str, Any]) -> dict[str, Any]:
    """Persist a locally verified, unapproved board for one reserved plan/group."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    plan_id = board_result.get("plan_id")
    relationship_group = board_result.get("relationship_group")
    if not plan_id or not relationship_group:
        raise ValueError("参考板结果缺少 plan_id 或 relationship_group")
    _, _, plan = _find_plan(manifest, str(plan_id))
    if plan.get("status") != "reference_board_required" or plan.get("relationship_group") != relationship_group:
        raise ValueError("该计划当前不需要这个参考板")
    members = _asset_members(root, board_result.get("members", []))
    expected_ids = set(plan.get("asset_ids", []))
    if {member["asset_id"] for member in members} != expected_ids:
        raise ValueError("参考板成员与需要的关系组不完全一致")
    source, _ = _project_image(root, board_result.get("output_path"), "参考板 output_path")
    boards = manifest.setdefault("reference_boards", [])
    same_plan = [item for item in boards if item.get("plan_id") == plan_id and item.get("relationship_group") == relationship_group]
    revision, destination = _next_revision(root / "references" / "boards", source.suffix.lower() or ".png")
    board_id = f"RB-{plan_id}-r{len(same_plan) + 1:03d}"
    named_destination = destination.with_name(f"{board_id}{destination.suffix}")
    shutil.copy2(source, named_destination)
    board = {
        "board_id": board_id,
        "plan_id": plan_id,
        "relationship_group": relationship_group,
        "path": named_destination.relative_to(root).as_posix(),
        "sha256": _sha256(named_destination),
        "members": members,
        "member_asset_ids": [member["asset_id"] for member in members],
        "layout": board_result.get("layout", "unspecified"),
        "low_resolution_risk": bool(board_result.get("low_resolution_risk", True)),
        "approved": False,
        "created_at": _utcnow(),
    }
    boards.append(board)
    _write_execution_pack(root, episode_dir, manifest)
    return board


def approve_reference_board(project_root: Path, episode_id: str, board_id: str) -> dict[str, Any]:
    """Record explicit user approval; scheduling still has to be rerun by caller."""
    root = project_root.resolve()
    episode_dir = _episode_directory(root, episode_id)
    manifest = _read_v2_manifest(episode_dir)
    for board in manifest.get("reference_boards", []):
        if board.get("board_id") == board_id:
            if board.get("approved"):
                raise ValueError("参考板已经确认")
            board["approved"] = True
            board["approved_at"] = _utcnow()
            _write_execution_pack(root, episode_dir, manifest)
            return board
    raise ValueError(f"执行单不存在参考板：{board_id}")


def _write_episode_assets_file(episode_dir: Path, assets_by_id: dict[str, dict[str, Any]], state: dict[str, Any]) -> None:
    asset_ids = state.get("asset_ids", [])
    new_asset_drafts = normalize_asset_drafts(state.get("new_asset_drafts", []))
    unknown_ids = [asset_id for asset_id in asset_ids if asset_id not in assets_by_id]
    if unknown_ids:
        raise ValueError(f"本集状态引用了不存在的素材：{', '.join(unknown_ids)}")
    (episode_dir / "episode-assets.md").write_text(
        "# 本集素材\n\n"
        "## 可用资产\n\n"
        + ("\n".join(f"- {assets_by_id[asset_id].get('name', asset_id)}（{asset_id}）" for asset_id in asset_ids) or "- 无")
        + "\n\n## 其他范围素材（需确认是否沿用）\n\n"
        + (
            "\n".join(f"- {_reuse_label(item)}" for item in state.get("reuse_candidates") or [])
            or "- 无"
        )
        + "\n\n## 本集新增资产（待生成 / 待确认）\n\n"
        + ("\n".join(f"- {_draft_label(draft)}；确认后才可提升为全局资产" for draft in new_asset_drafts) or "- 无")
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
        f"- {_draft_label(draft)}" for draft in normalize_asset_drafts(state.get("new_asset_drafts", []))
    ) or "- 无"
    reuse = "\n".join(f"- {_reuse_label(item)}" for item in state.get("reuse_candidates") or []) or "- 无"
    package_path = episode_dir / "storyboard-package.md"
    contents = package_path.read_text(encoding="utf-8")
    contents = _replace_markdown_section(contents, "已锁定资产", locked_assets)
    contents = _replace_markdown_section(contents, "其他范围素材（需确认是否沿用）", reuse)
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
    assert_asset_production_plan_current(root, episode_id)
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
    assert_asset_production_plan_current(root, episode_id)
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
    state["new_asset_drafts"] = [
        draft for draft in normalize_asset_drafts(state.get("new_asset_drafts", [])) if draft["name"] != name
    ]
    _write_episode_state(episode_dir, state)
    _refresh_episode_asset_handoff(root, episode_id)
    return registered


def create_episode(
    project_root: Path,
    episode_id: str,
    episode_title: str,
    story_brief: str,
    asset_references: list[str | dict[str, str]],
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
    detection = detect_story_assets(
        story_brief, index["assets"], episode_id=episode_id, project_root=root
    )
    asset_ids: list[str] = [
        str(item["asset_id"]) for item in detection["known_assets"] if item.get("asset_id")
    ]
    new_asset_drafts: list[dict[str, str]] = list(detection["new_asset_drafts"])
    reuse_candidates: list[dict[str, Any]] = list(detection.get("reuse_candidates") or [])
    for entry in asset_references:
        if isinstance(entry, dict):
            reference = str(entry.get("name", "")).strip()
            requested_kind = str(entry.get("kind", "")).strip()
        else:
            reference, requested_kind = str(entry).strip(), ""
        if not reference:
            continue
        try:
            resolved = resolve_asset_references(index["assets"], [reference])
        except ValueError as error:
            if str(error).startswith("素材索引中找不到："):
                existing = next((draft for draft in new_asset_drafts if draft["name"] == reference), None)
                if existing:
                    if requested_kind and not existing.get("kind"):
                        existing["kind"] = requested_kind
                else:
                    new_asset_drafts.extend(
                        normalize_asset_drafts([{"name": reference, "kind": requested_kind}])
                    )
                continue
            raise
        for asset_id in resolved:
            asset = assets_by_id[asset_id]
            if asset_is_lockable(asset, episode_id, project_root=root):
                if asset_id not in asset_ids:
                    asset_ids.append(asset_id)
                continue
            if asset_id not in {item.get("asset_id") for item in reuse_candidates}:
                reuse_candidates.append(
                    {
                        "asset_id": asset_id,
                        "name": asset.get("name") or asset_id,
                        "kind": asset.get("kind"),
                        "scope": asset.get("scope"),
                    }
                )

    gate = episode_creation_gate(root, episode_id, standalone=standalone)
    if not gate["allowed"]:
        raise ValueError(gate["reason"])
    previous_continuity = _immediately_previous_continuity(root, episode_id)

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
        "story_outline_status": "draft_pending",
        "asset_ids": asset_ids,
        "new_asset_drafts": new_asset_drafts,
        "reuse_candidates": reuse_candidates,
        "detected_asset_notice": detection["user_notice"],
    }
    _write_episode_state(episode_dir, episode_state)
    _story_outline_path(episode_dir).write_text(
        f"# {episode_id}《{episode_title}》故事概要\n\n"
        "- 状态：待生成\n"
        f"- 用户故事意图：{story_brief}\n\n"
        "## 故事梗概\n\n待 AI 根据项目设定生成。\n\n"
        "## 人物小传\n\n待 AI 根据已锁定角色与本集需求生成。\n\n"
        "## 本集大纲\n\n待 AI 生成可确认的起承转合。\n\n"
        "## 视觉资产分级\n\n"
        "待 AI 按 `名称 | 类别 | 时机 | 理由` 列出；时机只能是 "
        "`before_storyboard`、`before_keyframes` 或 `incidental`。\n",
        encoding="utf-8",
    )
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
        "## 本集故事概要（必须先确认）\n\n"
        "先由 Storyboard Generator 根据本交接包写入 `story-outline.md`，至少包含“故事梗概、人物小传、本集大纲、视觉资产分级”。"
        "展示给用户确认后，运行 `butler.py approve-story --episode <ID>`。确认前不得创建资产生产单、派发素材图、写正式剧本或分镜。\n\n"
        "## 已锁定资产\n\n"
        f"{asset_labels or '- 无'}\n\n"
        "| ID | 名称 | 类别 | 范围 | 图片路径 |\n| --- | --- | --- | --- | --- |\n"
        f"{rows or '| — | 无 | — | — | — |'}\n\n"
        "## 其他范围素材（需确认是否沿用）\n\n"
        f"{chr(10).join(f'- {_reuse_label(item)}' for item in reuse_candidates) or '- 无'}\n\n"
        "## 本集新增资产（待生成 / 待确认）\n\n"
        f"{chr(10).join(f'- {_draft_label(draft)}' for draft in new_asset_drafts) or '- 无'}\n\n"
        "## 交给 Storyboard Generator 的任务\n\n"
        + (f"使用 `${configured_skill}`" if configured_skill else "使用项目指定的分镜 Skill")
        + f" 阅读本文件与 {context_list}，先生成并登记 `story-outline.md`（故事梗概、人物小传、本集大纲和视觉资产分级），展示给用户确认。"
        "用户确认并通过 `butler.py approve-story` 前，不得计划或生成任何新素材，也不得写 `formal-script.md` 或 `storyboard.md`。"
        "视觉资产分级须逐行使用 `名称 | characters|scenes|props | before_storyboard|before_keyframes|incidental | 理由`。"
        "其中 `before_storyboard` 先确认，`before_keyframes` 在剧本与分镜确认后、关键帧方案前确认，`incidental` 不创建独立素材。"
        "故事概要确认、分镜前素材确认后，才写 `formal-script.md` 和 `storyboard.md`。"
        "正式剧本使用场次、镜头动作和角色对白；`storyboard.md` 必须使用导演版逐镜说明，不能用 Markdown 表格替代正文。"
        "开头固定为“《剧名》<本集目标时长>秒导演版分镜｜<主要场景或版本>”，随后各占一行写“整体时长：…、画面规格：…、固定场景：…、本集主题：…”，标签和内容不得拆行。"
        "按剧情节奏、动作、对白和情绪变化智能拆镜：默认只使用 5 秒或 10 秒；总时长无法凑整时，最后一镜使用不足 5 秒的余数，禁止为凑时长添加无意义碎镜头。"
        "5 秒镜头写“关键帧画面”，默认只需一张首帧；10 秒镜头写“首帧 A 画面、尾帧 B 画面”，10 秒镜头默认首帧与尾帧两张。"
        "过程帧只可作为有明确特殊原因的 10 秒例外；先在关键帧方案写明原因并逐镜等待用户确认，未获明确确认时按两张执行。"
        "每镜必须保留：镜号、时长、景别、运镜、画面关键状态 / 动作过程、台词与口型时间段、非说话嘴型控制、声音策略、音效、入点、出点 / 转场、素材参考和分镜出图提示词。"
        "5 秒镜头的独立标题顺序固定为：关键帧画面、运镜、台词与口型时间段、非说话嘴型控制、声音策略、音效、入点、出点 / 转场、素材参考、分镜出图提示词。"
        "10 秒镜头的独立标题顺序固定为：首帧 A 画面、尾帧 B 画面、运镜、台词与口型时间段、非说话嘴型控制、声音策略、音效、入点、出点 / 转场、素材参考、分镜出图提示词。"
        "写完后、展示给用户前，必须运行 `short-drama-butler/scripts/validate_director_storyboard.py --storyboard <本集 storyboard.md> --target-seconds <本集目标时长>`；任何表格、6 / 7 秒镜头或缺失标题都必须修正后才可进入确认。"
        "不得把分镜压缩成只有动作的一句提示。用户确认剧本和分镜后，短剧管家才会从该分镜逐镜生成关键帧执行单；执行单继承全部分镜字段，只额外增加首 / 过程 / 尾帧文件与各帧出图提示词。"
        "必须遵守上方交接优先级，不得套用冲突的默认规则。\n"
    )
    package.write_text(
        package_contents,
        encoding="utf-8",
    )
    return package
