# 每日笑话 · /jokes

一个可分享的 Agent Skill，包含两条制作路线：日常生成五个不同结构的文字笑话／独立漫画，以及将一则笑话制作成分镜和 AI 短视频。仓库名为 `daily-jokes`，技能短标识为 `jokes`。

视频路线由 Codex 联网收集文案、生成并查看 GPT 图片，再由本地脚本调用 MiniMax 视频 API、下载镜头、组合成片和整理上传包。默认一则笑话、三个独立 9:16 镜头；它不会为满足旧文字模式而先生成五则或制作漫画拼格。

**当前版本没有视频号上传器，不能声称已端到端跑通自动上传。** 2026-09-12 的接入尝试被宿主工具的站点安全策略拒绝，当前最后一步交付上传包，状态为待交接。后续只有在宿主可用且政策允许时才能通过官方支持渠道继续接入，并核验真实后台结果。见 [视频流程与完成边界](references/video-workflow.md)。

## 使用

视频流程请使用 [main 分支源码](https://github.com/WekoBear/daily-jokes/tree/main)。[v1.1.0 安装包 jokes.zip](https://github.com/WekoBear/daily-jokes/releases/download/v1.1.0/jokes.zip)仍是旧文字／漫画版本，包含首次配置、原生表单优先、近期热梗及每则独立漫画，**不包含本文的视频流程**。本次不创建新 release。

仓库根目录本身就是 Skill。从源码安装时，将完整仓库内容放入宿主支持的 `jokes/` 技能目录，保留 `references/`、`scripts/`、`examples/` 和依赖文件，再确认宿主已发现它；不要只复制入口文件。运行区、私有环境文件和登录态不属于可分享的 Skill 包。

## 视频流程

在 Codex 中使用：

```text
$jokes 在网上找一则生活笑话，用 GPT 生成三个独立竖屏分镜，
再调用 MiniMax API 做成短视频，并准备视频号上传交接包。
```

Codex 负责真实检索、文案和生图，终端脚本不冒充具备这些模型能力。首次无需图片 API 密钥；视频生成需要自己的 MiniMax API 密钥和账户余额。H3 V2 的准确模型名、计费口径与环境变量见 [MiniMax 接入说明](references/minimax-api.md)。

本版运行器支持 macOS／Linux，需要 Python 3.11+、`ffmpeg`、`ffprobe` 和可用的中文字库。从仓库根目录准备环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
python3 scripts/pipeline.py doctor
```

用 [雨伞样例](examples/umbrella/story.json)试跑，或由 Codex 按同一格式写入实际检索的故事。先创建运行区，再把 Codex 生成并检查过的三张图登记进去；示例命令中的图片路径要替换为本机真实文件。

```bash
python3 scripts/pipeline.py init --story examples/umbrella/story.json --run runs/umbrella
python3 scripts/pipeline.py status --run runs/umbrella

python3 scripts/pipeline.py image --run runs/umbrella --shot s1 --file /absolute/generated-s1.png
python3 scripts/pipeline.py image --run runs/umbrella --shot s2 --file /absolute/generated-s2.png
python3 scripts/pipeline.py image --run runs/umbrella --shot s3 --file /absolute/generated-s3.png

python3 scripts/pipeline.py estimate --run runs/umbrella
python3 scripts/pipeline.py generate --run runs/umbrella --env-file /private/path.env --budget-cny 10
```

环境文件使用仓库外的私有文件，或已被 Git 忽略的本地 `.env`；可按 `.env.example` 填写。`/private/path.env` 是路径示意，不能直接使用。密钥不进入 Git、运行日志或上传包。先看估算再提交；`--budget-cny 10` 是此运行的估算费用上限，不代表固定消耗 10 元，也不能代替服务商账户的扣费限制。提交前核对当前官方价格。

`generate` 每次提交尚未提交的镜头，并执行一次轮询。退出码 `75` 表示任务仍在处理中；再次执行同一条命令会续跑已有任务。已完成的镜头复用，结果不明的提交先核实，避免重复计费。平台核查到对应任务后，可按 [恢复说明](references/minimax-api.md)用 `reconcile` 绑定同一镜头，不重提生成。当前流水线仅接受中国区端点，以匹配人民币预算。

镜头全部真实生成并完成媒体检查后：

```bash
python3 scripts/pipeline.py assemble --run runs/umbrella
```

Codex 接着实际查看成片、听取台词与声音，核对角色连续性、字幕与结尾。把本次真实观察写入 `review`，再生成交接包；下面的检查记录是待替换内容，不能直接复制为“已通过”。这一步由实际检查过成片的 Codex 执行，不是新增用户审批：

```bash
python3 scripts/pipeline.py review --run runs/umbrella --notes "本次实际画面、台词和声音检查结果"
python3 scripts/pipeline.py upload-package --run runs/umbrella
python3 scripts/pipeline.py status --run runs/umbrella
```

本地合成输出 720×1280、30 fps 的 H.264／AAC 视频，附字幕文件和封面；有原始音轨时保留，无音轨时补静音以保证合成兼容。文件带 AAC 音轨不代表已经有配音，声音仍需实检。缺少中文字库时将 `DAILY_JOKES_FONT` 指向本地可用的中文字库文件。

没有视频密钥时仍可检查分镜和叙事：

```bash
python3 scripts/pipeline.py preview --run runs/umbrella --voiceover
```

macOS 的 `--voiceover` 用本地中文系统音色生成旁白和角色台词，不需要 API Key。每镜先完整合成台词，再安排停顿；超出时长时只允许小幅提速，仍放不下就报错，不能裁掉结尾。文案默认从字幕中识别“女士：／她：”等说话者，也可在镜头中通过 `speech: [{"speaker": "narrator", "text": "旁白"}, {"speaker": "woman", "text": "台词"}]` 明确设置。原静音版本保留，配音版输出到 `preview-voiceover/preview_voiceover.mp4`。它是系统合成配音预演，不是演员级配音。

其他系统可省略 `--voiceover` 生成静音预演。`preview` 是图片预演，不调用视频模型，不算真实 AI 视频。`upload-package` 只接受已验证的真实 AI 成片，生成视频、封面、文案与清单供后台接手；**交接包不等于已上传、已保存草稿或已发布**。

本版不创建定时任务。将来接入视频号需要目标账号的有效登录与管理／运营权限；后台若要求扫码或手机确认，需由账号持有人完成。公众号素材／草稿 API 和微信小店视频 API 都不能代替普通视频号动态发布。[官方公开视频号能力目录](https://developers.weixin.qq.com/doc/channels/api/channels/)

## 文字与漫画

支持按技能名注册斜杠命令的宿主，安装后使用 `/jokes`。首次无配置时，裸命令、“运行一下”“现在来一组”及“直接来一组”均先进入偏好设置；已有完整配置时直接生成。明确说“别问／跳过配置／先用默认值”才跳过本次问询。需要补项时，优先实际调用宿主当前可用且适用的原生表单／选择工具；按实际问题数量、单选／多选及自由输入能力组织，不固定四问。不可用或用户偏好文字时再用文字问询。其他 AI 可读取 `SKILL.md`，识别 `/jokes` 文本并执行同一流程。

Codex 官方明确支持 `$jokes` 或 `/skills` 选择技能；Skill 中的触发文本不会自行注册一个新的原生 `/jokes` 命令。Codex 用户可将下面示例的前缀换成 `$jokes`。复制指令也不会增加搜索、存储或推送工具。[调用方式依据](https://learn.chatgpt.com/docs/build-skills)

所有请求示例均为虚构、去标识化数据：

```text
/jokes

/jokes 设置，先不生成。

/jokes 别问，直接来一组。

/jokes 来五个生活和科技笑话，温和，避开疾病，不加入自嘲。

/jokes 来一组，加点最近流行的梗。

/jokes 不要热梗，来五条。

/jokes 设置，以后用漫画输出，每个笑话一张，先不生成。

/jokes 生成笑话。

/jokes 把刚才第 2 个画成漫画。

/jokes 这次文字加漫画，每则一张。

/jokes 我带了空购物袋去买菜，这件事仅本次可温和调侃，不保存。现在来一组。
```

用户补齐偏好后，若原请求要生成，就接着执行；若原请求只设置，Skill 不附赠笑话。输出可选文字、漫画、文字＋漫画；未选默认文字。漫画按每则一张独立成品展示，新组五则对应五张，已指定的一则只转一张。默认粗黑线、网点与明亮 1980 年代配色的周日彩色报纸连环漫画，按故事需要分格。普通“生成笑话”沿用已确认形式，临时转换不修改长期偏好。需宿主实际有生图能力，提示词不算已生成漫画。网络素材保留对应的必要来源引用。联网工具可用且获准时必须真实调用；尚未尝试不算失败，无联网工具和真实搜索失败分别说明。

## 文件

```text
jokes/
├── SKILL.md
├── requirements.txt
├── scripts/
│   ├── pipeline.py
│   ├── minimax_video.py
│   ├── media.py
│   ├── narration.py
│   └── package_skill.py
├── examples/
│   └── umbrella/
│       └── story.json
├── references/
│   ├── humor-rules.md
│   ├── onboarding-and-state.md
│   ├── comic-production.md
│   ├── video-workflow.md
│   └── minimax-api.md
└── tests/
    └── acceptance.md
```

上面展示主要入口；以源码实际文件为准。`runs/` 中保存本地运行状态和产物，不纳入仓库。旧 v1.1.0 的五文件安装包结构不适用于当前视频源码。

本地打包：`python3 scripts/package_skill.py --output dist/jokes.zip`。压缩包使用显式文件清单，包含可执行脚本、参考规则和示例，不包含 `.env`、密钥、运行产物或登录态。本版通过本地离线测试验证，暂未配置 GitHub Actions；测试不会访问真实视频 API 或上传视频号。

## 核心规则

- 区分题材、呈现形式和主导喜剧结构；文字／漫画新组五种不同机制是硬要求，七天轮换是软目标。视频按具体故事制作，不强制五则。
- 默认择优加入 1—2 条近期热梗笑话，证据或质量不足可为 0 条；用户可调整比例。按调用当天检索，优先近 7 天，必要时扩到 30 天，区分新梗与老梗翻红。热梗计入五条，仍需独立包袱、不同机制和来源引用；不维护永久“最新梗表”。
- 查重比较目标、行动、误导预期和揭底关系，区分核心包袱复用、同一母题过密与仅题材相同。
- 自嘲默认关闭，只使用明确授权的具体经历；不自动翻阅私事。一次性使用、未来使用、保存和对外发送分别判断。
- 定时需要真实执行与送达工具、明确时区及用户订阅授权。保存发送时间不代表任务已经创建。
- 只把实际展示或发送的内容记录为已送达，按授权保留最小七天查重信息；不把草稿或失败操作记为成功。
- 每位用户的数据与设置独立，Skill 包不包含任何人的真实偏好、经历或历史记录。

## 验证范围

视频验收分别检查真实来源、独立图片、第三方生成任务与可播放镜头、本地成片、上传包和后台记录。`review` 将实际观察记录与成片指纹绑定，不代表程序能自动判断画面或台词正确；上传包要求这份记录。图片预演、模拟服务响应、单次 HTTP 成功都不能证明整个流程跑通。当前实跑结果与缺口见 [验证记录](tests/verification.md)。

旧文字／漫画版本的历史检查包括 frontmatter、相对引用、18 个结构 ID、64 项验收规格必要字段、旧五文件封装及部分独立路由模拟。这些是旧版本检查记录，不是当前视频链路的通过报告；[验收场景](tests/acceptance.md)也不等于全部宿主执行通过。
