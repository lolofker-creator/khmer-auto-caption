import os
import subprocess
import tempfile
import json

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

# =========================================================
# Logo
# =========================================================

col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    st.image(
        "file_00000000568c8211831d7859c11ddf61.png",
        width=300,
    )
st.title("🇰🇭 Smey Auto Caption")
st.write("Gemini → Caption → Auto Translate → MP4")


# =========================================================
# FFmpeg
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
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        audio_path,
    ])


# =========================================================
# Time
# =========================================================

def to_seconds(value):
    if not value:
        return 0.0

    value = str(value).replace("s", "")

    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================================================
# Gemini Word Timestamps
# =========================================================

def get_words(interaction):
    words = []

    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for annotation in getattr(
                content,
                "annotations",
                [],
            ) or []:

                if getattr(
                    annotation,
                    "type",
                    None,
                ) == "word_info":
                    words.append(annotation)

    return words


# =========================================================
# Caption Groups
# =========================================================

def make_groups(
    words,
    max_words=5,
    max_duration=2.0,
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
            getattr(word, "start_offset", "")
        )

        word_end = to_seconds(
            getattr(word, "end_offset", "")
        )

        if start is None:
            start = word_start

        current.append(text)
        last_end = word_end

        if (
            len(current) >= max_words
            or last_end - start >= max_duration
        ):
            groups.append({
                "start": start,
                "end": last_end,
                "text": " ".join(current),
            })

            current = []
            start = None
            last_end = None

    if current and start is not None:
        groups.append({
            "start": start,
            "end": last_end,
            "text": " ".join(current),
        })

    return groups


# =========================================================
# Auto Translate
# =========================================================

def translate_captions(
    client,
    groups,
    source_language,
    target_language,
):
    if not groups or target_language == "មិនបកប្រែ":
        return groups

    source_map = {
        "Auto Detect": "the original language",
        "🇰🇭 ខ្មែរ": "Khmer",
        "🇬🇧 English": "English",
        "🇨🇳 中文": "Chinese",
        "🇻🇳 Tiếng Việt": "Vietnamese",
        "🇰🇷 한국어": "Korean",
        "🇯🇵 日本語": "Japanese",
    }

    target_map = {
        "🇰🇭 ខ្មែរ": "Khmer",
        "🇬🇧 English": "English",
        "🇨🇳 中文": "Chinese",
        "🇻🇳 Tiếng Việt": "Vietnamese",
        "🇰🇷 한국어": "Korean",
        "🇯🇵 日本語": "Japanese",
    }

    source_name = source_map.get(
        source_language,
        "the original language",
    )

    target_name = target_map.get(
        target_language,
        "Khmer",
    )

    texts = [
        group["text"]
        for group in groups
    ]

    prompt = f"""
Translate the following video captions.

Source language:
{source_name}

Target language:
{target_name}

IMPORTANT RULES:
1. Return exactly one translated string for each input caption.
2. Keep the exact same order.
3. Do not add explanations.
4. Do not add numbering.
5. Do not merge captions.
6. Keep names and numbers accurate.
7. Translate naturally for subtitles.
8. Return only a JSON array of strings.

Captions:
"""

    for i, text in enumerate(texts, start=1):
        prompt += f"\n{i}. {text}"

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[str],
        ),
    )

    translated = response.parsed

    if not translated:
        return groups

    if len(translated) != len(groups):
        raise ValueError(
            "Gemini បានបកប្រែចំនួន Caption មិនត្រូវគ្នា។"
        )

    new_groups = []

    for group, translated_text in zip(
        groups,
        translated,
    ):
        new_groups.append({
            "start": group["start"],
            "end": group["end"],
            "text": str(
                translated_text
            ).strip(),
        })

    return new_groups


# =========================================================
# ASS Subtitle
# =========================================================

def create_ass(
    groups,
    filename,
):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,50,50,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(header)

        for group in groups:
            text = group["text"]

            text = text.replace(
                "\n",
                " ",
            )

            text = text.replace(
                "{",
                r"\{",
            )

            text = text.replace(
                "}",
                r"\}",
            )

            f.write(
                f"Dialogue: 0,"
                f"{ass_time(group['start'])},"
                f"{ass_time(group['end'])},"
                f"Khmer,,0,0,0,,"
                f"{text}\n"
            )


def burn_caption(
    video_path,
    ass_path,
    output_path,
):
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


# =========================================================
# Language Settings
# =========================================================

source_language = st.selectbox(
    "🌐 ភាសាដើម",
    [
        "Auto Detect",
        "🇰🇭 ខ្មែរ",
        "🇬🇧 English",
        "🇨🇳 中文",
        "🇻🇳 Tiếng Việt",
        "🇰🇷 한국어",
        "🇯🇵 日本語",
    ],
)

