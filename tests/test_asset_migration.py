from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from asset_migration import (  # noqa: E402
    AssetMigrationError,
    build_plan,
    execute_plan,
    rollback,
)
from project_files import (  # noqa: E402
    build_asset_index,
    approve_keyframe_plan,
    assert_keyframe_generation_allowed,
    confirm_episode_asset,
    create_asset_production_plan,
    create_episode,
    create_keyframe_execution_pack,
    create_keyframe_plan,
    begin_stage_generation,
    initialize_project,
    prepare_keyframe_generation,
    record_stage_generation,
    record_stage_qa,
    request_keyframe_regeneration,
    register_user_override,
    record_reference_board,
    approve_reference_board,
    register_asset,
    register_project_asset,
    recommend_keyframe_strategy,
    record_episode_continuity,
    provide_episode_asset_image,
    provide_episode_asset_images,
    record_script_and_storyboard_approval,
    resolve_asset_references,
    write_asset_index,
)
from extract_docx_text import extract_text  # noqa: E402
from storyboard_dependency import (  # noqa: E402
    DependencyError,
    UPSTREAM_ARCHIVE_SHA256,
    UPSTREAM_ARCHIVE_URL,
    UPSTREAM_REVISION,
    extract_skill_from_archive,
    find_installed_skill,
)


