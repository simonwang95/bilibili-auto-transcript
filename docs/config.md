# 配置指南

所有可配置项集中在项目根目录的 `env.local` 文件中。该文件不会被提交到 git。

---

## 配置文件格式

`env.local` 使用 Bash/Python 兼容的 `KEY="value"` 格式。Shell 脚本通过 `source` 加载，Python 脚本通过自定义解析器加载。

```bash
# 注释以 # 开头
KEY="value"
ANOTHER_KEY="another value"
```

---

## 配置项详解

### 收藏夹

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FAV_MEDIA_ID` | `""` （需设置） | B站收藏夹 ID，从 URL `?fid=` 后的数字获取 |
| `BILI_COOKIE_FILE` | `""` | 私有收藏夹需要。指向 Netscape 格式 Cookie 文件的路径。留空使用公开访问 |

关于公开 vs 私有收藏夹：公开收藏夹只需 `FAV_MEDIA_ID`；私有收藏夹需要同时设置 `BILI_COOKIE_FILE`。报「访问权限不足」说明收藏夹为私有。

### 路径配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `OUTPUT_DIR` | `"$HOME/workspace/knowledge/bilibili"` | 输出目录。B站模式按当前年月（`YYYY-MM/`）分子目录，本地文件保存到 `local/` 子目录 |
| `CACHE_DIR` | `"./cache/audio"` | 下载音频的临时缓存，脚本退出时自动清理 |
| `MODEL_CACHE_DIR` | `"./models"` | Qwen3-ASR 从 HuggingFace 下载时的缓存目录。Whisper 引擎不使用此配置 |
| `STATE_DIR` | `"$HOME/.openclaw/workspace/.auto-transcript-state"` | 已处理记录与 CSV 报告 |
| `EPUB_OUTPUT_DIR` | `"$OUTPUT_DIR/epub"` | EPUB 电子书输出目录 |

### Conda 环境

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CONDA_ENV` | `"course-whisper"` | 运行 Python 脚本的 conda 环境名。自动三级回退：conda → .venv → 系统 python3 |

依赖安装：

```bash
conda activate course-whisper

# Qwen3-ASR 引擎
pip install qwen-asr requests torch

# Whisper MLX 引擎（Apple Silicon 推荐）
pip install mlx-whisper
```

### 浏览器 Cookie

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BROWSER_TYPE` | `"chrome"` | macOS: chrome / chromium / edge / safari / firefox。Linux: chromium / firefox |

### ASR 引擎

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ASR_ENGINE` | `"qwen3"` | 语音转文字引擎：`qwen3`（中文 CER ~3.8%）或 `whisper`（MLX 加速，Apple Silicon 原生优化） |
| `ASR_LOCAL_MODEL` | `""` | 本地模型路径。相对路径以项目根目录为基准。Whisper 示例：`"/Users/wyq/.lmstudio/models/mlx-community/whisper-large-v3-turbo"` |
| `FORCE_ASR` | `"false"` | 设为 `true` 跳过字幕检测，强制用本地 ASR 转录。B站模式跳过 CC/AI 字幕；本地模式跳过同名 `.srt` 字幕 |
| `FORCE_ASR_CPU` | `"false"` | Qwen3-ASR 专用。Apple Silicon 上 MPS 可能内存超限（47GB），设为 `true` 强制 CPU 推理 |
| `ASR_LANGUAGE` | `""` | Whisper 转录语言。默认空字符串=自动检测，非中文内容保留原语言。纯中文视频可设为 `zh` 强制提高准确率（但会丢失英文等非中文内容） |
| `ASR_PROMPT` | `""` | Whisper 初始提示词。可填入课程领域、专有名词、缩写等，帮助转写稳定；仅 `ASR_ENGINE=whisper` 时生效 |
| `ASR_PROGRESS_INTERVAL` | `"30"` | Whisper 转录状态提示间隔（秒）。长音频转写时会定时打印已耗时、音频时长和实时倍率；设为 `0` 关闭 |

`ASR_ENGINE=whisper` 时自动忽略 `FORCE_ASR_CPU`（Whisper 走 MLX 不走 PyTorch MPS）。

### LLM 后处理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SUMMARY_API_KEY` | `""` | LLM API Key。留空跳过摘要/导图/校对三阶段 |
| `SUMMARY_API_URL` | `"https://api.openai.com/v1/chat/completions"` | LLM API 端点，自动补全 `/chat/completions` |
| `SUMMARY_MODEL` | `"gpt-4o-mini"` | 三阶段共用的模型名称 |
| `SUMMARY_MAX_TOKENS` | `"1024"` | 每次 LLM 调用的最大 token 数 |
| `LLM_TIMEOUT` | `"600"` | LLM API 读取超时（秒），默认 600 适用于本地模型长文本 |
| `LLM_MAX_RETRIES` | `"2"` | LLM 请求失败后的最大重试次数。默认最多请求 3 次（首次 + 2 次重试） |
| `LLM_RETRY_DELAY` | `"3"` | LLM 重试基础等待秒数，按 1x / 2x / 4x 指数退避 |
| `PROOFREAD_DOMAINS` | `""` | 校对时关注的专有领域，逗号分隔。可选：finance / computer / medical / legal / engineering。留空默认启用金融+计算机 |
| `ENABLE_DIALOGUE_DETECTION` | `"false"` | 是否在 AI 校对前额外调用一次 LLM 判断对话/访谈/多人讨论。设为 `true` 时，对话内容会尝试标注主持人/嘉宾/说话人角色 |

