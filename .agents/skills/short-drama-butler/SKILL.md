---
name: short-drama-butler
description: Use when initializing, organizing, migrating, or maintaining a children’s AI short-drama project with character, scene, prop, episode, and storyboard-handoff files.
---

# 短剧管家

管理可复用少儿 AI 短剧项目。先把设定与素材变成可追溯资产库，再将单集创作包交给 `seedance-storyboard-generator`；不调用视频 API。

## 操作路由

| 用户目标 | 执行内容 |
| --- | --- |
| 初始化或导入旧资料 | 读取固定设定，建立项目文件、资产预检和冲突清单。 |
| 整理/新增素材 | 维护 `Cxx`、`Sxx`、`Pxx`，默认新素材仅限本集。 |
| 创建一集 | 创建剧情需求、本集状态、素材清单与交接包。 |
| 交给分镜 | 生成/更新 `storyboard-package.md`，随后调用 `$seedance-storyboard-generator`。 |
| 审核/提升素材 | 确认剧集素材可跨集复用后，迁入全局库并更新索引。 |

## 初始化与迁移

1. 先用 `scripts/extract_docx_text.py` 读取固定设定，再读取所有素材，列出全局、季度、本集、待确认四种范围；禁止静默把待确认素材变为锁定设定。
2. 遇到文字与已确认图片冲突时，图片优先；写入 `project-settings/setting-conflicts.md`，并更新角色圣经。
3. 使用 `scripts/asset_migration.py preflight` 生成计划。确认数量、目标路径、哈希、重名和范围均正确后才执行迁移。
4. 仅使用迁移账本回滚；禁止手工覆盖、删除或猜测目标文件。

项目结构、资产范围和交接字段见 [references/project-files.md](references/project-files.md)。

## 剧集与分镜交接

- 固定写入 16:9 横屏、目标 120 秒、镜头数量由剧情节奏决定、关键帧图片→豆包图生视频→剪辑。
- 明确列出本集可用资产 ID、图片路径、不可改动设定和本集状态；新增角色/场景/道具默认本集专属。
- 交给 `$seedance-storyboard-generator` 时，要求其先给梗概、人物小传和分集大纲，获确认后再写剧本和分镜；覆盖其默认 15 秒、9:16 和固定镜头数规则。

交接包模板和必含字段见 [references/storyboard-handoff.md](references/storyboard-handoff.md)。

## 验收

- `asset-index.json` 中的每项都有唯一 ID、范围和实际路径。
- 迁移前后逐项哈希一致；账本可回滚。
- 所有剧集交接包都列出可用素材，且没有视频 API、自动视频生成或自动剪辑指令。
