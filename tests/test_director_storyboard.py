from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from validate_director_storyboard import (  # noqa: E402
    FIVE_SECOND_SECTIONS,
    TEN_SECOND_SECTIONS,
    parse_storyboard,
    validate_storyboard,
)


METADATA = """# 《测试集》15秒导演版分镜｜客厅版

整体时长：15秒
画面规格：16:9 横屏，温暖动画风格。
固定场景：明亮客厅。
本集主题：先观察，再行动。
"""

FIVE_SECOND_SHOT = """镜头 01｜5秒｜发现小车
关键帧画面
小兔子蹲在地毯前，看到小车卡在沙发底边，抬头看向妈妈。
动作过程
00:00—00:03
小兔子蹲在地毯前，双手撑地，抬头看向妈妈。
00:03—00:05
小兔子一只手指向沙发底边，说完立即闭嘴。

**小兔子：**
“小车不见啦！”
运镜
中景缓慢推近小兔子的表情。
台词与口型时间段
00:03—00:05｜小兔子嘴巴开合说：“小车不见啦！”
非说话嘴型控制
妈妈在厨房忙碌不说话，嘴巴闭合；小兔子 00:05 说完立即闭嘴，只保持抬头。
角色声线
小兔子：4—6 岁幼童，声音软糯、着急；这一句像发现玩具不见时喊妈妈。
声音策略
后期配音，视频只生成自然口型。
无背景音乐。
音效
* 小车轻微滚动声
* 地毯摩擦声
入点
从客厅建立镜头切入。
出点 / 转场
小兔子的视线切到妈妈。
素材参考
小兔子、妈妈、客厅、小车。
分镜出图提示词
温暖动画风格，中景，小兔子和卡在沙发边的小车，锁已确认角色与客厅资产，不要文字。
"""

TEN_SECOND_SHOT = """镜头 02｜10秒｜妈妈提醒先观察
首帧 A 画面
妈妈蹲在沙发旁，小兔子抱着小车，二人看向沙发底边。
尾帧 B 画面
妈妈回到厨房，小兔子趴下观察沙发底边，表情认真。
动作过程
00:00—00:02.5
中景跟拍妈妈蹲下。妈妈看着小兔子，嘴巴开合说话。

**妈妈：**
“先低头看看。”

00:02.5—00:06
妈妈说完立即闭嘴，起身走向厨房。小兔子抱紧小车，目光跟着妈妈。
镜头缓慢推近小兔子。

00:06—00:10
无台词。
小兔子自己趴到沙发底边，表情认真。镜头落在小兔子侧脸。
运镜
跟拍妈妈蹲下，再推近小兔子决定自己观察的表情。
台词与口型时间段
* 00:00—00:02.5｜妈妈：“先低头看看。”
* 00:02.5—00:10｜无台词。
非说话嘴型控制
小兔子全程不说话，嘴巴闭合；妈妈 00:02.5 说完后立即闭嘴转身回厨房。
角色声线
妈妈：成年女性，声音温和、清楚，中音区；这一句是提醒，不责备，不拉长尾音。
声音策略
后期配音，视频只生成自然口型。
无背景音乐。
音效
* 妈妈蹲下的布料轻响
* 玩具车塑料壳轻碰
* 00:09—00:10 声音自然淡出
入点
承接上一镜小兔子的视线。
出点 / 转场
小兔子低头的动作切到沙发底边近景。
素材参考
小兔子、妈妈、客厅、小车。
分镜出图提示词
温暖动画风格，客厅中景，妈妈和小兔子看向沙发底边，锁已确认角色与客厅资产，不要文字。
"""


