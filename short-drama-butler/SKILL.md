---
name: short-drama-butler
description: Use when initializing or continuing an AI short-drama project, and whenever generating character, scene, prop, or keyframe images. Always attach existing confirmed assets as reference images; never invent a new look from text if asset-index.json already has that name.
---

# 短剧管家

管理可复用 AI 短剧项目。先把设定与素材变成可追溯资产库，再将单集创作包交给 `seedance-storyboard-generator`；不调用视频 API。

## 启动依赖检查

首次执行本 Skill 时，使用**本 Skill 安装目录内**的 `scripts/storyboard_dependency.py --install`（不能假定用户项目根目录有 `scripts/`）。它会检测同级 `seedance-storyboard-generator`；已安装则直接复用，缺失时才下载该 Skill 子目录。无论新装还是已有安装，都会把管家自己的 `references/director-board-contract.md` 盖到该 Skill 上。已经装过管家的人拉取更新后，下次运行 `butler.py status` 或 `inspect` 会自动同步这份合同，不必重装第三方 Skill。不要把第三方 `seedance-storyboard-generator/` 整目录提交进本仓库。

下载固定到脚本记录的上游提交和 SHA-256，安装后写入版本账本；下载或校验失败时，报告错误并停止分镜交接，不要假装依赖已可用。

## 操作路由

| 用户目标 | 执行内容 |
| --- | --- |
| 初始化或导入旧资料 | 读取固定设定，建立项目文件、资产预检和冲突清单。 |
| 整理/新增素材 | 以名称、别名、类别、范围和图片路径登记素材；内部自动维护 `Cxx`、`Sxx`、`Pxx`，默认新素材仅限本集。 |
| 创建一集 | 用户只说故事，例如「小鸟和咕噜在森林里快乐的一天」。运行 `scripts/butler.py new-episode --story "<用户原话>"`。随后用项目指定的分镜 Skill 生成故事梗概、人物小传、本集大纲和视觉资产分级，写入 `story-outline.md` 展示给用户。用户确认后才运行 `approve-story`；核心素材先于分镜，延后素材先于关键帧。不要让用户填写 `--asset`、路径或内部编号。 |
| 今天不知道写啥 | 用户说「今天不知道写啥」「你出个故事」「随便做一集」时，先运行 `scripts/butler.py propose-story`。若返回 `allowed: false`，先确认上集连续性，不要出故事、不要 `new-episode`。允许时根据已有锁定角色、场景和上集承接，用中文给出 2-3 个本集故事，等用户点头后再 `new-episode --story`。确认前不要建集、不要出图。 |
| 生产本集资产 | 仅在 AI 故事概要获用户确认后运行 `scripts/butler.py plan-assets`；它先生产 `before_storyboard` 核心资产，剧本分镜确认后再生产 `before_keyframes` 延后资产。出图前必须 `dispatch-asset` 并附上已确认参考图；确认图片后再 `provide-asset` / `confirm-asset`。 |
| 审核剧本与分镜 | 展示正式剧本和分镜，等待用户确认或按反馈修改；未经确认不得规划关键帧。确认后运行 `scripts/butler.py approve-script`。 |
| 规划 / 生成关键帧 | 逐镜列出首帧、尾帧、过程帧的数量和用途；方案确认后建立 v2 执行单。关键帧必须按帧派子 agent 出图：当前这一镜有几帧就同时派几个，做完审核后再开下一镜。子 agent 先运行 `scripts/butler.py dispatch-keyframe`，原样输出 `brief.text`，再读参考图生成。 |
| 精修静帧 | 用户可一次指出多张。运行 `refine-keyframe`（多个 `--item`，或单帧 `--shot/--frame/--note`），再按 status 返回的每一帧各派一个子 agent；精修帧优先于尚未开画的镜头。 |
| 结束一集 / 继续下一集 | 本集定稿后确认连续性记录；创建下一集时自动继承最近一份已确认记录。 |
| 交给分镜 | 生成/更新 `storyboard-package.md`，随后调用 `$seedance-storyboard-generator`。 |
| 审核/提升素材 | 确认剧集素材可跨集复用后，迁入全局库并更新索引。 |

