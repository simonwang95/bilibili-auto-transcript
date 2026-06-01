# 📼 Bilibili Auto Transcript

**B站视频自动转录 & 收藏夹扫描技能**

三级降级策略：CC字幕 → B站AI字幕 → Whisper 语音转文字，自动获取 B站视频的文字内容。

## 功能

- **三级字幕降级**：人工CC字幕 → AI字幕(9种语言) → Whisper本地转录，逐级自动降级
- **智能模型选择**：根据视频时长和 GPU 可用性自动选择 Whisper 模型（tiny/base/medium）
- **收藏夹扫描**：分页获取收藏夹所有视频，去重、断点续传
- **批量转录**：自动遍历收藏夹新视频，支持重试、报告生成
- **AI摘要**（可选）：设置 `OPENAI_API_KEY` 后自动生成结构化视频摘要
- **目录组织**：按视频发布年月自动分目录存储

## 快速开始

```bash
# 手动转录单个视频
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"

# 批量转录收藏夹所有新视频
python3 scripts/batch_transcribe.py
```

## 依赖

- yt-dlp — 视频/字幕下载
- ffmpeg — 音频处理
- openai-whisper — 语音转文字
- opencc — 繁转简（可选）
- chromium-browser — Cookie支持（B站AI字幕）

## 配置

1. 编辑 `scripts/bilibili_scanner.py`，设置 `FAV_MEDIA_ID` 为你的B站收藏夹ID
2. 用 chromium-browser 登录 bilibili.com 获取 Cookie
3. （可选）设置 `OPENAI_API_KEY` 环境变量开启自动摘要

## 项目结构

```
bilibili-auto-transcript/
├── SKILL.md                    # Skill 元数据
├── scripts/
│   ├── bilibili_scanner.py     # 收藏夹扫描
│   ├── bilibili_transcript.sh  # 核心转录引擎
│   └── batch_transcribe.py     # 批量转录调度
└── references/
    ├── architecture.md         # 架构说明
    └── bilibili-fav-api.md     # B站API参考
```

## 许可

MIT
