#!/usr/bin/env python3
"""Create portable project files and Storyboard Generator handoff packages."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize_project(project_root: Path, project_name: str, source_document: Path) -> None:
    """Create the standard project layout and move the source document once."""
    root = project_root.resolve()
    source_document = source_document.resolve()
    if source_document.parent != root or source_document.suffix.lower() != ".docx":
        raise ValueError("固定设定文档必须是项目根目录下的 .docx 文件")
    if not source_document.is_file():
        raise FileNotFoundError(source_document)

    for directory in ("project-settings", "source-material", "assets", "episodes", "templates"):
        (root / directory).mkdir(parents=True, exist_ok=True)
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
    (root / "project-settings" / "project.yaml").write_text(
        "\n".join(
            [
                f'project_name: "{project_name}"',
                "audience: \"3-8 岁\"",
                "format: \"16:9\"",
                "episode_target_seconds: 120",
                "shot_count: \"由剧情节奏、动作、对白和情绪变化决定\"",
                "visual_canon_precedence: \"confirmed_images\"",
                "video_workflow: \"关键帧图片 → 豆包图生视频 → 剪辑\"",
                "storyboard_skill: \"seedance-storyboard-generator\"",
                "source_document: \"source-material/固定设定.docx\"",
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
                "views": [],
            },
        )
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


def create_episode(
    project_root: Path,
    episode_id: str,
    episode_title: str,
    story_brief: str,
    asset_ids: list[str],
) -> Path:
    """Create an episode folder and its explicit Storyboard Generator handoff."""
    root = project_root.resolve()
    index_path = root / "project-settings" / "asset-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assets_by_id = {asset["asset_id"]: asset for asset in index["assets"]}
    missing = [asset_id for asset_id in asset_ids if asset_id not in assets_by_id]
    if missing:
        raise ValueError(f"素材索引中不存在：{', '.join(missing)}")

    episode_dir = root / "episodes" / f"{episode_id}_{episode_title}"
    if episode_dir.exists():
        raise FileExistsError(f"剧集目录已存在：{episode_dir}")
    episode_dir.mkdir(parents=True)
    (episode_dir / "story-brief.md").write_text(f"# {episode_title}\n\n{story_brief}\n", encoding="utf-8")
    (episode_dir / "episode-assets.md").write_text(
        "# 本集素材\n\n"
        "## 可用资产\n\n"
        + "\n".join(f"- {asset_id}" for asset_id in asset_ids)
        + "\n\n## 新增资产\n\n- （默认本集专属；确认后才可提升为全局资产）\n",
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
    package = episode_dir / "storyboard-package.md"
    package.write_text(
        f"# {episode_id}《{episode_title}》分镜交接包\n\n"
        "## 固定制作参数\n\n"
        "- 受众：3—8 岁\n- 画幅：16:9 横屏\n- 目标时长：120 秒\n"
        "- 镜头数量由剧情节奏决定，并综合动作、对白和情绪变化；避免无意义碎镜头。\n"
        "- 成片路径：每镜关键帧图片 → 豆包图生视频 → 剪辑成集。\n"
        "- 风格：温暖、明亮、轻松、儿童友好；不得出现恐怖、攻击性、字幕、Logo 或水印。\n\n"
        "## 剧情需求\n\n"
        f"{story_brief}\n\n"
        "## 已锁定资产\n\n"
        f"{asset_labels}\n\n"
        "| ID | 名称 | 类别 | 范围 | 图片路径 |\n| --- | --- | --- | --- | --- |\n"
        f"{rows}\n\n"
        "## 交给 Storyboard Generator 的任务\n\n"
        "使用 `$seedance-storyboard-generator` 阅读本文件、`project-settings/project.yaml`、"
        "`project-settings/fixed-settings-source.txt`、"
        "`project-settings/character-bible.md`、`project-settings/setting-conflicts.md`，先输出故事梗概、"
        "人物小传和本集大纲，等待确认后再写正式剧本并拆分镜头表。不要沿用其默认 15 秒、9:16 或固定镜头数设定。\n",
        encoding="utf-8",
    )
    return package