## 统一命令

新对话先运行本 Skill 目录中的 `scripts/butler.py status`。它告诉你当前走到哪一步、下一步该运行哪条命令。不要用 `python3 -c` 直接调用内部函数。

常用命令：

```bash
python short-drama-butler/scripts/butler.py status
python short-drama-butler/scripts/butler.py inspect
python short-drama-butler/scripts/butler.py propose-story
python short-drama-butler/scripts/butler.py new-episode --story "小鸟和咕噜在森林里快乐的一天"
python short-drama-butler/scripts/butler.py record-story-outline --episode EP001 --file <AI生成的概要.md>
python short-drama-butler/scripts/butler.py approve-story --episode EP001
python short-drama-butler/scripts/butler.py reuse-asset --episode EP003 --name 小螃蟹 --action use
python short-drama-butler/scripts/butler.py plan-assets --episode EP001
python short-drama-butler/scripts/butler.py dispatch-asset --episode EP001 --name 小鸟
python short-drama-butler/scripts/butler.py provide-asset --episode EP001 --name 小鸟 --image front=out/bird.png
python short-drama-butler/scripts/butler.py confirm-asset --episode EP001 --name 小鸟
python short-drama-butler/scripts/butler.py plan-keyframes --episode EP001
python short-drama-butler/scripts/butler.py create-execution --episode EP001
python short-drama-butler/scripts/butler.py refresh-prompts --episode EP001
python short-drama-butler/scripts/butler.py refine-keyframe --episode EP001 --shot 01 --frame start --note "手再靠近开关"
python short-drama-butler/scripts/butler.py refine-keyframe --episode EP001 --item 01/start="开关按母版" --item 08/end="窗外必须是夜空"
python short-drama-butler/scripts/butler.py dispatch-keyframe --episode EP001 --shot 01 --frame start
python short-drama-butler/scripts/butler.py record-image --episode EP001 --dispatch D-xxx --output out/frame.png
```

`codex_image_dispatch.py` 仍可作为 `inspect` / `dispatch-*` 的兼容入口；主流程一律走 `butler.py`。

## 新对话 / Codex 出图硬规则

即使用户只说“做图”“出关键帧”，没有写 `$short-drama-butler`，也必须先执行本 Skill。新窗口没有上一轮记忆，不得把项目当成空的。

1. 运行本 Skill 目录中的 `scripts/butler.py inspect` 和 `scripts/butler.py status`，读取 `asset-index.json`、角色圣经、当前剧集和下一步。
2. 关键帧使用 `butler.py dispatch-keyframe --episode <ID> --shot <镜号> --frame start|middle|end`；新角色/场景/道具使用 `butler.py dispatch-asset --episode <ID> --name <名称>`。
3. 先原样输出返回的 `brief.text`（本图故事、本镜引用素材、制作时必须注意），再对每一张 `view_image_paths` 调用 `view_image` / 读图，再调用 `$imagegen`。这些图分别约束人物身份、场景、道具或风格。
4. `prompt` 必须与派发单完全一致。`allowed` 为 false，或项目已有确认素材但参考图列表为空时，停止出图。
5. 不要询问用户是否参考已有素材。有确认图就必须用。只有项目里还没有任何确认图片时，才允许按文字圣经画第一批资产。
6. 旧执行单没有 `schema_version: 2` 时，按 `legacy_unplanned` 处理：禁止继续用旧提示词或 `keyframes/pending/` 出图。
7. 每一张图都必须回到已确认母版，禁止镜头链式参考（镜头2只参考镜头1、镜头3只参考镜头2）。上一镜不得当作唯一或主身份锁。
8. 关键帧必须由子 agent 出图：首次、精修、重做都一样。`status` 返回的是**当前这一镜**的待出帧：本镜有几帧就同时派几个子 agent，做完并审核后再开下一镜。不要把后面还是 planned 的镜头一起派。一次精修多张时，按返回的帧各派一个。主 agent 不自己 generate、不把参考图读进主对话。等全部 `record-image` 后，主 agent 只审核。

## 子代理出图

