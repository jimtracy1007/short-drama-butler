# 项目文件参考

短剧管家自动读写这些文件。用户使用角色、场景和道具的名称即可，不需要修改内部编号。

## 目录地图

```text
project-settings/                 项目长期记忆
source-material/                  导入前的原始资料
assets/                           已确认、可在画面中使用的图片
episodes/EP001_剧集名/            单集工作资料
templates/                        新建资料时使用的模板
```

## 项目长期记忆

| 文件 | 谁用 | 作用 | 何时更新 |
| --- | --- | --- | --- |
| `project-settings/project.yaml` | 短剧管家、分镜 Skill | 受众、画幅、时长、内容尺度、镜头节奏、制作流程和分镜 Skill。 | 初始化或用户改变项目规则时。 |
| `project-settings/character-bible.md` | 创作与出图阶段 | 每个角色不可变特征、可补充特征、当前状态。 | 确认人物设定或角色发生持续变化时。 |
| `project-settings/asset-index.json` | Agent 和工具 | 已确认资产的内部 ID、名称、别名、范围、图片路径和视图。 | 图片确认并登记，或资产升降级时。 |
| `project-settings/setting-conflicts.md` | 创作与出图阶段 | 文字设定与已确认图片矛盾时的裁决；图片优先。 | 每次确认冲突处理时。 |
| `project-settings/source-document.json` | 导入审计 | 原始 Word 的来源、哈希和迁移时间。 | 导入旧 Word 时自动创建。 |
| `project-settings/fixed-settings-source.txt` | 分镜 Skill | 从旧 Word 提取出的可读取文本。 | 导入旧 Word 时自动创建。 |
| `project-settings/migration-ledger.json` | 维护者 | 素材迁移前后路径、哈希和状态；用于回滚。 | 执行素材迁移时。 |

## 素材库

| 位置 | 里面放什么 | 什么时候使用 |
| --- | --- | --- |
| `assets/global/` | 会在不同剧集或不同季持续出现的角色、场景、道具。 | 用户明确确认“以后会复用”。 |
| `assets/seasons/` | 只在某一季复用的素材。 | 用户确认只在本季复用。 |
| `assets/episodes/` | 只属于一集的已确认图片。 | 新资产确认图片后的默认位置。 |
| `assets/pending/` | 还没有确认、或缺少文字设定的素材。 | 等用户确认后再归类。 |
| `source-material/` | 原始 Word、旧剧本、导入前资料。 | 用于追溯，不直接当作锁定视觉素材。 |

## 每集文件

每集目录是 `episodes/EP001_剧集名/`。先有需求，后有大纲与资产，最后才进入剧本和分镜。

| 文件 | 创建时机 | 它回答的问题 | 是否可直接交给分镜 Skill |
| --- | --- | --- | --- |
| `story-brief.md` | 创建这一集时 | “这一集要讲什么？” | 参考；不是完整交接包。 |
| `episode-overrides.yaml` | 用户给本集特殊时长、画幅、受众、内容限制或制作流程时 | “这一集有什么不同于项目默认的要求？” | 是；覆盖仅对本集有效。 |
| `episode-continuity.md` | 创建时先生成待确认模板；本集定稿后确认 | “这一集发生了什么，下一集必须承接什么？” | 是；仅“状态：已确认”的记录才会自动带入下一集。 |
| `episode-state.json` | 创建这一集时；确认本集资产时更新 | “本集有哪些锁定资产和待生成草案？” | Agent 内部状态；用户通常不需要编辑。 |
| `episode-assets.md` | 创建这一集时 | “现在有哪些已确认资产？还缺哪些？” | 参考；新增草案不能当锁定资产。 |
| `asset-production-plan.md` | 大纲确认后且有新增资产时 | “新增角色、场景、道具的图什么时候、按什么标准制作？” | 用于图片生产；不是分镜输入。 |
| `asset-production-manifest.json` | 创建资产生产单时 | “每项计划资产的状态和预留图片路径是什么？” | 供 Agent / 工具更新；状态依次为 `planned → image_provided → user_confirmed → registered`。 |
| `creative-review.md` | 用户确认正式剧本与分镜后 | “当前剧本与分镜可以进入关键帧阶段吗？” | 第一确认关口；必须同时存在 `formal-script.md` 与 `storyboard.md`。 |
| `keyframe-plan.md` | 剧本与分镜确认后 | “默认 1 / 2 张，哪一镜确实需要过程帧？” | 用户确认的逐镜出图计划；未确认不能生成关键帧；第三帧须逐镜明确确认。 |
| `keyframe-manifest.json` | 创建关键帧方案时 | “关键帧方案的确认状态、每镜帧类型与过程帧例外原因是什么？” | 供 Agent / 工具执行；状态为 `user_pending → user_confirmed`，未明确确认的过程帧会降为两帧。 |
| `keyframe-execution.md` | 关键帧方案确认后 | “这一镜的时长、对白、声音、转场、参考素材和各帧文件是什么？” | 分镜的生产镜像；保留原分镜内容，只增加 `KF<镜号>-start/middle/end.png` 与逐帧出图提示词。 |
| `keyframe-execution-manifest.json` | 创建关键帧执行单时 | “执行单的机器可读镜头和帧图字段是什么？” | Agent / 工具用；不替代给用户查看的 `keyframe-execution.md`。 |
| `storyboard-package.md` | 创建这一集时，及资产确认后更新 | “分镜 Skill 必须遵守什么？” | 是。它是本集唯一正式交接包。 |

