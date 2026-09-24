import os
import re
import json
import time
import tempfile
import subprocess
import urllib.request

import streamlit as st
from gtts import gTTS
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="🇰🇭 Smey Auto Caption",
    page_icon="🇰🇭"
)

st.title("🇰🇭 Smey Auto Caption")
st.caption("Caption • Translate • Free Voice • APK")


# =========================
# SETTINGS
# =========================

TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
TRANSLATE_MODEL = "gemini-3.1-flash-lite"

FONT_DIR = "fonts"
FONT_PATH = os.path.join(
    FONT_DIR,
    "NotoSansKhmer-Regular.ttf"
)

FONT_URL = (
    "https://raw.githubusercontent.com/"
    "ghostlypi/NotoSans/main/"
    "NotoSansKhmer-Regular.ttf"
)


# =========================
# BASIC
# =========================

def secret(name):
    try:
        return str(
            st.secrets.get(name, "") or ""
        ).strip()
    except Exception:
        return ""


def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def client():
    return genai.Client(
        api_key=secret("GEMINI_API_KEY")
    )


def value(obj, name, default=None):
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(obj, name, default)


def number(value):
    try:
        return float(
            str(value).replace("s", "")
        )
    except Exception:
        return 0.0


# =========================
# TRANSCRIBE
# =========================

def transcribe(c, audio_path, language):

    with open(audio_path, "rb") as f:
        data = f.read()

    options = {
        "word_timestamp": True
    }

    if language == "Khmer":
        options["language_codes"] = ["km-KH"]

    elif language == "Chinese":
        options["language_codes"] = [
            "cmn-Hans-CN"
        ]

    config = types.AudioTranscriptionConfig(
        **options
    )

    return c.models.generate_content(
        model=TRANSCRIBE_MODEL,
        contents=[
            types.Part.from_bytes(
                data=data,
                mime_type="audio/wav"
            ),
            (
                "Transcribe the speech exactly. "
                "Return accurate word-level timestamps. "
                "Do not translate."
            )
        ],
        config=types.GenerateContentConfig(
            audio_transcription_config=config
        )
    )


def get_words(response):

    result = []

    def add(word):

        text = value(
            word,
            "word",
            value(word, "text", "")
        )

        if not text:
            return

        start = value(
            word,
            "start_offset",
            value(
                word,
                "start_time",
                value(word, "start", 0)
            )
        )

        end = value(
            word,
            "end_offset",
            value(
                word,
                "end_time",
                value(word, "end", start)
            )
        )

        result.append({
            "text": str(text),
            "start": number(start),
            "end": number(end)
        })

    for candidate in value(
        response,
        "candidates",
        []
    ) or []:

        content = value(
            candidate,
            "content"
        )

        for part in value(
            content,
            "parts",
            []
        ) or []:

            transcription = value(
                part,
                "audio_transcription"
            )

            for word in value(
                transcription,
                "words",
                []
            ) or []:
                add(word)

    transcription = value(
        response,
        "audio_transcription"
    )

    for word in value(
        transcription,
        "words",
        []
    ) or []:
        add(word)

    return result


def make_groups(words):

    groups = []
    current = []

    for word in words:

        if current and (
            len(current) >= 12
            or word["end"]
            - current[0]["start"] >= 5
        ):
            groups.append(current)
            current = []

        current.append(word)

    if current:
        groups.append(current)

    return [
        {
            "text": " ".join(
                w["text"] for w in group
            ),
            "start": group[0]["start"],
            "end": group[-1]["end"]
        }
        for group in groups
    ]


# =========================
# TRANSLATE
# =========================

def translate(c, groups, language):

    if language == "No translation":
        return groups

    result = []

    for i in range(
        0,
        len(groups),
        15
    ):

        batch = groups[
            i:i + 15
        ]

        prompt = (
            f"Translate each subtitle line "
            f"into {language}.\n"
            "Return JSON array only. "
            "Keep the same order.\n\n"
            f"{[x['text'] for x in batch]}"
        )

        schema = types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.STRING
            )
        )

        try:

            response = c.models.generate_content(
                model=TRANSLATE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            )

            values = value(
                response,
                "parsed"
            )

            if not isinstance(
                values,
                list
            ):

                values = json.loads(
                    value(
                        response,
                        "text",
                        "[]"
                    )
                )

            if len(values) != len(batch):
                raise ValueError()

        except Exception:

            values = [
                x["text"]
                for x in batch
            ]

        for index, item in enumerate(batch):

            result.append({
                "text": str(
                    values[index]
                ),
                "start": item["start"],
                "end": item["end"]
            })

    return result


# =========================
# CAPTION
# =========================

