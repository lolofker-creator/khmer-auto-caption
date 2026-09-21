import streamlit as st
import subprocess
import tempfile
import os
from faster_whisper import WhisperModel

st.set_page_config(
    page_title="Khmer Auto Caption",
    page_icon="🎬"
)

st.title("🇰🇭 Khmer Auto Caption")
st.write("បញ្ចូលវីដេអូ → បង្កើត Caption ខ្មែរ តាមសំឡេង")

@st.cache_resource
def load_model():
    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8"
    )

def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def make_caption_groups(segments, max_words=4, max_duration=1.8):
    groups = []

    for seg in segments:
        words = getattr(seg, "words", None)

        if not words:
            text = seg.text.strip()
            if text:
                groups.append((seg.start, seg.end, text))
            continue

        current = []
        start = None
        last_end = None

        for word in words:
            text = word.word.strip()

            if not text:
                continue

            if start is None:
                start = word.start

            current.append(text)
            last_end = word.end

            duration = last_end - start

            if len(current) >= max_words or duration >= max_duration:
                groups.append(
                    (start, last_end, " ".join(current))
                )
                current = []
                start = None
                last_end = None

        if current and start is not None and last_end is not None:
            groups.append(
                (start, last_end, " ".join(current))
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
            text = text.replace("{", r"\{").replace("}", r"\}")

            f.write(
                f"Dialogue: 0,{ass_time(start)},"
                f"{ass_time(end)},Khmer,,0,0,0,,{text}\n"
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

            input_file = os.path.join(folder, "input.mp4")
            ass_file = os.path.join(folder, "caption.ass")
            output_file = os.path.join(folder, "output.mp4")

            with open(input_file, "wb") as f:
                f.write(video.getbuffer())

            with st.spinner(
                "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
            ):
                model = load_model()

                segments, info = model.transcribe(
                    input_file,
                    language="km",
                    task="transcribe",
                    beam_size=5,
                    vad_filter=True,
                    word_timestamps=True,
                    condition_on_previous_text=False
                )

                segments = list(segments)

            groups = make_caption_groups(
                segments,
                max_words=4,
                max_duration=1.8
            )

            create_ass(groups, ass_file)

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
                        "medium",
                        "-c:a",
                        "aac",
                        output_file
                    ],
                    check=True
                )

            st.success("✅ រួចរាល់!")

            with open(output_file, "rb") as f:
                st.download_button(
                    "⬇️ ទាញយកវីដេអូមាន Caption ខ្មែរ",
                    f,
                    file_name="khmer_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )
