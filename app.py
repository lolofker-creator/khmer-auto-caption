import os
import subprocess
import tempfile

import streamlit as st
from faster_whisper import WhisperModel


st.set_page_config(
    page_title="Smey Auto Caption FAST",
    page_icon="🎬",
)

st.title("🇰🇭 Smey Auto Caption FAST")
st.write("វីដេអូ → Caption ខ្មែរ លឿន")


@st.cache_resource(show_spinner=False)
def load_model():
    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
    )


def extract_audio(video_path, audio_path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            audio_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def create_ass(segments, filename):
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

        for seg in segments:
            text = seg.text.strip()

            if not text:
                continue

            text = text.replace("\n", " ")
            text = text.replace("{", r"\{")
            text = text.replace("}", r"\}")

            f.write(
                f"Dialogue: 0,"
                f"{ass_time(seg.start)},"
                f"{ass_time(seg.end)},"
                f"Khmer,,0,0,0,,"
                f"{text}\n"
            )


video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)

if video is not None:

    if st.button("⚡ បង្កើត Caption លឿន", use_container_width=True):

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

            with open(video_path, "wb") as f:
                f.write(video.getbuffer())

            with st.spinner("⚡ AI កំពុងស្តាប់..."):

                extract_audio(
                    video_path,
                    audio_path
                )

                model = load_model()

                segments, info = model.transcribe(
                    audio_path,
                    language="km",
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    word_timestamps=False,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )

                segments = list(segments)

                create_ass(
                    segments,
                    ass_path
                )

            with open(
                ass_path,
                "rb"
            ) as f:
                caption_data = f.read()

        st.success("✅ រួចរាល់!")

        st.download_button(
            "⬇️ ទាញយក Caption",
            data=caption_data,
            file_name="khmer_caption.ass",
            mime="text/plain",
            use_container_width=True,
        )
