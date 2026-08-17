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
    current_keyframe_dispatch,
    current_keyframe_plan,
    initialize_project,
    prepare_keyframe_generation,
    record_script_and_storyboard_approval,
    record_story_outline,
    request_keyframe_regeneration,
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
            self.assertTrue(any("sub-agent per frame" in rule for rule in context["rules"]))
            self.assertTrue(any("brief.text" in rule for rule in context["rules"]))
            self.assertTrue(any("background-only" in rule or "night lighting" in rule for rule in context["rules"]))
            self.assertTrue(any("blocking" in rule or "pose" in rule for rule in context["rules"]))

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
            self.assertTrue(card["prompt"].startswith("咕噜在泡泡湾挥手"))
            self.assertIn("时间、光线和窗外氛围以场景母版和本帧提示词为准", card["prompt"])
            self.assertEqual(card["generation_mode"], "single_pass")
            self.assertIn("出图必传参考图", execution)
            self.assertIn("C01_gulu/front.png", execution)
            joined = " ".join(card["codex_instructions"])
            self.assertIn("母版", joined)
            self.assertIn("链式参考", joined)
            self.assertIn("不得当作唯一或主身份参考", joined)
            self.assertIn("single_pass", joined)
            self.assertIn("不得用上一帧站位否决本帧动作", joined)
            self.assertIn("禁止自制构图叠加层", joined)
            self.assertTrue(card["codex_instructions"][0].startswith("出图前必须先原样输出"))
            self.assertIn("1. 本图故事", card["brief"]["text"])
            self.assertIn("2. 本镜引用素材", card["brief"]["text"])
            self.assertIn("3. 制作时必须注意", card["brief"]["text"])
            self.assertIn("咕噜", card["brief"]["text"])
            self.assertIn("泡泡湾", card["brief"]["text"])
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

    def _frame_manifest(self, root: Path) -> tuple[Path, dict]:
        manifest_path = root / "episodes/EP002_海滩小螃蟹/keyframe-execution-manifest.json"
        return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_stale_generating_dispatch_is_ignored_after_plan_invalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.ready_keyframe_episode(root)
            card = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(card["allowed"])

            manifest_path, manifest = self._frame_manifest(root)
            frame = manifest["shots"][0]["frames"][0]
            self.assertEqual(frame["status"], "generating")
            frame["current_plan_id"] = None
            for plan in frame["plans"]:
                plan["status"] = "invalidated"
                plan["invalidated_reason"] = "用户请求重做：测试"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            self.assertIsNone(current_keyframe_dispatch(root, "EP002", "01", "start"))
            self.assertIsNone(current_keyframe_plan(root, "EP002", "01", "start"))

            recovered = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(recovered["allowed"])
            self.assertNotEqual(recovered["dispatch_id"], card["dispatch_id"])
            self.assertNotEqual(recovered["plan_id"], card["plan_id"])

    def test_prepare_recovers_from_abandoned_generating_or_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.ready_keyframe_episode(root)
            first = dispatch_keyframe(root, "EP002", "01", "start")

            manifest_path, manifest = self._frame_manifest(root)
            frame = manifest["shots"][0]["frames"][0]
            frame["status"] = "failed"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            redo = request_keyframe_regeneration(root, "EP002", "01", "start", "上一轮生成卡住")
            self.assertEqual(redo["shot_id"], "01")
            _, after_redo = self._frame_manifest(root)
            old_plan = after_redo["shots"][0]["frames"][0]["plans"][0]
            self.assertEqual(old_plan["status"], "invalidated")
            self.assertEqual(old_plan["stages"][0]["status"], "failed")
            self.assertIn("上一轮生成卡住", old_plan["stages"][0]["error"])
            self.assertIsNone(current_keyframe_dispatch(root, "EP002", "01", "start"))

            prepared = prepare_keyframe_generation(root, "EP002", "01", "start")
            self.assertEqual(prepared["status"], "planned")
            self.assertNotEqual(prepared["plan_id"], first["plan_id"])

            manifest_path, manifest = self._frame_manifest(root)
            frame = manifest["shots"][0]["frames"][0]
            frame["status"] = "failed"
            frame["current_plan_id"] = None
            for plan in frame["plans"]:
                plan["status"] = "invalidated"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            recovered = prepare_keyframe_generation(root, "EP002", "01", "start")
            self.assertEqual(recovered["status"], "planned")
            self.assertNotEqual(recovered["plan_id"], prepared["plan_id"])
            card = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(card["allowed"])
            self.assertEqual(card["plan_id"], recovered["plan_id"])

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

    def test_dispatch_rebuilds_obsolete_background_then_character_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            self.ready_keyframe_episode(root)
            first = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertEqual(first["generation_mode"], "single_pass")

            manifest_path, manifest = self._frame_manifest(root)
            frame = manifest["shots"][0]["frames"][0]
            plan = frame["plans"][0]
            original_inputs = list(plan["stages"][0]["input_images"])
            scene = next(item for item in original_inputs if item.get("role") == "background")
            characters = [item for item in original_inputs if item.get("role") == "character_identity"]
            plan["generation_mode"] = "staged_edit"
            plan["force_staged_edit"] = False
            plan["stages"] = [
                {
                    **plan["stages"][0],
                    "kind": "background",
                    "input_images": [scene],
                    "status": "qa_passed",
                },
                {
                    "stage_id": "stage-2",
                    "status": "planned",
                    "mode": "edit",
                    "kind": "primary_subjects",
                    "input_images": [{"role": "edit_target", "source": "previous_stage", "stage_id": "stage-1"}, *characters],
                    "prompt": plan["stages"][0]["prompt"],
                    "required_qa_categories": ["character"],
                },
            ]
            frame["status"] = "generating"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            rebuilt = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(rebuilt["allowed"])
            self.assertEqual(rebuilt["generation_mode"], "single_pass")
            self.assertNotEqual(rebuilt["plan_id"], first["plan_id"])
            self.assertEqual(rebuilt["stage_id"], "stage-1")
            self.assertGreaterEqual(len(rebuilt["view_image_paths"]), 2)

    def test_dispatch_refuses_night_shot_without_night_scene_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.seed_project(root)
            create_episode(root, "EP004", "咕噜怕黑", "深夜泡泡湾里咕噜怕黑。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP004_咕噜怕黑"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            self.approve_outline(root, "EP004")
            record_script_and_storyboard_approval(root, "EP004")
            create_keyframe_plan(
                root,
                "EP004",
                [{"shot_id": "01", "duration_seconds": 5, "action": "深夜卧室", "strategy": "start_only"}],
            )
            approve_keyframe_plan(root, "EP004")
            details = [
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
                    "start_state": "怕黑",
                    "motion": "靠近妈妈",
                    "end_state": "被安抚",
                    "dialogue": "无",
                    "voice_strategy": "后期配音",
                    "sound_effects": "无",
                    "transition_in": "淡入",
                    "transition_out": "淡出",
                    "storyboard_image_prompt": "深夜月光下的房间",
                    "frame_prompts": {"start": "深夜卧室里咕噜和妈妈"},
                    "frame_specs": {"start": {"continuity_contract": None, "invariants": ["咕噜身份"]}},
                }
            ]
            with self.assertRaisesRegex(ValueError, "night 视图"):
                create_keyframe_execution_pack(root, "EP004", details)

            daytime = dict(details[0])
            daytime["start_state"] = "挥手"
            daytime["motion"] = "轻轻挥手"
            daytime["end_state"] = "微笑"
            daytime["storyboard_image_prompt"] = "白天的泡泡湾"
            daytime["frame_prompts"] = {"start": "咕噜在泡泡湾挥手"}
            create_keyframe_execution_pack(root, "EP004", [daytime])
            manifest_path = episode / "keyframe-execution-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["shots"][0]["time_of_day"] = "night"
            manifest["shots"][0]["storyboard_image_prompt"] = "深夜月光下的房间"
            manifest["shots"][0]["frame_prompts"]["start"] = "深夜卧室里咕噜和妈妈"
            manifest["shots"][0]["frames"][0]["frame_spec"]["prompt"] = "深夜卧室里咕噜和妈妈"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            card = dispatch_keyframe(root, "EP004", "01", "start")
            self.assertFalse(card["allowed"])
            self.assertIn("night", card["reason"])
            self.assertIn("dispatch-asset", card["reason"])

            self.write_file(root, "assets/global/scenes/S03_bay/night.png", b"bay-night")
            index_path = root / "project-settings/asset-index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for asset in index["assets"]:
                if asset["asset_id"] == "S03":
                    asset["views"].append({"variant": "night", "path": "assets/global/scenes/S03_bay/night.png"})
            index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            allowed = dispatch_keyframe(root, "EP004", "01", "start")
            self.assertTrue(allowed["allowed"], allowed.get("reason"))
            background = next(item for item in allowed["input_images"] if item.get("role") == "background")
            self.assertTrue(str(background["path"]).endswith("night.png"))
            self.assertIn("assets/global/scenes/S03_bay/night.png", allowed["view_image_paths"])


if __name__ == "__main__":
    unittest.main()
