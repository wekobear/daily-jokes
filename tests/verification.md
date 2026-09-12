# 本次视频流程验证

日期：2026-09-12。环境：macOS、Python 3.12、FFmpeg、Pillow 12.3。此文件记录已观察事实，不是完整链路通过声明。

| 阶段 | 本次结果 | 证据与限制 |
| --- | --- | --- |
| 网络文案 | 已真实执行 | 读取 Project Gutenberg《Jokes For All Occasions》开头 ABSENTMINDEDNESS 第一则，来源与中文改编见 `examples/umbrella/story.json` |
| GPT 图片分镜 | 已真实生成并查看 | 三张独立 941×1672 竖图，早上误拿伞／取回八把修好的伞／傍晚再次遇见女士。角色、雨伞数量与镜头顺序已检查；运行素材保存在本机，不装入公共 Skill |
| 本地分镜预演 | 已生成并检查 | 15 秒、720×1280、30 fps、H.264、AAC 静音轨，烧录中文字幕；视频画面及 metadata 明确标记为预演，不能视为 H3 生成视频 |
| MiniMax H3 V2 适配 | 客户端与离线合约通过 | 使用真实 localhost HTTP server 验证提交、轮询、下载、鉴权错误、超时、字段校验和错误脱敏；未以此冒充官方 API 实跑 |
| 断点续跑与合成 | 本地测试通过 | 包括不明 POST 不重提、明确拒绝后恢复、查询失败续跑、预算、文件指纹、运行锁、未知视频不被采纳、坏下载恢复、真实 FFmpeg 合成和交接包检查；服务商响应在 runner 测试中为模拟 |
| 真实 H3 生成 | 尚未执行 | 需要本地按量 API Key 和本次试跑预算；默认三个 5 秒 H3 768P 镜头估算 ¥7.50 |
| 视频号上传 | 未实现、未实测 | 当前宿主浏览器工具明确拒绝该站点，不能绕过；本版没有上传器，也没有真实后台草稿或发布记录 |

可复现的本地检查：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/package_skill.py --output dist/jokes.zip
```

当前测试包括 14 项 MiniMax HTTP 合约、3 项媒体集成、11 项 runner 状态与流程测试，共 28 项。它们使用合成测试媒体与模拟服务行为，不收费、不连接视频号、不证明官方账号权限或实际模型画面质量。

本次未创建新 release、定时任务、GitHub Actions 或视频号内容。源码推送以 GitHub 的实际提交记录确认，不以此文档代替远端核验。
