#!/usr/bin/env python3
"""Detect known and new assets from a natural-language story.

Users only say things like “小鸟和咕噜在森林里快乐的一天”.  This module
returns lockable confirmed assets plus conservative drafts.  Uncertain names
stay unclassified so the agent must ask in Chinese before storyboard work.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


DISTINCTIVE_SCENES = (
    "泡泡湾",
    "旧书店",
    "森林",
    "树林",
    "海滩",
    "海边",
    "沙滩",
    "海湾",
    "卧室",
    "客厅",
    "厨房",
    "教室",
    "学校",
    "医院",
    "公园",
    "广场",
    "山洞",
    "洞穴",
    "城堡",
    "夜市",
    "村庄",
    "草地",
    "花园",
    "码头",
    "港口",
    "沙漠",
    "雪山",
    "瀑布",
    "河边",
    "湖边",
)
PROP_NAMES = (
    "录音笔",
    "贝壳",
    "钥匙",
    "书包",
    "灯笼",
    "宝箱",
    "地图",
    "信件",
    "电话",
    "雨伞",
    "帽子",
    "气球",
    "风筝",
    "木船",
    "小船",
)
CREATURE_CHARS = "鸟猫狗兔熊鱼蟹鼠龙蛙鸭鸡猪猴象鹿狼狐虫蝶马牛羊怪兽人精螃"
CHARACTER_NAMES = (
    "小螃蟹",
    "小兔子",
    "小鸟",
    "小鱼",
    "小猫",
    "小狗",
    "小熊",
    "小鹿",
    "小狼",
    "小狐狸",
)
ROLE_NAMES = (
    "管理员",
    "老师",
    "警察",
    "医生",
    "店员",
    "妈妈",
    "爸爸",
    "奶奶",
    "爷爷",
)
STOPWORDS = {
    "快乐",
    "一天",
    "一起",
    "故事",
    "然后",
    "开始",
    "今天",
    "我们",
    "他们",
    "这个",
    "那个",
    "时候",
    "突然",
    "于是",
    "因为",
    "所以",
    "但是",
    "可是",
    "还是",
    "非常",
    "真的",
    "什么",
    "怎么",
    "没有",
    "不是",
    "一个",
    "一次",
    "这里",
    "那里",
    "现在",
    "已经",
    "正在",
    "出来",
    "过去",
    "回来",
    "看见",
    "发现",
    "觉得",
    "知道",
    "想要",
    "决定",
    "帮忙",
    "帮助",
    "玩耍",
    "游戏",
    "朋友",
    "新朋友",
    "认识",
    "测试",
    "剧情",
    "分享",
    "玩具",
    "学习",
    "宝藏",
    "一支",
    "走进",
}
NAME_TRAIL = "一起去在找来到走回说看玩吃了着的把向对给跟和与"
UNCONFIRMED_ASSET_STATUSES = frozenset({"planned", "image_provided", "user_pending", "pending"})
CONFIRMED_ASSET_STATUSES = frozenset({"registered", "user_confirmed", "confirmed"})


def _tokens(asset: dict[str, Any]) -> list[str]:
    values = [asset.get("name"), *asset.get("aliases", [])]
    return [str(value).strip() for value in values if str(value).strip() and len(str(value).strip()) >= 2]


def _scope_allows_lock(asset: dict[str, Any], episode_id: str | None = None) -> bool:
    scope = str(asset.get("scope") or "")
    if not scope or scope == "pending":
        return False
    if scope == "global" or scope.startswith("season-"):
        return True
    return bool(episode_id) and scope == f"episode-{episode_id}"


def asset_is_confirmed(asset: dict[str, Any], *, project_root: Path | None = None) -> bool:
    """True only when the asset is registered/confirmed and has a usable image view."""
    status = str(asset.get("status") or "").strip()
    if status in UNCONFIRMED_ASSET_STATUSES:
        return False
    if status and status not in CONFIRMED_ASSET_STATUSES:
        return False
    views = [view for view in asset.get("views") or [] if view.get("path")]
    paths = [str(view["path"]) for view in views]
    if not paths and asset.get("destination"):
        paths = [str(asset["destination"])]
    if not paths:
        return False
    if project_root is None:
        return True
    root = Path(project_root).resolve()
    for path in paths:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        if (root / relative).is_file():
            return True
    return False


def asset_is_lockable(
    asset: dict[str, Any],
    episode_id: str | None = None,
    *,
    project_root: Path | None = None,
) -> bool:
    """Only confirmed in-scope assets with real image views may lock."""
    return _scope_allows_lock(asset, episode_id) and asset_is_confirmed(
        asset, project_root=project_root
    )


def infer_asset_kind(name: str) -> str:
    """Return a kind only when the name itself is distinctive; otherwise leave blank."""
    text = name.strip()
    if not text:
        return ""
    if text in PROP_NAMES or any(text.endswith(item) for item in PROP_NAMES):
        return "props"
    if text in DISTINCTIVE_SCENES or any(text.endswith(item) for item in DISTINCTIVE_SCENES):
        return "scenes"
    if text in CHARACTER_NAMES or text in ROLE_NAMES:
        return "characters"
    if text.startswith("小") and 2 <= len(text) <= 4:
        rest = text[1:]
        if rest and all(char in CREATURE_CHARS for char in rest):
            return "characters"
        if any(rest.endswith(item) or item in rest for item in PROP_NAMES):
            return "props"
        return "characters"
    return ""


def _replace_all(text: str, token: str) -> str:
    if not token or token not in text:
        return text
    return text.replace(token, " " * len(token))


def _contained_in_longer(name: str, pool: tuple[str, ...], haystack: str) -> bool:
    return any(longer != name and name in longer and longer in haystack for longer in pool)


def detect_story_assets(
    text: str,
    indexed_assets: list[dict[str, Any]],
    extra_references: list[str | dict[str, str]] | None = None,
    *,
    episode_id: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Find lockable confirmed assets and conservative new-asset drafts."""
    haystack = str(text or "")
    remaining = haystack
    known: list[dict[str, Any]] = []
    reuse_candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    indexed = sorted(
        indexed_assets,
        key=lambda item: max((len(token) for token in _tokens(item)), default=0),
        reverse=True,
    )
    for asset in indexed:
        matched = next(
            (token for token in sorted(_tokens(asset), key=len, reverse=True) if token and token in remaining),
            None,
        )
        if not matched:
            continue
        record = {
            "asset_id": str(asset.get("asset_id") or ""),
            "name": asset.get("name") or asset.get("asset_id"),
            "kind": asset.get("kind"),
            "scope": asset.get("scope"),
        }
        remaining = _replace_all(remaining, matched)
        seen_names.add(str(record["name"] or ""))
        for alias in _tokens(asset):
            seen_names.add(alias)
        if not record["asset_id"] or record["asset_id"] in seen_ids:
            continue
        seen_ids.add(record["asset_id"])
        if asset_is_lockable(asset, episode_id, project_root=project_root):
            known.append(record)
        else:
            reuse_candidates.append(record)

    drafts: list[dict[str, str]] = []

    def add_draft(name: str, kind: str = "") -> None:
        cleaned = re.sub(r"[的了着过和与在]+$", "", name.strip())
        if not cleaned or cleaned in STOPWORDS or cleaned in seen_names:
            return
        if any(cleaned == item.get("name") for item in known):
            return
        if any(cleaned == item.get("name") for item in reuse_candidates):
            return
        inferred = kind or infer_asset_kind(cleaned)
        existing = next((item for item in drafts if item["name"] == cleaned), None)
        if existing:
            if not existing["kind"] and inferred:
                existing["kind"] = inferred
            return
        drafts.append({"name": cleaned, "kind": inferred})
        seen_names.add(cleaned)

    for reference in extra_references or []:
        if isinstance(reference, dict):
            add_draft(str(reference.get("name", "")), str(reference.get("kind", "")))
        else:
            add_draft(str(reference))

    for match in re.finditer(r"在([\u4e00-\u9fff]{2,6}?)(?:里|中)", remaining):
        add_draft(match.group(1), "scenes")
        remaining = _replace_all(remaining, match.group(1))

    for scene in sorted(DISTINCTIVE_SCENES, key=len, reverse=True):
        if scene in remaining and not _contained_in_longer(scene, DISTINCTIVE_SCENES, remaining):
            add_draft(scene, "scenes")
            remaining = _replace_all(remaining, scene)

    for prop in sorted(PROP_NAMES, key=len, reverse=True):
        if prop in remaining and not _contained_in_longer(prop, PROP_NAMES, remaining):
            add_draft(prop, "props")
            remaining = _replace_all(remaining, prop)

    for character in sorted((*CHARACTER_NAMES, *ROLE_NAMES), key=len, reverse=True):
        if character in remaining:
            add_draft(character, "characters")
            remaining = _replace_all(remaining, character)

    for match in re.finditer(rf"小[{CREATURE_CHARS}]{{1,3}}", remaining):
        add_draft(match.group(0), "characters")
        remaining = _replace_all(remaining, match.group(0))

    for match in re.finditer(
        rf"[和与]([\u4e00-\u9fff]{{2,4}}?)(?:[{NAME_TRAIL}]|一起|$)",
        remaining,
    ):
        add_draft(match.group(1), infer_asset_kind(match.group(1)) or "characters")
        remaining = _replace_all(remaining, match.group(1))

    for match in re.finditer(
        r"(?:遇到|遇见|碰到|看见|认识|跟着)([\u4e00-\u9fff]{2,4})",
        remaining,
    ):
        add_draft(match.group(1), infer_asset_kind(match.group(1)) or "characters")
        remaining = _replace_all(remaining, match.group(1))

    for match in re.finditer(r"(?:^|[。！？\s])([\u4e00-\u9fff]{2,3})在", remaining):
        add_draft(match.group(1), infer_asset_kind(match.group(1)) or "characters")
        remaining = _replace_all(remaining, match.group(1))

    from project_files import normalize_asset_drafts

    drafts = normalize_asset_drafts(drafts)
    notice = _user_notice(known, drafts, reuse_candidates)
    return {
        "known_assets": known,
        "reuse_candidates": reuse_candidates,
        "new_asset_drafts": drafts,
        "user_notice": notice,
        "needs_confirmation": bool(drafts or reuse_candidates),
    }


