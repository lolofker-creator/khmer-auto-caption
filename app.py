import os
import subprocess
import tempfile

import streamlit as st
from faster_whisper import WhisperModel


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🎬",
    layout="centered",
)

st.title("🇰🇭 Smey Auto Caption")
st.write("បញ្ចូលវីដេអូ → Caption ខ្មែរ")


# Load model only once
@st.cache_resource(show_spinner=False)
def load_model():
    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
    )


def extract_audio(video_path, audio_path):
    command = [
        "ffmpeg",
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
    ]

    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((seconds - int(seconds)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_caption_groups(segments, max_words=5, max_duration=2.0):
    groups = []

    for seg in segments:
        words = getattr(seg, "words", None)

        if not words:
            text = seg.text.strip()

            if text:
                groups.append(
                    (seg.start, seg.end, text)
                )

            continue

        current = []
        start = None
        last_end = None

        for word in words:
            text = (word.word or "").strip()

            if not text:
                continue

            if start is None:
                start = word.start

            current.append(text)
            last_end = word.end

            if (
                len(current) >= max_words
                or (last_end - start) >= max_duration
            ):
                groups.append(
                    (
                        start,
                        last_end,
                        " ".join(current),
                    )
                )

                current = []
                start = None
                last_end = None

        if current and start is not None and last_end is not None:
            groups.append(
                (
                    start,
                    last_end,
                    " ".join(current),
                )
            )

    return groups


def create_ass(groups, filename):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,50,50,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(header)

        for start, end, text in groups:

            text = text.replace("\n", " ")
            text = text.replace("{", r"\{")
            text = text.replace("}", r"\}")

            f.write(
                f"Dialogue: 0,"
                f"{ass_time(start)},"
                f"{ass_time(end)},"
                f"Khmer,,0,0,0,,"
                f"{text}\n"
            )


video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)

if video is not None:

    if st.button("🚀 បង្កើត Caption", use_container_width=True):

        model = load_model()

        with tempfile.TemporaryDirectory() as temp_dir:

            video_path = os.path.join(
                temp_dir,
                "input_video.mp4"
            )

            audio_path = os.path.join(
                temp_dir,
                "audio.wav"
            )

            ass_path = os.path.join(
                temp_dir,
                "caption.ass"
            )

            with open(video_path, "wb") as f:
                f.write(video.getbuffer())

            with st.status(
                "កំពុងបង្កើត Caption...",
                expanded=False
            ):

                extract_audio(
                    video_path,
                    audio_path
                )

                segments, info = model.transcribe(
                    audio_path,
                    language="km",
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    word_timestamps=True,
                    vad_filter=True,
                )

                segments = list(segments)

                groups = make_caption_groups(
                    segments,
                    max_words=5,
                    max_duration=2.0,
                )

                create_ass(
                    groups,
                    ass_path
                )

            st.success("✅ Caption រួចរាល់")

            with open(
                ass_path,
                "rb"
            ) as f:

                st.download_button(
                    "⬇️ ទាញយក Caption",
                    data=f,
                    file_name="khmer_caption.ass",
                    mime="text/plain",
                    use_container_width=True,
                )
