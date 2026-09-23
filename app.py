import os, json, time, subprocess, tempfile, urllib.request, urllib.error, wave
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="Smey Auto Caption", page_icon="🇰🇭", layout="centered")

TELEGRAM_URL = "https://t.me/Smeytk"

def ffmpeg(args):
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe()] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

def sec(v):
    try:
        return float(str(v).replace("s", ""))
    except Exception:
        return 0.0

def words_from(interaction):
    out = []
    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for a in getattr(content, "annotations", []) or []:
                if getattr(a, "type", None) == "word_info":
                    out.append(a)
    return out

def groups_from(words, max_words=10, max_seconds=4.0):
    groups, cur = [], []
    start = end = None
    for w in words:
        text = str(getattr(w, "text", "") or "").strip()
        if not text:
            continue
        s = sec(getattr(w, "start_offset", ""))
        e = sec(getattr(w, "end_offset", ""))
        if start is None:
            start = s
        cur.append(text)
        end = e
        if len(cur) >= max_words or end - start >= max_seconds:
            groups.append({"start": start, "end": end, "text": " ".join(cur)})
            cur, start, end = [], None, None
    if cur:
        groups.append({"start": start, "end": end, "text": " ".join(cur)})
    return groups

def translate(groups, client):
    if not groups:
        return groups

    texts = [g["text"] for g in groups]
    result = []

    for start in range(0, len(texts), 10):
        batch = texts[start:start + 10]
        prompt = (
            "Translate these Chinese video captions to natural Khmer. "
            "Return ONLY a JSON array with exactly one Khmer string for each input, "
            "same order. Do not explain, number, merge, or add text.\n\n"
            + "\n".join(f"{i+1}. {x}" for i, x in enumerate(batch))
        )

        answer = None
        for attempt in range(4):
            try:
                r = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=list[str],
                    ),
                )
                if r.parsed and len(r.parsed) == len(batch):
                    answer = [str(x).strip() for x in r.parsed]
                    break
            except Exception as e:
                if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                    raise
                time.sleep(16 if attempt == 0 else 8)

        if answer is None:
            answer = []
            for x in batch:
                for attempt in range(3):
                    try:
                        r = client.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents=f"Translate to Khmer. Return only the Khmer sentence.\n{x}",
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=str,
                            ),
                        )
                        answer.append(str(r.parsed or x).strip())
                        break
                    except Exception as e:
                        if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                            raise
                        time.sleep(16)

        result.extend(answer)

    return [{**g, "text": t} for g, t in zip(groups, result)]

def doslarb_tts(text, out):
    key = str(st.secrets.get("DOSLARB_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("❌ ខ្វះ DOSLARB_API_KEY ក្នុង Streamlit Secrets។")

    if len(text) > 1200:
        text = text[:1200]

    last = st.session_state.get("dos_last", 0.0)
    wait = 6.3 - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)

    data = json.dumps(
        {"text": text, "voice": "sovann"},
        ensure_ascii=False
    ).encode()

    for attempt in range(5):
        req = urllib.request.Request(
            "https://doslarb.cloud/api/v1/tts",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "User-Agent": "Mozilla/5.0",
            },
        )
        st.session_state["dos_last"] = time.monotonic()

        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                mp3 = r.read()
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429:
                if attempt == 4:
                    raise RuntimeError("❌ Doslarb 429: ដល់ rate limit បណ្ដោះអាសន្ន។ សូមសាកម្ដងទៀត។")
                time.sleep(max(8, float(e.headers.get("Retry-After", "0") or 0), 8 * (attempt + 1)))
                continue
            raise RuntimeError(f"❌ Doslarb Error {e.code}: {body}")

    mp3path = out[:-4] + ".mp3"
    open(mp3path, "wb").write(mp3)
    ffmpeg(["-y", "-i", mp3path, "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", out])
    os.remove(mp3path)

def duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()

def sync_clip(src, dst, slot):
    d = max(duration(src), 0.05)
    slot = max(slot, 0.15)

    if d > slot:
        factor = d / slot
        filters = []
        while factor > 2:
            filters.append("atempo=2")
            factor /= 2
        filters.append(f"atempo={max(0.5, factor):.6f}")
        filters.append(f"atrim=duration={slot:.3f}")
        f = ",".join(filters)
    else:
        f = f"apad=pad_dur={slot-d:.3f},atrim=duration={slot:.3f}"

    ffmpeg(["-y", "-i", src, "-af", f, "-ar", "24000", "-ac", "1", dst])