def ass_time(seconds):

    seconds = max(
        0,
        float(seconds)
    )

    h = int(seconds // 3600)
    m = int(
        seconds % 3600 // 60
    )
    s = seconds % 60

    return (
        f"{h}:{m:02d}:{s:05.2f}"
    )


def ensure_font():

    os.makedirs(
        FONT_DIR,
        exist_ok=True
    )

    if os.path.exists(
        FONT_PATH
    ):
        return

    urllib.request.urlretrieve(
        FONT_URL,
        FONT_PATH
    )


def make_ass(groups, path):

    ensure_font()

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

    with open(
        path,
        "w",
        encoding="utf-8-sig"
    ) as f:

        f.write(header)

        for item in groups:

            text = (
                item["text"]
                .replace("\\", "\\\\")
                .replace("{", "\\{")
                .replace("}", "\\}")
            )

            f.write(
                "Dialogue: 0,"
                f"{ass_time(item['start'])},"
                f"{ass_time(item['end'])},"
                f"Default,,0,0,0,,"
                f"{text}\n"
            )


def extract_audio(
    video,
    audio
):

    result = subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-i",
            video,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            audio
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    if result.returncode != 0:
        raise RuntimeError(
            "មិនអាចយកសំឡេងពីវីដេអូបាន"
        )


def burn_caption(
    video,
    ass,
    output
):

    ensure_font()

    result = subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-i",
            video,
            "-vf",
            (
                f"ass={ass}:"
                f"fontsdir={FONT_DIR}:"
                "shaping=complex"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            output
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    if result.returncode != 0:

        raise RuntimeError(
            result.stderr.decode(
                errors="ignore"
            )[-3000:]
        )


# =========================
# APK
# =========================

with st.expander("📱 APK"):

    apk_data = st.session_state.get(
        "apk_data"
    )

    apk_name = st.session_state.get(
        "apk_name"
    )

    if apk_data and apk_name:

        st.success(
            f"📦 {apk_name}"
        )

        st.download_button(
            "⬇️ Download APK",
            apk_data,
            file_name=apk_name,
            mime=(
                "application/vnd.android."
                "package-archive"
            ),
            use_container_width=True,
            key="apk_download"
        )

    else:

        st.info(
            "មិនទាន់មាន APK"
        )

    with st.expander(
        "👑 Admin"
    ):

        password = st.text_input(
            "🔐 Password",
            type="password",
            key="apk_password"
        )

        uploaded_apk = st.file_uploader(
            "📤 Upload APK",
            type=["apk"],
            key="apk_file"
        )

        custom_name = st.text_input(
            "✏️ ឈ្មោះ APK",
            placeholder="ឧ. Smey AI VIP 1",
            key="apk_name_input"
        )

        if st.button(
            "⬆️ Upload APK",
            use_container_width=True,
            key="apk_upload_button"
        ):

            admin_password = secret(
                "APK_ADMIN_PASSWORD"
            )

            if not admin_password:

                st.error(
                    "សូមកំណត់ "
                    "APK_ADMIN_PASSWORD "
                    "ក្នុង Secrets"
                )

            elif password != admin_password:

                st.error(
                    "❌ Password មិនត្រឹមត្រូវ"
                )

            elif uploaded_apk is None:

                st.warning(
                    "⚠️ សូមជ្រើស APK"
                )

            else:

                name = (
                    custom_name.strip()
                    or os.path.splitext(
                        uploaded_apk.name
                    )[0]
                )

                name = re.sub(
                    r'[\\/:*?"<>|]',
                    "",
                    name
                ).strip()

                if not name:
                    name = "app"

                if not name.lower().endswith(
                    ".apk"
                ):
                    name += ".apk"

                st.session_state[
                    "apk_data"
                ] = uploaded_apk.getvalue()

                st.session_state[
                    "apk_name"
                ] = name

                st.success(
                    f"✅ Upload រួចរាល់: {name}"
                )

                st.rerun()


# =========================
# FREE VOICE
# =========================

with st.expander(
    "🎙️ Free Voice"
):

    voice_text = st.text_area(
        "បញ្ចូលអត្ថបទ",
        key="voice_text"
    )

    voice_language = st.selectbox(
        "ភាសា",
        [
            "Khmer",
            "Chinese",
            "English"
        ],
        key="voice_language"
    )

    if st.button(
        "🎙️ Generate Voice",
        key="voice_button"
    ):

        if not voice_text.strip():

            st.warning(
                "សូមបញ្ចូលអត្ថបទ"
            )

        else:

            languages = {
                "Khmer": "km",
                "Chinese": "zh-CN",
                "English": "en"
            }

            try:

                file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".mp3"
                )

                file.close()

                gTTS(
                    text=voice_text,
                    lang=languages[
                        voice_language
                    ],
                    slow=False
                ).save(file.name)

                with open(
                    file.name,
                    "rb"
                ) as f:

                    data = f.read()

                st.audio(
                    data,
                    format="audio/mp3"
                )

                st.download_button(
                    "📥 Download Voice",
                    data,
                    file_name="smey_voice.mp3",
                    mime="audio/mpeg",
                    key="voice_download"
                )

            except Exception as e:

                st.error(
                    f"❌ Voice Error: {e}"
                )


# =========================
# DOWNLOAD VIDEO
# =========================

with st.expander(
    "⬇️ Download Video"
):

    url = st.text_input(
        "ដាក់ Link វីដេអូ",
        key="video_url"
    )

    if st.button(
        "⬇️ Download",
        key="video_download_button"
    ):

        if not url.strip():

            st.warning(
                "សូមដាក់ Link"
            )

        else:

            try:

                import yt_dlp

                file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".mp4"
                )

                file.close()

                options = {
                    "outtmpl": file.name,
                    "format": "bv*+ba/b",
                    "merge_output_format": "mp4",
                    "noplaylist": True,
                    "quiet": True,
                    "ffmpeg_location": ffmpeg()
                }

                with yt_dlp.YoutubeDL(
                    options
                ) as ydl:

                    ydl.download(
                        [url.strip()]
                    )

                st.video(
                    file.name
                )

                with open(
                    file.name,
                    "rb"
                ) as f:

                    st.download_button(
                        "📥 Download MP4",
                        f,
                        file_name="video.mp4",
                        mime="video/mp4",
                        key="download_video"
                    )

            except Exception as e:

                st.error(
                    f"❌ Download Error: {e}"
                )


