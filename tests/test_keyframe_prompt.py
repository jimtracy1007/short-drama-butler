from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from keyframe_prompt import (  # noqa: E402
    assert_storyboard_shots_complete,
    build_frame_brief,
    compose_still_prompt,
    load_parsed_storyboard,
    missing_time_scene_views,
    shots_from_storyboard,
)
from project_files import (  # noqa: E402
    approve_keyframe_plan,
    approve_story_outline,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    initialize_project,
    record_script_and_storyboard_approval,
    record_story_outline,
    refine_keyframe_prompt,
    refine_keyframe_prompts,
    refresh_execution_prompts,
    write_asset_index,
)
from workflow_status import episode_status, keyframe_work  # noqa: E402
from validate_director_storyboard import parse_storyboard  # noqa: E402


DAY_BOARD = """# 《测试集》5秒导演版分镜｜客厅版
整体时长：5秒
画面规格：16:9 横屏，温暖动画风格。
固定场景：明亮客厅。
本集主题：先观察，再行动。
镜头 01｜5秒｜发现小车
关键帧画面
小兔子蹲在地毯前，看到小车卡在沙发底边，抬头看向妈妈。
动作过程
00:00—00:05 小兔子蹲在地毯前，双手撑地，抬头看向妈妈。
运镜
中景缓慢推近小兔子的表情。
台词与口型时间段
00:03—00:05｜小兔子嘴巴开合说：“小车不见啦！”
非说话嘴型控制
说完立即闭嘴。
角色声线
小兔子：幼童软糯。
声音策略
后期配音。
音效
地毯摩擦声。
入点
从客厅切入。
出点 / 转场
视线切到妈妈。
素材参考
咕噜、泡泡湾。
分镜出图提示词
温暖动画风格，中景，小兔子和卡在沙发边的小车，锁已确认角色与客厅资产，不要文字。
"""


AUTO_BOARD = """# 《测试集》5秒导演版分镜｜海滩
整体时长：5秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：泡泡湾。
本集主题：挥手。
镜头 01｜5秒｜挥手
关键帧画面
咕噜站在泡泡湾岸边挥手，阳光下海水清澈。
动作过程
00:00—00:05 咕噜轻轻挥手。
运镜
中景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
海浪。
入点
淡入。
出点 / 转场
淡出。
素材参考
咕噜、泡泡湾。
分镜出图提示词
16:9横屏，已确认资产咕噜位于已确认资产泡泡湾，白天海滩中景，不要文字。
"""

TEN_AUTO_BOARD = """# 《测试集》10秒导演版分镜｜海滩
整体时长：10秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：泡泡湾。
本集主题：挥手。
镜头 01｜10秒｜挥手
首帧 A 画面
咕噜站在泡泡湾岸边举手。
尾帧 B 画面
咕噜放下手微笑。
动作过程
00:00—00:10 咕噜轻轻挥手后放下。
运镜
中景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
海浪。
入点
淡入。
出点 / 转场
淡出。
素材参考
咕噜、泡泡湾。
分镜出图提示词
16:9横屏，已确认资产咕噜位于已确认资产泡泡湾，白天海滩中景，不要文字。
"""

NIGHT_BAY_BOARD = """# 《测试集》5秒导演版分镜｜夜湾
整体时长：5秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：泡泡湾。
本集主题：夜。
镜头 01｜5秒｜夜里挥手
关键帧画面
咕噜站在月下的泡泡湾挥手。
动作过程
00:00—00:05 咕噜轻轻挥手。
运镜
中景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
海浪。
入点
淡入。
出点 / 转场
淡出。
素材参考
咕噜、泡泡湾。
分镜出图提示词
16:9横屏，已确认资产咕噜位于已确认资产泡泡湾，背景时间为深夜，禁止白天、日出、日落、黄昏或橙色天空。
"""

INCOMPLETE_BOARD = """# 《测试集》5秒导演版分镜｜海滩
整体时长：5秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：泡泡湾。
本集主题：挥手。
镜头 01｜5秒｜挥手
关键帧画面
咕噜站在泡泡湾岸边挥手。
动作过程
00:00—00:05 咕噜轻轻挥手。
运镜
中景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
海浪。
入点
淡入。
出点 / 转场
淡出。
素材参考
咕噜、泡泡湾。
分镜出图提示词
"""

