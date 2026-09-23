import os
import re
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
st.write("🎙️ Gemini → Caption ខ្មែរ → MP4")
st.info("Gemini 3.5 Transcribe")


# =========================================================
# API KEY
# =========================================================

api_key = st.text_input(
    "🔑 Gemini API Key",
    type="password",
    placeholder="បញ្ចូល Gemini API Key"
)

if not api_key:
    st.warning(
        "សូមបញ្ចូល Gemini API Key មុន"
    )
    st.stop()


# =========================================================
# GEMINI
# =========================================================

client = genai.Client(
    api_key=api_key
)


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
# TEXT CLEAN
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

    # Google returns values such as:
    # 0.100s
    # 1.250s

    if value.endswith("s"):

        try:
            return float(
                value[:-1]
            )
        except:
            return None

    try:
        return float(value)

    except:
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
# GET WORD TIMESTAMPS FROM GEMINI
# =========================================================

def get_words(response):

    words = []

    for candidate in (
        getattr(
            response,
            "candidates",
            []
        )
        or []
    ):

        content = getattr(
            candidate,
            "content",
            None
        )

        if content is None:
            continue

        parts = getattr(
            content,
            "parts",
            []
        ) or []

        for part in parts:

            transcription = getattr(
                part,
                "audio_transcription",
                None
            )

            if not transcription:
                continue

            word_list = getattr(
                transcription,
                "words",
                []
            ) or []

            for word_info in word_list:

                word = clean_text(
                    getattr(
                        word_info,
                        "word",
                        ""
                    )
                )

                start = seconds_from_offset(
                    getattr(
                        word_info,
                        "start_offset",
                        None
                    )
                )

                end = seconds_from_offset(
                    getattr(
                        word_info,
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
# GROUP WORDS INTO NATURAL CAPTIONS
#
# មិនបង្ហាញពាក្យមួយៗ
# ក៏មិនបង្ហាញប្រយោគទាំងអស់តាំងពីដើម
#
# Caption នឹងតាមការនិយាយ
# =========================================================

def make_captions(words):

    captions = []

    current = []

    start = None
    end = None

    for item in words:

        word = item["word"]

        if start is None:
            start = item["start"]

        current.append(word)

        end = item["end"]

        text = clean_text(
            " ".join(current)
        )

        duration = end - start

        should_finish = False

        # Caption មិនវែងពេក
        if len(text) >= 32:
            should_finish = True

        # ប្រហែល 2.2 វិនាទី
        if duration >= 2.2:
            should_finish = True

        # ចប់ប្រយោគ
        if text.endswith(
            (
                "។",
                "?",
                "!",
                "…",
                ":"
            )
        ):
            should_finish = True

        if should_finish:

            captions.append({
                "start": start,
                "end": end,
                "text": text
            })

            current = []
            start = None
            end = None

    if current and start is not None:

        text = clean_text(
            " ".join(current)
        )

        if text:

            captions.append({
                "start": start,
                "end": end,
                "text": text
            })

    return captions


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
                + ass_time(
                    item["start"]
                )
                + ","
                + ass_time(
                    item["end"]
                )
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
        .replace(
            "\\",
            "/"
        )
        .replace(
            ":",
            r"\:"
        )
        .replace(
            "'",
            r"\'"
        )
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
        "⚡ បង្កើត Caption ខ្មែរ",
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
                # 2. Upload audio to Gemini
                # ---------------------------------------------

                with st.spinner(
                    "☁️ កំពុងបញ្ជូនសំឡេងទៅ Gemini..."
                ):

                    audio_file = client.files.upload(
                        file=audio_path
                    )

                # ---------------------------------------------
                # 3. Gemini transcription
                # ---------------------------------------------

                with st.spinner(
                    "🧠 Gemini កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    response = client.models.generate_content(
                        model="gemini-3.5-transcribe",
                        contents=[
                            audio_file
                        ],
                        config=types.GenerateContentConfig(
                            audio_transcription_config=(
                                types.AudioTranscriptionConfig(
                                    language_codes=["km-KH"],
                                    word_timestamp=True
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
                        "❌ Gemini មិនបានបញ្ជូន Word Timing មកទេ។"
                    )

                    # បង្ហាញ transcript ដើម្បីពិនិត្យ
                    transcript = getattr(
                        response,
                        "text",
                        ""
                    )

                    if transcript:

                        st.write(
                            "Transcript:"
                        )

                        st.write(
                            transcript
                        )

                    st.stop()

                # ---------------------------------------------
                # 5. Natural captions
                # ---------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption តាមការនិយាយ..."
                ):

                    captions = make_captions(
                        words
                    )

                if not captions:

                    st.error(
                        "❌ មិនមាន Caption"
                    )

                    st.stop()

                # ---------------------------------------------
                # 6. ASS
                # ---------------------------------------------

                create_ass(
                    captions,
                    ass_path
                )

                # ---------------------------------------------
                # 7. Burn
                # ---------------------------------------------

                with st.spinner(
                    "🎬 កំពុងបង្កើត MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # ---------------------------------------------
                # 8. Result
                # ---------------------------------------------

                with open(
                    output_path,
                    "rb"
                ) as f:

                    output_data = f.read()

                st.success(
                    "✅ រួចរាល់!"
                )

                st.video(
                    output_data
                )

                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=output_data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )

            except Exception as e:

                st.error(
                    "❌ Gemini មានបញ្ហា"
                )

                st.code(
                    str(e)
                )
