# 脚本详解

项目包含四个核心脚本，每个承担明确的职责。

---

## 一、bilibili_transcript.sh — 核心转录引擎

**版本**: v5.0  
**语言**: Bash  
**职责**: 对单个 B站视频执行三级降级转录，或对本地目录批量转录，输出 TXT 文件

### 调用方式

```bash
# 模式1: B站在线视频
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"

# 模式2: 本地目录批量转录（v5.0 新增）
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/

# 可选参数
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/ --output-dir /custom/output/
```

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `VIDEO_URL` 或 `--local-dir` | ✅ | — | B站链接或本地目录路径 |
| `--output-dir` | ❌ | env.local 中的 `OUTPUT_DIR` | 输出目录 |

### 配置来源

```
env.local (source 加载) → 脚本默认值
```

所有路径、conda 环境、浏览器类型均从 `env.local` 读取，命令行参数可覆盖。

### Python 运行方式（v5.0 变更）

不再硬编码 `.venv/bin/python3`，改为三级回退：

1. 检测 `conda` 是否可用且 `course-whisper` 环境存在 → `conda run -n course-whisper python3`
2. 检测 `.venv/bin/python3` 是否存在 → 使用虚拟环境
3. 以上均不可用 → 使用系统 `python3`

### 本地目录模式（v5.0 新增）

```
输入: /path/to/videos/ 目录
  ↓
find 扫描目录中的媒体文件（mp4, mkv, avi, mov, webm, flv, wmv, ts,
                             mp3, m4a, wav, flac, ogg, opus, aac）
  ↓
对每个文件:
  ├── 视频文件 → ffmpeg 提取音轨并转 16kHz WAV
  ├── 非标准 WAV → ffmpeg 重采样
  └── 标准 WAV → 直接输入
  ↓
调用 qwen3_transcribe.py
  ↓
生成 TXT 文件（标题=文件名，链接=file://路径）
```

### 执行步骤（B站在线模式，共 10 步）

1. **检测浏览器 Cookie** — 自动探测 WSL Chromium → Windows Edge → WSL Firefox 的 Cookie 路径，用 `yt-dlp --cookies-from-browser` 验证可用性
2. **获取视频元数据** — `yt-dlp --dump-json` 提取标题、作者、发布日期、时长、视频 ID
3. **检查字幕可用性** — `yt-dlp --list-subs` 列出所有可用字幕，分类为 CC 字幕和 AI 字幕
4. **第 1 级：CC 字幕下载** — `yt-dlp --write-subs --convert-subs srt` 下载人工字幕，SRT 格式
5. **第 2 级：AI 字幕下载** — `yt-dlp --write-auto-subs --convert-subs srt` 下载 AI 字幕
6. **第 2.5 级：AI 字幕兜底** — 直接尝试下载 ai-zh/en/ja，解决 `--list-subs` 漏报问题
7. **第 3 级：Qwen3-ASR 转录** — 下载音频 → ffmpeg 转 16kHz WAV → 调用 `qwen3_transcribe.py`
8. **繁体转简体** — 若 `opencc` 可用，自动转换
9. **按年月分目录** — 从发布日期提取年份和月份，创建子目录
10. **生成 TXT 文件** — 写入元信息头部 + 摘要占位符 + 完整原文

### 临时文件清理

脚本使用 `trap cleanup_temp EXIT` 确保退出时清理所有临时文件（SRT 字幕、音频文件、中间转录文件）。

### Cookie 检测逻辑

按优先级逐级尝试：
1. 用户指定的浏览器类型
2. WSL Chromium: `$HOME/snap/chromium/common/chromium`
3. Windows Edge: `C:/Users/{user}/AppData/Local/Microsoft/Edge/User Data`
4. WSL Firefox: `$HOME/snap/firefox/common/.mozilla/firefox`

每次检测用 `yt-dlp --list-subs` 实际验证 Cookie 是否可用（检查输出是否包含 "Extracting"）。

---

## 二、bilibili_scanner.py — 收藏夹扫描器

**版本**: v1.1  
**语言**: Python 3  
**职责**: 分页获取收藏夹全量视频，对比已处理记录，输出新增视频列表

