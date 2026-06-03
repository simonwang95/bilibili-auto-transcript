#!/bin/bash
# B站视频字幕智能获取脚本 v4.0
# 功能：CC字幕 → AI字幕 → Qwen3-ASR 转录（三级降级）
# 支持：WSL Chromium/Edge Cookie、多语言AI字幕、CUDA/ROCm/MPS/CPU、音频优化
# v4.0 新增：Qwen3-ASR 替换 Whisper，自动选择 1.7B(GPU) / 0.6B(CPU)

VIDEO_URL="$1"
OUTPUT_DIR="${2:-$HOME/workspace/knowledge/bilibili}"
mkdir -p "$OUTPUT_DIR"
BROWSER_TYPE="${3:-chromium}"

CLEANUP_DIR="$OUTPUT_DIR"
cleanup_temp() {
    rm -f "$CLEANUP_DIR"/bilibili_subtitle*.srt "$CLEANUP_DIR"/bilibili_ai_subtitle*.srt \
          "$CLEANUP_DIR"/bilibili_audio*.mp3 "$CLEANUP_DIR"/bilibili_audio*.m4a \
          "$CLEANUP_DIR"/bilibili_audio*.wav "$CLEANUP_DIR"/bilibili_audio*.txt \
          "$CLEANUP_DIR"/.qwen_transcript.txt
}
trap cleanup_temp EXIT

if [ -z "$VIDEO_URL" ]; then
    echo "用法: $0 <B站视频链接> [输出目录] [浏览器类型:chromium|edge|firefox]"
    exit 1
fi

echo "🔍 正在获取视频信息..."

# ===== 检测浏览器Cookie =====
echo "🔍 检测浏览器Cookie..."

COOKIE_ARGS=()

detect_cookie() {
    local browser="$1"
    local path="$2"
    local label="$3"
    if [ -d "$path" ]; then
        local test_out
        test_out=$(yt-dlp --list-subs --cookies-from-browser "$browser:$path" "$VIDEO_URL" 2>&1 | head -1)
        if echo "$test_out" | grep -q "Extracting"; then
            echo "   ✅ 使用 $label Cookie"
            COOKIE_ARGS=(--cookies-from-browser "$browser:$path")
            return 0
        fi
    fi
    return 1
}

case "$BROWSER_TYPE" in
    chromium)
        detect_cookie "chromium" "$HOME/snap/chromium/common/chromium" "WSL Chromium" || true
        ;;
    edge)
        WIN_USER=$(ls /mnt/c/Users/ 2>/dev/null | grep -v "Public\|Default\|All Users" | head -1)
        if [ -n "$WIN_USER" ]; then
            detect_cookie "edge" "C:/Users/$WIN_USER/AppData/Local/Microsoft/Edge/User Data" "Windows Edge" || true
        fi
        ;;
    firefox)
        detect_cookie "firefox" "$HOME/snap/firefox/common/.mozilla/firefox" "WSL Firefox" || true
        ;;
esac

