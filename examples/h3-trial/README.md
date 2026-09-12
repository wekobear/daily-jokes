# 路灯下的老人：真实 API 动作试片

本案例复用《因为这儿亮》的结尾分镜，只生成一个镜头。左侧老人指向路灯，右侧路人愣住，用于验证首帧图生视频、动作变化和视频下载。

[播放真实 H3 试片](demo.mp4) · [完整输入和运动提示词](story.json) · [完整故事的本地版本](../afanti/README.md)

[![输入首帧](images/s3.png)](demo.mp4)

## 实际结果

- 供应商与模型：MiniMax H3，768P，请求四秒。
- 下载文件：4.458333 秒，768×1344，24 fps，H.264 视频与 AAC 音频。
- 服务报告输出四秒、输入一张图片；按当时刊例价输出估算 2 元，未核验实际账单。
- 文件指纹：`1bb901ed623e425ea5e08afaea9619059abdcaace53fc3bb867a7ff9e09bd7bc`。
- 已检查服务成功、本地下载、音视频解码，以及抽帧中的表情和动作变化。未逐字听验整段模型台词。

这不是完整十五秒 H3 故事，也不是另两镜已经生成的证明。原 MP4 保留 AI 生成标识，未重新编码或移除来源标记。

## 用自己的账号复刻

先按 [新手教程](../../docs/getting-started.md)准备环境和自己的 `.env`。以下命令先初始化和估算，不提交付费任务：

```bash
python3 scripts/pipeline.py init --story examples/h3-trial/story.json --run runs/my-h3-trial
python3 scripts/pipeline.py image --run runs/my-h3-trial --shot s3 --file examples/h3-trial/images/s3.png
python3 scripts/pipeline.py estimate --run runs/my-h3-trial
```

确认当前费率及本次授权预算后，再执行 `generate`；原任务处理中时继续同一目录，不重复初始化：

```bash
python3 scripts/pipeline.py generate --run runs/my-h3-trial --env-file .env --budget-cny 2
python3 scripts/pipeline.py status --run runs/my-h3-trial
```

预算不足时先停下，不能把此示例金额当作永久价格。重新生成不保证复制本样片的具体动作；若需要完整故事，重新规划全部镜头和预算，保留既有试片成本。

来源：[DLTK — The Lamp and the Key](https://www.dltk-kids.com/ya/nasruddin/lamp-key/story.htm)。人物使用通用外形描述，不依赖姓名维持形象；不以此承诺通过任何服务的内容审核。
