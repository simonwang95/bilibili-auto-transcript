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

**版本**: v1.3  
**语言**: Python 3  
**职责**: 分页获取收藏夹全量视频，磁盘文件权威去重，输出新增视频列表

### 调用方式

```bash
python scripts/bilibili_scanner.py
```

所有配置通过 `env.local` 读取。

### 磁盘文件权威去重（v1.3）

`_find_existing_ids()` 遍历 `OUTPUT_DIR` 及子目录下所有 `.md` 文件，从文件名末尾提取 avid/bvid 双向匹配。**磁盘文件是唯一去重来源**——文件存在 = 已转录，不存在 = 新视频（含之前失败的）。

`processed_videos.txt` 仅作日志参考，不再参与去重判断。输出示例：

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
3. **对话检测 + AI 校对** — 先调用 `_detect_dialogue()` 取文本前 3000 字符判断是否为对话/访谈/多人讨论。若检测为对话，校对 prompt 会额外要求根据语义区分说话角色，输出格式如「主持人：」「嘉宾：」或「说话人A：」「说话人B：」。非对话则执行常规校对（错别字 + 断句 + 标点 + 领域术语）

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
        ├── bilibili_scanner.py（磁盘文件权威去重）
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
- `organize_categories.py`：将日期目录下的文件按内容分类整理
- `build_epub.py`：将分类目录打包为 EPUB 电子书

---

## 六、organize_categories.py — 内容分类整理

**版本**: v1.0  
**语言**: Python 3  
**职责**: 将日期目录（YYYY-MM）下的 .md 转录文件按内容自动分类到技术/财经等目录

### 调用方式

```bash
# 自动分类（需 LLM，读取 SUMMARY_API_KEY）
python scripts/organize_categories.py

# 仅预览，不实际移动文件
python scripts/organize_categories.py --dry-run

# 手动归类单个文件
python scripts/organize_categories.py --category 技术 /path/to/file.md
```

### 工作流程

1. 扫描 `OUTPUT_DIR` 下所有 `YYYY-MM` 格式的日期目录
2. 对每个 `.md` 文件提取标题 + 摘要 + 思维导图（截取到完整原文之前）
3. 调用 LLM 从默认分类（技术/财经/生活/教育/其他）中判定归属
4. 将文件移动到 `OUTPUT_DIR/<分类>/` 目录
5. 删除已清空的日期目录

### 默认分类

| 分类 | 典型内容 |
|------|---------|
| 技术 | AI/编程/工具/软件 |
| 财经 | 经济/投资/商业 |
| 生活 | 日常/健康/旅游/美食 |
| 教育 | 课程/科普/学术 |
| 其他 | 无法归类的兜底 |

---

## 七、build_epub.py — EPUB 电子书导出

**版本**: v2.0  
**语言**: Python 3  
**依赖**: 无（纯标准库，无需 ebooklib / markdown 等外部包）  
**职责**: 合并所有分类目录下的 .md 文件为一部 EPUB，分类为一级目录，视频标题为二级目录

### 调用方式

```bash
# 合并所有分类生成一本 EPUB
python scripts/build_epub.py

# 指定输出目录
python scripts/build_epub.py --output-dir ./books

# 保留临时构建目录（调试用）
python scripts/build_epub.py --keep-build
```

### 书籍结构

```
B站视频转录合集
├── 技术                          ← 一级目录（EPUB 章节）
│   ├── ChatGPT 原理详解          ← 二级目录（视频标题）
│   │   ├── 视频摘要
│   │   ├── 思维导图（嵌套列表，最多四级深度）
│   │   └── AI校对
│   └── Kubernetes 部署指南
├── 财经                          ← 一级目录
│   └── ...
└── 生成日期                      ← 末尾页
```

### Markdown 解析

纯 Python 标准库实现的逐行解析器，核心特性：

- **嵌套列表**：通过栈跟踪缩进级别（每 2 空格一级），支持最多四级深度。同级兄弟闭合前一个 `<li>` 再开新项，子级在父 `<li>` 内嵌 `<ul>`。空白行不打断列表延续，非列表元素（标题/分隔线）自动关闭所有列表
- **引用块**：每条 `> ` 独立一个 `<blockquote><p>`，保证元信息逐行换行
- **标题**：`#` / `##` / `###` → `<h1>` / `<h2>` / `<h3>`（子章节模式下全部降一级）
- **行内格式**：粗体 `**text**`、行内代码 `` `code` ``

### 处理规则

- **剔除完整原文**：识别 `<details>` 折叠块或 `## 完整原文` 标题并移除，EPUB 只保留摘要/导图/校对
- **分类入口页**：每个分类一个导航页，列出该分类下所有文章链接
- **末尾页**：生成日期 + 署名
- **文件名**：`bilibili-all-YYYY-MM-DD.epub`，日期自动取当天
- **零依赖**：直接生成 EPUB 3.0 标准的 XML/ZIP 包，兼容 iBooks / Kindle / 各类阅读器
