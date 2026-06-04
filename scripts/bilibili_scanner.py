#!/usr/bin/env python3
"""
B站收藏夹快速扫描脚本 v1.2 - 只扫描，不转录
输出新视频列表供 AI Agent 处理（生成摘要、通知等）
自动分页，确保收藏夹中所有视频都被扫描。

配置：编辑项目根目录的 env.local 文件

支持公开和私有收藏夹：
  - 公开收藏夹：无需额外配置，FAV_MEDIA_ID 即可
  - 私有收藏夹：在 env.local 中设置 BILI_COOKIE_FILE 指向 Netscape 格式 Cookie 文件
    Cookie 文件可通过浏览器扩展导出，或用 yt-dlp --cookies-from-browser 生成：
      yt-dlp --cookies-from-browser chromium --cookies ./bili_cookies.txt --skip-download --print title "https://www.bilibili.com/video/BVxxx/"
"""

import os
import sys

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

FAV_MEDIA_ID = _env.get("FAV_MEDIA_ID", "")

def _expand_path(raw):
    """展开路径中的 $HOME / $VAR 和 ~"""
    return os.path.expanduser(os.path.expandvars(raw))

STATE_DIR = _expand_path(
    _env.get("STATE_DIR", "~/.openclaw/workspace/.auto-transcript-state")
)
COOKIE_FILE = _expand_path(
    _env.get("BILI_COOKIE_FILE", "")
)
PROCESSED_FILE = os.path.join(STATE_DIR, "processed_videos.txt")
API_BASE = "https://api.bilibili.com/x/v3/fav/resource/list"


def _load_cookies():
    """从 Netscape 格式 Cookie 文件加载 Cookie，转为 requests 可用的 dict"""
    cookies = {}
    if not COOKIE_FILE or not os.path.exists(COOKIE_FILE):
        return cookies
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    domain, _, path, secure, expires, name, value = parts[:7]
                    cookies[name] = value
    except Exception:
        pass
    return cookies


def fetch_all_medias():
    """分页获取收藏夹中的所有视频"""
    all_medias = []
    pn = 1
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }
    cookies = _load_cookies()

    if cookies:
        print(f"STATUS:COOKIE_FILE_LOADED:{len(cookies)}cookies", file=sys.stderr)
    else:
        print("STATUS:NO_COOKIE", file=sys.stderr)

    while True:
        url = f"{API_BASE}?media_id={FAV_MEDIA_ID}&ps=20&pn={pn}"
        try:
            resp = requests.get(
                url, headers=headers, cookies=cookies if cookies else None, timeout=30
            )
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"ERROR: 网络请求失败 - {e}")
            sys.exit(1)
        except ValueError as e:
            print(f"ERROR: API响应解析失败 - {e}")
            sys.exit(1)

        if data.get("code") != 0:
            msg = data.get("message", "未知错误")
            if "权限不足" in msg or "访问权限" in msg:
                print(f"ERROR: {msg}")
                print("HINT: 收藏夹可能为私有，请选择以下任一方式解决：")
                print("  1) 在B站将收藏夹设为「公开」")
                print("  2) 在 env.local 中设置 BILI_COOKIE_FILE 指向 Cookie 文件")
                print("     Cookie 文件生成方法：")
                print("     yt-dlp --cookies-from-browser chromium --cookies ./bili_cookies.txt \\")
                print("       --skip-download --print title \"https://www.bilibili.com/video/BVxxx/\"")
            else:
                print(f"ERROR: B站API返回错误 (code={data.get('code')}) - {msg}")
            sys.exit(1)

        medias = data["data"].get("medias", [])
        all_medias.extend(medias)

        if not data["data"].get("has_more"):
            break
        pn += 1

    return all_medias


def main():
    if not FAV_MEDIA_ID:
        print("ERROR: 请先设置收藏夹ID！编辑项目根目录的 env.local，设置 FAV_MEDIA_ID")
        return 1

    os.makedirs(STATE_DIR, exist_ok=True)

    # 分页获取收藏夹所有视频
    medias = fetch_all_medias()
    print(f"COLLECTION_TOTAL:{len(medias)}")

    # 加载已处理记录
    processed = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            processed = set(line.strip() for line in f if line.strip())
    print(f"PROCESSED:{len(processed)}")

    # 找出新视频
    new_videos = []
    for m in medias:
        avid = str(m["id"])
        if avid not in processed:
            new_videos.append({
                "avid": avid,
                "bvid": m.get("bvid", "") or m.get("bv_id", ""),
                "title": m["title"],
                "duration": m["duration"],
                "upper": m["upper"]["name"],
                "pubtime": m.get("pubtime", 0),
            })

    if not new_videos:
        print("ALL_CAUGHT_UP")
        return 0

    print(f"NEW_VIDEOS:{len(new_videos)}")
    for v in new_videos:
        mins = v["duration"] // 60
        secs = v["duration"] % 60
        print(f"  - AVID:{v['avid']}")
        print(f"    BVID:{v['bvid']}")
        print(f"    TITLE:{v['title']}")
        print(f"    DURATION:{mins}分{secs}秒")
        print(f"    UPPER:{v['upper']}")
        print(f"    PUBTIME:{v['pubtime']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