设置 `SUMMARY_API_KEY` 后，每个转录完成会自动执行：

1. **结构化摘要** — 核心观点 + 主要论点 + 关键结论
2. **思维导图** — 缩进 Markdown 列表格式
3. **AI 校对** — 默认执行常规校对（同音错别字 + 断句 + 标点 + 领域术语检查）。若 `ENABLE_DIALOGUE_DETECTION=true`，会先判断转录是否为对话/访谈类型；检测为对话时自动根据语义区分说话角色（标注为「主持人：」「嘉宾：」或「说话人A：」「说话人B：」）

三个阶段独立运行，一个失败不影响其他。LLM 请求会对超时、连接异常、HTTP 408/409/425/429、5xx、空响应或异常响应做重试；HTTP 400/401/403/404 等配置错误不重试，直接失败。

### 转录行为

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MAX_RETRIES` | `"2"` | 转录失败最大重试次数 |
| `BATCH_DELAY` | `"3"` | 视频完成后的短延迟（秒），防 B站风控 |
| `COOLDOWN_DELAY` | `"30"` | LLM 后处理冷却等待（秒），每次摘要/导图/校对完成后等待散热。Whisper/ASR 转录之间不等待 |
| `ENABLE_OPENCC` | `"true"` | 繁体转简体 |
| `INCLUDE_FULL_TEXT` | `"false"` | 是否在 Markdown 中展开完整原文。默认折叠为 `<details>`，设为 `true` 展开为 `## 完整原文` 章节 |

---

## 两种使用场景

### 场景 A：B站收藏夹

```bash
# env.local 核心配置
FAV_MEDIA_ID="3872645046"
SUMMARY_API_KEY="lm-studio"

# 启动
python scripts/batch_transcribe.py
```

流程：扫描收藏夹 → avid/bvid 双重去重（文本记录+磁盘文件）→ 三级降级转录（CC→AI→ASR）→ LLM 摘要/导图/校对（可选对话检测并标注角色）→ CSV 报告。结果按当前年月保存到 `bilibili/YYYY-MM/`。

### 场景 B：本地文件目录

```bash
# env.local 核心配置
ASR_ENGINE="whisper"
ASR_LOCAL_MODEL="/Users/wyq/.lmstudio/models/mlx-community/whisper-large-v3-turbo"
FORCE_ASR="true"

# 启动
python scripts/batch_transcribe.py --local-dir "/path/to/videos/"

# 如需递归扫描子目录
python scripts/batch_transcribe.py --local-dir "/path/to/videos/" --recursive
```

流程：扫描目录媒体文件 → 若 `FORCE_ASR=false` 且存在同目录同名 `.srt`，优先导入字幕（支持 `video.srt` 和 `video_*.srt` 语言后缀）→ 否则 ffmpeg 提取/转换音频 → ASR 转录 → LLM 摘要/导图/校对。默认只扫描目录第一层；加 `--recursive` 后递归扫描子目录。结果保存到 `bilibili/local/`。不涉及 B站 API，不走去重。

如果进程在 ASR 完成后、LLM 后处理完成前中断，不需要删除已生成的 Markdown。直接运行：

```bash
python scripts/batch_transcribe.py --summary-only
```

该命令默认扫描 `OUTPUT_DIR/local`，只补齐仍保留 `【AI待处理...】` 占位符的文件；也可以追加单个文件或目录路径。

### 场景对比

| | 场景 A：收藏夹 | 场景 B：本地文件夹 |
|---|---|---|
| 命令 | `python scripts/batch_transcribe.py` | `python scripts/batch_transcribe.py --local-dir <目录>`，递归扫描加 `--recursive` |
| 输入来源 | B站收藏夹 API | 本地文件系统 |
| 转录策略 | CC → AI → ASR 三级降级 | 直接 ASR |
| 输出目录 | `bilibili/YYYY-MM/` | `bilibili/local/` |
| 断点续传 | 是（avid 去重） | 否（每次全量） |
| CSV 报告 | 是 | 否 |
| 需要 Cookie | 是（AI 字幕） | 否 |
| 需要 FAV_MEDIA_ID | 是 | 否 |

---

## 优先级规则

命令行参数 > env.local > 脚本默认值。例如 `--output-dir /tmp/out` 覆盖 `env.local` 中的 `OUTPUT_DIR`；`build_epub.py --input-dir /path/to/root` 会覆盖 EPUB 读取的分类根目录。
