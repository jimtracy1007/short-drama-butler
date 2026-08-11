from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / ".agents" / "skills" / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from asset_migration import (  # noqa: E402
    AssetMigrationError,
    build_plan,
    execute_plan,
    rollback,
)
from project_files import (  # noqa: E402
    build_asset_index,
    confirm_episode_asset,
    create_asset_production_plan,
    create_episode,
    initialize_project,
    register_asset,
    register_project_asset,
    record_episode_continuity,
    provide_episode_asset_image,
    provide_episode_asset_images,
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

    def test_handoff_explicitly_overrides_storyboard_generator_short_form_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            initialize_project(project, "测试项目", None, audience="成年观众", frame_format="21:9", episode_target_seconds=75, content_guidelines="克制悬疑")
            write_asset_index(project, [{"asset_id": "C01", "name": "主角", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_lead/front.png"}])
            package = create_episode(project, "EP001", "测试集", "测试剧情", ["主角"]).read_text(encoding="utf-8")

        self.assertIn("21:9", package)
        self.assertIn("75 秒", package)
        self.assertIn("最高优先级", package)
        self.assertNotIn("fixed-settings-source.txt", package)

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
            repository_root / ".agents/skills/short-drama-butler/references/project-files.md"
        ).read_text(encoding="utf-8")

        for heading in (
            "## 先选一种使用方式",
            "从零开始做一个新系列",
            "已有项目、旧文档或图片",
            "今天只做一集独立短剧",
            "继续做连续剧的下一集",
            "大纲里出现新角色或新场景",
            "## 每个文件是做什么的",
        ):
            self.assertIn(heading, readme)
        self.assertNotIn("读取当前项目配置，创建剧情需求、本集状态、素材清单和 Storyboard 交接包", readme)
        for filename in (
            "story-brief.md",
            "episode-assets.md",
            "asset-production-plan.md",
            "asset-production-manifest.json",
            "storyboard-package.md",
        ):
            self.assertIn(filename, project_files)

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
