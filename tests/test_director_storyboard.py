from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from validate_director_storyboard import validate_storyboard  # noqa: E402


METADATA = """# 《测试集》15秒导演版分镜｜客厅版

整体时长：15秒
画面规格：16:9 横屏，温暖动画风格。
固定场景：明亮客厅。
本集主题：先观察，再行动。
"""

FIVE_SECOND_SHOT = """镜头 01｜5秒｜发现小车
关键帧画面
小兔子蹲在地毯前，看到小车卡在沙发底边，抬头看向妈妈。
运镜
中景缓慢推近小兔子的表情。
台词与口型时间段
3.0–4.0秒｜小兔子嘴巴开合说：“小车不见啦！”
非说话嘴型控制
妈妈在厨房忙碌不说话，嘴巴闭合；小兔子非台词时只推车和抬头。
声音策略
后期配音，视频只生成自然口型。
音效
小车滚动和轻微海浪声。
入点
从客厅建立镜头切入。
出点 / 转场
小兔子的视线切到妈妈。
素材参考
小兔子、妈妈、客厅、小车。
分镜出图提示词
温暖动画风格，中景，小兔子和卡在沙发边的小车，不要文字。
"""

TEN_SECOND_SHOT = """镜头 02｜10秒｜妈妈提醒先观察
首帧 A 画面
妈妈蹲在沙发旁，小兔子抱着小车，二人看向沙发底边。
尾帧 B 画面
妈妈回到厨房，小兔子趴下观察沙发底边，表情认真。
运镜
跟拍妈妈蹲下，再推近小兔子决定自己观察的表情。
台词与口型时间段
1.0–2.5秒｜妈妈嘴巴开合说：“先低头看看。”
非说话嘴型控制
小兔子全程不说话，嘴巴闭合；妈妈说完后闭嘴转身回厨房。
声音策略
后期配音，视频只生成自然口型。
音效
布料轻响和玩具车滚动声。
入点
承接上一镜小兔子的视线。
出点 / 转场
小兔子低头的动作切到沙发底边近景。
素材参考
小兔子、妈妈、客厅、小车。
分镜出图提示词
温暖动画风格，客厅中景，妈妈和小兔子看向沙发底边，不要文字。
"""


class DirectorStoryboardValidationTests(unittest.TestCase):
    def write_storyboard(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "storyboard.md"
        path.write_text(contents, encoding="utf-8")
        return path

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
        invalid = invalid.replace("非说话嘴型控制\n小兔子全程不说话，嘴巴闭合；妈妈说完后闭嘴转身回厨房。\n", "")

        errors = validate_storyboard(self.write_storyboard(invalid), 10)

        self.assertIn("镜头 02 缺少“尾帧 B 画面”", errors)
        self.assertIn("镜头 02 缺少“非说话嘴型控制”", errors)

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
