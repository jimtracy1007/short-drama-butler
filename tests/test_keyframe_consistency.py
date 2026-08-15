from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_SCRIPTS = Path(__file__).parents[1] / "short-drama-butler" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from keyframe_consistency import (  # noqa: E402
    KeyframeConsistencyError,
    build_generation_plan,
    resolve_applicable_overrides,
    resolve_keyframe_asset_uses,
    select_applicable_overrides,
    validate_continuity_contract,
)


class KeyframeConsistencyTests(unittest.TestCase):
    def write_file(self, root: Path, relative: str, contents: bytes) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return relative

    def write_index(self, root: Path, assets: list[dict]) -> None:
        index = root / "project-settings" / "asset-index.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps({"version": 1, "assets": assets}, ensure_ascii=False), encoding="utf-8")

    def asset(self, asset_id: str, name: str, kind: str, views: list[tuple[str, str]], aliases: list[str] | None = None) -> dict:
        return {
            "asset_id": asset_id,
            "name": name,
            "kind": kind,
            "scope": "global",
            "aliases": aliases or [],
            "views": [{"variant": variant, "path": path} for variant, path in views],
        }

    def required(self, asset_id: str, role: str = "character_identity", **extra: object) -> dict:
        item = {"asset_id": asset_id, "name": asset_id, "role": role, "required": True, "path": f"assets/{asset_id}.png", "sha256": asset_id}
        item.update(extra)
        return item

    def test_character_view_falls_back_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            front = self.write_file(root, "assets/C01-front.png", b"front")
            self.write_index(root, [self.asset("C01", "咕噜", "characters", [("front", front)], ["小怪兽"])])

            resolved = resolve_keyframe_asset_uses(root, [{"reference": "小怪兽", "role": "character_identity", "required": True, "view_hint": "side"}])

            self.assertEqual(resolved[0]["asset_id"], "C01")
            self.assertEqual(resolved[0]["selected_view"], "front")
            self.assertIn("side", resolved[0]["fallback_reason"])
            self.assertEqual(resolved[0]["sha256"], hashlib.sha256(b"front").hexdigest())

    def test_ambiguous_reference_and_missing_image_fail_before_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = self.write_file(root, "assets/a.png", b"a")
            self.write_index(
                root,
                [
                    self.asset("C01", "甲", "characters", [("front", image)], ["主角"]),
                    self.asset("C02", "乙", "characters", [("front", image)], ["主角"]),
                ],
            )
            with self.assertRaisesRegex(KeyframeConsistencyError, "歧义"):
                resolve_keyframe_asset_uses(root, [{"reference": "主角", "role": "character_identity", "required": True}])

            self.write_index(root, [self.asset("C01", "甲", "characters", [("front", "assets/missing.png")])])
            with self.assertRaisesRegex(KeyframeConsistencyError, "找不到素材"):
                resolve_keyframe_asset_uses(root, [{"reference": "甲", "role": "character_identity", "required": True}])

    def test_path_escape_and_empty_views_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_index(root, [self.asset("C01", "甲", "characters", [("front", "../outside.png")])])
            with self.assertRaisesRegex(KeyframeConsistencyError, "项目内相对路径"):
                resolve_keyframe_asset_uses(root, [{"reference": "甲", "role": "character_identity"}])

            self.write_index(root, [self.asset("C01", "甲", "characters", [])])
            with self.assertRaisesRegex(KeyframeConsistencyError, "没有可用视图"):
                resolve_keyframe_asset_uses(root, [{"reference": "甲", "role": "character_identity"}])

    def test_override_scope_and_recency_choose_one_winner_and_trace_losers(self) -> None:
        overrides = [
            {"override_id": "UO-episode", "path": "references/a.png", "sha256": "a", "role": "background", "target_asset_id": None, "scope": "episode", "scope_ids": [], "created_at": "2026-08-01T00:00:00Z"},
            {"override_id": "UO-shot-old", "path": "references/b.png", "sha256": "b", "role": "background", "target_asset_id": None, "scope": "shot", "scope_ids": ["09"], "created_at": "2026-08-02T00:00:00Z"},
            {"override_id": "UO-shot-new", "path": "references/c.png", "sha256": "c", "role": "background", "target_asset_id": None, "scope": "shot", "scope_ids": ["09"], "created_at": "2026-08-03T00:00:00Z"},
        ]
        selected = select_applicable_overrides(overrides, "09")
        self.assertEqual([item["override_id"] for item in selected["effective"]], ["UO-shot-new"])
        self.assertEqual({item["superseded_by"] for item in selected["superseded"]}, {"UO-shot-new"})

    def test_identity_override_requires_target_and_hash_checked_when_resolved(self) -> None:
        with self.assertRaisesRegex(KeyframeConsistencyError, "target_asset_id"):
            select_applicable_overrides(
                [{"override_id": "UO-1", "path": "u.png", "sha256": "x", "role": "character_identity", "scope": "shot", "scope_ids": ["01"]}],
                "01",
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_file(root, "references/u.png", b"user")
            override = {"override_id": "UO-1", "path": "references/u.png", "sha256": hashlib.sha256(b"wrong").hexdigest(), "role": "background", "scope": "shot", "scope_ids": ["01"]}
            with self.assertRaisesRegex(KeyframeConsistencyError, "哈希不匹配"):
                resolve_applicable_overrides(root, [override], "01")
        with self.assertRaisesRegex(KeyframeConsistencyError, "不适用于镜头素材"):
            select_applicable_overrides(
                [{"override_id": "UO-C99", "path": "u.png", "sha256": "x", "role": "character_identity", "target_asset_id": "C99", "scope": "shot", "scope_ids": ["01"]}],
                "01",
                {"C01"},
            )

    def test_dimension_override_replaces_only_the_matching_default_anchor(self) -> None:
        uses = [
            self.required("S01", "background"),
            self.required("C01", "character_identity"),
        ]
        override = {
            "override_id": "UO-background",
            "path": "references/beach.png",
            "sha256": "beach",
            "role": "background",
            "scope": "shot",
            "scope_ids": ["01"],
        }
        plan = build_generation_plan("P-background", {"continuity_contract": None}, uses, [override], None, [])
        inputs = [item for stage in plan["stages"] for item in stage["input_images"]]
        self.assertEqual([item.get("asset_id") for item in inputs if item["role"] == "background"], [None])
        self.assertEqual([item["asset_id"] for item in inputs if item["role"] == "character_identity"], ["C01"])

    def test_one_to_five_required_references_use_single_generate_stage(self) -> None:
        uses = [self.required(f"C{index:02d}") for index in range(1, 6)]
        plan = build_generation_plan("P-1", {"continuity_contract": None}, uses, [], None, [])
        self.assertEqual(plan["generation_mode"], "single_pass")
        self.assertEqual(len(plan["stages"]), 1)
        self.assertEqual(plan["stages"][0]["mode"], "generate")
        self.assertEqual(len(plan["stages"][0]["input_images"]), 5)

    def test_six_required_references_are_staged_without_loss(self) -> None:
        uses = [self.required(f"C{index:02d}") for index in range(1, 7)]
        plan = build_generation_plan("P-2", {"continuity_contract": None}, uses, [], None, [])
        self.assertEqual(plan["generation_mode"], "staged_edit")
        self.assertEqual([stage["mode"] for stage in plan["stages"]], ["generate", "edit"])
        self.assertTrue(all(len(stage["input_images"]) <= 5 for stage in plan["stages"]))
        planned = {item["asset_id"] for stage in plan["stages"] for item in stage["input_images"] if "asset_id" in item}
        self.assertEqual(planned, {item["asset_id"] for item in uses})

    def test_confirmed_anchor_occupies_the_only_edit_target_slot(self) -> None:
        frame_spec = {
            "continuity_contract": {
                "predecessor": {"shot_id": "09", "frame_kind": "start"},
                "inherit_dimensions": ["space", "character_identity"],
                "asset_ids": ["C01"],
            }
        }
        anchor = {"shot_id": "09", "frame_kind": "start", "revision": "r001", "path": "keyframes/final/KF09-start/r001.png", "sha256": "anchor", "status": "confirmed"}
        plan = build_generation_plan("P-3", frame_spec, [self.required(f"C{index:02d}") for index in range(1, 6)], [], anchor, [])
        self.assertEqual(plan["generation_mode"], "staged_edit")
        first = plan["stages"][0]["input_images"]
        self.assertEqual(first[0]["role"], "edit_target")
        self.assertEqual(len(first), 5)
        self.assertEqual(sum(item["role"] == "edit_target" for stage in plan["stages"] for item in stage["input_images"]), len(plan["stages"]))

    def test_missing_anchor_waits_and_contract_must_be_explicit(self) -> None:
        contract = {"continuity_contract": {"predecessor": {"shot_id": "01", "frame_kind": "start"}, "inherit_dimensions": ["space"], "asset_ids": ["S01"]}}
        waiting = build_generation_plan("P-4", contract, [self.required("S01", "background")], [], None, [])
        self.assertEqual(waiting["status"], "waiting_for_dependency")
        with self.assertRaisesRegex(KeyframeConsistencyError, "必须明确"):
            validate_continuity_contract({})

    def test_unsplittable_group_requires_a_matching_approved_reference_board(self) -> None:
        uses = [self.required(f"C{index:02d}", relationship_group="all-hold-hands") for index in range(1, 7)]
        required = build_generation_plan("P-5", {"continuity_contract": None}, uses, [], None, [])
        self.assertEqual(required["status"], "reference_board_required")
        board = {"plan_id": "P-5", "relationship_group": "all-hold-hands", "board_id": "RB-P-5-r001", "path": "references/boards/RB-P-5-r001.png", "sha256": "board", "member_asset_ids": [item["asset_id"] for item in uses], "approved": True}
        plan = build_generation_plan("P-5", {"continuity_contract": None}, uses, [], None, [board])
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["stages"][0]["input_images"][0]["role"], "reference_board")

    def test_identity_override_preserves_oversized_relationship_group(self) -> None:
        uses = [self.required(f"C{index:02d}", relationship_group="all-hold-hands") for index in range(1, 7)]
        override = {
            "override_id": "UO-C01",
            "path": "references/user-c01.png",
            "sha256": "user-c01",
            "role": "character_identity",
            "target_asset_id": "C01",
            "scope": "shot",
            "scope_ids": ["01"],
        }
        plan = build_generation_plan("P-override-group", {"continuity_contract": None}, uses, [override], None, [])
        self.assertEqual(plan["status"], "reference_board_required")
        self.assertEqual(plan["relationship_group"], "all-hold-hands")
        self.assertEqual(plan["asset_ids"], [f"C{index:02d}" for index in range(1, 7)])

    def test_required_inputs_are_phase_ordered_despite_caller_order(self) -> None:
        uses = [
            self.required("P02", "prop_identity", subject_tier="secondary"),
            self.required("C02", "character_identity", subject_tier="secondary"),
            self.required("C01", "character_identity", subject_tier="primary"),
            self.required("S01", "background"),
            self.required("P01", "prop_identity", subject_tier="primary"),
            self.required("S02", "lighting"),
        ]
        plan = build_generation_plan("P-phase-order", {"continuity_contract": None}, uses, [], None, [])
        flattened = [
            item["asset_id"]
            for stage in plan["stages"]
            for item in stage["input_images"]
            if item.get("role") != "edit_target"
        ]
        self.assertEqual(flattened, ["S01", "S02", "C01", "P01", "C02", "P02"])
        self.assertEqual([stage["kind"] for stage in plan["stages"]], ["background", "primary_subjects", "secondary_subjects"])
        self.assertEqual(
            [
                [item["asset_id"] for item in stage["input_images"] if item.get("role") != "edit_target"]
                for stage in plan["stages"]
            ],
            [["S01", "S02"], ["C01", "P01"], ["C02", "P02"]],
        )

        optional_secondary = self.required("P03", "prop_identity", subject_tier="secondary")
        optional_secondary["required"] = False
        required_subset = [uses[2], uses[3]]
        plan_with_optional = build_generation_plan("P-phase-optional", {"continuity_contract": None}, required_subset, [], None, [])
        self.assertEqual(plan_with_optional["stages"][0]["kind"], "background")
        self.assertEqual(plan_with_optional["stages"][1]["kind"], "primary_subjects")
        plan_with_optional = build_generation_plan("P-phase-optional", {"continuity_contract": None}, required_subset + [optional_secondary], [], None, [])
        self.assertEqual([item["asset_id"] for item in plan_with_optional["unselected_optional"]], ["P03"])


if __name__ == "__main__":
    unittest.main()
