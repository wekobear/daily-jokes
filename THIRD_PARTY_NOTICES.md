# 第三方致谢与许可证

## Archify

感谢 [tt-a1i/archify](https://github.com/tt-a1i/archify) 提供从结构化流程到可交互 HTML 的开源能力。本项目的流程展示由 Archify 实际生成、校验并在浏览器检查，不是手写图后冒称使用了该 Skill。

- 使用版本：Skill 2.17。
- 固定源码提交：`6db72a9aea3d0f67a6a034e41f8a5491476a11c1`。
- [对应源码](https://github.com/tt-a1i/archify/tree/6db72a9aea3d0f67a6a034e41f8a5491476a11c1)。
- 源文件：`docs/workflow.json`，类型为 workflow，schema v2。
- 交付物：`docs/workflow.html` 及说明文档中的静态预览。
- 未将 Archify 全部代码或个人环境配置打入本 Skill；生成的 HTML 包含其 viewer 代码，保留下方 MIT 声明。
- 图中未使用第三方品牌图标。HTML 内嵌 JetBrains Mono 字体子集并携带 SIL Open Font License 1.1 声明；中文使用系统字体回退。

在取得上述固定版本源码后，从它的 `archify/` 目录运行，替换输入输出为本项目文件的实际路径：

```bash
node bin/archify.mjs validate workflow <workflow.json> --quality showcase --json
node bin/archify.mjs deliver workflow <workflow.json> <workflow.html> --quality showcase --json
node bin/archify.mjs visual-check <workflow.html> --json
```

本项目未修改生成的 HTML；静态预览来自相同 HTML 的浏览器截图。验证回执摘要见 [流程展示验收](docs/workflow-verification.md)。

### Archify MIT License

MIT License

Copyright (c) 2026 tt-a1i (Archify)
Copyright (c) 2025 Cocoon AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## A-Joke

感谢 [Licoy/A-Joke](https://github.com/Licoy/A-Joke) 提供可读取的历史笑话整理库。固定来源提交为 `9d87e1c8f3fe9123c54fcc818e7fbd0255fd14a4`，上游 MIT 许可证署名为 Copyright (c) 2018 憧憬Licoy。我们的导入器为本项目自写，不执行或复制上游脚本；候选正文仅按需下载到使用者的 runs/，不装入共享 Skill。

[上游许可证](https://github.com/Licoy/A-Joke/blob/9d87e1c8f3fe9123c54fcc818e7fbd0255fd14a4/LICENSE)与[README 来源说明](https://github.com/Licoy/A-Joke/blob/9d87e1c8f3fe9123c54fcc818e7fbd0255fd14a4/README.md)需一并理解：网络整理身份不证明每则内容的原作者或使用权。采用候选时保留条目出处，逐项判断，不宣称整库段子全部公版或原创。

《是，大臣》《是，首相》的名称及剧情资料用于识别与评论，相关权利归其权利人；本包不包含整集字幕、剧本或影视片段。教学讽刺对话为新写，不冒称原剧台词。

## 其他依赖

感谢 [FFmpeg](https://ffmpeg.org/)、[Pillow](https://python-pillow.org/) 与 [Python](https://www.python.org/) 的开发者和社区。它们各自保留上游许可证；本包不包含其可执行程序、系统音色或本机字体文件。具体 FFmpeg 构建及编码器的许可范围以使用者所安装版本为准。