同一镜内各帧同时派、彼此不互相等待；不要把后面 planned 镜头一起派。`butler.py status` 的 `keyframe_work.mode` 为 `spawn_subagents` 时：

- 主 agent：只读 status / inspect，按返回的每一帧各派一个子 agent，等全部 `record-image` 后，对照场景母版、角色母版和分镜审核。通过才 `record-qa`；墙体/开关/开口错了必须 fail 并 `refine-keyframe`，失败几张就派几个子 agent。用户可一次精修多张：先 `refine-keyframe`（多个 `--item`），再按返回的帧各派一个子 agent，主对话不要自己画。
- 子 agent：只负责一帧。运行 `dispatch-keyframe --shot <镜号> --frame start|middle|end`，先原样输出 `brief.text`，读完全部 `view_image_paths`，prompt 原样 generate，`record-image` 后返回 dispatch_id 与产出路径。禁止 `record-qa`，禁止改另一帧，禁止改 prompt。
- 5 秒 1 帧派 1 个；10 秒这一镜派 2 个；三帧例外这一镜派 3 个；精修/重做按被重开的帧派。当前镜做完再派下一镜。不要让主 agent 代画出任何一帧。

子 agent 任务应写明：剧集 ID、镜号、帧类型、必须先 `$short-drama-butler`、必须 dispatch 后先输出 `brief.text` 再出图。

禁止（误差会累积：角变长、脸漂移、帽子偏移、桌子比例跑掉）：

```
镜头1 → 镜头2 → 镜头3 → 镜头4
```

推荐 A（最稳）：每一帧都是 `角色母版 + 场景母版 + 道具母版 → 本镜`。默认一次 `dispatch-keyframe`，把返回的全部 `view_image_paths` 放进同一次 generate（不超过 5 张）。`generation_mode` 为 `single_pass` 时禁止再拆“先背景后人物”，禁止为补深夜另开空房间，禁止自制构图叠加层或用上一镜产图替换场景母版，也禁止在出图中改脚本或取消重写提示词。本镜若是深夜/黄昏/黎明，场景必须有对应已确认视图（如 `night=`）；没有就先 `dispatch-asset` 补时段母版并 `confirm-asset`，禁止用白天场景图出夜戏。只有超过 5 张或不可拆关系组才拆阶段；纯背景底图阶段只是装不下时的溢出，不是 3 个母版的正常路径。

推荐 B（实战）：本帧参考角色母版（必传，身份锁）、场景母版（必传，空间锁）、画面中的道具母版（必传），上一镜/上一帧仅可选辅助连续性（动作衔接、机位延续、视线、情绪）。上一镜不能是唯一或主身份参考。

本 Skill 不绑定某个图片供应商，但 **Codex 出图必须走上述适配层**。禁止直接把 `keyframe-execution.md` 里的提示词交给 `$imagegen`。

## 自动上下文规则

创建、继续、交接一集，或生成任何图片时，先自动定位项目根目录并读取 `project.yaml`、角色圣经、素材索引、冲突清单、相关剧集文件和实际存在的旧设定文本。用户只需提供故事意图、已知名称和必要的新信息；不要要求用户重复说“读取配置”“创建清单”、提供内部 ID，或填写 `--asset` 这类命令参数。用户说「小鸟和咕噜在森林里」时，你必须自己从故事里识别已有素材和新角色/场景/道具，用中文复述给用户确认。只自动锁定已确认、有有效图片、且对本集可用的素材；pending、其他集专属、以及 `planned` / `image_provided` 等未确认索引项都不能自动锁定。认不准的名称先当待确认项，确认前不要写分镜。

若项目还没有配置或缺少会影响创作的关键信息，只询问缺失项。默认创建流程必须先产出交接包与待确认的 AI 故事概要；故事概要获确认后，才按视觉资产分级产出相应阶段的资产清单。

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

