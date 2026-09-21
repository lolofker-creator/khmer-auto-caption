import streamlit as st
import subprocess
import tempfile
import os
from transformers import pipeline

st.set_page_config(
    page_title="Khmer Auto Caption",
    page_icon="🎬"
)

st.title("🇰🇭 Smey Auto Caption")
st.write("បញ្ចូលវីដេអូ → ស្តាប់សំឡេងខ្មែរ → បង្កើត Caption ខ្មែរ")


@st.cache_resource
def load_model():
    return pipeline(
        "automatic-speech-recognition",
        model="1morecupofhottea/whisper-turbo-khmer-v9",
        device=-1,
        chunk_length_s=30
    )


def ass_time(seconds):
    if seconds is None:
        seconds = 0

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60

    return f"{h}:{m:02d}:{s:05.2f}"


def make_caption_groups(chunks, max_words=4, max_duration=1.6):
    groups = []

    current_words = []
    start_time = None
    end_time = None

    for chunk in chunks:

        timestamp = chunk.get("timestamp")
        text = chunk.get("text", "").strip()

        if not timestamp or not text:
            continue

        start, end = timestamp

        if start is None or end is None:
            continue

        if start_time is None:
            start_time = start

        current_words.append(text)
        end_time = end

        duration = end_time - start_time

        if (
            len(current_words) >= max_words
            or duration >= max_duration
        ):
            groups.append(
                (
                    start_time,
                    end_time,
                    " ".join(current_words)
                )
            )

            current_words = []
            start_time = None
            end_time = None

    if current_words and start_time is not None and end_time is not None:
        groups.append(
            (
                start_time,
                end_time,
                " ".join(current_words)
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

            text = text.strip()

            if not text:
                continue

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

        with tempfile.TemporaryDirectory() as folder:

            input_file = os.path.join(
                folder,
                "input.mp4"
            )

            ass_file = os.path.join(
                folder,
                "caption.ass"
            )

            output_file = os.path.join(
                folder,
                "output.mp4"
            )

            with open(input_file, "wb") as f:
                f.write(video.getbuffer())

            with st.spinner(
                "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
            ):

                model = load_model()

                result = model(
                    input_file,
                    return_timestamps="word",
                    generate_kwargs={
                        "language": "km",
                        "task": "transcribe"
                    }
                )

            chunks = result.get(
                "chunks",
                []
            )

            caption_groups = make_caption_groups(
                chunks,
                max_words=4,
                max_duration=1.6
            )

            if not caption_groups:

                full_text = result.get(
                    "text",
                    ""
                ).strip()

                if full_text:

                    caption_groups = [
                        (
                            0,
                            10,
                            full_text
                        )
                    ]

            if not caption_groups:

                st.error(
                    "❌ មិនអាចស្គាល់សំឡេងបានទេ។ "
                    "សូមសាកវីដេអូដែលនិយាយខ្មែរច្បាស់។"
                )

                st.stop()

            create_ass(
                caption_groups,
                ass_file
            )

            with st.spinner(
                "🎬 កំពុងដាក់ Caption តាមការនិយាយ..."
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
                        "medium",
                        "-c:a",
                        "aac",
                        output_file
                    ],
                    check=True
                )

            st.success(
                "✅ រួចរាល់!"
            )

            with open(
                output_file,
                "rb"
            ) as f:

                st.download_button(
                    "⬇️ ទាញយកវីដេអូមាន Caption ខ្មែរ",
                    f,
                    file_name="khmer_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True
        )
