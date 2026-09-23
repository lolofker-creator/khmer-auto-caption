import os
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg
from faster_whisper import WhisperModel


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭"
)

st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ សំឡេងខ្មែរ → Caption ខ្មែរ → MP4")
st.info("🆓 Free — មិនប្រើ Gemini API")


# =========================================================
# FFMPEG
# =========================================================

def run_ffmpeg(args):
    exe = imageio_ffmpeg.get_ffmpeg_exe()

    result = subprocess.run(
        [exe] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False
    )

    if result.returncode != 0:
        error = result.stderr.decode(
            "utf-8",
            errors="ignore"
        )
        raise RuntimeError(error)


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
        audio_path
    ])


# =========================================================
# KHMER FASTER-WHISPER
# =========================================================

@st.cache_resource
def load_model():

    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        num_workers=1
    )


# =========================================================
# TEXT
# =========================================================

def clean_text(text):

    text = str(text)

    text = text.replace(
        "\n",
        " "
    )

    text = text.replace(
        "\r",
        " "
    )

    return " ".join(
        text.split()
    ).strip()


# =========================================================
# ASS TIME
# =========================================================

def ass_time(seconds):

    seconds = max(
        0.0,
        float(seconds)
    )

    hours = int(
        seconds // 3600
    )

    minutes = int(
        (seconds % 3600) // 60
    )

    secs = int(
        seconds % 60
    )

    centiseconds = int(
        (seconds - int(seconds)) * 100
    )

    return (
        f"{hours}:"
        f"{minutes:02d}:"
        f"{secs:02d}."
        f"{centiseconds:02d}"
    )


# =========================================================
# CAPTION
#
# ប្រើ SEGMENT TIMESTAMP
# មិនបង្ហាញអក្សរទាំងអស់តាំងពីដើម
# =========================================================

def make_captions(segments):

    captions = []

    for segment in segments:

        text = clean_text(
            getattr(
                segment,
                "text",
                ""
            )
        )

        if not text:
            continue

        start = float(
            getattr(
                segment,
                "start",
                0.0
            )
        )

        end = float(
            getattr(
                segment,
                "end",
                start + 0.5
            )
        )

        if end <= start:
            end = start + 0.5

        captions.append({
            "start": start,
            "end": end,
            "text": text
        })

    return captions


# =========================================================
# ASS SUBTITLE
# =========================================================

def create_ass(
    captions,
    ass_path
):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,45,45,145,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        ass_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(header)

        for caption in captions:

            text = clean_text(
                caption["text"]
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
                + ass_time(
                    caption["start"]
                )
                + ","
                + ass_time(
                    caption["end"]
                )
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )

            file.write(line)


# =========================================================
# BURN CAPTION
# =========================================================

def burn_caption(
    video_path,
    ass_path,
    output_path
):

    filter_path = (
        ass_path
        .replace(
            "\\",
            "/"
        )
        .replace(
            ":",
            r"\:"
        )
        .replace(
            "'",
            r"\'"
        )
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
        output_path
    ])


# =========================================================
# VIDEO UPLOAD
# =========================================================

uploaded_video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm"
    ]
)


# =========================================================
# PROCESS
# =========================================================

if uploaded_video:

    st.video(
        uploaded_video
    )

    if st.button(
        "⚡ បង្កើត Caption ខ្មែរ",
        use_container_width=True
    ):

        with tempfile.TemporaryDirectory() as folder:

            video_path = os.path.join(
                folder,
                "input.mp4"
            )

            audio_path = os.path.join(
                folder,
                "audio.wav"
            )

            ass_path = os.path.join(
                folder,
                "caption.ass"
            )

            output_path = os.path.join(
                folder,
                "smey_auto_caption.mp4"
            )

            # Save video
            with open(
                video_path,
                "wb"
            ) as file:

                file.write(
                    uploaded_video.getbuffer()
                )

            try:

                # ---------------------------------------------
                # 1. Extract audio
                # ---------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                # ---------------------------------------------
                # 2. Load Khmer model
                # ---------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()

                # ---------------------------------------------
                # 3. Transcribe Khmer
                # ---------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់ និងសរសេរ Caption..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        task="transcribe",
                        beam_size=5,
                        best_of=5,
                        temperature=0,
                        vad_filter=True,
                        vad_parameters={
                            "min_silence_duration_ms": 350
                        },
                        word_timestamps=True,
                        condition_on_previous_text=True
                    )

                    segments = list(
                        segments
                    )

                # ---------------------------------------------
                # 4. Create timed captions
                # ---------------------------------------------

                captions = make_captions(
                    segments
                )

                if not captions:

                    st.error(
                        "❌ រកមិនឃើញសំឡេងខ្មែរ"
                    )

                    st.stop()

                # ---------------------------------------------
                # 5. Create ASS
                # ---------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំ Timing Caption..."
                ):

                    create_ass(
                        captions,
                        ass_path
                    )

                # ---------------------------------------------
                # 6. Burn into video
                # ---------------------------------------------

                with st.spinner(
                    "🎬 កំពុងបង្កើត MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # ---------------------------------------------
                # 7. Read output
                # ---------------------------------------------

                with open(
                    output_path,
                    "rb"
                ) as file:

                    output_data = file.read()

                # ---------------------------------------------
                # 8. Result
                # ---------------------------------------------

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
                    use_container_width=True
                )

            except Exception as error:

                st.error(
                    "❌ App មានបញ្ហា"
                )

                st.code(
                    str(error)
                )
