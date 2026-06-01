---
name: bilibili-auto-transcript
version: "3.5.0"
description: "B站视频转录+收藏夹扫描。三级降级（CC→AI→Whisper），智能模型选择，AI摘要生成。"
homepage: https://clawhub.ai/54lynnn/bilibili-transcript
metadata:
  {
    "openclaw":
      {
        "emoji": "📼",
        "requires": { "bins": ["yt-dlp", "ffmpeg", "curl"] },
        "install":
          [
            {
              "id": "pip",
              "kind": "pipx",
              "package": "openai-whisper",
              "bins": ["whisper"],
              "label": "Install Whisper (STT)",
            },
            {
              "id": "pip",
              "kind": "pipx",
              "package": "requests",
              "bins": [],
              "label": "Install requests (HTTP client for scanner)",
            },
          ],
      },
  }
---

# 📼 Bilibili 视频转录 & 收藏夹自动扫描

**双模式技能** — 可以手动转录单个视频，也可以定时扫描收藏夹自动处理。

## 模式一：手动转录

当你给我一个 B站链接时，我会自动执行转录。

**用法：**
```bash
bash scripts/bilibili_transcript.sh "https://www.bilibili.com/video/BVxxxxx/"
```

**转录优先级（自动降级）：**
1. ✅ **人工CC字幕**（zh-CN, zh-TW, en, ja 等）→ 100%准确，秒出
2. ✅ **AI字幕**（ai-zh, ai-en, ai-ja 等9种语言）→ 85-90%准确，秒出
3. ✅ **Whisper 语音转文字**（智能模型选择）→ 根据视频时长和GPU情况自动选模型

**Whisper 智能模型选择：**

| 条件 | < 3分钟 | 3-10分钟 | 10-30分钟 | > 30分钟 |
|------|---------|----------|-----------|----------|
| **有GPU** | tiny | base | medium | large-v3 |
| **无GPU(CPU)** | tiny | base | small | small |

- 自动检测 CUDA GPU 可用性
- 中文视频自动指定 `--language zh` 提高准确率
- 音频自动转为 16kHz 单声道 WAV（Whisper 处理更快）

**⚠️ 关键步骤（必须执行）：** 脚本运行后，**AI必须先做这件事**，才能向用户报告完成：

1. **写摘要** → `read` 输出的 TXT 文件，阅读全文，用 `edit` 替换占位符为结构化摘要

转录只负责出文件，索引那是 knowledge-rag 自己的事。

---

## 模式二：收藏夹自动扫描

定时检查 B站收藏夹，发现新视频后自动完成「转录 → AI 摘要 → 保存 → 通知」全流程。

### 工作流

```
定时触发 → 扫描收藏夹API → 对比已处理列表
  → 发现新视频 → 转录（三级降级）
  → （可选）AI读全文、写结构化摘要
  → 覆盖TXT中的摘要占位符
  → 记录avid到已处理列表
  → 生成转录报告CSV
  → 通知用户（标题/作者/时长/转录来源/摘要/TXT文件）
```

### 批量转录（推荐）

```bash
python3 scripts/batch_transcribe.py
```

自动扫描收藏夹全部视频，逐个转录，支持：
- **断点续传** — 中断后重跑自动跳过已处理视频
- **自动重试** — 失败任务自动重试2次
- **转录报告** — 生成 CSV 报告，含来源分布统计
- **AI摘要** — 可选，设置环境变量 `OPENAI_API_KEY` 即可自动生成摘要
- **目录组织** — 按视频发布年月自动分目录存储

### 首次设置

#### 1. 创建收藏夹
B站新建一个收藏夹，设为**公开**。

#### 2. 获取收藏夹ID
URL 中 `fid=` 后面的数字。

#### 3. 修改扫描脚本
编辑 `scripts/bilibili_scanner.py`，改 `FAV_MEDIA_ID` 为你的收藏夹ID。

#### 4. Chromium 登录B站（获取Cookie）
```bash
chromium-browser &
# 打开 bilibili.com 并登录
```

