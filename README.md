# 📼 Bilibili Auto Transcript

B站视频转录 + 收藏夹扫描 + 本地文件转录。双引擎 ASR（Qwen3-ASR / Whisper MLX），LLM 三阶段后处理。

## 功能

- **三模式转录**：B站单视频、收藏夹批量、本地文件目录
- **三级字幕降级**（B站）：CC 字幕 → AI 字幕 → ASR 本地转录
- **本地字幕优先**：本地媒体在 `FORCE_ASR=false` 时优先导入同名 `.srt`
- **双引擎 ASR**：Qwen3-ASR（中文 CER ~3.8%）或 Whisper v3 Turbo（MLX 加速）
- **LLM 后处理**：结构化摘要 + 思维导图 + AI 校对（领域术语检查）
- **后处理中断恢复**：`--summary-only` 可为已有 Markdown 补齐摘要/导图/校对，无需重新 ASR
- **断点续传**：avid 去重，中断后自动跳过已处理视频
- **Markdown 输出**：按发布日期分目录（`YYYY-MM/`），本地文件保存到 `local/`
- **统一配置**：所有参数集中在 `env.local`，无需改代码

## 快速开始

```bash
# 1. 初始化配置
cp env.example env.local
# 编辑 env.local：填入 FAV_MEDIA_ID、LLM 配置等

# 2. 安装依赖
conda activate course-whisper
pip install qwen-asr requests torch   # Qwen3 引擎
pip install mlx-whisper               # Whisper 引擎（Apple Silicon）

# 3. 确认系统依赖
yt-dlp --version && ffmpeg -version

# 4. 运行
python scripts/batch_transcribe.py                     # B站收藏夹
python scripts/batch_transcribe.py --local-dir ./videos/  # 本地目录
python scripts/batch_transcribe.py --local-dir ./videos/ --recursive  # 本地目录（含子目录）
python scripts/batch_transcribe.py --summary-only      # 仅补齐已有 Markdown 的 AI 后处理
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"  # 单视频
```

## 配置

编辑 `env.local`（参考 `env.example`），核心配置：

```bash
FAV_MEDIA_ID="your_id"                                        # B站收藏夹 ID
ASR_ENGINE="whisper"                                          # qwen3 | whisper
ASR_LOCAL_MODEL="/path/to/whisper-large-v3-turbo"             # 本地模型路径
FORCE_ASR="true"                                              # 跳过 B站字幕，直接本地转录
SUMMARY_API_KEY="lm-studio"                                   # LLM API Key
SUMMARY_API_URL="http://127.0.0.1:1234/v1"                    # LM Studio / Ollama
SUMMARY_MODEL="qwen3.6-27b-ud-mlx"
LLM_MAX_RETRIES="2"                                           # LLM 临时失败重试次数
COOLDOWN_DELAY="30"                                           # 视频间散热等待（秒）
PROOFREAD_DOMAINS="finance,computer"                          # 校对领域（支持对话检测）
```

完整配置说明见 [docs/config.md](docs/config.md)。

## 输出示例

```markdown
# 视频标题
> **链接**：...  **作者**：...  **转录来源**：Whisper-v3-turbo（MLX加速）

## 视频摘要
（LLM 生成：核心观点 + 主要论点 + 关键结论）

## 思维导图
（LLM 生成：缩进列表层次结构）

## AI校对
（LLM 校对：修正错别字 + 断句优化 + 术语检查）

<details>
<summary>📄 完整原文</summary>
（转录全文，默认折叠）
</details>
```

## 项目结构

```
bilibili-auto-transcript/
├── env.example                  # 配置模板
├── env.local                    # 本地配置（不提交）
├── docs/                        # 项目文档
├── scripts/
│   ├── bilibili_transcript.sh   # 转录引擎
│   ├── bilibili_scanner.py      # 收藏夹扫描
│   ├── qwen3_transcribe.py      # Qwen3-ASR
│   ├── whisper_transcribe.py    # Whisper MLX
│   ├── batch_transcribe.py      # 批量调度
│   ├── organize_categories.py   # 内容分类
│   └── build_epub.py            # EPUB 导出
├── cache/audio/                 # 音频缓存
└── models/                      # ASR 模型权重
```

## 依赖

| 工具 | 用途 |
|------|------|
| yt-dlp | 视频/字幕/音频下载 |
| ffmpeg | 音频格式转换 |
| qwen-asr / mlx-whisper | ASR 引擎（二选一） |
| torch | Qwen3 推理后端 |
| requests | HTTP 请求 |
| opencc | 繁转简（可选） |

## 许可

MIT
