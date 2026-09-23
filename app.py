import os
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
        stdout=subprocess.PIPE,
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
# KHMER MODEL
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
# TIME
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
# TEXT
# =========================================================

def clean_text(text):

    return " ".join(
        str(text)
        .replace("\n", " ")
        .replace("\r", " ")
        .split()
    ).strip()


# =========================================================
# MAKE CAPTIONS
# =========================================================

def make_captions(segments):

    captions = []

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
            end = start + 0.4

        captions.append({
            "start": start,
            "end": end,
            "text": text
        })

    return captions


# =========================================================
# ASS
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

            file.write(
                "Dialogue: 0,"
                + ass_time(item["start"])
                + ","
                + ass_time(item["end"])
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


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
        output_path
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

            # Save video
            with open(
                video_path,
                "wb"
            ) as file:

                file.write(
                    video.getbuffer()
                )

            try:

                # ---------------------------------------------
                # 1. Audio
                # ---------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                # ---------------------------------------------
                # 2. Model
                # ---------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()

                # ---------------------------------------------
                # 3. Speech to Khmer
                # ---------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេង និងសរសេរខ្មែរ..."
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
                        condition_on_previous_text=True
                    )

                    segments = list(
                        segments
                    )

                # ---------------------------------------------
                # 4. Captions
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
                # 5. ASS
                # ---------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption តាមពេលនិយាយ..."
                ):

                    create_ass(
                        captions,
                        ass_path
                    )

                # ---------------------------------------------
                # 6. Burn
                # ---------------------------------------------

                with st.spinner(
                    "🎬 កំពុងបញ្ចូល Caption ទៅ MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                # ---------------------------------------------
                # 7. Output
                # ---------------------------------------------

                with open(
                    output_path,
                    "rb"
                ) as file:

                    output_data = file.read()

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
