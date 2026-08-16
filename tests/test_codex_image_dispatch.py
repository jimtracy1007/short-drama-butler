from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from image_canon import (  # noqa: E402
    ImageCanonError,
    assert_reference_images_required,
    confirmed_image_assets,
    resolve_production_reference_images,
)
from codex_image_dispatch import (  # noqa: E402
    dispatch_asset,
    dispatch_keyframe,
    inspect_image_generation_context,
)
from project_files import (  # noqa: E402
    approve_keyframe_plan,
    approve_story_outline,
    confirm_episode_asset,
    create_asset_production_plan,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    initialize_project,
    record_script_and_storyboard_approval,
    record_story_outline,
    provide_episode_asset_images,
    write_asset_index,
)


class CodexImageDispatchTests(unittest.TestCase):
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
            "## 故事梗概\n\n测试梗概。\n\n## 人物小传\n\n主角保持既有设定。\n\n## 本集大纲\n\n起承转合。",
        )
        approve_story_outline(root, episode_id)

    def ready_keyframe_episode(self, root: Path) -> None:
        create_episode(root, "EP002", "海滩小螃蟹", "咕噜帮助小螃蟹。", ["咕噜", "泡泡湾"])
        episode = root / "episodes/EP002_海滩小螃蟹"
        (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
        (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
        self.approve_outline(root, "EP002")
        create_asset_production_plan(root, "EP002", [])
        crab = self.write_file(root, "generated/crab.png", b"crab")
        provide_episode_asset_images(root, "EP002", "小螃蟹", {"front": crab})
        confirm_episode_asset(root, "EP002", "小螃蟹")
        record_script_and_storyboard_approval(root, "EP002")
        create_keyframe_plan(
            root,
            "EP002",
            [{"shot_id": "01", "duration_seconds": 5, "action": "咕噜在泡泡湾挥手", "strategy": "start_only"}],
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
                    "start_state": "咕噜挥手",
                    "motion": "轻轻挥手",
                    "end_state": "咕噜微笑",
                    "dialogue": "无",
                    "voice_strategy": "后期配音",
                    "sound_effects": "海浪",
                    "transition_in": "淡入",
                    "transition_out": "淡出",
                    "storyboard_image_prompt": "咕噜在泡泡湾挥手",
                    "frame_prompts": {"start": "咕噜在泡泡湾挥手"},
                    "frame_specs": {"start": {"continuity_contract": None, "invariants": ["咕噜身份"]}},
                }
            ],
        )

    def test_inspect_lists_confirmed_assets_for_a_new_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP001", "测试集", "测试", ["咕噜"])

            context = inspect_image_generation_context(root)

            self.assertEqual(context["confirmed_asset_count"], 2)
            self.assertEqual({item["name"] for item in context["confirmed_assets"]}, {"咕噜", "泡泡湾"})
            self.assertEqual(context["episodes"][0]["episode_id"], "EP001")
            self.assertIn("view_image", " ".join(context["rules"]))
            self.assertTrue(any("masters" in rule and "previous shot" in rule for rule in context["rules"]))
            self.assertTrue(any("chain" in rule for rule in context["rules"]))

    def test_production_plan_attaches_existing_canon_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "海滩小螃蟹", "小螃蟹回海。", ["小螃蟹"])
            self.approve_outline(root, "EP002")

            plan_path = create_asset_production_plan(
                root,
                "EP002",
                [{"name": "小螃蟹", "kind": "characters", "visual_brief": "圆润小螃蟹，风格与泡泡湾一致"}],
            )
            plan = plan_path.read_text(encoding="utf-8")
            manifest = json.loads((plan_path.parent / "asset-production-manifest.json").read_text(encoding="utf-8"))
            references = manifest["assets"][0]["required_reference_images"]
            paths = {item["path"] for item in references}

            self.assertIn("assets/global/characters/C01_gulu/front.png", paths)
            self.assertIn("assets/global/scenes/S03_bay/front.png", paths)
            self.assertEqual(len(paths), 2)
            self.assertIn("必传参考图", plan)
            self.assertIn("butler.py dispatch-asset", plan)
            self.assertIn("不得纯文生图", manifest["assets"][0]["prompt"])

    def test_dispatch_asset_refuses_text_only_when_canon_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "海滩小螃蟹", "小螃蟹回海。", ["小螃蟹"])
            self.approve_outline(root, "EP002")
            create_asset_production_plan(
                root,
                "EP002",
                [{"name": "小螃蟹", "kind": "characters", "visual_brief": "圆润小螃蟹，出现在泡泡湾"}],
            )

            card = dispatch_asset(root, "EP002", "小螃蟹")

            self.assertTrue(card["allowed"])
            self.assertGreaterEqual(len(card["view_image_paths"]), 1)
            self.assertIn("assets/global/characters/C01_gulu/front.png", card["view_image_paths"])
            self.assertIn("母版", " ".join(card["codex_instructions"]))

    def test_dispatch_asset_allows_first_canon_without_existing_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "空项目", None)
            create_episode(root, "EP001", "第一集", "还没有图。", ["主角"])
            self.approve_outline(root, "EP001")
            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "主角", "kind": "characters", "visual_brief": "第一个角色"}],
            )

            card = dispatch_asset(root, "EP001", "主角")

            self.assertTrue(card["allowed"])
            self.assertEqual(card["view_image_paths"], [])
            self.assertTrue(card["first_canon"])

    def test_dispatch_keyframe_returns_existing_asset_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.ready_keyframe_episode(root)

            card = dispatch_keyframe(root, "EP002", "01", "start")
            execution = (root / "episodes/EP002_海滩小螃蟹/keyframe-execution.md").read_text(encoding="utf-8")
            planned_paths = {
                item["path"]
                for stage in json.loads((root / "episodes/EP002_海滩小螃蟹/keyframe-execution-manifest.json").read_text(encoding="utf-8"))["shots"][0]["frames"][0]["plans"][0]["stages"]
                for item in stage.get("input_images") or []
                if item.get("path")
            }

            self.assertTrue(card["allowed"])
            self.assertTrue(card["view_image_paths"])
            self.assertTrue(set(card["view_image_paths"]).issubset(planned_paths))
            self.assertIn("assets/global/characters/C01_gulu/front.png", planned_paths)
            self.assertIn("assets/global/scenes/S03_bay/front.png", planned_paths)
            self.assertEqual(card["prompt"], "咕噜在泡泡湾挥手")
            self.assertIn("出图必传参考图", execution)
            self.assertIn("C01_gulu/front.png", execution)
            joined = " ".join(card["codex_instructions"])
            self.assertIn("母版", joined)
            self.assertIn("链式参考", joined)
            self.assertIn("不得当作唯一或主身份参考", joined)
            again = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertEqual(again["dispatch_id"], card["dispatch_id"])
            self.assertEqual(again["stage_id"], card["stage_id"])

    def test_dispatch_keyframe_refuses_legacy_execution_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP002", "海滩小螃蟹", "测试", ["咕噜"])
            episode = root / "episodes/EP002_海滩小螃蟹"
            (episode / "keyframe-execution.md").write_text("# 旧执行单\n", encoding="utf-8")
            (episode / "keyframe-execution-manifest.json").write_text(
                json.dumps({"episode_id": "EP002", "status": "ready", "shots": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ImageCanonError, "legacy_unplanned"):
                dispatch_keyframe(root, "EP002", "01", "start")

    def test_text_only_generation_is_rejected_after_canon_exists(self) -> None:
        with self.assertRaisesRegex(ImageCanonError, "禁止"):
            assert_reference_images_required([], confirmed_asset_count=2)
        assert_reference_images_required([], confirmed_asset_count=0, allow_first_canon=True)

    def test_pending_assets_are_not_treated_as_canon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            self.write_file(root, "assets/pending/characters/C05.png", b"dad")
            write_asset_index(
                root,
                [
                    {
                        "asset_id": "C05",
                        "name": "咕噜爸爸",
                        "kind": "characters",
                        "scope": "pending",
                        "destination": "assets/pending/characters/C05.png",
                        "views": [{"variant": "front", "path": "assets/pending/characters/C05.png"}],
                    }
                ],
            )

            self.assertEqual(confirmed_image_assets(root), [])
            self.assertEqual(
                resolve_production_reference_images(root, name="小螃蟹", kind="characters", visual_brief="圆润"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
