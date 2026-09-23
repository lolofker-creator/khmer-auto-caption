import os
import re
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg
from faster_whisper import WhisperModel


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
    layout="centered",
)

st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ សំឡេងខ្មែរ → Caption ខ្មែរ → MP4")
st.info("🆓 Free — មិនប្រើ Gemini API")


# =========================================================
# FFMPEG
# =========================================================

def run_ffmpeg(args):
    exe = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [exe] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
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
        "PhanithLIM/whisper-tiny-khmer-ct2",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        num_workers=1,
    )


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    text = str(text)

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# ASS TIME
# =========================================================

def ass_time(seconds):

    seconds = max(0.0, float(seconds))

    h = int(seconds // 3600)

    m = int(
        (seconds % 3600) // 60
    )

    s = int(
        seconds % 60
    )

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# MAKE SHORT CAPTIONS
# =========================================================

def make_captions(segments):

    captions = []

    for segment in segments:

        words = getattr(
            segment,
            "words",
            None
        )

        if not words:
            continue

        current_words = []

        start_time = None
        end_time = None

        for word in words:

            word_text = clean_text(
                getattr(
                    word,
                    "word",
                    ""
                )
            )

            if not word_text:
                continue

            word_start = getattr(
                word,
                "start",
                None
            )

            word_end = getattr(
                word,
                "end",
                None
            )

            if word_start is None:
                continue

            if word_end is None:
                continue

            word_start = float(word_start)
            word_end = float(word_end)

            if start_time is None:
                start_time = word_start

            current_words.append(
                word_text
            )

            end_time = word_end

            text = clean_text(
                " ".join(current_words)
            )

            duration = (
                end_time - start_time
            )

            # Caption ខ្លីៗ
            should_cut = False

            # ប្រហែល 0.9 វិនាទី
            if duration >= 0.9:
                should_cut = True

            # កុំឲ្យអក្សរច្រើនពេក
            if len(text) >= 24:
                should_cut = True

            # បើចប់ប្រយោគ
            if text.endswith(
                (
                    "។",
                    "?",
                    "!",
                    "…",
                    "។។",
                )
            ):
                should_cut = True

            if should_cut:

                captions.append({
                    "start": start_time,
                    "end": end_time,
                    "text": text,
                })

                current_words = []
                start_time = None
                end_time = None

        # ពាក្យដែលនៅសល់
        if (
            current_words
            and start_time is not None
            and end_time is not None
        ):

            text = clean_text(
                " ".join(current_words)
            )

            if text:

                captions.append({
                    "start": start_time,
                    "end": end_time,
                    "text": text,
                })

    # =====================================================
    # FIX OVERLAP
    # =====================================================

    captions.sort(
        key=lambda x: x["start"]
    )

    fixed = []

    for item in captions:

        start = float(
            item["start"]
        )

        end = float(
            item["end"]
        )

        if fixed:

            previous_end = fixed[-1]["end"]

            if start < previous_end:
                start = previous_end

        if end <= start:
            end = start + 0.25

        fixed.append({
            "start": start,
            "end": end,
            "text": item["text"],
        })

    return fixed


# =========================================================
# ASS FILE
# =========================================================

def create_ass(captions, ass_path):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,45,45,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        ass_path,
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

            line = (
                "Dialogue: 0,"
                + ass_time(item["start"])
                + ","
                + ass_time(item["end"])
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )

            f.write(line)


# =========================================================
# BURN CAPTION INTO VIDEO
# =========================================================

def burn_caption(
    video_path,
    ass_path,
    output_path
):

    # FFmpeg filter path
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
        output_path,
    ])


# =========================================================
# UPLOAD
# =========================================================

uploaded_video = st.file_uploader(
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

if uploaded_video:

    st.video(uploaded_video)

    if st.button(
        "⚡ បង្កើត Caption ខ្មែរ",
        use_container_width=True,
    ):

        with tempfile.TemporaryDirectory() as temp_dir:

            video_path = os.path.join(
                temp_dir,
                "input.mp4"
            )

            audio_path = os.path.join(
                temp_dir,
                "audio.wav"
            )

            ass_path = os.path.join(
                temp_dir,
                "caption.ass"
            )

            output_path = os.path.join(
                temp_dir,
                "smey_auto_caption.mp4"
            )

            # Save uploaded video
            with open(
                video_path,
                "wb"
            ) as f:

                f.write(
                    uploaded_video.getbuffer()
                )

            try:

                # -------------------------------------------------
                # 1. Extract audio
                # -------------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេងពីវីដេអូ..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                # -------------------------------------------------
                # 2. Load model
                # -------------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()

                # -------------------------------------------------
                # 3. Transcribe
                # -------------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=1,
                        best_of=1,
                        temperature=0,
                        vad_filter=True,
                        word_timestamps=True,
                        condition_on_previous_text=False,
                    )

                    segments = list(
                        segments
                    )

                # -------------------------------------------------
                # 4. Make timed captions
                # -------------------------------------------------

                captions = make_captions(
                    segments
                )

                if not captions:

                    st.error(
                        "❌ រកមិនឃើញសំឡេងខ្មែរ។"
                    )

                    st.stop()

                # -------------------------------------------------
                # 5. Create ASS
                # -------------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption តាមពេលនិយាយ..."
                ):

                    create_ass(
                        captions,
                        ass_path
                    )

                # -------------------------------------------------
                # 6. Burn caption
                # -------------------------------------------------

                with st.spinner(
                    "🎬 កំពុងបញ្ចូល Caption ទៅក្នុង MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # -------------------------------------------------
                # 7. Read result
                # -------------------------------------------------

                with open(
                    output_path,
                    "rb"
                ) as f:

                    output_data = f.read()

                # -------------------------------------------------
                # 8. Show result
                # -------------------------------------------------

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
                    use_container_width=True,
                )

            except Exception as e:

                st.error(
                    "❌ App មានបញ្ហា"
                )

                st.code(
                    str(e)
)
