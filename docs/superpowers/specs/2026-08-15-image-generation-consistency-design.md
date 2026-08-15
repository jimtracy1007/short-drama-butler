# 短剧关键帧图片一致性：最终设计

日期：2026-08-15  
状态：最终方案，待实施

## 目标与边界

在单次图片生成或编辑最多使用 5 张参考图的限制下，建立短剧关键帧的一致性链路。链路必须让人物、场景、关键道具、同镜多帧和连续镜头的视觉状态可追溯、可复现地规划和质检。

它解决“实际发送过哪些图、分别承担什么作用、为何重做某一阶段”三个问题；不以一句“保持一致”的提示词代替记录。

不在本次范围内：

- 不调用视频生成或剪辑 API，不绑定图片平台的私有参数。
- 不承诺像素级确定性，也不修改已确认的原始资产图。
- 不增加无关资产或关键帧来掩盖一致性问题。
- 不重写导演版分镜、关键帧数量策略或现有两次用户确认关口。

## 已有基础与实施边界

现有短剧管家已具备多视图资产索引、名称/别名解析、剧本与关键帧方案确认，以及 `keyframe-execution-manifest.json` 的基础输出。新能力在这些既有流程之后接入：

```text
已确认剧本 / 分镜 + 已确认关键帧方案
        ↓
create_keyframe_execution_pack（写入 manifest v2 和静态帧规格）
        ↓
prepare_keyframe_generation（解析资产、等待或解析连续性锚点、生成阶段计划）
        ↓
图片调用适配层逐阶段出图 → 记录实际输入
        ↓
视觉质检 → 通过则继续，未知交给用户，失败只重做该阶段
        ↓
确认的 final 帧成为同镜后续帧或连续镜头的锚点
```

实施限定为以下五个边界；除它们以外不进行无关重构：

| 边界 | 位置 | 职责 |
| --- | --- | --- |
| 纯逻辑调度 | 新增 `scripts/keyframe_consistency.py` | 解析后的素材、静态帧规格和已确认锚点输入后，构建不超过 5 图的阶段计划；不调用图片工具、不写文件。 |
| 项目文件编排 | `scripts/project_files.py` | 校验结构化素材用途、写入和升级 manifest、记录生成/质检状态、维护阶段与文件版本。 |
| 图片调用适配层 | 短剧管家工作流或可替换 adapter | 按阶段计划调用用户选择的图片工具；唯一输入是提示词和已记录的图片路径，不含平台私有参数；只返回调用结果。 |
| 视觉质检适配层 | 短剧管家工作流或可替换 adapter | 对照阶段输入、不可变量和产图返回结构化 QA 结果；不能判断时转用户审核；只返回 QA 结果。 |
| 参考板构建适配层 | 可替换、非生成式的图片拼板 adapter | 仅从已确认的单体资产图制作一个项目内参考板；只返回拼板结果和成员清单。 |

所有 adapter 都是可替换实现，不被 Python 数据层硬编码，也不得自行改 manifest。`project_files.py` 是唯一写入者：`record_stage_generation(plan_id, stage_id, generation_result)` 验证并落盘图片调用结果，`record_stage_qa(plan_id, stage_id, qa_result)` 验证并落盘质检结果，`record_reference_board(board_result)` 验证并登记参考板，`approve_reference_board(board_id)` 记录用户确认。三个 adapter 仅返回数据，不写项目文件。

`generation_result` 必须含 `plan_id`、`stage_id`、`tool_request_id`、实际 `prompt`、按 `{path, sha256, role}` 列出的 `input_images`、临时 `output_path`、`started_at`、`completed_at` 和错误信息。`record_stage_generation` 只接受与已批准阶段完全一致的输入清单，验证产图文件后复制到标准 work 路径并计算其 SHA-256。`board_result` 必须含 `plan_id`、`relationship_group`、临时板图路径、布局方式和按 `{asset_id, path, sha256}` 列出的成员；`record_reference_board` 校验成员皆已确认后复制板图到标准路径，并返回和持久化唯一 `board_id`。任何不匹配的 result 均失败，不改变状态。

