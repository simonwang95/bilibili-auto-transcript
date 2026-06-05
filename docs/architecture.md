# 架构设计

## 一、系统总览

bilibili-auto-transcript 采用**三体架构**：Scanner（扫描发现）→ Cronjob（定时触发）→ Agent（AI 处理）。三个组件各司其职，通过 stdout 文本协议松耦合通信。

```
定时触发 (cronjob / 系统定时器 / 手动)
    ↓
扫描脚本 (bilibili_scanner.py)
    → 调用 B站收藏夹 API 获取全量数据（自动分页）
    → 读取本地已处理记录 (processed_videos.txt)
    → 取差集发现新视频
    → stdout 输出结构化标记文本
    ↓ stdout
AI Agent（加载 bilibili-auto-transcript skill）
    → 解析 stdout 中的新条目
    → 对每个新视频调用 bilibili_transcript.sh 执行三级降级转录
    → （可选）调用 LLM 生成结构化摘要
    → 更新已处理记录
    → 生成 CSV 报告并通知用户
```

## 二、三级降级转录策略

这是整个系统的核心引擎，实现在 `bilibili_transcript.sh` 中。转录按优先级逐级尝试，每级失败后自动降级到下一级。

### 第 1 级：人工 CC 字幕（目标准确率 100%）

```
检查视频是否有 CC 字幕（zh-CN, zh-TW, zh-Hans, zh-Hant, en, ja, ko, es, ar, pt, de, fr）
  ↓ 有 → yt-dlp 下载字幕 → 提取纯文本 → 完成（秒级，100% 准确）
  ↓ 无 → 进入第 2 级
```

关键实现细节：
- 用 `yt-dlp --list-subs` 检查可用字幕，过滤掉弹幕（danmaku）和 AI 字幕（ai-*）
- 下载时用 `--convert-subs srt` 统一转为 SRT 格式
- 提取文本时去除 SRT 的时间戳和序号行，只保留纯文本

### 第 2 级：B站 AI 字幕（目标准确率 85-90%）

```
检查视频是否有 AI 字幕（ai-zh, ai-en, ai-ja, ai-kr, ai-th, ai-id, ai-vi）
  ↓ 有 → yt-dlp 下载 AI 字幕 → 提取纯文本 → 完成（秒级）
  ↓ 无 → 进入第 2.5 级（兜底）
```

关键实现细节：
- 需要浏览器 Cookie 才能获取 AI 字幕（需先在 chromium-browser / Edge 中登录 B站）
- 脚本自动检测 Chromium（WSL/Ubuntu）、Edge（Windows）、Firefox 的 Cookie 路径
- Cookie 有效期约 30 天，脚本会检查最后使用时间并提示

### 第 2.5 级：AI 字幕兜底下载

```
yt-dlp --list-subs 有时检测不到 AI 字幕，但实际可以下载
  ↓ 直接尝试下载 ai-zh → ai-en → ai-ja（逐个尝试）
  ↓ 有任一成功 → 提取文本 → 完成
  ↓ 全部失败 → 进入第 3 级
```

这是一个实践驱动的补丁：B站 API 返回的字幕列表有时不完整，但 yt-dlp 实际可以下载到 AI 字幕。

### 第 3 级：Qwen3-ASR 本地语音转文字

```
yt-dlp 下载音频（优先 mp3 格式）
  ↓
ffmpeg 转 16kHz 单声道 WAV（统一格式，兼容性最佳）
  ↓
调用 qwen3_transcribe.py（自动检测设备并选择模型）
  ↓ 有 GPU → Qwen3-ASR-1.7B（中文 CER ~3.8%）
  ↓ 无 GPU → Qwen3-ASR-0.6B（中文 CER ~5-7%）
  ↓
输出转录文本 → 完成（分钟级，时长相关）
```

设备检测逻辑（`qwen3_transcribe.py`）：
- 检测 `torch.cuda.is_available()` → CUDA / ROCm
- 检测 `torch.backends.mps.is_available()` → Apple Silicon (M1-M4)
- 以上均不可用 → CPU

耗时参考：
- GPU 模式（1.7B）：约实时 0.3x 倍速（10 分钟视频约 3 分钟转录）
- CPU 模式（0.6B）：约实时 0.4x 倍速

## 三、本地文件转录模式（v5.0 新增）

当传入 `--local-dir <目录>` 时，脚本跳过 B站 API。若 `FORCE_ASR=false` 且媒体文件旁存在同目录同名 `.srt` 字幕，则优先导入字幕；否则进入 ASR 语音转文字流程。结果保存到 `OUTPUT_DIR/local/`。

