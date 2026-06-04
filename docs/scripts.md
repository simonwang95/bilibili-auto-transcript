# 脚本详解

项目包含五个核心脚本，每个承担明确的职责。

---

## 一、bilibili_transcript.sh — 核心转录引擎

**版本**: v5.1  
**语言**: Bash  
**职责**: B站单视频转录 / 本地目录批量转录。三级降级（CC→AI→ASR），双引擎分发（Qwen3 / Whisper）

### 调用方式

```bash
# B站在线视频
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"

# 本地目录批量转录
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/

# 指定输出目录
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/ --output-dir /custom/output/
```

### 配置来源

```
env.local (source 加载) → 脚本默认值
```

所有路径、conda 环境、浏览器类型、ASR 引擎均从 `env.local` 读取。命令行参数可覆盖。

### 三级降级转录（B站模式）

| 优先级 | 来源 | 准确率 | 速度 |
|:------:|:----:|:------:|:----:|
| 1 | 人工 CC 字幕 | ~100% | 秒出 |
| 2 | B站 AI 字幕 | 85-90% | 秒出 |
| 2.5 | AI 字幕兜底 | — | 秒出 |
| 3 | Qwen3-ASR / Whisper | 93-96%+ | 分钟级 |

设置 `FORCE_ASR=true` 后跳过前三步，直接进入 ASR 转录。

### ASR 引擎分发（v5.1）

`run_asr_transcribe()` 根据 `ASR_ENGINE` 分发：

- `qwen3` → `qwen3_transcribe.py`（支持 `--local-model`、`--force-cpu`）
- `whisper` → `whisper_transcribe.py`（`--model-path` 指向本地模型）

支持本地模型路径（`ASR_LOCAL_MODEL`），相对路径以项目根目录为基准解析。

### 本地目录模式

扫描目录中的媒体文件（mp4/mkv/avi/mov/webm/flv/wmv/ts + mp3/m4a/wav/flac/ogg/opus/aac），视频自动用 ffmpeg 提取音轨并转 16kHz WAV，送入 ASR 引擎转录。结果保存到 `OUTPUT_DIR/local/`。

### Python 运行方式

三级回退：conda（`course-whisper`）→ `.venv/bin/python3` → 系统 `python3`

---

## 二、bilibili_scanner.py — 收藏夹扫描器

**版本**: v1.2  
**语言**: Python 3  
**职责**: 分页获取收藏夹全量视频，双重去重（文本记录 + 磁盘文件），输出新增视频列表

### 调用方式

```bash
python scripts/bilibili_scanner.py
```

所有配置通过 `env.local` 读取。

### 双重去重机制（v1.2）

**来源 1 — `processed_videos.txt`**：每行一个 avid，由 `batch_transcribe.py` 在转录成功后写入。

**来源 2 — 输出目录 `.md` 文件**：`_find_existing_ids()` 遍历 `OUTPUT_DIR` 及子目录下所有 `.md` 文件，从文件名末尾同时提取 avid（纯数字结尾）和 bvid（`BV` 开头结尾）。因为 yt-dlp 保存的文件名用的是 bvid 而非 avid，所以需要双向匹配。文件名格式为 `{title}_{author}_{date}_{video_id}.md`。

两层取并集。即使 `processed_videos.txt` 被删除，磁盘上的 `.md` 文件仍会阻止重复转录。输出示例：

```
PROCESSED:7 (text:5, disk:4)
```

### 私有收藏夹支持

设置 `BILI_COOKIE_FILE` 指向 Netscape 格式 Cookie 文件后，`_load_cookies()` 将其解析为 dict 传入 `requests.get()`。

### 错误处理

- 网络异常 → `ERROR: 网络请求失败`
- API 错误 → `ERROR: B站API返回错误 (code=...)`
- 权限不足 → 打印详细提示（公开收藏夹 / Cookie 文件两种方案）

---

## 三、qwen3_transcribe.py — Qwen3-ASR 转录辅助

