import streamlit as st
import subprocess
import tempfile
import os
import threading
import time
from transformers import pipeline


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭"
)

st.title("🇰🇭 Smey Auto Caption")
st.write("បញ្ចូលវីដេអូ → ស្គាល់សំឡេងខ្មែរ → Caption តាមការនិយាយ")


# =========================================================
# QUEUE
# =========================================================

if "processing_lock" not in st.session_state:
    pass


@st.cache_resource
def get_processing_lock():
    return threading.Lock()


processing_lock = get_processing_lock()


# =========================================================
# MODEL
# =========================================================

@st.cache_resource
def load_model():

    return pipeline(
        "automatic-speech-recognition",
        model="1morecupofhottea/whisper-turbo-khmer-v9",
        chunk_length_s=30,
        device=-1
    )


# =========================================================
# TIME
# =========================================================

def ass_time(seconds):

    seconds = max(0, float(seconds))

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60

    return f"{h}:{m:02d}:{s:05.2f}"


# =========================================================
# VIDEO DURATION
# =========================================================

def get_duration(filename):

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filename
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return float(result.stdout.strip())


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    return (
        text
        .strip()
        .replace("\n", " ")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


# =========================================================
# WORD TIMESTAMP GROUPS
# =========================================================

def make_word_groups(chunks, words_per_caption=4):

    words = []

    for chunk in chunks:

        text = chunk.get("text", "")
        timestamp = chunk.get("timestamp")

        if not text or not timestamp:
            continue

        start, end = timestamp

        if start is None or end is None:
            continue

        text = text.strip()

        if not text:
            continue

        pieces = text.split()

        if not pieces:
            continue

        total = len(pieces)
        duration = max(0.05, end - start)

        for i, piece in enumerate(pieces):

            word_start = start + (
                duration * i / total
            )

            word_end = start + (
                duration * (i + 1) / total
            )

            words.append(
                (
                    word_start,
                    word_end,
                    piece
                )
            )

    if not words:
        return []

    groups = []

    current_words = []
    current_start = None
    current_end = None

    for start, end, word in words:

        if current_start is None:
            current_start = start

        current_words.append(word)
        current_end = end

        if len(current_words) >= words_per_caption:

            groups.append(
                (
                    current_start,
                    current_end,
                    " ".join(current_words)
                )
            )

            current_words = []
            current_start = None
            current_end = None

    if current_words:

        groups.append(
            (
                current_start,
                current_end,
                " ".join(current_words)
            )
        )

    return groups


# =========================================================
# SEGMENT TIMESTAMP FALLBACK
# =========================================================

def make_segment_groups(chunks):

    groups = []

    for chunk in chunks:

        timestamp = chunk.get("timestamp")
        text = chunk.get("text", "").strip()

        if not timestamp or not text:
            continue

        start, end = timestamp

        if start is None or end is None:
            continue

        text = clean_text(text)

        if text:

            groups.append(
                (
                    start,
                    end,
                    text
                )
            )

    return groups


# =========================================================
# TEXT FALLBACK
# =========================================================

def make_fallback_groups(text, duration):

    text = text.strip()

    if not text:
        return []

    parts = [
        x.strip()
        for x in text.split(";")
        if x.strip()
    ]

    if len(parts) == 1:

        words = parts[0].split()

        parts = []
        current = []

        for word in words:

            current.append(word)

            if len(current) >= 4:

                parts.append(
                    " ".join(current)
                )

                current = []

        if current:

            parts.append(
                " ".join(current)
            )

    if not parts:
        return []

    step = duration / len(parts)

    groups = []

    for i, part in enumerate(parts):

        start = i * step
        end = (i + 1) * step

        groups.append(
            (
                start,
                end,
                clean_text(part)
            )
        )

    return groups


# =========================================================
# CREATE ASS
# =========================================================

def create_ass(groups, filename):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,4,1,2,50,50,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(header)

        for start, end, text in groups:

            text = clean_text(text)

            if not text:
                continue

            f.write(
                "Dialogue: 0,"
                + ass_time(start)
                + ","
                + ass_time(end)
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


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


if video:

    st.video(video)

    if st.button(
        "🚀 បង្កើត Caption ខ្មែរ",
        use_container_width=True
    ):

        # =================================================
        # QUEUE
        # =================================================

        if processing_lock.locked():

            st.info(
                "⏳ មានអ្នកផ្សេងកំពុងប្រើ AI។ "
                "អ្នកត្រូវបានដាក់ចូលជួរ ហើយនឹងដំណើរការបន្ទាប់។"
            )

        queue_start = time.time()

        with st.spinner(
            "⏳ កំពុងរង់ចាំជួរ..."
        ):

            processing_lock.acquire()

        wait_time = time.time() - queue_start

        try:

            if wait_time > 1:

                st.success(
                    "✅ ដល់វេនរបស់អ្នកហើយ!"
                )

            else:

                st.info(
                    "🚀 ចាប់ផ្តើមដំណើរការ..."
                )


            # =============================================
            # TEMP FILES
            # =============================================

            with tempfile.TemporaryDirectory() as folder:

                input_file = os.path.join(
                    folder,
                    "input.mp4"
                )

                audio_file = os.path.join(
                    folder,
                    "audio.wav"
                )

                ass_file = os.path.join(
                    folder,
                    "caption.ass"
                )

                output_file = os.path.join(
                    folder,
                    "output.mp4"
                )


                # =========================================
                # SAVE VIDEO
                # =========================================

                with open(
                    input_file,
                    "wb"
                ) as f:

                    f.write(
                        video.getbuffer()
                    )


                # =========================================
                # EXTRACT AUDIO
                # =========================================

                with st.spinner(
                    "🔊 កំពុងរៀបចំសំឡេង..."
                ):

                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            input_file,
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            "-c:a",
                            "pcm_s16le",
                            audio_file
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE
                    )


                duration = get_duration(
                    input_file
                )


                # =========================================
                # AI
                # =========================================

                with st.spinner(
                    "🎙️ AI កំពុងស្គាល់សំឡេងខ្មែរ..."
                ):

                    model = load_model()

                    try:

                        result = model(
                            audio_file,
                            return_timestamps="word"
                        )

                    except Exception:

                        result = model(
                            audio_file,
                            return_timestamps=True
                        )


                chunks = result.get(
                    "chunks",
                    []
                )


                # =========================================
                # WORD TIMESTAMP
                # =========================================

                groups = make_word_groups(
                    chunks,
                    words_per_caption=4
                )


                # =========================================
                # SEGMENT FALLBACK
                # =========================================

                if not groups:

                    groups = make_segment_groups(
                        chunks
                    )


                # =========================================
                # TEXT FALLBACK
                # =========================================

                if not groups:

                    full_text = result.get(
                        "text",
                        ""
                    )

                    groups = make_fallback_groups(
                        full_text,
                        duration
                    )


                if not groups:

                    st.error(
                        "❌ AI មិនអាចស្គាល់សំឡេងបានទេ។"
                    )

                    st.stop()


                # =========================================
                # CREATE CAPTION
                # =========================================

                create_ass(
                    groups,
                    ass_file
                )


                # =========================================
                # BURN CAPTION
                # =========================================

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption តាមសំឡេង..."
                ):

                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            input_file,
                            "-vf",
                            f"ass={ass_file}",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-c:a",
                            "aac",
                            "-movflags",
                            "+faststart",
                            output_file
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE
                    )


                # =========================================
                # RESULT
                # =========================================

                st.success(
                    "✅ រួចរាល់!"
                )

                with open(
                    output_file,
                    "rb"
                ) as f:

                    st.download_button(
                        "⬇️ ទាញយកវីដេអូមាន Caption",
                        f,
                        file_name="khmer_caption.mp4",
                        mime="video/mp4",
                        use_container_width=True
                    )

        finally:

            processing_lock.release()
