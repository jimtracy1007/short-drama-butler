---
name: short-drama-butler
description: Use when initializing, organizing, migrating, or maintaining an AI short-drama project with character, scene, prop, episode, and storyboard-handoff files.
---

# 短剧管家

管理可复用 AI 短剧项目。先把设定与素材变成可追溯资产库，再将单集创作包交给 `seedance-storyboard-generator`；不调用视频 API。

## 启动依赖检查

首次执行本 Skill 时，先运行：

```bash
python3 scripts/storyboard_dependency.py --install
```

它会检测同级 `seedance-storyboard-generator`；已安装则直接复用，缺失时才从 `liangdabiao/Seedance2-Storyboard-Generator` 下载该 Skill 子目录。安装成功后继续工作；下载或校验失败时，报告错误并停止分镜交接，不要假装依赖已可用。

## 操作路由

| 用户目标 | 执行内容 |
| --- | --- |
| 初始化或导入旧资料 | 读取固定设定，建立项目文件、资产预检和冲突清单。 |
| 整理/新增素材 | 以名称、别名、类别、范围和图片路径登记素材；内部自动维护 `Cxx`、`Sxx`、`Pxx`，默认新素材仅限本集。 |
| 创建一集 | 创建剧情需求、本集状态、素材清单与交接包。 |
| 生产本集资产 | 在大纲确认后，生成 `asset-production-plan.md` 和出图提示词；确认图片后再登记资产。 |
| 交给分镜 | 生成/更新 `storyboard-package.md`，随后调用 `$seedance-storyboard-generator`。 |
| 审核/提升素材 | 确认剧集素材可跨集复用后，迁入全局库并更新索引。 |

## 自动上下文规则

创建、继续或交接一集时，先自动定位项目根目录并读取 `project.yaml`、角色圣经、素材索引、冲突清单、相关剧集文件和实际存在的旧设定文本。用户只需提供故事意图、已知名称和必要的新信息；不要要求用户重复说“读取配置”“创建清单”或提供内部 ID。

若项目还没有配置或缺少会影响创作的关键信息，只询问缺失项。默认创建流程必须产出本集需求、资产清单和交接包。

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
3. 用户确认图片后，用 `register_project_asset` 按名称、别名、范围和图片路径登记。默认范围为 `episode-<ID>`；只有明确确认才提升为季度或全局资产。
4. 将确认资产补入本集素材清单和交接包，随后再写正式剧本、镜头表和关键帧提示词。

未确认的生产单只能作为待生成草案，不能被分镜当作已锁定视觉素材。

交接包模板和必含字段见 [references/storyboard-handoff.md](references/storyboard-handoff.md)。
与 Seedance Storyboard Generator 或其他分镜 Skill 的覆盖规则见 [references/seedance-integration-protocol.md](references/seedance-integration-protocol.md)。

## 验收

- `asset-index.json` 中的每项都有唯一 ID、范围和实际路径。
- 迁移前后逐项哈希一致；账本可回滚。
- 所有剧集交接包都列出可用素材，且没有视频 API、自动视频生成或自动剪辑指令。
