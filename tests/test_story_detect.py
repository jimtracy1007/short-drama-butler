from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from project_files import (  # noqa: E402
    create_asset_production_plan,
    create_episode,
    decide_reuse_asset,
    initialize_project,
    approve_story_outline,
    record_story_outline,
    write_asset_index,
)
from story_detect import detect_story_assets  # noqa: E402
from workflow_status import episode_status, propose_story_context  # noqa: E402


class StoryDetectBoundaryTests(unittest.TestCase):
    def write_file(self, root: Path, relative: str, contents: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def approve_outline(self, root: Path, episode_id: str) -> None:
        record_story_outline(
            root,
            episode_id,
            "## 故事梗概\n\n测试梗概。\n\n## 人物小传\n\n主角保持既有设定。\n\n## 本集大纲\n\n起承转合。",
        )
        approve_story_outline(root, episode_id)

    def test_pending_and_other_episode_assets_are_not_auto_locked(self) -> None:
        assets = [
            {
                "asset_id": "C01",
                "name": "咕噜",
                "kind": "characters",
                "scope": "global",
                "status": "registered",
                "destination": "assets/global/characters/C01_gulu/front.png",
                "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
                "aliases": [],
            },
            {
                "asset_id": "C99",
                "name": "咕噜爸爸",
                "kind": "characters",
                "scope": "pending",
                "aliases": [],
            },
            {
                "asset_id": "C02",
                "name": "小螃蟹",
                "kind": "characters",
                "scope": "episode-EP002",
                "aliases": [],
            },
            {
                "asset_id": "S03",
                "name": "泡泡湾海滩",
                "kind": "scenes",
                "scope": "episode-EP002",
                "aliases": ["泡泡湾"],
            },
        ]
        detected = detect_story_assets(
            "咕噜和咕噜爸爸带小螃蟹去泡泡湾海滩。",
            assets,
            episode_id="EP003",
        )
        self.assertEqual([item["name"] for item in detected["known_assets"]], ["咕噜"])
        reuse_names = {item["name"] for item in detected["reuse_candidates"]}
        self.assertEqual(reuse_names, {"咕噜爸爸", "小螃蟹", "泡泡湾海滩"})
        self.assertTrue(detected["needs_confirmation"])
        self.assertNotIn("咕噜爸爸", {item["name"] for item in detected["known_assets"]})

    def test_encounter_and_together_patterns_keep_aqi_as_draft(self) -> None:
        gulu = [{
            "asset_id": "C01",
            "name": "咕噜",
            "kind": "characters",
            "scope": "global",
            "status": "registered",
            "destination": "assets/global/characters/C01_gulu/front.png",
            "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
            "aliases": [],
        }]
        encountered = detect_story_assets("咕噜遇到阿奇。", gulu, episode_id="EP001")
        self.assertEqual([item["name"] for item in encountered["known_assets"]], ["咕噜"])
        self.assertEqual(
            encountered["new_asset_drafts"],
            [{"name": "阿奇", "kind": "characters", "timing": "before_storyboard"}],
        )

        together = detect_story_assets("咕噜和阿奇一起找宝藏。", gulu, episode_id="EP001")
        draft_names = [item["name"] for item in together["new_asset_drafts"]]
        self.assertEqual(draft_names, ["阿奇"])
        self.assertNotIn("阿奇一起", draft_names)
        self.assertNotIn("宝藏", draft_names)

    def test_bookstore_story_does_not_split_overlapping_places_or_drop_roles(self) -> None:
        detected = detect_story_assets(
            "许岚在旧书店收到一支录音笔，管理员从门口走进来",
            [],
            episode_id="EP001",
        )
        drafts = {item["name"]: item["kind"] for item in detected["new_asset_drafts"]}
        self.assertEqual(drafts.get("许岚"), "characters")
        self.assertEqual(drafts.get("管理员"), "characters")
        self.assertEqual(drafts.get("旧书店"), "scenes")
        self.assertEqual(drafts.get("录音笔"), "props")
        self.assertNotIn("书店", drafts)
        self.assertNotIn("门口", drafts)

    def test_title_is_not_concatenated_so_places_are_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            write_asset_index(root, [])
            create_episode(
                root,
                "EP001",
                "许岚在旧书店收到一支录音笔",
                "许岚在旧书店收到一支录音笔，管理员从门口走进来",
                [],
            )
            state = json.loads((root / "episodes/EP001_许岚在旧书店收到一支录音笔/episode-state.json").read_text(encoding="utf-8"))
            names = [item["name"] for item in state["new_asset_drafts"]]
            self.assertEqual(names.count("旧书店"), 1)
            self.assertIn("许岚", names)
            self.assertIn("管理员", names)
            self.assertNotIn("书店", names)
            self.assertNotIn("门口", names)
            status = episode_status(root, "EP001")
            self.assertEqual(status["stage"], "story_outline_pending")
            self.assertIn("不能计划、派发或登记本集素材", status["summary"])

    def test_missing_new_character_blocks_storyboard_stage(self) -> None:
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
            create_episode(root, "EP001", "新朋友", "咕噜遇到阿奇。", [])
            status = episode_status(root, "EP001")
            self.assertEqual(status["stage"], "story_outline_pending")
            self.assertEqual(
                [item["name"] for item in status["new_asset_drafts"]],
                ["阿奇"],
            )
            self.assertFalse(status["has_storyboard"])

    def test_propose_story_refuses_when_previous_continuity_is_pending(self) -> None:
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
                    },
                    {
                        "asset_id": "C02",
                        "name": "小螃蟹",
                        "kind": "characters",
                        "scope": "episode-EP002",
                        "destination": "assets/episodes/episode-EP002/characters/C02.png",
                    },
                ],
            )
            create_episode(root, "EP002", "海滩", "咕噜在海边。", [])
            proposed = propose_story_context(root)
            self.assertFalse(proposed["allowed"])
            self.assertNotIn("小螃蟹", proposed["existing_characters"])
            self.assertIn("咕噜", proposed["existing_characters"])
            self.assertIn("不能开新一集", proposed["user_notice"])
            self.assertTrue(any("不要调用 new-episode" in item for item in proposed["agent_instructions"]))

    def test_reuse_candidates_still_block_after_planning_new_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "奇妙岛", None)
            self.write_file(root, "assets/global/characters/C01_gulu/front.png", b"gulu")
            self.write_file(root, "assets/episodes/episode-EP002/characters/C02.png", b"crab")
            write_asset_index(
                root,
                [
                    {
                        "asset_id": "C01",
                        "name": "咕噜",
                        "kind": "characters",
                        "scope": "global",
                        "destination": "assets/global/characters/C01_gulu/front.png",
                    },
                    {
                        "asset_id": "C02",
                        "name": "小螃蟹",
                        "kind": "characters",
                        "scope": "episode-EP002",
                        "destination": "assets/episodes/episode-EP002/characters/C02.png",
                    },
                ],
            )
            create_episode(root, "EP003", "森林", "咕噜和小螃蟹在森林里。", [])
            self.approve_outline(root, "EP003")
            status = episode_status(root, "EP003")
            self.assertEqual(status["stage"], "assets_pending")
            self.assertEqual([item["name"] for item in status["reuse_candidates"]], ["小螃蟹"])
            create_asset_production_plan(root, "EP003", [])
            after_plan = episode_status(root, "EP003")
            self.assertNotEqual(after_plan["stage"], "assets_ready")
            self.assertIn("不能写正式剧本或分镜", after_plan["summary"])
            decide_reuse_asset(root, "EP003", "小螃蟹", "use")
            reused = json.loads((root / "episodes/EP003_森林/episode-state.json").read_text(encoding="utf-8"))
            self.assertIn("C02", reused["asset_ids"])
            self.assertEqual(reused["reuse_candidates"], [])

    def test_pending_reuse_becomes_draft_instead_of_locking(self) -> None:
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
                    },
                    {
                        "asset_id": "C05",
                        "name": "咕噜爸爸",
                        "kind": "characters",
                        "scope": "pending",
                        "destination": "assets/pending/characters/C05.png",
                    },
                ],
            )
            create_episode(root, "EP001", "爸爸", "咕噜和咕噜爸爸去海边。", [])
            self.approve_outline(root, "EP001")
            state = json.loads((root / "episodes/EP001_爸爸/episode-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["asset_ids"], ["C01"])
            self.assertEqual([item["name"] for item in state["reuse_candidates"]], ["咕噜爸爸"])
            decided = decide_reuse_asset(root, "EP001", "咕噜爸爸", "use")
            self.assertNotIn("C05", decided["asset_ids"])
            draft_kinds = {item["name"]: item["kind"] for item in decided["new_asset_drafts"]}
            self.assertEqual(draft_kinds["咕噜爸爸"], "characters")
            self.assertEqual(decided["reuse_candidates"], [])

    def test_global_planned_asset_is_not_auto_locked(self) -> None:
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
                        "status": "planned",
                        "destination": "assets/global/characters/C01_gulu/front.png",
                        "views": [{"variant": "front", "path": "assets/global/characters/C01_gulu/front.png"}],
                    }
                ],
            )
            detected = detect_story_assets(
                "咕噜在森林里。",
                json.loads((root / "project-settings/asset-index.json").read_text(encoding="utf-8"))["assets"],
                episode_id="EP001",
                project_root=root,
            )
            self.assertEqual(detected["known_assets"], [])
            self.assertEqual([item["name"] for item in detected["reuse_candidates"]], ["咕噜"])
            create_episode(root, "EP001", "森林", "咕噜在森林里。", [])
            state = json.loads((root / "episodes/EP001_森林/episode-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["asset_ids"], [])
            self.assertEqual([item["name"] for item in state["reuse_candidates"]], ["咕噜"])
            status = episode_status(root, "EP001")
            self.assertEqual(status["stage"], "story_outline_pending")
            self.assertIn("不能计划、派发或登记本集素材", status["summary"])

    def test_season_image_provided_asset_is_not_offered_as_existing_cast(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "奇妙岛", None)
            self.write_file(root, "assets/season-1/characters/C08_shanshan/front.png", b"spark")
            write_asset_index(
                root,
                [
                    {
                        "asset_id": "C08",
                        "name": "闪闪",
                        "kind": "characters",
                        "scope": "season-1",
                        "status": "image_provided",
                        "destination": "assets/season-1/characters/C08_shanshan/front.png",
                        "views": [{"variant": "front", "path": "assets/season-1/characters/C08_shanshan/front.png"}],
                    }
                ],
            )
            proposed = propose_story_context(root)
            self.assertTrue(proposed["allowed"])
            self.assertNotIn("闪闪", proposed["existing_characters"])
            detected = detect_story_assets(
                "闪闪在海边。",
                json.loads((root / "project-settings/asset-index.json").read_text(encoding="utf-8"))["assets"],
                episode_id="EP001",
                project_root=root,
            )
            self.assertEqual(detected["known_assets"], [])
            self.assertEqual([item["name"] for item in detected["reuse_candidates"]], ["闪闪"])
            self.assertTrue(detected["needs_confirmation"])
