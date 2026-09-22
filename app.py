import os
import base64
import subprocess
import tempfile
import wave
import time

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

st.title("🇰🇭 Smey Auto Caption")
st.write("Gemini → Caption → Auto Translate → AI Dubbing → MP4")


# =========================
# FFmpeg
# =========================

def run_ffmpeg(args):

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [ffmpeg] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def extract_audio(
    video_path,
    audio_path
):

    run_ffmpeg([
        "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        audio_path,
    ])


# =========================
# Time
# =========================

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

    cs = int(
        (seconds - int(seconds)) * 100
    )

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# =========================
# Gemini word timestamps
# =========================

def get_words(interaction):

    words = []

    for step in getattr(
        interaction,
        "steps",
        []
    ) or []:

        for content in getattr(
            step,
            "content",
            []
        ) or []:

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

                    words.append(
                        annotation
                    )

    return words


# =========================
# Caption groups
# =========================

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
            getattr(
                word,
                "text",
                ""
            )
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
            or
            last_end - start >= max_duration
        ):

            groups.append(
                {
                    "start": start,
                    "end": last_end,
                    "text": " ".join(current),
                }
            )

            current = []
            start = None
            last_end = None

    if current and start is not None:

        groups.append(
            {
                "start": start,
                "end": last_end,
                "text": " ".join(current),
            }
        )

    return groups


# =========================
# Auto Translate
# =========================

