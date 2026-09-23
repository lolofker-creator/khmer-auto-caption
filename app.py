import os
import base64
import subprocess
import tempfile
import wave
import json
import urllib.request
import time
import hashlib
import hmac
import secrets
import time

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

    source_name = source_map.get(source_language, "the original language")
    target_name = target_map.get(target_language, "Khmer")

    # Keep Gemini requests comfortably below the Free-tier 15 requests/minute
    # limit. One request handles several captions, so normal videos need only
    # a small number of Gemini calls.
    batch_size = 20
    min_gap = 4.5
    last_request_time = [0.0]

    def gemini_translate(texts):
        prompt = f"""
Translate these video captions from {source_name} to {target_name}.

Return EXACTLY {len(texts)} strings in one JSON array.
Rules:
- one output string for each input caption
- same order
- never merge or split captions
- no numbering
- no explanation
- natural subtitle translation

Captions:
"""
        for i, caption_text in enumerate(texts, 1):
            prompt += f"\n{i}. {caption_text}"

        models = [
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
        ]

        last_error = None
        for model_name in models:
            for attempt in range(3):
                wait = min_gap - (time.monotonic() - last_request_time[0])
                if wait > 0:
                    time.sleep(wait)

                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=list[str],
                        ),
                    )
                    last_request_time[0] = time.monotonic()
                    translated = response.parsed
                    if translated and len(translated) == len(texts):
                        return [str(x).strip() for x in translated]
                    last_error = ValueError(
                        f"Gemini returned {len(translated or [])} captions; expected {len(texts)}."
                    )
                    break
                except Exception as e:
                    last_request_time[0] = time.monotonic()
                    last_error = e
                    error_text = str(e)
                    if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                        # Gemini often tells us exactly how long to wait.
                        delay = 16.0
                        import re
                        m = re.search(r"retry in ([0-9.]+)s", error_text, re.I)
                        if m:
                            delay = max(16.0, float(m.group(1)) + 1.0)
                        time.sleep(delay)
                        continue
                    if "503" in error_text or "UNAVAILABLE" in error_text:
                        time.sleep(3.0)
                        continue
                    break

        # Last-resort: preserve original text instead of crashing the video.
        if last_error:
            raise RuntimeError(
                "❌ Gemini Translation កំពុងដល់ rate limit/quota។ "
                "សូមរង់ចាំបន្តិច ហើយសាកម្តងទៀត។"
            ) from last_error
        return texts

    translated_all = []
    for start in range(0, len(groups), batch_size):
        batch_groups = groups[start:start + batch_size]
        batch_texts = [str(g["text"]).strip() for g in batch_groups]
        translated_all.extend(gemini_translate(batch_texts))

    return [
        {
            "start": group["start"],
            "end": group["end"],
            "text": str(translated_text).strip(),
        }
        for group, translated_text in zip(groups, translated_all)
    ]


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
    """Generate Khmer speech with Doslarb Cloud TTS.

    Free Doslarb is limited to 10 requests/minute. The dubbing process can
    create many TTS requests in a short time, so this function deliberately
    spaces requests out and retries HTTP 429 responses instead of failing.
    """
    api_key = str(st.secrets.get("DOSLARB_API_KEY", "")).strip()

    if not api_key:
        raise RuntimeError(
            "❌ មិនមាន DOSLARB_API_KEY ក្នុង Streamlit Secrets ទេ។"
        )

    if not api_key.startswith("ds_sk_"):
        raise RuntimeError(
            "❌ DOSLARB_API_KEY មិនមានទម្រង់ត្រឹមត្រូវទេ។ "
            "Doslarb API Key ត្រូវចាប់ផ្ដើមដោយ ds_sk_."
        )

    clean_text = str(text).strip()
    if not clean_text:
        raise ValueError("❌ អត្ថបទសម្រាប់ Doslarb TTS ទទេ។")

    # Doslarb Free allows up to 1200 Unicode characters per TTS request.
    if len(clean_text) > 1200:
        clean_text = clean_text[:1200]

    data = json.dumps({
        "text": clean_text,
        "voice": "sovann",
    }, ensure_ascii=False).encode("utf-8")

    # Free tier: 10 requests/minute. Keep at least ~6.2 seconds between
    # requests made by this Streamlit session so we stay safely below the cap.
    min_interval = 6.2
    last_request_at = float(
        st.session_state.get("doslarb_last_request_at", 0.0)
    )
    elapsed = time.monotonic() - last_request_at
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

    max_429_retries = 5
    mp3_data = None

    for attempt in range(max_429_retries + 1):
        request = urllib.request.Request(
            "https://doslarb.cloud/api/v1/tts",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            },
            method="POST",
        )

        st.session_state["doslarb_last_request_at"] = time.monotonic()

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                mp3_data = response.read()
            break

        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace").strip()
            except Exception:
                body = ""

            if e.code == 429:
                if attempt >= max_429_retries:
                    raise RuntimeError(
                        "❌ Doslarb នៅតែបញ្ជូន 429 បន្ទាប់ពីរង់ចាំ និងសាកម្ដងទៀត។ "
                        "Free plan មានកំណត់ 10 requests/នាទី។ សូមរង់ចាំបន្តិច ហើយសាកម្ដងទៀត។"
                    ) from e

                retry_after = 0.0
                try:
                    retry_after = float(e.headers.get("Retry-After", "0"))
                except Exception:
                    retry_after = 0.0

                # If Doslarb supplies Retry-After, honor it. Otherwise use
                # an increasing backoff, always at least 7 seconds.
                wait_seconds = max(
                    7.0,
                    retry_after,
                    7.0 * (attempt + 1),
                )

                st.info(
                    f"⏳ Doslarb កំពុងកំណត់ល្បឿន។ "
                    f"កម្មវិធីនឹងរង់ចាំ {wait_seconds:.0f} វិនាទី "
                    f"ហើយសាកម្ដងទៀត ({attempt + 1}/{max_429_retries})..."
                )
                time.sleep(wait_seconds)
                continue

            if e.code == 401:
                raise RuntimeError(
                    "❌ Doslarb API Key មិនត្រឹមត្រូវ ឬត្រូវបានបដិសេធ (401). "
                    "សូមពិនិត្យ DOSLARB_API_KEY ដែលចាប់ផ្ដើមដោយ ds_sk_."
                ) from e

            if e.code == 403:
                detail = body[:500] if body else "គ្មានព័ត៌មានបន្ថែមពី Server"
                raise RuntimeError(
                    "❌ Doslarb បដិសេធសំណើ (403 Forbidden).\n\n"
                    "សូមពិនិត្យ DOSLARB_API_KEY ក្នុង Streamlit Secrets។\n\n"
                    f"Server response: {detail}"
                ) from e

            if e.code in (502, 503, 504):
                if attempt < 2:
                    time.sleep(7.0)
                    continue
                raise RuntimeError(
                    f"❌ Doslarb TTS មិនអាចប្រើបានបណ្ដោះអាសន្ន ({e.code}). "
                    "សូមសាកម្ដងទៀត។"
                ) from e

            detail = body[:500] if body else "គ្មានព័ត៌មានបន្ថែមពី Server"
            raise RuntimeError(
                f"❌ Doslarb API Error {e.code}: {detail}"
            ) from e

    if not mp3_data:
        raise RuntimeError("❌ Doslarb មិនបានបញ្ជូនសម្លេង MP3 មកទេ។")

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
