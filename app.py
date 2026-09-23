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
from datetime import datetime, timedelta, timezone

import requests

import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg



# =========================================================
# ACCOUNT / SUBSCRIPTION SYSTEM
# =========================================================

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
SUPABASE_KEY = str(st.secrets.get("SUPABASE_KEY", ""))
ADMIN_USERNAME = str(st.secrets.get("ADMIN_USERNAME", ""))
ADMIN_PASSWORD = str(st.secrets.get("ADMIN_PASSWORD", ""))


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
    url = f"{SUPABASE_URL}/rest/v1/accounts"
    response = requests.get(
        url,
        headers=supabase_headers(),
        params={
            "select": "id,username,password_hash,plan,expires_at,active,created_at",
            "username": f"eq.{username}",
            "limit": "1",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def list_accounts():
    url = f"{SUPABASE_URL}/rest/v1/accounts"
    response = requests.get(
        url,
        headers=supabase_headers(),
        params={
            "select": "id,username,plan,expires_at,active,created_at",
            "order": "created_at.desc",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def create_account(username, password, plan, days):
    username = username.strip()
    if not username or not password:
        raise ValueError("សូមបំពេញ Username និង Password។")

    if get_account(username):
        raise ValueError("Username នេះមានរួចហើយ។")

    expires = datetime.now(timezone.utc) + timedelta(days=days)
    payload = {
        "username": username,
        "password_hash": hash_password(password),
        "plan": plan,
        "expires_at": expires.isoformat(),
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


def extend_account(account_id, current_expires, days):
    try:
        current = datetime.fromisoformat(
            current_expires.replace("Z", "+00:00")
        )
    except Exception:
        current = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    base = max(current, now)
    new_expiry = base + timedelta(days=days)

    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/accounts",
        headers={**supabase_headers(), "Prefer": "return=representation"},
        params={"id": f"eq.{account_id}"},
        json={"expires_at": new_expiry.isoformat(), "active": True},
        timeout=20,
    )
    response.raise_for_status()
    return new_expiry


def is_account_valid(account):
    if not account or not account.get("active"):
        return False
    try:
        expiry = datetime.fromisoformat(
            account["expires_at"].replace("Z", "+00:00")
        )
        return expiry > datetime.now(timezone.utc)
    except Exception:
        return False


def format_expiry(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def show_login():
    st.title("🔐 Smey Auto Caption")
    st.subheader("ចូលប្រើ Account")

    with st.form("login_form"):
        username = st.text_input("👤 Username")
        password = st.text_input("🔑 Password", type="password")
        submitted = st.form_submit_button(
            "ចូលប្រើ",
            use_container_width=True,
        )

    if submitted:
        if not username or not password:
            st.error("សូមបំពេញ Username និង Password។")
            return

        # Admin login is kept in Streamlit Secrets, never in GitHub code.
        if ADMIN_USERNAME and ADMIN_PASSWORD:
            if (
                hmac.compare_digest(username, ADMIN_USERNAME)
                and hmac.compare_digest(password, ADMIN_PASSWORD)
            ):
                st.session_state.logged_in = True
                st.session_state.is_admin = True
                st.session_state.account = {
                    "username": ADMIN_USERNAME,
                    "plan": "ADMIN",
                }
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

            if not is_account_valid(account):
                st.error("⛔ Account នេះផុតកំណត់ ឬត្រូវបានបិទ។")
                return

            st.session_state.logged_in = True
            st.session_state.is_admin = False
            st.session_state.account = account
            st.rerun()
        except Exception as e:
            st.error("❌ មិនអាចភ្ជាប់ទៅ Account Database បានទេ។")
            st.exception(e)


def show_admin_panel():
    st.title("👑 Smey Auto Caption — Admin")
    st.caption("អ្នកអាចបង្កើត និងគ្រប់គ្រង Account អតិថិជននៅទីនេះ។")

    if st.button("🚪 ចាកចេញ", key="admin_logout"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.subheader("➕ បង្កើត Account ថ្មី")

    plans = {
        "$1.99 — 1 ខែ": ("1_MONTH", 30),
        "$5 — 3 ខែ": ("3_MONTHS", 90),
        "$100 — 1 ឆ្នាំ": ("1_YEAR", 365),
    }

    with st.form("create_account_form"):
        username = st.text_input("👤 Username ថ្មី")
        password = st.text_input("🔑 Password ថ្មី", type="password")
        plan_label = st.selectbox("💵 ជ្រើសកញ្ចប់", list(plans.keys()))
        create_clicked = st.form_submit_button(
            "បង្កើត Account",
            use_container_width=True,
        )

    if create_clicked:
        try:
            plan, days = plans[plan_label]
            account = create_account(
                username,
                password,
                plan,
                days,
            )
            st.success(
                f"✅ បង្កើត Account `{username.strip()}` រួចរាល់។"
            )
            st.info(
                "Username និង Password ខាងលើ សូមផ្ញើឲ្យអតិថិជនដោយផ្ទាល់។"
            )
            st.write("ថ្ងៃផុតកំណត់:", format_expiry(account["expires_at"]))
        except Exception as e:
            st.error("❌ មិនអាចបង្កើត Account បានទេ។")
            st.exception(e)

    st.divider()
    st.subheader("👥 Account អតិថិជន")

    try:
        accounts = list_accounts()
        if not accounts:
            st.info("មិនទាន់មាន Account អតិថិជនទេ។")
            return

        for account in accounts:
            valid = is_account_valid(account)
            status = "🟢 កំពុងប្រើ" if valid else "🔴 ផុតកំណត់/បិទ"

            with st.expander(
                f"👤 {account['username']} — {status}"
            ):
                st.write("កញ្ចប់:", account["plan"])
                st.write(
                    "ផុតកំណត់:",
                    format_expiry(account["expires_at"]),
                )

                c1, c2 = st.columns(2)

                if account.get("active"):
                    if c1.button(
                        "🚫 បិទ Account",
                        key=f"disable_{account['id']}",
                    ):
                        try:
                            update_account_status(
                                account["id"],
                                False,
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
                else:
                    if c1.button(
                        "✅ បើក Account",
                        key=f"enable_{account['id']}",
                    ):
                        try:
                            update_account_status(
                                account["id"],
                                True,
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

                extension_options = {
                    "បន្ត 1 ខែ": 30,
                    "បន្ត 3 ខែ": 90,
                    "បន្ត 1 ឆ្នាំ": 365,
                }
                extend_choice = c2.selectbox(
                    "បន្តសុពលភាព",
                    list(extension_options.keys()),
                    key=f"extend_choice_{account['id']}",
                )
                if st.button(
                    "📅 បន្ត",
                    key=f"extend_{account['id']}",
                ):
                    try:
                        new_expiry = extend_account(
                            account["id"],
                            account["expires_at"],
                            extension_options[extend_choice],
                        )
                        st.success(
                            f"បានបន្តដល់ {format_expiry(new_expiry.isoformat())}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
    except Exception as e:
        st.error("❌ មិនអាចអានបញ្ជី Account បានទេ។")
        st.exception(e)


# =========================================================
# Login Gate
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        st.warning(
            "⚠️ សូមដាក់ ADMIN_USERNAME និង ADMIN_PASSWORD ក្នុង Streamlit Secrets ជាមុនសិន។"
        )
    show_login()
    st.stop()

if st.session_state.is_admin:
    show_admin_panel()
    st.stop()

current_account = st.session_state.get("account") or {}
if not is_account_valid(current_account):
    st.session_state.clear()
    st.error("⛔ Account របស់អ្នកផុតកំណត់ ឬត្រូវបានបិទ។")
    st.stop()

st.sidebar.success(f"👤 {current_account.get('username', '')}")
st.sidebar.info(
    f"📅 ផុតកំណត់: {format_expiry(current_account['expires_at'])}"
)
if st.sidebar.button("🚪 ចាកចេញ"):
    st.session_state.clear()
    st.rerun()

st.set_page_config(
    page_title="Smey Auto Caption",
    page_icon="🇰🇭",
)

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
            "speech_config"
