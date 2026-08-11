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
from project_files import build_asset_index, create_episode, initialize_project, write_asset_index  # noqa: E402
from extract_docx_text import extract_text  # noqa: E402


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
            source_document = self.write_file(root, "旧资料.docx", b"docx")

            initialize_project(root, "奇妙岛怪事", source_document)
            write_asset_index(root, [{"asset_id": "C01", "name": "咕噜", "kind": "characters", "scope": "global", "destination": "assets/global/characters/C01_gulu/front.png"}])
            package = create_episode(root, "EP001", "分享的泡泡", "咕噜学习分享玩具", ["C01"])

            self.assertFalse(source_document.exists())
            self.assertTrue((root / "source-material/固定设定.docx").is_file())
            self.assertIn("16:9", (root / "project-settings/project.yaml").read_text(encoding="utf-8"))
            contents = package.read_text(encoding="utf-8")
            self.assertIn("120 秒", contents)
            self.assertIn("镜头数量由剧情节奏决定", contents)
            self.assertIn("C01｜咕噜", contents)

    def test_asset_index_groups_multiple_views_under_one_asset_id(self) -> None:
        index = build_asset_index(
            [
                {"asset_id": "C01", "name": "咕噜", "kind": "characters", "scope": "global", "variant": "front", "destination": "assets/global/characters/C01_gulu/front.png"},
                {"asset_id": "C01", "name": "咕噜", "kind": "characters", "scope": "global", "variant": "back", "destination": "assets/global/characters/C01_gulu/back.png"},
            ]
        )
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["destination"], "assets/global/characters/C01_gulu/front.png")
        self.assertEqual([view["variant"] for view in index[0]["views"]], ["front", "back"])

    def test_handoff_explicitly_overrides_storyboard_generator_short_form_defaults(self) -> None:
        root = Path(__file__).parents[1]
        storyboard_skill = (root / ".agents/skills/seedance-storyboard-generator/SKILL.md").read_text(encoding="utf-8")
        package = (root / "episodes/EP001_分享的泡泡/storyboard-package.md").read_text(encoding="utf-8")

        self.assertIn("每集15秒", storyboard_skill)
        self.assertIn("9:16", storyboard_skill)
        self.assertIn("16:9 横屏", package)
        self.assertIn("120 秒", package)
        self.assertIn("不要沿用其默认 15 秒、9:16 或固定镜头数设定", package)
        self.assertIn("project-settings/fixed-settings-source.txt", package)

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


if __name__ == "__main__":
    unittest.main()
