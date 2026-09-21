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
st.write("បញ្ចូលវីដេអូ → បង្កើត Caption ខ្មែរ ស្វ័យប្រវត្តិ")

@st.cache_resource
def load_model():
    return WhisperModel("PhanithLIM/whisper-small-khmer-ct2", device="cpu", compute_type="int8")

def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

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
            text = text.replace("\n", " ")
            text = text.replace("{", r"\{").replace("}", r"\}")
            
            f.write(
                f"Dialogue: 0,{ass_time(seg.start)},"
                f"{ass_time(seg.end)},Khmer,,0,0,0,,{text}\n"
            )

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"]
)

if video:
    st.video(video)

    if st.button("🚀 បង្កើត Caption ខ្មែរ", use_container_width=True):

        with tempfile.TemporaryDirectory() as folder:

            input_file = os.path.join(folder, "input.mp4")
            ass_file = os.path.join(folder, "caption.ass")
            output_file = os.path.join(folder, "output.mp4")

            with open(input_file, "wb") as f:
                f.write(video.getbuffer())

            with st.spinner("🎙️ កំពុងស្តាប់ និងបម្លែងសំឡេងជាអក្សរខ្មែរ..."):

                model = load_model()

                segments, info = model.transcribe(
                    input_file,
                    language="km",
                    beam_size=5,
                    vad_filter=True
                )

                segments = list(segments)

            create_ass(segments, ass_file)

            with st.spinner("🎬 កំពុងដាក់ Caption លើវីដេអូ..."):

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
                    "⬇️ ទាញយកវីដេអូមាន Caption",
                    f,
                    file_name="khmer_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )
