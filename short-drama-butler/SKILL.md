---
name: short-drama-butler
description: Use when initializing or continuing an AI short-drama project, and whenever generating character, scene, prop, or keyframe images. Always attach existing confirmed assets as reference images; never invent a new look from text if asset-index.json already has that name.
---

# 短剧管家

管理可复用 AI 短剧项目。先把设定与素材变成可追溯资产库，再将单集创作包交给 `seedance-storyboard-generator`；不调用视频 API。

## 启动依赖检查

首次执行本 Skill 时，使用**本 Skill 安装目录内**的 `scripts/storyboard_dependency.py --install`（不能假定用户项目根目录有 `scripts/`）。它会检测同级 `seedance-storyboard-generator`；已安装则直接复用，缺失时才下载该 Skill 子目录。

下载固定到脚本记录的上游提交和 SHA-256，安装后写入版本账本；下载或校验失败时，报告错误并停止分镜交接，不要假装依赖已可用。

## 操作路由

| 用户目标 | 执行内容 |
| --- | --- |
| 初始化或导入旧资料 | 读取固定设定，建立项目文件、资产预检和冲突清单。 |
| 整理/新增素材 | 以名称、别名、类别、范围和图片路径登记素材；内部自动维护 `Cxx`、`Sxx`、`Pxx`，默认新素材仅限本集。 |
| 创建一集 | 运行 `scripts/butler.py new-episode`。用户说「小鸟和咕噜在森林里」时，必须把未登记名称列为新增资产，并问清类别（角色/场景/道具）。 |
| 生产本集资产 | 大纲确认后运行 `scripts/butler.py plan-assets`；出图前必须 `dispatch-asset` 并附上已确认参考图；确认图片后再 `provide-asset` / `confirm-asset`。 |
| 审核剧本与分镜 | 展示正式剧本和分镜，等待用户确认或按反馈修改；未经确认不得规划关键帧。确认后运行 `scripts/butler.py approve-script`。 |
| 规划 / 生成关键帧 | 逐镜列出首帧、尾帧、过程帧的数量和用途；方案确认后建立 v2 执行单。任何出图必须先运行 `scripts/butler.py dispatch-keyframe`，把返回路径读进当前对话后再生成。 |
| 结束一集 / 继续下一集 | 本集定稿后确认连续性记录；创建下一集时自动继承最近一份已确认记录。 |
| 交给分镜 | 生成/更新 `storyboard-package.md`，随后调用 `$seedance-storyboard-generator`。 |
| 审核/提升素材 | 确认剧集素材可跨集复用后，迁入全局库并更新索引。 |

## 统一命令

新对话先运行本 Skill 目录中的 `scripts/butler.py status`。它告诉你当前走到哪一步、下一步该运行哪条命令。不要用 `python3 -c` 直接调用内部函数。

常用命令：

```bash
python short-drama-butler/scripts/butler.py status
python short-drama-butler/scripts/butler.py inspect
python short-drama-butler/scripts/butler.py new-episode --episode EP001 --title 森林的一天 --story "..." --asset "咕噜" --asset "小鸟:characters" --asset "森林:scenes"
python short-drama-butler/scripts/butler.py plan-assets --episode EP001 --new "小鸟:characters:黄色小鸟"
python short-drama-butler/scripts/butler.py dispatch-asset --episode EP001 --name 小鸟
python short-drama-butler/scripts/butler.py provide-asset --episode EP001 --name 小鸟 --image front=out/bird.png
python short-drama-butler/scripts/butler.py confirm-asset --episode EP001 --name 小鸟
python short-drama-butler/scripts/butler.py dispatch-keyframe --episode EP001 --shot 01 --frame start
python short-drama-butler/scripts/butler.py record-image --episode EP001 --dispatch D-xxx --output out/frame.png
```

`codex_image_dispatch.py` 仍可作为 `inspect` / `dispatch-*` 的兼容入口；主流程一律走 `butler.py`。

## 新对话 / Codex 出图硬规则

即使用户只说“做图”“出关键帧”，没有写 `$short-drama-butler`，也必须先执行本 Skill。新窗口没有上一轮记忆，不得把项目当成空的。

1. 运行本 Skill 目录中的 `scripts/butler.py inspect` 和 `scripts/butler.py status`，读取 `asset-index.json`、角色圣经、当前剧集和下一步。
2. 关键帧使用 `butler.py dispatch-keyframe --episode <ID> --shot <镜号> --frame start|middle|end`；新角色/场景/道具使用 `butler.py dispatch-asset --episode <ID> --name <名称>`。
3. 对返回的每一张 `view_image_paths` 先 `view_image` / 读图，再调用 `$imagegen`。这些图分别约束人物身份、场景、道具或风格。
4. `prompt` 必须与派发单完全一致。`allowed` 为 false，或项目已有确认素材但参考图列表为空时，停止出图。
5. 不要询问用户是否参考已有素材。有确认图就必须用。只有项目里还没有任何确认图片时，才允许按文字圣经画第一批资产。
6. 旧执行单没有 `schema_version: 2` 时，按 `legacy_unplanned` 处理：禁止继续用旧提示词或 `keyframes/pending/` 出图。

本 Skill 不绑定某个图片供应商，但 **Codex 出图必须走上述适配层**。禁止直接把 `keyframe-execution.md` 里的提示词交给 `$imagegen`。

## 自动上下文规则

创建、继续、交接一集，或生成任何图片时，先自动定位项目根目录并读取 `project.yaml`、角色圣经、素材索引、冲突清单、相关剧集文件和实际存在的旧设定文本。用户只需提供故事意图、已知名称和必要的新信息；不要要求用户重复说“读取配置”“创建清单”或提供内部 ID。

若项目还没有配置或缺少会影响创作的关键信息，只询问缺失项。默认创建流程必须产出本集需求、资产清单和交接包。

用户说“这集 180 秒”“这集改为横屏”等只属于当前集的要求时，写入 `episode-overrides.yaml` 并在交接包中优先使用；不得改写项目默认配置或其他剧集。

连续剧在本集剧本、分镜或成片定稿后，先根据定稿内容起草 `episode-continuity.md`，包含关键事件、角色状态、最后一帧、未解线索和下一集必须承接项；用户确认后运行 `scripts/butler.py record-continuity` 标记为已确认。创建下一集时，自动读取直接前一集的已确认记录并写入交接包。若上一集记录仍是待确认，默认停止在确认节点；只有用户明确说本集是独立集时，才以 `--standalone` 创建且不继承上集。

## 初始化与迁移

1. 有旧资料时，先用 `scripts/extract_docx_text.py` 读取固定设定，再读取所有素材，列出全局、季度、本集、待确认四种范围；禁止静默把待确认素材变为锁定设定。
2. 没有旧资料时，先确认项目级制作参数，再产出故事方向、角色/场景/道具资产计划和出图提示词；生成并确认图片后再入库。
3. 遇到文字与已确认图片冲突时，图片优先；写入 `project-settings/setting-conflicts.md`，并更新角色圣经。
4. 使用 `scripts/asset_migration.py preflight` 生成计划。确认数量、目标路径、哈希、重名和范围均正确后才执行迁移。
5. 仅使用迁移账本回滚；禁止手工覆盖、删除或猜测目标文件。

项目结构、资产范围和交接字段见 [references/project-files.md](references/project-files.md)。

## 剧集与分镜交接

- 从 `project-settings/project.yaml` 读取受众、画幅、目标时长、内容限制、镜头节奏、分镜 Skill 和制作流程；这些选择由项目决定，Skill 不预设。
- 用户只需说“许岚”“管理员”“录音笔”等名称。内部 `Cxx`、`Sxx`、`Pxx` 仅用于索引和交接；按名称与别名解析，名称不唯一时列出候选项让用户选择。
- 明确列出本集可用资产 ID、图片路径、不可改动设定和本集状态；新增角色/场景/道具默认本集专属。
- 交给项目配置指定的分镜 Skill（可设为 `$seedance-storyboard-generator`）时，要求其先给梗概、人物小传和分集大纲，获确认后再写剧本和分镜；交接包项目配置优先于对方的默认规则。

## 本集新增资产生产关口

只要大纲中出现未登记的新角色、重要场景或道具，必须在“确认大纲”与“正式剧本 / 分镜”之间执行：

