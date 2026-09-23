import os
import re
import json
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg

from google import genai
from google.genai import types


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭"
)

st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ ស្តាប់ → បកប្រែ → Caption ខ្មែរ → MP4")


# =========================================================
# API KEY
# =========================================================

api_key = ""

try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

if not api_key:

    api_key = st.text_input(
        "🔑 Gemini API Key",
        type="password"
    )

if not api_key:

    st.warning(
        "សូមដាក់ Gemini API Key"
    )

    st.stop()


client = genai.Client(
    api_key=api_key
)


# =========================================================
# SOURCE LANGUAGE
# =========================================================

source_language = st.selectbox(
    "🌐 ភាសាដើម",
    [
        "ចិន",
        "អង់គ្លេស",
        "ជប៉ុន",
        "កូរ៉េ",
        "វៀតណាម",
        "ថៃ",
        "ខ្មែរ",
        "ស្វ័យប្រវត្តិ"
    ],
    index=0
)


language_map = {
    "ចិន": "zh-CN",
    "អង់គ្លេស": "en-US",
    "ជប៉ុន": "ja-JP",
    "កូរ៉េ": "ko-KR",
    "វៀតណាម": "vi-VN",
    "ថៃ": "th-TH",
    "ខ្មែរ": "km-KH",
    "ស្វ័យប្រវត្តិ": ""
}


# =========================================================
# FFMPEG
# =========================================================

def run_ffmpeg(args):

    exe = imageio_ffmpeg.get_ffmpeg_exe()

    result = subprocess.run(
        [exe] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False
    )

    if result.returncode != 0:

        error = result.stderr.decode(
            "utf-8",
            errors="ignore"
        )

        raise RuntimeError(error)


def extract_audio(
    video_path,
    audio_path
):

    run_ffmpeg([
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        audio_path
    ])


# =========================================================
# TEXT
# =========================================================

def clean_text(text):

    text = str(text)

    text = text.replace(
        "\n",
        " "
    )

    text = text.replace(
        "\r",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# TIME
# =========================================================

def seconds_from_offset(value):

    if value is None:
        return None

    value = str(value).strip()

    if value.endswith("s"):

        try:
            return float(
                value[:-1]
            )
        except Exception:
            return None

    try:
        return float(value)
    except Exception:
        return None


def ass_time(seconds):

    seconds = max(
        0.0,
        float(seconds)
    )

    h = int(
        seconds // 3600
    )

    m = int(
        (seconds % 3600) // 60
    )

    s = int(
        seconds % 60
    )

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return (
        f"{h}:"
        f"{m:02d}:"
        f"{s:02d}."
        f"{cs:02d}"
    )


# =========================================================
# GEMINI WORD TIMESTAMPS
# =========================================================

def get_words(response):

    words = []

    candidates = (
        getattr(
            response,
            "candidates",
            []
        )
        or []
    )

    for candidate in candidates:

        content = getattr(
            candidate,
            "content",
            None
        )

        if content is None:
            continue

        parts = (
            getattr(
                content,
                "parts",
                []
            )
            or []
        )

        for part in parts:

            transcription = getattr(
                part,
                "audio_transcription",
                None
            )

            if not transcription:
                continue

            word_list = (
                getattr(
                    transcription,
                    "words",
                    []
                )
                or []
            )

            for info in word_list:

                word = clean_text(
                    getattr(
                        info,
                        "word",
                        ""
                    )
                )

                start = seconds_from_offset(
                    getattr(
                        info,
                        "start_offset",
                        None
                    )
                )

                end = seconds_from_offset(
                    getattr(
                        info,
                        "end_offset",
                        None
                    )
                )

                if not word:
                    continue

                if start is None:
                    continue

                if end is None:
                    end = start + 0.25

                if end <= start:
                    end = start + 0.25

                words.append({
                    "word": word,
                    "start": start,
                    "end": end
                })

    words.sort(
        key=lambda x: x["start"]
    )

    return words


# =========================================================
# MAKE CAPTION SEGMENTS
# =========================================================

def make_segments(words):

    segments = []

    current = []

    start = None
    end = None

    for item in words:

        if start is None:
            start = item["start"]

        current.append(
            item["word"]
        )

        end = item["end"]

        text = clean_text(
            " ".join(current)
        )

        duration = end - start

        finish = False

        if len(text) >= 35:
            finish = True

        if duration >= 2.5:
            finish = True

        if text.endswith(
            (
                "。",
                "?",
                "!",
                "…",
                ":"
            )
        ):
            finish = True

        if finish:

            segments.append({
                "id": len(segments) + 1,
                "start": start,
                "end": end,
                "source": text
            })

            current = []
            start = None
            end = None

    if current and start is not None:

        text = clean_text(
            " ".join(current)
        )

        segments.append({
            "id": len(segments) + 1,
            "start": start,
            "end": end,
            "source": text
        })

    return segments


# =========================================================
# TRANSLATE ALL CAPTIONS IN ONE REQUEST
# =========================================================

def translate_captions(
    segments,
    source_name
):

    payload = []

    for item in segments:

        payload.append({
            "id": item["id"],
            "text": item["source"]
        })

    prompt = f"""
អ្នកគឺជាអ្នកបកប្រែ Subtitle អាជីព។

ភាសាដើម៖ {source_name}
ភាសាគោលដៅ៖ ភាសាខ្មែរ

បកប្រែ Caption ទាំងអស់ខាងក្រោមទៅជាភាសាខ្មែរ។

ច្បាប់សំខាន់ៗ៖
1. រក្សា id ដដែល។
2. កុំប្តូរ ឬលុប id។
3. បកប្រែឲ្យមានន័យធម្មជាតិជាភាសាខ្មែរ។
4. កុំសង្ខេប។
5. កុំបន្ថែមការពន្យល់។
6. បើអត្ថបទដើមជាខ្មែរ សូមរក្សាជាខ្មែរ។
7. Output ត្រូវជា JSON array ប៉ុណ្ណោះ។

Caption:
{json.dumps(
    payload,
    ensure_ascii=False
)}
"""

    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "id": {
                    "type": "INTEGER"
                },
                "text": {
                    "type": "STRING"
                }
            },
            "required": [
                "id",
                "text"
            ]
        }
    }

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2
        )
    )

    raw = getattr(
        response,
        "text",
        ""
    )

    if not raw:
        raise RuntimeError(
            "Gemini មិនបានបញ្ជូនការបកប្រែមកទេ។"
        )

    translated = json.loads(
        raw
    )

    translation_map = {}

    for item in translated:

        item_id = int(
            item["id"]
        )

        translation_map[item_id] = (
            clean_text(
                item["text"]
            )
        )

    result = []

    for segment in segments:

        translated_text = (
            translation_map.get(
                segment["id"],
                segment["source"]
            )
        )

        result.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": translated_text
        })

    return result


