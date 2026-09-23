import os
import subprocess
import tempfile
import urllib.request

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
    layout="centered",
)

TELEGRAM_URL = "https://t.me/Smeytk"
MAX_DOWNLOAD_MB = 500


def ffmpeg(args):
    # Keep FFmpeg output clean and show the real error instead of the long
    # FFmpeg version/configuration banner.
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"] + list(args)
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode:
        err = p.stderr.decode("utf-8", errors="ignore").strip()
        out = p.stdout.decode("utf-8", errors="ignore").strip()
        detail = err or out or f"FFmpeg exit code: {p.returncode}"
        raise RuntimeError(detail[-4000:])
    return p


def sec(v):
    try:
        return float(str(v).replace("s", ""))
    except Exception:
        return 0.0


def _add_word(words, item):
    """Add a Gemini word_info object/dict when it has usable offsets."""
    def get(obj, *names):
        for name in names:
            if isinstance(obj, dict) and name in obj:
                return obj[name]
            value = getattr(obj, name, None)
            if value is not None:
                return value
        return None

    word = get(item, "text", "word")
    start = get(item, "start_offset", "startOffset")
    end = get(item, "end_offset", "endOffset")
    if word and start is not None and end is not None:
        words.append({
            "text": str(word).strip(),
            "start": sec(start),
            "end": sec(end),
        })


def words_from(response):
    """Support both the current word_info annotation shape and older SDK shapes."""
    words = []

    def walk(obj, depth=0):
        if obj is None or depth > 8:
            return
        if isinstance(obj, (str, bytes, int, float, bool)):
            return

        if isinstance(obj, dict):
            if obj.get("type") == "word_info":
                _add_word(words, obj)
                return
            for k, v in obj.items():
                if k in {"annotations", "parts", "content", "steps", "candidates", "output"}:
                    walk(v, depth + 1)
            return

        typ = getattr(obj, "type", None)
        if typ == "word_info":
            _add_word(words, obj)
            return

        for attr in ("annotations", "parts", "content", "steps", "candidates", "output"):
            try:
                v = getattr(obj, attr, None)
            except Exception:
                v = None
            if v is not None:
                walk(v, depth + 1)

    walk(response)

    # Remove accidental duplicates while preserving timing order.
    unique = []
    seen = set()
    for w in words:
        key = (w["text"], round(w["start"], 3), round(w["end"], 3))
        if key not in seen:
            seen.add(key)
            unique.append(w)
    unique.sort(key=lambda x: (x["start"], x["end"]))
    return unique


def detect_source_language(words):
    """Fast local detection for the two requested source languages."""
    text = "".join(w.get("text", "") for w in words)
    khmer = sum(1 for ch in text if "\u1780" <= ch <= "\u17ff")
    chinese = sum(1 for ch in text if "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff")
    if khmer > chinese and khmer >= 3:
        return "🇰🇭 ខ្មែរ"
    if chinese > khmer and chinese >= 3:
        return "🇨🇳 中文"
    return "🤖 មិនប្រាកដ"

def make_groups(words, max_words=10, max_seconds=4):
    groups = []
    current = []
    start = end = None

    for w in words:
        text = str(w.get("text", "") or "").strip()
        if not text:
            continue

        s = float(w.get("start", 0.0))
        e = float(w.get("end", s))

        if start is None:
            start = s

        current.append(text)
        end = e

        if len(current) >= max_words or end - start >= max_seconds:
            groups.append({
                "start": start,
                "end": end,
                "text": " ".join(current),
            })
            current = []
            start = end = None

    if current:
        groups.append({
            "start": start,
            "end": end,
            "text": " ".join(current),
        })

    return groups

