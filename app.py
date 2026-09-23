import os
import re
import subprocess
import tempfile
import urllib.request
import base64
import time
import wave

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="Smey Auto Caption", page_icon="🇰🇭", layout="centered")

TELEGRAM_URL = "https://t.me/Smeytk"
USER_AGENT = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Safari/537.36"


# ------------------------- Common helpers -------------------------

def get_value(obj, *names):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def ffmpeg(args):
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner", "-loglevel", "error", "-nostdin",
        *args,
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        err = (p.stderr or p.stdout).decode("utf-8", errors="ignore").strip()
        raise RuntimeError(err[-4000:] or f"FFmpeg exit code: {p.returncode}")
    return p


def sec(value):
    try:
        return float(str(value).replace("s", ""))
    except Exception:
        return 0.0


def ass_time(value):
    value = max(0.0, float(value))
    h = int(value // 3600)
    m = int(value % 3600 // 60)
    s = int(value % 60)
    cs = min(99, int((value - int(value)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


# ------------------------- Gemini transcription -------------------------

def add_word(words, item):
    word = get_value(item, "text", "word")
    start = get_value(item, "start_offset", "startOffset")
    end = get_value(item, "end_offset", "endOffset")
    if word and start is not None and end is not None:
        words.append({"text": str(word).strip(), "start": sec(start), "end": sec(end)})


def words_from(response):
    """Read Gemini word timing from current/legacy response shapes."""
    words = []

    def walk(obj, depth=0):
        if obj is None or depth > 8 or isinstance(obj, (str, bytes, int, float, bool)):
            return

        transcription = get_value(obj, "audio_transcription", "audioTranscription")
        if transcription is not None:
            for item in (get_value(transcription, "words") or []):
                add_word(words, item)

        for annotation in (get_value(obj, "annotations") or []):
            if get_value(annotation, "type") == "word_info":
                add_word(words, annotation)

        for key in ("parts", "content", "candidates", "output", "steps"):
            child = get_value(obj, key)
            if child is not None:
                if isinstance(child, (list, tuple)):
                    for item in child:
                        walk(item, depth + 1)
                else:
                    walk(child, depth + 1)

    walk(response)

    unique = {}
    for word in words:
        if word["text"]:
            key = (word["text"], round(word["start"], 3), round(word["end"], 3))
            unique[key] = word
    return sorted(unique.values(), key=lambda x: (x["start"], x["end"]))


def detect_language(words):
    text = "".join(w["text"] for w in words)
    khmer = sum("\u1780" <= c <= "\u17ff" for c in text)
    chinese = sum("\u3400" <= c <= "\u4dbf" or "\u4e00" <= c <= "\u9fff" for c in text)
    if khmer >= 3 and khmer > chinese:
        return "🇰🇭 ខ្មែរ"
    if chinese >= 3 and chinese > khmer:
        return "🇨🇳 中文"
    return "🤖 មិនប្រាកដ"


def make_groups(words, max_words=10, max_seconds=4):
    groups, current = [], []
    start = end = None

    for word in words:
        text = word["text"].strip()
        if not text:
            continue
        s, e = float(word["start"]), float(word["end"])
        if start is None:
            start = s
        current.append(text)
        end = e
        if len(current) >= max_words or e - start >= max_seconds:
            groups.append({"start": start, "end": end, "text": " ".join(current)})
            current, start, end = [], None, None

    if current:
        groups.append({"start": start, "end": end, "text": " ".join(current)})
    return groups


def transcribe(video_audio_path, source):
    client = get_gemini_client()
    audio_file = client.files.upload(file=video_audio_path)
    language_codes = {
        "🇨🇳 中文": ["cmn-Hans-CN"],
        "🇰🇭 ខ្មែរ": ["km-KH"],
    }.get(source, [])

    response = client.models.generate_content(
        model="gemini-3.5-transcribe",
        contents=[audio_file],
        config=types.GenerateContentConfig(
            audio_transcription_config=types.AudioTranscriptionConfig(
                word_timestamp=True,
                language_codes=language_codes,
            )
        ),
    )
    words = words_from(response)
    if not words:
        transcript = getattr(response, "text", "") or ""
        raise RuntimeError(
            "Gemini បានស្តាប់សំឡេង ប៉ុន្តែមិនបានផ្ញើ Word Timing មកទេ."
            + (f"\n\nTranscript: {transcript[:1000]}" if transcript else "")
        )
    return words


# ------------------------- Translation -------------------------

def translate_groups(groups, source, target):
    if not groups or target == "🚫 មិនបកប្រែ" or source == target:
        return groups

    client = get_gemini_client()
    source_name = "Chinese" if source == "🇨🇳 中文" else "Khmer"
    target_name = "Chinese (Simplified)" if target == "🇨🇳 中文" else "Khmer"
    translated = []

    for i in range(0, len(groups), 30):
        batch = groups[i:i + 30]
        prompt = (
            f"Translate these {source_name} captions into natural {target_name}. "
            "Return ONLY a JSON array, exactly one string per input, same order. "
            "Keep names and meaning accurate.\n\n"
            + "\n".join(f"{n + 1}. {g['text']}" for n, g in enumerate(batch))
        )

        answer = None
        for attempt in range(2):
            try:
                result = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=list[str],
                    ),
                )
                if result.parsed and len(result.parsed) == len(batch):
                    answer = [str(x).strip() for x in result.parsed]
                    break
            except Exception as exc:
                if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                    raise
                if attempt == 0:
                    time.sleep(5)

        translated.extend(answer or [g["text"] for g in batch])

    return [{**g, "text": text} for g, text in zip(groups, translated)]


# ------------------------- Caption rendering -------------------------

ASS_HEADER = """[Script Info]
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


def make_ass(groups, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER)
        for g in groups:
            text = g["text"].replace("\n", " ").replace("{", r"\{").replace("}", r"\}")
            f.write(
                f"Dialogue: 0,{ass_time(g['start'])},{ass_time(g['end'])},"
                f"Khmer,,0,0,0,,{text}\n"
            )


def burn(video, ass, output):
    ass_path = ass.replace("\\", "/").replace(":", r"\:")
    ffmpeg([
        "-y", "-i", video,
        "-vf", f"ass='{ass_path}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        output,
    ])


# ------------------------- Audio extraction -------------------------

def extract_audio(video_path, audio_path):
    """PyAV first (avoids the previous FFmpeg -11 issue), FFmpeg fallback."""
    av_error = None
    try:
        import av

        container = av.open(video_path)
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            container.close()
            raise RuntimeError("វីដេអូនេះមិនមាន Audio stream ទេ។")

        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
        with wave.open(audio_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    wav.writeframes(out.to_ndarray().tobytes())
        container.close()
        if os.path.getsize(audio_path) >= 1000:
            return
    except Exception as exc:
        av_error = exc
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass

    try:
        ffmpeg([
            "-y", "-i", video_path, "-map", "0:a:0?", "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", audio_path,
        ])
    except Exception as exc:
        raise RuntimeError(
            "❌ មិនអាចអាន Audio ពីវីដេអូបានទេ។\n\n"
            f"PyAV: {str(av_error)[-1000:]}\n\nFFmpeg: {str(exc)[-1800:]}"
        ) from exc


# ------------------------- Gemini voice -------------------------

def gemini_tts(text, output_path):
    response = get_gemini_client().models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        ),
    )
    try:
        data = response.candidates[0].content.parts[0].inline_data.data
        if isinstance(data, str):
            data = base64.b64decode(data)
        with wave.open(output_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(data)
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("❌ Gemini មិនបានផ្ញើ Audio មកទេ។ សូមពិនិត្យ GEMINI_API_KEY និង TTS model access។") from exc


# ------------------------- Web video downloader -------------------------

def find_media_urls(html):
    from html import unescape

    text = unescape(html).replace(r"\\/", "/").replace(r"\/", "/")
    text = text.replace(r"\u0026", "&").replace(r"\u003A", ":")
    patterns = [
        r'https?://[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
        r'https?://[^"\'\s<>]+?\.mp4(?:\?[^"\'\s<>]*)?',
        r'(?:(?:https?:)?//)[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
        r'(?:(?:https?:)?//)[^"\'\s<>]+?\.mp4(?:\?[^"\'\s<>]*)?',
    ]
    found = []
    for pattern in patterns:
        for url in re.findall(pattern, text, flags=re.I):
            if url.startswith("//"):
                url = "https:" + url
            url = url.rstrip("\\'\".,);]")
            if url not in found:
                found.append(url)
    return found


def download_media_url(media_url, output_path, referer=None):
    headers = f"User-Agent: {USER_AGENT}\r\n"
    if referer:
        headers += f"Referer: {referer}\r\n"
    ffmpeg([
        "-y", "-headers", headers, "-i", media_url,
        "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
        "-movflags", "+faststart", output_path,
    ])


def page_media_download(url, output_path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    urls = find_media_urls(html)
    if not urls:
        raise RuntimeError("ទំព័រនេះមិនបង្ហាញ MP4/M3U8 ជាសាធារណៈទេ។ អាចជាវីដេអូការពារ/DRM ឬបង្កើត URL តាម JavaScript។")

    last_error = None
    for media_url in urls[:10]:
        try:
            download_media_url(media_url, output_path, url)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return os.path.getsize(output_path)
        except Exception as exc:
            last_error = exc
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
    raise RuntimeError("រកឃើញ Video URL ប៉ុន្តែ Download មិនបាន។ " + str(last_error or ""))


def webpage_download(url, output_path):
    """Page URL -> yt-dlp first, then public MP4/M3U8 fallback."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("❌ URL មិនត្រឹមត្រូវ។")

    first_error = None
    try:
        import yt_dlp

        template = output_path.rsplit(".", 1)[0] + ".%(ext)s"
        options = {
            "format": "bv*+ba/b",
            "outtmpl": template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "fragment_retries": 2,
            "socket_timeout": 30,
            "http_headers": {"User-Agent": USER_AGENT, "Referer": url},
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and info.get("_type") == "playlist":
                info = next((x for x in (info.get("entries") or []) if x), info)
            prepared = ydl.prepare_filename(info)

        candidates = [
            output_path,
            os.path.splitext(prepared)[0] + ".mp4",
            prepared,
        ]
        folder = os.path.dirname(output_path)
        candidates += [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.lower().endswith((".mp4", ".webm", ".mkv", ".mov"))
        ]
        existing = [p for p in candidates if os.path.exists(p) and os.path.getsize(p) > 1000]
        if existing:
            found = max(existing, key=os.path.getmtime)
            if found != output_path:
                os.replace(found, output_path)
            return os.path.getsize(output_path)
    except Exception as exc:
        first_error = exc

    try:
        return page_media_download(url, output_path)
    except Exception as exc:
        raise RuntimeError(
            "❌ មិនអាចរក/Download វីដេអូពី Link នេះបានទេ។\n\n" + str(exc)[-1800:]
        ) from (first_error or exc)


# ------------------------- UI -------------------------

st.title("🇰🇭 Smey Auto Caption")
st.caption("🎙️ Auto Caption → 🇰🇭 Khmer → MP4")
st.link_button("📱 ទាក់ទងម្ចាស់តាម Telegram", TELEGRAM_URL, use_container_width=True)

with st.expander("🎬 Download Video", expanded=False):
    st.caption("ដាក់ Link ទំព័រវីដេអូ ដូចជា FlickReels ហើយចុច Download។")
    video_url = st.text_input("🔗 Video URL", placeholder="https://www.flickreels.net/playlist/...")

    if st.button("⬇️ Download Video", use_container_width=True):
        if not video_url.strip():
            st.warning("សូមដាក់ Video URL ជាមុន។")
        else:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    output = os.path.join(tmp, "video.mp4")
                    with st.spinner("⬇️ កំពុងរក និង Download វីដេអូ..."):
                        size = webpage_download(video_url, output)
                    data = open(output, "rb").read()
                    st.success(f"✅ Download រួច — {size / 1024 / 1024:.1f} MB")
                    st.video(data)
                    st.download_button("⬇️ ទាញយក MP4", data, "smey_video.mp4", "video/mp4", use_container_width=True)
            except Exception as exc:
                st.error("❌ Download មិនបាន")
                st.warning(str(exc))

st.subheader("🗣️ អក្សរ → សំឡេង Gemini")
tts_text = st.text_area("✍️ សរសេរអត្ថបទ", placeholder="សរសេរអត្ថបទខ្មែរនៅទីនេះ...", height=100, key="tts_text")
if st.button("🔊 បង្កើតសំឡេង Gemini", use_container_width=True):
    if not tts_text.strip():
        st.warning("សូមសរសេរអត្ថបទជាមុន។")
    else:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "gemini_tts.wav")
                with st.spinner("🔊 កំពុងបង្កើតសំឡេង..."):
                    gemini_tts(tts_text.strip(), path)
                data = open(path, "rb").read()
                st.audio(data, format="audio/wav")
                st.download_button("⬇️ ទាញយកសំឡេង", data, "gemini_tts.wav", "audio/wav", use_container_width=True)
        except Exception as exc:
            st.error("❌ បង្កើតសំឡេងមិនបាន")
            st.warning(str(exc))

source = st.selectbox("🌐 ភាសាដើមក្នុងវីដេអូ", ["🤖 ស្វ័យប្រវត្តិ — ចិន / ខ្មែរ", "🇨🇳 中文", "🇰🇭 ខ្មែរ"], index=0)
target = st.selectbox("🔄 បកប្រែទៅ", ["🇰🇭 ខ្មែរ", "🇨🇳 中文", "🚫 មិនបកប្រែ"], index=0)
video = st.file_uploader("🎥 ជ្រើសវីដេអូ", type=["mp4", "mov", "mkv", "webm"])

if video:
    st.video(video)
    if st.button("⚡ Auto Caption", use_container_width=True):
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
                    raise RuntimeError("❌ មិនអាចបង្កើត Audio file បានទេ។")

                with st.spinner("🎙️ Gemini កំពុងស្តាប់សំឡេង..."):
                    words = transcribe(audio_path, source)

                groups = make_groups(words)
                detected = detect_language(words) if source.startswith("🤖") else source
                st.info(f"🌐 ភាសាដែលរកឃើញ: {detected}")

                if detected in {"🇨🇳 中文", "🇰🇭 ខ្មែរ"}:
                    with st.spinner("🔄 កំពុងរៀបចំ Caption..."):
                        groups = translate_groups(groups, detected, target)

                st.subheader("📝 Caption")
                for group in groups:
                    st.write(f"**{ass_time(group['start'])} → {ass_time(group['end'])}**  {group['text']}")

                make_ass(groups, ass_path)
                with st.spinner("🎬 កំពុងដាក់ Caption លើវីដេអូ..."):
                    burn(video_path, ass_path, output_path)

                result = open(output_path, "rb").read()
                st.success("✅ វីដេអូរួចរាល់!")
                st.video(result)
                st.download_button("⬇️ ទាញយក MP4", result, "smey_auto_caption.mp4", "video/mp4", use_container_width=True)
            except Exception as exc:
                st.error("❌ Auto Caption មិនបាន")
                st.warning(str(exc))
                