## 输入合同：结构化素材用途

保留 `asset_references` 作为人可读的名称列表，但新建的 v2 执行单必须额外提供每镜 `asset_uses`。不能再仅凭名称文本进入正式出图。

```json
{
  "reference": "小螃蟹",
  "role": "character_identity",
  "required": true,
  "view_hint": "side",
  "facing": "side",
  "continuity_relevant": true,
  "relationship_group": "crab-holds-shell"
}
```

字段规则：

- `reference` 是资产 ID、名称或别名；解析后必须写为稳定的 `asset_id`。
- `role` 只能是 `background`、`character_identity`、`prop_identity`、`lighting`、`composition` 或 `style`。`edit_target`、`continuity` 和 `reference_board` 只能由调度器生成，不能由分镜伪造。
- `required=true` 表示该对象必须被分配到某一阶段；任何 required 项未入计划即为错误，不允许以优先级静默丢弃。
- `view_hint` 和 `facing` 是调度器选择资产视图的依据。人物按 `front`、`side`、`back`、`expression-sheet` 回退；场景按 `front`、`reverse`、`side`、`wide`、`top` 回退。每次回退都必须记录 `fallback_reason`。
- `relationship_group` 表示不能拆开的接触或持有关系，例如“角色手持该道具”。含 `edit_target` 后仍超过 5 张的不可拆组不能假装可执行，必须报错或满足参考板条件。

`resolve_keyframe_asset_uses(project_root, asset_uses)` 必须返回 `asset_id`、名称、类别、范围、选中视图、项目内相对路径、SHA-256 和回退原因。它必须在规划前硬失败：名称歧义、未登记的 required 资产、路径不存在、没有可用视图、或路径逃出项目根目录。

“持续性”不再由自然语言猜测：同一资产在两镜及以上出现、被持有/传递/特写，或 `continuity_relevant=true` 时为 required；一次性环境装饰可为 optional，但不能成为连续性锚点。

## 用户参考图覆盖

用户提供的图先安全复制或登记到项目内 `references/user/`，计算 SHA-256 后才可使用。每项覆盖必须具有以下合同：

```json
{
  "override_id": "UO-09-01",
  "path": "references/user/beach-r001.png",
  "sha256": "…",
  "role": "background",
  "target_asset_id": null,
  "scope": "shot",
  "scope_ids": ["09"],
  "source": "user_upload",
  "created_at": "2026-08-15T00:00:00Z"
}
```

- `role=character_identity` 或 `prop_identity` 必须有唯一 `target_asset_id`；多人镜头中“人物按这张图”不能省略对象。
- `scope` 只能是 `shot`、`continuity_run` 或 `episode`。`continuity_run` 在写入时展开为明确镜号列表，直到分镜标注的场景、时间或叙事段落切换为止。
- 重叠覆盖按作用域 `shot > continuity_run > episode` 取唯一生效项；同一作用域、目标与维度中最新项优先。被更具体或更新项取代的覆盖写为 `superseded`，包含胜出 `override_id`，不进入阶段输入。用户覆盖只影响所声明维度，不修改资产索引或角色圣经。
- `style` 只约束渲染质感、色彩和笔触；它不得替换人物身份、场景几何或道具形状。背景、光线和构图同理只替换本维度锚点。
- 用户未声明用途时，流程只询问用途，不能把该图当作全维度参考。

每个维度经上述规则选出的生效覆盖都是 required 输入。若同一阶段无法容纳，调度器必须分阶段或报告不可行，不能丢弃生效覆盖或资产。

## Manifest v2、文件与迁移

`keyframe-execution-manifest.json` 升级为 schema v2。根对象包含 `schema_version: 2`、`episode_id`、`status`、`shots` 和 `user_overrides`。每个镜头保存静态 `asset_references`、`asset_uses` 与逐帧对象；逐帧对象保存 `frame_spec`、状态、依赖、计划历史与版本。

