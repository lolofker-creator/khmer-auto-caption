import os
import json
import base64
import hmac
import hashlib
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(page_title="Smey Auto Caption", page_icon="🇰🇭", layout="centered")

# =========================================================
# BASIC SETTINGS
# =========================================================

st.title("🇰🇭 Smey Auto Caption")
st.write("Gemini → Caption → Auto Translate → MP4")

PLANS = {
    "1 ខែ — $1.99": {"amount": "1.99", "days": 30},
    "3 ខែ — $5.00": {"amount": "5.00", "days": 90},
    "1 ឆ្នាំ — $100.00": {"amount": "100.00", "days": 365},
}

ABA_PURCHASE_URL = st.secrets.get(
    "ABA_API_URL",
    "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase",
)
ABA_CHECK_URL = (
    "https://checkout-sandbox.payway.com.kh/"
    "api/payment-gateway/v1/payments/check-transaction-2"
)
ABA_MERCHANT_ID = st.secrets.get("ABA_MERCHANT_ID", "")
# PayWay's purchase hash uses the ABA-provided public/API key as the HMAC key.
ABA_PUBLIC_KEY = st.secrets.get("ABA_PUBLIC_KEY", "")

# =========================================================
# HELPERS
# =========================================================

def get_secret(name, default=""):
    try:
        return str(st.secrets[name])
    except Exception:
        return default


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
        "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", audio_path,
    ])


def to_seconds(value):
    if not value:
        return 0.0
    value = str(value).replace("s", "")
    try:
        return float(value)
    except Exception:
        return 0.0


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_groups(segments):
    groups = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", start + 2))
        except Exception:
            continue
        if end <= start:
            end = start + 2
        groups.append({"start": start, "end": end, "text": text})
    return groups


def translate_captions(client, groups, source_language, target_language):
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

    prompt = f"""
Translate these video captions.

Source language: {source_map.get(source_language, "the original language")}
Target language: {target_map.get(target_language, "Khmer")}

Rules:
1. Return exactly one translated string for every input caption.
2. Keep the exact same order.
3. Do not add explanations or numbering.
4. Do not merge captions.
5. Keep names and numbers accurate.
6. Return only a JSON array of strings.

Captions:
"""
    for i, group in enumerate(groups, 1):
        prompt += f"\n{i}. {group['text']}"

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[str],
        ),
    )

    translated = response.parsed
    if not translated or len(translated) != len(groups):
        raise ValueError("Gemini បកប្រែ Caption មិនបានត្រឹមត្រូវ។")

    return [
        {
            "start": group["start"],
            "end": group["end"],
            "text": str(translated_text).strip(),
        }
        for group, translated_text in zip(groups, translated)
    ]


def create_ass(groups, filename):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Khmer,Noto Sans Khmer,70,&H00CC66FF,&H00FFFFFF,&HFFFFFF,&H99000000,1,0,0,0,100,100,0,0,3,3,1,2,50,50,150,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(header)
        for group in groups:
            text = str(group["text"]).replace("\n", " ")
            text = text.replace("{", r"\{").replace("}", r"\}")
            f.write(
                f"Dialogue: 0,{ass_time(group['start'])},"
                f"{ass_time(group['end'])},Khmer,,0,0,0,,{text}\n"
            )


def burn_caption(video_path, ass_path, output_path):
    escaped = ass_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    run_ffmpeg([
        "-y", "-i", video_path,
        "-vf", f"ass='{escaped}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        output_path,
    ])


# =========================================================
# ABA PAYWAY
# =========================================================

def payway_hash(text):
    if not ABA_PUBLIC_KEY:
        raise RuntimeError("ខ្វះ ABA_PUBLIC_KEY ក្នុង Streamlit Secrets។")
    return base64.b64encode(
        hmac.new(
            ABA_PUBLIC_KEY.encode("utf-8"),
            text.encode("utf-8"),
            hashlib.sha512,
        ).digest()
    ).decode("utf-8")


def new_tran_id():
    # Max 20 chars according to PayWay.
    return datetime.now(timezone.utc).strftime("%y%m%d%H%M%S%f")[:20]


def make_purchase_form(plan_name, email, firstname, lastname, phone):
    plan = PLANS[plan_name]
    amount = plan["amount"]
    tran_id = new_tran_id()
    req_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    return_params = json.dumps(
        {"plan": plan_name, "email": email},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # Purchase hash order specified by PayWay.
    items_json = json.dumps(
        [{"name": "Smey Auto Caption " + plan_name, "quantity": 1, "price": float(amount)}],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    items = base64.b64encode(items_json.encode("utf-8")).decode("utf-8")

    values = [
        req_time, ABA_MERCHANT_ID, tran_id, amount, items, "",
        firstname, lastname, email, phone, "purchase", "",
        "", "", "", "", "USD", "", return_params, "", "", "", "", ""
    ]
    signature = payway_hash("".join(values))

    # The official checkout2-0.js opens PayWay's hosted checkout.
    html = f"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://checkout.payway.com.kh/plugins/checkout2-0.js" defer></script>
<style>
body{{font-family:Arial,sans-serif;margin:0;padding:10px;background:#fff}}
button{{width:100%;padding:14px;border:0;border-radius:10px;background:#0b8f5a;color:white;font-size:17px}}
.small{{font-size:12px;color:#666;margin-top:8px;text-align:center}}
</style>
</head>
<body>
<form method="POST" target="aba_webservice" id="aba_merchant_request"
      action="{ABA_PURCHASE_URL}">
<input type="hidden" name="hash" value="{signature}">
<input type="hidden" name="req_time" value="{req_time}">
<input type="hidden" name="merchant_id" value="{ABA_MERCHANT_ID}">
<input type="hidden" name="tran_id" value="{tran_id}">
<input type="hidden" name="firstname" value="{firstname}">
<input type="hidden" name="lastname" value="{lastname}">
<input type="hidden" name="email" value="{email}">
<input type="hidden" name="phone" value="{phone}">
<input type="hidden" name="type" value="purchase">
<input type="hidden" name="payment_option" value="">
<input type="hidden" name="items" value="{items}">
<input type="hidden" name="shipping" value="">
<input type="hidden" name="amount" value="{amount}">
<input type="hidden" name="currency" value="USD">
<input type="hidden" name="return_url" value="">
<input type="hidden" name="cancel_url" value="">
<input type="hidden" name="continue_success_url" value="">
<input type="hidden" name="return_deeplink" value="">
<input type="hidden" name="custom_fields" value="">
<input type="hidden" name="return_params" value='{return_params.replace("'", "&#39;")}'>
<input type="hidden" name="view_type" value="">
<input type="hidden" name="payment_gate" value="">
<input type="hidden" name="payout" value="">
<input type="hidden" name="additional_params" value="">
<input type="hidden" name="lifetime" value="">
<input type="hidden" name="google_pay_token" value="">
<input type="hidden" name="skip_success_page" value="">
<button type="submit">💳 បង់ {amount} USD តាម ABA PayWay</button>
</form>
<script>
document.getElementById("aba_merchant_request").addEventListener("submit", function(event) {{
  event.preventDefault();
  if (window.AbaPayway) {{
    AbaPayway.checkout();
  }} else {{
    this.submit();
  }}
}});
</script>
<div class="small">Sandbox សម្រាប់សាកល្បងប៉ុណ្ណោះ</div>
</body>
</html>
"""
    return tran_id, html


def check_payment(tran_id):
    req_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    signature = payway_hash(req_time + ABA_MERCHANT_ID + tran_id)

    response = requests.post(
        ABA_CHECK_URL,
        json={
            "req_time": req_time,
            "merchant_id": ABA_MERCHANT_ID,
            "tran_id": tran_id,
            "hash": signature,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# =========================================================
# SUBSCRIPTION UI
# =========================================================

if "premium_until" not in st.session_state:
    st.session_state.premium_until = None
if "pending_tran_id" not in st.session_state:
    st.session_state.pending_tran_id = None
if "pending_plan" not in st.session_state:
    st.session_state.pending_plan = None

with st.expander("💳 កញ្ចប់ Premium", expanded=True):
    plan_name = st.selectbox("ជ្រើសគម្រោង", list(PLANS.keys()))
    c1, c2 = st.columns(2)
    with c1:
        firstname = st.text_input("នាមខ្លួន")
        email = st.text_input("Email")
    with c2:
        lastname = st.text_input("នាមត្រកូល")
        phone = st.text_input("លេខទូរស័ព្ទ")

    if not ABA_MERCHANT_ID or not ABA_PUBLIC_KEY:
        st.warning("⚠️ ABA credentials មិនទាន់គ្រប់នៅ Streamlit Secrets។")
    else:
        if st.button("💳 បង្កើតការបង់ប្រាក់ ABA", use_container_width=True):
            if not email or not firstname or not phone:
                st.error("សូមបំពេញ នាមខ្លួន, Email និងលេខទូរស័ព្ទសិន។")
            else:
                try:
                    tran_id, payment_html = make_purchase_form(
                        plan_name, email, firstname, lastname, phone
                    )
                    st.session_state.pending_tran_id = tran_id
                    st.session_state.pending_plan = plan_name
                    st.success("បានបង្កើត Transaction។ ចុចប៊ូតុងខាងក្រោមដើម្បីបង់ប្រាក់។")
                    components.html(payment_html, height=120, scrolling=False)
                except Exception as e:
                    st.error(f"❌ បង្កើត Payment មិនបាន: {e}")

    if st.session_state.pending_tran_id:
        st.info(f"Transaction: {st.session_state.pending_tran_id}")
        if st.button("🔄 ពិនិត្យការបង់ប្រាក់", use_container_width=True):
            try:
                result = check_payment(st.session_state.pending_tran_id)
                data = result.get("data", {})
                status = data.get("payment_status", "")
                code = data.get("payment_status_code")
                expected = float(PLANS[st.session_state.pending_plan]["amount"])
                paid = float(data.get("payment_amount", 0) or 0)

                if code == 0 and status == "APPROVED" and abs(paid - expected) < 0.001:
                    now = datetime.now(timezone.utc)
                    old = st.session_state.premium_until
                    if old and old > now:
                        start = old
                    else:
                        start = now
                    days = PLANS[st.session_state.pending_plan]["days"]
                    st.session_state.premium_until = start + timedelta(days=days)
                    st.success(
                        f"✅ បង់ប្រាក់ជោគជ័យ! Premium ដល់ "
                        f"{st.session_state.premium_until.strftime('%Y-%m-%d %H:%M UTC')}"
                    )
                else:
                    st.warning(f"មិនទាន់ Approved: {status or code}")
            except Exception as e:
                st.error(f"❌ ពិនិត្យ Payment មិនបាន: {e}")

if st.session_state.premium_until:
    if st.session_state.premium_until > datetime.now(timezone.utc):
        st.success(
            "👑 Premium Active — ដល់ "
            + st.session_state.premium_until.strftime("%Y-%m-%d %H:%M UTC")
        )
    else:
        st.warning("Premium បានផុតកំណត់។")


# =========================================================
# GEMINI
# =========================================================

api_key = get_secret("GEMINI_API_KEY")
if not api_key:
    st.warning("សូមដាក់ GEMINI_API_KEY ក្នុង Streamlit Secrets។")
    st.stop()

client = genai.Client(api_key=api_key)

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

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)

premium_active = (
    st.session_state.premium_until is not None
    and st.session_state.premium_until > datetime.now(timezone.utc)
)

if not premium_active:
    st.info("🔒 សូមទិញ Premium ដើម្បីប្រើ Auto Caption។")
else:
    if video is not None and st.button(
        "⚡ បង្កើត Caption",
        use_container_width=True,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "input.mp4")
            audio_path = os.path.join(temp_dir, "audio.wav")
            ass_path = os.path.join(temp_dir, "caption.ass")
            output_path = os.path.join(temp_dir, "smey_auto_caption.mp4")

            with open(video_path, "wb") as f:
                f.write(video.getbuffer())

            try:
                with st.spinner("⚡ កំពុងដកសំឡេង..."):
                    extract_audio(video_path, audio_path)

                with st.spinner("🎙️ Gemini កំពុងស្តាប់សំឡេង..."):
                    audio_file = client.files.upload(file=audio_path)

                    language_code_map = {
                        "🇰🇭 ខ្មែរ": "km-KH",
                        "🇬🇧 English": "en-US",
                        "🇨🇳 中文": "zh-CN",
                        "🇻🇳 Tiếng Việt": "vi-VN",
                        "🇰🇷 한국어": "ko-KR",
                        "🇯🇵 日本語": "ja-JP",
                    }
                    language_hint = language_code_map.get(
                        source_language, "detect automatically"
                    )

                    prompt = f"""
Transcribe this audio accurately.
Language: {language_hint}

Return ONLY valid JSON as an array.
Each item must contain:
start: number of seconds
end: number of seconds
text: exact spoken words

Make short natural subtitle segments around 2 seconds.
Do not translate. Do not add explanations.
"""
                    response = client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=[
                            types.Part.from_uri(
                                file_uri=audio_file.uri,
                                mime_type=audio_file.mime_type,
                            ),
                            prompt,
                        ],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=list[dict[str, object]],
                        ),
                    )

                    groups = make_groups(response.parsed)
                    if not groups:
                        st.error("❌ Gemini មិនបានរក Caption timestamps ទេ។")
                        st.stop()

                if target_language != "មិនបកប្រែ":
                    with st.spinner("🌐 Gemini កំពុងបកប្រែ Caption..."):
                        groups = translate_captions(
                            client, groups, source_language, target_language
                        )

                create_ass(groups, ass_path)

                with st.spinner("🎬 កំពុងដាក់ Caption ក្នុងវីដេអូ..."):
                    burn_caption(video_path, ass_path, output_path)

                with open(output_path, "rb") as f:
                    output_data = f.read()

                st.success("✅ វីដេអូរួចរាល់!")
                st.video(output_data)
                st.download_button(
                    "⬇️ ទាញយកវីដេអូ MP4",
                    data=output_data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )

            except Exception as e:
                st.error("❌ មានបញ្ហាពេលបង្កើតវីដេអូ")
                st.exception(e)
