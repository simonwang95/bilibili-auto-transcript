#!/usr/bin/env python3
"""
批量转录 B站收藏夹中的所有新视频 v3.0
功能：
  - 自动扫描收藏夹所有视频（含分页）
  - 支持本地目录批量转录
  - 支持断点续传（已处理视频自动跳过）
  - 自动重试失败任务
  - 生成转录报告 CSV
  - 支持 LLM 摘要自动生成（可选）

配置：编辑项目根目录的 env.local 文件
"""

import csv
import hashlib
import os
import subprocess
import sys
import time

import requests

# ===== 加载 env.local 配置 =====
def _load_env_local():
    """从项目根目录的 env.local 加载配置"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    env_file = os.path.join(project_dir, "env.local")

    config = {}
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    config[key] = value
    return config

_env = _load_env_local()

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.join(SKILL_DIR, "scripts", "bilibili_scanner.py")
TRANSCRIPT_SH = os.path.join(SKILL_DIR, "scripts", "bilibili_transcript.sh")


def _expand_path(raw):
    """展开路径中的 $HOME / $VAR 和 ~ —— 兼容 env.local 的双引号写法"""
    return os.path.expanduser(os.path.expandvars(raw))


STATE_DIR = _expand_path(
    _env.get("STATE_DIR", "~/.openclaw/workspace/.auto-transcript-state")
)
PROCESSED_FILE = os.path.join(STATE_DIR, "processed_videos.txt")
REPORT_FILE = os.path.join(STATE_DIR, "transcript_report.csv")
OUTPUT_DIR = _expand_path(
    _env.get("OUTPUT_DIR", "~/workspace/knowledge/bilibili")
)

CONDA_ENV = _env.get("CONDA_ENV", "course-whisper")
MAX_RETRIES = int(_env.get("MAX_RETRIES", "2"))
BATCH_DELAY = int(_env.get("BATCH_DELAY", "3"))

# LLM 摘要配置
SUMMARY_API_KEY = _env.get("SUMMARY_API_KEY", "")
SUMMARY_API_URL = _env.get("SUMMARY_API_URL", "https://api.openai.com/v1/chat/completions")
SUMMARY_MODEL = _env.get("SUMMARY_MODEL", "gpt-4o-mini")
SUMMARY_MAX_TOKENS = int(_env.get("SUMMARY_MAX_TOKENS", "1024"))
LLM_TIMEOUT = int(_env.get("LLM_TIMEOUT", "600"))
PROOFREAD_DOMAINS = _env.get("PROOFREAD_DOMAINS", "").strip()

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_python_cmd():
    """获取 Python 运行命令（conda 环境优先）"""
    if CONDA_ENV:
        # 检查 conda 是否可用
        try:
            result = subprocess.run(
                ["conda", "env", "list"],
                capture_output=True, text=True, timeout=10
            )
            if CONDA_ENV in result.stdout:
                return ["conda", "run", "-n", CONDA_ENV, "python3"]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return [sys.executable]


def load_processed():
    processed = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            processed = set(line.strip() for line in f if line.strip())
    return processed


def save_processed(avid):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{avid}\n")


def get_content_hash(filepath):
    if not os.path.exists(filepath):
        return ""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            h.update(f.read(65536))
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _safe_subprocess(args, **kwargs):
    """运行子进程，用 errors='replace' 处理编码问题。

    macOS 上 yt-dlp --cookies-from-browser 可能输出钥匙串相关的
    非 UTF-8 终端序列，导致 UnicodeDecodeError。此函数强制替换
    无效字节为 U+FFFD 而非抛出异常。
    """
    timeout = kwargs.pop("timeout", None)
    cwd = kwargs.pop("cwd", None)
    result = subprocess.run(
        args,
        capture_output=True,
        cwd=cwd,
        timeout=timeout,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def scan_videos():
    """扫描 B站收藏夹新视频"""
    python_cmd = get_python_cmd()
    result = _safe_subprocess(
        python_cmd + [SCANNER], cwd=SKILL_DIR
    )

    # 过滤 conda 的干扰输出（conda run 可能在 stdout 或 stderr 中注入噪声）
    stdout_lines = []
    for line in result.stdout.splitlines():
        # 跳过 conda 注入行
        if "conda.cli.main_run" in line or "conda run" in line:
            continue
        stdout_lines.append(line)

    clean_stdout = "\n".join(stdout_lines)
    print(clean_stdout)

    if result.returncode != 0:
        # 提取有意义的错误信息（跳过 conda 噪声）
        stderr_lines = []
        for line in result.stderr.splitlines():
            if "conda.cli.main_run" in line:
                continue
            stderr_lines.append(line)
        meaningful_stderr = "\n".join(stderr_lines).strip()
        if meaningful_stderr:
            print(f"Scanner error: {meaningful_stderr}")

        # 检查是否是收藏夹权限问题，给出明确指引
        if "访问权限" in result.stdout or "权限不足" in result.stdout:
            print("")
            print("💡 提示：收藏夹可能为私有。解决方法：")
            print("  1) 在 B站网页端将该收藏夹设为「公开」")
            print("  2) 或在 env.local 中配置 BILI_COOKIE_FILE：")
            print("     yt-dlp --cookies-from-browser chromium --cookies ./bili_cookies.txt \\")
            print("       --skip-download --print title \"https://www.bilibili.com/video/BVxxx/\"")
            print("     然后在 env.local 中添加: BILI_COOKIE_FILE=\"./bili_cookies.txt\"")
        return []

    # 解析视频列表（使用过滤后的行）
    videos = []
    current = None
    for line in stdout_lines:
        if line.startswith("  - AVID:"):
            if current:
                videos.append(current)
            current = {"avid": line.split("AVID:", 1)[1].strip()}
        elif line.startswith("    BVID:") and current:
            current["bvid"] = line.split("BVID:", 1)[1].strip()
        elif line.startswith("    TITLE:") and current:
            current["title"] = line.split("TITLE:", 1)[1].strip()
        elif line.startswith("    DURATION:") and current:
            current["duration"] = line.split("DURATION:", 1)[1].strip()
        elif line.startswith("    UPPER:") and current:
            current["upper"] = line.split("UPPER:", 1)[1].strip()
        elif line.startswith("    PUBTIME:") and current:
            current["pubtime"] = line.split("PUBTIME:", 1)[1].strip()
    if current:
        videos.append(current)
    return videos


def transcribe_video(bvid, attempt=1, max_retries=1):
    """转录单个 B站视频"""
    url = f"https://www.bilibili.com/video/{bvid}/"
    print(f"\n{'='*70}")
    print(f"🎬 开始转录: {bvid} (尝试 {attempt}/{max_retries})")
    print(f"{'='*70}")

    result = _safe_subprocess(
        ["bash", TRANSCRIPT_SH, url],
        cwd=SKILL_DIR, timeout=7200,
    )

    if result.stdout:
        print(result.stdout[-2000:])
    if result.stderr:
        stderr_preview = result.stderr.strip()[-500:]
        if stderr_preview:
            print(f"STDERR: {stderr_preview}")

    used_stt = "🎤" in result.stdout

    if "✅ 转录完成" in result.stdout:
        saved_file = None
        for line in result.stdout.splitlines():
            if line.strip().endswith(".md") and "/" in line:
                saved_file = line.strip()
        transcript_source = None
        for line in result.stdout.splitlines():
            if "转录来源" in line:
                transcript_source = line.replace("📝 转录来源：", "").strip()
                break
        return True, saved_file or "unknown", transcript_source or "unknown", used_stt
    else:
        error_msg = result.stdout[-300:] if result.stdout else "无输出"
        return False, error_msg, None, used_stt


def transcribe_local_dir(local_dir):
    """转录本地目录中的所有媒体文件"""
    print(f"\n{'='*70}")
    print(f"📁 本地目录转录: {local_dir}")
    print(f"{'='*70}")

    result = _safe_subprocess(
        ["bash", TRANSCRIPT_SH, "--local-dir", local_dir, "--output-dir", OUTPUT_DIR],
        cwd=SKILL_DIR, timeout=7200,
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # 解析输出文件列表
    output_files = []
    for line in result.stdout.splitlines():
        if line.strip().endswith(".md") and "/" in line:
            output_files.append(line.strip())

    return output_files, result.returncode


def _call_llm(system_prompt, user_prompt, max_tokens=None):
    """调用 LLM，返回响应文本或 None"""
    if not SUMMARY_API_KEY:
        return None

    api_url = SUMMARY_API_URL.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    payload = {
        "model": SUMMARY_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens or SUMMARY_MAX_TOKENS,
    }
    resp = requests.post(
        api_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SUMMARY_API_KEY}",
        },
        timeout=LLM_TIMEOUT,
    )
    resp_data = resp.json()
    # LM Studio 等本地服务可能不返回 choices
    if "choices" in resp_data:
        return resp_data["choices"][0]["message"]["content"]
    elif "content" in resp_data:
        return resp_data["content"]
    else:
        raise ValueError(f"Unexpected response: {resp_data}")


def _build_domain_prompt(domains_str):
    """根据 PROOFREAD_DOMAINS 配置生成领域专有名词校对提示。

    默认覆盖金融和计算机领域。用户可在 env.local 中通过 PROOFREAD_DOMAINS
    追加额外领域（逗号分隔，如 "medical,legal,engineering"）。
    """
    domain_map = {
        "finance": (
            "6a) 金融领域：修正金融术语的语音识别错误，如「股权→债券」「期货→期权」"
            "「量化→量价」「对冲→对充」「杠杆→钢杆」「IPO→I P O」等；"
            "保持「PE/VC/ROE/ROI/NPV/EBITDA」等缩写格式正确\n"
        ),
        "computer": (
            "6b) 计算机领域：修正技术术语的识别错误，如「API→A P I」「SDK→S D K」"
            "「Kubernetes→K 8 s」「Docker→道客」「Git→给特」「SQL→C Q L」"
            "「JSON→J 桑」「RESTful→REST ful」「微服务→微浮物」「容器化→荣启华」等\n"
        ),
        "medical": (
            "6c) 医学领域：修正医学术语的识别错误，如药名、疾病名、解剖学术语等；"
            "保持「CT/MRI/DNA/RNA」等缩写格式正确\n"
        ),
        "legal": (
            "6d) 法律领域：修正法律术语的识别错误，如「合同法→和同法」「仲裁→中才」"
            "「知识产权→知识产全」「法人→发人」等\n"
        ),
        "engineering": (
            "6e) 工程领域：修正工程术语的识别错误，如「架构→加购」「模块→磨快」"
            "「耦合→偶合」「并发→病发」「冗余→绒余」等\n"
        ),
    }

    # 默认领域
    domains = ["finance", "computer"]
    if domains_str:
        extra = [d.strip().lower() for d in domains_str.split(",") if d.strip()]
        domains.extend(extra)

    seen = set()
    letters = "abcdefgh"
    idx = 0
    parts = []
    for d in domains:
        if d in seen:
            continue
        seen.add(d)
        if d in domain_map:
            # Replace placeholder numbering with actual sequential numbering
            rule_num = f"6{letters[idx]})"
            desc = domain_map[d]
            # The stored desc has hardcoded numbering, rebuild it
            desc_clean = desc.split(")", 1)[1] if ")" in desc else desc
            parts.append(f"{rule_num}{desc_clean}")
            idx += 1

    if not parts:
        return ""

    return "".join(parts) + "\n"


def generate_summary(filepath):
    """使用 LLM 为转录文件生成摘要、思维导图、校对版本

    三阶段处理：
      1. 结构化摘要（替换第一部分占位符）
      2. 思维导图（替换思维导图占位符）
      3. 原文校对——修复 ASR 错别字，优化可读性（替换校对占位符）
    每个阶段独立，一个失败不影响其他。
    """
    if not SUMMARY_API_KEY:
        return False
    if not os.path.exists(filepath):
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 如果所有占位符都已被替换，跳过
    placeholders = [
        "【AI待处理：请设置 SUMMARY_API_KEY 后重新运行以生成结构化摘要】",
        "【AI待处理：请设置 SUMMARY_API_KEY 后重新运行以生成思维导图】",
        "【AI待处理：请设置 SUMMARY_API_KEY 后重新运行以生成校对版本】",
    ]
    # 兼容旧版占位符
    old_summary_ph = "【AI待处理：请阅读全文后，替换此行，写结构化摘要】"

    has_any = any(ph in content for ph in placeholders) or old_summary_ph in content
    if not has_any:
        return False

    title = ""
    for line in content.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            break
        if "视频标题：" in line:
            title = line.split("视频标题：", 1)[1].strip()
            break

    # 提取原文（"## 完整原文" 标题之后）
    text_start = content.find("## 完整原文")
    if text_start == -1:
        return False

    # 跳过标题行本身
    text_start = content.find("\n", text_start)
    if text_start == -1:
        return False
    text_start += 1

    # 找到原文的结束位置（"## AI校对" 标题或 EOF）
    text_end = content.find("\n## AI校对", text_start)
    if text_end == -1:
        text_end = content.find("文档结束", text_start)
    if text_end == -1:
        transcript_text = content[text_start:]
    else:
        transcript_text = content[text_start:text_end]

    # 控制输入长度（本地模型上下文有限）
    transcript_text = transcript_text[:20000]

    changed = False

    # ===== 第 1 阶段：结构化摘要 =====
    summary_ph = placeholders[0] if placeholders[0] in content else old_summary_ph
    if summary_ph in content:
        print("   📝 生成摘要...")
        try:
            summary = _call_llm(
                "你是一个视频摘要助手。请对以下转录文本生成结构化摘要，"
                "包含：1) 核心观点 2) 主要论点 3) 关键结论。用中文回复，简洁明了。",
                f"视频标题：{title}\n\n转录文本：\n{transcript_text}",
            )
            if summary:
                # 用 replace 精确匹配（old_summary_ph 和 new ph 不同）
                if old_summary_ph in content:
                    content = content.replace(old_summary_ph, summary.strip())
                else:
                    content = content.replace(placeholders[0], summary.strip())
                changed = True
                print(f"   ✅ 摘要已写入")
        except Exception as e:
            print(f"   ⚠️ 摘要生成失败: {e}")

    # ===== 第 2 阶段：思维导图 =====
    if placeholders[1] in content:
        print("   🧠 生成思维导图...")
        try:
            mindmap = _call_llm(
                "你是一个结构化整理助手。请根据转录文本生成一份思维导图，"
                "使用缩进的 Markdown 列表格式（2空格缩进）。\n"
                "格式示例：\n"
                "- 主题\n  - 子主题\n    - 要点\n"
                "要求：层次清晰、要点精炼、覆盖全文核心内容。",
                f"视频标题：{title}\n\n转录文本：\n{transcript_text}",
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            if mindmap:
                content = content.replace(placeholders[1], mindmap.strip())
                changed = True
                print(f"   ✅ 思维导图已写入")
        except Exception as e:
            print(f"   ⚠️ 思维导图生成失败: {e}")

    # ===== 第 3 阶段：原文校对 =====
    if placeholders[2] in content:
        print("   🔍 AI校对转录文本...")
        try:
            # 构建领域专有名词提示
            domain_terms = _build_domain_prompt(PROOFREAD_DOMAINS)

            proofread = _call_llm(
                "你是一个文字校对员。请校对并修正以下语音转文字的转录文本。\n"
                "规则：\n"
                "1) 修正明显的同音错别字和语音识别错误\n"
                "2) 修复断句问题（合并不合理的断句、拆分超长句）\n"
                "3) 去除口语填充词（如过多的「嗯」「啊」「就是说」）\n"
                "4) 修正标点符号，使文本更易读\n"
                "5) 严禁增删实质性内容，严禁改变原意和说话风格\n"
                + domain_terms +
                "7) 输出完整的校对后文本",
                f"视频标题：{title}\n\n原始转录文本：\n{transcript_text}",
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            if proofread:
                content = content.replace(placeholders[2], proofread.strip())
                changed = True
                print(f"   ✅ AI校对已写入")
        except Exception as e:
            print(f"   ⚠️ AI校对失败: {e}")

    if changed:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    return changed


def print_summary_stats(report_rows):
    """打印转录来源分布统计"""
    sources = {}
    for row in report_rows:
        if row["status"] == "success":
            s = row["source"]
            sources[s] = sources.get(s, 0) + 1
    if sources:
        print(f"\n   📝 转录来源分布:")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"      - {src}: {count} 个")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="B站收藏夹批量转录")
    parser.add_argument("--local-dir", default=None, help="转录本地目录中的媒体文件")
    args = parser.parse_args()

    # ===== 模式：本地目录转录 =====
    if args.local_dir:
        local_dir = os.path.expanduser(args.local_dir)
        if not os.path.isdir(local_dir):
            print(f"❌ 目录不存在: {local_dir}")
            return 1

        print("=" * 70)
        print("📼 本地目录批量转录 v3.0")
        print("=" * 70)

        start_time = time.time()
        output_files, returncode = transcribe_local_dir(local_dir)

        # 生成摘要
        if SUMMARY_API_KEY and output_files:
            print(f"\n📝 生成 AI 摘要...")
            for f in output_files:
                try:
                    generate_summary(f)
                except Exception as e:
                    print(f"   ⚠️ 摘要生成异常: {e}")

        total_time = time.time() - start_time
        print(f"\n⏱️  总耗时: {int(total_time // 60)}分{int(total_time % 60)}秒")
        return returncode

    # ===== 模式：B站收藏夹转录 =====
    print("=" * 70)
    print("📼 B站收藏夹批量转录 v3.0")
    print("=" * 70)

    videos = scan_videos()
    if not videos:
        print("没有新视频需要转录")
        return 0

    processed = load_processed()
    pending = [v for v in videos if v["avid"] not in processed]
    total = len(videos)
    remaining = len(pending)

    print(f"\n📊 总计 {total} 个视频")
    print(f"✅ 已处理 {total - remaining} 个")
    print(f"⏳ 待处理 {remaining} 个")

    if remaining == 0:
        print("🎉 全部视频已转录完成！")
        return 0

    enable_summary = bool(SUMMARY_API_KEY)

    if enable_summary:
        print(f"📝 AI摘要生成: 已启用 (模型: {SUMMARY_MODEL})")
    else:
        print(f"📝 AI摘要生成: 未启用（在 env.local 中设置 SUMMARY_API_KEY 可开启）")

    start_time = time.time()
    success_count = 0
    fail_count = 0
    report_rows = []

    for i, v in enumerate(pending, 1):
        bvid = v["bvid"]
        current_remaining = remaining - i + 1

        elapsed = time.time() - start_time if i > 1 else 0
        if elapsed > 0 and success_count > 0:
            avg_time = elapsed / success_count
            eta = avg_time * current_remaining
            print(f"\n⏱️  已用: {int(elapsed // 60)}分{int(elapsed % 60)}秒"
                  f" | 预计剩余: {int(eta // 60)}分{int(eta % 60)}秒")

        print(f"\n📌 [{total - remaining + i}/{total}] {v['title']}")
        print(f"   ⏱️  {v['duration']} | 👤 {v['upper']}")

        # 带重试的转录
        ok = False
        output_file = None
        transcript_source = None
        used_stt = False
        max_attempts = MAX_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            ok, output_path, transcript_source, used_stt = transcribe_video(
                bvid, attempt, max_attempts
            )
            if ok:
                output_file = output_path
                break
            if used_stt:
                print("   ⏭️ Qwen3-ASR 失败，跳过重试（模型加载耗时）")
                break
            if attempt <= MAX_RETRIES:
                wait = BATCH_DELAY * attempt
                print(f"   ⏳ 等待 {wait} 秒后重试...")
                time.sleep(wait)

        if ok and output_file and output_file != "unknown":
            content_hash = get_content_hash(output_file)

            report_rows.append({
                "bvid": bvid,
                "title": v["title"],
                "author": v["upper"],
                "duration": v["duration"],
                "source": transcript_source or "unknown",
                "output_file": output_file,
                "content_hash": content_hash,
                "status": "success",
                "attempts": attempt,
            })

            success_count += 1
            save_processed(v["avid"])
            print(f"   ✅ [{success_count}/{remaining}] 成功! 来源: {transcript_source}")

            # AI摘要生成
            if enable_summary and output_file and output_file != "unknown":
                try:
                    generate_summary(output_file)
                except Exception as e:
                    print(f"   ⚠️ 摘要生成异常: {e}")

        else:
            report_rows.append({
                "bvid": bvid,
                "title": v["title"],
                "author": v["upper"],
                "duration": v["duration"],
                "source": "失败",
                "output_file": "",
                "content_hash": "",
                "status": f"failed_after_{attempt}_attempts",
                "attempts": attempt,
            })

            fail_count += 1
            print(f"   ❌ [{fail_count}] 失败 (尝试{attempt}次后放弃)")

        # 视频间延迟
        if i < len(pending):
            time.sleep(BATCH_DELAY)

    # 生成报告
    total_time = time.time() - start_time
    print(f"\n{'=' * 70}")
    print(f"📊 批量转录完成")
    print(f"{'=' * 70}")
    print(f"   总计: {remaining} 个")
    print(f"   成功: {success_count} 个 ✅")
    print(f"   失败: {fail_count} 个 {'❌' if fail_count else '✅'}")
    print(f"   耗时: {int(total_time // 60)}分{int(total_time % 60)}秒")

    if report_rows:
        with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "bvid", "title", "author", "duration",
                "source", "output_file", "content_hash",
                "status", "attempts",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"   📄 报告已保存: {REPORT_FILE}")
        print_summary_stats(report_rows)

    # 列出失败项
    if fail_count:
        print(f"\n   ❌ 失败列表:")
        for row in report_rows:
            if row["status"] != "success":
                print(f"      - {row['bvid']} {row['title']}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
