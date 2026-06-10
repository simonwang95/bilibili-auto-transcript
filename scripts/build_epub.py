#!/usr/bin/env python3
"""将指定目录下的 .md 转录文件整理为 EPUB 电子书。

纯 Python 标准库实现，无需 pandoc / ebooklib 等外部依赖。

结构：
  文件夹层级 → EPUB 目录层级
  视频标题 → 文章章节

用法：
  python scripts/build_epub.py                      # 合并 OUTPUT_DIR 下所有笔记
  python scripts/build_epub.py --input-dir ./notes  # 指定输入根目录
  python scripts/build_epub.py --output-dir ./books # 指定 EPUB 输出目录
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

SKIP_DIRS = {"epub", "epub-build", "__pycache__"}


def natural_key(value: str) -> list:
    """自然排序：1, 2, 9, 10，而不是 1, 10, 2。"""
    parts = re.split(r"(\d+)", value)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


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


def section_xhtml(title: str, notes: list[dict[str, str]], children: list[dict] = None) -> str:
    children = children or []
    note_items = "\n".join(
        f'    <li><a href="{html.escape(Path(note["href"]).name, quote=True)}">{html.escape(note["title"])}</a></li>'
        for note in notes
    )
    child_items = "\n".join(
        f'    <li><a href="{html.escape(Path(child["href"]).name, quote=True)}">{html.escape(child["title"])}</a></li>'
        for child in children
    )
    note_block = f"<h2>文章</h2>\n<ol>\n{note_items}\n</ol>" if notes else ""
    child_block = f"<h2>子目录</h2>\n<ol>\n{child_items}\n</ol>" if children else ""
    body = f"""<h1>{html.escape(title)}</h1>