### 调用方式

```bash
# conda 环境（自动检测）
python scripts/bilibili_scanner.py

# 或手动指定
conda run -n course-whisper python3 scripts/bilibili_scanner.py
```

无需命令行参数，所有配置通过 `env.local` 读取。

### 配置项（从 env.local 读取）

```python
FAV_MEDIA_ID = "3972051046"  # 从 env.local 读取，不再硬编码
STATE_DIR    = "~/.openclaw/workspace/.auto-transcript-state"
```

### 数据结构

**API 请求**:
```python
GET https://api.bilibili.com/x/v3/fav/resource/list?media_id={ID}&ps=20&pn={N}
Headers: {"User-Agent": "Mozilla/5.0 ... Chrome/120.0.0.0 ..."}
```

**内部使用字段**:
| 字段 | 来源 | 用途 |
|------|------|------|
| `id` | API `medias[].id` | avid，去重追踪 key |
| `bvid` | API `medias[].bvid` 或 `medias[].bv_id` | BV 号，构建转录 URL |
| `title` | API `medias[].title` | 视频标题，报告展示 |
| `duration` | API `medias[].duration` | 时长（秒），转换为 `X分Y秒` |
| `upper.name` | API `medias[].upper.name` | UP 主名称 |
| `pubtime` | API `medias[].pubtime` | 发布时间戳 |

### 错误处理

- **网络异常** (`requests.exceptions.RequestException`): 输出 `ERROR: 网络请求失败`，退出码 1
- **JSON 解析失败** (`ValueError`): 输出 `ERROR: API响应解析失败`，退出码 1
- **API 错误** (`code != 0`): 输出 `ERROR: B站API返回错误`，退出码 1
- **未设置收藏夹 ID**: 输出提示信息，退出码 1

---

## 三、qwen3_transcribe.py — Qwen3-ASR 转录辅助

**版本**: v1.2  
**语言**: Python 3  
**职责**: 自动检测计算设备并选择合适的 Qwen3-ASR 模型进行语音转文字

### 调用方式

```bash
python scripts/qwen3_transcribe.py \
  --audio <音频文件路径> \
  --output-file <输出文件路径> \
  [--device auto|cpu|cuda|mps] \
  [--model-cache-dir <模型缓存目录>]
```

| 参数 | 说明 |
|------|------|
| `--audio` | 输入音频文件路径（建议 16kHz 单声道 WAV） |
| `--output-file` | 输出文件路径 |
| `--device` | 设备选择，默认 `auto` |
| `--model-cache-dir` | **v1.2 新增** — 模型下载目录（优先级 > HF_HOME） |

### 模型缓存目录（v1.2 变更）

优先级：`--model-cache-dir` 参数 > `HF_HOME` 环境变量 > 默认 `~/.cache/huggingface`

上层脚本 `bilibili_transcript.sh` 会设置 `HF_HOME=$MODEL_CACHE_DIR`，因此模型会下载到 `env.local` 中配置的 `MODEL_CACHE_DIR`（默认 `./models/`）。

### 设备检测逻辑

```
import torch
  ↓ torch.cuda.is_available() → "cuda" (NVIDIA / AMD ROCm)
  ↓ torch.backends.mps.is_available() → "mps" (Apple Silicon M1-M4)
  ↓ 以上均不可用 → "cpu"
```

### 模型选择

| 检测到的设备 | 模型 | 中文 CER | 显存需求 |
|-------------|------|----------|---------|
| CUDA / MPS | `Qwen/Qwen3-ASR-1.7B` | ~3.8% | 4-6 GB (CUDA) / 3-4 GB (MPS) |
| CPU | `Qwen/Qwen3-ASR-0.6B` | ~5-7% | ~2 GB 内存 |

### 输出格式

输出文件恰好两行：
```
Qwen3-ASR-1.7B（CUDA加速）
（完整转录文本内容...）
```

第一行被 `bilibili_transcript.sh` 读取作为 `TRANSCRIPT_SOURCE`，写入 TXT 文件的元信息头部。

### 首次运行

