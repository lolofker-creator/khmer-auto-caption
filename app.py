import os
import base64
import subprocess
import tempfile
import wave
import json
import urllib.request
import hashlib
import hmac
import secrets

from datetime import datetime, timezone

import requests
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)


# =========================================================
# OWNER-ONLY ACCOUNT SYSTEM
# =========================================================

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
SUPABASE_KEY = str(st.secrets.get("SUPABASE_KEY", ""))
ADMIN_USERNAME = str(st.secrets.get("ADMIN_USERNAME", ""))
ADMIN_PASSWORD = str(st.secrets.get("ADMIN_PASSWORD", ""))
TELEGRAM_URL = "https://t.me/Smeytk"


def supabase_headers():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "សូមដាក់ SUPABASE_URL និង SUPABASE_KEY ក្នុង Streamlit Secrets។"
        )
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def hash_password(password, salt=None):
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        200_000,
    )
    return f"pbkdf2_sha256$200000${salt_bytes.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(rounds),
        ).hex()
        return hmac.compare_digest(actual, digest_hex)
    except Exception:
        return False


def get_account(username):
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/accounts",
        headers=supabase_headers(),
        params={
            "select": "id,username,password_hash,active,created_at",
            "username": f"eq.{username}",
            "limit": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def list_accounts():
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/accounts",
        headers=supabase_headers(),
        params={
            "select": "id,username,active,created_at",
            "order": "created_at.desc",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def create_account(username, password):
    username = username.strip()
    if not username or not password:
        raise ValueError("សូមបំពេញ Username និង Password។")

    if get_account(username):
        raise ValueError("Username នេះមានរួចហើយ។")

    # The existing Supabase table has plan/expires_at as required columns.
    # They are kept only for database compatibility and are NOT used by the app.
    payload = {
        "username": username,
        "password_hash": hash_password(password),
        "plan": "STANDARD",
        "expires_at": "2099-12-31T23:59:59+00:00",
        "active": True,
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/accounts",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else payload


def update_account_status(account_id, active):
    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/accounts",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        params={"id": f"eq.{account_id}"},
        json={"active": active},
        timeout=20,
    )
    response.raise_for_status()


def show_login():
    st.title("🔐 Smey Auto Caption")
    st.subheader("ចូលប្រើ Account")

    with st.form("login_form"):
        username = st.text_input("👤 Username")
        password = st.text_input("🔑 Password", type="password")
        submitted = st.form_submit_button("ចូលប្រើ", use_container_width=True)

    st.link_button(
        "📱 ទាក់ទងម្ចាស់តាម Telegram",
        TELEGRAM_URL,
        use_container_width=True,
    )
    st.caption("មិនមាន Account? សូមទាក់ទងម្ចាស់កម្មវិធី ដើម្បីឲ្យម្ចាស់បង្កើត Account ឲ្យ។")

    if submitted:
        if not username or not password:
            st.error("សូមបំពេញ Username និង Password។")
            return

        # Owner/Admin credentials live only in Streamlit Secrets.
        if ADMIN_USERNAME and ADMIN_PASSWORD:
            if (
                hmac.compare_digest(username, ADMIN_USERNAME)
                and hmac.compare_digest(password, ADMIN_PASSWORD)
            ):
                st.session_state.logged_in = True
                st.session_state.is_admin = True
                st.session_state.account = {"username": ADMIN_USERNAME}
                st.rerun()
                return

        try:
            account = get_account(username)
            if not account or not verify_password(
                password,
                account["password_hash"],
            ):
                st.error("❌ Username ឬ Password មិនត្រឹមត្រូវ។")
                return

            if not account.get("active", False):
                st.error("⛔ Account នេះត្រូវបានបិទ។")
                return

            st.session_state.logged_in = True
            st.session_state.is_admin = False
            st.session_state.account = account
            st.rerun()
        except Exception as e:
            st.error("❌ មិនអាចភ្ជាប់ទៅ Account Database បានទេ។")
            st.caption("បើមានបញ្ហា DNS/Supabase សូមពិនិត្យ Supabase API URL។")
            st.exception(e)


def show_admin_panel():
    st.caption("👑 ម្ចាស់កម្មវិធី")

    st.link_button(
        "📱 Telegram របស់ម្ចាស់",
        TELEGRAM_URL,
        use_container_width=True,
    )

    if st.button("🚪 ចាកចេញ", key="admin_logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# =========================================================
# LOGIN GATE
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        st.warning("⚠️ សូមដាក់ ADMIN_USERNAME និង ADMIN_PASSWORD ក្នុង Streamlit Secrets។")
    show_login()
    st.stop()

# Admin អាចប្រើ Caption Tool បានដែរ។
# មិនបង្ហាញផ្នែកបង្កើត Account ហើយក៏មិនបញ្ឈប់កម្មវិធីនៅ Admin page ទេ។
if st.session_state.is_admin:
    show_admin_panel()

else:
    current_account = st.session_state.get("account") or {}

    if not current_account.get("active", False):
        st.session_state.clear()
        st.error("⛔ Account នេះត្រូវបានបិទ។")
        st.stop()

    st.sidebar.success(f"👤 {current_account.get('username', '')}")
    st.sidebar.link_button(
        "📱 ទាក់ទងម្ចាស់តាម Telegram",
        TELEGRAM_URL,
        use_container_width=True,
    )

    if st.sidebar.button("🚪 ចាកចេញ"):
        st.session_state.clear()
        st.rerun()


# Authentication is shown before the caption tool.
st.title("🇰🇭 Smey Auto Caption")
st.write("Gemini → Caption → Auto Translate → AI Dubbing → MP4")


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

    # Translation model fallback:
    # 3.5 Flash-Lite is used first for lightweight/high-volume translation.
    # If it is temporarily unavailable, try 3.6 Flash.
    models_to_try = [
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ]

    response = None
    last_error = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=list[str],
                ),
            )
            break
        except Exception as e:
            last_error = e
            error_text = str(e)

            # 503 = temporary model unavailability/high demand.
            # Try the next model instead of stopping the whole video.
            if "503" in error_text or "UNAVAILABLE" in error_text:
                continue

            raise

    if response is None:
        raise RuntimeError(
            "❌ Gemini Translation មិនអាចដំណើរការបានឥឡូវនេះ។ "
            "ម៉ូដែលបកប្រែទាំងអស់កំពុងមិនអាចប្រើបានជាបណ្តោះអាសន្ន។"
        ) from last_error

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
# AI Dubbing
# =========================================================

TTS_VOICES = {
    "Kore — Firm": "Kore",
    "Puck — Upbeat": "Puck",
    "Charon — Informative": "Charon",
    "Fenrir — Excitable": "Fenrir",
    "Leda — Youthful": "Leda",
    "Aoede — Breezy": "Aoede",
    "Iapetus — Clear": "Iapetus",
    "Achird — Friendly": "Achird",
    "Sulafat — Warm": "Sulafat",
}


def get_tts_language(language):
    return {
        "🇬🇧 English": "English",
        "🇨🇳 中文": "Chinese Mandarin",
        "🇻🇳 Tiếng Việt": "Vietnamese",
        "🇰🇷 한국어": "Korean",
        "🇯🇵 日本語": "Japanese",
    }.get(language, "English")


def generate_doslarb_tts_wav(
    text,
    output_path,
):
    api_key = st.secrets["DOSLARB_API_KEY"]

    data = json.dumps({
        "text": text,
        "voice": "sovann",
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://doslarb.cloud/api/v1/tts",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=60,
    ) as response:
        mp3_data = response.read()

    mp3_path = output_path.replace(
        ".wav",
        ".mp3",
    )

    with open(
        mp3_path,
        "wb",
    ) as f:
        f.write(mp3_data)

    run_ffmpeg([
        "-y",
        "-i", mp3_path,
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        output_path,
    ])

    os.remove(mp3_path)


def generate_tts_wav(
    client,
    text,
    output_path,
    voice_name,
    language,
):
    if language == "🇰🇭 ខ្មែរ":
        generate_doslarb_tts_wav(
            text,
            output_path,
        )
        return

    language_name = get_tts_language(language)

    prompt = f"""
Speak the following text naturally.

Language:
{language_name}

Style:
Natural, clear, conversational.

Speak ONLY the transcript below.
Do not explain anything.
Do not add extra words.

TRANSCRIPT:
{text}
"""

    interaction = client.interactions.create(
        model="gemini-3.1-flash-tts-preview",
        input=prompt,
        response_format={
            "type": "audio",
        },
        generation_config={
            "speech_config": [
                {
                    "voice": voice_name,
                }
            ]
        },
    )

    if not interaction.output_audio:
        raise ValueError(
            "Gemini TTS មិនបានបញ្ជូនសំឡេងមកទេ។"
        )

    audio_data = base64.b64decode(
        interaction.output_audio.data
    )

    with wave.open(
        output_path,
        "wb",
    ) as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_data)


def create_dubbing_audio(
    client,
    groups,
    output_path,
    temp_dir,
    voice_name,
    dubbing_language,
):
    if not groups:
        raise ValueError(
            "មិនមាន Caption សម្រាប់ AI Dubbing ទេ។"
        )

    clip_paths = []

    for index, group in enumerate(groups):
        text = str(
            group["text"]
        ).strip()

        if not text:
            continue

        clip_path = os.path.join(
            temp_dir,
            f"dub_{index:04d}.wav",
        )

        generate_tts_wav(
            client,
            text,
            clip_path,
            voice_name,
            dubbing_language,
        )

        clip_paths.append((
            clip_path,
            float(group["start"]),
        ))

    if not clip_paths:
        raise ValueError(
            "មិនអាចបង្កើតសំឡេង AI បានទេ។"
        )

    inputs = []
    filters = []

    for index, (
        clip_path,
        start,
    ) in enumerate(clip_paths):
        inputs.extend([
            "-i",
            clip_path,
        ])

        delay_ms = max(
            0,
            int(start * 1000),
        )

        filters.append(
            f"[{index}:a]"
            f"adelay={delay_ms}:all=1"
            f"[a{index}]"
        )

    labels = "".join(
        f"[a{i}]"
        for i in range(len(clip_paths))
    )

    filters.append(
        f"{labels}"
        f"amix="
        f"inputs={len(clip_paths)}:"
        f"duration=longest:"
        f"dropout_transition=0:"
        f"normalize=0"
        f"[out]"
    )

    run_ffmpeg(
        inputs
        + [
            "-filter_complex",
            ";".join(filters),
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
    output_path,
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
               text = text.replace("\n", " ")
            text = text.replace("{", r"\{")
            text = text.replace("}", r"\}")

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
        "🇨🇳 中文",
        "Auto Detect",
        "🇰🇭 ខ្មែរ",
        "🇬🇧 English",
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
# AI Dubbing Settings
# =========================================================

st.subheader("🎙️ AI Dubbing")

enable_dubbing = st.checkbox(
    "បើក AI Dubbing",
)

dubbing_language = st.selectbox(
    "🗣️ ភាសាសំឡេង AI",
    [
        "🇰🇭 ខ្មែរ",
        "🇬🇧 English",
        "🇨🇳 中文",
        "🇻🇳 Tiếng Việt",
        "🇰🇷 한국어",
        "🇯🇵 日本語",
    ],
    index=0,
    disabled=not enable_dubbing,
)

voice_label = st.selectbox(
    "🎤 សម្លេង AI",
    list(TTS_VOICES.keys()),
    disabled=(
        not enable_dubbing
        or dubbing_language == "🇰🇭 ខ្មែរ"
    ),
)

if enable_dubbing:
    if dubbing_language == "🇰🇭 ខ្មែរ":
        st.info(
            "🇨🇳➡️🇰🇭 រឿងចិន → បកប្រែជាខ្មែរ → សំឡេង AI ខ្មែរ។ "
            "មិនចាំបាច់ជ្រើស 'បកប្រែទៅជា' ទៀតទេ។"
        )
    else:
        st.info(
            "AI Dubbing នឹងបង្កើតសំឡេងថ្មី "
            "ហើយជំនួសសំឡេងដើម។"
        )

    if dubbing_language == "🇰🇭 ខ្មែរ":
        st.caption(
            "🇰🇭 សំឡេងខ្មែរ ប្រើ Doslarb — Sovann"
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

    dubbing_clicked = st.button(
        "🎙️ AI Dubbing",
        use_container_width=True,
    )

    if caption_clicked or dubbing_clicked:

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

            dubbed_audio_path = os.path.join(
                temp_dir,
                "dubbed_audio.m4a",
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
                                "language_codes": language_codes,
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
                            "❌ Gemini មិនបានរកឃើញ Caption timestamps ទេ។"
                        )
                        st.stop()


                # ---------------------------------
                # Auto Translate
                # ---------------------------------

                # AI Dubbing អាចជ្រើសភាសារបស់វាដោយផ្ទាល់
                # មិនបង្ខំឱ្យអ្នកជ្រើស "បកប្រែទៅជា" ទៀតទេ។
                dubbing_target_language = (
                    dubbing_language
                    if dubbing_clicked and enable_dubbing
                    else target_language
                )

                if dubbing_target_language != "មិនបកប្រែ":
                    with st.spinner(
                        "🌐 Gemini កំពុងបកប្រែ Caption..."
                    ):
                        groups = translate_captions(
                            client,
                            groups,
                            source_language,
                            dubbing_target_language,
                        )


                # ---------------------------------
                # Caption ONLY
                # ---------------------------------

                if caption_clicked:

                    ass_path = os.path.join(
                        temp_dir,
                        "khmer_caption.ass",
                    )

                    caption_video_path = os.path.join(
                        temp_dir,
                        "caption_video.mp4",
                    )

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
                # AI Dubbing ONLY
                # ---------------------------------

                if dubbing_clicked:

                    if not enable_dubbing:
                        st.warning(
                            "⚠️ សូមបើក AI Dubbing ជាមុនសិន។"
                        )
                        st.stop()

                    # មិនចាំបាច់ឱ្យ "បកប្រែទៅជា" ត្រូវបានជ្រើសទៀតទេ។
                    # AI Dubbing ប្រើ "ភាសាសំឡេង AI" ជាភាសាគោល។

                    with st.spinner(
                        "🎙️ កំពុងបង្កើតសំឡេង AI..."
                    ):

                        if dubbing_language == "🇰🇭 ខ្មែរ":
                            voice_name = "Sovann"
                        else:
                            voice_name = TTS_VOICES[
                                voice_label
                            ]

                        create_dubbing_audio(
                            client,
                            groups,
                            dubbed_audio_path,
                            temp_dir,
                            voice_name,
                            dubbing_language,
                        )

                    with st.spinner(
                        "🔊 កំពុងជំនួសសំឡេងដើម..."
                    ):
                        replace_audio(
                            video_path,
                            dubbed_audio_path,
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
