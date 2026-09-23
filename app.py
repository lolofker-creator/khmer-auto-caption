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
st.write("🎙️ សំឡេងខ្មែរ → Caption តាមពេលនិយាយ")
st.info("🆓 Free — មិនប្រើ Gemini")


# =========================================================
# FFMPEG
# =========================================================

def ffmpeg(args):
    exe = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [exe] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True
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
# WHISPER
# =========================================================

@st.cache_resource
def get_model():
    return WhisperModel(
        "PhanithLIM/whisper-tiny-khmer-ct2",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        num_workers=1
    )


# =========================================================
# CLEAN
# =========================================================

def clean(text):
    text = str(text)
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =========================================================
# ASS TIME
# =========================================================

def ass_time(t):
    t = max(0.0, float(t))

    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int((t - int(t)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# IMPORTANT
#
# ពាក្យនីមួយៗ = Caption នីមួយៗ
#
# មិនកាត់ 0.9 វិនាទី
# មិនយក segment ទាំងមូល
# =========================================================

def make_word_captions(segments):

    result = []

    for segment in segments:

        words = getattr(
            segment,
            "words",
            None
        )

        if not words:
            continue

        for word in words:

            text = clean(
                getattr(
                    word,
                    "word",
                    ""
                )
            )

            start = getattr(
                word,
                "start",
                None
            )

            end = getattr(
                word,
                "end",
                None
            )

            if not text:
                continue

            if start is None or end is None:
                continue

            start = float(start)
            end = float(end)

            if end <= start:
                end = start + 0.15

            result.append({
                "start": start,
                "end": end,
                "text": text
            })

    result.sort(
        key=lambda x: x["start"]
    )

    return result


# =========================================================
# CREATE ASS
#
# ពាក្យមួយចេញតាមពេលរបស់វា
# =========================================================

def create_ass(words, path):

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,45,45,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(header)

        for item in words:

            text = clean(
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

            start = ass_time(
                item["start"]
            )

            end = ass_time(
                item["end"]
            )

            line = (
                "Dialogue: 0,"
                + start
                + ","
                + end
                + ",Khmer,,0,0,0,,"
                + text
                + "\n"
            )

            f.write(line)


# =========================================================
# BURN CAPTION
# =========================================================

def burn_caption(
    video,
    ass,
    output
):

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


# =========================================================
# PROCESS
# =========================================================

if video:

    st.video(video)

    if st.button(
        "⚡ បង្កើត Caption",
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
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):
                    model = get_model()

                # 3
                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេង..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=1,
                        best_of=1,
                        temperature=0,
                        vad_filter=True,
                        word_timestamps=True,
                        condition_on_previous_text=False
                    )

                    segments = list(
                        segments
                    )

                # 4
                # ពាក្យនីមួយៗមាន timing ផ្ទាល់ខ្លួន
                with st.spinner(
                    "⏱️ កំពុងកំណត់ពេលពាក្យនីមួយៗ..."
                ):

                    word_captions = (
                        make_word_captions(
                            segments
                        )
                    )

                if not word_captions:

                    st.error(
                        "❌ រកមិនឃើញ Caption"
                    )

                    st.stop()

                # 5
                with st.spinner(
                    "📝 កំពុងបង្កើត Caption តាមសំឡេង..."
                ):

                    create_ass(
                        word_captions,
                        ass_path
                    )

                # 6
                with st.spinner(
                    "🎬 កំពុងបញ្ចូល Caption ទៅវីដេអូ..."
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