### 与在线模式的区别

| 阶段 | B站在线模式 | 本地文件模式 |
|------|------------|------------|
| 字幕检测 | CC → AI → 兜底 → ASR | 同名 `.srt`（`FORCE_ASR=false`）→ ASR |
| 元数据 | yt-dlp 从 B站 API 获取 | 文件名作为标题 |
| 音频处理 | yt-dlp 下载 → ffmpeg 转 WAV | 视频提取音轨 → ffmpeg 转 WAV |
| 输出目录 | `YYYY-MM/` 按当前年月分目录 | `local/` 统一子目录 |
| ASR 引擎 | Qwen3-ASR（或 FORCE_ASR 后同本地） | Qwen3 / Whisper（由 ASR_ENGINE 控制） |
| Cookie | 需要（AI 字幕） | 不需要 |

### 支持的本地格式

- **视频**: mp4, mkv, avi, mov, webm, flv, wmv, ts
- **音频**: mp3, m4a, wav, flac, ogg, opus, aac

### 调用方式

```bash
# Shell 直接调用
bash scripts/bilibili_transcript.sh --local-dir /path/to/videos/

# Python 调度器调用
python scripts/batch_transcribe.py --local-dir /path/to/videos/
```

## 四、配置系统（env.local）

v5.0 引入统一的 `env.local` 配置文件，所有可配置参数集中管理。

### 加载机制

- **Shell 脚本**: 通过 `source env.local` 加载，变量直接可用
- **Python 脚本**: 自定义解析器读取 key=value 对，兼容 Shell 格式（引号、注释）
- **优先级**: 命令行参数 > env.local > 脚本默认值

### 关键配置影响范围

| 配置 | 影响脚本 |
|------|---------|
| `CONDA_ENV` | 所有 Python 脚本的运行环境 |
| `MODEL_CACHE_DIR` | qwen3_transcribe.py（通过 `HF_HOME` 环境变量） |
| `CACHE_DIR` | bilibili_transcript.sh（音频临时缓存） |
| `SUMMARY_*` | batch_transcribe.py（LLM 摘要生成） |

## 五、扫描器设计（bilibili_scanner.py）

扫描器的唯一职责是**发现增量**，不做任何处理。这是一个铁律——任何耗时操作（下载、转录、摘要）都属于 Agent 层。

### 数据流

```
B站收藏夹 API
  ↓ 分页请求（ps=20, 最多20条/页）
  ↓ 循环直到 has_more=false
全量视频列表（id, bvid, title, duration, upper, pubtime）
  ↓
去重：磁盘 .md 文件（权威来源）
  → _find_existing_ids() 遍历 OUTPUT_DIR 下所有 *.md 文件名
  → 从文件名末尾提取 avid（纯数字）和 bvid（BV 开头）双向匹配
  → processed_videos.txt 仅作日志参考，不作为去重依据
  ↓
取差集（API 返回的 bvid 不在磁盘 bvid 集合中 → 新视频）
  ↓
stdout 输出结构化结果
```

### 磁盘文件权威去重（v1.3）

磁盘上的 `.md` 文件是唯一去重来源。文件名由 yt-dlp 的 video_id（bvid）结尾，`_find_existing_ids()` 提取所有 `.md` 文件末尾的视频 ID 并双向匹配。

**为什么「磁盘为准」**：
- `processed_videos.txt` 可能因手动删除、版本迁移等原因对应关系丢失
- 磁盘 `.md` 文件是真实产物，存在 = 已转录，不存在 = 未转录或转录失败
- 转录失败的视频没有 `.md` 文件 → 总会出现在新视频列表中 → 自动重试

两层取并集作为最终去重集合。即使 `processed_videos.txt` 被手动删除，只要磁盘上的 `.md` 文件还在，就不会重复转录。

### 输出协议

扫描器通过 stdout 输出结构化标记文本，供 Agent 解析：

**有新视频时：**
```
COLLECTION_TOTAL:156
PROCESSED:150
NEW_VIDEOS:6
  - BVID:BV1rPDkB7ESC
    TITLE:视频标题
    DURATION:4分58秒
    UPPER:UP主名称
    PUBTIME:1775616958
```

**无新视频时：**
```
COLLECTION_TOTAL:156
PROCESSED:156
ALL_CAUGHT_UP
```