if [ ${#COOKIE_ARGS[@]} -eq 0 ]; then
    detect_cookie "chromium" "$HOME/snap/chromium/common/chromium" "WSL Chromium" || \
    { WIN_USER=$(ls /mnt/c/Users/ 2>/dev/null | grep -v "Public\|Default\|All Users" | head -1); \
      [ -n "$WIN_USER" ] && detect_cookie "edge" "C:/Users/$WIN_USER/AppData/Local/Microsoft/Edge/User Data" "Windows Edge"; } || \
    detect_cookie "firefox" "$HOME/snap/firefox/common/.mozilla/firefox" "WSL Firefox" || true
fi

if [ ${#COOKIE_ARGS[@]} -eq 0 ]; then
    echo "   ⚠️ 无可用Cookie，B站AI字幕可能无法获取"
    echo "   💡 请先用 chromium-browser 登录 bilibili.com"
else
    COOKIE_AGE=$(ls -lu "$HOME/snap/chromium/common/chromium/Default/Cookies" 2>/dev/null | awk '{print $6, $7}')
    echo "   ℹ️  Cookie最后使用: $COOKIE_AGE（约30天过期）"
fi
echo ""

# ===== 获取视频元数据 =====
VIDEO_INFO=$(yt-dlp "${COOKIE_ARGS[@]}" --dump-json "$VIDEO_URL" 2>/dev/null | head -1)

if [ -z "$VIDEO_INFO" ]; then
    VIDEO_INFO=$(yt-dlp --dump-json "$VIDEO_URL" 2>/dev/null | head -1)
    if [ -z "$VIDEO_INFO" ]; then
        echo "❌ 无法获取视频信息，请检查网络或链接是否正确"
        exit 1
    fi
fi

TITLE=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('title', '未知标题'))")
AUTHOR=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('uploader', '未知作者'))")
UPLOAD_DATE=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('upload_date', '未知时间'))")
DURATION=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; d=json.load(sys.stdin).get('duration', 0); print(f'{int(d//60)}分{int(d%60)}秒')")
VIDEO_ID=$(echo "$VIDEO_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))")

if [ "$UPLOAD_DATE" != "未知时间" ]; then
    UPLOAD_DATE_FORMATTED=$(echo "$UPLOAD_DATE" | sed 's/\(....\)\(..\)\(..\)/\1-\2-\3/')
else
    UPLOAD_DATE_FORMATTED="$UPLOAD_DATE"
fi

echo "📹 视频: $TITLE"
echo "👤 作者: $AUTHOR"
echo "📅 发布: $UPLOAD_DATE_FORMATTED"
echo "⏱️  时长: $DURATION"

# ===== 检查字幕 =====
echo ""
echo "🔍 正在检查字幕..."
SUB_CHECK=$(yt-dlp "${COOKIE_ARGS[@]}" --list-subs "$VIDEO_URL" 2>&1)

HAS_CC_SUBS=false
CC_SUB_LANG=""
CC_SUB_LANG=$(echo "$SUB_CHECK" | awk '!/danmaku/ && !/ai-/ && /^[[:space:]]*(zh-CN|zh-TW|zh-Hans|zh-Hant|en|ja|ko|es|ar|pt|de|fr)($|[-[:space:]])/ {print $1; exit}')
if [ -n "$CC_SUB_LANG" ]; then
    HAS_CC_SUBS=true
fi

HAS_AI_SUBS=false
AI_LANG=""
for lang in "ai-zh" "ai-en" "ai-ja" "ai-kr" "ai-th" "ai-id" "ai-vi"; do
    if echo "$SUB_CHECK" | grep -q "$lang"; then
        HAS_AI_SUBS=true
        AI_LANG="$lang"
        break
    fi
done

TRANSCRIPT_SOURCE=""
TRANSCRIPT_TEXT=""

# 第1级：人工CC字幕
if [ "$HAS_CC_SUBS" = true ]; then
    echo "✅ 发现人工CC字幕（$CC_SUB_LANG），优先下载..."

    yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --sub-langs "$CC_SUB_LANG" --convert-subs srt \
        -o "${OUTPUT_DIR}/bilibili_subtitle.%(ext)s" "$VIDEO_URL" 2>&1

    SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_subtitle*.srt" -type f 2>/dev/null | head -1)

    if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
        echo "✅ CC字幕下载成功"
        TRANSCRIPT_SOURCE="B站CC字幕"
        TRANSCRIPT_TEXT=$(sed '/^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
    else
        echo "⚠️  CC字幕下载失败..."
        HAS_CC_SUBS=false
    fi
fi

# 第2级：AI字幕
if [ -z "$TRANSCRIPT_TEXT" ] && [ "$HAS_AI_SUBS" = true ]; then
    echo "✅ 发现AI字幕（$AI_LANG），正在下载..."

    yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --write-auto-subs --sub-langs "$AI_LANG" --convert-subs srt \
        -o "${OUTPUT_DIR}/bilibili_ai_subtitle.%(ext)s" "$VIDEO_URL" 2>&1

    SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_ai_subtitle*.srt" -type f 2>/dev/null | head -1)

    if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
        echo "✅ AI字幕下载成功"
        TRANSCRIPT_SOURCE="B站AI字幕 ($AI_LANG)"
        TRANSCRIPT_TEXT=$(sed '/^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
    else
        echo "⚠️  AI字幕下载失败..."
        HAS_AI_SUBS=false
    fi
fi

# 第2.5级：兜底 - 尝试直接下载AI字幕（解决 yt-dlp 列表检测不到的 AI 字幕）
if [ -z "$TRANSCRIPT_TEXT" ]; then
    echo "🔍 尝试直接下载 AI 字幕（兜底）..."
    for try_lang in "ai-zh" "ai-en" "ai-ja"; do
        yt-dlp "${COOKIE_ARGS[@]}" --skip-download --write-subs --write-auto-subs --sub-langs "$try_lang" --convert-subs srt \
            -o "${OUTPUT_DIR}/bilibili_ai_subtitle.%(ext)s" "$VIDEO_URL" 2>/dev/null
        SUB_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "bilibili_ai_subtitle*.srt" -type f 2>/dev/null | head -1)
        if [ -n "$SUB_FILE" ] && [ -s "$SUB_FILE" ]; then
            echo "✅ 兜底成功！AI字幕已下载（$try_lang）"
            TRANSCRIPT_SOURCE="B站AI字幕 ($try_lang)"
            TRANSCRIPT_TEXT=$(sed '/^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/d' "$SUB_FILE" | sed '/^[0-9]*$/d' | sed '/^$/d')
            break
        fi
    done
fi

# 第3级：Qwen3-ASR 本地语音转文字
# 有独显 → Qwen3-ASR-1.7B（自动检测 CUDA/ROCm/MPS）
# 无独显 → Qwen3-ASR-0.6B（CPU）
if [ -z "$TRANSCRIPT_TEXT" ]; then
    echo "🎤 未发现字幕，使用 Qwen3-ASR 本地语音转文字..."
    echo "⏳ 这可能需要一些时间，请耐心等待..."

    # 下载音频
    echo "   ⬇️ 下载音频..."
    yt-dlp "${COOKIE_ARGS[@]}" -x --audio-format mp3 -o "${OUTPUT_DIR}/bilibili_audio.%(ext)s" "$VIDEO_URL" 2>&1 || \
    yt-dlp -x --audio-format mp3 -o "${OUTPUT_DIR}/bilibili_audio.%(ext)s" "$VIDEO_URL" 2>&1

    AUDIO_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 \( -name "bilibili_audio*.mp3" -o -name "bilibili_audio*.m4a" \) 2>/dev/null | head -1)

    if [ -z "$AUDIO_FILE" ]; then
        echo "❌ 音频下载失败"
        exit 1
    fi

    # 转为 16kHz 单声道 WAV（统一格式，兼容性最好）
    echo "   🔄 音频格式优化（16kHz 单声道）..."
    WAV_FILE="${OUTPUT_DIR}/bilibili_audio.wav"
    ffmpeg -y -i "$AUDIO_FILE" -ar 16000 -ac 1 "$WAV_FILE" 2>/dev/null

    if [ -f "$WAV_FILE" ] && [ -s "$WAV_FILE" ]; then
        AUDIO_FILE="$WAV_FILE"
        echo "   ✅ 音频已优化"
    fi

    # 调用 Qwen3-ASR 转录
    # Python 脚本自动检测设备、自动选择模型（1.7B/0.6B）
    Q3_DIR="$(cd "$(dirname "$0")" && pwd)"
    Q3_SCRIPT="${Q3_DIR}/qwen3_transcribe.py"
    Q3_PYTHON="${Q3_DIR}/../.venv/bin/python3"
    Q3_OUTPUT_FILE="${OUTPUT_DIR}/.qwen_transcript.txt"

    if [ ! -f "$Q3_PYTHON" ]; then
        echo "   ❌ 未找到虚拟环境 Python"
        echo "   请先执行以下命令安装依赖:"
        echo "     cd ${Q3_DIR}/.."
        echo "     python3 -m venv .venv"
        echo "     .venv/bin/pip install qwen-asr"
        exit 1
    fi

    echo "   🎤 开始语音转文字..."
    "$Q3_PYTHON" "$Q3_SCRIPT" --audio "$AUDIO_FILE" --output-file "$Q3_OUTPUT_FILE"

    if [ -f "$Q3_OUTPUT_FILE" ] && [ -s "$Q3_OUTPUT_FILE" ]; then
        # 输出文件格式：
        #   第一行：转录来源（如 "Qwen3-ASR-1.7B（GPU加速）"）
        #   第二行起：完整转录文本
        TRANSCRIPT_SOURCE=$(head -1 "$Q3_OUTPUT_FILE")
        TRANSCRIPT_TEXT=$(tail -n +2 "$Q3_OUTPUT_FILE")
        rm -f "$Q3_OUTPUT_FILE"
        echo "✅ 转录完成"
    else
        echo "❌ Qwen3-ASR 转录失败"
        rm -f "$Q3_OUTPUT_FILE"
        exit 1
    fi
fi

# 繁体转简体
if command -v opencc >/dev/null 2>&1; then
    echo "🔄 正在转换为简体字..."
    TRANSCRIPT_TEXT_SIMPLIFIED=$(echo "$TRANSCRIPT_TEXT" | opencc -c tw2s)
else
    TRANSCRIPT_TEXT_SIMPLIFIED="$TRANSCRIPT_TEXT"
fi

# 按发布年月组织输出目录
PUB_YEAR=$(echo "$UPLOAD_DATE_FORMATTED" | cut -d'-' -f1)
PUB_MONTH=$(echo "$UPLOAD_DATE_FORMATTED" | cut -d'-' -f2)
if [ -n "$PUB_YEAR" ] && [ "$PUB_YEAR" != "未知时间" ]; then
    OUTPUT_DIR="${OUTPUT_DIR}/${PUB_YEAR}/${PUB_MONTH}"
    mkdir -p "$OUTPUT_DIR"
fi

SAFE_TITLE=$(echo "$TITLE" | python3 -c "import sys, re; s=sys.stdin.read().strip(); s=re.sub(r'[\\\\/:*?\"<>|]', '', s); s=re.sub(r'[\\s\\W]+', '-', s); s=re.sub(r'-+', '-', s).strip('-'); print(s[:60] or 'untitled')")
AUTHOR_SAFE=$(echo "$AUTHOR" | python3 -c "import sys, re; s=sys.stdin.read().strip(); s=re.sub(r'[\\\\/:*?\"<>|]', '', s); s=re.sub(r'[\\s\\W]+', '-', s); s=re.sub(r'-+', '-', s).strip('-'); print(s[:30] or 'unknown')")
OUTPUT_FILE="${OUTPUT_DIR}/${SAFE_TITLE}_${AUTHOR_SAFE}_${UPLOAD_DATE_FORMATTED}_${VIDEO_ID}.txt"

echo "📝 正在生成转录文件..."

cat > "$OUTPUT_FILE" << EOF
================================================================================
B站视频转录文档
================================================================================

📹 视频标题：$TITLE
🔗 B站链接：$VIDEO_URL
👤 作者：$AUTHOR
📅 发布时间：$UPLOAD_DATE_FORMATTED
⏱️  视频时长：$DURATION
📝 转录来源：$TRANSCRIPT_SOURCE
⏰ 转录时间：$(date '+%Y-%m-%d %H:%M:%S')

================================================================================
第一部分：视频摘要（AI生成）
================================================================================

【AI待处理：请阅读全文后，替换此行，写结构化摘要】

================================================================================
第二部分：完整原文
================================================================================

$TRANSCRIPT_TEXT_SIMPLIFIED

================================================================================
文档结束
================================================================================
EOF

echo ""
echo "✅ 转录完成！"
echo "📄 文件已保存: $OUTPUT_FILE"
echo "$OUTPUT_FILE"
