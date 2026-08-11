# Storyboard Generator 交接协议

短剧管家与任意分镜 Skill 通过 `storyboard-package.md` 协作。若使用 `seedance-storyboard-generator`，请确认其已具备以下规则；没有时可将本段作为调用提示附在交接包之后。

短剧管家的启动检查从 `liangdabiao/Seedance2-Storyboard-Generator` 获取其 `.claude/skills/seedance-storyboard-generator` 子目录；只在同级 Skill 缺失时下载，绝不覆盖已有版本。

```text
项目交接包优先规则：
当提供 storyboard-package.md 时，本交接包与它引用的 project.yaml、角色圣经、素材索引、冲突清单为最高优先级。
必须覆盖分镜 Skill 的默认受众、画幅、时长、镜头数、节奏和内容尺度；仅当项目字段为空时才可使用默认值。
素材索引中的名称、别名、图片路径和已锁定视觉设定必须保留。先输出梗概、人物小传和大纲，收到确认后再输出剧本和分镜。
```

这不是对某一版本或某一平台 API 的依赖。它是一条文件级约定：任何遵守该优先级和确认节点的分镜 Skill 都可以接入。