**版本**: v1.3  
**语言**: Python 3  
**职责**: 自动检测设备并选择 Qwen3-ASR 模型（1.7B / 0.6B），支持本地模型路径

### 调用方式

```bash
python scripts/qwen3_transcribe.py \
  --audio <音频路径> \
  --output-file <输出路径> \
  [--device auto|cpu|cuda|mps] \
  [--model-cache-dir <目录>] \
  [--local-model <本地模型路径>] \
  [--force-cpu]
```

| 参数 | 说明 |
|------|------|
| `--audio` | 输入音频（建议 16kHz WAV） |
| `--output-file` | 输出，第一行=来源，其余=文本 |
| `--device` | 设备选择，默认 auto |
| `--model-cache-dir` | 下载缓存目录 |
| `--local-model` | **v1.3** — 本地模型路径，跳过下载 |
| `--force-cpu` | **v1.3** — 强制 CPU（MPS 内存超限时用） |

### 设备与模型

| 设备 | 模型 | CER | 需求 |
|---|---|---|---|
| CUDA / MPS | Qwen3-ASR-1.7B | ~3.8% | GPU 4-6 GB |
| CPU / --force-cpu | Qwen3-ASR-0.6B | ~5-7% | ~2 GB |

---

## 四、whisper_transcribe.py — Whisper MLX 转录辅助

**版本**: v1.0  
**语言**: Python 3  
**职责**: 基于 Apple `mlx-whisper`，专为 Apple Silicon 优化

### 调用方式

```bash
python scripts/whisper_transcribe.py \
  --audio <音频路径> \
  --output-file <输出路径> \
  --model-path <本地 Whisper 模型目录>
```

在 `env.local` 中设置 `ASR_ENGINE="whisper"` 切换到此引擎。`bilibili_transcript.sh` 的 `run_asr_transcribe()` 自动分发。

---

## 五、batch_transcribe.py — 批量转录调度器

**版本**: v3.0  
**语言**: Python 3  
**职责**: B站收藏夹扫描+转录 / 本地目录转录，LLM 三阶段后处理

### 调用方式

```bash
# B站收藏夹
python scripts/batch_transcribe.py

# 本地目录
python scripts/batch_transcribe.py --local-dir /path/to/videos/
```

所有配置从 `env.local` 读取。

### LLM 三阶段后处理

设置 `SUMMARY_API_KEY` 后，每个转录完成自动执行：

1. **结构化摘要** — 核心观点 + 主要论点 + 关键结论
2. **思维导图** — 缩进 Markdown 列表
3. **AI 校对** — 错别字 + 断句 + 标点 + 领域术语（`PROOFREAD_DOMAINS` 控制，默认金融+计算机）

三阶段独立，一个失败不影响其他。LLM 调用通过 `_call_llm()` 统一处理，超时由 `LLM_TIMEOUT` 控制。

### 编码兼容

`_safe_subprocess()` 包装所有 subprocess 调用，用 `errors="replace"` 处理非 UTF-8 输出（如 macOS 钥匙串终端序列）。

### 其他

- **avid 去重**：扫描器输出 AVID，调度器用 avid 匹配已处理记录
- **断点续传**：每转录成功一个立刻写入 `processed_videos.txt`
- **CSV 报告**：含 bvid/title/source/content_hash/status

---

## 脚本间依赖关系

```
batch_transcribe.py (v3.0)
  ├── --local-dir → bilibili_transcript.sh --local-dir
  └── 默认模式:
        ├── bilibili_scanner.py（双重去重：文本+磁盘）
        └── bilibili_transcript.sh（三级降级 / ASR）
              ├── source env.local
              ├── run_asr_transcribe()
              │     ├── ASR_ENGINE=qwen3 → qwen3_transcribe.py
              │     └── ASR_ENGINE=whisper → whisper_transcribe.py
              └── write_output_file() → .md
```

独立使用：
- `bilibili_scanner.py`：仅扫描收藏夹，不转录
- `bilibili_transcript.sh`：单视频 URL 或本地目录转录
- `qwen3_transcribe.py` / `whisper_transcribe.py`：纯语音转文字
