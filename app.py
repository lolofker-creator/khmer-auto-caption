import os
import subprocess
import tempfile
import urllib.request
import urllib.error
import ipaddress
import socket
from urllib.parse import urlparse

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
    p = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe()] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode:
        raise RuntimeError(
            p.stderr.decode("utf-8", errors="ignore")[-3000:]
        )


def sec(v):
    try:
        return float(str(v).replace("s", ""))
    except Exception:
        return 0.0


def words_from(response):
    words = []
    for step in getattr(response, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for a in getattr(content, "annotations", []) or []:
                if getattr(a, "type", None) == "word_info":
                    words.append(a)
    return words


def make_groups(words, max_words=10, max_seconds=4):
    groups = []
    current = []
    start = end = None

    for w in words:
        text = str(getattr(w, "text", "") or "").strip()
        if not text:
            continue

        s = sec(getattr(w, "start_offset", ""))
        e = sec(getattr(w, "end_offset", ""))

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


def translate_to_khmer(groups, client, source):
    if source == "🇰🇭 ខ្មែរ" or not groups:
        return groups

    result = []

    for i in range(0, len(groups), 10):
        batch = groups[i:i + 10]
        prompt = (
            f"Translate these {source} captions into natural Khmer. "
            "Return ONLY a JSON array, exactly one Khmer string per input, "
            "same order. Do not explain.\n\n"
            + "\n".join(
                f"{n + 1}. {g['text']}"
                for n, g in enumerate(batch)
            )
        )

        answer = None

        for attempt in range(3):
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
                time.sleep(10)

        if answer is None:
            answer = [g["text"] for g in batch]

        result.extend(answer)

    return [
        {**g, "text": text}
        for g, text in zip(groups, result)
    ]


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

def validate_url(url):
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("❌ URL មិនត្រឹមត្រូវ។")

    try:
        port = parsed.port
    except ValueError:
        raise RuntimeError("❌ Port ក្នុង URL មិនត្រឹមត្រូវ។")

    if port and port not in (80, 443):
        raise RuntimeError("❌ អនុញ្ញាតតែ Port 80/443។")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            port or 443,
            type=socket.SOCK_STREAM,
        )
    except Exception:
        raise RuntimeError("❌ មិនអាចភ្ជាប់ទៅ Website នេះបាន។")

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise RuntimeError("❌ URL នេះមិនអាចប្រើសម្រាប់ Download បានទេ។")

    return url.strip()


def direct_download(url, output_path):
    url = validate_url(url)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "video/mp4,video/*,application/octet-stream;q=0.9,*/*;q=0.5",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content_type = (r.headers.get("Content-Type") or "").lower()
            length = r.headers.get("Content-Length")

            if length:
                try:
                    if int(length) > MAX_DOWNLOAD_MB * 1024 * 1024:
                        raise RuntimeError(
                            f"❌ វីដេអូលើស {MAX_DOWNLOAD_MB}MB។"
                        )
                except ValueError:
                    pass

            if "text/html" in content_type:
                raise RuntimeError(
                    "❌ Link នេះមិនមែនជា Direct Video Link ទេ។ "
                    "ត្រូវប្រើ Link ដែលបើកជាវីដេអូ/MP4 ផ្ទាល់។"
                )

            total = 0

            with open(output_path, "wb") as f:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break

                    total += len(chunk)

                    if total > MAX_DOWNLOAD_MB * 1024 * 1024:
                        raise RuntimeError(
                            f"❌ វីដេអូលើស {MAX_DOWNLOAD_MB}MB។"
                        )

                    f.write(chunk)

    except urllib.error.HTTPError as e:
        raise RuntimeError(f"❌ Website ឆ្លើយ HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"❌ មិនអាចភ្ជាប់ Website បាន: {e.reason}") from e

    if total < 1000:
        raise RuntimeError("❌ File តូចពេក ឬមិនមែនវីដេអូ។")

    try:
        ffmpeg(["-v", "error", "-i", output_path, "-f", "null", "-"])
    except Exception as e:
        raise RuntimeError(
            "❌ Link នេះមិនមែនជា Video File ដែលអាចអានបាន។"
        ) from e

    return total


# ========================= UI =========================

st.title("🇰🇭 Smey Auto Caption")
st.caption("🎙️ Auto Caption → 🇰🇭 Khmer → MP4")

st.link_button(
    "📱 ទាក់ទងម្ចាស់តាម Telegram",
    TELEGRAM_URL,
    use_container_width=True,
)


# ========================= DIRECT VIDEO DOWNLOAD =========================

with st.expander("🎬 Download Video", expanded=False):
    st.caption(
        "ដាក់ Direct Video URL ដែលអាចបើកជាវីដេអូបាន។ "
        "ឧទាហរណ៍ Link .mp4។"
    )

    video_url = st.text_input(
        "🔗 Video URL",
        placeholder="https://example.com/video.mp4",
    )

    if st.button("⬇️ Download Video", use_container_width=True):
        if not video_url.strip():
            st.warning("សូមដាក់ Video URL ជាមុន។")
        else:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    output = os.path.join(tmp, "video.mp4")

                    with st.spinner("⬇️ កំពុង Download..."):
                        size = direct_download(
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
    "🌐 ភាសាដើម",
    [
        "🇨🇳 中文",
        "🇰🇭 ខ្មែរ",
        "🇬🇧 English",
    ],
    index=0,
)

translate = st.checkbox(
    "🇰🇭 បកប្រែ Caption ទៅខ្មែរ",
    value=True,
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
                    ffmpeg([
                        "-y",
                        "-i", video_path,
                        "-vn",
                        "-ac", "1",
                        "-ar", "16000",
                        "-c:a", "pcm_s16le",
                        audio_path,
                    ])

                client = genai.Client(
                    api_key=st.secrets["GEMINI_API_KEY"]
                )

                with st.spinner("🎙️ Gemini កំពុងស្តាប់សំឡេង..."):
                    audio_file = client.files.upload(file=audio_path)

                    lang = {
                        "🇨🇳 中文": "zh-CN",
                        "🇰🇭 ខ្មែរ": "km-KH",
                        "🇬🇧 English": "en-US",
                    }[source]

                    response = client.models.generate_content(
                        model="gemini-3.5-transcribe",
                        contents=[audio_file],
                        config=types.GenerateContentConfig(
                            audio_transcription_config=(
                                types.AudioTranscriptionConfig(
                                    word_timestamp=True,
                                    language_codes=[lang],
                                )
                            )
                        ),
                    )

                words = words_from(response)

                if not words:
                    raise RuntimeError(
                        "Gemini មិនបានផ្តល់ Word Timing មកទេ។"
                    )

                groups = make_groups(words)

                if translate and source != "🇰🇭 ខ្មែរ":
                    with st.spinner("🇰🇭 កំពុងបកប្រែទៅខ្មែរ..."):
                        groups = translate_to_khmer(
                            groups,
                            client,
                            source,
                        )

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
                
