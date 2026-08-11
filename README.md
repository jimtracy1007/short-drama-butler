# 短剧管家：少儿 AI 短剧制作工作流

`短剧管家`（`$short-drama-butler`）用于管理少儿 AI 短剧项目的设定、角色、场景、道具和剧集资料；`Seedance 分镜生成器`（`$seedance-storyboard-generator`）负责基于这些资料完成故事、剧本与分镜。

它们不调用 Seedance、豆包或任何视频 API。视频制作保持人工可控：先生成每个镜头的关键帧图片，再在豆包做图生视频，最后剪辑成一集。

## 适用场景

- 已有角色图、场景图、道具图和历史设定文档，想先整理成长期可复用的项目资产库。
- 每天制作独立的一集短剧，但仍要保持主角、家、道具和画风一致。
- 新增角色、场景或道具时，希望先作为“本集素材”，确认成熟后再提升为全局素材。
- 每集为 16:9 横屏、约 120 秒；镜头数量不预设，依据剧情、动作、对白和情绪变化决定。

## 两个 Skill 如何配合

```text
固定设定 + 图片素材
        ↓
$short-drama-butler
整理设定、迁移素材、创建本集交接包
        ↓
$seedance-storyboard-generator
故事梗概 → 人物小传 → 分集大纲 → 正式剧本 → 分镜表
        ↓
逐镜生成关键帧图片 → 豆包图生视频 → 剪辑成片
```

短剧管家只交接“已锁定且可用的项目上下文”，不会替你直接生成视频。分镜生成器也不应自行改写角色圣经或素材范围。

## 项目目录

```text
project-settings/
  project.yaml                 制作参数与项目级规则
  fixed-settings-source.txt    从 Word 提取出的可读设定文本
  character-bible.md           锁定角色设定、可补充设定与本集状态规则
  asset-index.json             角色/场景/道具的唯一 ID 和图片路径
  setting-conflicts.md         文字与图片不一致时的裁决记录
  migration-ledger.json        素材迁移账本，可用于回滚
source-material/
  固定设定.docx                 原始 Word 文档
assets/
  global/                      跨剧集可复用素材
  seasons/                     某一季可复用素材
  episodes/                    仅限特定剧集的素材
  pending/                     还没有完整小传、等待确认的素材
episodes/
  EP001_剧集名/
    story-brief.md
    episode-assets.md
    storyboard-package.md
```

## 素材管理规则

| 类型 | 编号 | 示例 |
| --- | --- | --- |
| 角色 | `Cxx` | `C01` 咕噜 |
| 场景 | `Sxx` | `S01` 星星客餐厅 |
| 道具 | `Pxx` | `P01` 鞋柜 |

每个逻辑素材只占一个 ID，可在索引内包含正面、侧面、背面、表情或场景反打等多个参考图。

新增素材默认只属于当前剧集。只有明确确认“以后也要复用”时，短剧管家才会将它提升为 `global` 或 `season-<N>`。如果历史文档与已确认角色图冲突，以已确认图片作为最终视觉准则，并记录在 `setting-conflicts.md`。

## 首次导入旧项目

将 Word 文档和图片放到项目根目录后，使用：

```text
$short-drama-butler

初始化这个少儿短剧项目：读取固定设定和现有素材，先输出全局、季度、本集、待确认素材的预检清单；确认后迁移并重命名素材，建立角色圣经、素材索引、冲突清单和迁移账本。
```

迁移分为两步：先预检，再移动。预检会检查源文件、目标路径、哈希和重名；迁移后账本保留原路径、目标路径与 SHA-256。不要手工移动已入库素材。

如需恢复一次素材迁移，使用账本回滚：

```bash
python3 .agents/skills/short-drama-butler/scripts/asset_migration.py rollback \
  --project-root . \
  --ledger project-settings/migration-ledger.json
```

## 制作新的一集

先让短剧管家创建剧集资料。示例：

```text
$short-drama-butler

创建一集 16:9 横屏、目标 120 秒的少儿短剧。
主题是“学会分享”；主角是咕噜。使用 C01、C02、C03、C04、S01 和 S02。
新出现的小兔子先作为本集专属角色；请创建剧情需求、本集素材清单和 Storyboard 交接包。
```

短剧管家应在交接包中固定写入：

- 3—8 岁、16:9 横屏、目标 120 秒。
- 镜头数量由剧情节奏决定，避免无意义碎镜头。
- 温暖、明亮、儿童友好；无恐怖、攻击性、字幕、Logo 或水印。
- 本集已锁定的素材 ID、参考图路径、不可改动设定和本集状态。
- “关键帧图片 → 豆包图生视频 → 剪辑”的人工制作路径。

## 交给 Storyboard Generator

交接包准备好后，再调用分镜 Skill。请始终先确认故事和大纲，再让它生成正式剧本与分镜。

```text
$seedance-storyboard-generator

请读取：
<项目根目录>/episodes/EP001_剧集名/storyboard-package.md

并同时遵守：
- <项目根目录>/project-settings/project.yaml
- <项目根目录>/project-settings/fixed-settings-source.txt
- <项目根目录>/project-settings/character-bible.md
- <项目根目录>/project-settings/setting-conflicts.md

先输出故事梗概、人物小传和本集大纲，等待我确认后再写正式剧本；最后自动拆分分镜表，并为每镜给出关键帧出图提示词。
不要沿用默认的 15 秒、9:16 或固定镜头数规则。
```

分镜表的每一行应包含镜头号、景别、运镜、画面动作、台词、预估时长和关键帧提示词。总时长以约 120 秒为目标，允许根据故事节奏调整每镜时长。

## 当前项目示例

本仓库已经完成《奇妙岛怪事》的首次导入：50 张图片被整理为 25 个逻辑资产。可直接从以下交接包开始：

- [EP001《分享的泡泡》交接包](episodes/EP001_分享的泡泡/storyboard-package.md)

其中夜猫怪的文件名和尾巴设定差异已记录在 [设定冲突清单](project-settings/setting-conflicts.md)。

## 边界

- 不直接调用 Seedance、豆包或其他视频生成 API。
- 不自动剪辑视频，也不替代人工审核关键帧与成片。
- 不把没有完整文字设定的角色自动升级为锁定主角。
- 不覆盖原有 `seedance-storyboard-generator` Skill；后续可在流程稳定后再合并两者的入口。
