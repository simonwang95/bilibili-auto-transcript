# Bilibili Auto Transcript — 项目文档

**B站视频自动转录与收藏夹扫描技能** — 三级字幕降级策略（CC 字幕 → B站 AI 字幕 → Qwen3-ASR），支持 B站在线视频和本地文件。本地模式支持 Qwen3-ASR 和 Whisper 双引擎。

---

## 文档导航

| 文档 | 内容 |
|------|------|
| [架构设计](architecture.md) | 系统整体架构、三级降级转录数据流、设计原则 |
| [脚本详解](scripts.md) | 五个核心脚本的详细分析 |
| [B站 API 参考](api.md) | B站收藏夹 API 端点的参数、响应结构、认证方式 |
| [配置指南](config.md) | env.local 配置项详解 |

---

## 项目概览

```
bilibili-auto-transcript/
├── SKILL.md                     # Skill 元数据
├── README.md                    # 项目入口
├── env.local                    # 🔧 本地环境配置（不提交git）
├── .gitignore
├── docs/                        # 📖 项目文档
│   ├── index.md
│   ├── architecture.md
│   ├── scripts.md
│   ├── api.md
│   └── config.md
├── references/                  # 原始参考文档
├── scripts/                     # 核心脚本
│   ├── bilibili_transcript.sh   # 转录引擎 v5.1
│   ├── bilibili_scanner.py      # 收藏夹扫描器 v1.2
│   ├── qwen3_transcribe.py      # Qwen3-ASR v1.3
│   ├── whisper_transcribe.py    # Whisper (MLX) v1.0
│   ├── batch_transcribe.py      # 批量调度器 v3.0
│   ├── organize_categories.py   # 内容分类整理
│   └── build_epub.py            # EPUB 电子书导出
├── cache/audio/                 # 音频缓存（不提交）
└── models/                      # ASR 模型权重（不提交）
```

## 核心能力

- **三级字幕降级**（B站模式）：CC 字幕（100%）→ AI 字幕（85-90%）→ 本地 ASR
- **双引擎 ASR**：Qwen3-ASR（中文 CER ~3.8%）或 Whisper large-v3-turbo（MLX 加速，Apple Silicon 原生优化）
- **本地文件转录**：视频自动提取音轨 → ffmpeg 转 16kHz WAV → ASR 转录 → Markdown 输出
- **强制 ASR 模式**：`FORCE_ASR=true` 跳过所有 B站字幕检测，直接本地转录
- **LLM 三阶段后处理**：结构化摘要 + 思维导图 + AI 校对（领域术语检查）
- **收藏夹全量扫描**：自动分页、avid 去重、断点续传、CSV 报告
- **所有配置集中化**：`env.local` 统一管理路径、模型、LLM、校对领域

## 快速开始

### 前置步骤

```bash
conda activate course-whisper

# Qwen3-ASR 依赖
pip install qwen-asr requests torch

# Whisper (MLX) 依赖（Apple Silicon 推荐）
pip install mlx-whisper

# 系统依赖
yt-dlp --version   # 必需
ffmpeg -version    # 必需
```

### 场景 A：B站收藏夹转录

三级降级：CC 字幕 → AI 字幕 → ASR 本地转录。结果按当前 `YYYY-MM/` 分目录，文件名保留视频发布时间。

```bash
# 编辑 env.local: 设置 FAV_MEDIA_ID、LLM 配置
python scripts/batch_transcribe.py
```

### 场景 B：本地文件转录

给定目录，扫描所有视频/音频，用本地 ASR 转文字。结果保存在 `bilibili/local/`。

```bash
python scripts/batch_transcribe.py --local-dir "/path/to/videos/"
```

### 常用 env.local 配置

```bash
# ASR 引擎和模型
ASR_ENGINE="whisper"                                          # qwen3 | whisper
ASR_LOCAL_MODEL="/Users/wyq/.lmstudio/models/mlx-community/whisper-large-v3-turbo"

# 强制本地转录（跳过 B站字幕）
FORCE_ASR="true"

# LLM 摘要（LM Studio 示例）
SUMMARY_API_KEY="lm-studio"
SUMMARY_API_URL="http://127.0.0.1:1234/v1"
SUMMARY_MODEL="qwen3.6-27b-ud-mlx"
SUMMARY_MAX_TOKENS="16000"
LLM_TIMEOUT="600"
LLM_MAX_RETRIES="2"
LLM_RETRY_DELAY="3"
COOLDOWN_DELAY="30"

# 校对领域 + 可选对话检测
PROOFREAD_DOMAINS="finance,computer"
ENABLE_DIALOGUE_DETECTION="false"
# true 时 AI 校对前检测对话/访谈，对话内容按语义区分说话角色
```

### 脚本速查

| 需求 | 命令 |
|------|------|
| 转录 B站收藏夹 | `python scripts/batch_transcribe.py` |
| 转录本地目录 | `python scripts/batch_transcribe.py --local-dir <目录>` |
| 递归转录本地目录 | `python scripts/batch_transcribe.py --local-dir <目录> --recursive` |
| 补齐 AI 后处理 | `python scripts/batch_transcribe.py --summary-only [文件或目录]` |
| 单个 B站视频 | `bash scripts/bilibili_transcript.sh "<URL>"` |
| 只扫描不转录 | `python scripts/bilibili_scanner.py` |
| 分类整理文件 | `python scripts/organize_categories.py` |
| 预览分类 | `python scripts/organize_categories.py --dry-run` |
| 导出 EPUB（合并） | `python scripts/build_epub.py` |
| 导出指定目录 EPUB | `python scripts/build_epub.py --input-dir <根目录>` |

## 外部依赖

| 工具 | 用途 | 必需 |
|------|------|------|
| yt-dlp | 视频信息获取、字幕/音频下载 | ✅ |
| ffmpeg | 音频格式转换 | ✅ |
| qwen-asr | Qwen3-ASR 引擎 | 二选一 |
| mlx-whisper | Whisper MLX 引擎（Apple Silicon） | 二选一 |
| requests | HTTP 请求 | ✅ |
| torch | Qwen3-ASR 推理后端 | Qwen3 引擎需要 |
| opencc | 繁体转简体 | ❌ 可选 |
