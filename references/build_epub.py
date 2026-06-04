#!/usr/bin/env python3
"""Build an EPUB ebook from Markdown notes.

This script intentionally uses only the Python standard library so it can run
on a fresh macOS machine without pandoc or extra packages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import mimetypes
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = ROOT / "notes"
DEFAULT_OUTPUT = ROOT / "dist" / "青枫浦上Q-视频图文笔记.epub"


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((<[^>]+>|[^)]+)\)")
README_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
SKIP_NOTE_NAMES = {"readme.md", "readme.source.md"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an EPUB from notes/*.md in README order."
    )
    parser.add_argument(
        "--notes-dir",
        type=Path,
        default=NOTES_DIR,
        help="Notes directory, default: notes",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output EPUB path, default: dist/青枫浦上Q-视频图文笔记.epub",
    )
    parser.add_argument(
        "--title",
        default="青枫浦上Q 视频图文笔记",
        help="EPUB title",
    )
    parser.add_argument("--author", default="青枫浦上Q", help="EPUB author")
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Do not embed images; replace image references with captions.",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help="Keep temporary build directory under dist/epub-build",
    )
    return parser.parse_args()


def note_groups(notes_dir: Path) -> list[tuple[str, list[Path]]]:
    readme = notes_dir / "README.md"
    groups: list[tuple[str, list[Path]]] = []
    current: tuple[str, list[Path]] | None = None
    seen: set[Path] = set()

    if readme.exists():
        for line in readme.read_text(encoding="utf-8").splitlines():
            heading = re.match(r"^##\s+(.+)$", line.strip())
            if heading:
                current = (heading.group(1).strip(), [])
                groups.append(current)
                continue

            for match in README_LINK_RE.finditer(line):
                rel = match.group(1).replace("%20", " ")
                path = (notes_dir / rel).resolve()
                if path.exists() and path.suffix == ".md" and path not in seen:
                    if current is None:
                        current = ("未分组", [])
                        groups.append(current)
                    current[1].append(path)
                    seen.add(path)

    for path in sorted(notes_dir.glob("**/*.md")):
        if path.name.lower() in SKIP_NOTE_NAMES:
            continue
        resolved = path.resolve()
        if resolved not in seen:
            relative = path.relative_to(notes_dir)
            group_title = relative.parts[0] if len(relative.parts) > 1 else "未分组"
            group = next((item for item in groups if item[0] == group_title), None)
            if group is None:
                group = (group_title, [])
                groups.append(group)
            group[1].append(resolved)
            seen.add(resolved)

    return [(title, paths) for title, paths in groups if paths]


def title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def clean_image_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1]
    return raw.strip()


def image_href(
    target: str,
    note_path: Path,
    build_dir: Path,
    image_manifest: dict[Path, str],
) -> tuple[str | None, str | None]:
    source = (note_path.parent / clean_image_target(target)).resolve()
    if not source.exists() or not source.is_file():
        return None, str(source)

    if source in image_manifest:
        return f"../{image_manifest[source]}", None

    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:12]
    suffix = source.suffix.lower() or ".bin"
    dest_rel = f"images/{digest}{suffix}"
    dest = build_dir / "OEBPS" / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    image_manifest[source] = dest_rel
    return f"../{dest_rel}", None


def inline_to_html(text: str) -> str:
    parts = text.split("`")
    rendered: list[str] = []
    for i, part in enumerate(parts):
        escaped = html.escape(part)
        if i % 2:
            rendered.append(f"<code>{escaped}</code>")
            continue

        escaped = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
            escaped,
        )
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        rendered.append(escaped)
    return "".join(rendered)


def close_lists(open_lists: list[str], out: list[str]) -> None:
    while open_lists:
        out.append(f"</{open_lists.pop()}>")


def markdown_to_xhtml(
    text: str,
    note_path: Path,
    build_dir: Path,
    image_manifest: dict[Path, str],
    embed_images: bool,
) -> tuple[str, list[str]]:
    out: list[str] = []
    warnings: list[str] = []
    open_lists: list[str] = []
    in_code = False
    code_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("<pre><code>")
                out.append(html.escape("\n".join(code_lines)))
                out.append("</code></pre>")
                code_lines = []
                in_code = False
            else:
                close_lists(open_lists, out)
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            close_lists(open_lists, out)
            continue

        image_match = IMAGE_RE.fullmatch(stripped)
        if image_match:
            close_lists(open_lists, out)
            alt = image_match.group(1).strip()
            target = clean_image_target(image_match.group(2))
            if not embed_images:
                caption = alt or target
                out.append(f'<p class="image-caption">[图片：{inline_to_html(caption)}]</p>')
                continue
            href, missing = image_href(target, note_path, build_dir, image_manifest)
            if missing:
                warnings.append(f"missing image: {note_path.relative_to(ROOT)} -> {target}")
                out.append(
                    f'<p class="missing-image">[缺失图片：{inline_to_html(target)}]</p>'
                )
                continue
            assert href is not None
            caption_html = inline_to_html(alt) if alt else ""
            out.append("<figure>")
            out.append(
                f'<img src="{html.escape(href, quote=True)}" alt="{html.escape(alt, quote=True)}" />'
            )
            if caption_html:
                out.append(f"<figcaption>{caption_html}</figcaption>")
            out.append("</figure>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            close_lists(open_lists, out)
            level = len(heading.group(1))
            content = inline_to_html(heading.group(2).strip())
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if unordered:
            if not open_lists or open_lists[-1] != "ul":
                close_lists(open_lists, out)
                out.append("<ul>")
                open_lists.append("ul")
            out.append(f"<li>{inline_to_html(unordered.group(1).strip())}</li>")
            continue

        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ordered:
            if not open_lists or open_lists[-1] != "ol":
                close_lists(open_lists, out)
                out.append("<ol>")
                open_lists.append("ol")
            out.append(f"<li>{inline_to_html(ordered.group(1).strip())}</li>")
            continue

        if stripped.startswith(">"):
            close_lists(open_lists, out)
            out.append(f"<blockquote><p>{inline_to_html(stripped.lstrip('> ').strip())}</p></blockquote>")
            continue

        close_lists(open_lists, out)
        out.append(f"<p>{inline_to_html(stripped)}</p>")

    close_lists(open_lists, out)
    if in_code:
        out.append("<pre><code>")
        out.append(html.escape("\n".join(code_lines)))
        out.append("</code></pre>")

    return "\n".join(out), warnings


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
<p>本章节包含 {len(notes)} 篇视频图文笔记。</p>
<ol>
{items}
</ol>"""
    return chapter_xhtml(title, body)


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