1. 识别新增资产的名称、类别和视觉说明，运行 `scripts/butler.py plan-assets --episode <ID> --new '名称:characters|scenes|props:视觉说明'` 生成本集生产单。建集时已分类的草案可直接沿用。
2. 展示生产单，待用户确认后再使用用户指定的图片工具生成参考图；也可接收用户提供的图片。出图前必须运行 `scripts/butler.py dispatch-asset`，把已确认风格/场景/角色图读进当前对话；生产单里的「必传参考图」不能省略。
3. 图片先放入项目目录后，用 `scripts/butler.py provide-asset --episode <ID> --name <名称> --image front=<路径>` 登记图片路径；角色默认登记 `front`、`side`、`back` 三视图，重要场景默认登记 `front`、`reverse`、`side` 三个机位。用户确认后必须运行 `scripts/butler.py confirm-asset`。它会以迁移账本安全归档整组图片，再登记为一个名称资产、更新生产状态、本集素材清单和交接包。默认范围为 `episode-<ID>`；只有明确确认才提升为季度或全局资产。
4. 确认资产已进入更新后的交接包后，再写正式剧本、镜头表和关键帧提示词。

未确认的生产单只能作为待生成草案，不能被分镜当作已锁定视觉素材。

## 剧本、分镜与关键帧关口

调用 `seedance-storyboard-generator` 时，让它生成 `formal-script.md` 和 `storyboard.md`。前者是剧本源文件；后者是分镜源文件，默认用**导演版逐镜说明**，不是 Markdown 表格。标题固定为“《剧名》<本集目标时长>秒导演版分镜｜<主要场景或版本>”；其后必须各占一行写“整体时长：…、画面规格：…、固定场景：…、本集主题：…”，再补必要的关键视觉设定。不得把标签和内容拆成两行。之后才逐镜写完整生产信息。5 秒镜头必须依次使用“关键帧画面、运镜、台词与口型时间段、非说话嘴型控制”；10 秒镜头必须依次使用“首帧 A 画面、尾帧 B 画面、运镜、台词与口型时间段、非说话嘴型控制”。两种镜头都必须继续以独立标题写声音策略、音效、入点、出点 / 转场、素材参考和分镜出图提示词。不要另写简化版故事或简化版分镜。

按剧情节奏、动作、对白和情绪变化智能拆镜：默认只使用 5 秒或 10 秒；总时长不能整除 5 秒时，最后一镜使用不足 5 秒的余数，不得为凑时长增加碎镜头。5 秒和余数镜头写“关键帧画面”，默认 1 张首帧；10 秒镜头写“首帧 A 画面、尾帧 B 画面”，默认 2 张。过程帧仅用于确实无法由首尾表达的变形、魔法、分阶段动作、复杂走位或关键反转；先在方案中写明原因，后续必须逐镜让用户明确确认，未确认即按两张执行。

正式剧本和分镜完成后，**先运行**本 Skill 目录中的 `scripts/validate_director_storyboard.py --storyboard <本集 storyboard.md> --target-seconds <本集目标时长>`。出现 Markdown 表格、6 / 7 秒等非标准镜头、缺少 5 秒 / 10 秒固定标题、总时长不符或缺少全局设定时，必须修正 `storyboard.md` 并重跑校验；校验通过前不得展示或要求用户确认。校验通过后才展示正式剧本和分镜并询问用户是否符合要求、是否要调整；收到明确确认后运行 `scripts/butler.py approve-script` 写入 `creative-review.md`。没有这项确认，不得规划关键帧，更不得使用图片工具生成关键帧。

随后按导演版分镜创建 `keyframe-plan.md`：5 秒或余数镜头固定 `start_only`；10 秒镜头固定 `start_end`。只有要表现不可省略中间状态的 10 秒镜头才能提议 `start_middle_end`，且必须写 `exception_reason`。展示方案时，将每个三帧例外单独问清“是否保留过程帧”；运行 `scripts/butler.py approve-keyframes` 时仅把用户明确同意的镜号写入 `--middle-shot`。未列入该参数的例外自动降为两帧。只有 `assert_keyframe_generation_allowed` 成功时才可生成关键帧。多帧的价值来自清晰的阶段差异和工具支持，不得用近似重复图凑数量；同一镜的图片应明确标注为首 / 过程 / 尾帧，便于交给图生视频工具。

关键帧执行阶段运行 `scripts/butler.py create-execution`。它从已确认分镜逐镜建立 `keyframe-execution.md` 和 schema v2 的 `keyframe-execution-manifest.json`：保留时长、镜头语言、画面三阶段、台词、声音策略、音效、入点、出点 / 转场、按名称的素材参考和原分镜出图提示词；Markdown 只展示当前确认版，JSON 保存逐阶段输入、哈希、质检和版本历史。不得把它降级为一句动作说明。详细字段见 [references/storyboard-to-keyframes.md](references/storyboard-to-keyframes.md)。