先由项目指定的 Storyboard Generator 阅读本集 `storyboard-package.md`，生成“故事梗概、人物小传、本集大纲、视觉资产分级”并保存到 `story-outline.md`。视觉资产分级每行固定写为 `名称 | characters|scenes|props | before_storyboard|before_keyframes|incidental | 理由`：核心身份、空间或剧情装置用 `before_storyboard`；一次性但需近景、持握或跨镜连续的元素用 `before_keyframes`；普通背景、普通餐具等装饰用 `incidental`，不建独立素材。必须展示给用户；收到明确确认后运行 `scripts/butler.py approve-story --episode <ID>`。该命令未成功前，`plan-assets`、`dispatch-asset`、`provide-asset`、`confirm-asset`、`reuse-asset` 与 `approve-script` 都必须停止，不得用用户原话或未确认 AI 稿直接创建素材。

只要**已确认的故事概要**中有 `before_storyboard` 的未登记资产，必须在“确认大纲”与“正式剧本 / 分镜”之间执行：

1. 识别新增资产的名称、类别和视觉说明，运行 `scripts/butler.py plan-assets --episode <ID> --new '名称:characters|scenes|props:视觉说明'` 生成本集生产单。建集时已分类的草案可直接沿用。
2. 展示生产单，待用户确认后再使用用户指定的图片工具生成参考图；也可接收用户提供的图片。出图前必须运行 `scripts/butler.py dispatch-asset`，把已确认风格/场景/角色图读进当前对话；生产单里的「必传参考图」不能省略。
3. 图片先放入项目目录后，用 `scripts/butler.py provide-asset --episode <ID> --name <名称> --image front=<路径>` 登记图片路径；角色默认登记 `front`、`side`、`back` 三视图，重要场景默认登记 `front`、`reverse`、`side` 三个机位。用户确认后必须运行 `scripts/butler.py confirm-asset`。它会以迁移账本安全归档整组图片，再登记为一个名称资产、更新生产状态、本集素材清单和交接包。默认范围为 `episode-<ID>`；只有明确确认才提升为季度或全局资产。
4. 确认资产已进入更新后的交接包后，再写正式剧本、镜头表和关键帧提示词。

`before_keyframes` 的资产不阻断正式剧本和分镜：先让用户确认通过校验的 `formal-script.md` 与 `storyboard.md`，再运行同一条 `plan-assets --episode <ID>` 生成延后生产单。未确认并登记这些素材前，`plan-keyframes`、创建执行单和任何关键帧出图都必须停止。`incidental` 元素只在对应关键帧画面中处理，不能伪装成已锁定资产。

未确认的生产单只能作为待生成草案，不能被分镜当作已锁定视觉素材。

## 剧本、分镜与关键帧关口

调用 `seedance-storyboard-generator` 时，让它生成 `formal-script.md` 和 `storyboard.md`。前者是剧本源文件；后者是分镜源文件，默认用**导演版逐镜说明**，不是 Markdown 表格。标题固定为“《剧名》<本集目标时长>秒导演版分镜｜<主要场景或版本>”；其后必须各占一行写“整体时长：…、画面规格：…、固定场景：…、本集主题：…”，再补必要的关键视觉设定。不得把标签和内容拆成两行。之后才逐镜写完整生产信息。5 秒镜头必须依次使用“关键帧画面、动作过程、运镜、台词与口型时间段、非说话嘴型控制、角色声线”；10 秒镜头必须依次使用“首帧 A 画面、尾帧 B 画面、动作过程、运镜、台词与口型时间段、非说话嘴型控制、角色声线”。两种镜头都必须继续以独立标题写声音策略、音效、入点、出点 / 转场、素材参考和分镜出图提示词。动作过程必须写出 `00:00—00:xx` 节拍、点名角色，并把台词写进对应时间段；角色声线写年龄/质感/音区与这一句怎么说，画外音须标明。不要另写简化版故事或简化版分镜。

按剧情节奏、动作、对白和情绪变化智能拆镜：默认只使用 5 秒或 10 秒；总时长不能整除 5 秒时，最后一镜使用不足 5 秒的余数，不得为凑时长增加碎镜头。5 秒和余数镜头写“关键帧画面”，默认 1 张首帧；10 秒镜头写“首帧 A 画面、尾帧 B 画面”，默认 2 张。过程帧仅用于确实无法由首尾表达的变形、魔法、分阶段动作、复杂走位或关键反转；先在方案中写明原因，后续必须逐镜让用户明确确认，未确认即按两张执行。