def translate_groups(groups, client, source_label, target_label):
    if not groups or target_label == "🚫 មិនបកប្រែ":
        return groups

    # No translation needed when source and target are the same.
    if source_label == target_label:
        return groups

    target_name = "Khmer" if target_label == "🇰🇭 ខ្មែរ" else "Chinese (Simplified)"
    source_name = "Khmer" if source_label == "🇰🇭 ខ្មែរ" else "Chinese"
    result = []

    # Larger batches reduce API round-trips and make the app noticeably faster.
    for i in range(0, len(groups), 30):
        batch = groups[i:i + 30]
        prompt = (
            f"Translate these {source_name} captions into natural {target_name}. "
            "Return ONLY a JSON array, exactly one string per input, same order. "
            "Do not explain. Keep names and meaning accurate.\n\n"
            + "\n".join(f"{n + 1}. {g['text']}" for n, g in enumerate(batch))
        )

        answer = None
        for attempt in range(2):
            try:
                r = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=list[str],
                    ),
                )
                if r.parsed and len(r.parsed) == len(batch):
                    answer = [str(x).strip() for x in r.parsed]
                    break
            except Exception as e:
                if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                    raise
                import time
                time.sleep(5)

        if answer is None:
            answer = [g["text"] for g in batch]
        result.extend(answer)

    return [{**g, "text": text} for g, text in zip(groups, result)]

def ass_time(x):
    h = int(x // 3600)
    m = int(x % 3600 // 60)
    s = int(x % 60)
    cs = int((x - int(x)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_ass(groups, path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,50,50,220,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for g in groups:
            text = (
                g["text"]
                .replace("\n", " ")
                .replace("{", r"\{")
                .replace("}", r"\}")
            )
            f.write(
                f"Dialogue: 0,{ass_time(g['start'])},"
                f"{ass_time(g['end'])},Khmer,,0,0,0,,{text}\n"
            )


def burn(video, ass, output):
    ass_path = ass.replace("\\", "/").replace(":", r"\:")
    ffmpeg([
        "-y",
        "-i", video,
        "-vf", f"ass='{ass_path}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output,
    ])





def extract_audio(video_path, audio_path):
    """Extract mono 16 kHz WAV. Try PyAV first so a broken FFmpeg process
    does not crash the Streamlit app with exit code -11; fall back to FFmpeg."""
    av_error = None
    try:
        import av
        import wave

        container = av.open(video_path, mode="r")
        audio_stream = next((st for st in container.streams if st.type == "audio"), None)
        if audio_stream is None:
            container.close()
            raise RuntimeError("វីដេអូនេះមិនមាន Audio stream ទេ។")

        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000,
        )

        with wave.open(audio_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)

            for frame in container.decode(audio_stream):
                for out_frame in resampler.resample(frame):
                    arr = out_frame.to_ndarray()
                    wf.writeframes(arr.tobytes())

        container.close()

        if os.path.exists(audio_path) and os.path.getsize(audio_path) >= 1000:
            return
    except Exception as e:
        av_error = e
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except OSError:
            pass

    # Fallback for files PyAV cannot decode.
    try:
        ffmpeg([
            "-y",
            "-i", video_path,
            "-map", "0:a:0?",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            audio_path,
        ])
    except Exception as ff_error:
        if av_error:
            raise RuntimeError(
                "❌ មិនអាចអាន Audio ពីវីដេអូបានទេ។\n\n"
                f"PyAV: {str(av_error)[-1200:]}\n\n"
                f"FFmpeg: {str(ff_error)[-1800:]}"
            ) from ff_error
        raise

def gemini_tts(text, output_path):
    client = genai.Client(
        api_key=st.secrets["GEMINI_API_KEY"]
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore",
                    )
                )
            ),
        ),
    )

    try:
        import base64
        import wave

        part = response.candidates[0].content.parts[0]
        data = part.inline_data.data

        if isinstance(data, str):
            data = base64.b64decode(data)

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(data)

    except (AttributeError, IndexError, TypeError) as e:
        raise RuntimeError(
            "❌ Gemini មិនបានផ្ញើ Audio មកទេ។ "
            "សូមពិនិត្យ GEMINI_API_KEY និង TTS model access។"
        ) from e