**错误时：**
- 以 `ERROR:` 前缀开头，Agent 据此判断是否停止处理
- 网络错误和 API 错误分别处理

### 关键设计决策

- **用 avid 而非 bvid 做去重 key**：avid 是数字 ID，唯一且稳定；bvid 是字符串，存在大小写和格式变体风险
- **每页 20 条**：B站 API 硬限制，超过返回 `code=-400`
- **公开收藏夹无需 Cookie**：扫描器不依赖登录态，仅依赖 API 公开访问

## 六、批量转录调度器（batch_transcribe.py）

### 执行流程

```
1. 调用 bilibili_scanner.py 获取新视频列表
2. 补全标题、时长、UP主等元信息
3. 对每个新视频：
   a. 调用 bilibili_transcript.sh 执行转录（三级降级）
   b. 成功后保存 avid 到已处理记录（断点续传保证）
   c. （可选）调用 OpenAI API 生成结构化摘要
   d. 失败自动重试（最多 2 次），Qwen3-ASR 失败不重试（模型加载慢）
4. 生成 CSV 转录报告（含来源分布统计）
5. 打印失败列表
```

### 断点续传机制

- 每转录成功一个视频就立即追加 avid 到 `processed_videos.txt`
- 即使中途中断（Ctrl+C、崩溃、OOM），已处理的不会被重复处理
- 转录和记录是原子操作（转录成功后才记录）

### 重试策略

- CC 字幕 / AI 字幕下载失败 → 重试（快速，无模型加载开销）
- Qwen3-ASR 转录失败 → 不重试（模型加载耗时，失败通常是模型或音频问题）
- 重试间隔随尝试次数递增（`BATCH_DELAY * attempt` 秒）
- LLM 后处理请求失败 → 对超时、连接异常、HTTP 408/409/425/429、5xx、空响应或异常响应按 `LLM_MAX_RETRIES` 重试，等待时间按 `LLM_RETRY_DELAY` 指数退避；400/401/403/404 等配置错误不重试

### 进度预估

基于已完成视频的平均耗时计算剩余时间：
```
avg_time = total_elapsed / success_count
eta = avg_time * remaining_count
```

### 视频间延迟

每个视频处理后等待 `BATCH_DELAY` 秒防风控。LLM 后处理（摘要/导图/校对）之间等待 `COOLDOWN_DELAY` 秒散热。Whisper/ASR 转录之间不等待。

## 七、输出文件格式

转录结果保存为 Markdown 文件。AI 校对在前，完整原文在末尾（默认 `<details>` 折叠）。

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

## AI校对
（对话类型自动区分说话角色：主持人/嘉宾/说话人A/B）

---

<details>
<summary>📄 完整原文</summary>
（原始转录文本）
</details>
```


文件路径规则：`{OUTPUT_DIR}/{YYYY-MM}/{safe_title}_{safe_author}_{date}_{video_id}.md`。目录为当前年月，文件名保留视频发布时间。

## 八、状态文件

| 文件 | 位置 | 内容 |
|------|------|------|
| processed_videos.txt | `~/.openclaw/workspace/.auto-transcript-state/` | 已处理的 avid 列表，每行一个 |
| transcript_report.csv | `~/.openclaw/workspace/.auto-transcript-state/` | 每次批量转录的详细报告 |

CSV 报告字段：bvid, title, author, duration, source, output_file, content_hash, status, attempts

## 九、设计原则

1. **扫描必须快** — Scanner 只做 API 调用 + 集合比对，不应包含任何耗时操作。通常 <1 秒完成。
2. **增量记录用唯一 ID** — 用 avid（数字）而非 bvid 或文件名，避免重名/改名导致重复处理。
3. **磁盘文件权威去重** — 仅以输出目录中的 `.md` 文件判断是否已转录。文件存在 = 跳过，不存在 = 重试（含之前失败的）。`processed_videos.txt` 仅作日志，不干预去重逻辑。
4. **不重复不遗漏** — 处理完立即记录 ID，Agent 中途失败也不会漏掉。
5. **无增量时静默** — 用户只在有内容变化时才收到通知。
6. **自愈** — 脚本/Agent 处理失败不阻塞后续扫描，下次运行时自动重试。
7. **转录脚本只出文件** — 不负责索引。索引是 knowledge-rag 的职责。
8. **各司其职** — Scanner 负责发现、转录引擎负责产出文件、调度器负责 LLM 后处理和报告。
9. **文档同步** — 每次功能更新同步更新 docs/ 下的对应文档，保持代码与文档一致。
