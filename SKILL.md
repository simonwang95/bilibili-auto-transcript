---
name: bilibili-auto-transcript
version: "5.1.0"
description: "B站视频转录+收藏夹扫描+本地文件转录。双引擎ASR（Qwen3-ASR / Whisper MLX），三级降级（CC→AI→ASR），LLM摘要+思维导图+校对。"
homepage: https://github.com/simonwang95/bilibili-auto-transcript
metadata:
  {
    "openclaw":
      {
        "emoji": "📼",
        "requires": { "bins": ["yt-dlp", "ffmpeg", "curl"] },
        "install":
          [
            {
              "id": "deps",
              "kind": "shell",
              "command": "cd {{SKILL_DIR}} && cp -n env.example env.local 2>/dev/null; conda activate course-whisper 2>/dev/null && pip install qwen-asr requests torch 2>/dev/null; echo '请编辑 env.local 填入你的配置'",
              "label": "初始化配置 & 安装依赖",
            },
          ],
      },
  }
---

# 📼 Bilibili 视频转录 & 收藏夹自动扫描

**三模式技能** — 支持 B站单视频、收藏夹批量、本地文件目录转录。双引擎 ASR（Qwen3-ASR / Whisper MLX），LLM 三阶段后处理（摘要+思维导图+校对）。

## 快速开始

```bash
# 1. 初始化配置
cp env.example env.local
# 编辑 env.local，填入 FAV_MEDIA_ID、LLM 配置等

# 2. 安装依赖
conda activate course-whisper
pip install qwen-asr requests torch        # Qwen3 引擎
pip install mlx-whisper                     # Whisper 引擎（Apple Silicon）

# 3. 确认系统依赖
yt-dlp --version && ffmpeg -version
```

---

## 模式一：B站收藏夹转录

定时检查 B站收藏夹，发现新视频后自动完成「转录 → AI 后处理 → 报告」全流程。

```bash
python scripts/batch_transcribe.py
```

**三级降级转录策略：**

| 优先级 | 来源 | 准确率 | 速度 |
|:------:|:----:|:------:|:----:|
| 1 | 人工 CC 字幕（zh-CN, en, ja 等） | ~100% | 秒出 |
| 2 | B站 AI 字幕（ai-zh, ai-en 等 9 种语言） | 85-90% | 秒出 |
| 3 | Qwen3-ASR 本地转录（1.7B / 0.6B） | 93-96% CER | 分钟级 |

支持断点续传（avid 去重）、自动重试、CSV 报告。输出 Markdown 文件，按视频发布日期分目录（`bilibili/YYYY-MM/`）。

**设置 `SUMMARY_API_KEY` 后自动执行三阶段 LLM 后处理：**
1. **结构化摘要** — 核心观点 + 主要论点 + 关键结论
2. **思维导图** — 缩进 Markdown 列表格式
3. **AI 校对** — 修正 ASR 同音错别字 + 断句优化 + 领域术语检查（金融/计算机/医学/法律/工程）

---

## 模式二：本地文件转录

给定本地目录，自动扫描视频/音频文件，用 ASR 引擎语音转文字，输出 Markdown 文件。

```bash
# 基本用法
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/

# 含 LLM 后处理
python scripts/batch_transcribe.py --local-dir /path/to/videos/
```

**支持格式：** mp4, mkv, avi, mov, webm, flv, wmv, ts（视频）；mp3, m4a, wav, flac, ogg, opus, aac（音频）

**流程：** 扫描目录 → 视频提取音轨 → ffmpeg 转 16kHz WAV → ASR 转录 → LLM 后处理。结果保存到 `bilibili/local/`。

---

## 模式三：手动转录单个 B站视频

```bash
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"
```

---

## ASR 引擎

通过 `env.local` 中的 `ASR_ENGINE` 切换：

| 引擎 | 配置值 | 中文质量 | 适用平台 | 依赖 |
|:----:|:------:|:--------:|:--------:|:----:|
| Qwen3-ASR | `qwen3` | CER ~3.8% (1.7B) | CUDA / MPS / CPU | qwen-asr, torch |
| Whisper v3 Turbo | `whisper` | 良好 | Apple Silicon (MLX) | mlx-whisper |

**Qwen3-ASR 智能模型选择：**

