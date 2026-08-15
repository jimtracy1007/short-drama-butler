# 奇妙岛怪事 / 短剧管家

这是带项目记忆的 AI 短剧仓库。新对话也必须先读已有素材，不能凭文字重新发明角色。

## 每次开始先做

1. 读取 `short-drama-butler/SKILL.md`。
2. 运行：

```bash
python short-drama-butler/scripts/butler.py inspect
python short-drama-butler/scripts/butler.py status
```

3. 用户只需说「咕噜」「小鸟和咕噜在森林里」或「今天不知道写啥，你出个故事」。不要让用户填写 `--asset`、路径或内部编号。有故事时把原话交给 `butler.py new-episode --story`；没故事时先 `butler.py propose-story`，用已有角色出 2-3 个选项等用户点头。

## 出图硬规则

任何角色图、场景图、道具图、关键帧，在调用 `$imagegen` / `image_gen` 之前必须先拿到派发单：

```bash
python short-drama-butler/scripts/butler.py dispatch-keyframe --episode EP002 --shot 01 --frame start
python short-drama-butler/scripts/butler.py dispatch-asset --episode EP002 --name 小螃蟹
```

然后：

1. 对返回的 `view_image_paths` **逐张** `view_image`，把已有素材读进当前对话。
2. 再用这些图作为人物身份 / 场景 / 道具 / 风格参考去生成。
3. `prompt` 必须与派发单完全一致，不得改外观、不得新增角色。
4. `allowed` 为 false，或 `view_image_paths` 为空且项目已有确认素材时，**禁止出图**。
5. 旧版关键帧执行单没有 `schema_version: 2` 时，先归档再从已确认分镜重建 v2，不要拿 `keyframes/pending/` 或纯提示词继续画。

不要问用户「要不要参考已有素材」。索引里有图，就用图。

## 不要做的事

- 不要只把「青蓝色小怪兽」写成提示词，却不打开 `assets/global/characters/C01_gulu/`。
- 不要因为这是新窗口，就当项目是空的。
- 不要调用视频 API 或自动剪辑。
- 不要覆盖已确认图片；新版本递增保存。