```json
{
  "schema_version": 2,
  "episode_id": "EP002",
  "status": "ready",
  "shots": [{
    "shot_id": "09",
    "asset_references": ["小螃蟹", "小彩纹贝壳", "泡泡湾海滩"],
    "asset_uses": ["…结构化素材用途…"],
    "frames": [{
      "frame_kind": "end",
      "status": "waiting_for_dependency",
      "frame_spec": {
        "prompt": "…",
        "allowed_changes": ["角色回头"],
        "continuity_contract": {
          "predecessor": {"shot_id": "09", "frame_kind": "start"},
          "inherit_dimensions": ["space", "character_identity", "prop_identity"],
          "asset_ids": ["P02", "S01"]
        }
      },
      "anchor_query": {"source": "same_shot_previous_confirmed", "shot_id": "09", "frame_kind": "start"},
      "plans": [],
      "confirmed_revision": null
    }]
  }]
}
```

`frame_spec` 是可在执行单创建时写入的静态事实，且必须包含 `continuity_contract`：`predecessor`（精确的 `shot_id`、`frame_kind`）、`inherit_dimensions`（`space`、`character_identity`、`prop_identity`、`composition` 的非空子集）和 `asset_ids`。没有承接关系时该合同明确写为 `null`，禁止由场景、动作或转场的自然语言猜测。`anchor_query` 由这个合同生成，是对“已确认帧”的查询，不能在此前伪造文件路径。`prepare_keyframe_generation` 只在依赖帧已确认后把它解析为带 revision、路径和 SHA-256 的 `continuity_anchor`，再创建一次具体 `generation_plan`。因此尾帧和下一镜不会错误地依赖尚未生成或尚未确认的图。

`prepare_keyframe_generation` 在首次调度前预留 `plan_id`；调度器据此写入或返回候选计划。若不可拆组需要参考板，它先返回 `reference_board_required` 与关系组，再由参考板流程为同一 `plan_id` 构建并确认板图，最后重跑调度。每次最终计划保存：解析后的资产、实际覆盖、具体锚点、`generation_mode`、阶段列表、不可变量、未采用 optional 图的原因。每个阶段保存输入角色、路径、SHA-256、提示词、产图、QA 与尝试历史。

文件不覆盖：

- 工作中间图：`keyframes/work/KF09-end/r001-background.png`。
- 确认成图：`keyframes/final/KF09-end/r001.png`。
- 同一阶段重做递增其 revision；旧文件仍保留并由 manifest 的 `supersedes` / `superseded_by` 关联。
- `keyframe-execution.md` 展示当前确认版路径；JSON 保存全历史，二者由同一写入函数原子更新。

旧 manifest 无 `schema_version` 或版本低于 2 时标记 `legacy_unplanned`，只允许查看与人工归档，禁止自动出图。唯一迁移方式是从已确认分镜重新创建 v2 执行单；旧 `keyframes/pending/` 文件和 Markdown 原样保留，不自动移动或覆盖。

## 调度算法与 5 图硬约束

调度器是纯函数：`build_generation_plan(plan_id, frame_spec, resolved_uses, applicable_overrides, confirmed_anchor, approved_boards)`。`approved_boards` 只含与当前 `plan_id` 和 `relationship_group` 精确匹配的已确认 `board_id`。它按以下确定性步骤工作：

1. 验证所有 required 素材与覆盖均已解析且文件存在；否则不输出计划。
2. 通过 `anchor_query` 解析本帧连续性依赖。无依赖的首帧可立即规划；有依赖但未确认时返回 `waiting_for_dependency`，不调用图片工具。
3. 将 required 输入按不可拆关系和维度分组：背景/空间、主要人物、次要人物与其持有道具。没有连续性锚点时先以 generate 阶段固定空间；有连续性锚点时首阶段必须为 edit，锚点是该阶段唯一 `edit_target`，不能再作为另一张输入图。
4. 每个 generate 阶段最多 5 张输入；每个 edit 阶段预留 1 张给唯一 `edit_target`，剩余 4 槽分配新加入的 required 参考。一个阶段不能容纳时继续拆分，不裁剪 required 项。首阶段使用已确认锚点时严格按 1 个 `edit_target` 加至多 4 张新增参考计算，不存在六图调用。
5. 仅当全部 required 输入能在一个无 `edit_target` 的阶段容纳时使用 `single_pass`；其余使用 `staged_edit`。optional 输入按优先级补槽，未采用时记录原因。
6. 每次阶段完成并 QA 通过后，其输出成为后续阶段的 `edit_target`。这个 QA 通过的派生图正式继承此前的空间/连续性锚点；后续阶段只要不改变相关维度，无需重复发送原锚点，避免虚耗槽位。