正式剧本和分镜完成后，**先运行**本 Skill 目录中的 `scripts/validate_director_storyboard.py --storyboard <本集 storyboard.md> --target-seconds <本集目标时长>`。出现 Markdown 表格、6 / 7 秒等非标准镜头、缺少 5 秒 / 10 秒固定标题、总时长不符或缺少全局设定时，必须修正 `storyboard.md` 并重跑校验；校验通过前不得展示或要求用户确认。校验通过后才展示正式剧本和分镜并询问用户是否符合要求、是否要调整；收到明确确认后运行 `scripts/butler.py approve-script` 写入 `creative-review.md`。没有这项确认，不得规划关键帧，更不得使用图片工具生成关键帧。

随后运行 `scripts/butler.py plan-keyframes --episode <ID>`：默认从已确认导演版分镜生成 `keyframe-plan.md`，不必手写 shots.json。5 秒或余数镜头固定 `start_only`；10 秒镜头固定 `start_end`。只有要表现不可省略中间状态的 10 秒镜头才能提议 `start_middle_end`，且必须写 `exception_reason`。展示方案时，将每个三帧例外单独问清“是否保留过程帧”；运行 `scripts/butler.py approve-keyframes` 时仅把用户明确同意的镜号写入 `--middle-shot`。未列入该参数的例外自动降为两帧。只有 `assert_keyframe_generation_allowed` 成功时才可生成关键帧。多帧的价值来自清晰的阶段差异和工具支持，不得用近似重复图凑数量；同一镜的图片应明确标注为首 / 过程 / 尾帧，便于交给图生视频工具。

关键帧执行阶段运行 `scripts/butler.py create-execution`，默认不必提供 details-file。它读取已确认 `storyboard.md`：按「素材参考」解析已确认资产；每帧出图提示词由本帧画面 + 画风/时段/禁令 + 已确认资产 + 背景锁 + 场景道具锁拼装，不把整段动作过程、对白或运镜落幅写进这一张。角色参考图只锁外貌服装，姿势以本帧画面为准。整体空间当背景；场景母版里已有的固定物按道具处理，禁止新增窗口或糊成一块新结构。自动执行单每帧都从母版出图，不拿上一帧锁姿势。夜戏缺对应场景视图时，`status` 会先要求补母版，避免画错再精修。用户要改画面时用 `refine-keyframe` 追加，可一次多帧；有几张就派几个子 agent 重出，主对话不自己画；并阻塞依赖这些帧的连续性镜头。已有执行单可用 `refresh-prompts` 按分镜重拼提示词、时段母版和母版出图合同。夜戏缺多张场景时段图时，`status` 会逐项列出。Markdown 只展示当前确认版，JSON 保存逐阶段输入、哈希、质检和版本历史。不得把它降级为一句动作说明。详细字段见 [references/storyboard-to-keyframes.md](references/storyboard-to-keyframes.md)。

创建 v2 执行单时，每镜除了人可读的 `asset_references`，还必须给出结构化 `asset_uses`。每项以用户可说的资产 ID、名称或别名作为 `reference`，并明确 `role`（仅 `background`、`character_identity`、`prop_identity`、`lighting`、`composition`、`style`）、`required`，需要时再给 `view_hint` / `facing`、`relationship_group` 和连续性标记。系统将名称或别名解析为唯一的内部资产 ID、已登记视图、项目内相对路径和 SHA-256；名称歧义、未登记素材、缺图或无可用视图时停止该帧，不能猜测或删掉 required 素材。`frame_spec` 还必须明确 `continuity_contract`：没有承接关系时写 `null`；有承接关系时精确指定前序镜号/帧、继承维度和资产 ID，不能从自然语言推断。

用户继续只说名称，不需要输入内部 ID。若用户为某一镜或连续段提供额外参考图，先询问其约束的维度和范围；使用 `register_user_override` 将项目内图片复制到 `references/user/` 并记录 SHA-256。人物身份或道具身份覆盖必须指定唯一 `target_asset_id`；范围只能是单镜、明确镜号列表的连续段或整集。覆盖只替换声明维度，按单镜优先于连续段优先于整集、同范围较新优先；被替代项保留为 `superseded`，不改写资产索引或角色圣经。

