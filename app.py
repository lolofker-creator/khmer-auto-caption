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
st.write("🎙️ Khmer Speech → Caption → MP4")
st.info("🆓 Free")


# =========================================================
# FFMPEG
# =========================================================

def ffmpeg(args):
    exe = imageio_ffmpeg.get_ffmpeg_exe()

    p = subprocess.run(
        [exe] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False
    )

    if p.returncode != 0:
        raise RuntimeError(
            p.stderr.decode(
                "utf-8",
                errors="ignore"
            )
        )


def extract_audio(video, audio):
    ffmpeg([
        "-y",
        "-i", video,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        audio
    ])


# =========================================================
# KHMER MODEL
# =========================================================

@st.cache_resource
def load_model():

    return WhisperModel(
        "seanghay/whisper-small-khmer-v2",
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1
    )


# =========================================================
# TIME
# =========================================================

def ass_time(t):

    t = max(0.0, float(t))

    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int((t - int(t)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# TEXT
# =========================================================

def clean(text):

    return " ".join(
        str(text)
        .replace("\n", " ")
        .replace("\r", " ")
        .split()
    ).strip()


# =========================================================
# MAKE CAPTIONS
#
# យក SEGMENT របស់ WHISPER
# មិនយកពាក្យមួយៗ
# =========================================================

def make_captions(segments):

    captions = []

    for seg in segments:

        text = clean(
            getattr(
                seg,
                "text",
                ""
            )
        )

        if not text:
            continue

        start = float(
            getattr(
                seg,
                "start",
                0
            )
        )

        end = float(
            getattr(
                seg,
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
# ASS
# =========================================================

def create_ass(captions, path):

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

        for c in captions:

            text = c["text"]

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
                + ass_time(c["start"])
                + ","
                + ass_time(c["end"])
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )


# =========================================================
# BURN
# =========================================================

def burn(video, ass, output):

    ass_filter = (
        ass
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    ffmpeg([
        "-y",
        "-i", video,
        "-vf",
        f"ass='{ass_filter}'",
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


if video:

    st.video(video)

    if st.button(
        "⚡ បង្កើត Caption ខ្មែរ",
        use_container_width=True
    ):

        with tempfile.TemporaryDirectory() as d:

            video_path = os.path.join(
                d,
                "input.mp4"
            )

            audio_path = os.path.join(
                d,
                "audio.wav"
            )

            ass_path = os.path.join(
                d,
                "caption.ass"
            )

            output_path = os.path.join(
                d,
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

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):
                    extract_audio(
                        video_path,
                        audio_path
                    )

                with st.spinner(
                    "🧠 កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    model = load_model()

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
                        condition_on_previous_text=True,
                        no_speech_threshold=0.6
                    )

                    segments = list(
                        segments
                    )

                captions = make_captions(
                    segments
                )

                if not captions:
                    st.error(
                        "❌ រកមិនឃើញសំឡេងទេ"
                    )
                    st.stop()

                with st.spinner(
                    "📝 កំពុងរៀបចំ Caption តាមការនិយាយ..."
                ):

                    create_ass(
                        captions,
                        ass_path
                    )

                with st.spinner(
                    "🎬 កំពុងបង្កើត MP4..."
                ):

                    burn(
                        video_path,
                        ass_path,
                        output_path
                    )

                with open(
                    output_path,
                    "rb"
                ) as f:
                    data = f.read()

                st.success(
                    "✅ រួចរាល់"
                )

                st.video(data)

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