单阶段内 optional 输入优先级为：连续性、当前机位场景、主要人物、关键道具、次要人物、参考板。required 输入不参与“谁被挤掉”的排序，它们必须被分阶段分配。

参考板只在同时满足下列条件时可用：所有成员已有独立、已确认资产图；一个不可拆关系组即使拆阶段仍不能在 5 图中表达；`record_reference_board` 已为该 `plan_id` 与 `relationship_group` 写入 `board_id` 和 `references/boards/RB-<plan_id>-rNNN.png`，并记录板图 SHA-256、成员资产 ID、每个成员路径与 SHA-256、拼板方式和低分辨率风险；`approve_reference_board(board_id)` 已记录用户确认。调度器只能选择同一 plan、同一关系组的已确认 `board_id`，并把该 ID 写入阶段输入。它不能替代缺失资产，也不能用于掩盖可分阶段的群像；所有使用参考板的结果都进入用户审核。

## 阶段、连续性和不可变量

通常阶段顺序如下，调度器可跳过没有输入的阶段，但不得调整依赖顺序：

1. `background`：生成或编辑背景、机位、空间结构、时间和光线。
2. `primary_subjects`：以已通过 QA 的背景为底图，加入主要动作或台词人物。
3. `secondary_subjects`：以最近通过 QA 的底图，加入次要人物、关键道具和不可拆关系组；不足以容纳时切为多个连续阶段。

每一个编辑阶段恰好一个 `edit_target`。所有阶段都明确 `allowed_changes` 和 `invariants`：例如“只加入小螃蟹与贝壳”“不得改变海岸线、机位、光线、已存在对象”。重做原因必须转为当前阶段的禁止项或不变量。

连续性查询规则只读取 `continuity_contract`：

- 同镜 `middle` 的合同指向 `start`；`end` 指向 `middle`，没有过程帧时指向 `start`。
- 跨镜只在分镜作者已写出精确 predecessor 与继承维度时依赖该帧；未写合同即视为没有跨镜空间锚点。
- 场景、时间或叙事段落切换必须在合同中去除 `space`，而相关人物和道具的 `asset_ids` 仍可保留身份素材。
- 若当前阶段改变连续性相关维度，必须把对应确认锚点或其 QA 通过的派生 `edit_target` 放入阶段并记录继承链。

## 执行与质检状态机

帧状态为 `waiting_for_dependency`、`planned`、`generating`、`pending_review`、`confirmed`、`needs_regeneration`、`failed`。阶段状态为 `planned`、`generating`、`generated`、`qa_passed`、`pending_review`、`needs_regeneration`、`failed`。帧不单独进入 `generated` 或 `qa_passed`：它在每个阶段通过后保持 `generating`，最后一个阶段的 QA 结论才决定帧进入 `confirmed`、`pending_review` 或 `needs_regeneration`。

允许的迁移如下：

```text
帧：waiting_for_dependency → planned → generating → confirmed | pending_review | needs_regeneration
帧：generating → failed → planned；needs_regeneration → planned
阶段：planned → generating → generated → qa_passed → 下一阶段或帧确认
阶段：generated → pending_review → qa_passed | needs_regeneration
阶段：generated → needs_regeneration → planned；generating → failed → planned
```

图片调用 adapter 只在 `planned → generating → generated` 期间返回实际输入图、用途、SHA-256、提示词、时间、产图路径和调用结果；`record_stage_generation` 校验并写入这些数据。adapter 不得把图片标为 confirmed。

视觉质检 adapter 必须返回：

