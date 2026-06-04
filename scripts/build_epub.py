#!/usr/bin/env python3
"""将分类目录下的 .md 转录文件整理为 EPUB 电子书。

纯 Python 标准库实现，无需 pandoc / ebooklib 等外部依赖。

结构：
  分类名 → 一级目录（EPUB 章节）
  视频标题 → 二级目录（子章节）

用法：
  python scripts/build_epub.py                     # 合并所有分类
  python scripts/build_epub.py --output-dir ./books # 指定输出目录
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path


# ===== 加载 env.local 配置 =====
def _load_env_local():
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent
    env_file = project_dir / "env.local"
    config = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
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
    return Path(os.path.expanduser(os.path.expandvars(raw)))

OUTPUT_DIR = _expand_path(_env.get("OUTPUT_DIR", "~/workspace/knowledge/bilibili"))
EPUB_OUTPUT_DIR = _expand_path(
    _env.get("EPUB_OUTPUT_DIR", str(OUTPUT_DIR / "epub"))
)

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
SKIP_DIRS = {"local", "epub"}


# ── markdown 解析 ──────────────────────────────────────────────

def inline_to_html(text: str) -> str:
    """处理行内元素：粗体、行内代码、链接"""
    parts = text.split("`")
    rendered = []
    for i, part in enumerate(parts):
        escaped = html.escape(part)
        if i % 2:
            rendered.append(f"<code>{escaped}</code>")
            continue
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        rendered.append(escaped)
    return "".join(rendered)


def strip_fulltext(text: str) -> str:
    """剔除「完整原文」折叠块 (v1.0)。

    支持两种格式：
    1. <details><summary>📄 完整原文</summary>...</details>
    2. ## 完整原文（旧格式）
    """
    details_start = text.find("<details>")
    if details_start != -1:
        details_end = text.find("</details>", details_start)
        if details_end != -1:
            return text[:details_start].rstrip() + "\n" + text[details_end + len("</details>"):]
    heading = "## 完整原文"
    pos = text.find(heading)
    if pos != -1:
        rest = text[pos + len(heading):]
        next_section = re.search(r"\n## ", rest)
        if next_section:
            return text[:pos].rstrip() + rest[next_section.start():]
        return text[:pos].rstrip() + "\n"
    return text


def markdown_to_xhtml(text: str) -> str:
    """将 Markdown 转为 XHTML body 片段。

    列表：<li> 延迟闭合，支持任意嵌套层级。
    引用块：每条 > 独立一个 blockquote。
    """
    out = []
    li_stack = []     # 栈元素 = 缩进级别
    in_code = False
    code_lines = []

    def _pop_to(level):
        nonlocal li_stack
        while li_stack and li_stack[-1] > level:
            out.append("</li></ul>")
            li_stack.pop()

    def _pop_all():
        nonlocal li_stack
        while li_stack:
            out.append("</li></ul>")
            li_stack.pop()

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code:
                out.append("<pre><code>")
                out.append(html.escape("\n".join(code_lines)))
                out.append("</code></pre>")
                code_lines = []
                in_code = False
            else:
                _pop_all()
                in_code = True
            continue
        if in_code:
            code_lines.append(raw_line)
            continue

        # 空行 — 不关闭列表（思维导图内多级嵌套间常有空行）
        if not stripped:
            continue

        # ── 自此以下 stripped 非空 ──

        # 标题
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            _pop_all()
            level = len(heading.group(1))
            content = inline_to_html(heading.group(2).strip())
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # 分隔线
        if stripped == "---":
            _pop_all()
            out.append("<hr/>")
            continue

        # 无序列表
        ul_match = re.match(r"^(  )*(- |\* )(.+)$", raw_line)
        if ul_match:
            indent = (len(raw_line) - len(raw_line.lstrip())) // 2
            content = inline_to_html(ul_match.group(3).strip())

            if not li_stack:
                out.append(f"<ul><li>{content}")
                li_stack.append(indent)
            elif indent == li_stack[-1]:
                out.append(f"</li><li>{content}")
            elif indent > li_stack[-1]:
                out.append(f"<ul><li>{content}")
                li_stack.append(indent)
            else:
                _pop_to(indent)
                if li_stack and li_stack[-1] == indent:
                    out.append(f"</li><li>{content}")
                else:
                    out.append("<ul>")
                    out.append(f"<li>{content}")
                    li_stack.append(indent)
            continue

        # 有序列表
        ol_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ol_match:
            _pop_all()
            out.append("<ol>")
            out.append(f"<li>{inline_to_html(ol_match.group(1).strip())}</li>")
            out.append("</ol>")
            continue

        # 引用块
        if stripped.startswith(">"):
            _pop_all()
            content = inline_to_html(stripped.lstrip("> ").strip())
            out.append(f"<blockquote><p>{content}</p></blockquote>")
            continue

        # 普通段落
        _pop_all()
        out.append(f"<p>{inline_to_html(stripped)}</p>")

    # 文档结束
    _pop_all()
    if in_code:
        out.append("<pre><code>")
        out.append(html.escape("\n".join(code_lines)))
        out.append("</code></pre>")

    return "\n".join(out)


# ── EPUB 结构 ──────────────────────────────────────────────────

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def chapter_xhtml(title: str, body: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN" xml:lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css" />
</head>
<body>
{body}
</body>
</html>
"""