def _find_media_urls(html):
    """Find direct MP4/M3U8 URLs embedded in a webpage."""
    import re
    from html import unescape

    text = unescape(html)
    text = text.replace(r'\\/', '/')
    text = text.replace(r'\/', '/')
    text = text.replace(r'\u0026', '&')
    text = text.replace(r'\u003A', ':')

    patterns = [
        r'https?://[^\"\'\s<>]+?\.m3u8(?:\?[^\"\'\s<>]*)?',
        r'https?://[^\"\'\s<>]+?\.mp4(?:\?[^\"\'\s<>]*)?',
        r'(?:(?:https?:)?//)[^\"\'\s<>]+?\.m3u8(?:\?[^\"\'\s<>]*)?',
        r'(?:(?:https?:)?//)[^\"\'\s<>]+?\.mp4(?:\?[^\"\'\s<>]*)?',
    ]

    found = []
    for pattern in patterns:
        for url in re.findall(pattern, text, flags=re.I):
            if url.startswith('//'):
                url = 'https:' + url
            url = url.rstrip('\\\'\".,);]')
            if url not in found:
                found.append(url)
    return found


def _download_media_url(media_url, output_path, referer=None):
    """Download a direct MP4 or HLS/M3U8 URL with FFmpeg."""
    headers = (
        'User-Agent: Mozilla/5.0 (Linux; Android 10) '
        'AppleWebKit/537.36 Chrome/120 Safari/537.36\r\n'
    )
    if referer:
        headers += f'Referer: {referer}\r\n'

    ffmpeg([
        '-y',
        '-headers', headers,
        '-i', media_url,
        '-map', '0:v:0?',
        '-map', '0:a:0?',
        '-c', 'copy',
        '-movflags', '+faststart',
        output_path,
    ])


def _page_media_download(url, output_path):
    """Fallback: fetch page HTML and try embedded MP4/M3U8 URLs."""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Linux; Android 10) '
                'AppleWebKit/537.36 Chrome/120 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode('utf-8', errors='ignore')

    media_urls = _find_media_urls(html)
    if not media_urls:
        raise RuntimeError(
            'ទំព័រនេះមិនបង្ហាញ MP4/M3U8 ជាសាធារណៈទេ។ '
            'ប្រសិនបើវីដេអូត្រូវបានការពារ ឬបង្កើត URL តាម JavaScript/DRM '
            'កម្មវិធីមិនអាចទាញវាបានទេ។'
        )

    last_error = None
    for media_url in media_urls[:10]:
        try:
            _download_media_url(media_url, output_path, referer=url)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return os.path.getsize(output_path)
        except Exception as e:
            last_error = e
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass

    raise RuntimeError(
        'រកឃើញ Video URL ប៉ុន្តែ Download មិនបាន។ '
        + (str(last_error)[-1200:] if last_error else '')
    )


def webpage_download(url, output_path):
    """Page URL -> try yt-dlp first, then embedded MP4/M3U8 fallback."""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        raise RuntimeError('❌ URL មិនត្រឹមត្រូវ។')

    last_error = None

    # 1) Try yt-dlp. It supports many sites and its generic extractor can
    # sometimes find embedded players even when the site has no dedicated extractor.
    try:
        import yt_dlp

        temp_template = output_path.replace('.mp4', '.%(ext)s')
        options = {
            'format': 'bv*+ba/b',
            'outtmpl': temp_template,
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
            'fragment_retries': 3,
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Linux; Android 10) '
                    'AppleWebKit/537.36 Chrome/120 Safari/537.36'
                ),
                'Referer': url,
            },
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

            if info and info.get('_type') == 'playlist':
                entries = [e for e in (info.get('entries') or []) if e]
                if entries:
                    info = entries[0]

            downloaded = ydl.prepare_filename(info)
            candidates = [
                output_path,
                os.path.splitext(downloaded)[0] + '.mp4',
                downloaded,
            ]

            folder = os.path.dirname(output_path)
            candidates += [
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if name.lower().endswith(('.mp4', '.webm', '.mkv', '.mov'))
            ]

            existing = [x for x in candidates if os.path.exists(x)]
            if existing:
                found = max(existing, key=os.path.getmtime)
                if found != output_path:
                    os.replace(found, output_path)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return os.path.getsize(output_path)

    except Exception as e:
        last_error = e

    # 2) Fallback for pages that expose an MP4/M3U8 in HTML/JSON.
    try:
        return _page_media_download(url, output_path)
    except Exception as e:
        if last_error:
            raise RuntimeError(
                '❌ មិនអាចរកវីដេអូពី Link នេះបានទេ។\n\n'
                'សាកល្បងរក Video Player/MP4/M3U8 ក្នុងទំព័ររួចហើយ ប៉ុន្តែមិនអាចទាញបាន។\n\n'
                + str(e)[-1800:]
            ) from e
        raise