首次使用时会从 HuggingFace 自动下载模型权重：
- 0.6B 模型：约 2 GB
- 1.7B 模型：约 5 GB

下载仅发生一次，后续使用直接从缓存加载。

---

## 四、batch_transcribe.py — 批量转录调度器

**版本**: v3.0  
**语言**: Python 3  
**职责**: 串联扫描和转录，提供断点续传、重试、进度预估、报告生成

### 调用方式

```bash
# B站收藏夹模式
python scripts/batch_transcribe.py

# 本地目录模式（v3.0 新增）
python scripts/batch_transcribe.py --local-dir /path/to/videos/
```

所有配置从 `env.local` 读取，无需命令行参数（除 `--local-dir`）。

### env.local 配置读取

```python
CONDA_ENV        # conda 环境名
MAX_RETRIES      # 最大重试次数
BATCH_DELAY      # 视频间延迟
SUMMARY_API_KEY  # LLM API Key
SUMMARY_API_URL  # LLM API 端点
SUMMARY_MODEL    # 摘要模型
SUMMARY_MAX_TOKENS  # 最大 token 数
```

### 本地目录模式（v3.0 新增）

调用 `bilibili_transcript.sh --local-dir` 实现。不涉及 B站 API、不维护已处理记录、不生成 CSV 报告（本地文件没有 avid 用于去重）。仅依次转录每个文件并可选生成摘要。

### 核心流程

```
scan_videos()
  → 调用 bilibili_scanner.py，解析 stdout 输出
  → 返回新视频列表 [{bvid, title, duration, upper, pubtime}, ...]

主循环 (for each pending video):
  transcribe_video(bvid, attempt, max_retries)
    → 调用 bilibili_transcript.sh
    → 解析 stdout 判断成功/失败/转录来源
    → Qwen3-ASR 失败不重试（模型加载耗时）
    → CC/AI 字幕失败重试最多 2 次
  save_processed(bvid)
    → 追加 avid 到 processed_videos.txt
  generate_summary(output_file)
    → 读取 TXT 文件，检查是否有占位符
    → 提取视频标题和转录文本（截取前 30,000 字符）
    → 调用 OpenAI API 生成结构化摘要
    → 替换 TXT 文件中的占位符

生成报告:
  → 写入 CSV (bvid, title, author, duration, source, output_file,
               content_hash, status, attempts)
  → 打印来源分布统计
  → 打印失败列表
```

### 摘要生成

当 `SUMMARY_API_KEY`（在 `env.local` 中）不为空时自动启用。模型、API URL、max_tokens 均可自由配置：

```python
SUMMARY_MODEL = "gpt-4o-mini"       # 或 "qwen2.5:7b"（Ollama 本地模型）
SUMMARY_API_URL = "https://api.openai.com/v1/chat/completions"
SUMMARY_MAX_TOKENS = 1024
```

System prompt 要求生成包含「核心观点、主要论点、关键结论」的结构化中文摘要。

### 内容哈希去重

`get_content_hash()` 对输出文件取 SHA-256 前 16 位，记录在 CSV 报告中，用于后续识别内容完全相同的重复转录。

### 进度预估算法

```
if success_count > 0:
    avg_time = total_elapsed / success_count
    eta = avg_time * remaining_count
```

---

## 脚本间依赖关系

```
batch_transcribe.py (v3.0)
  ├── --local-dir → bilibili_transcript.sh --local-dir（本地模式）
  └── 默认模式:
        ├── 调用 → bilibili_scanner.py（扫描收藏夹，从 env.local 读 FAV_MEDIA_ID）
        └── 调用 → bilibili_transcript.sh（转录每个视频）
                      ├── source env.local（所有路径和配置）
                      ├── conda run -n course-whisper（Python 运行环境）
                      └── 第3级降级 → qwen3_transcribe.py（HF_HOME=$MODEL_CACHE_DIR）
```

三个脚本也可以独立使用：

- `bilibili_scanner.py`：仅扫描收藏夹新内容，不转录
- `bilibili_transcript.sh`：单视频 URL 转录或本地目录批量转录
- `qwen3_transcribe.py`：纯语音转文字，不依赖 B站
