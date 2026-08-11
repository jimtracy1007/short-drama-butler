#!/usr/bin/env python3
"""Detect and install the optional Storyboard Generator sibling Skill."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


SKILL_NAME = "seedance-storyboard-generator"
UPSTREAM_ARCHIVE_URL = "https://github.com/liangdabiao/Seedance2-Storyboard-Generator/archive/refs/heads/main.zip"
UPSTREAM_SKILL_SUFFIX = Path(".claude/skills") / SKILL_NAME


class DependencyError(RuntimeError):
    """Raised when the storyboard dependency cannot be installed safely."""


def find_installed_skill(skill_roots: list[Path]) -> Path | None:
    """Return the first valid sibling skill directory, if any."""
    for root in skill_roots:
        candidate = root / SKILL_NAME
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def extract_skill_from_archive(archive: zipfile.ZipFile, skill_root: Path) -> Path:
    """Install only the upstream Skill subtree, refusing to overwrite a sibling."""
    destination = skill_root / SKILL_NAME
    if destination.exists():
        raise DependencyError(f"目标 Skill 已存在：{destination}")

    matching_names = [
        name
        for name in archive.namelist()
        if Path(name).as_posix().endswith(UPSTREAM_SKILL_SUFFIX.as_posix())
        or f"/{UPSTREAM_SKILL_SUFFIX.as_posix()}/" in Path(name).as_posix()
    ]
    if not matching_names:
        raise DependencyError("上游压缩包中找不到 seedance-storyboard-generator")

    skill_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="storyboard-skill-", dir=skill_root) as temporary:
        staging = Path(temporary) / SKILL_NAME
        suffix = f"/{UPSTREAM_SKILL_SUFFIX.as_posix()}/"
        for member in archive.infolist():
            name = member.filename
            if suffix not in name or member.is_dir():
                continue
            relative = Path(name.split(suffix, 1)[1])
            if not relative.parts or ".." in relative.parts:
                raise DependencyError(f"不安全的上游文件路径：{name}")
            output = staging / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
        if not (staging / "SKILL.md").is_file():
            raise DependencyError("上游 Skill 缺少 SKILL.md")
        staging.replace(destination)
    return destination


def install_skill(skill_root: Path, archive_url: str = UPSTREAM_ARCHIVE_URL) -> Path:
    """Download the public upstream archive and install the precise Skill subtree."""
    try:
        with urllib.request.urlopen(archive_url, timeout=30) as response:
            archive_bytes = response.read()
    except OSError as error:
        raise DependencyError(f"无法下载 Storyboard Generator：{error}") from error
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            return extract_skill_from_archive(archive, skill_root)
    except zipfile.BadZipFile as error:
        raise DependencyError("上游下载内容不是有效 ZIP 文件") from error


def default_skill_roots() -> list[Path]:
    """Prioritize the directory containing this Skill, then common Codex roots."""
    roots = [Path(__file__).resolve().parents[2]]
    roots.extend([Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"])
    unique_roots: list[Path] = []
    for root in roots:
        if root not in unique_roots:
            unique_roots.append(root)
    return unique_roots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, help="Skill sibling directory; defaults to this Skill's directory")
    parser.add_argument("--install", action="store_true", help="Install upstream only when the dependency is absent")
    args = parser.parse_args()

    roots = [args.skills_root.resolve()] if args.skills_root else default_skill_roots()
    installed = find_installed_skill(roots)
    if installed is None and args.install:
        installed = install_skill(roots[0])
    print(
        json.dumps(
            {
                "installed": installed is not None,
                "path": str(installed) if installed else None,
                "source": "liangdabiao/Seedance2-Storyboard-Generator",
            },
            ensure_ascii=False,
        )
    )
    if installed is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