TWO_NIGHT_BOARD = """# 《测试集》10秒导演版分镜｜两处夜景
整体时长：10秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：泡泡湾与咕噜房间。
本集主题：夜。
镜头 01｜5秒｜夜里挥手
关键帧画面
咕噜站在月下的泡泡湾挥手。
动作过程
00:00—00:05 咕噜轻轻挥手。
运镜
中景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
海浪。
入点
淡入。
出点 / 转场
切到房间。
素材参考
咕噜、泡泡湾。
分镜出图提示词
16:9横屏，已确认资产咕噜位于已确认资产泡泡湾，背景时间为深夜，禁止白天。
镜头 02｜5秒｜夜里坐床
关键帧画面
咕噜坐在月下的房间床沿。
动作过程
00:00—00:05 咕噜坐着看窗帘。
运镜
全景固定。
台词与口型时间段
本镜无台词。
非说话嘴型控制
嘴巴闭合。
角色声线
本镜无台词。
声音策略
后期环境声。
音效
窗帘轻响。
入点
切到房间。
出点 / 转场
淡出。
素材参考
咕噜、咕噜房间。
分镜出图提示词
16:9横屏，已确认资产咕噜位于已确认资产咕噜房间，背景时间为深夜，禁止白天。
"""

NIGHT_BOARD = """# 《咕噜怕黑》10秒导演版分镜｜夜景
整体时长：10秒
画面规格：16:9横屏，软萌高品质3D家庭动画电影感。
固定场景：咕噜房间。
本集主题：怕黑。
镜头 01｜10 秒｜关灯前
首帧 A 画面
咕噜坐在床沿掖被角，妈妈蹲在床边，墙上开关和窗帘都在画面中。
尾帧 B 画面
咕噜望向墙角，妈妈右手悬在开关前，没有按下。
动作过程
00:00—00:10 咕噜整理被子后看向墙角。
运镜
全景缓慢推近中景。
台词与口型时间段
本镜有对白。
非说话嘴型控制
说完立即闭嘴。
角色声线
咕噜：软糯童声。
声音策略
画面内口型。
音效
被子轻摩擦。
入点
月光从窗帘缝进入。
出点 / 转场
手指悬在开关前。
素材参考
咕噜、咕噜妈妈、咕噜房间。
分镜出图提示词
16:9横屏，已确认资产咕噜和咕噜妈妈位于已确认资产咕噜房间内，背景时间为深夜，窗外是深蓝近黑的夜空，禁止白天、日出、日落、黄昏或橙色天空；暖色大灯亮着，无文字、字幕、Logo、水印。
"""


