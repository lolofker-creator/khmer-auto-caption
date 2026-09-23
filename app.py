import os
import re
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
st.write("🎙️ សំឡេងខ្មែរ → អក្សរខ្មែរ → MP4")
st.info("🆓 Free")


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


def extract_audio(video, audio):

    run_ffmpeg([
        "-y",
        "-i",
        video,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        audio
    ])


# =========================================================
# KHMER LARGE V3
# =========================================================

@st.cache_resource
def load_model():

    return WhisperModel(
        "Tnaot/whisper-large-v3-khmer-ct2",
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

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# TIME
# =========================================================

def ass_time(seconds):

    seconds = max(
        0.0,
        float(seconds)
    )

    h = int(
        seconds // 3600
    )

    m = int(
        (seconds % 3600) // 60
    )

    s = int(
        seconds % 60
    )

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return (
        f"{h}:"
        f"{m:02d}:"
        f"{s:02d}."
        f"{cs:02d}"
    )


# =========================================================
# CAPTION
# =========================================================

def make_captions(segments):

    result = []

    for segment in segments:

        text = clean_text(
            segment.text
        )

        if not text:
            continue

        start = float(
            segment.start
        )

        end = float(
            segment.end
        )

        if end <= start:
            end = start + 0.5

        result.append({
            "start": start,
            "end": end,
            "text": text
        })

    return result


# =========================================================
# ASS
# =========================================================

def create_ass(
    captions,
    path
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
        path,
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

            f.write(
                "Dialogue: 0,"
                + ass_time(item["start"])
                + ","
                + ass_time(item["end"])
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


# =========================================================
# BURN
# =========================================================

def burn_caption(
    video,
    ass,
    output
):

    ass_path = (
        ass
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    run_ffmpeg([
        "-y",
        "-i",
        video,
        "-vf",
        f"ass='{ass_path}'",
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
        output
    ])


# =========================================================
# UPLOAD
# =========================================================

video = st.file_uploader(
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

if video:

    st.video(video)

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

            with open(
                video_path,
                "wb"
            ) as f:

                f.write(
                    video.getbuffer()
                )

            try:

                # 1
                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                # 2
                with st.spinner(
                    "🧠 កំពុងបើក Khmer Large V3..."
                ):

                    model = load_model()

                # 3
                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
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
                            "min_silence_duration_ms": 300
                        },

                        word_timestamps=True,

                        condition_on_previous_text=True,

                        initial_prompt=(
                            "សូមសរសេរសំឡេងនេះ "
                            "ជាអក្សរខ្មែរ។"
                        )
                    )

                    segments = list(
                        segments
                    )

                # 4
                captions = make_captions(
                    segments
                )

                if not captions:

                    st.error(
                        "❌ រកមិនឃើញសំឡេង"
                    )

                    st.stop()

                # 5
                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption..."
                ):

                    create_ass(
                        captions,
                        ass_path
                    )

                # 6
                with st.spinner(
                    "🎬 កំពុងបញ្ចូល Caption..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # 7
                with open(
                    output_path,
                    "rb"
                ) as f:

                    data = f.read()

                st.success(
                    "✅ រួចរាល់"
                )

                st.video(
                    data
                )

                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )

            except Exception as e:

                st.error(
                    "❌ App មានបញ្ហា"
                )

                st.code(
                    str(e)
                )
