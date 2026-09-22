import os
import re
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg
from faster_whisper import WhisperModel


# =========================================================
# APP
# =========================================================

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ Khmer Speech → Caption → MP4")
st.info("🆓 Free Version — មិនប្រើ Gemini API")


# =========================================================
# LOGO
# =========================================================

LOGO_FILE = "file_00000000568c8211831d7859c11ddf61.png"

if os.path.exists(LOGO_FILE):
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.image(LOGO_FILE, width=300)


# =========================================================
# FFMPEG
# =========================================================

def run_ffmpeg(args):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [ffmpeg] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def extract_audio(video_path, audio_path):
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
        audio_path,
    ])


# =========================================================
# KHMER WHISPER
# =========================================================

@st.cache_resource
def load_model():
    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
    )


# =========================================================
# TIME
# =========================================================

def ass_time(seconds):
    seconds = max(0.0, float(seconds))

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)

    cs = int(
        round((seconds - int(seconds)) * 100)
    )

    if cs >= 100:
        cs = 0
        s += 1

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# TEXT
# =========================================================

def clean_text(text):
    text = str(text)

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# =========================================================
# KHMER WORD HANDLING
# =========================================================

def word_text(word):
    return clean_text(
        getattr(
            word,
            "word",
            "",
        )
    )


def is_sentence_end(text):
    return bool(
        re.search(
            r"[។!?！？…]$",
            text,
        )
    )


# =========================================================
# MAKE TIMED CAPTIONS
# =========================================================

def make_timed_captions(segments):

    captions = []

    for segment in segments:

        words = getattr(
            segment,
            "words",
            None,
        )

        if not words:
            continue

        current_words = []
        current_start = None
        current_end = None

        for word in words:

            text = word_text(word)

            if not text:
                continue

            start = getattr(
                word,
                "start",
                None,
            )

            end = getattr(
                word,
                "end",
                None,
            )

            if start is None or end is None:
                continue

            start = float(start)
            end = float(end)

            if current_start is None:
                current_start = start

            current_words.append(text)
            current_end = end

            current_text = clean_text(
                " ".join(current_words)
            )

            duration = (
                current_end - current_start
            )

            # ប្តូរ Caption នៅពេល៖
            # 1. និយាយដល់ប្រហែល 1.6 វិនាទី
            # 2. ឃើញចប់ប្រយោគ
            # 3. មានអក្សរច្រើនពេក

            too_long = duration >= 1.6

            too_many_chars = (
                len(current_text) >= 32
            )

            sentence_finished = (
                is_sentence_end(current_text)
            )

            if (
                too_long
                or too_many_chars
                or sentence_finished
            ):

                captions.append({
                    "start": current_start,
                    "end": current_end,
                    "text": current_text,
                })

                current_words = []
                current_start = None
                current_end = None

        # ពាក្យដែលនៅសល់
        if (
            current_words
            and current_start is not None
            and current_end is not None
        ):

            text = clean_text(
                " ".join(current_words)
            )

            if text:
                captions.append({
                    "start": current_start,
                    "end": current_end,
                    "text": text,
                })

    # =====================================================
    # FIX OVERLAP
    # =====================================================

    captions.sort(
        key=lambda x: x["start"]
    )

    fixed = []

    for caption in captions:

        start = float(
            caption["start"]
        )

        end = float(
            caption["end"]
        )

        text = clean_text(
            caption["text"]
        )

        if not text:
            continue

        if fixed:

            previous = fixed[-1]

            if start < previous["end"]:
                start = previous["end"]

        if end <= start:
            end = start + 0.3

        fixed.append({
            "start": start,
            "end": end,
            "text": text,
        })

    return fixed


# =========================================================
# CREATE ASS
# =========================================================

def create_ass(captions, filename):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding

Style: Khmer,Noto Sans Khmer,70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,50,50,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(header)

        for caption in captions:

            text = clean_text(
                caption["text"]
            )

            text = text.replace(
                "{",
                r"\{",
            )

            text = text.replace(
                "}",
                r"\}",
            )

            start = ass_time(
                caption["start"]
            )

            end = ass_time(
                caption["end"]
            )

            f.write(
                "Dialogue: 0,"
                f"{start},"
                f"{end},"
                "Khmer,,0,0,0,,"
                f"{text}\n"
            )


# =========================================================
# BURN CAPTION
# =========================================================

def burn_caption(
    video_path,
    ass_path,
    output_path,
):

    escaped_ass = (
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
        f"ass='{escaped_ass}'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ])


# =========================================================
# VIDEO
# =========================================================

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm",
    ],
)


# =========================================================
# PROCESS
# =========================================================

if video is not None:

    st.video(video)

    if st.button(
        "⚡ បង្កើត Caption ខ្មែរ",
        use_container_width=True,
    ):

        with tempfile.TemporaryDirectory() as temp_dir:

            video_path = os.path.join(
                temp_dir,
                "input.mp4",
            )

            audio_path = os.path.join(
                temp_dir,
                "audio.wav",
            )

            ass_path = os.path.join(
                temp_dir,
                "caption.ass",
            )

            output_path = os.path.join(
                temp_dir,
                "smey_auto_caption.mp4",
            )

            with open(
                video_path,
                "wb",
            ) as f:

                f.write(
                    video.getbuffer()
                )

            try:

                # ---------------------------------------------
                # AUDIO
                # ---------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path,
                    )


                # ---------------------------------------------
                # MODEL
                # ---------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()


                # ---------------------------------------------
                # TRANSCRIBE
                # ---------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=5,
                        best_of=5,
                        vad_filter=True,
                        word_timestamps=True,
                        condition_on_previous_text=False,
                    )

                    segments = list(
                        segments
                    )


                if not segments:

                    st.error(
                        "❌ មិនរកឃើញសំឡេងទេ។"
                    )

                    st.stop()


                # ---------------------------------------------
                # TIMING
                # ---------------------------------------------

                with st.spinner(
                    "📝 កំពុងកំណត់ពេល Caption តាមការនិយាយ..."
                ):

                    captions = make_timed_captions(
                        segments
                    )


                if not captions:

                    st.error(
                        "❌ មិនអាចបង្កើត Timing Caption បានទេ។"
                    )

                    st.stop()


                # ---------------------------------------------
                # ASS
                # ---------------------------------------------

                create_ass(
                    captions,
                    ass_path,
                )


                # ---------------------------------------------
                # BURN
                # ---------------------------------------------

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ចូលវីដេអូ..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path,
                    )


                # ---------------------------------------------
                # RESULT
                # ---------------------------------------------

                with open(
                    output_path,
                    "rb",
                ) as f:

                    output_data = f.read()


                st.success(
                    "✅ វីដេអូរួចរាល់!"
                )

                st.video(
                    output_data
                )

                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=output_data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )


            except Exception as e:

                st.error(
                    "❌ មានបញ្ហាពេលបង្កើត Caption"
                )

                st.exception(e)
