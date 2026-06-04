# B站 API 参考

本文档记录了 bilibili-auto-transcript 项目使用的 B站开放 API。

---

## 收藏夹列表 API

### 端点

```
GET https://api.bilibili.com/x/v3/fav/resource/list
```

### 请求参数

| 参数 | 类型 | 必需 | 说明 | 限制 |
|------|------|------|------|------|
| `media_id` | int | ✅ | 收藏夹 ID，从 URL `?fid=` 后的数字获取 | — |
| `ps` | int | ❌ | 每页返回的视频数量 | **最大 20**，超过返回 `code=-400`「请求错误」 |
| `pn` | int | ❌ | 页码，从 1 开始 | 默认 1 |

### 请求头

```http
GET /x/v3/fav/resource/list?media_id=3972051046&ps=20&pn=1 HTTP/1.1
Host: api.bilibili.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
```

User-Agent 不是严格必需的，但建议设置一个真实的浏览器 UA 避免被限流。

### 认证

- **公开收藏夹**：无需 Cookie，直接 GET 即可
- **私有收藏夹**：需要携带 B站登录态 Cookie（`Cookie` 请求头）

本项目扫描器使用公开收藏夹访问，无需 Cookie。转录脚本通过 yt-dlp 的 Cookie 支持获取需要登录态的字幕。

### 响应结构

```json
{
  "code": 0,
  "message": "OK",
  "data": {
    "info": {
      "title": "收藏夹名称",
      "media_count": 156
    },
    "medias": [
      {
        "id": 116366820508713,
        "type": 2,
        "title": "视频标题",
        "cover": "https://i0.hdslb.com/bfs/archive/xxx.jpg",
        "intro": "",
        "page": 1,
        "duration": 298,
        "upper": {
          "mid": 123456,
          "name": "UP主名称",
          "face": "https://i0.hdslb.com/bfs/face/xxx.jpg"
        },
        "cnt_info": {
          "collect": 1234,
          "play": 56789,
          "danmaku": 123
        },
        "bvid": "BV1rPDkB7ESC",
        "pubtime": 1775616958,
        "fav_time": 1779933181
      }
    ],
    "has_more": false
  }
}
```

### 项目使用的字段

| 字段路径 | 变量名 | 用途 |
|----------|--------|------|
| `medias[].id` | `avid` | 数字 ID，去重追踪 key |
| `medias[].bvid` | `bvid` | BV 号，构建视频 URL |
| `medias[].bv_id` | `bvid`（备用） | 部分 API 版本使用此字段名 |
| `medias[].title` | `title` | 视频标题 |
| `medias[].duration` | `duration` | 视频时长（秒） |
| `medias[].upper.name` | `upper` | UP 主名称 |
| `medias[].pubtime` | `pubtime` | 发布时间（Unix 时间戳） |
| `data.has_more` | — | 是否有下一页（分页控制） |

### 分页处理

B站 API 的 `ps` 参数最大只支持 20。对于超过 20 个视频的收藏夹，需要分页请求：

```python
pn = 1
all_medias = []
while True:
    resp = requests.get(f"{API_BASE}?media_id={ID}&ps=20&pn={pn}")
    data = resp.json()
    all_medias.extend(data["data"]["medias"])
    if not data["data"]["has_more"]:
        break
    pn += 1
```

### 常见问题

**ps > 20 返回错误**:
```json
{"code": -400, "message": "请求错误"}
```
解决方案：始终使用 `ps=20` 并通过 `pn` 分页。

**curl -L 导致错误**:
不要给 B站 API 请求加 `-L`（跟随重定向）参数。这会导致返回非 JSON 内容或错误响应。
```bash
# ✅ 正确
curl -s "https://api.bilibili.com/x/v3/fav/resource/list?media_id=xxx&ps=20"

# ❌ 错误
curl -s -L "https://api.bilibili.com/x/v3/fav/resource/list?media_id=xxx&ps=20"
```

**bvid 字段位置不一致**:
部分 API 响应使用 `bvid` 字段，部分使用 `bv_id`。项目代码同时检查两个字段：
```python
bvid = m.get("bvid", "") or m.get("bv_id", "")
```

---

## Cookie 获取（yt-dlp 方式）

当需要访问私有收藏夹或获取 AI 字幕时，需要 B站登录态 Cookie。

### WSL Chromium

```bash
CHROMIUM_PATH="$HOME/snap/chromium/common/chromium"
yt-dlp \
  --cookies-from-browser "chromium:$CHROMIUM_PATH" \
  --cookies /tmp/bili_cookies.txt \
  --skip-download \
  --print title \
  "https://www.bilibili.com/video/BV1rPDkB7ESC/"
```

### Windows Edge

```bash
WIN_USER=$(ls /mnt/c/Users/ | grep -v "Public\|Default\|All Users" | head -1)
yt-dlp \
  --cookies-from-browser "edge:C:/Users/$WIN_USER/AppData/Local/Microsoft/Edge/User Data" \
  --cookies /tmp/bili_cookies.txt \
  --skip-download \
  --print title \
  "https://www.bilibili.com/video/BV1rPDkB7ESC/"
```

### 注意事项

- `--cookies` 参数每次调用会覆盖目标文件，不要在同一个 tick 内多次调用
- Cookie 有效期约 30 天，过期后需要重新登录
- yt-dlp 提取 Cookie 时需要浏览器完全关闭（Chromium 尤其如此）

---

## curl 测试示例

```bash
# 获取公开收藏夹内容
curl -s "https://api.bilibili.com/x/v3/fav/resource/list?media_id=3972051046&ps=20&pn=1" | python3 -m json.tool

# 带 Cookie 访问私有收藏夹
curl -s -b /tmp/bili_cookies.txt "https://api.bilibili.com/x/v3/fav/resource/list?media_id=xxx&ps=20&pn=1"

# 检查收藏夹总页数
curl -s "https://api.bilibili.com/x/v3/fav/resource/list?media_id=3972051046&ps=20" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'总数: {d[\"data\"][\"info\"][\"media_count\"]}, has_more: {d[\"data\"][\"has_more\"]}')"
```

---

## API 限制与最佳实践

| 限制 | 说明 | 应对措施 |
|------|------|---------|
| `ps` 最大 20 | 单页最多 20 条 | 循环分页直到 `has_more=false` |
| 公开收藏夹无需认证 | Cookie 仅用于 AI 字幕获取 | Scanner 不依赖 Cookie |
| 请求频率限制 | B站有风控机制 | 视频间延迟 3 秒（`BATCH_DELAY`） |
| Cookie 过期 | 约 30 天 | 脚本检测最后使用时间并提示 |
| 响应字段不稳定 | `bvid` vs `bv_id` | 代码同时检查两个字段 |