def _user_notice(
    known: list[dict[str, Any]],
    drafts: list[dict[str, str]],
    reuse_candidates: list[dict[str, Any]],
) -> str:
    from project_files import KIND_LABELS

    parts: list[str] = []
    if known:
        names = "、".join(str(item.get("name")) for item in known)
        parts.append(f"已有素材：{names}")
    if reuse_candidates:
        names = "、".join(
            f"{item.get('name')}（{item.get('scope')}）" for item in reuse_candidates
        )
        parts.append(f"故事里还提到仅属于其他范围的素材：{names}，本集不能自动锁定")
    grouped: dict[str, list[str]] = {"characters": [], "scenes": [], "props": [], "": []}
    for draft in drafts:
        grouped.get(draft.get("kind", ""), grouped[""]).append(draft["name"])
    for kind, names in grouped.items():
        if not names:
            continue
        label = KIND_LABELS.get(kind, "待确认名称")
        parts.append(f"发现{label}：{'、'.join(names)}")
    if not parts:
        return "这段故事没有检出新的角色、场景或道具。"
    if grouped[""]:
        parts.append("请先用中文确认这些名称是新角色、新场景还是新道具，确认前不要写分镜")
        return "。".join(parts) + "。"
    return "。".join(parts) + "。请确认后我再画参考图，不用填任何命令。"
