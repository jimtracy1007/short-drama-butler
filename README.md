# 短剧管家：通用 AI 短剧资产与剧集管理 Skill

`$short-drama-butler` 是 AI 短剧的“项目记忆层”：它管理设定、角色、场景、道具、剧集和素材一致性。`$seedance-storyboard-generator` 则基于已整理的上下文创作故事、剧本和分镜。

它适用于少儿动画、都市情感、悬疑、喜剧、品牌剧情等任何需要跨集保持一致性的 AI 短剧。受众、画幅、单集时长、内容尺度和镜头节奏都由项目配置决定，不由 Skill 写死。

```text
项目设定 / 历史文档 / 图片素材
              ↓
      $short-drama-butler
  项目记忆、资产库、剧集交接包
              ↓
$seedance-storyboard-generator
故事 → 大纲 → 剧本 → 分镜 → 关键帧提示词
              ↓
关键帧图片 → 图生视频工具 → 剪辑成片
```

短剧管家不调用 Seedance、豆包或其他视频 API，也不自动剪辑。你可以使用任意图片和视频工具。

短剧管家在首次使用时会自动检测同级的 `seedance-storyboard-generator`：已安装则直接复用，缺失时仅下载上游仓库里的该 Skill 子目录，不覆盖已有安装。它会使用 [liangdabiao/Seedance2-Storyboard-Generator](https://github.com/liangdabiao/Seedance2-Storyboard-Generator) 作为来源，并让它遵守本项目的[交接优先协议](.agents/skills/short-drama-butler/references/seedance-integration-protocol.md)：交接包的项目参数高于分镜 Skill 的默认值。这样即使对方 Skill 默认使用短时长或竖屏，也不会覆盖你的项目配置。

Codex Skill 本身没有“安装完成后自动执行脚本”的生命周期钩子，因此可靠的自动动作发生在你第一次调用 `$short-drama-butler` 时，而不是下载文件夹的瞬间。需要手动触发时，运行：

```bash
python3 .agents/skills/short-drama-butler/scripts/storyboard_dependency.py --install
```

## 你只需要说名称，不需要记编号

你可以这样说：

> 这一集使用许岚、管理员、旧书店和录音笔；新来的实习生只在本集出现。

短剧管家会在内部将素材绑定为 `Cxx`、`Sxx`、`Pxx` 等稳定 ID，供 Agent 检索、图片路径追踪和 Storyboard 交接使用。它不会要求你输入 `C01` 或 `S02`。

如果“妈妈”对应多个角色，短剧管家会列出候选项让你选择；找不到“小兔子”时，会先把它标为本集新增资产，而不是擅自套用已有角色。

## 项目文件

```text
project-settings/
  project.yaml                 项目级制作参数
  character-bible.md           角色不可改动设定、可补充设定、本集状态
  asset-index.json             内部 ID、名称、别名、范围和图片路径
  setting-conflicts.md         文字与图片冲突的裁决
  migration-ledger.json        已导入旧素材的可回滚账本
source-material/               历史 Word、设定稿等原始资料
assets/
  global/                      跨剧集复用
  seasons/                     某一季复用
  episodes/                    仅限某一集
  pending/                     等待确认
episodes/
  EP001_剧集名/
    story-brief.md
    episode-assets.md
    storyboard-package.md
```

项目配置仅保存这个项目自己的选择。新项目可以从空值开始，确认后再填写：

```yaml
project_name: ""
audience: ""
format: ""
episode_target_seconds: ""
shot_count: ""
content_guidelines: ""
visual_canon_precedence: ""
video_workflow: ""
storyboard_skill: ""
```

## 路径一：已有旧资产和历史文档

适合你已经有角色图、场景图、道具图、Word 设定或以前做过的剧本。

1. 将资料放到项目根目录，不需要预先改名或手工分类。
2. 调用短剧管家做预检，确认范围和冲突后才迁移。
3. 它会提取文档、建立角色圣经、给素材分配内部 ID、保留原文件名和哈希账本。

```text
$short-drama-butler

我有一批旧角色图、场景图和一份 Word 设定。请初始化项目：
先读取资料并输出预检清单，按“全局、季度、本集、待确认”分类；
我确认后再迁移素材、建立角色圣经、素材索引和冲突清单。
项目参数先向我确认，不要替我预设受众、画幅、时长或内容限制。
```

例如：一张叫“录音笔.png”的图会在索引中记录名称“录音笔”、原文件名、迁移后路径和内部 ID；之后你只需继续说“录音笔”。

## 路径二：从零创建新短剧

适合只有一个想法，尚未写故事、没有角色图和场景图的项目。

1. 短剧管家先初始化空项目，并确认制作参数。
2. 先产出故事方向、人物关系和资产计划，不立即生成分镜。
3. 生成或确认角色、场景、道具参考图后，把它们导入资产库。
4. 有了锁定资产，再创建第一集并交给分镜 Skill。

```text
$short-drama-butler

我要从零创建一个 AI 短剧项目。
题材是都市轻喜剧，核心设定是“共享办公室里会说话的打印机”。
请先向我确认受众、画幅、单集时长和内容限制；
然后输出故事方向、人物关系、角色/场景/道具资产计划，以及每项的关键帧出图提示词。
确认资产图后，再把它们作为全局或本集素材入库。
```

资产图可由你使用任意图片工具生成，也可以直接让 Codex 根据资产计划生成。每次生成后，短剧管家负责登记名称、别名、范围、图片路径和一致性规则。

## 创建新的一集

每天的剧集可以完全独立，只要它引用同一个项目资产库即可。

```text
$short-drama-butler

创建一集《雨夜来信》。主角使用“林夏”和“周屿”，场景使用“旧咖啡馆”。
新出现的“快递员”先设为本集专属角色。
读取当前项目配置，创建剧情需求、本集状态、素材清单和 Storyboard 交接包。
```

短剧管家会：

- 用名称和别名解析已有素材；内部 ID 只出现在资料表中。
- 将“快递员”放入本集新增资产，除非你明确决定以后复用。
- 把项目参数、已锁定设定、可用素材路径和本集状态写进 `storyboard-package.md`。

## 交给 Storyboard Generator

```text
$seedance-storyboard-generator

请读取：
<项目根目录>/episodes/EP001_剧集名/storyboard-package.md

同时遵守该项目的 project.yaml、character-bible.md、asset-index.json、
setting-conflicts.md 和已有固定设定资料。

先输出故事梗概、人物小传和本集大纲，等待我确认后再写正式剧本；
最后按项目配置拆分镜头表，并为每镜生成关键帧出图提示词。
```

这样，分镜 Skill 会继承当前项目的参数，而不是套用自身的默认时长、画幅或镜头数。

## 素材生命周期

```text
新想法 / 新人物
      ↓
本集新增资产（默认）
      ↓  用户确认可复用
季度素材或全局素材
      ↓
后续剧集按名称调用并保持一致
```

当文字设定与最终确认的参考图冲突时，以确认图片为视觉准则，并把裁决写入 `setting-conflicts.md`。这能让之后的故事、图片和视频都遵守同一版本。

## 边界

- 不直接调用视频 API，不自动剪辑。
- 不替用户决定受众、画幅、时长、内容尺度或项目类型。
- 不把本集新增素材自动升级为全局资产。
- 不覆盖 `seedance-storyboard-generator`；两者目前通过交接包协作，流程稳定后可再合并为一个入口。
