import os, json, subprocess, tempfile, wave, base64, time, urllib.request, urllib.error
import ipaddress
import socket
from urllib.parse import urlparse
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="Smey Auto Caption", page_icon="🇰🇭", layout="centered")

TELEGRAM_URL = "https://t.me/Smeytk"
MAX_DOWNLOAD_MB = 500


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


def gemini_tts(text, out):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore",
                    )
                )
            ),
        ),
    )

    try:
        part = response.candidates[0].content.parts[0]
        audio = part.inline_data
        data = audio.data

        if isinstance(data, str):
            data = base64.b64decode(data)

        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(data)

    except (AttributeError, IndexError, TypeError) as e:
        raise RuntimeError(
            "❌ Gemini មិនបានផ្ញើ Audio មកទេ។ "
            "សូមពិនិត្យ GEMINI_API_KEY និង TTS model access។"
        ) from e


def hf_image(prompt, aspect_ratio="1:1", quality="Low"):
    """Generate an image through Hugging Face Inference Providers."""
    try:
        token = st.secrets["HF_TOKEN"]
    except Exception as e:
        raise RuntimeError(
            "❌ មិនឃើញ HF_TOKEN ក្នុង Streamlit Secrets ទេ។ "
            "សូមបន្ថែម HF_TOKEN មុនប្រើ AI Image។"
        ) from e

    try:
        from huggingface_hub import InferenceClient
    except ImportError as e:
        raise RuntimeError(
            "❌ មិនទាន់ដំឡើង huggingface_hub ទេ។ "
            "សូមដាក់ huggingface_hub ក្នុង requirements.txt។"
        ) from e

    size_map = {
        "1:1": (1024, 1024),
        "9:16": (768, 1365),
        "16:9": (1365, 768),
        "4:3": (1152, 864),
        "3:4": (864, 1152),
    }
    width, height = size_map.get(aspect_ratio, (1024, 1024))

    steps_map = {
        "Low": 4,
        "Medium": 8,
        "High": 12,
    }

    client = InferenceClient(
        provider="fal-ai",
        api_key=token,
    )

    try:
        image = client.text_to_image(
            prompt=prompt,
            model="krea/Krea-2-Turbo",
            width=width,
            height=height,
            num_inference_steps=steps_map.get(quality, 8),
        )
    except Exception as e:
        message = str(e)
        if "401" in message or "403" in message or "token" in message.lower():
            raise RuntimeError(
                "❌ Hugging Face Token មិនត្រឹមត្រូវ ឬមិនមានសិទ្ធិ Inference Providers។"
            ) from e
        if "429" in message or "quota" in message.lower() or "credit" in message.lower():
            raise RuntimeError(
                "❌ Hugging Face quota/credits មិនគ្រប់សម្រាប់ Image generation ទេ.\n\n"
                + message
            ) from e
        raise RuntimeError(f"❌ Hugging Face Image API Error: {message}") from e

    from io import BytesIO
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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

        gemini_tts(g["text"], raw)
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


# ---------- FREE / AUTHORIZED DIRECT VIDEO DOWNLOADER ----------

def validate_download_url(url):
    """Allow only normal public HTTP/HTTPS URLs; do not bypass protected streams."""
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise RuntimeError("❌ URL ត្រូវចាប់ផ្តើមដោយ http:// ឬ https://")

    if not parsed.hostname:
        raise RuntimeError("❌ URL មិនត្រឹមត្រូវ។")

    if parsed.port and parsed.port not in (80, 443):
        raise RuntimeError("❌ អនុញ្ញាតតែ Port 80/443។")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except Exception as e:
        raise RuntimeError("❌ មិនអាចស្វែងរក Server របស់ Website នេះបាន។") from e

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise RuntimeError("❌ URL នេះមិនអាចប្រើសម្រាប់ Download បានទេ។")

    return url.strip()


