import os
import re
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
        st.image(LOGO_FILE, width=300)


st.title("🇰🇭 Smey Auto Caption")
st.write("🎙️ Khmer Speech → Caption → MP4")
st.info("🆓 Free Version — មិនប្រើ Gemini API")


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
# WHISPER KHMER
# =========================================================

@st.cache_resource
def load_model():

    return WhisperModel(
        "PhanithLIM/whisper-small-khmer-ct2",
        device="cpu",
        compute_type="int8",
    )


# =========================================================
# ASS TIME
# =========================================================

def ass_time(seconds):

    seconds = max(0, float(seconds))

    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# CLEAN TEXT
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

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# =========================================================
# SPLIT TEXT
# =========================================================

def split_text(text):

    text = clean_text(text)

    if not text:
        return []

    # Keep Khmer / Latin / numbers together when separated
    # by normal spaces.
    parts = text.split()

    if len(parts) > 1:
        return parts

    # If Whisper returns one long Khmer string without spaces,
    # split it into small groups of characters.
    chars = list(text)

    groups = []

    current = ""

    for char in chars:

        current += char

        if len(current) >= 6:

            groups.append(
                current.strip()
            )

            current = ""

    if current.strip():
        groups.append(
            current.strip()
        )

    return groups


# =========================================================
# MAKE TIMED CAPTIONS
# =========================================================

def make_timed_captions(segments):

    captions = []

    for segment in segments:

        seg_start = float(
            getattr(
                segment,
                "start",
                0,
            )
        )

        seg_end = float(
            getattr(
                segment,
                "end",
                seg_start + 2,
            )
        )

        if seg_end <= seg_start:
            seg_end = seg_start + 1

        words = getattr(
            segment,
            "words",
            None,
        )

        # -------------------------------------------------
        # METHOD 1
        # Real Whisper word timestamps
        # -------------------------------------------------

        if words:

            current = []
            current_start = None
            current_end = None

            for word in words:

                word_text = clean_text(
                    getattr(
                        word,
                        "word",
                        "",
                    )
                )

                if not word_text:
                    continue

                word_start = getattr(
                    word,
                    "start",
                    None,
                )

                word_end = getattr(
                    word,
                    "end",
                    None,
                )

                if (
                    word_start is None
                    or word_end is None
                ):
                    continue

                word_start = float(
                    word_start
                )

                word_end = float(
                    word_end
                )

                if current_start is None:
                    current_start = word_start

                current.append(
                    word_text
                )

                current_end = word_end

                duration = (
                    current_end
                    - current_start
                )

                # Caption changes every
                # approximately 1.2 seconds.
                if duration >= 1.2:

                    text = clean_text(
                        " ".join(current)
                    )

                    if text:

                        captions.append({
                            "start": current_start,
                            "end": current_end,
                            "text": text,
                        })

                    current = []
                    current_start = None
                    current_end = None

            # Remaining words
            if (
                current
                and current_start is not None
                and current_end is not None
            ):

                text = clean_text(
                    " ".join(current)
                )

                if text:

                    captions.append({
                        "start": current_start,
                        "end": current_end,
                        "text": text,
                    })

            continue

        # -------------------------------------------------
        # METHOD 2
        # Fallback if word timestamps unavailable
        # -------------------------------------------------

        text = clean_text(
            getattr(
                segment,
                "text",
                "",
            )
        )

        parts = split_text(text)

        if not parts:
            continue

        total_duration = (
            seg_end - seg_start
        )

        # Approximately 1.2 seconds
        # per caption.
        number_of_parts = max(
            1,
            len(parts),
        )

        duration_per_part = (
            total_duration
            / number_of_parts
        )

        for index, part in enumerate(parts):

            start = (
                seg_start
                + index * duration_per_part
            )

            end = (
                seg_start
                + (index + 1)
                * duration_per_part
            )

            captions.append({
                "start": start,
                "end": end,
                "text": part,
            })

    # -----------------------------------------------------
    # Remove overlaps
    # -----------------------------------------------------

    captions.sort(
        key=lambda x: x["start"]
    )

    fixed = []

    for caption in captions:

        start = float(
            caption["start"]
        )

        end = float(
            caption["end"]
        )

        text = clean_text(
            caption["text"]
        )

        if not text:
            continue

        if fixed:

            previous_end = float(
                fixed[-1]["end"]
            )

            if start < previous_end:
                start = previous_end

        if end <= start:
            end = start + 0.4

        fixed.append({
            "start": start,
            "end": end,
            "text": text,
        })

    return fixed


# =========================================================
# CREATE ASS
# =========================================================

def create_ass(
    captions,
    filename,
):

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
                "Dialogue: 0,"
                f"{start},"
                f"{end},"
                "Khmer,,0,0,0,,"
                f"{text}\n"
            )


# =========================================================
# BURN CAPTION
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
# UPLOAD VIDEO
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
# PROCESS
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
                # AUDIO
                # -------------------------------------------------

                with st.spinner(
                    "🎵 កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path,
                    )


                # -------------------------------------------------
                # MODEL
                # -------------------------------------------------

                with st.spinner(
                    "🧠 កំពុងបើក Khmer Whisper..."
                ):

                    model = load_model()


                # -------------------------------------------------
                # TRANSCRIPTION
                # -------------------------------------------------

                with st.spinner(
                    "🎙️ កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    segments, info = model.transcribe(
                        audio_path,
                        language="km",
                        beam_size=5,
                        best_of=5,
                        vad_filter=True,
                        word_timestamps=True,
                        condition_on_previous_text=False,
                    )

                    segments = list(
                        segments
                    )


                if not segments:

                    st.error(
                        "❌ មិនរកឃើញសំឡេងទេ។"
                    )

                    st.stop()


                # -------------------------------------------------
                # TIMED CAPTIONS
                # -------------------------------------------------

                with st.spinner(
                    "📝 កំពុងបែងអក្សរតាមពេលនិយាយ..."
                ):

                    captions = make_timed_captions(
                        segments
                    )


                if not captions:

                    st.error(
                        "❌ មិនអាចបង្កើត Timing Caption បានទេ។"
                    )

                    st.stop()


                # -------------------------------------------------
                # ASS
                # -------------------------------------------------

                create_ass(
                    captions,
                    ass_path,
                )


                # -------------------------------------------------
                # VIDEO
                # -------------------------------------------------

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ចូលវីដេអូ..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path,
                    )


                # -------------------------------------------------
                # RESULT
                # -------------------------------------------------

                with open(
                    output_path,
                    "rb",
                ) as f:

                    output_data = f.read()


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
                    use_container_width=True,
                )


            except Exception as e:

                st.error(
                    "❌ មានបញ្ហាពេលបង្កើត Caption"
                )

                st.exception(e)
