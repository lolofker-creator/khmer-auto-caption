import os
import re
import subprocess
import tempfile
import urllib.request
import base64
import time
import wave
import json

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

# ============================================================
# 🇰🇭 Smey Auto Caption
# Gemini → Caption → Auto Translate → MP4
# ============================================================

st.set_page_config(page_title="🇰🇭 Smey Auto Caption", page_icon="🇰🇭")

st.title("🇰🇭 Smey Auto Caption")
st.caption("Gemini → Caption → Auto Translate → MP4")
st.markdown(
    "📩 **ទំនាក់ទំនងម្ចាស់កម្មវិធី:** "
    "[Telegram @Smeytk](https://t.me/Smeytk)"
)

# ============================================================
# CONFIG
# ============================================================

TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
TRANSLATE_MODEL = "gemini-3.1-flash-lite"
TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_VOICE = "Kore"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "fonts")
FONT_PATH = os.path.join(FONT_DIR, "NotoSansKhmer-Regular.ttf")

# The app can install the free Noto Sans Khmer font automatically.
# This avoids requiring the user to manually add a font file.
FONT_URL = (
    "https://raw.githubusercontent.com/ghostlypi/NotoSans/main/"
    "NotoSansKhmer-Regular.ttf"
)

# ============================================================
# COMMON HELPERS
# ============================================================