class KeyframePromptTests(unittest.TestCase):
    def write_storyboard(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "storyboard.md"
        path.write_text(contents, encoding="utf-8")
        return path

    def write_file(self, root: Path, relative: str, contents: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def seed_project(self, root: Path) -> None:
        initialize_project(root, "测试项目", None, frame_format="16:9")
        self.write_file(root, "assets/global/characters/C01_gulu/front.png", b"gulu")
        self.write_file(root, "assets/global/scenes/S03_bay/front.png", b"bay")
        write_asset_index(
            root,
            [
                {
                    "asset_id": "C01",
                    "name": "咕噜",
                    "kind": "characters",
                    "scope": "global",
                    "destination": "assets/global/characters/C01_gulu/front.png",
                    "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
                },
                {
                    "asset_id": "S03",
                    "name": "泡泡湾",
                    "kind": "scenes",
                    "scope": "global",
                    "destination": "assets/global/scenes/S03_bay/front.png",
                    "views": [{"variant": "front", "path": "assets/global/scenes/S03_bay/front.png"}],
                },
            ],
        )

    def approve_outline(self, root: Path, episode_id: str) -> None:
        record_story_outline(
            root,
            episode_id,
            "## 故事梗概\n\n测试。\n\n## 人物小传\n\n角色。\n\n## 本集大纲\n\n大纲。",
        )
        approve_story_outline(root, episode_id)

    def execution_details(self) -> list[dict]:
        return [
            {
                "shot_id": "01",
                "shot_size": "中景",
                "camera_movement": "固定",
                "scene": "泡泡湾",
                "asset_references": ["咕噜", "泡泡湾"],
                "asset_uses": [
                    {"reference": "咕噜", "role": "character_identity", "required": True},
                    {"reference": "泡泡湾", "role": "background", "required": True},
                ],
                "start_state": "挥手",
                "motion": "轻轻挥手",
                "end_state": "微笑",
                "dialogue": "无",
                "voice_strategy": "后期配音",
                "sound_effects": "海浪",
                "transition_in": "淡入",
                "transition_out": "淡出",
                "storyboard_image_prompt": "咕噜在泡泡湾挥手",
                "frame_prompts": {"start": "咕噜在泡泡湾挥手"},
                "frame_specs": {"start": {"continuity_contract": None, "invariants": ["咕噜身份"]}},
            }
        ]

    def ready_episode(self, root: Path, storyboard: str) -> Path:
        create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
        episode = root / "episodes/EP002_泡泡湾挥手"
        (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
        (episode / "storyboard.md").write_text(storyboard, encoding="utf-8")
        self.approve_outline(root, "EP002")
        record_script_and_storyboard_approval(root, "EP002")
        create_keyframe_plan(
            root,
            "EP002",
            [{"shot_id": "01", "duration_seconds": 5, "action": "挥手", "strategy": "start_only"}],
        )
        approve_keyframe_plan(root, "EP002")
        return episode

    def test_stub_storyboard_is_not_parsed(self) -> None:
        self.assertIsNone(load_parsed_storyboard(self.write_storyboard("# 分镜\n")))

    def test_compose_keeps_this_frame_and_night_lock(self) -> None:
        parsed = parse_storyboard(self.write_storyboard(NIGHT_BOARD))
        shot = parsed["shots"][0]
        start = compose_still_prompt(parsed, shot, "start", shot_size="全景", camera_movement="推近")
        end = compose_still_prompt(parsed, shot, "end", shot_size="中景", camera_movement="推近")

        self.assertIn("掖被角", start)
        self.assertIn("禁止白天", start)
        self.assertIn("按道具处理", start)
        self.assertIn("禁止新增母版没有的固定物", start)
        self.assertIn("已确认资产：咕噜、咕噜妈妈、咕噜房间", start)
        self.assertNotIn("望向墙角", start)
        self.assertIn("望向墙角", end)
        self.assertIn("禁止白天", end)
        self.assertNotIn("掖被角", end)

    def test_user_refinement_appends_without_dropping_locks(self) -> None:
        parsed = parse_storyboard(self.write_storyboard(NIGHT_BOARD))
        prompt = compose_still_prompt(
            parsed,
            parsed["shots"][0],
            "start",
            refinements=["手再靠近开关"],
        )

        self.assertIn("禁止白天", prompt)
        self.assertIn("禁止新增母版没有的固定物", prompt)
        self.assertIn("用户精修：手再靠近开关", prompt)

    def test_frame_brief_lists_story_assets_and_must_watch(self) -> None:
        parsed = parse_storyboard(self.write_storyboard(NIGHT_BOARD))
        brief = build_frame_brief(
            parsed,
            {"shot_id": "01", "motion": parsed["shots"][0]["motion"]},
            "start",
            input_images=[
                {
                    "name": "咕噜",
                    "role": "character_identity",
                    "selected_view": "front",
                    "path": "assets/gulu.png",
                },
                {
                    "name": "咕噜房间",
                    "role": "background",
                    "selected_view": "night",
                    "path": "assets/room-night.png",
                },
            ],
        )

        self.assertIn("掖被角", brief["story"])
        self.assertNotIn("望向墙角", brief["story"])
        self.assertIn("1. 本图故事", brief["text"])
        self.assertIn("2. 本镜引用素材", brief["text"])
        self.assertIn("3. 制作时必须注意", brief["text"])
        self.assertIn("咕噜房间（场景 / night）", brief["text"])
        self.assertIn("禁止新增母版没有的固定物", brief["text"])
        self.assertIn("禁止白天", brief["text"])

    def test_frame_brief_fills_names_from_resolved_uses_when_dispatch_strips_them(self) -> None:
        brief = build_frame_brief(
            None,
            {
                "shot_id": "01",
                "start_state": "咕噜挥手",
                "resolved_asset_uses": [
                    {
                        "name": "咕噜",
                        "role": "character_identity",
                        "selected_view": "front",
                        "path": "assets/gulu.png",
                    }
                ],
            },
            "start",
            input_images=[{"role": "character_identity", "path": "assets/gulu.png", "sha256": "abc"}],
        )

        self.assertEqual(brief["assets"][0]["name"], "咕噜")
        self.assertEqual(brief["assets"][0]["view"], "front")
        self.assertIn("咕噜（角色 / front）", brief["text"])

    def test_create_execution_replaces_paraphrased_prompts_from_storyboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            episode = self.ready_episode(root, DAY_BOARD)
            create_keyframe_execution_pack(root, "EP002", self.execution_details())
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            prompt = manifest["shots"][0]["frame_prompts"]["start"]
            self.assertIn("小兔子蹲在地毯前", prompt)
            self.assertIn("锁已确认角色与客厅资产", prompt)
            self.assertEqual(
                manifest["shots"][0]["storyboard_image_prompt"],
                "温暖动画风格，中景，小兔子和卡在沙发边的小车，锁已确认角色与客厅资产，不要文字。",
            )
            self.assertNotEqual(prompt, "咕噜在泡泡湾挥手")

    def test_refine_and_refresh_keep_storyboard_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            episode = self.ready_episode(root, "# 分镜\n")
            create_keyframe_execution_pack(root, "EP002", self.execution_details())
            refined = refine_keyframe_prompt(root, "EP002", "01", "start", "手再抬高一点")
            self.assertIn("用户精修：手再抬高一点", refined["prompt"])
            (episode / "storyboard.md").write_text(DAY_BOARD, encoding="utf-8")
            refreshed = refresh_execution_prompts(root, "EP002")
            self.assertEqual(refreshed["count"], 1)
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            prompt = manifest["shots"][0]["frame_prompts"]["start"]
            self.assertIn("小兔子蹲在地毯前", prompt)
            self.assertIn("用户精修：手再抬高一点", prompt)

    def test_refresh_keeps_confirmed_and_skips_generating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            episode = self.ready_episode(root, DAY_BOARD)
            create_keyframe_execution_pack(root, "EP002", self.execution_details())
            path = episode / "keyframe-execution-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["shots"][0]["frames"][0]["status"] = "confirmed"
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            refreshed = refresh_execution_prompts(root, "EP002")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            frame = manifest["shots"][0]["frames"][0]
            self.assertEqual(frame["status"], "confirmed")
            self.assertEqual(refreshed["skipped_frames"], [])
            self.assertIn("禁止新增母版没有的固定物", frame["frame_spec"]["prompt"])

            manifest["shots"][0]["frames"][0]["status"] = "generating"
            old_prompt = manifest["shots"][0]["frame_prompts"]["start"]
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            skipped = refresh_execution_prompts(root, "EP002")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["shots"][0]["frames"][0]["status"], "generating")
            self.assertEqual(manifest["shots"][0]["frame_prompts"]["start"], old_prompt)
            self.assertEqual(
                skipped["skipped_frames"],
                [{"shot_id": "01", "frame_kind": "start", "reason": "generating"}],
            )

    def test_plan_and_execution_come_from_storyboard_without_handwritten_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(AUTO_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(root, "EP002")
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(root, "EP002")
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            shot = manifest["shots"][0]
            prompt = shot["frame_prompts"]["start"]
            self.assertEqual(shot["asset_references"], ["咕噜", "泡泡湾"])
            self.assertIn("咕噜站在泡泡湾岸边挥手", prompt)
            self.assertIn("禁止新增母版没有的固定物", prompt)
            self.assertIsNone(shot["frames"][0]["frame_spec"]["continuity_contract"])

    def test_status_asks_two_subagents_for_a_two_frame_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(TEN_AUTO_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(root, "EP002")
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(root, "EP002")
            status = episode_status(root, "EP002")
            work = status["keyframe_work"]
            self.assertEqual(work["mode"], "spawn_subagents")
            self.assertEqual(
                [item["frame_kind"] for item in work["frames"]],
                ["start", "end"],
            )
            actions = " ".join(status["next_actions"])
            self.assertIn("派 2 个子 agent", actions)
            self.assertIn("--frame start", actions)
            self.assertIn("--frame end", actions)
            self.assertIn("不要 record-qa", actions)
            self.assertIn("不自己出图", actions)

    def test_status_asks_one_subagent_for_a_one_frame_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            episode = self.ready_episode(root, DAY_BOARD)
            create_keyframe_execution_pack(root, "EP002")
            status = episode_status(root, "EP002")
            work = status["keyframe_work"]
            self.assertEqual(work["mode"], "spawn_subagents")
            self.assertEqual([item["frame_kind"] for item in work["frames"]], ["start"])
            actions = " ".join(status["next_actions"])
            self.assertIn("派 1 个子 agent", actions)
            self.assertIn("--frame start", actions)
            self.assertNotIn("--frame end", actions)

    def test_refine_reopens_only_that_frame_for_a_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(TEN_AUTO_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(root, "EP002")
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(root, "EP002")
            path = episode / "keyframe-execution-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for frame in manifest["shots"][0]["frames"]:
                frame["status"] = "confirmed"
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            refine_keyframe_prompt(root, "EP002", "01", "end", "手指悬在开关上")
            status = episode_status(root, "EP002")
            work = status["keyframe_work"]
            actions = " ".join(status["next_actions"])
            self.assertEqual(work["mode"], "spawn_subagents")
            self.assertEqual([item["frame_kind"] for item in work["frames"]], ["end"])
            self.assertIn("派 1 个子 agent", actions)
            self.assertIn("精修", actions)
            self.assertIn("--frame end", actions)
            self.assertNotIn("--frame start", actions)

    def test_refine_batch_reopens_each_named_frame_for_its_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(TEN_AUTO_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(root, "EP002")
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(root, "EP002")
            path = episode / "keyframe-execution-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for frame in manifest["shots"][0]["frames"]:
                frame["status"] = "confirmed"
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = refine_keyframe_prompts(
                root,
                "EP002",
                [
                    {"shot_id": "1", "frame_kind": "start", "note": "手再抬高"},
                    {"shot_id": "01", "frame_kind": "end", "note": "手指悬在开关上"},
                ],
            )
            self.assertEqual(result["count"], 2)
            status = episode_status(root, "EP002")
            work = status["keyframe_work"]
            actions = " ".join(status["next_actions"])
            self.assertEqual(work["mode"], "spawn_subagents")
            self.assertEqual(
                [(item["shot_id"], item["frame_kind"]) for item in work["frames"]],
                [("01", "start"), ("01", "end")],
            )
            self.assertIn("派 2 个子 agent", actions)
            self.assertIn("精修", actions)
            self.assertIn("--frame start", actions)
            self.assertIn("--frame end", actions)

    def test_keyframe_work_spawns_refines_before_later_planned_shots(self) -> None:
        work = keyframe_work(
            {
                "shots": [
                    {
                        "shot_id": "01",
                        "frames": [
                            {"frame_kind": "start", "status": "planned", "frame_spec": {"continuity_contract": None}},
                        ],
                    },
                    {
                        "shot_id": "03",
                        "frames": [
                            {
                                "frame_kind": "end",
                                "status": "needs_regeneration",
                                "frame_spec": {"continuity_contract": None},
                            },
                        ],
                    },
                    {
                        "shot_id": "08",
                        "frames": [
                            {
                                "frame_kind": "start",
                                "status": "failed",
                                "frame_spec": {"continuity_contract": None},
                            },
                        ],
                    },
                    {
                        "shot_id": "09",
                        "frames": [
                            {"frame_kind": "start", "status": "planned", "frame_spec": {"continuity_contract": None}},
                        ],
                    },
                ]
            }
        )
        self.assertEqual(work["mode"], "spawn_subagents")
        self.assertEqual(
            [(item["shot_id"], item["frame_kind"]) for item in work["frames"]],
            [("03", "end"), ("08", "start")],
        )

    def test_keyframe_work_spawns_every_frame_in_the_shot(self) -> None:
        work = keyframe_work(
            {
                "shots": [
                    {
                        "shot_id": "01",
                        "frames": [
                            {"frame_kind": "start", "status": "planned", "frame_spec": {"continuity_contract": None}},
                            {"frame_kind": "middle", "status": "planned", "frame_spec": {"continuity_contract": None}},
                            {"frame_kind": "end", "status": "planned", "frame_spec": {"continuity_contract": None}},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(work["mode"], "spawn_subagents")
        self.assertEqual([item["frame_kind"] for item in work["frames"]], ["start", "middle", "end"])

    def test_status_asks_for_night_scene_before_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            parsed = parse_storyboard(self.write_storyboard(NIGHT_BAY_BOARD))
            missing = missing_time_scene_views(root, parsed)
            self.assertEqual(missing[0]["name"], "泡泡湾")
            self.assertEqual(missing[0]["needed_view"], "night")
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(NIGHT_BAY_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            status = episode_status(root, "EP002")
            self.assertEqual(status["missing_time_views"][0]["needed_view"], "night")
            self.assertTrue(any("night" in action for action in status["next_actions"]))

    def test_plan_fails_when_storyboard_image_prompt_is_missing(self) -> None:
        parsed = parse_storyboard(self.write_storyboard(INCOMPLETE_BOARD))
        with self.assertRaisesRegex(ValueError, "缺少分镜出图提示词"):
            assert_storyboard_shots_complete(parsed)
        with self.assertRaisesRegex(ValueError, "缺少分镜出图提示词"):
            shots_from_storyboard(parsed)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(INCOMPLETE_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            with self.assertRaisesRegex(ValueError, "缺少分镜出图提示词"):
                create_keyframe_plan(root, "EP002")

    def test_refine_start_blocks_continuity_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "泡泡湾挥手", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_泡泡湾挥手"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(
                root,
                "EP002",
                [{"shot_id": "01", "duration_seconds": 10, "action": "挥手", "strategy": "start_end"}],
            )
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(
                root,
                "EP002",
                [
                    {
                        "shot_id": "01",
                        "shot_size": "中景",
                        "camera_movement": "固定",
                        "scene": "泡泡湾",
                        "asset_references": ["咕噜", "泡泡湾"],
                        "asset_uses": [
                            {"reference": "咕噜", "role": "character_identity", "required": True},
                            {"reference": "泡泡湾", "role": "background", "required": True},
                        ],
                        "start_state": "举手",
                        "motion": "轻轻挥手",
                        "end_state": "放下手",
                        "dialogue": "无",
                        "voice_strategy": "后期配音",
                        "sound_effects": "海浪",
                        "transition_in": "淡入",
                        "transition_out": "淡出",
                        "storyboard_image_prompt": "白天海滩",
                        "frame_prompts": {"start": "举手", "end": "放下手"},
                        "frame_specs": {
                            "start": {"continuity_contract": None},
                            "end": {
                                "continuity_contract": {
                                    "predecessor": {"shot_id": "01", "frame_kind": "start"},
                                    "inherit_dimensions": ["space"],
                                    "asset_ids": ["S03"],
                                }
                            },
                        },
                    }
                ],
            )
            refined = refine_keyframe_prompt(root, "EP002", "01", "start", "手再抬高一点")
            self.assertEqual(refined["invalidated_dependents"], [{"shot_id": "01", "frame_kind": "end"}])
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            frames = {frame["frame_kind"]: frame for frame in manifest["shots"][0]["frames"]}
            self.assertEqual(frames["end"]["status"], "waiting_for_dependency")
            self.assertIn("用户精修：手再抬高一点", frames["start"]["frame_spec"]["prompt"])

    def test_refresh_nulls_contracts_and_sets_time_of_day(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.write_file(root, "assets/global/characters/C04_mom/front.png", b"mom")
            self.write_file(root, "assets/episode-EP002/scenes/S02_room/reverse.png", b"room-day")
            write_asset_index(
                root,
                [
                    {
                        "asset_id": "C01",
                        "name": "咕噜",
                        "kind": "characters",
                        "scope": "global",
                        "destination": "assets/global/characters/C01_gulu/front.png",
                        "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
                    },
                    {
                        "asset_id": "C04",
                        "name": "咕噜妈妈",
                        "kind": "characters",
                        "scope": "global",
                        "destination": "assets/global/characters/C04_mom/front.png",
                        "views": [{"variant": "front", "path": "assets/global/characters/C04_mom/front.png"}],
                    },
                    {
                        "asset_id": "S02",
                        "name": "咕噜房间",
                        "kind": "scenes",
                        "scope": "episode-EP002",
                        "destination": "assets/episode-EP002/scenes/S02_room/reverse.png",
                        "views": [
                            {"variant": "reverse", "path": "assets/episode-EP002/scenes/S02_room/reverse.png"}
                        ],
                    },
                ],
            )
            create_episode(root, "EP002", "怕黑", "咕噜怕黑。", ["咕噜", "咕噜妈妈", "咕噜房间"])
            episode = root / "episodes/EP002_怕黑"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(
                root,
                "EP002",
                [{"shot_id": "01", "duration_seconds": 10, "action": "关灯前", "strategy": "start_end"}],
            )
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(
                root,
                "EP002",
                [
                    {
                        "shot_id": "01",
                        "shot_size": "全景",
                        "camera_movement": "推近",
                        "scene": "咕噜房间",
                        "asset_references": ["咕噜", "咕噜妈妈", "咕噜房间"],
                        "asset_uses": [
                            {"reference": "咕噜", "role": "character_identity", "required": True},
                            {"reference": "咕噜妈妈", "role": "character_identity", "required": True},
                            {
                                "reference": "咕噜房间",
                                "role": "background",
                                "required": True,
                                "view_hint": "reverse",
                            },
                        ],
                        "start_state": "掖被角",
                        "motion": "看向墙角",
                        "end_state": "望向墙角",
                        "dialogue": "无",
                        "voice_strategy": "画面内口型",
                        "sound_effects": "被子轻摩擦",
                        "transition_in": "切入",
                        "transition_out": "切出",
                        "storyboard_image_prompt": "白天房间",
                        "frame_prompts": {"start": "白天掖被角", "end": "白天望向墙角"},
                        "frame_specs": {
                            "start": {"continuity_contract": None},
                            "end": {
                                "continuity_contract": {
                                    "predecessor": {"shot_id": "01", "frame_kind": "start"},
                                    "inherit_dimensions": ["space"],
                                    "asset_ids": ["S02"],
                                }
                            },
                        },
                    }
                ],
            )
            (episode / "storyboard.md").write_text(NIGHT_BOARD, encoding="utf-8")
            refreshed = refresh_execution_prompts(root, "EP002")
            self.assertEqual(refreshed["count"], 2)
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            shot = manifest["shots"][0]
            self.assertEqual(shot["time_of_day"], "night")
            background = next(item for item in shot["asset_uses"] if item["role"] == "background")
            self.assertEqual(background["view_hint"], "night")
            frames = {frame["frame_kind"]: frame for frame in shot["frames"]}
            self.assertIsNone(frames["start"]["frame_spec"]["continuity_contract"])
            self.assertIsNone(frames["end"]["frame_spec"]["continuity_contract"])
            self.assertEqual(frames["end"]["status"], "planned")
            self.assertIn("禁止白天", frames["start"]["frame_spec"]["prompt"])
            self.assertIn("望向墙角", frames["end"]["frame_spec"]["prompt"])
            status = episode_status(root, "EP002")
            self.assertEqual(status["missing_time_views"][0]["name"], "咕噜房间")
            self.assertTrue(status["next_actions"][0].startswith("先为「咕噜房间」补 night"))

    def test_status_lists_all_missing_night_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.write_file(root, "assets/episode-EP002/scenes/S02_room/reverse.png", b"room-day")
            write_asset_index(
                root,
                [
                    {
                        "asset_id": "C01",
                        "name": "咕噜",
                        "kind": "characters",
                        "scope": "global",
                        "destination": "assets/global/characters/C01_gulu/front.png",
                        "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
                    },
                    {
                        "asset_id": "S03",
                        "name": "泡泡湾",
                        "kind": "scenes",
                        "scope": "global",
                        "destination": "assets/global/scenes/S03_bay/front.png",
                        "views": [{"variant": "front", "path": "assets/global/scenes/S03_bay/front.png"}],
                    },
                    {
                        "asset_id": "S02",
                        "name": "咕噜房间",
                        "kind": "scenes",
                        "scope": "episode-EP002",
                        "destination": "assets/episode-EP002/scenes/S02_room/reverse.png",
                        "views": [
                            {"variant": "reverse", "path": "assets/episode-EP002/scenes/S02_room/reverse.png"}
                        ],
                    },
                ],
            )
            create_episode(root, "EP002", "两处夜景", "夜里两处。", ["咕噜", "泡泡湾", "咕噜房间"])
            episode = root / "episodes/EP002_两处夜景"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text(TWO_NIGHT_BOARD, encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            status = episode_status(root, "EP002")
            names = {item["name"] for item in status["missing_time_views"]}
            self.assertEqual(names, {"泡泡湾", "咕噜房间"})
            self.assertGreaterEqual(sum("night" in action for action in status["next_actions"]), 2)
            self.assertTrue(any("泡泡湾" in action for action in status["next_actions"]))
            self.assertTrue(any("咕噜房间" in action for action in status["next_actions"]))


if __name__ == "__main__":
    unittest.main()