# ========================= UI =========================

st.title("🇰🇭 Smey Auto Caption")
st.caption("🎙️ Auto Caption → 🇰🇭 Khmer → MP4")

st.link_button(
    "📱 ទាក់ទងម្ចាស់តាម Telegram",
    TELEGRAM_URL,
    use_container_width=True,
)


# ========================= WEB VIDEO DOWNLOAD =========================

with st.expander("🎬 Download Video", expanded=False):
    st.caption(
        "ដាក់ Link ទំព័រវីដេអូ ដូចជា FlickReels ហើយចុច Download។ "
        "កម្មវិធីនឹងព្យាយាមរកវីដេអូពីទំព័រនោះដោយស្វ័យប្រវត្តិ។"
    )

    video_url = st.text_input(
        "🔗 Video URL",
        placeholder="https://www.flickreels.net/playlist/...",
    )

    if st.button("⬇️ Download Video", use_container_width=True):
        if not video_url.strip():
            st.warning("សូមដាក់ Video URL ជាមុន។")
        else:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    output = os.path.join(tmp, "video.mp4")

                    with st.spinner("⬇️ កំពុងរក និង Download វីដេអូ..."):
                        size = webpage_download(
                            video_url,
                            output,
                        )

                    with open(output, "rb") as f:
                        data = f.read()

                    st.success(
                        f"✅ Download រួច — {size / 1024 / 1024:.1f} MB"
                    )
                    st.video(data)

                    st.download_button(
                        "⬇️ ទាញយក MP4",
                        data=data,
                        file_name="smey_video.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                    )

            except Exception as e:
                st.error("❌ Download មិនបាន")
                st.warning(str(e))



# ========================= TEXT → GEMINI VOICE =========================

st.subheader("🗣️ អក្សរ → សំឡេង Gemini")

tts_text = st.text_area(
    "✍️ សរសេរអត្ថបទ",
    placeholder="សរសេរអត្ថបទខ្មែរនៅទីនេះ...",
    height=100,
    key="tts_text",
)

if st.button(
    "🔊 បង្កើតសំឡេង Gemini",
    use_container_width=True,
):
    if not tts_text.strip():
        st.warning("សូមសរសេរអត្ថបទជាមុន។")
    else:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                audio_path = os.path.join(
                    tmp,
                    "gemini_tts.wav",
                )

                with st.spinner("🔊 កំពុងបង្កើតសំឡេង..."):
                    gemini_tts(
                        tts_text.strip(),
                        audio_path,
                    )

                with open(audio_path, "rb") as f:
                    audio_data = f.read()

                st.audio(
                    audio_data,
                    format="audio/wav",
                )

                st.download_button(
                    "⬇️ ទាញយកសំឡេង",
                    data=audio_data,
                    file_name="gemini_tts.wav",
                    mime="audio/wav",
                    use_container_width=True,
                )

        except Exception as e:
            st.error("❌ បង្កើតសំឡេងមិនបាន")
            st.warning(str(e))


# ========================= AUTO CAPTION =========================

source = st.selectbox(
    "🌐 ភាសាដើមក្នុងវីដេអូ",
    [
        "🤖 ស្វ័យប្រវត្តិ — ចិន / ខ្មែរ",
        "🇨🇳 中文",
        "🇰🇭 ខ្មែរ",
    ],
    index=0,
)

target = st.selectbox(
    "🔄 បកប្រែទៅ",
    [
        "🇰🇭 ខ្មែរ",
        "🇨🇳 中文",
        "🚫 មិនបកប្រែ",
    ],
    index=0,
)

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)