创建 v2 执行单时，每镜除了人可读的 `asset_references`，还必须给出结构化 `asset_uses`。每项以用户可说的资产 ID、名称或别名作为 `reference`，并明确 `role`（仅 `background`、`character_identity`、`prop_identity`、`lighting`、`composition`、`style`）、`required`，需要时再给 `view_hint` / `facing`、`relationship_group` 和连续性标记。系统将名称或别名解析为唯一的内部资产 ID、已登记视图、项目内相对路径和 SHA-256；名称歧义、未登记素材、缺图或无可用视图时停止该帧，不能猜测或删掉 required 素材。`frame_spec` 还必须明确 `continuity_contract`：没有承接关系时写 `null`；有承接关系时精确指定前序镜号/帧、继承维度和资产 ID，不能从自然语言推断。

用户继续只说名称，不需要输入内部 ID。若用户为某一镜或连续段提供额外参考图，先询问其约束的维度和范围；使用 `register_user_override` 将项目内图片复制到 `references/user/` 并记录 SHA-256。人物身份或道具身份覆盖必须指定唯一 `target_asset_id`；范围只能是单镜、明确镜号列表的连续段或整集。覆盖只替换声明维度，按单镜优先于连续段优先于整集、同范围较新优先；被替代项保留为 `superseded`，不改写资产索引或角色圣经。

调用 `prepare_keyframe_generation` 后，才会为一张帧图保存最多 5 张输入的阶段计划。带连续性合同的帧必须等待前序帧已确认；不可拆的关系组无法装入 5 图时，先登记并由用户确认同一计划的参考板，再重新规划。此函数只准备本地计划，**不调用任何图片、视频或剪辑供应商**。Codex 或其他适配层必须先运行 `scripts/butler.py dispatch-keyframe`（内部调用 `begin_stage_generation`）：它重算每张输入的 SHA-256、冻结提示词与输入并将阶段写为 `generating`，返回唯一的 `dispatch_id` 和 `view_image_paths`。随后适配层必须先把这些路径读进当前对话，再原样交给图片工具，并把带相同 `dispatch_id` 的返回数据交给 `scripts/butler.py record-image`；后者核对提示词、实际输入和哈希后，才将产图写为不可覆盖的工作版本：`episodes/<集>/keyframes/work/KF<镜号>-<帧类型>/rNNN-<阶段>.<扩展名>`。没有参考图路径时禁止调用图片工具。

每次生成后，使用 `scripts/butler.py record-qa` 写入结构化质检。自动质检只有在该阶段所有 required 类别均通过且置信度不低于 0.85 时才可通过；不确定、低置信度或参考板参与的结果必须转给用户审核。质检失败或用户否决时，只重做出错阶段并递增 revision，保留旧图和理由。需要用户主动重做已确认帧时运行 `scripts/butler.py redo-keyframe`；它保留历史、废止旧计划，并将直接连续性依赖帧重新阻塞，直到新锚点确认。最后阶段通过后，系统才写入确认版本 `episodes/<集>/keyframes/final/KF<镜号>-<帧类型>/rNNN.<扩展名>`；该确认帧可成为同镜后续帧或精确指定的连续镜头锚点。

v2 不创建新的 `keyframes/pending/` 目录。旧执行单缺少 `schema_version: 2` 时标记为 `legacy_unplanned`，仅可查看和人工归档；禁止自动出图、自动迁移、移动或覆盖任何旧 `keyframes/pending/` 文件或旧 Markdown。创建函数也会拒绝覆盖任何已有执行单；需要进入 v2 时，先人工归档旧执行单，再从已确认分镜创建新的 v2 执行单。

交接包模板和必含字段见 [references/storyboard-handoff.md](references/storyboard-handoff.md)。
与 Seedance Storyboard Generator 或其他分镜 Skill 的覆盖规则见 [references/seedance-integration-protocol.md](references/seedance-integration-protocol.md)。

## 验收

- `asset-index.json` 中的每项都有唯一 ID、范围和实际路径。
- 迁移前后逐项哈希一致；账本可回滚。
- 所有剧集交接包都列出可用素材，且没有视频 API、自动视频生成或自动剪辑指令。