| 条件 | 模型 |
|:----:|:----:|
| NVIDIA/AMD GPU | Qwen3-ASR-1.7B |
| Apple Silicon (MPS) | Qwen3-ASR-1.7B |
| CPU / FORCE_ASR_CPU | Qwen3-ASR-0.6B |

使用本地模型时设置 `ASR_LOCAL_MODEL` 指向模型目录即可跳过下载。

```bash
# env.local 中
ASR_ENGINE="whisper"
ASR_LOCAL_MODEL="/path/to/mlx-community/whisper-large-v3-turbo"
FORCE_ASR="true"   # 跳过 B站字幕检测，强制用本地 ASR
```

---

## 配置

所有配置集中在 `env.local`（参考 `env.example` 创建）。核心配置项：

| 配置 | 说明 |
|------|------|
| `FAV_MEDIA_ID` | B站收藏夹 ID |
| `ASR_ENGINE` | `qwen3` 或 `whisper` |
| `ASR_LOCAL_MODEL` | 本地模型路径，留空自动下载 |
| `FORCE_ASR` | `true` 跳过 B站字幕，直接本地转录 |
| `SUMMARY_API_KEY` | LLM API Key，留空跳过 LLM 后处理 |
| `SUMMARY_API_URL` | LLM 端点（兼容 OpenAI / LM Studio / Ollama） |
| `SUMMARY_MODEL` | 模型名称 |
| `PROOFREAD_DOMAINS` | 校对领域，逗号分隔 |
| `LLM_TIMEOUT` | LLM 读取超时（秒），默认 600 |

完整配置说明见 [docs/config.md](docs/config.md)。

---

## 项目结构

```
bilibili-auto-transcript/
├── SKILL.md                     # 本文件
├── README.md
├── env.example                  # 配置模板（可提交）
├── env.local                    # 本地配置（不提交）
├── .gitignore
├── docs/                        # 项目文档
│   ├── index.md
│   ├── architecture.md
│   ├── scripts.md
│   ├── api.md
│   └── config.md
├── scripts/
│   ├── bilibili_transcript.sh   # 转录引擎 v5.1
│   ├── bilibili_scanner.py      # 收藏夹扫描 v1.2
│   ├── qwen3_transcribe.py      # Qwen3-ASR v1.3
│   ├── whisper_transcribe.py    # Whisper MLX v1.0
│   └── batch_transcribe.py      # 批量调度 v3.0
├── cache/audio/                 # 音频缓存
└── models/                      # ASR 模型权重
```

## 依赖

| 工具 | 用途 | 必需 |
|------|------|:----:|
| yt-dlp | 视频/字幕/音频下载 | ✅ |
| ffmpeg | 音频格式转换 | ✅ |
| qwen-asr | Qwen3-ASR 引擎 | 二选一 |
| mlx-whisper | Whisper MLX 引擎 | 二选一 |
| torch | Qwen3-ASR 推理后端 | Qwen3 需要 |
| requests | HTTP 请求（B站 API / LLM） | ✅ |
| opencc | 繁体转简体 | ❌ |

## 输出格式

Markdown 文件，包含五个区域：

```markdown
# 视频标题
> **链接**：...  **作者**：...  **转录来源**：...

---

## 视频摘要
（LLM 生成的结构化摘要）

---

## 思维导图
（LLM 生成的缩进列表）

---

## 完整原文
（转录文本）

---

## AI校对
（LLM 校对后的可读版本）
```

## 注意事项

- B站 AI 字幕需要浏览器 Cookie（macOS 用 Chrome/Safari，Linux 用 chromium）
- 私有收藏夹需设置 `BILI_COOKIE_FILE` 或改为公开
- Qwen3-ASR 首次运行从 HuggingFace 下载模型（1.7B ~5GB，0.6B ~2GB）
- Apple Silicon 上 Qwen3-ASR MPS 可能内存超限，设置 `FORCE_ASR_CPU=true` 或换用 Whisper 引擎
- 本地文件模式不走 B站 API，不需要 Cookie，结果保存到 `local/` 子目录
- 转录只输出文件，索引由 knowledge-rag 或其他工具负责

---

## 📦 开源

- **GitHub**：[github.com/simonwang95/bilibili-auto-transcript](https://github.com/simonwang95/bilibili-auto-transcript)
