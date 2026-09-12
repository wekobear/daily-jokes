# MiniMax H3 视频 API 接入

用于本 Skill 的第三方视频生成阶段。参数与价格核验日期：2026-09-12。这里的“V2”是视频 API 版本，默认模型的准确标识是 `MiniMax-H3`，不是 `MiniMax-H3-V2`。本版通过首帧图生视频，每镜独立提交；文本与首帧图片仍由 Codex 准备。

## 账号与本地配置

需要 MiniMax 开放平台的普通按量 API Key，以及可覆盖生成费用的账户余额。普通按量 Key 与订阅 Key 的计费方式不同，不能仅凭已购买文字模型订阅推定已具备视频按量额度。[官方按量计费说明](https://platform.minimax.cn/docs/guides/pricing-paygo)

在仓库之外的私有环境文件，或已被 Git 忽略的本地 `.env` 写入：

```dotenv
MINIMAX_API_KEY=your_minimax_paygo_api_key
# 可省略；本版流水线仅接受中国区端点，以匹配人民币预算。
MINIMAX_BASE_URL=https://api.minimax.cn
```

运行时通过 `--env-file /private/path.env` 指定实际文件，或使用当前进程环境中的 `MINIMAX_API_KEY`。不要把真实 Key 发进仓库文件、提交说明、截图、命令输出或上传包。流程缺 Key 时报告缺口并保留已完成产物，不捏造任务标识或用预演顶替 API 结果。

## 本版请求契约

中国区创建入口为 `POST https://api.minimax.cn/v2/video_generation`，认证头为 `Authorization: Bearer <API_KEY>`，请求体为 JSON。官方另有国际区服务，但本版 `pipeline.py generate` 仅接受 `https://api.minimax.cn`，以保持人民币价格与预算口径一致；不能宣称流水线兼容任意供应商，也不能把换域名当作认证失败的盲目重试。[官方 V2 创建文档](https://platform.minimax.cn/docs/api-reference/video-generation-v2-create)

每镜请求的关键字段如下；运行脚本会读取镜头图片并编码，不需要先上传到公共图床：

```json
{
  "model": "MiniMax-H3",
  "content": [
    {"type": "text", "text": "保持输入图角色与画风，描述本镜动作、镜头运动和台词。"},
    {
      "type": "image_url",
      "image_url": {"url": "data:image/png;base64,<实际图片数据>"},
      "role": "first_frame"
    }
  ],
  "duration": 5,
  "resolution": "768P",
  "ratio": "adaptive"
}
```

源图片必须是真实竖幅。I2V 的画幅由输入图决定，传 `ratio: "9:16"` 不会把横图变成竖图。官方支持图片 URL、Base64 Data URL 和文件标识；本版只需要单张本地首帧，不必为联调新增云存储。不要混用旧 V1 视频接口的 `first_frame_image`、查询响应或下载流程。

与本流程有关的官方输入限制：H3 时长为 4—15 的整数秒，输出分辨率支持 `768P`、`2K`；图片不超过 30 MB，宽高各在 256—5760 像素之间，宽高比在 0.4—2.5 之间；请求体不超过 64 MB，提示词不超过 7000 字符。本版默认三个 5 秒的 `768P` 镜头。以创建文档及本次真实服务错误为准，不将能力表当作每个账号都已通过的运行证明。[官方创建参数](https://platform.minimax.cn/docs/api-reference/video-generation-v2-create)

H3 支持原生音视频输出。要口播时，在运动提示词中明确普通话、说话者、台词和声音要求；最终实际听看检查台词与画面。模型具备音频能力不代表每次都能准确说完指定内容，生成成功也不能替代声音验收。[H3 官方介绍](https://minimaxi.com/blog/minimax-h3)

## 成本与预算

下表是本次核验的输出刊例价，不是永久价格或实际账单：[官方价格](https://platform.minimax.cn/docs/guides/pricing-paygo)

| 模型 | 分辨率 | 输出单价 |
| --- | --- | --- |
| `MiniMax-H3` | `768P` | ¥0.50／秒 |
| `MiniMax-H3` | `2K` | ¥0.80／秒 |
| `MiniMax-H3-Max` | `480P` | ¥0.33／秒 |
| `MiniMax-H3-Max` | `768P` | ¥0.50／秒 |

H3 每次输入前五张图片免费，超过部分为 ¥0.20／张；本流程每镜一张图片，不产生该项超额输入费用。三个 5 秒、`MiniMax-H3`、`768P` 镜头的输出估算为 **¥7.50**，不包含重新生成的任务或其他服务费用。改成不同分辨率、时长或模型后重新估算；`H3-Max` 与 H3 的可用参数不同，不能仅凭名称直接替换。

每次实际提交前核对当前价格，价格变化时先更新脚本费率表与核验日期。先运行 `estimate`，再用 `generate --budget-cny 10` 给本次运行设置估算费用上限。脚本检查已计划／提交任务的估算额度，不是服务商账户硬性扣费限额；实际扣费以服务商账单为准。保留运行区的任务记录，不通过反复初始化或换目录规避预算；失败后重新生成也可能产生新的费用。

## 异步任务、下载与恢复

创建成功返回 `task_id`。随后通过 `GET /v2/query/video_generation/{task_id}` 查询；V2 的状态在 `task.status`，成功视频地址在 `task.content.url`。无需走旧 V1 的 `file_id` 下载链。[官方 V2 查询文档](https://platform.minimax.cn/docs/api-reference/video-generation-v2-query)

| 服务状态 | 处理 |
| --- | --- |
| `queued` / `running` | 保存已有任务标识，稍后继续查询，不重新创建 |
| `succeeded` | 读取 `task.content.url` 下载 MP4，再检查媒体与实际内容 |
| `failed` / `cancelled` | 保留失败记录，报告服务错误；重新生成是新的提交，不伪装成轮询 |
| 请求超时或返回结果不明 | 记录不确定状态并核实；不要自动盲目重提 |

官方建议查询间隔约 10 秒；本 CLI 每次只轮询一轮，待处理时返回退出码 `75`，调用者按节奏续跑。查询可覆盖最近 7 天内创建的任务，生成后及时下载。签名下载地址可能失效；若文件尚未取得，重新查询已有任务获取新的地址，而非重新生成视频。

创建请求结果不明、但在平台核查后找到任务时，可以恢复关联：

```bash
python3 scripts/pipeline.py reconcile --run runs/umbrella --shot s1 --task-id actual_task_id --env-file /private/path.env
```

必须先确认任务对应同一镜头的图片、提示词、模型与时长，再将其绑定到运行区。`reconcile` 查询指定任务并恢复本地记录，不重新 POST 创建视频；不能把其他镜头的成功任务随意绑定来使检查通过。绑定后用 `status` 检查，再按普通 `generate` 命令续跑。

`reconcile` 与 `generate` 使用相同的中国区端点限制，并核对返回模型、分辨率和时长；图像与提示词仍需操作者在平台核对。明确的 HTTP 400／401／402／422／429 提交拒绝可在修正原因后重跑 `generate`，尝试历史会保留；结果不明的 POST 始终不自动重提。下载重试只重新查询和下载已有任务；未登记或损坏的本地文件先移入运行目录的 `quarantine/` 留作检查。

只有“服务生成成功、实际文件已下载、媒体检查通过”才推进到可合成状态；台词、角色连续性和包袱仍需实际查看／收听判断，并在成片后通过 `review` 记录真实观察，才可制作上传包。本版的最终交接与后台阻断边界见 [视频流程](video-workflow.md)。
