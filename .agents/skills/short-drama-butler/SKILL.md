---
name: short-drama-butler
description: Use when initializing, organizing, migrating, or maintaining an AI short-drama project with character, scene, prop, episode, and storyboard-handoff files.
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
| 创建一集 | 创建剧情需求、本集状态、素材清单与交接包。 |
| 生产本集资产 | 在大纲确认后，生成 `asset-production-plan.md` 和出图提示词；确认图片后再登记资产。 |
| 审核剧本与分镜 | 展示正式剧本和分镜，等待用户确认或按反馈修改；未经确认不得规划关键帧。 |
| 规划 / 生成关键帧 | 逐镜列出首帧、尾帧、过程帧的数量和用途，等待用户确认方案后才使用图片工具出图。 |
| 结束一集 / 继续下一集 | 本集定稿后确认连续性记录；创建下一集时自动继承最近一份已确认记录。 |
| 交给分镜 | 生成/更新 `storyboard-package.md`，随后调用 `$seedance-storyboard-generator`。 |
| 审核/提升素材 | 确认剧集素材可跨集复用后，迁入全局库并更新索引。 |

## 自动上下文规则

创建、继续或交接一集时，先自动定位项目根目录并读取 `project.yaml`、角色圣经、素材索引、冲突清单、相关剧集文件和实际存在的旧设定文本。用户只需提供故事意图、已知名称和必要的新信息；不要要求用户重复说“读取配置”“创建清单”或提供内部 ID。

若项目还没有配置或缺少会影响创作的关键信息，只询问缺失项。默认创建流程必须产出本集需求、资产清单和交接包。

用户说“这集 180 秒”“这集改为横屏”等只属于当前集的要求时，写入 `episode-overrides.yaml` 并在交接包中优先使用；不得改写项目默认配置或其他剧集。

连续剧在本集剧本、分镜或成片定稿后，先根据定稿内容起草 `episode-continuity.md`，包含关键事件、角色状态、最后一帧、未解线索和下一集必须承接项；用户确认后调用 `record_episode_continuity` 标记为已确认。创建下一集时，自动读取直接前一集的已确认记录并写入交接包。若上一集记录仍是待确认，默认停止在确认节点；只有用户明确说本集是独立集时，才以 `standalone=True` 创建且不继承上集。

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

1. 识别新增资产的名称、类别和视觉说明，调用 `create_asset_production_plan` 生成本集生产单。
2. 展示生产单，待用户确认后再使用用户指定的图片工具生成参考图；也可接收用户提供的图片。
3. 图片先放入项目目录后，用 `provide_episode_asset_images` 登记图片路径；角色默认登记 `front`、`side`、`back` 三视图，重要场景默认登记 `front`、`reverse`、`side` 三个机位。单张图片仍可用兼容接口 `provide_episode_asset_image`。用户确认后必须使用 `confirm_episode_asset`。它会以迁移账本安全归档整组图片，再登记为一个名称资产、更新生产状态、本集素材清单和交接包。默认范围为 `episode-<ID>`；只有明确确认才提升为季度或全局资产。
4. 确认资产已进入更新后的交接包后，再写正式剧本、镜头表和关键帧提示词。

未确认的生产单只能作为待生成草案，不能被分镜当作已锁定视觉素材。

## 剧本、分镜与关键帧关口

调用 `seedance-storyboard-generator` 时，让它生成 `formal-script.md` 和 `storyboard.md`。前者是剧本源文件；后者是分镜源文件，默认用**导演版逐镜说明**，不是 Markdown 表格：先写整体时长、画面规格、固定场景、本集主题和必要的关键视觉设定，再逐镜写完整生产信息。每镜必须保留镜号、时长、景别、运镜、画面关键状态 / 动作过程、台词与口型时间段、非说话嘴型控制、声音策略、音效、入点、出点 / 转场、素材参考和分镜出图提示词。不要另写简化版故事或简化版分镜。

按剧情节奏、动作、对白和情绪变化智能拆镜：默认只使用 5 秒或 10 秒；总时长不能整除 5 秒时，最后一镜使用不足 5 秒的余数，不得为凑时长增加碎镜头。5 秒和余数镜头写“关键帧画面”，默认 1 张首帧；10 秒镜头写“首帧 A 画面、尾帧 B 画面”，默认 2 张。过程帧仅用于确实无法由首尾表达的变形、魔法、分阶段动作、复杂走位或关键反转；先在方案中写明原因，后续必须逐镜让用户明确确认，未确认即按两张执行。

正式剧本和镜头表完成后，必须先展示二者并询问用户是否符合要求、是否要调整；收到明确确认后调用 `record_script_and_storyboard_approval` 写入 `creative-review.md`。没有这项确认，不得调用 `create_keyframe_plan`，更不得使用图片工具生成关键帧。

随后按导演版分镜创建 `keyframe-plan.md`：5 秒或余数镜头固定 `start_only`；10 秒镜头固定 `start_end`。只有要表现不可省略中间状态的 10 秒镜头才能提议 `start_middle_end`，且必须写 `exception_reason`。展示方案时，将每个三帧例外单独问清“是否保留过程帧”；调用 `approve_keyframe_plan` 时仅把用户明确同意的镜号写入 `approved_middle_shot_ids`。未列入该参数的例外自动降为两帧。只有 `assert_keyframe_generation_allowed` 成功时才可生成关键帧。多帧的价值来自清晰的阶段差异和工具支持，不得用近似重复图凑数量；同一镜的图片应明确标注为首 / 过程 / 尾帧，便于交给图生视频工具。

关键帧执行阶段调用 `create_keyframe_execution_pack`。它从已确认分镜逐镜建立 `keyframe-execution.md`：保留时长、镜头语言、画面三阶段、台词、声音策略、音效、入点、出点 / 转场、按名称的素材参考和原分镜出图提示词；只新增 `KF<镜号>-start/middle/end.png` 文件以及对应帧图提示词，并合成可复制的视频生成提示词。不得把它降级为一句动作说明。详细字段见 [references/storyboard-to-keyframes.md](references/storyboard-to-keyframes.md)。

交接包模板和必含字段见 [references/storyboard-handoff.md](references/storyboard-handoff.md)。
与 Seedance Storyboard Generator 或其他分镜 Skill 的覆盖规则见 [references/seedance-integration-protocol.md](references/seedance-integration-protocol.md)。

## 验收

- `asset-index.json` 中的每项都有唯一 ID、范围和实际路径。
- 迁移前后逐项哈希一致；账本可回滚。
- 所有剧集交接包都列出可用素材，且没有视频 API、自动视频生成或自动剪辑指令。