class AssetMigrationTests(unittest.TestCase):
    def write_file(self, root: Path, relative: str, contents: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def test_build_plan_preserves_hash_and_uses_canonical_asset_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = self.write_file(root, "images/咕噜.png", b"gulu")
            plan = build_plan(
                root,
                [{"source": "images/咕噜.png", "asset_id": "C01", "kind": "characters", "slug": "gulu", "variant": "front", "scope": "global"}],
            )

            self.assertEqual(plan["records"][0]["destination"], "assets/global/characters/C01_gulu/front.png")
            self.assertEqual(plan["records"][0]["sha256"], hashlib.sha256(image.read_bytes()).hexdigest())

    def test_build_plan_preserves_the_original_file_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(root, "images/主角.jpg", b"jpg")
            plan = build_plan(
                root,
                [{"source": "images/主角.jpg", "asset_id": "C01", "kind": "characters", "slug": "lead", "variant": "front", "scope": "global"}],
            )
            self.assertEqual(plan["records"][0]["destination"], "assets/global/characters/C01_lead/front.jpg")

    def test_execute_then_rollback_restores_every_source_without_changing_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = self.write_file(root, "images/咕噜.png", b"gulu")
            plan = build_plan(
                root,
                [{"source": "images/咕噜.png", "asset_id": "C01", "kind": "characters", "slug": "gulu", "variant": "front", "scope": "global"}],
            )
            ledger_path = execute_plan(root, plan)

            self.assertFalse(original.exists())
            moved = root / "assets/global/characters/C01_gulu/front.png"
            self.assertEqual(moved.read_bytes(), b"gulu")
            self.assertEqual(json.loads(ledger_path.read_text(encoding="utf-8"))["records"][0]["status"], "moved")

            rollback(root, ledger_path)
            self.assertEqual(original.read_bytes(), b"gulu")
            self.assertFalse(moved.exists())

    def test_duplicate_destinations_abort_before_any_file_is_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self.write_file(root, "images/甲.png", b"first")
            second = self.write_file(root, "images/乙.png", b"second")
            with self.assertRaisesRegex(AssetMigrationError, "重复目标"):
                build_plan(
                    root,
                    [
                        {"source": "images/甲.png", "asset_id": "C01", "kind": "characters", "slug": "gulu", "variant": "front", "scope": "global"},
                        {"source": "images/乙.png", "asset_id": "C01", "kind": "characters", "slug": "gulu", "variant": "front", "scope": "global"},
                    ],
                )
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_initializer_moves_source_document_and_writes_an_episode_handoff_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_document = root / "旧资料.docx"
            with zipfile.ZipFile(source_document, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>旧设定文本</w:t></w:r></w:p></w:body></w:document>',
                )

            initialize_project(
                root,
                "奇妙岛怪事",
                source_document,
                audience="3—8 岁",
                frame_format="16:9 横屏",
                episode_target_seconds=120,
                content_guidelines="温暖、明亮、儿童友好；无恐怖、攻击性、字幕、Logo 或水印",
            )
            write_asset_index(root, [{"asset_id": "C01", "name": "咕噜", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_gulu/front.png"}])
            package = create_episode(root, "EP001", "分享的泡泡", "咕噜学习分享玩具", ["C01"])

            self.assertFalse(source_document.exists())
            self.assertTrue((root / "source-material/固定设定.docx").is_file())
            self.assertIn("16:9", (root / "project-settings/project.yaml").read_text(encoding="utf-8"))
            contents = package.read_text(encoding="utf-8")
            self.assertIn("120 秒", contents)
            self.assertIn("镜头数量由剧情节奏、动作、对白和情绪变化决定", contents)
            self.assertIn("C01｜咕噜", contents)
            self.assertIn("fixed-settings-source.txt", contents)
            self.assertIn("formal-script.md", contents)
            self.assertIn("storyboard.md", contents)
            self.assertIn("台词与口型时间段", contents)
            self.assertIn("非说话嘴型控制", contents)
            self.assertEqual((root / "project-settings/fixed-settings-source.txt").read_text(encoding="utf-8"), "旧设定文本\n")

    def test_asset_index_groups_multiple_views_under_one_asset_id(self) -> None:
        index = build_asset_index(
            [
                {"asset_id": "C01", "name": "咕噜", "aliases": ["小怪兽"], "kind": "characters", "scope": "global", "variant": "front", "destination": "assets/global/characters/C01_gulu/front.png"},
                {"asset_id": "C01", "name": "咕噜", "kind": "characters", "scope": "global", "variant": "back", "destination": "assets/global/characters/C01_gulu/back.png"},
            ]
        )
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["destination"], "assets/global/characters/C01_gulu/front.png")
        self.assertEqual([view["variant"] for view in index[0]["views"]], ["front", "back"])
        self.assertEqual(index[0]["aliases"], ["小怪兽"])

    def test_keyframe_plan_requires_two_user_approval_gates_and_keeps_per_shot_frame_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, frame_format="16:9", episode_target_seconds=120)
            create_episode(root, "EP001", "海边新朋友", "咕噜帮助小螃蟹回海。", [])
            episode_dir = root / "episodes/EP001_海边新朋友"
            (episode_dir / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode_dir / "storyboard.md").write_text("# 分镜表\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "剧本和分镜"):
                create_keyframe_plan(
                    root,
                    "EP001",
                    [
                        {"shot_id": "01", "duration_seconds": 4, "action": "咕噜看向海面", "strategy": "start_only"},
                        {"shot_id": "02", "duration_seconds": 10, "action": "小螃蟹沿水道回海", "strategy": "start_end"},
                        {
                            "shot_id": "03",
                            "duration_seconds": 10,
                            "action": "水道从沙坑连到大海",
                            "strategy": "start_middle_end",
                            "exception_reason": "水流成形、连通大海和角色反应需要三个清晰阶段",
                        },
                    ],
                )

            record_script_and_storyboard_approval(root, "EP001")
            plan_path = create_keyframe_plan(
                root,
                "EP001",
                [
                    {"shot_id": "01", "duration_seconds": 4, "action": "咕噜看向海面", "strategy": "start_only"},
                    {"shot_id": "02", "duration_seconds": 10, "action": "小螃蟹沿水道回海", "strategy": "start_end"},
                    {
                        "shot_id": "03",
                        "duration_seconds": 10,
                        "action": "水道从沙坑连到大海",
                        "strategy": "start_middle_end",
                        "exception_reason": "水流成形、连通大海和角色反应需要三个清晰阶段",
                    },
                ],
            )
            contents = plan_path.read_text(encoding="utf-8")
            self.assertIn("状态：待用户确认", contents)
            self.assertIn("| 01 | 4 秒 | 1 张（首帧）", contents)
            self.assertIn("| 02 | 10 秒 | 2 张（首帧、尾帧）", contents)
            self.assertIn("| 03 | 10 秒 | 3 张（首帧、过程帧、尾帧）", contents)
            self.assertIn("待逐镜确认", contents)
            with self.assertRaisesRegex(ValueError, "关键帧方案"):
                assert_keyframe_generation_allowed(root, "EP001")

            approve_keyframe_plan(root, "EP001")
            self.assertTrue(assert_keyframe_generation_allowed(root, "EP001"))

    def test_keyframe_timing_defaults_and_middle_frame_exception_require_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, frame_format="16:9", episode_target_seconds=120)
            create_episode(root, "EP001", "魔法测试", "测试关键帧节奏。", [])
            episode_dir = root / "episodes/EP001_魔法测试"
            (episode_dir / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode_dir / "storyboard.md").write_text("# 导演版分镜\n", encoding="utf-8")
            record_script_and_storyboard_approval(root, "EP001")

            self.assertEqual(recommend_keyframe_strategy(3), "start_only")
            self.assertEqual(recommend_keyframe_strategy(5), "start_only")
            self.assertEqual(recommend_keyframe_strategy(10), "start_end")
            with self.assertRaisesRegex(ValueError, "5 秒、10 秒"):
                recommend_keyframe_strategy(7)

            with self.assertRaisesRegex(ValueError, "特殊原因"):
                create_keyframe_plan(
                    root,
                    "EP001",
                    [{"shot_id": "02", "duration_seconds": 10, "action": "魔法变形", "strategy": "start_middle_end"}],
                )

            plan = create_keyframe_plan(
                root,
                "EP001",
                [
                    {"shot_id": "01", "duration_seconds": 5, "action": "主角回头", "strategy": "start_only"},
                    {
                        "shot_id": "02",
                        "duration_seconds": 10,
                        "action": "魔法泡泡分三阶段变形",
                        "strategy": "start_middle_end",
                        "exception_reason": "中间状态决定变形是否连贯",
                    },
                ],
            )
            self.assertIn("待逐镜确认", plan.read_text(encoding="utf-8"))

            approve_keyframe_plan(root, "EP001")
            manifest = json.loads((episode_dir / "keyframe-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["shots"][1]["strategy"], "start_end")
            self.assertEqual(manifest["shots"][1]["frames"], ["start", "end"])
            self.assertEqual(manifest["shots"][1]["middle_frame_status"], "defaulted_to_two_frames")

            create_keyframe_plan(
                root,
                "EP001",
                [
                    {
                        "shot_id": "02",
                        "duration_seconds": 10,
                        "action": "魔法泡泡分三阶段变形",
                        "strategy": "start_middle_end",
                        "exception_reason": "中间状态决定变形是否连贯",
                    }
                ],
            )
            approve_keyframe_plan(root, "EP001", approved_middle_shot_ids=["02"])
            manifest = json.loads((episode_dir / "keyframe-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["shots"][0]["frames"], ["start", "middle", "end"])
            self.assertEqual(manifest["shots"][0]["middle_frame_status"], "user_confirmed")

    def test_keyframe_execution_pack_preserves_storyboard_fields_and_adds_frame_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, frame_format="16:9", episode_target_seconds=120)
            self.write_file(root, "assets/global/characters/C01_crab/front.png", b"crab")
            self.write_file(root, "assets/global/scenes/S01_beach/front.png", b"beach")
            write_asset_index(
                root,
                [
                    {"asset_id": "C01", "name": "小螃蟹", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_crab/front.png", "views": [{"variant": "front", "path": "assets/global/characters/C01_crab/front.png"}]},
                    {"asset_id": "S01", "name": "泡泡湾海滩", "kind": "scenes", "scope": "global", "destination": "assets/global/scenes/S01_beach/front.png", "views": [{"variant": "front", "path": "assets/global/scenes/S01_beach/front.png"}]},
                ],
            )
            create_episode(root, "EP001", "海边新朋友", "咕噜帮助小螃蟹回海。", [])
            episode_dir = root / "episodes/EP001_海边新朋友"
            (episode_dir / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode_dir / "storyboard.md").write_text("# 分镜表\n", encoding="utf-8")
            record_script_and_storyboard_approval(root, "EP001")
            create_keyframe_plan(
                root,
                "EP001",
                [{"shot_id": "02", "duration_seconds": 10, "action": "小螃蟹沿水道回海", "strategy": "start_end"}],
            )
            approve_keyframe_plan(root, "EP001")

            execution_path = create_keyframe_execution_pack(
                root,
                "EP001",
                [
                    {
                        "shot_id": "02",
                        "shot_size": "低机位中景",
                        "camera_movement": "缓慢跟拍",
                        "scene": "泡泡湾海滩水道",
                        "asset_references": ["小螃蟹", "泡泡湾海滩"],
                        "asset_uses": [
                            {"reference": "小螃蟹", "role": "character_identity", "required": True},
                            {"reference": "泡泡湾海滩", "role": "background", "required": True},
                        ],
                        "start_state": "小螃蟹抱住小贝壳，站在水道起点",
                        "motion": "横着走三步，水面泛起细小涟漪",
                        "end_state": "小螃蟹靠近浅海并回头",
                        "dialogue": "咕噜（画外音）：慢慢走，我陪你走。",
                        "voice_strategy": "后期配音，不要求视频生成口型",
                        "sound_effects": "浅水流动、细小脚步、远处海浪",
                        "transition_in": "承接上一镜水道刚被注满的水流声",
                        "transition_out": "小螃蟹回头的视线切至浅海挥钳镜头",
                        "storyboard_image_prompt": "软萌3D儿童动画，低机位中景，小螃蟹抱贝壳走在浅水道中，金色湿沙与明亮海面。",
                        "frame_prompts": {
                            "start": "软萌3D儿童动画，低机位中景，小螃蟹抱住小贝壳站在水道起点。",
                            "end": "软萌3D儿童动画，低机位中景，小螃蟹抱住小贝壳靠近浅海并回头。",
                        },
                        "frame_specs": {
                            "start": {"continuity_contract": None, "allowed_changes": ["建立水道"], "invariants": ["小螃蟹身份"]},
                            "end": {"continuity_contract": {"predecessor": {"shot_id": "02", "frame_kind": "start"}, "inherit_dimensions": ["space", "character_identity"], "asset_ids": ["C01", "S01"]}},
                        },
                    }
                ],
            )

            contents = execution_path.read_text(encoding="utf-8")
            self.assertIn("- 时长：10 秒", contents)
            self.assertIn("- 台词：咕噜（画外音）：慢慢走，我陪你走。", contents)
            self.assertIn("- 声音策略：后期配音，不要求视频生成口型", contents)
            self.assertIn("- 入点：承接上一镜水道刚被注满的水流声", contents)
            self.assertIn("- 出点 / 转场：小螃蟹回头的视线切至浅海挥钳镜头", contents)
            self.assertIn("| start | `待确认`", contents)
            self.assertIn("| end | `待确认`", contents)
            self.assertIn("10 秒，16:9，低机位中景，缓慢跟拍", contents)
            manifest = json.loads((episode_dir / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["shots"][0]["frames"][1]["status"], "waiting_for_dependency")

    def test_v2_generation_waits_for_dependency_and_records_qa_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            self.write_file(root, "assets/S01.png", b"beach")
            write_asset_index(root, [{"asset_id": "S01", "name": "海滩", "kind": "scenes", "scope": "global", "destination": "assets/S01.png", "views": [{"variant": "front", "path": "assets/S01.png"}]}])
            create_episode(root, "EP001", "测试集", "测试", [])
            episode = root / "episodes/EP001_测试集"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            record_script_and_storyboard_approval(root, "EP001")
            create_keyframe_plan(root, "EP001", [{"shot_id": "01", "duration_seconds": 10, "action": "海浪靠岸", "strategy": "start_end"}])
            approve_keyframe_plan(root, "EP001")
            create_keyframe_execution_pack(
                root, "EP001", [{
                    "shot_id": "01", "shot_size": "全景", "camera_movement": "固定", "scene": "海滩", "asset_references": ["海滩"],
                    "asset_uses": [{"reference": "海滩", "role": "background", "required": True}],
                    "start_state": "海浪靠岸", "motion": "浪花推进", "end_state": "浪花退去", "dialogue": "无", "voice_strategy": "后期配音", "sound_effects": "海浪", "transition_in": "淡入", "transition_out": "淡出", "storyboard_image_prompt": "明亮海滩",
                    "frame_prompts": {"start": "海浪靠岸", "end": "浪花退去"},
                    "frame_specs": {"start": {"continuity_contract": None}, "end": {"continuity_contract": {"predecessor": {"shot_id": "01", "frame_kind": "start"}, "inherit_dimensions": ["space"], "asset_ids": ["S01"]}}},
                }],
            )
            waiting = prepare_keyframe_generation(root, "EP001", "01", "end")
            self.assertEqual(waiting["status"], "waiting_for_dependency")
            start_plan = prepare_keyframe_generation(root, "EP001", "01", "start")
            stage = start_plan["stages"][0]
            original_asset = (root / "assets/S01.png").read_bytes()
            (root / "assets/S01.png").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "哈希不匹配"):
                begin_stage_generation(root, "EP001", start_plan["plan_id"], stage["stage_id"])
            (root / "assets/S01.png").write_bytes(original_asset)
            start_dispatch = begin_stage_generation(root, "EP001", start_plan["plan_id"], stage["stage_id"])
            self.write_file(root, "provider/start.png", b"start-result")
            with self.assertRaisesRegex(ValueError, "prompt"):
                record_stage_generation(root, "EP001", start_plan["plan_id"], stage["stage_id"], {
                    "plan_id": start_plan["plan_id"], "stage_id": stage["stage_id"], "dispatch_id": start_dispatch["dispatch_id"], "tool_request_id": "req-wrong-prompt", "prompt": "私自改写的提示词", "input_images": start_dispatch["input_images"], "output_path": "provider/start.png", "started_at": "2026-08-15T00:00:00Z", "completed_at": "2026-08-15T00:01:00Z",
                })
            generation = record_stage_generation(root, "EP001", start_plan["plan_id"], stage["stage_id"], {
                "plan_id": start_plan["plan_id"], "stage_id": stage["stage_id"], "dispatch_id": start_dispatch["dispatch_id"], "tool_request_id": "req-start", "prompt": start_dispatch["prompt"], "input_images": start_dispatch["input_images"], "output_path": "provider/start.png", "started_at": "2026-08-15T00:00:00Z", "completed_at": "2026-08-15T00:01:00Z",
            })
            self.assertTrue(generation["path"].startswith("episodes/EP001_测试集/keyframes/work/KF01-start/r001-"))
            record_stage_qa(root, "EP001", start_plan["plan_id"], stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T00:02:00Z", "checks": [{"category": "scene", "status": "pass", "confidence": 0.9, "evidence_paths": []}], "issues": [],
            })
            # A user-authorized public regeneration retains the first revision
            # and invalidates any downstream continuity anchor.
            manifest_path = episode / "keyframe-execution-manifest.json"
            redo = request_keyframe_regeneration(root, "EP001", "01", "start", "海浪形状需要修正")
            self.assertEqual(redo["invalidated_dependents"], [{"shot_id": "01", "frame_kind": "end"}])
            replacement_plan = prepare_keyframe_generation(root, "EP001", "01", "start")
            with self.assertRaisesRegex(ValueError, "新版计划"):
                begin_stage_generation(root, "EP001", start_plan["plan_id"], stage["stage_id"])
            replacement_stage = replacement_plan["stages"][0]
            replacement_dispatch = begin_stage_generation(root, "EP001", replacement_plan["plan_id"], replacement_stage["stage_id"])
            self.write_file(root, "provider/start-r002.png", b"start-replacement")
            record_stage_generation(root, "EP001", replacement_plan["plan_id"], replacement_stage["stage_id"], {
                "plan_id": replacement_plan["plan_id"], "stage_id": replacement_stage["stage_id"], "dispatch_id": replacement_dispatch["dispatch_id"], "tool_request_id": "req-start-r002", "prompt": replacement_dispatch["prompt"], "input_images": replacement_dispatch["input_images"], "output_path": "provider/start-r002.png", "started_at": "2026-08-15T00:02:30Z", "completed_at": "2026-08-15T00:03:00Z",
            })
            record_stage_qa(root, "EP001", replacement_plan["plan_id"], replacement_stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T00:03:30Z", "checks": [{"category": "scene", "status": "pass", "confidence": 0.95, "evidence_paths": []}], "issues": [],
            })
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            start_history = manifest["shots"][0]["frames"][0]["confirmed_revisions"]
            self.assertEqual([item["revision"] for item in start_history], ["r001", "r002"])
            self.assertEqual(start_history[0]["superseded_by"], "r002")
            self.assertEqual(start_history[1]["supersedes"], "r001")
            self.assertEqual(manifest["shots"][0]["frames"][0]["confirmed_revision"]["revision"], "r002")
            end_plan = prepare_keyframe_generation(root, "EP001", "01", "end")
            self.assertEqual(end_plan["status"], "planned")
            end_stage = end_plan["stages"][0]
            self.assertEqual(end_stage["input_images"][0]["role"], "edit_target")
            end_dispatch = begin_stage_generation(root, "EP001", end_plan["plan_id"], end_stage["stage_id"])
            self.write_file(root, "provider/end.png", b"end-result")
            record_stage_generation(root, "EP001", end_plan["plan_id"], end_stage["stage_id"], {
                "plan_id": end_plan["plan_id"], "stage_id": end_stage["stage_id"], "dispatch_id": end_dispatch["dispatch_id"], "tool_request_id": "req-end", "prompt": end_dispatch["prompt"], "input_images": end_dispatch["input_images"], "output_path": "provider/end.png", "started_at": "2026-08-15T00:03:00Z", "completed_at": "2026-08-15T00:04:00Z",
            })
            record_stage_qa(root, "EP001", end_plan["plan_id"], end_stage["stage_id"], {
                "status": "uncertain", "reviewer_type": "automated", "checked_at": "2026-08-15T00:05:00Z", "checks": [{"category": "continuity", "status": "uncertain", "confidence": 0.6, "evidence_paths": []}], "issues": [],
            })
            with self.assertRaisesRegex(ValueError, "不允许准备"):
                prepare_keyframe_generation(root, "EP001", "01", "end")
            confirmed = record_stage_qa(root, "EP001", end_plan["plan_id"], end_stage["stage_id"], {
                "status": "pass", "reviewer_type": "user", "checked_at": "2026-08-15T00:06:00Z", "checks": [{"category": "continuity", "status": "pass", "confidence": 1.0, "evidence_paths": []}], "issues": [],
            })
            self.assertEqual(confirmed["status"], "qa_passed")
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["shots"][0]["frames"][1]["status"], "confirmed")
            self.assertTrue((root / manifest["shots"][0]["frames"][1]["confirmed_revision"]["path"]).is_file())
            self.write_file(root, "uploads/beach.png", b"user-beach")
            override = register_user_override(root, "EP001", {"path": "uploads/beach.png", "role": "background", "scope": "shot", "scope_ids": ["01"]})
            self.assertTrue((root / override["path"]).is_file())
            self.assertEqual(override["role"], "background")

    def test_ep002_uses_names_to_complete_a_v2_keyframe_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            self.write_file(root, "assets/S01.png", b"beach")
            self.write_file(root, "assets/C01.png", b"crab")
            self.write_file(root, "assets/P01.png", b"shell")
            write_asset_index(root, [
                {"asset_id": "S01", "name": "海滩", "aliases": ["金色沙滩"], "kind": "scenes", "scope": "global", "destination": "assets/S01.png", "views": [{"variant": "wide", "path": "assets/S01.png"}]},
                {"asset_id": "C01", "name": "咕噜", "aliases": ["小螃蟹"], "kind": "characters", "scope": "global", "destination": "assets/C01.png", "views": [{"variant": "front", "path": "assets/C01.png"}]},
                {"asset_id": "P01", "name": "彩纹贝壳", "kind": "props", "scope": "global", "destination": "assets/P01.png", "views": [{"variant": "reference", "path": "assets/P01.png"}]},
            ])
            create_episode(root, "EP002", "海滩小螃蟹", "咕噜找到彩纹贝壳。", [])
            episode = root / "episodes/EP002_海滩小螃蟹"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            record_script_and_storyboard_approval(root, "EP002")
            create_keyframe_plan(root, "EP002", [{"shot_id": "01", "duration_seconds": 5, "action": "咕噜举起贝壳", "strategy": "start_only"}])
            approve_keyframe_plan(root, "EP002")
            create_keyframe_execution_pack(root, "EP002", [{
                "shot_id": "01", "shot_size": "中景", "camera_movement": "固定", "scene": "金色沙滩",
                "asset_references": ["金色沙滩", "小螃蟹", "彩纹贝壳"],
                "asset_uses": [
                    {"reference": "金色沙滩", "role": "background", "required": True},
                    {"reference": "小螃蟹", "role": "character_identity", "required": True, "subject_tier": "primary"},
                    {"reference": "彩纹贝壳", "role": "prop_identity", "required": True, "subject_tier": "primary"},
                ],
                "start_state": "咕噜发现贝壳", "motion": "举起贝壳", "end_state": "咕噜微笑", "dialogue": "哇，好漂亮！", "voice_strategy": "后期配音", "sound_effects": "海浪", "transition_in": "淡入", "transition_out": "淡出", "storyboard_image_prompt": "儿童 3D 海滩",
                "frame_prompts": {"start": "儿童 3D 动画，咕噜在金色沙滩举起彩纹贝壳。"},
                "frame_specs": {"start": {"continuity_contract": None, "allowed_changes": ["咕噜举起贝壳"], "invariants": ["海滩、咕噜和贝壳身份"]}},
            }])
            plan = prepare_keyframe_generation(root, "EP002", "01", "start")
            background_stage, subject_stage = plan["stages"]
            self.assertEqual(set(background_stage["required_qa_categories"]), {"scene"})
            self.assertEqual(set(subject_stage["required_qa_categories"]), {"character", "continuity", "prop"})
            background_dispatch = begin_stage_generation(root, "EP002", plan["plan_id"], background_stage["stage_id"])
            self.write_file(root, "provider/ep002-background.png", b"ep002-background")
            record_stage_generation(root, "EP002", plan["plan_id"], background_stage["stage_id"], {
                "plan_id": plan["plan_id"], "stage_id": background_stage["stage_id"], "dispatch_id": background_dispatch["dispatch_id"], "tool_request_id": "req-ep002-background", "prompt": background_dispatch["prompt"], "input_images": background_dispatch["input_images"], "output_path": "provider/ep002-background.png", "started_at": "2026-08-15T01:00:00Z", "completed_at": "2026-08-15T01:01:00Z",
            })
            record_stage_qa(root, "EP002", plan["plan_id"], background_stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T01:02:00Z",
                "checks": [{"category": "scene", "status": "pass", "confidence": 0.95, "evidence_paths": []}], "issues": [],
            })
            subject_dispatch = begin_stage_generation(root, "EP002", plan["plan_id"], subject_stage["stage_id"])
            self.write_file(root, "provider/ep002-subjects.png", b"ep002-subjects")
            record_stage_generation(root, "EP002", plan["plan_id"], subject_stage["stage_id"], {
                "plan_id": plan["plan_id"], "stage_id": subject_stage["stage_id"], "dispatch_id": subject_dispatch["dispatch_id"], "tool_request_id": "req-ep002-subjects", "prompt": subject_dispatch["prompt"], "input_images": subject_dispatch["input_images"], "output_path": "provider/ep002-subjects.png", "started_at": "2026-08-15T01:03:00Z", "completed_at": "2026-08-15T01:04:00Z",
            })
            record_stage_qa(root, "EP002", plan["plan_id"], subject_stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T01:05:00Z",
                "checks": [
                    {"category": "character", "status": "pass", "confidence": 0.95, "evidence_paths": []},
                    {"category": "prop", "status": "pass", "confidence": 0.95, "evidence_paths": []},
                    {"category": "continuity", "status": "pass", "confidence": 0.95, "evidence_paths": []},
                ], "issues": [],
            })
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            frame = manifest["shots"][0]["frames"][0]
            self.assertEqual(frame["status"], "confirmed")
            self.assertTrue((root / frame["confirmed_revision"]["path"]).is_file())

    def test_v2_reference_board_requires_registration_and_user_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            assets = []
            uses = []
            members = []
            for number in range(1, 7):
                path = self.write_file(root, f"assets/C{number:02d}.png", f"C{number}".encode())
                asset_id = f"C{number:02d}"
                assets.append({"asset_id": asset_id, "name": asset_id, "kind": "characters", "scope": "global", "destination": path.relative_to(root).as_posix(), "views": [{"variant": "front", "path": path.relative_to(root).as_posix()}]})
                uses.append({"reference": asset_id, "role": "character_identity", "required": True, "relationship_group": "hold-hands"})
                members.append({"asset_id": asset_id, "path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            write_asset_index(root, assets)
            create_episode(root, "EP001", "群像", "测试", [])
            episode = root / "episodes/EP001_群像"
            (episode / "formal-script.md").write_text("# 正式剧本\n", encoding="utf-8")
            (episode / "storyboard.md").write_text("# 分镜\n", encoding="utf-8")
            record_script_and_storyboard_approval(root, "EP001")
            create_keyframe_plan(root, "EP001", [{"shot_id": "01", "duration_seconds": 5, "action": "大家牵手", "strategy": "start_only"}])
            approve_keyframe_plan(root, "EP001")
            create_keyframe_execution_pack(root, "EP001", [{
                "shot_id": "01", "shot_size": "全景", "camera_movement": "固定", "scene": "广场", "asset_references": [item["reference"] for item in uses], "asset_uses": uses,
                "start_state": "牵手", "motion": "微笑", "end_state": "牵手", "dialogue": "无", "voice_strategy": "后期", "sound_effects": "无", "transition_in": "切入", "transition_out": "切出", "storyboard_image_prompt": "群像", "frame_prompts": {"start": "群像"}, "frame_specs": {"start": {"continuity_contract": None}},
            }])
            self.write_file(root, "uploads/first.png", b"first")
            self.write_file(root, "uploads/second.png", b"second")
            first_override = register_user_override(root, "EP001", {"path": "uploads/first.png", "role": "background", "scope": "shot", "scope_ids": ["01"]})
            second_override = register_user_override(root, "EP001", {"path": "uploads/second.png", "role": "background", "scope": "shot", "scope_ids": ["01"]})
            manifest = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            first_record = next(item for item in manifest["user_overrides"] if item["override_id"] == first_override["override_id"])
            self.assertEqual(first_record["status"], "superseded")
            self.assertEqual(first_record["superseded_by"], second_override["override_id"])
            needed = prepare_keyframe_generation(root, "EP001", "01", "start")
            self.assertEqual(needed["status"], "reference_board_required")
            self.assertEqual(needed["applicable_overrides"]["superseded"][0]["superseded_by"], second_override["override_id"])
            self.write_file(root, "provider/board.png", b"board")
            board = record_reference_board(root, "EP001", {"plan_id": needed["plan_id"], "relationship_group": "hold-hands", "output_path": "provider/board.png", "members": members, "layout": "grid", "low_resolution_risk": True})
            self.assertFalse(board["approved"])
            approved = approve_reference_board(root, "EP001", board["board_id"])
            self.assertTrue(approved["approved"])
            plan = prepare_keyframe_generation(root, "EP001", "01", "start")
            self.assertEqual(plan["status"], "planned")
            background_stage, board_stage = plan["stages"]
            background_dispatch = begin_stage_generation(root, "EP001", plan["plan_id"], background_stage["stage_id"])
            self.write_file(root, "provider/background.png", b"background")
            background_output = record_stage_generation(root, "EP001", plan["plan_id"], background_stage["stage_id"], {
                "plan_id": plan["plan_id"], "stage_id": background_stage["stage_id"], "dispatch_id": background_dispatch["dispatch_id"], "tool_request_id": "req-background", "prompt": background_dispatch["prompt"], "input_images": background_dispatch["input_images"], "output_path": "provider/background.png", "started_at": "2026-08-15T00:00:00Z", "completed_at": "2026-08-15T00:01:00Z",
            })
            record_stage_qa(root, "EP001", plan["plan_id"], background_stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T00:02:00Z", "checks": [{"category": "scene", "status": "pass", "confidence": 0.99, "evidence_paths": []}], "issues": [],
            })
            self.write_file(root, "provider/frame.png", b"frame")
            board_dispatch = begin_stage_generation(root, "EP001", plan["plan_id"], board_stage["stage_id"])
            record_stage_generation(root, "EP001", plan["plan_id"], board_stage["stage_id"], {
                "plan_id": plan["plan_id"], "stage_id": board_stage["stage_id"], "dispatch_id": board_dispatch["dispatch_id"], "tool_request_id": "req-board", "prompt": board_dispatch["prompt"], "input_images": board_dispatch["input_images"], "output_path": "provider/frame.png", "started_at": "2026-08-15T00:03:00Z", "completed_at": "2026-08-15T00:04:00Z",
            })
            record_stage_qa(root, "EP001", plan["plan_id"], board_stage["stage_id"], {
                "status": "pass", "reviewer_type": "automated", "checked_at": "2026-08-15T00:05:00Z", "checks": [{"category": "character", "status": "pass", "confidence": 0.99, "evidence_paths": []}], "issues": [],
            })
            with self.assertRaisesRegex(ValueError, "不允许准备"):
                prepare_keyframe_generation(root, "EP001", "01", "start")

    def test_legacy_execution_manifest_is_marked_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(root, "EP001", "旧版", "测试", [])
            episode = root / "episodes/EP001_旧版"
            (episode / "keyframe-execution-manifest.json").write_text(json.dumps({"episode_id": "EP001", "status": "ready", "shots": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy_unplanned"):
                prepare_keyframe_generation(root, "EP001", "01", "start")
            marked = json.loads((episode / "keyframe-execution-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(marked["status"], "legacy_unplanned")

    def test_handoff_explicitly_overrides_storyboard_generator_short_form_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            initialize_project(project, "测试项目", None, audience="成年观众", frame_format="21:9", episode_target_seconds=75, content_guidelines="克制悬疑")
            write_asset_index(project, [{"asset_id": "C01", "name": "主角", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_lead/front.png"}])
            package = create_episode(project, "EP001", "测试集", "测试剧情", ["主角"]).read_text(encoding="utf-8")

        self.assertIn("21:9", package)
        self.assertIn("75 秒", package)
        self.assertIn("最高优先级", package)
        self.assertIn("导演版逐镜说明", package)
        self.assertIn("开头固定为“《剧名》<本集目标时长>秒导演版分镜", package)
        self.assertIn("整体时长：…、画面规格：…、固定场景：…、本集主题：…", package)
        self.assertIn("5 秒或 10 秒", package)
        self.assertIn("10 秒镜头默认首帧与尾帧", package)
        self.assertIn("validate_director_storyboard.py", package)
        self.assertNotIn("分镜表逐镜必须", package)
        self.assertNotIn("fixed-settings-source.txt", package)

    def test_storyboard_integration_protocol_uses_director_board_instead_of_legacy_table_template(self) -> None:
        protocol = (
            Path(__file__).parents[1]
            / "short-drama-butler"
            / "references"
            / "seedance-integration-protocol.md"
        ).read_text(encoding="utf-8")

        self.assertIn("导演版逐镜说明", protocol)
        self.assertIn("整体时长：<本集目标时长>", protocol)
        self.assertIn("画面规格：<画幅、风格与画面限制>", protocol)
        self.assertIn("固定场景：<固定场景与空间关系>", protocol)
        self.assertIn("本集主题：<主题>", protocol)
        self.assertIn("首帧 A 画面", protocol)
        self.assertIn("10 秒默认 2 张", protocol)
        for heading in ("首帧 A 画面", "尾帧 B 画面", "运镜", "台词与口型时间段", "非说话嘴型控制"):
            self.assertIn(heading, protocol)
        self.assertNotIn("分镜表逐镜必须", protocol)

        butler_skill = (
            Path(__file__).parents[1]
            / "short-drama-butler"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("validate_director_storyboard.py", butler_skill)

    def test_docx_extractor_preserves_chinese_paragraphs_without_external_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = Path(temp_dir) / "设定.docx"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>奇妙岛</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>泡泡湾</w:t></w:r></w:p></w:body></w:document>'
            )
            with zipfile.ZipFile(document, "w") as archive:
                archive.writestr("word/document.xml", xml)

            self.assertEqual(extract_text(document), "奇妙岛\n泡泡湾\n")

    def test_initializer_and_handoff_accept_non_children_project_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_document = root / "设定.docx"
            with zipfile.ZipFile(source_document, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>都市设定</w:t></w:r></w:p></w:body></w:document>',
                )
            initialize_project(
                root,
                "都市悬疑短剧",
                source_document,
                audience="成年观众",
                frame_format="9:16",
                episode_target_seconds=60,
                content_guidelines="悬疑克制、无血腥画面",
            )
            write_asset_index(root, [{"asset_id": "C01", "name": "主角", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_lead/front.png"}])
            package = create_episode(root, "EP001", "雨夜来信", "一封匿名信打破平静。", ["C01"])

            contents = package.read_text(encoding="utf-8")
            self.assertIn("受众：成年观众", contents)
            self.assertIn("画幅：9:16", contents)
            self.assertIn("目标时长：60 秒", contents)
            self.assertIn("悬疑克制、无血腥画面", contents)

    def test_episode_duration_override_changes_only_that_episode_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, episode_target_seconds=120)
            write_asset_index(
                root,
                [{"asset_id": "C01", "name": "主角", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_lead/front.png"}],
            )
            package = create_episode(
                root,
                "EP001",
                "特别篇",
                "一段更完整的故事。",
                ["主角"],
                episode_overrides={"episode_target_seconds": 180},
            )

            self.assertIn("目标时长：180 秒", package.read_text(encoding="utf-8"))
            self.assertIn('episode_target_seconds: "120"', (root / "project-settings/project.yaml").read_text(encoding="utf-8"))
            self.assertIn('episode_target_seconds: "180"', (package.parent / "episode-overrides.yaml").read_text(encoding="utf-8"))

    def test_confirmed_episode_continuity_is_automatically_handed_to_the_next_episode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            write_asset_index(root, [])
            first_package = create_episode(root, "EP001", "雨夜来信", "许岚收到录音。", [])
            continuity_path = first_package.parent / "episode-continuity.md"
            self.assertIn("状态：待确认", continuity_path.read_text(encoding="utf-8"))

            record_episode_continuity(
                root,
                "EP001",
                events=["许岚收到一段匿名录音。"],
                character_states=["许岚决定追查录音来源。"],
                ending_frame="雨夜的旧书店门口，许岚握着录音笔望向远处。",
                unresolved_threads=["录音是谁留下的？"],
                next_episode_constraints=["第 2 集从旧书店门口继续。"],
            )
            second_package = create_episode(root, "EP002", "追查", "许岚开始调查录音。", [])
            package_contents = second_package.read_text(encoding="utf-8")

            self.assertIn("状态：已确认", continuity_path.read_text(encoding="utf-8"))
            self.assertIn("## 上集承接", package_contents)
            self.assertIn("许岚收到一段匿名录音", package_contents)
            self.assertIn("第 2 集从旧书店门口继续", package_contents)

    def test_pending_immediately_previous_episode_is_not_skipped_for_an_older_continuity_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            write_asset_index(root, [])
            create_episode(root, "EP001", "开端", "第一集剧情。", [])
            record_episode_continuity(
                root,
                "EP001",
                events=["第一集已经发生的事件。"],
                character_states=[],
                ending_frame="第一集最后一帧。",
                unresolved_threads=[],
                next_episode_constraints=[],
            )
            create_episode(root, "EP002", "未定稿", "第二集还在修改。", [])

            with self.assertRaisesRegex(ValueError, "EP002"):
                create_episode(root, "EP003", "下一集", "第三集需求。", [])

            third_package = create_episode(
                root,
                "EP003",
                "独立下一集",
                "这是一集独立故事。",
                [],
                standalone=True,
            ).read_text(encoding="utf-8")
            self.assertNotIn("第一集已经发生的事件", third_package)
            self.assertNotIn("## 上集承接", third_package)

    def test_episode_creation_resolves_asset_names_without_requiring_internal_ids(self) -> None:
        assets = [
            {"asset_id": "C01", "name": "咕噜", "aliases": ["小怪兽"], "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_gulu/front.png"},
            {"asset_id": "C02", "name": "咕噜妈妈", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C02_gulu-mom/front.png"},
        ]
        self.assertEqual(resolve_asset_references(assets, ["咕噜", "咕噜妈妈"]), ["C01", "C02"])
        self.assertEqual(resolve_asset_references(assets, ["小怪兽", "C02"]), ["C01", "C02"])
        ambiguous = assets + [{"asset_id": "C03", "name": "妈妈", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C03_mom/front.png"}, {"asset_id": "C04", "name": "妈妈", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C04_mom/front.png"}]
        with self.assertRaisesRegex(ValueError, "素材名称不唯一"):
            resolve_asset_references(ambiguous, ["妈妈"])

    def test_initializer_supports_a_new_project_without_a_legacy_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "全新短剧项目", None)

            config = (root / "project-settings/project.yaml").read_text(encoding="utf-8")
            self.assertIn('audience: ""', config)
            self.assertIn('format: ""', config)
            self.assertTrue((root / "project-settings/character-bible.md").is_file())
            self.assertFalse((root / "project-settings/source-document.json").exists())

    def test_reinitializing_an_existing_project_refuses_to_overwrite_its_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, frame_format="16:9")
            register_project_asset(
                root,
                "许岚",
                "characters",
                "global",
                "assets/global/characters/C01_xulan/reference.png",
            )
            create_episode(root, "EP001", "开端", "第一集。", ["许岚"])

            with self.assertRaisesRegex(FileExistsError, "已初始化"):
                initialize_project(root, "错误的新名字", None)

            config = (root / "project-settings/project.yaml").read_text(encoding="utf-8")
            assets = json.loads((root / "project-settings/asset-index.json").read_text(encoding="utf-8"))["assets"]
            self.assertIn('project_name: "测试项目"', config)
            self.assertEqual(assets[0]["name"], "许岚")
            self.assertTrue((root / "episodes/EP001_开端/episode-continuity.md").is_file())

    def test_new_asset_references_become_episode_drafts_and_can_be_registered_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "全新短剧项目", None)
            assets = [{"asset_id": "C01", "name": "主角", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_lead/front.png"}]
            write_asset_index(root, assets)
            package = create_episode(root, "EP001", "新朋友", "主角认识新朋友。", ["主角", "小兔子"])
            contents = package.read_text(encoding="utf-8")
            self.assertIn("小兔子", contents)
            self.assertIn("本集新增资产", contents)

            registered = register_asset(assets, "小兔子", "characters", "episode-EP001", "assets/episodes/episode-EP001/characters/C02_rabbit/front.webp", aliases=["兔兔"])
            self.assertEqual(registered["asset_id"], "C02")
            self.assertEqual(resolve_asset_references(assets, ["兔兔"]), ["C02"])

    def test_project_configuration_is_escaped_and_controls_handoff_without_hardcoded_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(
                root,
                '项目："夜班"',
                None,
                audience="成人：悬疑爱好者",
                frame_format="2.39:1",
                episode_target_seconds=90,
                content_guidelines="不展示血腥：保持克制",
            )
            config_path = root / "project-settings/project.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                + 'video_workflow: "关键帧图 → 任意图生视频工具 → 人工剪辑"\n'
                + 'storyboard_skill: "custom-storyboard"\n',
                encoding="utf-8",
            )
            write_asset_index(root, [])
            package = create_episode(root, "EP001", "测试", "测试剧情", []).read_text(encoding="utf-8")

            self.assertIn("成人：悬疑爱好者", package)
            self.assertIn("关键帧图 → 任意图生视频工具 → 人工剪辑", package)
            self.assertIn("$custom-storyboard", package)

    def test_storyboard_dependency_detector_installs_exact_skill_directory_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "skills"
            archive_path = Path(temp_dir) / "upstream.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "Seedance2-Storyboard-Generator-main/.claude/skills/seedance-storyboard-generator/SKILL.md",
                    "---\nname: seedance-storyboard-generator\ndescription: test\n---\n",
                )
                archive.writestr(
                    "Seedance2-Storyboard-Generator-main/.claude/skills/seedance-storyboard-generator/references/manual.md",
                    "reference",
                )

            self.assertIsNone(find_installed_skill([root]))
            with zipfile.ZipFile(archive_path) as archive:
                installed = extract_skill_from_archive(archive, root)
            self.assertEqual(installed, root / "seedance-storyboard-generator")
            self.assertEqual(find_installed_skill([root]), installed)
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaisesRegex(DependencyError, "已存在"):
                    extract_skill_from_archive(archive, root)

    def test_storyboard_dependency_is_pinned_to_a_revision_and_archive_hash(self) -> None:
        self.assertIn(UPSTREAM_REVISION, UPSTREAM_ARCHIVE_URL)
        self.assertNotIn("refs/heads/main", UPSTREAM_ARCHIVE_URL)
        self.assertEqual(len(UPSTREAM_ARCHIVE_SHA256), 64)

    def test_readme_and_project_file_reference_explain_all_beginner_creation_modes(self) -> None:
        repository_root = Path(__file__).parents[1]
        readme = (repository_root / "README.md").read_text(encoding="utf-8")
        project_files = (
            repository_root / "short-drama-butler/references/project-files.md"
        ).read_text(encoding="utf-8")
        todo = (repository_root / "TODO.md").read_text(encoding="utf-8")

        for heading in (
            "## 先选一种使用方式",
            "从零开始做一个新系列",
            "已有项目、旧文档或图片",
            "今天只做一集独立短剧",
            "继续做连续剧的下一集",
            "大纲里出现新角色或新场景",
            "## 剧本与分镜确认后：再规划关键帧",
            "## 每个文件是做什么的",
        ):
            self.assertIn(heading, readme)
        self.assertNotIn("读取当前项目配置，创建剧情需求、本集状态、素材清单和 Storyboard 交接包", readme)
        self.assertIn("keyframe-execution.md", readme)
        for filename in (
            "story-brief.md",
            "episode-assets.md",
            "asset-production-plan.md",
            "asset-production-manifest.json",
            "creative-review.md",
            "keyframe-plan.md",
            "keyframe-manifest.json",
            "keyframe-execution.md",
            "keyframe-execution-manifest.json",
            "storyboard-package.md",
        ):
            self.assertIn(filename, project_files)
        self.assertIn("# 短剧管家待办", todo)
        self.assertIn("关键帧与图生视频", todo)

    def test_asset_production_plan_is_created_after_outline_for_episode_only_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None, frame_format="16:9 横屏")
            create_episode(root, "EP001", "雨夜来信", "许岚在旧书店收到录音。", ["神秘访客", "旧书店"])

            plan_path = create_asset_production_plan(
                root,
                "EP001",
                [
                    {"name": "神秘访客", "kind": "characters", "visual_brief": "成年访客，深色风衣，神情克制"},
                    {"name": "旧书店", "kind": "scenes", "visual_brief": "雨夜街角的旧书店，暖黄橱窗"},
                ],
            )
            plan = plan_path.read_text(encoding="utf-8")
            manifest = json.loads((plan_path.parent / "asset-production-manifest.json").read_text(encoding="utf-8"))

            self.assertIn("大纲确认后、正式剧本与分镜前", plan)
            self.assertIn("16:9 横屏", plan)
            self.assertIn("神秘访客", plan)
            self.assertIn("旧书店", plan)
            self.assertEqual(manifest["assets"][0]["scope"], "episode-EP001")
            self.assertEqual(manifest["assets"][1]["status"], "planned")

    def test_adding_to_an_asset_production_plan_preserves_existing_asset_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(root, "EP001", "海滩", "小螃蟹回海。", ["小螃蟹", "海滩"])
            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "小螃蟹", "kind": "characters", "visual_brief": "圆润小螃蟹"}],
            )
            image = self.write_file(root, "assets/pending/crab.png", b"crab")
            provide_episode_asset_image(root, "EP001", "小螃蟹", image)
            confirm_episode_asset(root, "EP001", "小螃蟹")

            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "泡泡湾海滩", "kind": "scenes", "visual_brief": "浅海与湿沙的海滩"}],
            )
            manifest = json.loads((root / "episodes/EP001_海滩/asset-production-manifest.json").read_text(encoding="utf-8"))
            by_name = {asset["name"]: asset for asset in manifest["assets"]}

            self.assertEqual(by_name["小螃蟹"]["status"], "registered")
            self.assertEqual(by_name["泡泡湾海滩"]["status"], "planned")

    def test_confirming_an_episode_asset_updates_manifest_assets_and_storyboard_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            package = create_episode(root, "EP001", "新朋友", "许岚遇见神秘访客。", ["神秘访客"])
            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "神秘访客", "kind": "characters", "visual_brief": "深色风衣，表情克制"}],
            )
            image = self.write_file(root, "assets/pending/visitor.png", b"visitor-image")

            provide_episode_asset_image(root, "EP001", "神秘访客", image)
            asset = confirm_episode_asset(root, "EP001", "神秘访客")

            manifest = json.loads((package.parent / "asset-production-manifest.json").read_text(encoding="utf-8"))
            package_contents = package.read_text(encoding="utf-8")
            episode_assets = (package.parent / "episode-assets.md").read_text(encoding="utf-8")
            self.assertEqual(manifest["assets"][0]["status"], "registered")
            self.assertEqual(manifest["assets"][0]["asset_id"], asset["asset_id"])
            self.assertFalse(image.exists())
            self.assertTrue((root / asset["destination"]).is_file())
            self.assertEqual((root / asset["destination"]).read_bytes(), b"visitor-image")
            self.assertIn("神秘访客", package_contents)
            self.assertIn(asset["asset_id"], package_contents)
            self.assertNotIn("神秘访客（默认本集专属）", package_contents)
            self.assertIn("神秘访客", episode_assets)

    def test_confirming_a_character_three_view_set_archives_all_views_under_one_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(root, "测试项目", None)
            create_episode(root, "EP001", "新朋友", "许岚遇见小螃蟹。", ["小螃蟹"])
            create_asset_production_plan(
                root,
                "EP001",
                [{"name": "小螃蟹", "kind": "characters", "visual_brief": "圆润的小螃蟹"}],
            )
            images = {
                "front": self.write_file(root, "assets/pending/crab-front.png", b"front"),
                "side": self.write_file(root, "assets/pending/crab-side.png", b"side"),
                "back": self.write_file(root, "assets/pending/crab-back.png", b"back"),
            }

            provide_episode_asset_images(root, "EP001", "小螃蟹", images)
            asset = confirm_episode_asset(root, "EP001", "小螃蟹")

            self.assertEqual(asset["destination"], asset["views"][0]["path"])
            self.assertEqual([view["variant"] for view in asset["views"]], ["front", "side", "back"])
            self.assertEqual([(root / view["path"]).read_bytes() for view in asset["views"]], [b"front", b"side", b"back"])
            self.assertTrue(all(not image.exists() for image in images.values()))

    def test_initialize_and_register_project_asset_persist_full_configuration_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initialize_project(
                root,
                "测试项目",
                None,
                shot_count="每个情绪节拍至少一个镜头",
                visual_canon_precedence="confirmed_images",
                video_workflow="图片 → 视频工具 → 剪辑",
                storyboard_skill="custom-storyboard",
            )
            registered = register_project_asset(
                root,
                "林夏",
                "characters",
                "global",
                "assets/global/characters/C01_linxia/front.png",
                aliases=["夏夏"],
            )
            stored = json.loads((root / "project-settings/asset-index.json").read_text(encoding="utf-8"))["assets"]
            package = create_episode(root, "EP001", "测试", "测试剧情", ["夏夏"]).read_text(encoding="utf-8")

            self.assertEqual(registered["asset_id"], "C01")
            self.assertEqual(stored[0]["name"], "林夏")
            self.assertIn("每个情绪节拍至少一个镜头", package)
            self.assertIn("图片 → 视频工具 → 剪辑", package)
            self.assertIn("$custom-storyboard", package)


if __name__ == "__main__":
    unittest.main()