# =========================
# AUTO CAPTION
# =========================

st.divider()
st.subheader(
    "🎬 Auto Caption"
)

source_language = st.selectbox(
    "ភាសាសំឡេង",
    [
        "Auto",
        "Chinese",
        "Khmer"
    ],
    key="source_language"
)

target_language = st.selectbox(
    "ភាសា Caption",
    [
        "Khmer",
        "Chinese",
        "No translation"
    ],
    key="target_language"
)

video = st.file_uploader(
    "📤 Upload Video",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm",
        "avi"
    ],
    key="caption_video"
)

if video:
    st.video(video)


if st.button(
    "🚀 Auto Caption",
    type="primary",
    key="caption_button"
):

    if not secret(
        "GEMINI_API_KEY"
    ):

        st.error(
            "សូមដាក់ GEMINI_API_KEY "
            "ក្នុង Secrets"
        )

        st.stop()

    if not video:

        st.warning(
            "សូម Upload Video"
        )

        st.stop()

    temp = tempfile.mkdtemp()

    input_video = os.path.join(
        temp,
        "input.mp4"
    )

    audio_file = os.path.join(
        temp,
        "audio.wav"
    )

    ass_file = os.path.join(
        temp,
        "caption.ass"
    )

    output_video = os.path.join(
        temp,
        "Smey_Auto_Caption.mp4"
    )

    try:

        with open(
            input_video,
            "wb"
        ) as f:

            f.write(
                video.getbuffer()
            )

        c = client()

        with st.spinner(
            "🎧 កំពុងយកសំឡេង..."
        ):

            extract_audio(
                input_video,
                audio_file
            )

        with st.spinner(
            "📝 កំពុងស្តាប់..."
        ):

            response = transcribe(
                c,
                audio_file,
                (
                    source_language
                    if source_language != "Auto"
                    else None
                )
            )

        words = get_words(
            response
        )

        if not words:

            raise RuntimeError(
                "រកមិនឃើញ Word Timing"
            )

        groups = make_groups(
            words
        )

        with st.spinner(
            "🔄 កំពុងបកប្រែ..."
        ):

            groups = translate(
                c,
                groups,
                target_language
            )

        with st.spinner(
            "🔥 កំពុងបញ្ចូល Caption..."
        ):

            make_ass(
                groups,
                ass_file
            )

            burn_caption(
                input_video,
                ass_file,
                output_video
            )

        st.success(
            "✅ Auto Caption រួចរាល់!"
        )

        st.video(
            output_video
        )

        with open(
            output_video,
            "rb"
        ) as f:

            st.download_button(
                "📥 Download MP4",
                f,
                file_name=(
                    "Smey_Auto_Caption.mp4"
                ),
                mime="video/mp4",
                key="caption_download"
            )

    except Exception as e:

        st.error(
            f"❌ Error: {e}"
        )
