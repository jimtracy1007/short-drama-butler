# Task 3 report — v2 keyframe documentation and regression closure

## Changed files

- `.agents/skills/short-drama-butler/SKILL.md`
  - Documents the schema-v2 execution workflow, structured asset inputs, user-image overrides, state/QA gates, versioned outputs, legacy behavior, and provider boundary.
- `.agents/skills/short-drama-butler/references/project-files.md`
  - Adds the v2 directory map, execution-manifest responsibilities, work/final revision paths, user-reference and reference-board locations, and the migration/QA rules.
- `.agents/skills/short-drama-butler/references/storyboard-to-keyframes.md`
  - Defines the v2 input, continuity, generation, QA, revision, and user-reference contracts for the storyboard-to-keyframe handoff.
- `README.md`
  - Replaces the obsolete new-`pending/` guidance with v2 work/final behavior and explains the user-facing image-reference workflow without introducing a provider promise.

## User-visible rules documented

- Users keep using names or aliases; v2 resolves them to a unique registered asset, selected view, project-relative path, and SHA-256. Ambiguity, missing required assets, missing images, and unavailable views stop planning.
- A v2 frame needs structured `asset_uses` and an explicit `continuity_contract`; a missing confirmed predecessor remains `waiting_for_dependency` and cannot enter image generation.
- User reference images require an explicit role and scope. Identity and prop references also require their target asset. Registered files are copied to `references/user/`, hash-checked, dimension-scoped, and never rewrite the asset index or character bible.
- A stage accepts at most five inputs. Required inputs are staged rather than silently dropped; oversized atomic relationships require a registered, user-approved reference board before replanning.
- Generation results are recorded only after exact approved-input and hash verification. Attempts are retained under `episodes/<集>/keyframes/work/KF<镜号>-<帧类型>/rNNN-<阶段>.<扩展名>`; only final-stage QA approval creates `keyframes/final/KF<镜号>-<帧类型>/rNNN.<扩展名>`.
- Script/storyboard approval and keyframe-plan approval remain mandatory. Automated QA requires every check to pass at confidence >= 0.85; uncertain, low-confidence, and reference-board results require user review; rejection regenerates only the failed stage.
- v2 creates no new `keyframes/pending/` directory. Legacy execution manifests become `legacy_unplanned`; old pending files and Markdown are neither moved nor overwritten, and migration requires recreating the execution pack from an approved storyboard.
- No image, video, or editing provider is bound or automatically called. The documented APIs prepare/record local plans and results only.

## Validation

- `python3 -m unittest discover -s tests -v` — 49 tests passed.
- `python3 -m unittest tests/test_asset_migration.py -v` — 32 tests passed, including v2 dependency, revision, user-override, reference-board, and legacy-manifest behavior.
- `python3 -m py_compile .agents/skills/short-drama-butler/scripts/*.py tests/*.py` — passed.
- `git diff --check` — passed.
- Self-review compared all documentation claims to `project_files.py`, `keyframe_consistency.py`, the final design, and the task brief. No provider automation or new pending-directory behavior is claimed.

## Commit

- `docs: document v2 keyframe consistency workflow` (this task's commit)

## Concerns

- The implementation deliberately leaves image/board/QA adapters replaceable. Documentation therefore describes only the approved input/result-recording boundary and does not provide provider-specific instructions.
