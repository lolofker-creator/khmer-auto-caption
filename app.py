import streamlit as st
import subprocess
import tempfile
import os
from transformers import pipeline

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭"
)

st.title("🇰🇭 Smey Auto Caption")
st.write("បញ្ចូលវីដេអូ → ស្គាល់សំឡេងខ្មែរ → Caption តាមការនិយាយ")


@st.cache_resource
def load_model():
    return pipeline(
        "automatic-speech-recognition",
        model="1morecupofhottea/whisper-turbo-khmer-v9",
        chunk_length_s=30,
        device=-1
    )


def ass_time(seconds):
    if seconds is None:
        seconds = 0

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60

    return f"{h}:{m:02d}:{s:05.2f}"


def make_groups(chunks):
    groups = []

    for chunk in chunks:
        timestamp = chunk.get("timestamp")
        text = chunk.get("text", "").strip()

        if not timestamp or not text:
            continue

        start, end = timestamp

        if start is None or end is None:
            continue

        parts = [
            x.strip()
            for x in text.split(";")
            if x.strip()
        ]

        if not parts:
            continue

        duration = end - start

        if len(parts) == 1:
            groups.append(
                (start, end, parts[0])
            )
            continue

        step = duration / len(parts)

        for i, part in enumerate(parts):
            part_start = start + (i * step)
            part_end = start + ((i + 1) * step)

            groups.append(
                (part_start, part_end, part)
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

            text = text.strip()

            if not text:
                continue

            text = text.replace("\n", " ")
            text = text.replace("{", r"\{")
            text = text.replace("}", r"\}")

            f.write(
                "Dialogue: 0,"
                + ass_time(start)
                + ","
                + ass_time(end)
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"]
)


if video:

    st.video(video)

    if st.button(
        "🚀 បង្កើត Caption ខ្មែរ",
        use_container_width=True
    ):

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

            # Save video
            with open(input_file, "wb") as f:
                f.write(video.getbuffer())

            # Extract audio from video
            with st.spinner("🔊 កំពុងដកសំឡេងពីវីដេអូ..."):

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

            # Speech recognition
            with st.spinner("🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."):

                model = load_model()

                result = model(
                    audio_file,
                    return_timestamps=True
                )

            chunks = result.get(
                "chunks",
                []
            )

            groups = make_groups(chunks)

            if not groups:
                st.error(
                    "❌ AI មិនអាចរកពេលវេលាសំឡេងបានទេ។"
                )
                st.stop()

            # Create subtitles
            create_ass(
                groups,
                ass_file
            )

            # Burn subtitles into video
            with st.spinner("🎬 កំពុងដាក់ Caption..."):

                subprocess
