#!/usr/bin/env python3
"""Validate that a generated storyboard follows the director-board production contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SHOT_PATTERN = re.compile(r"^\s*(?:#{1,6}\s*)?镜头\s*(\d+)\s*[｜|]\s*(\d+)\s*秒\s*[｜|]\s*(\S.*)\s*$")
TABLE_SHOT_PATTERN = re.compile(r"^\s*\|\s*(\d+)\s*\|\s*(\d+)\s*秒\s*\|")
BEAT_PATTERN = re.compile(
    r"(?:"
    r"\d{1,2}:\d{2}(?:\.\d+)?\s*[—–\-]\s*\d{1,2}:\d{2}(?:\.\d+)?"
    r"|"
    r"\d+(?:\.\d+)?\s*[—–\-]\s*\d+(?:\.\d+)?"
    r")"
)
REQUIRED_METADATA = ("整体时长：", "画面规格：", "固定场景：", "本集主题：")
COMMON_SECTIONS = (
    "动作过程",
    "运镜",
    "台词与口型时间段",
    "非说话嘴型控制",
    "角色声线",
    "声音策略",
    "音效",
    "入点",
    "出点 / 转场",
    "素材参考",
    "分镜出图提示词",
)
FIVE_SECOND_SECTIONS = ("关键帧画面",) + COMMON_SECTIONS
TEN_SECOND_SECTIONS = ("首帧 A 画面", "尾帧 B 画面") + COMMON_SECTIONS


def _normalized_line(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^#{1,6}\s*", "", value)
    value = value.strip("*").strip()
    return value


def _section_labels(lines: list[str]) -> set[str]:
    return {_normalized_line(line) for line in lines}


def _heading_order(lines: list[str], known: tuple[str, ...]) -> list[str]:
    known_set = set(known)
    order: list[str] = []
    for line in lines:
        label = _normalized_line(line)
        if label in known_set:
            order.append(label)
    return order


def _section_body(lines: list[str], heading: str, known: tuple[str, ...]) -> str:
    known_set = set(known)
    collecting = False
    body: list[str] = []
    for line in lines:
        label = _normalized_line(line)
        if label in known_set:
            if collecting:
                break
            collecting = label == heading
            continue
        if collecting:
            body.append(line)
    return "\n".join(body).strip()


def validate_storyboard(path: Path, target_seconds: int | None = None) -> list[str]:
    """Return structural errors; an empty list means the director contract is satisfied."""
    contents = path.read_text(encoding="utf-8")
    lines = contents.splitlines()
    errors: list[str] = []

    if not any(_normalized_line(line).startswith("《") and "导演版分镜" in line for line in lines):
        errors.append("标题必须使用《剧名》<时长>秒导演版分镜｜<场景或版本>")
    for field in REQUIRED_METADATA:
        label = field[:-1]
        has_same_line_value = any(
            re.match(rf"^\s*(?:#{1,6}\s*)?{re.escape(field)}\s*\S", line)
            for line in lines
        )
        if has_same_line_value:
            continue
        if any(_normalized_line(line).startswith(label) for line in lines):
            errors.append(f"全局字段“{label}”必须在同一行包含内容")
        else:
            errors.append(f"缺少全局字段“{label}”")
    table_shots = [match for line in lines if (match := TABLE_SHOT_PATTERN.match(line))]
    if any(line.lstrip().startswith("|") for line in lines):
        errors.append("不得使用 Markdown 表格")
    for position, match in enumerate(table_shots):
        shot_id, duration_text = match.groups()
        duration = int(duration_text)
        is_last_shot = position == len(table_shots) - 1
        if duration not in (5, 10) and not (is_last_shot and 1 <= duration <= 4):
            errors.append(f"表格镜头 {shot_id} 时长为 {duration} 秒；只允许 5 秒、10 秒或最后不足 5 秒的余数")

    shot_starts = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := SHOT_PATTERN.match(line))
    ]
    if not shot_starts:
        errors.append("至少需要一个镜头")
        return errors

    durations: list[int] = []
    for position, (start, match) in enumerate(shot_starts):
        shot_id, duration_text, _title = match.groups()
        duration = int(duration_text)
        durations.append(duration)
        end = shot_starts[position + 1][0] if position + 1 < len(shot_starts) else len(lines)
        shot_lines = lines[start + 1 : end]
        labels = _section_labels(shot_lines)
        required_sections = FIVE_SECOND_SECTIONS if duration <= 5 else TEN_SECOND_SECTIONS
        for field in required_sections:
            if field not in labels:
                errors.append(f"镜头 {shot_id} 缺少“{field}”")
        order = _heading_order(shot_lines, required_sections)
        if all(field in labels for field in required_sections) and order != list(required_sections):
            errors.append(f"镜头 {shot_id} 标题顺序必须为：{'、'.join(required_sections)}")
        motion_body = _section_body(shot_lines, "动作过程", required_sections)
        if "动作过程" in labels and not BEAT_PATTERN.search(motion_body):
            errors.append(f"镜头 {shot_id} 的“动作过程”必须写出 00:00—00:xx 时间段")
        voice_body = _section_body(shot_lines, "角色声线", required_sections)
        if "角色声线" in labels and not voice_body:
            errors.append(f"镜头 {shot_id} 的“角色声线”不能为空")

        is_last_shot = position == len(shot_starts) - 1
        if duration not in (5, 10) and not (is_last_shot and 1 <= duration <= 4):
            errors.append(f"镜头 {shot_id} 时长为 {duration} 秒；只允许 5 秒、10 秒或最后不足 5 秒的余数")
        if duration == 10 and "关键帧画面" in labels:
            errors.append(f"镜头 {shot_id} 为 10 秒镜头，必须使用首帧 A 画面和尾帧 B 画面")

    if target_seconds is not None and sum(durations) != target_seconds:
        errors.append(f"镜头总时长为 {sum(durations)} 秒，与目标 {target_seconds} 秒不一致")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--target-seconds", type=int)
    args = parser.parse_args()

    errors = validate_storyboard(args.storyboard, args.target_seconds)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