#### 5. 检查依赖
```bash
yt-dlp --version    # 必需
ffmpeg -version     # 必需
whisper --help      # 可选，无字幕视频降级用
opencc --version    # 可选，繁转简
```

#### 6. 配置定时任务（推荐每6小时）
```bash
openclaw cron add \
  --name bilibili-scan \
  --every 21600000 \
  --message "运行扫描脚本：python3 scripts/bilibili_scanner.py"
```

---

## 公共部分

### 转录脚本
`scripts/bilibili_transcript.sh` — 两个模式共享同一个引擎（v3.0）。

### 依赖
- `yt-dlp` — 视频下载、字幕获取
- `ffmpeg` — 音频处理（Whisper 模式）
- `whisper` (openai-whisper) — 语音转文字（降级）；首次使用时自动下载模型
- `opencc` — 繁转简（可选）
- `chromium-browser` — Cookie 支持（B站AI字幕）

### 输出文件格式
```
================================================================================
B站视频转录文档
================================================================================

📹 视频标题：xxx
🔗 B站链接：xxx
👤 作者：xxx
📅 发布时间：xxx
⏱️  视频时长：xxx
📝 转录来源：CC字幕 / B站AI字幕 / Whisper tiny/base/medium/large-v3 模型
⏰ 转录时间：xxx

================================================================================
第一部分：视频摘要（AI生成）
================================================================================

【AI待处理：请阅读全文后，替换此行，写结构化摘要】
（设置 OPENAI_API_KEY 后自动生成）

================================================================================
第二部分：完整原文
================================================================================

（完整转录内容...）

================================================================================
文档结束
================================================================================
```

### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 收藏夹ID | （需设置） | URL `fid=` 的数字 |
| 输出目录 | `~/workspace/knowledge/bilibili/` | TXT存放路径，自动按年/月分子目录 |
| 已处理记录 | `~/.openclaw/workspace/.auto-transcript-state/processed_videos.txt` | 去重文件（每行一个avid） |
| 转录报告 | `~/.openclaw/workspace/.auto-transcript-state/transcript_report.csv` | 每次批量转录的详细报告 |
| 扫描间隔 | 每6小时 | 自动模式定时 |
| OPENAI_API_KEY | （可选） | 设置后自动生成AI摘要 |

### B站收藏夹API
```
GET https://api.bilibili.com/x/v3/fav/resource/list?media_id={ID}&ps=20&pn=1
```
- `ps` 最大20（脚本已设 ps=20）
- 公开收藏夹无需Cookie

### avid vs bvid
- `id` = avid（数字）→ 去重追踪用
- `bvid` / `bv_id` = BV号 → 构建转录URL用

### 注意事项
1. **同文件覆盖** — 同一BV号多次转录覆盖旧文件，已处理列表防重复
2. **需要Cookie** — 通过 Chromium cookie 获取 AI 字幕，需先B站登录；Cookie快过期时脚本会提示
3. **Whisper 耗时** — GPU模式约耗时视频时长的10-50%（取决于模型大小）；CPU模式显著更慢
4. **B站API ps上限20** — 超过需分页
5. **摘要占位符必须替换** — 设置 `OPENAI_API_KEY` 环境变量可自动生成摘要
6. **只干自己的事** — 转录只输出文件。索引是 knowledge-rag 的事情
7. **输出目录** — 自 v3.0 起按视频发布年月自动组织目录（如 `bilibili/2026/06/`）

## 推荐搭配：📖 Knowledge RAG

装了这个 skill 后再装 **knowledge-rag**，知识库会定时自动扫描新文件并索引，无需手动操作：

```bash
clawhub install knowledge-rag
```

转录后自动索引，随时用自然语言搜索所有转过的内容，还有网页搜索界面。

---

## 📦 开源 & 交流

- **GitHub**：[github.com/54Lynnn/bilibili-auto-transcript](https://github.com/54Lynnn/bilibili-auto-transcript)（⭐️ Star 支持）
- **ClawHub**：[clawhub.ai/54lynnn/bilibili-auto-transcript](https://clawhub.ai/54lynnn/bilibili-auto-transcript)
- **QQ 群**：120363664（欢迎扫码加入交流）