target_language = st.selectbox(
    "🎯 បកប្រែទៅជា",
    [
        "មិនបកប្រែ",
        "🇰🇭 ខ្មែរ",
        "🇬🇧 English",
        "🇨🇳 中文",
        "🇻🇳 Tiếng Việt",
        "🇰🇷 한국어",
        "🇯🇵 日本語",
    ],
)


# =========================================================
# Video Upload
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
# Process
# =========================================================

if video is not None:

    caption_clicked = st.button(
        "⚡ បង្កើត Caption",
        use_container_width=True,
    )

    if caption_clicked:

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
                "khmer_caption.ass",
            )

            output_path = os.path.join(
                temp_dir,
                "smey_auto_caption.mp4",
            )

            with open(
                video_path,
                "wb",
            ) as f:
                f.write(
                    video.getbuffer()
                )

            try:

                # ---------------------------------
                # Extract Audio
                # ---------------------------------

                with st.spinner(
                    "⚡ កំពុងដកសំឡេង..."
                ):
                    extract_audio(
                        video_path,
                        audio_path,
                    )


                # ---------------------------------
                # Gemini Transcription
                # ---------------------------------

                with st.spinner(
                    "🎙️ Gemini កំពុងស្តាប់សំឡេង..."
                ):

                    client = genai.Client(
                        api_key=st.secrets[
                            "GEMINI_API_KEY"
                        ]
                    )

                    audio_file = client.files.upload(
                        file=audio_path,
                    )

                    language_codes = []

                    language_code_map = {
                        "🇰🇭 ខ្មែរ": "km-KH",
                        "🇬🇧 English": "en-US",
                        "🇨🇳 中文": "zh-CN",
                        "🇻🇳 Tiếng Việt": "vi-VN",
                        "🇰🇷 한국어": "ko-KR",
                        "🇯🇵 日本語": "ja-JP",
                    }

                    if source_language != "Auto Detect":
                        language_codes = [
                            language_code_map[
                                source_language
                            ]
                        ]

                    language_hint = (
                        language_codes[0]
                        if language_codes
                        else "detect automatically"
                    )

                    timestamp_prompt = f"""
Transcribe this audio accurately.
Language: {language_hint}

Return ONLY valid JSON: an array of caption segments.

Each segment must have exactly these fields:
- start: number of seconds from the beginning
- end: number of seconds from the beginning
- text: the exact spoken words for that segment

Make short natural caption segments, about 2 seconds each.
Do not translate.
Do not add explanations or markdown.
"""

                    response = client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=[
                            types.Part.from_uri(
                                file_uri=audio_file.uri,
                                mime_type=audio_file.mime_type,
                            ),
                            timestamp_prompt,
                        ],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=list[
                                dict[str, object]
                            ],
                        ),
                    )

                    raw_segments = response.parsed
                    groups = []

                    if isinstance(
                        raw_segments,
                        list,
                    ):
                        for item in raw_segments:

                            if not isinstance(
                                item,
                                dict,
                            ):
                                continue

                            text = str(
                                item.get(
                                    "text",
                                    "",
                                )
                            ).strip()

                            if not text:
                                continue

                            try:
                                start = float(
                                    item.get(
                                        "start",
                                        0,
                                    )
                                )

                                end = float(
                                    item.get(
                                        "end",
                                        start + 2,
                                    )
                                )

                            except (
                                TypeError,
                                ValueError,
                            ):
                                continue

                            if end <= start:
                                end = start + 2

                            groups.append({
                                "start": start,
                                "end": end,
                                "text": text,
                            })

                    if not groups:
                        st.error(
                            "❌ Gemini មិនបានរកឃើញ Caption timestamps ទេ។"
                        )
                        st.stop()


                # ---------------------------------
                # Auto Translate
                # ---------------------------------

                if target_language != "មិនបកប្រែ":

                    with st.spinner(
                        "🌐 Gemini កំពុងបកប្រែ Caption..."
                    ):

                        groups = translate_captions(
                            client,
                            groups,
                            source_language,
                            target_language,
                        )


                # ---------------------------------
                # Create Caption
                # ---------------------------------

                create_ass(
                    groups,
                    ass_path,
                )

                with st.spinner(
                    "🎬 កំពុងដាក់ Caption ជាប់ក្នុងវីដេអូ..."
                ):

                    burn_caption(
                        video_path,
                        ass_path,
                        output_path,
                    )


                # ---------------------------------
                # Output
                # ---------------------------------

                with open(
                    output_path,
                    "rb",
                ) as f:
                    output_data = f.read()

                st.success(
                    "✅ វីដេអូរួចរាល់!"
                )

                st.video(
                    output_data
                )

                st.download_button(
                    "⬇️ ទាញយកវីដេអូ MP4",
                    data=output_data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                    on_click="ignore",
                )


            except Exception as e:

                st.error(
                    "❌ មានបញ្ហាពេលបង្កើតវីដេអូ"
                )

                st.exception(e)