class DirectorStoryboardValidationTests(unittest.TestCase):
    def write_storyboard(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "storyboard.md"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_required_heading_lists_match_production_contract(self) -> None:
        self.assertEqual(
            FIVE_SECOND_SECTIONS,
            (
                "关键帧画面",
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
            ),
        )
        self.assertEqual(
            TEN_SECOND_SECTIONS,
            (
                "首帧 A 画面",
                "尾帧 B 画面",
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
            ),
        )

    def test_accepts_exact_five_and_ten_second_director_blocks(self) -> None:
        errors = validate_storyboard(self.write_storyboard(METADATA + "\n" + FIVE_SECOND_SHOT + "\n" + TEN_SECOND_SHOT), 15)

        self.assertEqual(errors, [])

    def test_rejects_legacy_table_and_nonstandard_six_second_shot(self) -> None:
        legacy = METADATA + "\n| 镜号 | 时长 | 画面 |\n| --- | --- | --- |\n| 01 | 6 秒 | 小兔子看小车 |\n"

        errors = validate_storyboard(self.write_storyboard(legacy), 6)

        self.assertIn("不得使用 Markdown 表格", errors)
        self.assertIn("至少需要一个镜头", errors)
        self.assertIn("表格镜头 01 时长为 6 秒；只允许 5 秒、10 秒或最后不足 5 秒的余数", errors)

    def test_rejects_ten_second_shot_without_tail_frame_or_mouth_controls(self) -> None:
        invalid = (METADATA.replace("15秒", "10秒") + "\n" + TEN_SECOND_SHOT)
        invalid = invalid.replace("尾帧 B 画面\n妈妈回到厨房，小兔子趴下观察沙发底边，表情认真。\n", "")
        invalid = invalid.replace("非说话嘴型控制\n小兔子全程不说话，嘴巴闭合；妈妈 00:02.5 说完后立即闭嘴转身回厨房。\n", "")

        errors = validate_storyboard(self.write_storyboard(invalid), 10)

        self.assertIn("镜头 02 缺少“尾帧 B 画面”", errors)
        self.assertIn("镜头 02 缺少“非说话嘴型控制”", errors)

    def test_rejects_shot_missing_motion_timeline_or_voice(self) -> None:
        invalid = METADATA + "\n" + FIVE_SECOND_SHOT + "\n" + TEN_SECOND_SHOT
        invalid = invalid.replace("动作过程\n00:00—00:03\n小兔子蹲在地毯前，双手撑地，抬头看向妈妈。\n00:03—00:05\n小兔子一只手指向沙发底边，说完立即闭嘴。\n\n**小兔子：**\n“小车不见啦！”\n", "")
        invalid = invalid.replace("角色声线\n妈妈：成年女性，声音温和、清楚，中音区；这一句是提醒，不责备，不拉长尾音。\n", "")

        errors = validate_storyboard(self.write_storyboard(invalid), 15)

        self.assertIn("镜头 01 缺少“动作过程”", errors)
        self.assertIn("镜头 02 缺少“角色声线”", errors)

    def test_rejects_motion_section_without_timed_beats(self) -> None:
        invalid = FIVE_SECOND_SHOT.replace(
            "动作过程\n00:00—00:03\n小兔子蹲在地毯前，双手撑地，抬头看向妈妈。\n00:03—00:05\n小兔子一只手指向沙发底边，说完立即闭嘴。",
            "动作过程\n小兔子发现小车不见，心里一紧，赶紧喊妈妈。",
        )

        errors = validate_storyboard(self.write_storyboard(METADATA.replace("15秒", "5秒") + "\n" + invalid), 5)

        self.assertIn("镜头 01 的“动作过程”必须写出 00:00—00:xx 时间段", errors)

    def test_rejects_wrong_heading_order(self) -> None:
        shuffled = FIVE_SECOND_SHOT.replace(
            "动作过程\n00:00—00:03\n小兔子蹲在地毯前，双手撑地，抬头看向妈妈。\n00:03—00:05\n小兔子一只手指向沙发底边，说完立即闭嘴。\n\n**小兔子：**\n“小车不见啦！”\n运镜\n中景缓慢推近小兔子的表情。\n",
            "运镜\n中景缓慢推近小兔子的表情。\n动作过程\n00:00—00:03\n小兔子蹲在地毯前，双手撑地，抬头看向妈妈。\n00:03—00:05\n小兔子一只手指向沙发底边，说完立即闭嘴。\n\n**小兔子：**\n“小车不见啦！”\n",
        )

        errors = validate_storyboard(self.write_storyboard(METADATA.replace("15秒", "5秒") + "\n" + shuffled), 5)

        self.assertIn(
            "镜头 01 标题顺序必须为：关键帧画面、动作过程、运镜、台词与口型时间段、非说话嘴型控制、角色声线、声音策略、音效、入点、出点 / 转场、素材参考、分镜出图提示词",
            errors,
        )

    def test_rejects_global_metadata_when_label_and_value_are_split(self) -> None:
        split_metadata = """# 《测试集》5秒导演版分镜｜客厅版

整体时长
5秒
画面规格：
16:9 横版
固定场景：明亮客厅。
本集主题：先观察，再行动。
"""

        errors = validate_storyboard(self.write_storyboard(split_metadata + "\n" + FIVE_SECOND_SHOT), 5)

        self.assertIn("全局字段“整体时长”必须在同一行包含内容", errors)
        self.assertIn("全局字段“画面规格”必须在同一行包含内容", errors)

    def test_parse_storyboard_keeps_stills_and_image_prompts(self) -> None:
        parsed = parse_storyboard(self.write_storyboard(METADATA + "\n" + FIVE_SECOND_SHOT + "\n" + TEN_SECOND_SHOT))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["format"], "16:9 横屏，温暖动画风格。")
        self.assertEqual([shot["shot_id"] for shot in parsed["shots"]], ["01", "02"])
        first, second = parsed["shots"]
        self.assertIn("小兔子蹲在地毯前", first["still_start"])
        self.assertEqual(first["still_end"], "")
        self.assertIn("锁已确认角色与客厅资产", first["image_prompt"])
        self.assertEqual(first["asset_names"], ["小兔子", "妈妈", "客厅", "小车"])
        self.assertIn("妈妈蹲在沙发旁", second["still_start"])
        self.assertIn("妈妈回到厨房", second["still_end"])


if __name__ == "__main__":
    unittest.main()
