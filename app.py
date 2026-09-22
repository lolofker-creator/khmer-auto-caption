import os
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg
from faster_whisper import WhisperModel


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

# =========================
# LOGO
# =========================

LOGO_FILE = "file_00000000568c8211831d7859c11ddf61.png"

if os.path.exists(LOGO_FILE):
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(LOGO_FILE, width=300)


st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ Khmer Speech → Caption → MP4")
st.info("🆓 Version Free — មិនប្រើ Gemini API")


# =========================
# FFMPEG
# =========================

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


# =========================
# WHISPER KHMER
# =========================

@st.cache_resource
def load_model():

    model = WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
    )

    return model


# =========================
# TIME
# =========================

def ass_time(seconds):

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)

    cs = int((seconds - int(seconds)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================
# CREATE ASS
# =========================

def create_ass(segments, filename):

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

    with open(filename, "w", encoding="utf-8") as f:

        f.write(header)

        for segment in segments:

            text = str(segment.text).strip()

            text = text.replace("\n", " ")
            text = text.replace("{", r"\{")
            text = text.replace("}", r"\}")

            start = ass_time(segment.start)
            end = ass_time(segment.end)

            f.write(
                f"Dialogue: 0,{start},{end},Khmer,,0,0,0,,{text}\n"
            )


# =========================
# BURN CAPTION
# =========================

def burn_caption(video_path, ass_path, output_path):

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


# =========================
# VIDEO UPLOAD
# =========================

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)


# =========================
# PROCESS
# =========================

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

            # Save video
            with open(video_path, "wb") as f:
                f.write(video.getbuffer())

            try:

                # -------------------------
                # Extract audio
                # -------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេងពីវីដេអូ..."
                ):

                    extract_audio(
                        video_path,
                        audio_path,
                    )


                # -------------------------
                # Load model
                # -------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()


                # -------------------------
                # Transcribe
                # -------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=5,
                        vad_filter=True,
                    )

                    segments = list(segments)


                if not segments:

                    st.error(
                        "❌ រកមិនឃើញសំឡេងសម្រាប់បង្កើត Caption ទេ។"
                    )

                    st.stop()


                # -------------------------
                # Create ASS
                # -------------------------

                with st.spinner(
                    "📝 កំពុងបង្កើត Caption..."
                ):

                    create_ass(
                        segments,
                        ass_path,
                    )


                # -------------------------
                # Burn Caption
                # -------------------------

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ចូលក្នុង MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path,
                    )


                # -------------------------
                # Result
                # -------------------------

                with open(
                    output_path,
                    "rb",
                ) as f:

                    output_data = f.read()


                st.success(
                    "✅ រួចរាល់!"
                )

                st.video(output_data)

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