if video:
    st.video(video)

    if st.button(
        "⚡ Auto Caption",
        use_container_width=True,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "input.mp4")
            audio_path = os.path.join(tmp, "audio.wav")
            ass_path = os.path.join(tmp, "caption.ass")
            output_path = os.path.join(tmp, "output.mp4")

            with open(video_path, "wb") as f:
                f.write(video.getbuffer())

            try:
                with st.spinner("🎵 កំពុងដកសំឡេង..."):
                    extract_audio(video_path, audio_path)

                if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
                    raise RuntimeError(
                        "❌ មិនអាចបង្កើត Audio file បានទេ។ សូមពិនិត្យថាវីដេអូមានសំឡេង។"
                    )

                client = genai.Client(
                    api_key=st.secrets["GEMINI_API_KEY"]
                )

                with st.spinner("🎙️ Gemini កំពុងស្តាប់សំឡេង..."):
                    audio_file = client.files.upload(file=audio_path)

                    # Auto mode: omit language_codes so Gemini detects Chinese/Khmer itself.
                    if source == "🇨🇳 中文":
                        language_codes = ["cmn-Hans-CN"]
                    elif source == "🇰🇭 ខ្មែរ":
                        language_codes = ["km-KH"]
                    else:
                        language_codes = []

                    response = client.models.generate_content(
                        model="gemini-3.5-transcribe",
                        contents=[audio_file],
                        config=types.GenerateContentConfig(
                            audio_transcription_config=(
                                types.AudioTranscriptionConfig(
                                    word_timestamp=True,
                                    language_codes=language_codes,
                                )
                            )
                        ),
                    )

                words = words_from(response)

                if not words:
                    transcript = getattr(response, "text", "") or ""
                    detail = transcript.strip()[:1000]
                    raise RuntimeError(
                        "Gemini បានទទួលសំឡេង ប៉ុន្តែ Response មិនមាន Word Timing។ "
                        "កូដថ្មីបានអានទីតាំង AudioTranscription ត្រឹមត្រូវហើយ។"
                        + (f"\n\nTranscript: {detail}" if detail else "")
                    )

                groups = make_groups(words)

                detected = detect_source_language(words) if source.startswith("🤖") else source
                st.info(f"🌐 ភាសាដែលរកឃើញ: {detected}")

                if target != "🚫 មិនបកប្រែ" and detected in {"🇨🇳 中文", "🇰🇭 ខ្មែរ"} and detected != target:
                    with st.spinner(f"🔄 កំពុងបកប្រែទៅ {target}..."):
                        groups = translate_groups(groups, client, detected, target)

                st.subheader("📝 Caption")

                for g in groups:
                    st.write(
                        f"**{ass_time(g['start'])} → "
                        f"{ass_time(g['end'])}**  {g['text']}"
                    )

                make_ass(groups, ass_path)

                with st.spinner("🎬 កំពុងដាក់ Caption លើវីដេអូ..."):
                    burn(
                        video_path,
                        ass_path,
                        output_path,
                    )

                with open(output_path, "rb") as f:
                    result = f.read()

                st.success("✅ វីដេអូរួចរាល់!")
                st.video(result)

                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=result,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )

            except Exception as e:
                st.error("❌ Auto Caption មិនបាន")
                st.warning(str(e))
                st.caption("💡 បើ Error និយាយពី Audio/Stream វីដេអូអាចមិនមានសំឡេង ឬ File មិនពេញលេញ។")
