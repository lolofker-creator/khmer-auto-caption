import os
import subprocess
import tempfile

import streamlit as st
import imageio_ffmpeg
from faster_whisper import WhisperModel


# =========================================================
# APP
# =========================================================

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)


# =========================================================
# LOGO
# =========================================================

LOGO_FILE = "file_00000000568c8211831d7859c11ddf61.png"

if os.path.exists(LOGO_FILE):
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.image(
            LOGO_FILE,
            width=300,
        )


st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ Khmer Speech → Caption → MP4")
st.info("🆓 Version Free — មិនប្រើ Gemini API")


# =========================================================
# FFMPEG
# =========================================================

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


# =========================================================
# KHMER WHISPER
# =========================================================

@st.cache_resource
def load_model():

    model = WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
    )

    return model


# =========================================================
# ASS TIME
# =========================================================

def ass_time(seconds):

    h = int(seconds // 3600)

    m = int(
        (seconds % 3600) // 60
    )

    s = int(
        seconds % 60
    )

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# CLEAN KHMER TEXT
# =========================================================

def clean_text(text):

    text = str(text)

    text = text.replace(
        "\n",
        " ",
    )

    text = text.replace(
        "\r",
        " ",
    )

    text = text.strip()

    # Whisper word tokens sometimes contain
    # spaces around Khmer words.
    text = " ".join(
        text.split()
    )

    return text


# =========================================================
# MAKE SHORT CAPTIONS
# =========================================================

def make_short_captions(segments):

    captions = []

    for segment in segments:

        words = getattr(
            segment,
            "words",
            None,
        )

        if not words:
            continue

        current_words = []

        chunk_start = None
        last_end = None

        for word in words:

            word_text = str(
                getattr(
                    word,
                    "word",
                    "",
                )
            ).strip()

            if not word_text:
                continue

            word_start = float(
                getattr(
                    word,
                    "start",
                    0,
                )
            )

            word_end = float(
                getattr(
                    word,
                    "end",
                    word_start,
                )
            )

            if chunk_start is None:
                chunk_start = word_start

            current_words.append(
                word_text
            )

            last_end = word_end

            duration = (
                last_end - chunk_start
            )

            # Caption changes approximately
            # every 1.8 seconds.
            if duration >= 1.8:

                text = clean_text(
                    " ".join(
                        current_words
                    )
                )

                if text:

                    captions.append({
                        "start": chunk_start,
                        "end": last_end,
                        "text": text,
                    })

                current_words = []
                chunk_start = None

        # Remaining words
        if (
            current_words
            and chunk_start is not None
            and last_end is not None
        ):

            text = clean_text(
                " ".join(
                    current_words
                )
            )

            if text:

                captions.append({
                    "start": chunk_start,
                    "end": last_end,
                    "text": text,
                })

    return captions


# =========================================================
# CREATE ASS
# =========================================================

def create_ass(captions, filename):

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

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(header)

        for caption in captions:

            text = clean_text(
                caption["text"]
            )

            text = text.replace(
                "{",
                r"\{",
            )

            text = text.replace(
                "}",
                r"\}",
            )

            start = ass_time(
                caption["start"]
            )

            end = ass_time(
                caption["end"]
            )

            f.write(
                f"Dialogue: 0,"
                f"{start},"
                f"{end},"
                f"Khmer,,0,0,0,,"
                f"{text}\n"
            )


# =========================================================
# BURN CAPTION INTO VIDEO
# =========================================================

def burn_caption(
    video_path,
    ass_path,
    output_path,
):

    escaped_ass = (
        ass_path
        .replace(
            "\\",
            "/",
        )
        .replace(
            ":",
            r"\:",
        )
        .replace(
            "'",
            r"\'",
        )
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


# =========================================================
# VIDEO UPLOAD
# =========================================================

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm",
    ],
)


# =========================================================
# PROCESS VIDEO
# =========================================================

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

            # -------------------------------------------------
            # SAVE VIDEO
            # -------------------------------------------------

            with open(
                video_path,
                "wb",
            ) as f:

                f.write(
                    video.getbuffer()
                )

            try:

                # -------------------------------------------------
                # EXTRACT AUDIO
                # -------------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេងពីវីដេអូ..."
                ):

                    extract_audio(
                        video_path,
                        audio_path,
                    )


                # -------------------------------------------------
                # LOAD KHMER MODEL
                # -------------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()


                # -------------------------------------------------
                # TRANSCRIBE
                # -------------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=5,
                        vad_filter=True,
                        word_timestamps=True,
                    )

                    segments = list(
                        segments
                    )


                # -------------------------------------------------
                # CHECK AUDIO
                # -------------------------------------------------

                if not segments:

                    st.error(
                        "❌ រកមិនឃើញសំឡេងសម្រាប់បង្កើត Caption ទេ។"
                    )

                    st.stop()


                # -------------------------------------------------
                # MAKE SHORT CAPTIONS
                # -------------------------------------------------

                with st.spinner(
                    "📝 កំពុងបែង Caption តាមការនិយាយ..."
                ):

                    captions = make_short_captions(
                        segments
                    )


                if not captions:

                    st.error(
                        "❌ មិនអាចបែង Caption បានទេ។"
                    )

                    st.stop()


                # -------------------------------------------------
                # CREATE ASS
                # -------------------------------------------------

                with st.spinner(
                    "📝 កំពុងរៀបចំអក្សរ Caption..."
                ):

                    create_ass(
                        captions,
                        ass_path,
                    )


                # -------------------------------------------------
                # BURN CAPTION
                # -------------------------------------------------

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ចូលក្នុង MP4..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path,
                    )


                # -------------------------------------------------
                # READ OUTPUT
                # -------------------------------------------------

                with open(
                    output_path,
                    "rb",
                ) as f:

                    output_data = f.read()


                # -------------------------------------------------
                # RESULT
                # -------------------------------------------------

                st.success(
                    "✅ វីដេអូរួចរាល់!"
                )

                st.video(
                    output_data
                )


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
