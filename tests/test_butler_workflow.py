from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from butler import build_parser, _parse_refine_item  # noqa: E402
from codex_image_dispatch import dispatch_asset, dispatch_keyframe, inspect_image_generation_context  # noqa: E402
from image_canon import ImageCanonError  # noqa: E402
from project_files import (  # noqa: E402
    approve_keyframe_plan,
    approve_story_outline,
    confirm_episode_asset,
    create_asset_production_plan,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    initialize_project,
    record_episode_continuity,
    record_script_and_storyboard_approval,
    record_story_outline,
    record_stage_generation,
    record_stage_qa,
    provide_episode_asset_images,
    write_asset_index,
)
from workflow_status import episode_status, project_status  # noqa: E402


class ButlerWorkflowTests(unittest.TestCase):
    def write_file(self, root: Path, relative: str, contents: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def run_butler(self, root: Path, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SKILL_SCRIPTS / "butler.py"), "--project-root", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(completed.stdout)
        if completed.returncode != 0:
            self.fail(f"butler.py {' '.join(args)} failed: {payload}")
        return payload

    def approve_outline(self, root: Path, episode_id: str, classifications: str = "") -> None:
        record_story_outline(
            root,
            episode_id,
            "## 故事梗概\n\n测试梗概。\n\n## 人物小传\n\n主角保持既有设定。\n\n## 本集大纲\n\n起承转合。"
            + classifications,
        )
        approve_story_outline(root, episode_id)

    def test_status_on_empty_directory_tells_agent_to_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = self.run_butler(root, "status")
            self.assertEqual(payload["stage"], "no_project")
            self.assertIn("init", payload["next_actions"][0])

    def test_new_episode_records_classified_asset_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "森林奇遇", None, frame_format="16:9")
            package = create_episode(
                root,
                "EP001",
                "森林的一天",
                "小鸟和咕噜在森林里快乐的一天。",
                [],
            )
            state = json.loads((root / "episodes/EP001_森林的一天/episode-state.json").read_text(encoding="utf-8"))
            drafts = {item["name"]: item["kind"] for item in state["new_asset_drafts"]}
            self.assertEqual(drafts["小鸟"], "characters")
            self.assertEqual(drafts["森林"], "scenes")
            self.assertEqual(drafts["咕噜"], "characters")
            self.assertIn("发现新角色：小鸟、咕噜", state["detected_asset_notice"])
            self.assertIn("发现新场景：森林", state["detected_asset_notice"])
            contents = package.read_text(encoding="utf-8")
            self.assertIn("小鸟（新角色；分镜前确认；默认本集专属）", contents)
            self.assertIn("森林（新场景；分镜前确认；默认本集专属）", contents)
            status = episode_status(root, "EP001")
            self.assertEqual(status["stage"], "story_outline_pending")
            self.assertIn("user_notice", status)
            self.assertTrue(any("story-outline.md" in action for action in status["next_actions"]))

    def test_outline_must_be_confirmed_before_asset_plan_or_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(root, "EP001", "新朋友", "咕噜遇到新朋友。", [{"name": "新朋友", "kind": "characters"}])

            with self.assertRaisesRegex(ValueError, "故事概要尚未获用户确认"):
                create_asset_production_plan(root, "EP001", [])
            dispatch = dispatch_asset(root, "EP001", "新朋友")
            self.assertFalse(dispatch["allowed"])
            self.assertIn("故事概要尚未获用户确认", dispatch["reason"])

            self.approve_outline(root, "EP001")
            create_asset_production_plan(root, "EP001", [])
            self.assertTrue(dispatch_asset(root, "EP001", "新朋友")["allowed"])

    def test_asset_timing_defers_small_props_until_after_storyboard_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(
                root,
                "EP001",
                "餐桌",
                "咕噜吃饭时一直看平板。",
                [
                    {"name": "平板", "kind": "props"},
                    {"name": "餐盘", "kind": "props"},
                    {"name": "窗外树影", "kind": "scenes"},
                ],
            )
            self.approve_outline(
                root,
                "EP001",
                "\n\n## 视觉资产分级\n\n"
                "- 平板 | props | before_storyboard | 本集冲突核心，需多镜互动。\n"
                "- 餐盘 | props | before_keyframes | 仅在关键镜头近景出现。\n"
                "- 窗外树影 | scenes | incidental | 仅作普通画面装饰。",
            )

            initial = episode_status(root, "EP001")
            self.assertEqual(initial["stage"], "assets_pending")
            self.assertEqual([asset["name"] for asset in initial["before_storyboard_assets_pending"]], ["平板"])
            self.assertEqual([asset["name"] for asset in initial["before_keyframes_assets_pending"]], ["餐盘"])
            self.assertEqual([asset["name"] for asset in initial["incidental_assets"]], ["窗外树影"])

            episode = root / "episodes/EP001_餐桌"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 导演版分镜\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "分镜前确认素材尚未登记：平板"):
                record_script_and_storyboard_approval(root, "EP001")

            create_asset_production_plan(root, "EP001", [])
            production = json.loads((root / "episodes/EP001_餐桌/asset-production-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([asset["name"] for asset in production["assets"]], ["平板"])
            tablet = self.write_file(root, "generated/tablet.png", b"tablet")
            provide_episode_asset_images(root, "EP001", "平板", {"reference": tablet})
            confirm_episode_asset(root, "EP001", "平板")

            record_script_and_storyboard_approval(root, "EP001")
            deferred = episode_status(root, "EP001")
            self.assertEqual(deferred["stage"], "deferred_assets_pending")
            with self.assertRaisesRegex(ValueError, "关键帧前确认素材尚未登记：餐盘"):
                create_keyframe_plan(
                    root,
                    "EP001",
                    [{"shot_id": "01", "duration_seconds": 5, "action": "咕噜放下平板", "strategy": "start_only"}],
                )

            create_asset_production_plan(root, "EP001", [])
            rebuilt = json.loads((episode / "asset-production-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [(asset["name"], asset["timing"]) for asset in rebuilt["assets"]],
                [("平板", "before_storyboard"), ("餐盘", "before_keyframes")],
            )
            self.assertNotIn("窗外树影", {asset["name"] for asset in rebuilt["assets"]})
            plate = self.write_file(root, "generated/plate.png", b"plate")
            provide_episode_asset_images(root, "EP001", "餐盘", {"reference": plate})
            confirm_episode_asset(root, "EP001", "餐盘")
            ready = episode_status(root, "EP001")
            self.assertEqual(ready["stage"], "script_approved")
            self.assertEqual([asset["name"] for asset in ready["incidental_assets"]], ["窗外树影"])
            create_keyframe_plan(
                root,
                "EP001",
                [{"shot_id": "01", "duration_seconds": 5, "action": "咕噜放下平板", "strategy": "start_only"}],
            )

    def test_plan_created_before_outline_approval_is_superseded_and_cannot_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(root, "EP001", "餐桌", "咕噜吃饭时看平板。", [{"name": "平板", "kind": "props"}])
            episode = root / "episodes/EP001_餐桌"
            (episode / "asset-production-manifest.json").write_text(
                json.dumps(
                    {
                        "episode_id": "EP001",
                        "assets": [{"name": "平板", "kind": "props", "status": "planned"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.approve_outline(root, "EP001")
            stale = dispatch_asset(root, "EP001", "平板")
            self.assertFalse(stale["allowed"])
            self.assertIn("早于当前已确认故事概要", stale["reason"])

            create_asset_production_plan(root, "EP001", [])
            rebuilt = json.loads((episode / "asset-production-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["assets"][0]["name"], "平板")
            self.assertEqual(rebuilt["superseded_plans"][0]["reason"], "story_outline_confirmed_after_plan")
            self.assertTrue(dispatch_asset(root, "EP001", "平板")["allowed"])

    def test_story_only_cli_detects_existing_gulu_and_new_forest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.run_butler(root, "init", "--name", "奇妙岛")
            self.write_file(root, "assets/global/characters/C01_gulu/front.png", b"gulu")
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
                    }
                ],
            )
            created = self.run_butler(
                root,
                "new-episode",
                "--story",
                "小鸟和咕噜在森林里快乐的一天",
            )
            self.assertIn("已有素材：咕噜", created["user_notice"])
            self.assertIn("小鸟", created["user_notice"])
            self.assertIn("森林", created["user_notice"])
            drafts = {item["name"]: item["kind"] for item in created["status"]["new_asset_drafts"]}
            self.assertEqual(drafts["小鸟"], "characters")
            self.assertEqual(drafts["森林"], "scenes")
            self.assertNotIn("咕噜", drafts)
            outline_source = self.write_file(
                root,
                "generated/outline.md",
                "## 故事梗概\n\n测试梗概。\n\n## 人物小传\n\n咕噜。\n\n## 本集大纲\n\n起承转合。\n".encode(),
            )
            self.run_butler(root, "record-story-outline", "--episode", created["status"]["episode_id"], "--file", str(outline_source))
            self.run_butler(root, "approve-story", "--episode", created["status"]["episode_id"])
            planned = self.run_butler(root, "plan-assets", "--episode", created["status"]["episode_id"])
            names = {item["name"] for item in planned["status"]["unregistered_planned_assets"]}
            self.assertEqual(names, {"小鸟", "森林"})

    def test_legacy_name_only_drafts_still_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            write_asset_index(root, [])
            create_episode(root, "EP001", "测试集", "测试", ["小兔子"])
            state_path = root / "episodes/EP001_测试集/episode-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["new_asset_drafts"] = ["小兔子"]
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            from project_files import _refresh_episode_asset_handoff

            _refresh_episode_asset_handoff(root, "EP001")
            package = (root / "episodes/EP001_测试集/storyboard-package.md").read_text(encoding="utf-8")
            self.assertIn("小兔子（类别待确认；分镜前确认；默认本集专属）", package)

    def test_dispatch_asset_reads_kind_from_episode_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "森林奇遇", None)
            create_episode(
                root,
                "EP001",
                "森林的一天",
                "小鸟出现。",
                [{"name": "小鸟", "kind": "characters"}],
            )
            self.approve_outline(root, "EP001")
            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "小鸟", "kind": "characters", "visual_brief": "一只明亮的小鸟"}],
            )
            payload = dispatch_asset(root, "EP001", "小鸟")
            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["asset_kind"], "characters")
            self.assertTrue(payload["first_canon"])

    def test_dispatch_asset_without_kind_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "森林奇遇", None)
            create_episode(root, "EP001", "森林的一天", "测试", ["闪闪"])
            self.approve_outline(root, "EP001")
            payload = dispatch_asset(root, "EP001", "闪闪")
            self.assertFalse(payload["allowed"])
            self.assertIn("尚未根据已确认故事概要创建资产生产单", payload["reason"])

    def test_cli_init_plan_and_confirm_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.run_butler(root, "init", "--name", "森林奇遇", "--format", "16:9", "--seconds", "60")
            created = self.run_butler(
                root,
                "new-episode",
                "--episode",
                "EP001",
                "--title",
                "森林的一天",
                "--story",
                "小鸟在森林里。",
                "--asset",
                "小鸟:characters",
                "--asset",
                "森林:scenes",
            )
            self.assertEqual(created["status"]["stage"], "story_outline_pending")
            outline_source = self.write_file(
                root,
                "generated/outline.md",
                "## 故事梗概\n\n测试梗概。\n\n## 人物小传\n\n小鸟。\n\n## 本集大纲\n\n起承转合。\n".encode(),
            )
            self.run_butler(root, "record-story-outline", "--episode", "EP001", "--file", str(outline_source))
            self.run_butler(root, "approve-story", "--episode", "EP001")
            planned = self.run_butler(
                root,
                "plan-assets",
                "--episode",
                "EP001",
                "--new",
                "小鸟:characters:一只黄色小鸟",
            )
            self.assertEqual(planned["status"]["stage"], "assets_pending")
            image = self.write_file(root, "generated/bird.png", b"bird")
            self.run_butler(
                root,
                "provide-asset",
                "--episode",
                "EP001",
                "--name",
                "小鸟",
                "--image",
                f"front={image}",
            )
            confirmed = self.run_butler(root, "confirm-asset", "--episode", "EP001", "--name", "小鸟")
            self.assertEqual(confirmed["registered"]["name"], "小鸟")
            self.assertEqual(confirmed["status"]["unregistered_planned_assets"], [])

    def test_dispatch_keyframe_continues_next_stage_after_qa(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
            create_episode(root, "EP002", "海滩", "咕噜在泡泡湾挥手。", ["咕噜", "泡泡湾"])
            episode = root / "episodes/EP002_海滩"
            (episode / "formal-script.md").write_text("# 剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            self.approve_outline(root, "EP002")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(
                root,
                "EP002",
                [{"shot_id": "01", "duration_seconds": 5, "action": "咕噜挥手", "strategy": "start_only"}],
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
                ],
            )
            first = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(first["allowed"])
            self.assertEqual(
                set(first["view_image_paths"]),
                {
                    "assets/global/scenes/S03_bay/front.png",
                    "assets/global/characters/C01_gulu/front.png",
                },
            )
            output = self.write_file(root, "generated/kf.png", b"frame")
            record_stage_generation(
                root,
                "EP002",
                first["plan_id"],
                first["stage_id"],
                {
                    "plan_id": first["plan_id"],
                    "stage_id": first["stage_id"],
                    "dispatch_id": first["dispatch_id"],
                    "tool_request_id": first["dispatch_id"],
                    "prompt": first["prompt"],
                    "input_images": first["input_images"],
                    "output_path": str(output.relative_to(root)),
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "completed_at": "2026-01-01T00:00:01+00:00",
                },
            )
            record_stage_qa(
                root,
                "EP002",
                first["plan_id"],
                first["stage_id"],
                {
                    "status": "pass",
                    "reviewer_type": "automated",
                    "checked_at": "2026-01-01T00:00:02+00:00",
                    "checks": [
                        {"category": "scene", "status": "pass", "confidence": 0.95, "evidence_paths": []},
                        {"category": "character", "status": "pass", "confidence": 0.95, "evidence_paths": []},
                    ],
                    "issues": [],
                },
            )
            with self.assertRaisesRegex(ImageCanonError, "不允许准备生成：confirmed"):
                dispatch_keyframe(root, "EP002", "01", "start")

    def test_propose_story_uses_existing_cast_and_confirmed_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "奇妙岛", None)
            self.write_file(root, "assets/global/characters/C01_gulu/front.png", b"gulu")
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
                    }
                ],
            )
            create_episode(root, "EP001", "第一集", "咕噜在海边玩耍。", [])
            record_episode_continuity(
                root,
                "EP001",
                events=["咕噜捡到一只贝壳"],
                character_states=["咕噜很开心"],
                ending_frame="咕噜举着贝壳站在海边",
                unresolved_threads=["贝壳会不会发光"],
                next_episode_constraints=["必须从海边贝壳继续"],
            )
            proposed = self.run_butler(root, "propose-story")
            self.assertTrue(proposed["allowed"])
            self.assertIn("咕噜", proposed["existing_characters"])
            self.assertEqual(proposed["last_confirmed_continuity"]["episode_id"], "EP001")
            self.assertIn("必须从海边贝壳继续", proposed["last_confirmed_continuity"]["excerpt"])
            self.assertTrue(any("不要反问用户要剧情" in item for item in proposed["agent_instructions"]))
            self.assertIn("2-3", proposed["user_notice"])

    def test_inspect_includes_workflow_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            context = inspect_image_generation_context(root)
            self.assertEqual(context["workflow"]["stage"], "no_episode")
            status = project_status(root)
            self.assertEqual(status["stage"], "no_episode")
            parser = build_parser()
            self.assertIn("status", [action.dest for action in parser._subparsers._group_actions[0]._choices_actions])

    def test_refine_keyframe_accepts_repeated_items(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "refine-keyframe",
                "--episode",
                "EP004",
                "--item",
                "01/end=开关按母版",
                "--item",
                "08/start=窗外必须是夜空",
            ]
        )
        self.assertEqual(
            args.item,
            ["01/end=开关按母版", "08/start=窗外必须是夜空"],
        )
        self.assertEqual(
            _parse_refine_item("01/end=开关按母版"),
            {"shot_id": "01", "frame_kind": "end", "note": "开关按母版"},
        )
        self.assertEqual(
            _parse_refine_item("8:start=窗外必须是夜空"),
            {"shot_id": "8", "frame_kind": "start", "note": "窗外必须是夜空"},
        )