def translate_captions(
    client,
    groups,
    source_language,
    target_language
):

    if not groups:
        return groups

    if (
        target_language == "មិនបកប្រែ"
    ):
        return groups

    source_map = {

        "Auto Detect":
            "the original language",

        "🇰🇭 ខ្មែរ":
            "Khmer",

        "🇬🇧 English":
            "English",

        "🇨🇳 中文":
            "Chinese",

        "🇻🇳 Tiếng Việt":
            "Vietnamese",

        "🇰🇷 한국어":
            "Korean",

        "🇯🇵 日本語":
            "Japanese",
    }

    target_map = {

        "🇰🇭 ខ្មែរ":
            "Khmer",

        "🇬🇧 English":
            "English",

        "🇨🇳 中文":
            "Chinese",

        "🇻🇳 Tiếng Việt":
            "Vietnamese",

        "🇰🇷 한국어":
            "Korean",

        "🇯🇵 日本語":
            "Japanese",
    }

    source_name = source_map.get(
        source_language,
        "the original language"
    )

    target_name = target_map.get(
        target_language,
        "Khmer"
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

    for i, text in enumerate(
        texts,
        start=1
    ):

        prompt += (
            f"\n{i}. {text}"
        )

    response = client.models.generate_content(
        model="gemini-3.8-flash",
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
        translated
    ):

        new_groups.append(
            {
                "start":
                    group["start"],

                "end":
                    group["end"],

                "text":
                    str(
                        translated_text
                    ).strip(),
            }
        )

    return new_groups


# =========================
# AI Dubbing
# =========================

TTS_VOICES = {

    "Kore — Firm":
        "Kore",

    "Puck — Upbeat":
        "Puck",

    "Charon — Informative":
        "Charon",

    "Fenrir — Excitable":
        "Fenrir",

    "Leda — Youthful":
        "Leda",

    "Aoede — Breezy":
        "Aoede",

    "Iapetus — Clear":
        "Iapetus",

    "Achird — Friendly":
        "Achird",

    "Sulafat — Warm":
        "Sulafat",
}


def tts_prompt(
    text,
    language
):

    language_name = {

        "🇬🇧 English":
            "English",

        "🇨🇳 中文":
            "Chinese Mandarin",

        "🇻🇳 Tiếng Việt":
            "Vietnamese",

        "🇰🇷 한국어":
            "Korean",

        "🇯🇵 日本語":
            "Japanese",

    }.get(
        language,
        "the target language"
    )

    return f"""
Synthesize natural spoken audio.

Language:
{language_name}

Style:
Natural, clear, conversational voice.

IMPORTANT:
Speak only the transcript.
Do not explain anything.
Do not add words.
Do not translate the transcript.

TRANSCRIPT:
{text}
"""


def write_pcm_wav(
    filename,
    pcm_data,
    channels=1,
    rate=24000,
    sample_width=2
):

    with wave.open(
        filename,
        "wb"
    ) as wf:

        wf.setnchannels(
            channels
        )

        wf.setsampwidth(
            sample_width
        )

        wf.setframerate(
            rate
        )

        wf.writeframes(
            pcm_data
        )


def generate_tts_wav(
    client,
    text,
    output_path,
    voice_name,
    language,
    retries=2
):

    last_error = None

    for attempt in range(
        retries + 1
    ):

        try:

            interaction = client.interactions.create(

                model=
                    "gemini-3.1-flash-tts-preview",

                input=
                    tts_prompt(
                        text,
                        language
                    ),

                response_format={
                    "type": "audio"
                },

                generation_config={

                    "speech_config": [

                        {
                            "voice":
                                voice_name
                        }

                    ]

                },
            )

            audio = getattr(
                interaction,
                "output_audio",
                None
            )

            if (
                audio is None
                or
                not getattr(
                    audio,
                    "data",
                    None
                )
            ):

                raise ValueError(
                    "Gemini TTS មិនបានបញ្ជូនសំឡេងមកទេ។"
                )

            pcm_data = base64.b64decode(
                audio.data
            )

            write_pcm_wav(
                output_path,
                pcm_data
            )

            return

        except Exception as e:

            last_error = e

            if attempt < retries:

                time.sleep(2)

    raise last_error


def create_dubbing_audio(
    client,
    groups,
    output_path,
    temp_dir,
    voice_name,
    dubbing_language
):

    if not groups:

        raise ValueError(
            "មិនមាន Caption សម្រាប់ AI Dubbing ទេ។"
        )

    clip_paths = []

    for index, group in enumerate(
        groups
    ):

        text = str(
            group["text"]
        ).strip()

        if not text:
            continue

        clip_path = os.path.join(
            temp_dir,
            f"dub_{index:04d}.wav"
        )

        generate_tts_wav(
            client,
            text,
            clip_path,
            voice_name,
            dubbing_language,
        )

        clip_paths.append(
            (
                clip_path,
                float(
                    group["start"]
                ),
                float(
                    group["end"]
                ),
            )
        )

    if not clip_paths:

        raise ValueError(
            "មិនអាចបង្កើតសំឡេង AI បានទេ។"
        )

    inputs = []
    filters = []

    for index, (
        clip_path,
        start,
        end
    ) in enumerate(
        clip_paths
    ):

        inputs.extend(
            [
                "-i",
                clip_path
            ]
        )

        delay_ms = max(
            0,
            int(
                start * 1000
            )
        )

        filters.append(
            f"[{index}:a]"
            f"adelay={delay_ms}:all=1"
            f"[a{index}]"
        )

    labels = "".join(
        f"[a{i}]"
        for i in range(
            len(clip_paths)
        )
    )

    filters.append(
        f"{labels}"
        f"amix="
        f"inputs={len(clip_paths)}:"
        f"duration=longest:"
        f"dropout_transition=0:"
        f"normalize=0,"
        f"apad"
        f"[out]"
    )

    filter_complex = ";".join(
        filters
    )

    run_ffmpeg(
        inputs
        + [
            "-filter_complex",
            filter_complex,

            "-map",
            "[out]",

            "-ar",
            "48000",

            "-ac",
            "2",

            "-c:a",
            "aac",

            "-b:a",
            "192k",

            "-y",
            output_path,
        ]
    )


def replace_audio(
    video_path,
    dubbed_audio_path,
    output_path
):

    run_ffmpeg([
        "-y",

        "-i",
        video_path,

        "-i",
        dubbed_audio_path,

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        "-c:v",
        "copy",

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        "-shortest",

        "-movflags",
        "+faststart",

        output_path,
    ])


# =========================
# ASS Subtitle
# =========================

def create_ass(
    groups,
    filename
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
        encoding="utf-8"
    ) as f:

        f.write(
            header
        )

        for group in groups:

            start = group[
                "start"
            ]

            end = group[
                "end"
            ]

            text = group[
                "text"
            ]

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


# =========================
# Burn Caption
# =========================

def burn_caption(
    video_path,
    ass_path,
    output_path
):

    escaped_ass = (
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
# Language Settings
# =========================

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


# =========================
# AI Dubbing Settings
# =========================

st.subheader(
    "🎙️ AI Dubbing"
)


enable_dubbing = st.checkbox(
    "បើក AI Dubbing"
)


dubbing_language = st.selectbox(
    "🗣️ ភាសាសំឡេង AI",
    [
        "🇬🇧 English",
        "🇨🇳 中文",
        "🇻🇳 Tiếng Việt",
        "🇰🇷 한국어",
        "🇯🇵 日本語",
    ],
    disabled=not enable_dubbing,
)


voice_label = st.selectbox(
    "🎤 សម្លេង AI",
    list(
        TTS_VOICES.keys()
    ),
    disabled=not enable_dubbing,
)


if enable_dubbing:

    st.info(
        "AI Dubbing នឹងបង្កើតសំឡេងថ្មី "
        "ហើយជំនួសសំឡេងដើម។"
    )


# =========================
# Video Upload
# =========================

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=[
        "mp4",
        "mov",
        "mkv",
        "webm",
    ],
)


# =========================
# Process
# =========================

if video is not None:

    if st.button(
        "⚡ បង្កើត Caption",
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

            caption_video_path = os.path.join(
                temp_dir,
                "caption_video.mp4"
            )

            dubbed_audio_path = os.path.join(
                temp_dir,
                "dubbed_audio.wav"
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

                # -------------------------
                # Extract Audio
                # -------------------------

                with st.spinner(
                    "⚡ កំពុងដកសំឡេង..."
                ):

                    extract_audio(
                        video_path,
                        audio_path
                    )


                # -------------------------
                # Gemini Transcription
                # -------------------------

                with st.spinner(
                    "🎙️ Gemini កំពុងស្តាប់សំឡេង..."
                ):

                    client = genai.Client(
                        api_key=st.secrets[
                            "GEMINI_API_KEY"
                        ]
                    )

                    audio_file = client.files.upload(
                        file=audio_path
                    )

                    language_codes = []

                    language_code_map = {

                        "🇰🇭 ខ្មែរ":
                            "km-KH",

                        "🇬🇧 English":
                            "en-US",

                        "🇨🇳 中文":
                            "zh-CN",

                        "🇻🇳 Tiếng Việt":
                            "vi-VN",

                        "🇰🇷 한국어":
                            "ko-KR",

                        "🇯🇵 日本語":
                            "ja-JP",
                    }

                    if (
                        source_language
                        != "Auto Detect"
                    ):

                        language_codes = [
                            language_code_map[
                                source_language
                            ]
                        ]

                    interaction = client.interactions.create(

                        model=
                            "gemini-3.5-transcribe",

                        input=[
                            {
                                "type":
                                    "audio",

                                "uri":
                                    audio_file.uri,

                                "mime_type":
                                    audio_file.mime_type,
                            }
                        ],

                        generation_config={

                            "transcription_config": {

                                "language_codes":
                                    language_codes,

                                "mode": {

                                    "type":
                                        "verbatim",

                                    "timestamp_granularities": [
                                        "word"
                                    ],
                                }
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
                        "❌ Gemini មិនបានរកឃើញ Caption timestamps ទេ។"
                    )

                    st.stop()

                   