def get_value(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_api_key():
    """Read Gemini API key from Streamlit Secrets or environment only.
    The key is no longer shown or entered in the app UI.
    """
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""

    return str(key or os.getenv("GEMINI_API_KEY", "")).strip()



def ass_time(value):
    value = max(0.0, float(value))
    h = int(value // 3600)
    m = int((value % 3600) // 60)
    s = value % 60
    return f"{h}:{m:02d}:{s:05.2f}"


@st.cache_resource
def get_gemini_client(api_key):
    return genai.Client(api_key=api_key)


def retry_gemini(call, attempts=4, delay=2):
    """Retry only temporary Gemini errors (429/5xx)."""
    last_error = None

    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            temporary = any(
                code in message
                for code in ("429", "500", "502", "503", "504", "unavailable", "resource_exhausted")
            )
            if not temporary or attempt == attempts - 1:
                raise
            time.sleep(delay * (2 ** attempt))

    raise last_error


def ensure_khmer_font():
    """Ensure the free Noto Sans Khmer font exists locally."""
    os.makedirs(FONT_DIR, exist_ok=True)

    if os.path.isfile(FONT_PATH) and os.path.getsize(FONT_PATH) > 10_000:
        return FONT_PATH

    try:
        request = urllib.request.Request(
            FONT_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()

        if len(data) < 10_000:
            raise RuntimeError("Font file ដែលទាញយកមកមានទំហំមិនត្រឹមត្រូវ")

        with open(FONT_PATH, "wb") as f:
            f.write(data)

        return FONT_PATH
    except Exception as e:
        raise RuntimeError(
            "មិនអាចរក/ទាញយក Noto Sans Khmer Font បាន។ "
            f"សូមពិនិត្យ Internet របស់ Streamlit Cloud។\n{e}"
        ) from e

# ============================================================
# WORD / TRANSCRIPTION HELPERS
# ============================================================

def parse_duration(value):
    """Convert Gemini Duration values such as '1.25s' to seconds."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return 0.0


def add_word(result, word, start=None, end=None):
    text = get_value(word, "word", None)
    if text is None:
        text = get_value(word, "text", "")
    if not text:
        return

    # Current Gemini WordInfo uses start_offset / end_offset.
    if start is None:
        start = get_value(word, "start_offset", None)
    if start is None:
        start = get_value(word, "start_time", None)
    if start is None:
        start = get_value(word, "start", 0)

    if end is None:
        end = get_value(word, "end_offset", None)
    if end is None:
        end = get_value(word, "end_time", None)
    if end is None:
        end = get_value(word, "end", start)

    result.append({
        "text": str(text),
        "start": parse_duration(start),
        "end": parse_duration(end),
    })


def words_from(response):
    """Extract word timing from Gemini GenerateContent response.

    Gemini returns AudioTranscription inside:
    response.candidates[].content.parts[].audio_transcription
    when word_timestamp=True.
    """
    words = []

    # Official GenerateContent response shape.
    for candidate in get_value(response, "candidates", []) or []:
        content = get_value(candidate, "content", None)
        for part in get_value(content, "parts", []) or []:
            transcription = get_value(part, "audio_transcription", None)
            if transcription is None:
                continue

            current_words = get_value(transcription, "words", []) or []
            for word in current_words:
                add_word(words, word)

    # Keep compatibility with older/alternate SDK response shapes.
    transcription = get_value(response, "audio_transcription", None)
    if transcription is not None:
        for word in get_value(transcription, "words", []) or []:
            add_word(words, word)

    direct_words = get_value(response, "words", None)
    if direct_words:
        for word in direct_words:
            add_word(words, word)

    # Legacy annotation shape.
    annotations = get_value(response, "annotations", None)
    if annotations:
        for item in annotations:
            if get_value(item, "type", "") == "word_info":
                add_word(words, item)

    return words


def detect_language(text):
    khmer = len(re.findall(r"[\u1780-\u17FF]", text))
    chinese = len(re.findall(r"[\u4E00-\u9FFF]", text))

    if khmer > chinese and khmer > 0:
        return "Khmer"
    if chinese > 0:
        return "Chinese"
    return "Unknown"


def make_groups(words, max_words=12, max_seconds=5.0):
    groups = []
    current = []

    for word in words:
        if not current:
            current = [word]
            continue

        duration = word["end"] - current[0]["start"]
        if len(current) >= max_words or duration >= max_seconds:
            groups.append(current)
            current = [word]
        else:
            current.append(word)

    if current:
        groups.append(current)

    result = []
    for group in groups:
        text = " ".join(x["text"] for x in group).strip()
        if text:
            result.append({
                "text": text,
                "start": group[0]["start"],
                "end": group[-1]["end"],
            })

    return result

# ============================================================
# GEMINI TRANSCRIPTION
# ============================================================

def transcribe(client, audio_path, source_language):
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    prompt = (
        "Transcribe the spoken audio exactly. "
        "Return accurate word-level timestamps. "
        "Do not translate the speech."
    )

    language_codes = None
    if source_language == "Chinese":
        language_codes = ["cmn-Hans-CN"]
    elif source_language == "Khmer":
        language_codes = ["km-KH"]

    # Transcription options must be nested in AudioTranscriptionConfig.
    transcription_kwargs = {
        "word_timestamp": True,
    }
    if language_codes:
        transcription_kwargs["language_codes"] = language_codes

    transcription_config = types.AudioTranscriptionConfig(
        **transcription_kwargs
    )

    def call():
        return client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=audio_data,
                    mime_type="audio/wav",
                ),
                prompt,
            ],
            config=types.GenerateContentConfig(
                audio_transcription_config=transcription_config,
            ),
        )

    return retry_gemini(call)

# ============================================================
# TRANSLATION
# ============================================================

def translate_groups(client, groups, target_language):
    if not groups or target_language == "No translation":
        return groups

    translated = []
    batch_size = 15

    for start in range(0, len(groups), batch_size):
        batch = groups[start:start + batch_size]
        texts = [item["text"] for item in batch]

        prompt = (
            f"Translate each subtitle line into {target_language}.\n"
            "Return exactly one translated line per input line, in the same order. "
            "Do not add explanations. Keep names and numbers accurate.\n\n"
            f"Input:\n{texts}"
        )

        schema = types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        )

        def call():
            return client.models.generate_content(
                model=TRANSLATE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )

        try:
            response = retry_gemini(call)
            values = get_value(response, "parsed", None)

            if values is None:
                raw = get_value(response, "text", "") or ""
                try:
                    values = json.loads(raw)
                except Exception:
                    values = []

            if not isinstance(values, list) or len(values) != len(batch):
                raise RuntimeError("Translation response មិនត្រឹមត្រូវ")

        except Exception as exc:
            # Keep the Auto Caption pipeline usable if translation service is temporarily unavailable.
            st.warning(
                "⚠️ Gemini Translation មិនទាន់អាចប្រើបាន។ "
                "Caption នឹងរក្សាភាសាដើមសម្រាប់ផ្នែកនេះ។"
            )
            values = [item["text"] for item in batch]

        for index, item in enumerate(batch):
            translated.append({
                "text": str(values[index]),
                "start": item["start"],
                "end": item["end"],
            })

    return translated

# ============================================================
# ASS CAPTION — KHMER SAFE
# ============================================================

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def make_ass(groups, ass_path):
    with open(ass_path, "w", encoding="utf-8-sig") as f:
        f.write(ASS_HEADER)

        for item in groups:
            text = (
                item["text"]
                .replace("\\", r"\\")
                .replace("{", r"\{")
                .replace("}", r"\}")
                .replace("\n", r"\N")
            )

            f.write(
                f"Dialogue: 0,{ass_time(item['start'])},"
                f"{ass_time(item['end'])},Default,,0,0,0,,{text}\n"
            )


def burn(video_path, ass_path, output_path):
    ensure_khmer_font()
    font_dir = FONT_DIR.replace("\\", "/")
    ass_file = ass_path.replace("\\", "/")

    # shaping=complex is important for Khmer script rendering.
    vf = (
        f"ass=filename='{ass_file}':"
        f"fontsdir='{font_dir}':"
        f"shaping=complex"
    )

    command = [
        ffmpeg(),
        "-y",
        "-i", video_path,
        "-vf", vf,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(
            "FFmpeg បញ្ចូល Caption មិនបាន:\n\n" + error[-5000:]
        )

    return output_path

# ============================================================
# AUDIO EXTRACTION
# ============================================================

def extract_audio(video_path, output_wav):
    try:
        import av

        container = av.open(video_path)
        stream = next(
            (s for s in container.streams if s.type == "audio"),
            None,
        )
        if stream is None:
            raise RuntimeError("រកមិនឃើញ Audio ក្នុងវីដេអូ")

        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000,
        )

        pcm = bytearray()
        for frame in container.decode(stream):
            frames = resampler.resample(frame)
            if not isinstance(frames, list):
                frames = [frames]
            for converted in frames:
                for plane in converted.planes:
                    pcm.extend(plane.to_bytes())

        container.close()

        if not pcm:
            raise RuntimeError("Audio ទទេ")

        with wave.open(output_wav, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(pcm))

        return output_wav

    except Exception:
        command = [
            ffmpeg(),
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            output_wav,
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(
                "មិនអាច Extract Audio បាន:\n\n" + error[-4000:]
            )

        return output_wav

# ============================================================
# GEMINI TTS — EXISTING FEATURE
# ============================================================

def gemini_tts(client, text, output_wav):
    response = retry_gemini(
        lambda: client.models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE
                        )
                    )
                ),
            ),
        ),
        attempts=2,
        delay=4,
    )

    audio = get_value(response, "audio", None)

    if audio is None:
        candidates = get_value(response, "candidates", [])
        for candidate in candidates or []:
            content = get_value(candidate, "content", None)
            for part in get_value(content, "parts", []) or []:
                inline = get_value(part, "inline_data", None)
                if inline:
                    audio = inline
                    break
            if audio:
                break

    if audio is None:
        raise RuntimeError("Gemini មិនបានបញ្ជូនសំឡេងត្រឡប់មកវិញ")

    data = get_value(audio, "data", None)
    if isinstance(data, str):
        data = base64.b64decode(data)
    if not data:
        raise RuntimeError("ទិន្នន័យ TTS ទទេ")

    mime = get_value(audio, "mime_type", "") or ""

    if "wav" not in mime.lower():
        with wave.open(output_wav, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(data)
    else:
        with open(output_wav, "wb") as f:
            f.write(data)

    return output_wav

# ============================================================
# DOWNLOAD VIDEO — EXISTING FEATURE
# ============================================================

MEDIA_RE = re.compile(
    r'https?://[^\s"\']+\.(?:mp4|m3u8)(?:\?[^\s"\']*)?',
    re.IGNORECASE,
)


def find_media_urls(html):
    return list(dict.fromkeys(MEDIA_RE.findall(html)))


def download_media_url(url, output_path):
    urllib.request.urlretrieve(url, output_path)
    return output_path


def page_media_download(page_url, output_path):
    request = urllib.request.Request(
        page_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Android 10; Mobile) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    for url in find_media_urls(html):
        try:
            return download_media_url(url, output_path)
        except Exception:
            continue

    raise RuntimeError("រកមិនឃើញ MP4/M3U8 សាធារណៈក្នុងទំព័រនេះ")


def webpage_download(page_url, output_path):
    """Download a public video URL/page with yt-dlp first.

    FFmpeg is explicitly supplied so yt-dlp can merge video/audio on
    Streamlit Cloud. Falls back to a direct public MP4/M3U8 URL.
    """
    import yt_dlp

    errors = []

    formats = [
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "best",
    ]

    for fmt in formats:
        try:
            options = {
                "outtmpl": output_path,
                "format": fmt,
                "merge_output_format": "mp4",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "ffmpeg_location": ffmpeg(),
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
            }

            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([page_url])

            # yt-dlp may write the requested path directly or with a final
            # extension. Accept either result.
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return output_path

            base, _ = os.path.splitext(output_path)
            for candidate in (base + ".mp4", base + ".webm", base + ".mkv"):
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    if candidate != output_path:
                        os.replace(candidate, output_path)
                    return output_path

        except Exception as exc:
            errors.append(str(exc))

    try:
        return page_media_download(page_url, output_path)
    except Exception as exc:
        errors.append(str(exc))

    raise RuntimeError(
        "មិនអាច Download វីដេអូនេះបានទេ។ សូមពិនិត្យ Link ឬវីដេអូថាជា Public។\n\n"
        + "\n".join(errors[-3:])
    )

# ============================================================
# UI — DOWNLOAD VIDEO
# ============================================================

with st.expander("⬇️ Download Video"):
    page_url = st.text_input(
        "ដាក់ Page / Video URL",
        placeholder="https://...",
    )

    if st.button("⬇️ Download"):
        if not page_url.strip():
            st.warning("សូមដាក់ Link ជាមុន")
        else:
            try:
                with st.spinner("កំពុង Download..."):
                    output = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=".mp4",
                    )
                    output.close()
                    webpage_download(page_url.strip(), output.name)

                with open(output.name, "rb") as f:
                    st.download_button(
                        "📥 Save Video",
                        f,
                        file_name="download.mp4",
                        mime="video/mp4",
                    )
                st.success("Download រួចរាល់")
            except Exception as e:
                st.error(str(e))

# ============================================================
# UI — TEXT → GEMINI VOICE
# ============================================================

with st.expander("🎙️ Text → Gemini Voice"):
    api_key_tts = get_api_key()

    tts_text = st.text_area(
        "បញ្ចូលអត្ថបទ",
        height=120,
        key="tts_text",
    )

    if st.button("🎙️ Generate Voice"):
        if not api_key_tts:
            st.error("មិនទាន់កំណត់ GEMINI_API_KEY ក្នុង Streamlit Secrets ទេ។")
        elif not tts_text.strip():
            st.warning("សូមបញ្ចូលអត្ថបទ")
        else:
            try:
                client = get_gemini_client(api_key_tts)
                output = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".wav",
                )
                output.close()

                with st.spinner("កំពុងបង្កើតសំឡេង..."):
                    gemini_tts(client, tts_text.strip(), output.name)

                with open(output.name, "rb") as f:
                    audio_bytes = f.read()
                st.audio(audio_bytes, format="audio/wav")

                with open(output.name, "rb") as f:
                    st.download_button(
                        "📥 Download Voice",
                        f,
                        file_name="gemini_voice.wav",
                        mime="audio/wav",
                    )
            except Exception as e:
                st.error(str(e))

# ============================================================
# UI — AUTO CAPTION
# ============================================================

st.divider()
st.subheader("🎬 Auto Caption")

api_key = get_api_key()

source_language = st.selectbox(
    "ភាសាសំឡេងដើម",
    ["Auto", "Chinese", "Khmer"],
)

target_language = st.selectbox(
    "ភាសា Caption",
    ["Khmer", "Chinese", "No translation"],
)

uploaded_video = st.file_uploader(
    "📤 Upload Video",
    type=["mp4", "mov", "mkv", "webm", "avi"],
)

if uploaded_video:
    st.video(uploaded_video)

if st.button("🚀 Auto Caption", type="primary"):
    if not api_key:
        st.error("មិនទាន់កំណត់ GEMINI_API_KEY ក្នុង Streamlit Secrets ទេ។")
        st.stop()

    if not uploaded_video:
        st.warning("សូម Upload Video ជាមុន")
        st.stop()

    client = get_gemini_client(api_key)
    temp_dir = tempfile.mkdtemp()

    input_video = os.path.join(temp_dir, "input.mp4")
    audio_path = os.path.join(temp_dir, "audio.wav")
    ass_path = os.path.join(temp_dir, "captions.ass")
    output_video = os.path.join(temp_dir, "Smey_Auto_Caption.mp4")

    try:
        with open(input_video, "wb") as f:
            f.write(uploaded_video.getbuffer())

        with st.status(
            "កំពុងដំណើរការ Auto Caption...",
            expanded=True,
        ) as status:
            st.write("🎧 1/5 កំពុងយកសំឡេងពីវីដេអូ...")
            extract_audio(input_video, audio_path)

            st.write("📝 2/5 កំពុងស្តាប់ និងកំណត់ Word Timing...")
            transcription = transcribe(
                client,
                audio_path,
                source_language if source_language != "Auto" else None,
            )

            words = words_from(transcription)
            if not words:
                raise RuntimeError(
                    "Gemini មិនបានផ្តល់ Word Timing។ សូមសាកល្បងម្តងទៀត។"
                )

            groups = make_groups(words)
            full_text = " ".join(item["text"] for item in groups)
            detected = detect_language(full_text)
            st.write(f"🌐 ភាសាដែលបានរកឃើញ: **{detected}**")

            st.write("🔄 3/5 កំពុងបកប្រែ Caption...")
            final_groups = translate_groups(
                client,
                groups,
                target_language,
            )

            st.write("🎞️ 4/5 កំពុងបង្កើត Caption...")
            make_ass(final_groups, ass_path)

            st.write("🔥 5/5 កំពុងបញ្ចូល Caption ទៅក្នុង MP4...")
            burn(input_video, ass_path, output_video)

            status.update(
                label="✅ Auto Caption រួចរាល់!",
                state="complete",
            )

        st.success(f"រកឃើញ {len(final_groups)} Caption")

        st.subheader("📝 Caption Preview")
        for item in final_groups:
            st.write(
                f"`{ass_time(item['start'])} → {ass_time(item['end'])}`  "
                f"{item['text']}"
            )

        st.subheader("🎬 Result")
        st.video(output_video)

        with open(output_video, "rb") as f:
            st.download_button(
                "📥 Download MP4",
                f,
                file_name="Smey_Auto_Caption.mp4",
                mime="video/mp4",
            )

    except Exception as e:
        st.error(f"❌ Auto Caption មិនអាចបញ្ចប់បាន: {e}")