def section_xhtml(title: str, notes: list[dict[str, str]]) -> str:
    items = "\n".join(
        f'    <li><a href="{html.escape(Path(note["href"]).name, quote=True)}">{html.escape(note["title"])}</a></li>'
        for note in notes
    )
    body = f"""<h1>{html.escape(title)}</h1>
<p>共 {len(notes)} 篇</p>
<ol>
{items}
</ol>"""
    return chapter_xhtml(title + " — 目录", body)


def nav_xhtml(title: str, sections: list[dict]) -> str:
    items = []
    for section in sections:
        notes = "\n".join(
            f'        <li><a href="{html.escape(note["href"], quote=True)}">{html.escape(note["title"])}</a></li>'
            for note in section["notes"]
        )
        items.append(
            f"""      <li><a href="{html.escape(section["href"], quote=True)}">{html.escape(section["title"])}</a>
      <ol>
{notes}
      </ol>
      </li>"""
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)} - 目录</title>
  <link rel="stylesheet" type="text/css" href="styles/style.css" />
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
{chr(10).join(items)}
    </ol>
  </nav>
</body>
</html>
"""


def toc_ncx(uid: str, title: str, sections: list[dict]) -> str:
    nav_points = []
    play_order = 1
    for section_index, section in enumerate(sections, start=1):
        section_play_order = play_order
        play_order += 1
        child_points = []
        for note in section["notes"]:
            child_points.append(
                f"""      <navPoint id="navPoint-{play_order}" playOrder="{play_order}">
        <navLabel><text>{html.escape(note["title"])}</text></navLabel>
        <content src="{html.escape(note["href"], quote=True)}"/>
      </navPoint>"""
            )
            play_order += 1
        nav_points.append(
            f"""    <navPoint id="section-{section_index}" playOrder="{section_play_order}">
      <navLabel><text>{html.escape(section["title"])}</text></navLabel>
      <content src="{html.escape(section["href"], quote=True)}"/>
{chr(10).join(child_points)}
    </navPoint>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{uid}"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(title)}</text></docTitle>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>
"""


def content_opf(uid: str, title: str, author: str, pages: list[dict[str, str]]) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="style" href="styles/style.css" media-type="text/css"/>',
    ]
    for page in pages:
        manifest_items.append(
            f'<item id="{page["id"]}" href="{html.escape(page["href"], quote=True)}" media-type="application/xhtml+xml"/>'
        )
    spine_items = "\n".join(
        f'    <itemref idref="{page["id"]}"/>' for page in pages
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:creator>{html.escape(author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <meta property="dcterms:modified">{now}</meta>
  </metadata>
  <manifest>
    {chr(10).join(manifest_items)}
  </manifest>
  <spine toc="toc">
{spine_items}
  </spine>
</package>
"""


def stylesheet() -> str:
    return """body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  line-height: 1.65;
  margin: 0 5%;
  color: #222;
}
h1, h2, h3, h4, h5, h6 {
  line-height: 1.35;
  margin-top: 1.4em;
  margin-bottom: 0.5em;
}
h1 {
  border-bottom: 1px solid #d8d8d8;
  padding-bottom: 0.35em;
}
h2 { color: #333; }
h3 { color: #555; }
h4 { color: #666; }
p { margin: 0.5em 0; }
blockquote {
  border-left: 4px solid #ccc;
  color: #555;
  margin: 0.5em 0;
  padding: 0.2em 0 0.2em 1em;
}
blockquote p { margin: 0.5em 0; }
hr { border: none; border-top: 1px solid #e0e0e0; margin: 1.5em 0; }
ul, ol { padding-left: 1.8em; margin: 0.4em 0; list-style-position: outside; }
ul ul, ol ol, ul ol, ol ul { padding-left: 1.8em; margin: 0.15em 0; }
ul ul ul { padding-left: 1.6em; }
li { margin: 0.35em 0; line-height: 1.6; }
code {
  font-family: "SFMono-Regular", Consolas, monospace;
  background: #f2f2f2;
  padding: 0.05em 0.25em;
  border-radius: 3px;
}
pre code {
  display: block;
  padding: 0.8em;
  white-space: pre-wrap;
}
a { color: #4CAF50; text-decoration: none; }
"""


