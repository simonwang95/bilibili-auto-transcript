#!/usr/bin/env python3
"""
将日期目录（YYYY-MM）下的 .md 文件按内容分类到技术/财经等目录，删除空日期目录。

用法：
  python scripts/organize_categories.py                     # 自动分类（需 LLM）
  python scripts/organize_categories.py --dry-run           # 仅预览，不动文件
  python scripts/organize_categories.py --category 技术 /path/to/file.md  # 手动归类单个文件

分类依据：读取 .md 文件的标题 + 摘要 + 思维导图，调用 LLM 判断归属。
"""

import os
import re
import shutil
import sys

import requests

# ===== 加载 env.local 配置 =====
def _load_env_local():
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

def _expand_path(raw):
    return os.path.expanduser(os.path.expandvars(raw))

OUTPUT_DIR = _expand_path(_env.get("OUTPUT_DIR", "~/workspace/knowledge/bilibili"))
SUMMARY_API_KEY = _env.get("SUMMARY_API_KEY", "")
SUMMARY_API_URL = _env.get("SUMMARY_API_URL", "http://127.0.0.1:1234/v1")
SUMMARY_MODEL = _env.get("SUMMARY_MODEL", "auto")

# 默认分类标签
DEFAULT_CATEGORIES = ["技术", "财经", "生活", "教育", "其他"]

# 日期目录正则：YYYY-MM
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}$")


def list_date_dirs():
    """列出 OUTPUT_DIR 下所有日期目录"""
    if not os.path.isdir(OUTPUT_DIR):
        return []
    dirs = []
    for name in os.listdir(OUTPUT_DIR):
        full = os.path.join(OUTPUT_DIR, name)
        if os.path.isdir(full) and DATE_DIR_RE.match(name):
            dirs.append(full)
    return sorted(dirs)


def list_md_files(directory):
    """列出目录中所有 .md 文件"""
    if not os.path.isdir(directory):
        return []
    return sorted([
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".md")
    ])


def extract_preview(filepath):
    """提取 .md 文件的前半部分（标题 + 摘要 + 思维导图），用于分类"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return ""

    # 截取到 完整原文 之前（或 AI校对 之后、原文之前）
    stop_at = content.find("## 完整原文")
    if stop_at == -1:
        stop_at = content.find("<details>")
    if stop_at == -1:
        return content[:3000]

    return content[:stop_at].strip()[:3000]


def classify_with_llm(title, preview):
    """调用 LLM 判断文件应归属的分类"""
    if not SUMMARY_API_KEY:
        return "其他"

    api_url = SUMMARY_API_URL.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    cats = "、".join(DEFAULT_CATEGORIES)
    prompt = (
        f"请根据以下视频标题和内容摘要，从 [{cats}] 中选择最匹配的一个分类。\n"
        f"只回复分类名称，不要多余文字。\n\n"
        f"标题：{title}\n\n摘要：{preview[:2000]}"
    )
    try:
        resp = requests.post(
            api_url,
            json={
                "model": SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": "你是一个内容分类助手。只回复分类名称。"},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 32,
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SUMMARY_API_KEY}",
            },
            timeout=30,
        )
        data = resp.json()
        if "choices" in data:
            result = data["choices"][0]["message"]["content"].strip()
        elif "content" in data:
            result = data["content"].strip()
        else:
            return "其他"
        # 验证返回值是合法分类
        for cat in DEFAULT_CATEGORIES:
            if cat in result:
                return cat
        return "其他"
    except Exception:
        return "其他"


def move_to_category(filepath, category, dry_run=False):
    """将文件移动到分类目录"""
    cat_dir = os.path.join(OUTPUT_DIR, category)
    if not dry_run:
        os.makedirs(cat_dir, exist_ok=True)
    basename = os.path.basename(filepath)
    target = os.path.join(cat_dir, basename)

    if os.path.exists(target) and not dry_run:
        # 同名文件已存在，跳过
        print(f"   ⏭️  跳过（已存在）: {basename}")
        return False

    if dry_run:
        print(f"   📋 [DRY RUN] {basename} → {category}/")
    else:
        shutil.move(filepath, target)
        print(f"   ✅ {basename} → {category}/")
    return True


def remove_empty_date_dirs(dry_run=False):
    """删除空的日期目录"""
    for d in list_date_dirs():
        if not os.listdir(d):  # 目录已空
            if dry_run:
                print(f"   📋 [DRY RUN] 删除空目录: {os.path.basename(d)}/")
            else:
                os.rmdir(d)
                print(f"   🗑️  已删除: {os.path.basename(d)}/")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="按内容分类整理转录文件")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际移动文件")
    parser.add_argument("--category", default=None, help="手动指定分类（配合文件路径参数使用）")
    parser.add_argument("file", nargs="?", default=None, help="单个文件路径（用于 --category）")
    args = parser.parse_args()

    # 模式：手动归类单个文件
    if args.category and args.file:
        filepath = os.path.expanduser(args.file)
        if not os.path.isfile(filepath):
            print(f"❌ 文件不存在: {filepath}")
            return 1
        move_to_category(filepath, args.category, dry_run=args.dry)
        return 0

    # 模式：自动分类所有日期目录下的文件
    print("=" * 60)
    print("📂 转录文件自动分类")
    print("=" * 60)

    date_dirs = list_date_dirs()
    if not date_dirs:
        print("没有找到日期目录（YYYY-MM 格式）")
        return 0

    all_files = []
    for d in date_dirs:
        files = list_md_files(d)
        if files:
            print(f"\n📁 {os.path.basename(d)}/ ({len(files)} 个文件)")
            all_files.extend(files)

    if not all_files:
        print("\n没有找到待分类的 .md 文件")
        remove_empty_date_dirs(dry_run=args.dry)
        return 0

    print(f"\n总计 {len(all_files)} 个文件待分类")
    if args.dry_run:
        print("⚠️  DRY RUN 模式：只预览，不实际操作")
    print()

    moved = 0
    for filepath in all_files:
        basename = os.path.basename(filepath)
        print(f"🔍 {basename}")

        # 提取标题
        title = basename.rsplit(".", 1)[0][:80]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                first = f.readline().strip()
                if first.startswith("# "):
                    title = first[2:].strip()
        except Exception:
            pass

        # 分类
        preview = extract_preview(filepath)
        category = classify_with_llm(title, preview)
        print(f"   🏷️  判定分类: {category}")

        if move_to_category(filepath, category, dry_run=args.dry_run):
            moved += 1

    print(f"\n已分类: {moved}/{len(all_files)}")

    # 清理空目录
    if not args.dry_run:
        remove_empty_date_dirs()
    else:
        remove_empty_date_dirs(dry_run=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
