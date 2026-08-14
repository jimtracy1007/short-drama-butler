# Director Storyboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make director-style 5/10-second storyboards and conservative keyframe defaults the shared, testable contract of short-drama-butler and seedance-storyboard-generator.

**Architecture:** Keep storytelling judgment in the Skill instructions and enforce deterministic timing/frame safeguards in `project_files.py`. The episode handoff carries the contract across Skills; the keyframe manifest records a user-reviewable exception reason for an optional middle frame.

**Tech Stack:** Python 3 standard library, `unittest`, Markdown, YAML frontmatter.

## Global Constraints

- Default director-board durations are 5 seconds or 10 seconds; only a final 1–4-second remainder is allowed.
- 5 seconds and remainders use `start_only`; 10 seconds uses `start_end`.
- `start_middle_end` needs a non-empty, user-visible `exception_reason`; it remains three frames only when `approve_keyframe_plan(..., approved_middle_shot_ids=[...])` explicitly includes that shot, otherwise it becomes two frames.
- No third-party dependencies, video APIs, automatic video generation, or image uploads.
- Director-board prose is the default `storyboard.md`; Markdown tables cannot replace it.

---

### Task 1: Lock the timing and third-frame contract in tests and code

**Files:**
- Modify: `tests/test_asset_migration.py`
- Modify: `.agents/skills/short-drama-butler/scripts/project_files.py:17-22,494-574`

**Interfaces:**
- Produces: `recommend_keyframe_strategy(duration_seconds: float) -> str`.
- Produces: `_validate_keyframe_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]`, with required `exception_reason` on three-frame entries.
- Consumes: existing `create_keyframe_plan(project_root, episode_id, shots)` and existing approval gates.

- [ ] **Step 1: Write the failing test**

```python
def test_keyframe_timing_defaults_and_middle_frame_exception_are_reviewable(self) -> None:
    self.assertEqual(recommend_keyframe_strategy(5), "start_only")
    self.assertEqual(recommend_keyframe_strategy(10), "start_end")
    self.assertEqual(recommend_keyframe_strategy(3), "start_only")
    with self.assertRaisesRegex(ValueError, "特殊原因"):
        create_keyframe_plan(root, "EP001", [{
            "shot_id": "02", "duration_seconds": 10, "action": "魔法变形",
            "strategy": "start_middle_end",
        }])
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_keyframe_timing_defaults_and_middle_frame_exception_are_reviewable -v`

Expected: FAIL because the strategy helper does not exist and a three-frame plan accepts no rationale.

- [ ] **Step 3: Write minimal implementation**

```python
def recommend_keyframe_strategy(duration_seconds: float) -> str:
    if duration_seconds <= 5:
        return "start_only"
    if duration_seconds == 10:
        return "start_end"
    raise ValueError("默认导演版分镜只使用 5 秒、10 秒或最后不足 5 秒的余数")
```

Validate supplied strategies against that default. For `start_middle_end`, require a 10-second duration and non-empty `exception_reason`. Persist the reason in `keyframe-manifest.json`, render it in `keyframe-plan.md` as “待逐镜确认”, and downgrade it to two frames unless the approval call explicitly includes its shot ID.

- [ ] **Step 4: Run focused tests and commit**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_keyframe_timing_defaults_and_middle_frame_exception_are_reviewable tests.test_asset_migration.AssetMigrationTests.test_keyframe_plan_requires_two_user_approval_gates_and_keeps_per_shot_frame_counts -v`

Expected: PASS; existing coverage is updated to 5 seconds, 10 seconds and an explicit exception.

```bash
git add tests/test_asset_migration.py .agents/skills/short-drama-butler/scripts/project_files.py
git commit -m "Enforce director storyboard keyframe defaults"
```

### Task 2: Make the short-drama-butler handoff prescribe the director board

**Files:**
- Modify: `.agents/skills/short-drama-butler/SKILL.md:50-85`
- Modify: `.agents/skills/short-drama-butler/scripts/project_files.py:1060-1124`
- Modify: `.agents/skills/short-drama-butler/references/seedance-integration-protocol.md`
- Modify: `.agents/skills/short-drama-butler/references/storyboard-handoff.md`
- Modify: `.agents/skills/short-drama-butler/references/storyboard-to-keyframes.md`
- Modify: `.agents/skills/short-drama-butler/references/project-files.md`

**Interfaces:**
- Consumes: project target duration and optional episode override in `create_episode`.
- Produces: a `storyboard-package.md` requiring director-board prose and the 5/10 rule.

- [ ] **Step 1: Write failing handoff assertions**

```python
package = create_episode(root, "EP001", "测试集", "测试剧情", []).read_text(encoding="utf-8")
self.assertIn("导演版逐镜说明", package)
self.assertIn("5 秒或 10 秒", package)
self.assertIn("10 秒镜头默认首帧与尾帧", package)
self.assertNotIn("分镜表逐镜必须", package)
```

- [ ] **Step 2: Run it and verify it fails**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_handoff_explicitly_overrides_storyboard_generator_short_form_defaults -v`