def download_direct_video(url, output_path):
    url = validate_download_url(url)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 SmeyAutoCaption/1.0",
            "Accept": "video/mp4,video/*,application/octet-stream;q=0.9,*/*;q=0.5",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    size = int(content_length)
                    if size > MAX_DOWNLOAD_MB * 1024 * 1024:
                        raise RuntimeError(
                            f"❌ វីដេអូធំជាង {MAX_DOWNLOAD_MB}MB។"
                        )
                except ValueError:
                    pass

            if (
                "text/html" in content_type
                and not url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".mkv"))
            ):
                raise RuntimeError(
                    "❌ Link នេះជាទំព័រ Website មិនមែនជា Direct Video File ទេ។\n"
                    "សូមប្រើ Link ដែល Website អនុញ្ញាតឱ្យ Download ជា MP4/WebM/MOV។"
                )

            total = 0
            chunk_size = 1024 * 1024

            with open(output_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    total += len(chunk)
                    if total > MAX_DOWNLOAD_MB * 1024 * 1024:
                        raise RuntimeError(
                            f"❌ វីដេអូលើស {MAX_DOWNLOAD_MB}MB។"
                        )

                    f.write(chunk)

    except urllib.error.HTTPError as e:
        raise RuntimeError(f"❌ Website បដិសេធ Download: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"❌ មិនអាចភ្ជាប់ទៅ Website បាន: {e.reason}") from e

    if total < 1000:
        raise RuntimeError("❌ File ដែលបានទាញយកតូចពេក ឬមិនមែនវីដេអូ។")

    # Verify that FFmpeg can read the downloaded file.
    try:
        ffmpeg([
            "-v", "error",
            "-i", output_path,
            "-f", "null",
            "-",
        ])
    except Exception as e:
        raise RuntimeError(
            "❌ File ដែលបាន Download មិនមែនជា Video ដែលអាចអានបាន។ "
            "វាអាចជា webpage ឬ protected stream។"
        ) from e

    return total


# ---------- UI ----------
st.title("🇰🇭 Smey Auto Caption")
st.caption("🇨🇳 Chinese → Auto Caption → Khmer → Gemini Voice → Auto Sync → MP4")

st.link_button(
    "📱 ទាក់ទងម្ចាស់តាម Telegram",
    TELEGRAM_URL,
    use_container_width=True,
)

# ---------- VIDEO DOWNLOADER ----------
with st.expander("🎬 Download រឿង/វីដេអូពី Website", expanded=False):
    st.caption(
        "សម្រាប់ Direct Video Link ដែល Website អនុញ្ញាតឱ្យ Download "
        "(MP4 / WebM / MOV / file video)។ មិនរំលងការការពារ ឬ DRM ទេ។"
    )

    download_url = st.text_input(
        "🔗 បញ្ចូល Video Download Link",
        placeholder="https://example.com/video.mp4",
        key="download_video_url",
    )

    if st.button("⬇️ Download Video", use_container_width=True):
        if not download_url.strip():
            st.warning("សូមបញ្ចូល Video Link ជាមុន។")
        else:
            try:
                with tempfile.TemporaryDirectory() as dl_tmp:
                    downloaded = os.path.join(dl_tmp, "smey_download.mp4")

                    progress = st.progress(0, text="⬇️ កំពុង Download...")
                    size = download_direct_video(download_url, downloaded)
                    progress.progress(100, text="✅ Download រួចរាល់")

                    data = open(downloaded, "rb").read()

                    st.success(
                        f"✅ បាន Download រួច — {size / (1024 * 1024):.1f} MB"
                    )
                    st.video(data)

                    st.download_button(
                        "⬇️ ទាញយក MP4",
                        data=data,
                        file_name="smey_download_video.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                    )

            except Exception as e:
                st.error("❌ Download មិនបាន")
                st.warning(str(e))

source = st.selectbox(
    "🌐 ភាសាដើម",
    ["🇨🇳 中文", "🇰🇭 ខ្មែរ", "🇬🇧 English"],
    index=0,
)

translate_to_kh = st.checkbox(
    "🇰🇭 បកប្រែ Caption ទៅខ្មែរ",
    value=True,
)

dub = st.checkbox(
    "🎙️ AI Dubbing — Gemini",
    value=False,
)

st.subheader("🖼️ បង្កើតរូបភាព AI — Hugging Face")
st.caption("Hugging Face Inference Providers • Text → Image")

image_prompt = st.text_area(
    "✍️ សរសេរអ្វីដែលចង់បង្កើតជារូបភាព",
    placeholder="ឧទាហរណ៍៖ ឆ្កែស្ទាវស្លៀកខោអាវខ្មែរឈរនៅវាលស្រែពេលថ្ងៃលិច, 3D cinematic, realistic, beautiful lighting",
    height=120,
    key="image_prompt",
)

img_c1, img_c2 = st.columns(2)
with img_c1:
    image_ratio = st.selectbox(
        "📐 សមាមាត្រ",
        ["1:1", "9:16", "16:9", "4:3", "3:4"],
        index=0,
        key="image_ratio",
    )
with img_c2:
    image_quality = st.selectbox(
        "✨ គុណភាព",
        ["Low", "Medium", "High"],
        index=0,
        key="image_quality",
    )

if st.button("🎨 បង្កើតរូបភាព AI", use_container_width=True):
    if not image_prompt.strip():
        st.warning("សូមសរសេរ Prompt ជាមុន។")
    else:
        try:
            with st.spinner("🎨 AI កំពុងបង្កើតរូបភាព..."):
                image_data = hf_image(
                    image_prompt.strip(),
                    aspect_ratio=image_ratio,
                    quality=image_quality,
                )

            st.image(image_data, use_container_width=True)
            st.download_button(
                "⬇️ ទាញយករូបភាព",
                data=image_data,
                file_name="smey_ai_image.png",
                mime="image/png",
                use_container_width=True,
            )
        except Exception as e:
            st.error("❌ បង្កើតរូបភាពមិនបាន")
            st.warning(str(e))

st.subheader("🗣️ អក្សរ → សំឡេង Gemini")

tts_text = st.text_area(
    "✍️ សរសេរអត្ថបទ",
    placeholder="សរសេរអត្ថបទខ្មែរនៅទីនេះ...",
    height=100,
)

if st.button("🔊 បង្កើតសំឡេង Gemini", use_container_width=True):
    if not tts_text.strip():
        st.warning("សូមសរសេរអត្ថបទជាមុន។")
    else:
        try:
            with tempfile.TemporaryDirectory() as t:
                audio_path = os.path.join(t, "gemini_tts.wav")
                with st.spinner("🔊 កំពុងបង្កើតសំឡេង..."):
                    gemini_tts(tts_text.strip(), audio_path)

                audio_data = open(audio_path, "rb").read()
                st.audio(audio_data, format="audio/wav")
                st.download_button(
                    "⬇️ ទាញយកសំឡេង",
                    data=audio_data,
                    file_name="gemini_tts.wav",
                    mime="audio/wav",
                    use_container_width=True,
                )
        except Exception as e:
            st.error("❌ បង្កើតសំឡេងមិនបាន")
            st.exception(e)

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
                    codes = (
                        ["zh-CN"] if source == "🇨🇳 中文"
                        else ["km-KH"] if source == "🇰🇭 ខ្មែរ"
                        else ["en-US"]
                    )

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

                if source in ("🇨🇳 中文", "🇬🇧 English") and (translate_to_kh or dub):
                    label = "ចិន → ខ្មែរ" if source == "🇨🇳 中文" else "អង់គ្លេស → ខ្មែរ"
                    with st.spinner(f"🌐 កំពុងបកប្រែ {label}..."):
                        groups = translate(groups, client)

                if caption_btn:
                    make_ass(groups, ass)
                    with st.spinner("🎬 កំពុងដាក់ Caption..."):
                        burn(vp, ass, out)
                else:
                    with st.spinner("🔊 កំពុងបង្កើតសំឡេង Gemini + Auto Sync..."):
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