def dubbing(groups, out, tmp):
    clips = []

    for i, g in enumerate(groups):
        if not g["text"].strip():
            continue

        raw = os.path.join(tmp, f"raw{i}.wav")
        synced = os.path.join(tmp, f"sync{i}.wav")

        doslarb_tts(g["text"], raw)
        sync_clip(raw, synced, max(0.2, g["end"] - g["start"]))
        clips.append((synced, g["start"]))

    if not clips:
        raise RuntimeError("❌ មិនមានសំឡេងសម្រាប់ Dubbing ទេ។")

    args, filt = [], []

    for i, (p, s) in enumerate(clips):
        args += ["-i", p]
        filt.append(f"[{i}:a]adelay={max(0, int(s * 1000))}:all=1[a{i}]")

    labels = "".join(f"[a{i}]" for i in range(len(clips)))
    filt.append(
        f"{labels}amix=inputs={len(clips)}:duration=longest:"
        "dropout_transition=0:normalize=0[out]"
    )

    ffmpeg(
        args + [
            "-filter_complex", ";".join(filt),
            "-map", "[out]",
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y", out,
        ]
    )

def ass_time(x):
    h = int(x // 3600)
    m = int(x % 3600 // 60)
    s = int(x % 60)
    cs = int((x - int(x)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def make_ass(groups, path):
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
    with open(path, "w", encoding="utf8") as f:
        f.write(header)
        for g in groups:
            t = (
                g["text"]
                .replace("\n", " ")
                .replace("{", r"\{")
                .replace("}", r"\}")
            )
            f.write(
                f"Dialogue: 0,{ass_time(g['start'])},{ass_time(g['end'])},"
                f"Khmer,,0,0,0,,{t}\n"
            )

def burn(video, ass, out):
    a = ass.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    ffmpeg([
        "-y", "-i", video,
        "-vf", f"ass='{a}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        out,
    ])

def replace_audio(video, audio, out):
    ffmpeg([
        "-y", "-i", video, "-i", audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        out,
    ])

# ---------- UI ----------
st.title("🇰🇭 Smey Auto Caption")
st.caption("🇨🇳 Chinese → Auto Caption → Khmer → Sovann → Auto Sync → MP4")

st.link_button(
    "📱 ទាក់ទងម្ចាស់តាម Telegram",
    TELEGRAM_URL,
    use_container_width=True,
)

source = st.selectbox(
    "🌐 ភាសាដើម",
    ["🇨🇳 中文", "Auto Detect"],
    index=0,
)

translate_to_kh = st.checkbox(
    "🇰🇭 បកប្រែ Caption ទៅខ្មែរ",
    value=True,
)

dub = st.checkbox(
    "🎙️ AI Dubbing — Sovann",
    value=False,
)

video = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm"],
)

if video:
    c1, c2 = st.columns(2)
    caption_btn = c1.button("⚡ Auto Caption", use_container_width=True)
    dub_btn = c2.button("🎙️ Dubbing + Sync", use_container_width=True)

    if caption_btn or dub_btn:
        with tempfile.TemporaryDirectory() as tmp:
            vp = os.path.join(tmp, "input.mp4")
            ap = os.path.join(tmp, "audio.wav")
            ass = os.path.join(tmp, "caption.ass")
            out = os.path.join(tmp, "output.mp4")
            da = os.path.join(tmp, "dub.m4a")

            open(vp, "wb").write(video.getbuffer())

            try:
                ffmpeg([
                    "-y", "-i", vp,
                    "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", ap,
                ])

                client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

                with st.spinner("🎙️ កំពុង Auto Caption..."):
                    af = client.files.upload(file=ap)
                    codes = [] if source == "Auto Detect" else ["zh-CN"]

                    it = client.interactions.create(
                        model="gemini-3.5-transcribe",
                        input=[{
                            "type": "audio",
                            "uri": af.uri,
                            "mime_type": af.mime_type,
                        }],
                        generation_config={
                            "transcription_config": {
                                "language_codes": codes,
                                "mode": {
                                    "type": "verbatim",
                                    "timestamp_granularities": ["word"],
                                },
                            }
                        },
                    )

                    groups = groups_from(words_from(it))

                if not groups:
                    raise RuntimeError("❌ មិនរកឃើញ Caption timestamps ទេ។")

                if translate_to_kh or dub:
                    with st.spinner("🌐 កំពុងបកប្រែទៅខ្មែរ..."):
                        groups = translate(groups, client)

                if caption_btn:
                    make_ass(groups, ass)
                    with st.spinner("🎬 កំពុងដាក់ Caption..."):
                        burn(vp, ass, out)
                else:
                    with st.spinner("🔊 កំពុងបង្កើតសំឡេង Sovann + Auto Sync..."):
                        dubbing(groups, da, tmp)
                    replace_audio(vp, da, out)

                data = open(out, "rb").read()

                st.success("✅ រួចរាល់!")
                st.video(data)
                st.download_button(
                    "⬇️ ទាញយក MP4",
                    data=data,
                    file_name="smey_auto_caption.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )

            except Exception as e:
                st.error("❌ មានបញ្ហា")
                st.exception(e)
                        
