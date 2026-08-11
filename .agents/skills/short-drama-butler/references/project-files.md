# 项目文件约定

```text
project-settings/  项目配置、角色圣经、素材索引、冲突、迁移账本
source-material/   原始固定设定文档
assets/global/     可跨剧集复用的角色、场景、道具
assets/seasons/    某一季可复用素材
assets/episodes/   本集专属素材
assets/pending/    缺少文字设定或等待确认的素材
episodes/          剧情需求、剧本、分镜和交接包
```

| 字段 | 规则 |
| --- | --- |
| ID | 角色 `Cxx`、场景 `Sxx`、道具 `Pxx`；不得复用。 |
| 角色圣经 | 每位角色分别记录不可改动设定、可补充设定、本集状态。 |
| 素材范围 | 新素材默认 `episode-<ID>`；只有用户确认才改为 `global` 或 `season-<N>`。 |
| 迁移账本 | 记录原路径、目标路径、SHA-256、时间和状态；它是唯一回滚依据。 |

