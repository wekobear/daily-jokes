# 流程图验收

本图使用 Archify 2.17 的 workflow v2 格式生成。以下数据绑定最终文件，不代表视频制作服务或发布平台的验收。

| 项目 | 结果 |
| --- | --- |
| diagram_type | workflow |
| output | docs/workflow.html |
| specification_sha256 | 6ac26dba59a377caef4afc6302a65bad11bffa17991cf3f7525fa87f5658bae4 |
| artifact_sha256 | 74e98dda282a18c044d0fd8267839837731d3833af9363061e4a32eaff2dc0f2 |
| specification_bytes | 3029 |
| artifact_bytes | 806949 |
| validation | 9/9 showcase，0 errors，0 warnings |
| browser_evidence | passed |
| visual_review | passed（检查了浅色大屏和深色笔记本截图） |
| correction_rounds | 0（v0.4.0 基于已验收布局更新标签） |

自动浏览器检查覆盖 1440×900、1600×1000、1920×1080、2048×1320，均无页面横向或纵向溢出；另捕获最小和最大尺寸的浅色、深色截图。视觉查看确认主线清楚、中文标签未截断，连线不穿过无关节点，用户手动上传与 Skill 的本地交付终点分开。

前版已经修正过长中文标签并紧凑化排版。本版将模型节点改为“第三方视频 API”，体现供应商通用流程，重新通过确定性和浏览器验证并检查浅色大屏、深色笔记本截图。生成 HTML 未作事后手改。静态预览 workflow.png 是本版最终浅色大屏截图的原样副本。

确定性验证、真实浏览器尺寸证据和视觉观察是三项独立结果。本轮未逐一操作 viewer 的搜索、焦点、透镜或导出菜单，因此不声称所有交互功能都经过人工测试。

完整原始浏览器回执含本机路径，仅保留在私有运行区，不进入公开 Skill。此摘要保留文件指纹与实际验证范围，方便接收者复核。重生成方法与开源致谢见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