<p>直属文章 {len(notes)} 篇，子目录 {len(children)} 个</p>
{note_block}
{child_block}"""
    return chapter_xhtml(title + " — 目录", body)


def nav_xhtml(title: str, sections: list[dict]) -> str:
    def render_section(section: dict, level: int = 3) -> str:
        indent = "  " * level
        child_items = []
        for note in section["notes"]:
            child_items.append(
                f'{indent}  <li><a href="{html.escape(note["href"], quote=True)}">{html.escape(note["title"])}</a></li>'
            )
        for child in section.get("children", []):
            child_items.append(render_section(child, level + 1))
        children = ""
        if child_items:
            children = f"\n{indent}  <ol>\n{chr(10).join(child_items)}\n{indent}  </ol>\n{indent}"
        return (
            f'{indent}<li><a href="{html.escape(section["href"], quote=True)}">'
            f'{html.escape(section["title"])}</a>{children}</li>'
        )

    items = [render_section(section) for section in sections]
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
    play_order = 1

    def tree_depth(section_list: list[dict]) -> int:
        if not section_list:
            return 1
        depths = []
        for section in section_list:
            child_depth = tree_depth(section.get("children", [])) if section.get("children") else 0
            note_depth = 1 if section["notes"] else 0
            depths.append(1 + max(child_depth, note_depth))
        return max(depths)

    def render_note(note: dict, indent: str) -> str:
        nonlocal play_order
        order = play_order
        play_order += 1
        return f"""{indent}<navPoint id="navPoint-{order}" playOrder="{order}">
{indent}  <navLabel><text>{html.escape(note["title"])}</text></navLabel>
{indent}  <content src="{html.escape(note["href"], quote=True)}"/>
{indent}</navPoint>"""

    def render_section(section: dict, indent: str = "    ") -> str:
        nonlocal play_order
        order = play_order
        play_order += 1
        child_points = []
        for note in section["notes"]:
            child_points.append(render_note(note, indent + "  "))
        for child in section.get("children", []):
            child_points.append(render_section(child, indent + "  "))
        children = f"\n{chr(10).join(child_points)}" if child_points else ""
        return f"""{indent}<navPoint id="{section["id"]}" playOrder="{order}">
{indent}  <navLabel><text>{html.escape(section["title"])}</text></navLabel>
{indent}  <content src="{html.escape(section["href"], quote=True)}"/>{children}
{indent}</navPoint>"""

    nav_points = [render_section(section) for section in sections]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{uid}"/>
    <meta name="dtb:depth" content="{tree_depth(sections)}"/>
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

def new_dir_node(title: str, path: Path) -> dict:
    return {"title": title, "path": path, "note_paths": [], "children": []}


def build_note_tree(root_dir: Path) -> dict:
    """递归扫描 Markdown，保留文件夹嵌套关系。"""
    if not root_dir.is_dir():
        return None

    root_node = new_dir_node(root_dir.name or "根目录", root_dir)
    nodes = {root_dir: root_node}
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in SKIP_DIRS
        ]
        dirs.sort(key=natural_key)
        current_dir = Path(root)
        current_node = nodes[current_dir]

        for dirname in dirs:
            child_path = current_dir / dirname
            child_node = new_dir_node(dirname, child_path)
            current_node["children"].append(child_node)
            nodes[child_path] = child_node

        current_node["note_paths"].extend(
            current_dir / name
            for name in sorted(files, key=natural_key)
            if name.endswith(".md") and not name.startswith(".")
        )

    def prune(node: dict) -> dict:
        kept_children = []
        for child in node["children"]:
            pruned = prune(child)
            if pruned:
                kept_children.append(pruned)
        node["children"] = kept_children
        if node["note_paths"] or node["children"]:
            return node
        return None

    return prune(root_node)


def top_level_nodes(root_node: dict) -> list[dict]:
    if root_node["note_paths"]:
        return [root_node]
    return root_node["children"]


def count_notes(node: dict) -> int:
    return len(node["note_paths"]) + sum(count_notes(child) for child in node["children"])


def count_sections(section: dict) -> int:
    return 1 + sum(count_sections(child) for child in section.get("children", []))


def title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="递归合并 Markdown 生成 EPUB")
    parser.add_argument("--input-dir", type=Path, default=None, help="输入根目录（默认读取 OUTPUT_DIR，递归扫描）")
    parser.add_argument("--output-dir", type=Path, default=None, help="EPUB 输出目录")
    parser.add_argument("--title", default="B站视频转录合集", help="EPUB 标题")
    parser.add_argument("--author", default="Bilibili Auto Transcript", help="EPUB 作者")
    parser.add_argument("--keep-build", action="store_true", help="保留临时构建目录")
    args = parser.parse_args()

    input_dir = args.input_dir.expanduser().resolve() if args.input_dir else OUTPUT_DIR
    epub_dir = args.output_dir.resolve() if args.output_dir else EPUB_OUTPUT_DIR

    note_tree = build_note_tree(input_dir)
    if not note_tree:
        print("没有可导出的 .md 文件")
        return 2

    top_nodes = top_level_nodes(note_tree)
    total_files = count_notes(note_tree)

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
    section_idx = 0

    print("=" * 60)
    print("📚 生成 EPUB")
    print(f"📂 输入目录: {input_dir}")
    print(f"📦 输出目录: {epub_dir}")
    print("=" * 60)

    def build_section(node: dict, depth: int = 0) -> tuple[dict, list[dict[str, str]]]:
        nonlocal note_idx, section_idx
        section_idx += 1
        section_id = f"section{section_idx:03d}"
        section_href = f"chapters/{section_id}.xhtml"
        section_notes = []
        section_children = []
        section_pages = [{"id": section_id, "href": section_href, "title": node["title"]}]

        indent = "  " * depth
        print(f"\n{indent}📁 {node['title']}（直属 {len(node['note_paths'])} 篇，合计 {count_notes(node)} 篇）")

        for fp in node["note_paths"]:
            text = fp.read_text(encoding="utf-8")
            title = title_from_markdown(text, fp.stem[:80])
            note_idx += 1
            body = markdown_to_xhtml(strip_fulltext(text))
            chapter_id = f"chapter{note_idx:03d}"
            href = f"chapters/{chapter_id}.xhtml"
            write_text(build_dir / "OEBPS" / href, chapter_xhtml(title, body))
            note_page = {"id": chapter_id, "href": href, "title": title}
            section_notes.append(note_page)
            section_pages.append(note_page)
            print(f"{indent}  ✅ {title[:60]}")

        for child in node["children"]:
            child_section, child_pages = build_section(child, depth + 1)
            section_children.append(child_section)
            section_pages.extend(child_pages)

        write_text(
            build_dir / "OEBPS" / section_href,
            section_xhtml(node["title"], section_notes, section_children),
        )
        section = {
            "id": section_id,
            "href": section_href,
            "title": node["title"],
            "notes": section_notes,
            "children": section_children,
        }
        return section, section_pages

    for node in top_nodes:
        section, section_pages = build_section(node)
        sections.append(section)
        pages.extend(section_pages)

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
    total_sections = sum(count_sections(section) for section in sections)
    print(f"   目录: {total_sections} 个 | 文章: {total_files} 篇")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
