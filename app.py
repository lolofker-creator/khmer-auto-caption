import os
import subprocess
import tempfile
import base64

import streamlit as st
from google import genai
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

st.title("🇰🇭 Smey Auto Caption")
st.write("Gemini → Khmer Caption → MP4")


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
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        audio_path,
    ])


def to_seconds(value):
    if not value:
        return 0.0

    value = str(value).replace("s", "")

    try:
        return float(value)
    except ValueError:
        return 0.0


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_words(interaction):
    words = []

    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for annotation in getattr(
                content,
                "annotations",
                []
            ) or []:

                if getattr(
                    annotation,
                    "type",
                    None
                ) == "word_info":

                    words.append(annotation)

    return words


def make_groups(
    words,
    max_words=5,
    max_duration=2.0
):
    groups = []

    current = []
    start = None
    last_end = None

    for word in words:

        text = (
            getattr(word, "text", "")
            or ""
        ).strip()

        if not text:
            continue

        word_start = to_seconds(
            getattr(
                word,
                "start_offset",
                ""
            )
        )

        word_end = to_seconds(
            getattr(
                word,
                "end_offset",
                ""
            )
        )

        if start is None:
            start = word_start

        current.append(text)
        last_end = word_end

        if (
            len(current) >= max_words
            or last_end - start >= max_duration
        ):

            groups.append(
                (
                    start,
                    last_end,
                    " ".join(current),
                )
            )

            current = []
            start = None
            last_end = None

    if current and start is not None:
        groups.append(
            (
                start,
                last_end,
                " ".join(current),
            )
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

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(header)

        for start, end, text in groups:

            text = text.replace(
                "\n",
                " "
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
                f"Dialogue: 0,"
                f"{ass_time(start)},"
                f"{ass_time(end)},"
                f"Khmer,,0,0,0,,"
                f"{text}\n"
            )


def burn_caption(
    video_path,
    ass_path,
    output_path
):

    escaped_ass = (
        ass_path
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    run_ffmpeg([
        "-y",
        "-i", video_path,
        "-vf", f"ass='{escaped_ass}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ])


def show_download_link(video_data):

    encoded = base64.b64encode(
        video_data
    ).decode("utf-8")

    html = f"""
    <div style="text-align:center; margin-top:15px;">
        <a
            href="data:video/mp4;base64,{encoded}"
            download="smey_auto_caption.mp4"
            style="
                display:inline-block;
                padding:14px 24px;
                background:#ff4b4b;
                color:white;
                text-decoration:none;
                border-radius:10px;
                font-size:18px;
                font-weight:bold;
            "
        >
            ⬇️ ទាញយកវីដេអូ MP4
        </a>
    </div>
    """

    st.html(html)


video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm"
    ],
)


if video is not None:

    if st.button(
        "⚡ Gemini បង្កើត Caption",
        use_container_width=True
    ):

        with tempfile.TemporaryDirectory() as temp_dir:

            video_path = os.path.join(
                temp_dir,
                "input.mp4"
            )

            audio_path = os.path.join(
                temp_dir,
                "audio.wav"
            )

            ass_path = os.path.join(
                temp_dir,
                "khmer_caption.ass"
            )

            output_path = os.path.join(
                temp_dir,
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
                    "⚡ កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )

                with st.spinner(
                    "🇰🇭 Gemini កំពុងស្តាប់សំឡេងខ្មែរ..."
                ):

                    client = genai.Client(
                        api_key=st.secrets[
                            "GEMINI_API_KEY"
                        ]
                    )

                    audio_file = client.files.upload(
                        file=audio_path
                    )

                    interaction = client.interactions.create(
                        model="gemini-3.5-transcribe",
                        input=[
                            {
                                "type": "audio",
                                "uri": audio_file.uri,
                                "mime_type": audio_file.mime_type,
                            }
                        ],
                        generation_config={
                            "transcription_config": {
                                "language_codes": [
                                    "km-KH"
                                ],
                                "mode": {
                                    "type": "verbatim",
                                    "timestamp_granularities": [
                                        "word"
                                    ],
                                },
                            }
                        },
                    )

                    words = get_words(
                        interaction
                    )

                    groups = make_groups(
                        words,
                        max_words=5,
                        max_duration=2.0,
                    )

                    if not groups:
                        st.error(
                            "❌ Gemini មិនបានរកឃើញ timestamps សម្រាប់ Caption ទេ។"
                        )
                        st.stop()

                    create_ass(
                        groups,
                        ass_path
                    )

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ជាប់ក្នុងវីដេអូ..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path
                    )

                with open(
                    output_path,
                    "rb"
                ) as f:
                    output_data = f.read()

                st.success(
                    "✅ វីដេអូមាន Caption រួចរាល់!"
                )

                st.video(
                    output_data
                )

                show_download_link(
                    output_data
                )

            except Exception as e:

                st.error(
                    "❌ មានបញ្ហាពេលបង្កើត Caption"
                )

                st.exception(e)