def zip_epub(build_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w") as epub:
        mimetype = build_dir / "mimetype"
        epub.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(build_dir.rglob("*")):
            if path.is_dir() or path == mimetype:
                continue
            epub.write(path, path.relative_to(build_dir), compress_type=zipfile.ZIP_DEFLATED)


# ── 主逻辑 ─────────────────────────────────────────────────────

def list_category_dirs() -> list[Path]:
    if not OUTPUT_DIR.is_dir():
        return []
    dirs = []
    for name in sorted(os.listdir(OUTPUT_DIR)):
        full = OUTPUT_DIR / name
        if full.is_dir() and name not in SKIP_DIRS and not DATE_DIR_RE.match(name):
            dirs.append(full)
    return dirs


def list_md_files(directory: Path) -> list[Path]:
    return sorted(
        [directory / f for f in os.listdir(directory) if f.endswith(".md")]
    )


def title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="合并分类目录生成 EPUB")
    parser.add_argument("--output-dir", type=Path, default=None, help="EPUB 输出目录")
    parser.add_argument("--title", default="B站视频转录合集", help="EPUB 标题")
    parser.add_argument("--author", default="Bilibili Auto Transcript", help="EPUB 作者")
    parser.add_argument("--keep-build", action="store_true", help="保留临时构建目录")
    args = parser.parse_args()

    epub_dir = args.output_dir.resolve() if args.output_dir else EPUB_OUTPUT_DIR

    category_dirs = list_category_dirs()
    if not category_dirs:
        print("没有找到分类目录")
        return 2

    # 组装数据
    groups = []
    for cat_dir in category_dirs:
        cat_name = cat_dir.name
        files = list_md_files(cat_dir)
        if not files:
            continue
        notes = []
        for fp in files:
            text = fp.read_text(encoding="utf-8")
            title = title_from_markdown(text, fp.stem[:80])
            notes.append((title, text))
        groups.append((cat_name, notes))

    if not groups:
        print("没有可导出的 .md 文件")
        return 2

    total_files = sum(len(n) for _, n in groups)

    # 构建目录
    build_dir = epub_dir / "epub-build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    (build_dir / "META-INF").mkdir(parents=True)
    (build_dir / "OEBPS" / "chapters").mkdir(parents=True)
    (build_dir / "OEBPS" / "styles").mkdir(parents=True)

    write_text(build_dir / "mimetype", "application/epub+zip")
    write_text(
        build_dir / "META-INF" / "container.xml",
        """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
    )
    write_text(build_dir / "OEBPS" / "styles" / "style.css", stylesheet())

    sections = []
    pages = []
    note_idx = 0

    print("=" * 60)
    print("📚 生成 EPUB")
    print("=" * 60)

    for section_idx, (group_title, notes) in enumerate(groups, start=1):
        section_id = f"section{section_idx:03d}"
        section_href = f"chapters/{section_id}.xhtml"
        section_notes = []

        print(f"\n📁 {group_title}（{len(notes)} 篇）")

        for title, text in notes:
            note_idx += 1
            body = markdown_to_xhtml(strip_fulltext(text))
            chapter_id = f"chapter{note_idx:03d}"
            href = f"chapters/{chapter_id}.xhtml"
            write_text(build_dir / "OEBPS" / href, chapter_xhtml(title, body))
            section_notes.append({"id": chapter_id, "href": href, "title": title})
            print(f"  ✅ {title[:60]}")

        write_text(
            build_dir / "OEBPS" / section_href,
            section_xhtml(group_title, section_notes),
        )
        section = {
            "id": section_id,
            "href": section_href,
            "title": group_title,
            "notes": section_notes,
        }
        sections.append(section)
        pages.append({"id": section_id, "href": section_href, "title": group_title})
        pages.extend(section_notes)

    # 末尾页
    colophon_id = f"colophon{note_idx + 1:03d}"
    colophon_href = f"chapters/{colophon_id}.xhtml"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    colophon_body = (
        f'<div style="text-align:center; margin-top:4em; color:#999;">'
        f"<p>— 全文完 —</p>"
        f'<p style="font-size:0.9em;">生成日期：{now}</p>'
        f'<p style="font-size:0.8em;">由 Bilibili Auto Transcript 自动生成</p>'
        f"</div>"
    )
    write_text(build_dir / "OEBPS" / colophon_href, chapter_xhtml("生成日期", colophon_body))
    pages.append({"id": colophon_id, "href": colophon_href, "title": "生成日期"})

    # 生成 EPUB 元文件
    uid = f"urn:uuid:{uuid.uuid4()}"
    write_text(build_dir / "OEBPS" / "nav.xhtml", nav_xhtml(args.title, sections))
    write_text(build_dir / "OEBPS" / "toc.ncx", toc_ncx(uid, args.title, sections))
    write_text(
        build_dir / "OEBPS" / "content.opf",
        content_opf(uid, args.title, args.author, pages),
    )

    # 打包
    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    out_path = epub_dir / f"bilibili-all-{date_str}.epub"
    zip_epub(build_dir, out_path)

    if not args.keep_build:
        shutil.rmtree(build_dir)

    print(f"\n{'=' * 60}")
    print(f"📦 已保存: {out_path}")
    print(f"   分类: {len(sections)} 个 | 文章: {total_files} 篇")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