def content_opf(
    uid: str,
    title: str,
    author: str,
    pages: list[dict[str, str]],
    image_manifest: dict[Path, str],
) -> str:
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
    for index, rel in enumerate(sorted(image_manifest.values()), start=1):
        media_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        manifest_items.append(
            f'<item id="img{index}" href="{html.escape(rel, quote=True)}" media-type="{media_type}"/>'
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
}
h1, h2, h3, h4, h5, h6 {
  line-height: 1.35;
  margin-top: 1.4em;
}
h1 {
  border-bottom: 1px solid #d8d8d8;
  padding-bottom: 0.35em;
}
img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1em auto 0.35em;
}
figure {
  margin: 1.2em 0;
}
figcaption, .image-caption, .missing-image {
  color: #666;
  font-size: 0.9em;
  text-align: center;
}
code {
  font-family: "SFMono-Regular", Consolas, monospace;
  background: #f2f2f2;
  padding: 0.05em 0.25em;
}
pre code {
  display: block;
  padding: 0.8em;
  white-space: pre-wrap;
}
blockquote {
  border-left: 4px solid #ccc;
  color: #555;
  margin-left: 0;
  padding-left: 1em;
}
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


def main() -> int:
    args = parse_args()
    notes_dir = args.notes_dir.resolve()
    output = args.output.resolve()
    build_dir = output.parent / "epub-build"

    if not notes_dir.exists():
        print(f"notes directory not found: {notes_dir}", file=sys.stderr)
        return 2

    groups = note_groups(notes_dir)
    if not groups:
        print(f"no markdown notes found under: {notes_dir}", file=sys.stderr)
        return 2

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

    image_manifest: dict[Path, str] = {}
    sections: list[dict] = []
    pages: list[dict[str, str]] = []
    all_warnings: list[str] = []
    note_count = 0

    for section_index, (group_title, notes) in enumerate(groups, start=1):
        section_id = f"section{section_index:03d}"
        section_href = f"chapters/{section_id}.xhtml"
        section_notes: list[dict[str, str]] = []

        for note in notes:
            note_count += 1
            text = note.read_text(encoding="utf-8")
            title = title_from_markdown(text, note.stem)
            body, warnings = markdown_to_xhtml(
                text,
                note,
                build_dir,
                image_manifest,
                embed_images=not args.no_images,
            )
            all_warnings.extend(warnings)
            chapter_id = f"chapter{note_count:03d}"
            href = f"chapters/{chapter_id}.xhtml"
            write_text(build_dir / "OEBPS" / href, chapter_xhtml(title, body))
            section_notes.append({"id": chapter_id, "href": href, "title": title})

        section = {
            "id": section_id,
            "href": section_href,
            "title": group_title,
            "notes": section_notes,
        }
        write_text(
            build_dir / "OEBPS" / section_href,
            section_xhtml(group_title, section_notes),
        )
        sections.append(section)
        pages.append({"id": section_id, "href": section_href, "title": group_title})
        pages.extend(section_notes)

    uid = f"urn:uuid:{uuid.uuid4()}"
    write_text(build_dir / "OEBPS" / "nav.xhtml", nav_xhtml(args.title, sections))
    write_text(build_dir / "OEBPS" / "toc.ncx", toc_ncx(uid, args.title, sections))
    write_text(
        build_dir / "OEBPS" / "content.opf",
        content_opf(uid, args.title, args.author, pages, image_manifest),
    )

    zip_epub(build_dir, output)

    print(f"EPUB written: {output}")
    print(f"Sections: {len(sections)}")
    print(f"Notes: {note_count}")
    print(f"Spine items: {len(pages)}")
    print(f"Images embedded: {0 if args.no_images else len(image_manifest)}")
    if all_warnings:
        print("Warnings:", file=sys.stderr)
        for warning in all_warnings:
            print(f"- {warning}", file=sys.stderr)

    if not args.keep_build:
        shutil.rmtree(build_dir)
    else:
        print(f"Build directory kept: {build_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