## 资产从想法到可用图片

```text
新名称出现在大纲
        ↓
episode-assets.md：本集新增草案
        ↓
asset-production-plan.md：确认生产任务
        ↓
图片生成并由用户确认
        ↓
asset-index.json：登记为已确认资产
        ↓
storyboard-package.md：作为锁定素材交给分镜
```

## 从分镜到关键帧

```text
正式剧本 + 导演版逐镜分镜完成
        ↓
用户确认：creative-review.md
        ↓
keyframe-plan.md：5 秒 1 张、10 秒 2 张；过程帧逐镜确认
        ↓
用户确认：keyframe-manifest.json
        ↓
keyframe-execution.md：继承完整分镜 + 补帧图文件
        ↓
生成并归档关键帧，再交给图生视频工具
```

关键帧默认按镜号和帧类型命名，例如 `KF07-start`、`KF07-middle`、`KF07-end`。5 秒或最后不足 5 秒的余数固定只需 `start`；10 秒固定 `start`、`end`。只有明确存在不可由首尾表达的中间状态时才可提议 `middle`，必须写明原因并由用户逐镜确认；若用户没有明确同意该镜，系统按两帧执行。多帧必须对应真实动作阶段，不能以近似重复图片凑数。

`keyframe-execution.md` 不是“简版执行提示”。它逐镜保留导演版分镜的时长、景别、运镜、起点、过程、终点、台词与口型控制、声音策略、音效、入点、出点 / 转场、参考素材和原分镜出图提示词；只新增关键帧文件与每张帧图的提示词，以便任何图生视频工具都能按相同信息制作。

新资产默认范围为 `episode-<ID>`。用户确认可复用后，才移动到 `global` 或 `season-<N>`；其名称和别名始终是用户面对的操作方式，`Cxx`、`Sxx`、`Pxx` 只供系统内部索引。

角色的推荐最小参考组是 `front`（正面）、`side`（侧面）、`back`（背面）；重要场景的推荐最小参考组是 `front`（正打）、`reverse`（反打）、`side`（侧面全景）。这些视图在素材索引中归入同一个资产名称，而不是三个独立角色或场景；后续创作仍只按名称调用。

## 连续剧记忆

```text
本集剧本 / 分镜 / 成片定稿
        ↓
episode-continuity.md：用户确认连续性事实
        ↓
下一集创建：自动读取最近一份“已确认”记录
        ↓
storyboard-package.md：上集承接（锁定）
```

连续性记录不保存聊天全文，只保存会影响下一集的事实：已发生事件、角色当前状态、最后一帧、未解线索和必须承接的开场条件。这样隔天或新对话继续制作也不会依赖模型记忆。

如果直接前一集还是待确认，连续集的创建会停在确认节点，不会退回读取更早剧集；只有用户明确声明独立集时，才不带入前序连续性。