调用 `prepare_keyframe_generation` 后，才会为一张帧图保存最多 5 张输入的阶段计划。默认把能装进 5 张的角色/场景/道具母版打进**同一 generate 阶段**，不要发明“先背景后人物”。只有超过 5 张或不可拆关系组才拆阶段；纯背景底图阶段只是溢出残留。带连续性合同的帧必须等待前序帧已确认；不可拆的关系组无法装入 5 图时，先登记并由用户确认同一计划的参考板，再重新规划。规划时角色/场景/道具母版是必传身份锁；上一镜只占可选连续性槽，不能顶替母版。超过 5 图时先丢掉上一镜辅助，再考虑分阶段，不得为了链式参考挤掉 required 母版。此函数只准备本地计划，**不调用任何图片、视频或剪辑供应商**。Codex 或其他适配层必须先运行 `scripts/butler.py dispatch-keyframe`（内部调用 `begin_stage_generation`）：它重算每张输入的 SHA-256、冻结提示词与输入并将阶段写为 `generating`，返回唯一的 `dispatch_id`、`brief` 和 `view_image_paths`。随后适配层必须先原样输出 `brief.text`，再把这些路径读进当前对话，再原样交给图片工具，并把带相同 `dispatch_id` 的返回数据交给 `scripts/butler.py record-image`；后者核对提示词、实际输入和哈希后，才将产图写为不可覆盖的工作版本：`episodes/<集>/keyframes/work/KF<镜号>-<帧类型>.<扩展名>`，例如 `KF01-start.png`。同一帧再次出图时，旧工作图移到 `keyframes/recovery/KF01-start-r001.png`。没有参考图路径时禁止调用图片工具。`view_image_paths` 里的角色/场景/道具母版是身份与空间锁；若含上一镜，只作动作、机位、视线、情绪辅助，不得当作唯一或主参考。

每次生成后，使用 `scripts/butler.py record-qa` 写入结构化质检。自动质检只有在该阶段所有 required 类别均通过且置信度不低于 0.85 时才可通过；不确定、低置信度或参考板参与的结果必须转给用户审核。质检只锁身份、空间和时段；上一镜辅助图不构成必过的 continuity 门。分镜要求的走位、姿势、视线变化必须通过，不得用上一帧站位否决本帧动作。质检失败或用户否决时，只重做出错阶段并递增 revision，保留旧图和理由。需要用户主动重做已确认帧时运行 `scripts/butler.py redo-keyframe`；它保留历史、废止旧计划，并将直接连续性依赖帧重新阻塞，直到新锚点确认。最后阶段通过后，系统才写入确认版本 `episodes/<集>/keyframes/final/KF<镜号>-<帧类型>.<扩展名>`，例如 `KF01-start.png`；该确认帧可成为同镜后续帧或精确指定的连续镜头锚点。重做时把旧确认图改名为 `KF01-start-r001.png`，当前确认始终是不带版本号的扁平文件。

v2 不创建新的 `keyframes/pending/` 目录。旧执行单缺少 `schema_version: 2` 时标记为 `legacy_unplanned`，仅可查看和人工归档；禁止自动出图、自动迁移、移动或覆盖任何旧 `keyframes/pending/` 文件或旧 Markdown。创建函数也会拒绝覆盖任何已有执行单；需要进入 v2 时，先人工归档旧执行单，再从已确认分镜创建新的 v2 执行单。

交接包模板和必含字段见 [references/storyboard-handoff.md](references/storyboard-handoff.md)。
与 Seedance Storyboard Generator 或其他分镜 Skill 的覆盖规则见 [references/seedance-integration-protocol.md](references/seedance-integration-protocol.md)。

## 验收

- `asset-index.json` 中的每项都有唯一 ID、范围和实际路径。
- 迁移前后逐项哈希一致；账本可回滚。
- 所有剧集交接包都列出可用素材，且没有视频 API、自动视频生成或自动剪辑指令。
