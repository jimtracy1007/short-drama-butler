from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from butler import build_parser  # noqa: E402
from codex_image_dispatch import dispatch_asset, dispatch_keyframe, inspect_image_generation_context  # noqa: E402
from image_canon import ImageCanonError  # noqa: E402
from project_files import (  # noqa: E402
    approve_keyframe_plan,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    initialize_project,
    record_script_and_storyboard_approval,
    record_stage_generation,
    record_stage_qa,
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
                [
                    {"name": "咕噜", "kind": "characters"},
                    {"name": "小鸟", "kind": "characters"},
                    {"name": "森林", "kind": "scenes"},
                ],
            )
            state = json.loads((root / "episodes/EP001_森林的一天/episode-state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                state["new_asset_drafts"],
                [
                    {"name": "咕噜", "kind": "characters"},
                    {"name": "小鸟", "kind": "characters"},
                    {"name": "森林", "kind": "scenes"},
                ],
            )
            contents = package.read_text(encoding="utf-8")
            self.assertIn("小鸟（新角色；默认本集专属）", contents)
            self.assertIn("森林（新场景；默认本集专属）", contents)
            status = episode_status(root, "EP001")
            self.assertEqual(status["stage"], "episode_created")

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
            self.assertIn("小兔子（类别待确认；默认本集专属）", package)

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
            payload = dispatch_asset(root, "EP001", "小鸟")
            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["asset_kind"], "characters")
            self.assertTrue(payload["first_canon"])

    def test_dispatch_asset_without_kind_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "森林奇遇", None)
            create_episode(root, "EP001", "森林的一天", "小鸟出现。", ["小鸟"])
            with self.assertRaisesRegex(ImageCanonError, "无法确定素材类别：小鸟"):
                dispatch_asset(root, "EP001", "小鸟")

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
            self.assertEqual(created["status"]["stage"], "episode_created")
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
            self.assertEqual(first["view_image_paths"], ["assets/global/scenes/S03_bay/front.png"])
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
                    "checks": [{"category": "scene", "status": "pass", "confidence": 0.95, "evidence_paths": []}],
                    "issues": [],
                },
            )
            second = dispatch_keyframe(root, "EP002", "01", "start")
            self.assertTrue(second["allowed"])
            self.assertNotEqual(second["dispatch_id"], first["dispatch_id"])
            self.assertIn("assets/global/characters/C01_gulu/front.png", second["view_image_paths"])

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
