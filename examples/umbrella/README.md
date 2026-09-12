# 雨伞误会：从分镜到配音预演

早上坐电车，他顺手拿起旁边女士的伞。女士提醒：“那是我的！”他赶紧道歉。下班后，他取回家里送修的八把伞，回程又碰见那位女士。她扫了一眼：“今天收获不错啊。”

笑点是误导反转：观众知道八把伞来自修伞铺，女士却把它们与早上的误拿联系起来。中间镜头必须交代伞的真实来源，否则结尾会变成没有依据的指责。

[静音预演](preview-silent.mp4) · [中文配音预演](preview-voiceover.mp4) · [完整输入和提示词](story.json)

[![视频封面](cover.jpg)](preview-voiceover.mp4)

## 三个节拍

### 1. 建立误会

![早上误拿伞](images/s1.png)

早上，他顺手拿起旁边的伞。女士：“那是我的！”

### 2. 告诉观众真相

![取回送修的伞](images/s2.png)

下班后，他取回家里送修的八把伞。

### 3. 让另一位角色误解

![再次相遇](images/s3.png)

回程，又遇见早上那位女士。她：“今天收获不错啊。”

## 如何复刻

初始化 `story.json`，逐镜登记 `images/s1.png` 至 `s3.png`，再执行视频流程中的 `preview`。macOS 使用 `preview --voiceover` 得到系统配音预演。详见 [新手教程](../../docs/getting-started.md)和 [命令说明](../../references/video-workflow.md)。

这两份视频只验证本地叙事预演，不是 H3 人物动作生成。静音轨存在不代表有配音；不要将预演提交为真实 API 成片。

来源：[Project Gutenberg《Jokes For All Occasions》ABSENTMINDEDNESS](https://www.gutenberg.org/cache/epub/21084/pg21084-images.html)，本案例为简短中文改编，分镜由 GPT 生成。
