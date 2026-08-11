#!/usr/bin/env python3
"""Create portable project files and Storyboard Generator handoff packages."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_docx_text import extract_text


KIND_PREFIXES = {"characters": "C", "scenes": "S", "props": "P"}


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


def create_episode(
    project_root: Path,
    episode_id: str,
    episode_title: str,
    story_brief: str,
    asset_references: list[str],
) -> Path:
    """Create an episode folder and its explicit Storyboard Generator handoff."""
    root = project_root.resolve()
    settings = _read_project_settings(root)
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

    episode_dir = root / "episodes" / f"{episode_id}_{episode_title}"
    if episode_dir.exists():
        raise FileExistsError(f"剧集目录已存在：{episode_dir}")
    episode_dir.mkdir(parents=True)
    (episode_dir / "story-brief.md").write_text(f"# {episode_title}\n\n{story_brief}\n", encoding="utf-8")
    (episode_dir / "episode-assets.md").write_text(
        "# 本集素材\n\n"
        "## 可用资产\n\n"
        + ("\n".join(f"- {assets_by_id[asset_id].get('name', asset_id)}（{asset_id}）" for asset_id in asset_ids) or "- 无")
        + "\n\n## 本集新增资产（待生成 / 待确认）\n\n"
        + ("\n".join(f"- {name}（默认本集专属；确认后才可提升为全局资产）" for name in new_asset_drafts) or "- 无")
        + "\n",
        encoding="utf-8",
    )
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
    configured_workflow = settings.get("video_workflow") or "未设置；由项目负责人选择图片、视频与剪辑工具"
    configured_skill = settings.get("storyboard_skill")
    context_files = [
        "project-settings/project.yaml",
        "project-settings/character-bible.md",
        "project-settings/asset-index.json",
        "project-settings/setting-conflicts.md",
    ]
    fixed_settings = root / "project-settings" / "fixed-settings-source.txt"
    if fixed_settings.is_file():
        context_files.append("project-settings/fixed-settings-source.txt")
    context_list = "、".join(f"`{path}`" for path in context_files)
    package = episode_dir / "storyboard-package.md"
    package.write_text(
        f"# {episode_id}《{episode_title}》分镜交接包\n\n"
        "## 项目制作参数\n\n"
        f"- 受众：{settings.get('audience') or '未设置，请先确认'}\n"
        f"- 画幅：{settings.get('format') or '未设置，请先确认'}\n"
        f"- 目标时长：{settings.get('episode_target_seconds') or '未设置，请先确认'} 秒\n"
        f"- 镜头数量{settings.get('shot_count') or '由剧情节奏、动作、对白和情绪变化决定'}。\n"
        f"- 内容限制：{settings.get('content_guidelines') or '未设置，请先确认'}。\n"
        f"- 制作流程：{configured_workflow}。\n\n"
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
        + f" 阅读本文件与 {context_list}，先输出故事梗概、人物小传和本集大纲，等待确认后再写正式剧本并拆分镜头表。必须遵守上方交接优先级，不得套用冲突的默认规则。\n",
        encoding="utf-8",
    )
    return package