# =========================================================
# ASS
# =========================================================

def create_ass(
    captions,
    path
):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,45,45,145,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(header)

        for item in captions:

            text = clean_text(
                item["text"]
            )

            text = text.replace(
                "{",
                r"\{"
            )

            text = text.replace(
                "}",
                r"\}"
            )

            f.write(
                "Dialogue: 0,"
                + ass_time(item["start"])
                + ","
                + ass_time(item["end"])
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


# =========================================================
# BURN CAPTION
# =========================================================

def burn_caption(
    video_path,
    ass_path,
    output_path
):

    filter_path = (
        ass_path
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    run_ffmpeg([
        "-y",
        "-i",
        video_path,
        "-vf",
        f"ass='{filter_path}'",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "26",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path
    ])


# =========================================================
# UPLOAD
# =========================================================

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm"
    ]
)


# =========================================================
# PROCESS
# =========================================================

if video:

    st.video(video)

    if st.button(
        "⚡ បកប្រែ + បង្កើត Caption ខ្មែរ",
        use_container_width=True
    ):

        with tempfile.TemporaryDirectory() as folder:

            video_path = os.path.join(
                folder,
                "input.mp4"
            )

            audio_path = os.path.join(
                folder,
                "audio.wav"
            )

            ass_path = os.path.join(
                folder,
                "caption.ass"
            )

            output_path = os.path.join(
                folder,
                "smey_auto_caption.mp4"
            )

            with open(
                video_path,
                "wb"
            ) as f:

                f.write(
                    video.getbuffer()
                )

            try:

                # ---------------------------------------------
                # 1. Extract audio
                # ---------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                # ---------------------------------------------
                # 2. Upload audio
                # ---------------------------------------------

                with st.spinner(
                    "☁️ កំពុងបញ្ជូនសំឡេងទៅ Gemini..."
                ):

                    audio_file = client.files.upload(
                        file=audio_path
                    )

                # ---------------------------------------------
                # 3. Transcribe
                # ---------------------------------------------

                with st.spinner(
                    "🎙️ Gemini កំពុងស្តាប់សំឡេង..."
                ):

                    language_code = (
                        language_map[
                            source_language
                        ]
                    )

                    config_args = {
                        "word_timestamp": True
                    }

                    if language_code:
                        config_args[
                            "language_codes"
                        ] = [
                            language_code
                        ]

                    response = (
                        client.models.generate_content(
                            model="gemini-3.5-transcribe",
                            contents=[
                                audio_file
                            ],
                            config=types.GenerateContentConfig(
                                audio_transcription_config=(
                                    types.AudioTranscriptionConfig(
                                        **config_args
                                    )
                                )
                            )
                        )
                    )

                # ---------------------------------------------
                # 4. Get word timestamps
                # ---------------------------------------------

                words = get_words(
                    response
                )

                if not words:

                    st.error(
                        "❌ Gemini មិនបានផ្តល់ Timing មកទេ។"
                    )

                    st.stop()

                # ---------------------------------------------
                # 5. Make source captions
                # ---------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption ដើម..."
                ):

                    source_segments = (
                        make_segments(
                            words
                        )
                    )

                if not source_segments:

                    st.error(
                        "❌ រកមិនឃើញ Caption"
                    )

                    st.stop()

                # ---------------------------------------------
                # 6. Translate
                # ---------------------------------------------

                with st.spinner(
                    "🇰🇭 Gemini កំពុងបកប្រែ Caption ជាខ្មែរ..."
                ):

                    khmer_captions = (
                        translate_captions(
                            source_segments,
                            source_language
                        )
                    )

                # ---------------------------------------------
                # 7. Create ASS
                # ---------------------------------------------

                with st.spinner(
                    "⏱️ កំពុងរក្សា Timing ដើម..."
                ):

                    create_ass(
                        khmer_captions,
                        ass_path
                    )

                # ---------------------------------------------
                # 8. Burn
                # ---------------------------------------------

                with st.spinner(
                    "🎬 កំពុងបញ្ចូល Caption ខ្មែរ..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # ---------------------------------------------
                # 9. Result
                # ---------------------------------------------

                with open(
                    output_path,
                    "rb"
                ) as f:

                    output_data = f.read()

                st.success(
                    "✅ បកប្រែ + Caption រួចរាល់!"
                )

                st.video(
                    output_data
                )

                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=output_data,
                    file_name="smey_auto_caption_khmer.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )

            except Exception as error:

                st.error(
                    "❌ App មានបញ្ហា"
                )

                st.code(
                    str(error)
                )