```json
{
  "status": "pass | uncertain | fail",
  "reviewer_type": "automated | user",
  "checked_at": "2026-08-15T00:00:00Z",
  "checks": [
    {"category": "character", "status": "pass", "confidence": 0.91, "evidence_paths": ["…"]}
  ],
  "issues": [
    {"code": "prop_color_drift", "message": "小彩纹贝壳由粉蓝变成黄色", "severity": "error"}
  ]
}
```

检查类别固定为 `character`、`scene`、`prop` 和 `continuity`。自动 QA 仅在每项 required 检查均为 pass 且置信度不低于 0.85 时，才由 `record_stage_qa` 写为 `qa_passed`；若它是最后阶段，该函数同时将帧从 `generating` 写为 `confirmed`。任何未知、低置信度、参考板使用或无法判断的项都转 `pending_review`。用户审核可确认或否决：确认后由同一函数将阶段写为 `qa_passed`，并在最后阶段确认帧；否决后写入原因并只重做出错阶段。失败必须使用明确代码，例如 `prop_color_drift`、`character_feature_missing`、`scene_orientation_flip`。

## 错误处理

- required 参考超过阶段容量：继续分阶段；不可拆组仍超容量时，按参考板门槛处理，否则失败并说明组与槽位。
- 用户图片不存在、越出项目根目录或哈希不匹配：停止该帧，不调用图片工具。
- 资产歧义、未登记 required 资产、空视图或缺失选定视图：停止该帧并进入资产生产或纠错流程。
- 阶段调用失败：保留所有前序 `qa_passed` 底图，只重试失败阶段。
- QA 失败或用户否决：创建新 revision，保留失败图、QA 结果和理由；不扩大到无关阶段。
- 旧版本或已标记 `superseded_downstream_files` 的执行单：禁止自动出图。

## 测试与验收

单元测试至少覆盖：

- 名称/别名解析为带路径与哈希的素材用途；歧义、未登记 required 项、空视图、路径不存在和路径逃逸均失败。
- 正面、侧面、背面、表情及场景正打、反打、侧面、空间视图的选择与回退原因。
- 1 至 5 个 required 输入的单阶段规划；第 6 个 required 输入与“edit_target + 两个覆盖 + 连续性 + 场景 + 人物”溢出时的无丢失分阶段规划。
- 用户背景、人物、道具、光线、构图和 style 覆盖只影响目标维度；多角色身份覆盖缺 `target_asset_id` 时失败；重叠 scope 按优先级产生唯一生效项和可追溯的 `superseded` 记录。
- 同镜和跨镜锚点在上游 confirmed 前等待，确认后形成带 revision 的继承链；场景切换只解除空间依赖。
- 每个编辑阶段恰有一个 `edit_target`，每个阶段至多 5 图，所有 required 输入均在某阶段出现。
- 有确认锚点时首阶段使用该锚点作为唯一 `edit_target`；参考板必须有已确认成员、板图哈希、用户确认和低分辨率风险记录。
- QA pass、uncertain、fail、用户确认、用户否决与阶段级重试的状态迁移。
- v1/无版本 manifest 标为 `legacy_unplanned`，不会移动或覆盖旧文件。

EP002 集成回归必须证明：小彩纹贝壳先登记为道具资产，圆润沙堡先登记为场景/道具资产；后段群像按阶段出图；用户海滩背景只覆盖场景；每阶段保存真实输入；贝壳、人物和水道在连续镜头中有可查询的确认锚点与版本链。

最终验收：

1. 出图前能逐帧回答实际将使用哪些图、每张图的作用、哪些 required 项已被分配。
2. 任意图片调用的输入图不超过 5 张，且 required 项从不被静默丢弃。
3. 只有已确认资产、合法用户覆盖和已确认连续性锚点可进入正式调用。
4. 用户覆盖精确限于声明维度与写入时固定的作用域。
5. 每个确认帧、阶段、QA 结论与重做版本都可由 manifest 追溯到路径和 SHA-256。
6. 旧执行单不被误升级或自动出图；新 v2 仅在状态机允许时推进。