Expected: FAIL after adding assertions because the current handoff requires a “分镜表”.

- [ ] **Step 3: Update package and references**

Replace table-oriented wording with one director-board contract: title and global visual rules, then per-shot prose; 5 seconds/10 seconds/final remainder; 5-second keyframe, 10-second two-frame default; a third frame requires a stated rationale and the existing user confirmation gate. Keep continuity, dialogue, sound, transition, asset-reference and image-prompt fields.

- [ ] **Step 4: Run focused regression and commit**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_handoff_explicitly_overrides_storyboard_generator_short_form_defaults tests.test_asset_migration.AssetMigrationTests.test_keyframe_execution_pack_preserves_storyboard_fields_and_adds_frame_files -v`

Expected: PASS.

```bash
git add .agents/skills/short-drama-butler
git commit -m "Specify director storyboard handoff format"
```

### Task 3: Replace Storyboard Generator’s legacy table recipe and update guidance

**Files:**
- Modify: `.agents/skills/seedance-storyboard-generator/SKILL.md:10-18,406-429`
- Modify: `.agents/skills/seedance-storyboard-generator/references/seedance-manual.md:607-628`
- Modify: `README.md`

**Interfaces:**
- Consumes: a short-drama-butler `storyboard-package.md` or a standalone storytelling request.
- Produces: director-style `storyboard.md`; standalone use cannot default to the legacy 2–5-second table recipe.

- [ ] **Step 1: Add the failing documentation regression test**

```python
generator = (Path(__file__).parents[1] / ".agents/skills/seedance-storyboard-generator/SKILL.md").read_text(encoding="utf-8")
self.assertIn("导演版逐镜说明", generator)
self.assertIn("首帧 A 画面", generator)
self.assertNotIn("只输出一张 Markdown 表格", generator)
```

- [ ] **Step 2: Run it and verify it fails**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_generator_uses_director_board_instead_of_legacy_table_template -v`

Expected: FAIL because the existing template explicitly asks for one Markdown table.

- [ ] **Step 3: Replace templates**

In both generator documents, replace the table-only and 2–5-second/13–15-second rules with the director-board recipe. Include 5-second, 10-second and confirmed three-frame shapes; lip-sync time ranges; non-speaking mouth control; transitions; and the rule that no table replaces the director-board prose. In README, add a compact “默认分镜节奏” explanation before keyframe planning.

- [ ] **Step 4: Run test and commit**

Run: `python3 -m unittest tests.test_asset_migration.AssetMigrationTests.test_generator_uses_director_board_instead_of_legacy_table_template -v`

Expected: PASS.

```bash
git add .agents/skills/seedance-storyboard-generator README.md tests/test_asset_migration.py
git commit -m "Use director-style storyboard output by default"
```

### Task 4: Validate Skills and end-to-end regressions

**Files:**
- Verify: both `SKILL.md` files, `.agents/skills/short-drama-butler/agents/openai.yaml`, and `tests/test_asset_migration.py`.

- [ ] **Step 1: Run the complete unit suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS with all filesystem work confined to temporary directories.

- [ ] **Step 2: Validate both Skill folders**

```bash
python3 /Users/jim/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/short-drama-butler
python3 /Users/jim/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/seedance-storyboard-generator
```

Expected: both report `Skill is valid!`.

- [ ] **Step 3: Check for stale defaults and unsafe staging**

```bash
rg -n "只输出一张 Markdown 表格|每个分镜时长控制在2-5秒|合计13-15秒" .agents/skills README.md
git status --short
git diff --check HEAD
```

Expected: no legacy default recipe matches; only intended Markdown, Python, test and plan files are staged; whitespace is clean.
