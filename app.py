import os,re,json,time,tempfile,subprocess,urllib.request
import streamlit as st
from gtts import gTTS
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="🇰🇭 Smey Auto Caption",page_icon="🇰🇭")
st.title("🇰🇭 Smey Auto Caption")
st.caption("Auto Caption • Translate • Free Voice • APK")

TRANSCRIBE="gemini-3.5-transcribe"
TRANSLATE="gemini-3.1-flash-lite"

def key():
    try:return str(st.secrets.get("GEMINI_API_KEY","") or "").strip()
    except:return ""

def apk_pw():
    try:return str(st.secrets.get("APK_ADMIN_PASSWORD","") or "").strip()
    except:return ""

def client():
    return genai.Client(api_key=key())

def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()

def val(x,n,d=None):
    return x.get(n,d) if isinstance(x,dict) else getattr(x,n,d)

def retry(fn):
    for i in range(4):
        try:return fn()
        except Exception as e:
            if i==3:raise
            if any(x in str(e).lower() for x in ["429","500","502","503","504","unavailable"]):
                time.sleep(2**i)
            else:raise

def seconds(x):
    try:return float(str(x).replace("s",""))
    except:return 0

def words_from(r):
    out=[]
    def add(w):
        text=val(w,"word",val(w,"text",""))
        if not text:return
        s=val(w,"start_offset",val(w,"start_time",val(w,"start",0)))
        e=val(w,"end_offset",val(w,"end_time",val(w,"end",s)))
        out.append({"text":str(text),"start":seconds(s),"end":seconds(e)})
    for c in val(r,"candidates",[]) or []:
        for p in val(val(c,"content"),"parts",[]) or []:
            t=val(p,"audio_transcription")
            for w in val(t,"words",[]) or []:add(w)
    t=val(r,"audio_transcription")
    for w in val(t,"words",[]) or []:add(w)
    for w in val(r,"words",[]) or []:add(w)
    return out

def groups(words):
    out=[];cur=[]
    for w in words:
        if not cur:cur=[w];continue
        if len(cur)>=12 or w["end"]-cur[0]["start"]>=5:
            out.append(cur);cur=[w]
        else:cur.append(w)
    if cur:out.append(cur)
    return [{"text":" ".join(x["text"] for x in g),
             "start":g[0]["start"],"end":g[-1]["end"]} for g in out]

def transcribe(c,audio,lang):
    with open(audio,"rb") as f:data=f.read()
    kw={"word_timestamp":True}
    if lang=="Khmer":kw["language_codes"]=["km-KH"]
    if lang=="Chinese":kw["language_codes"]=["cmn-Hans-CN"]
    cfg=types.AudioTranscriptionConfig(**kw)
    return retry(lambda:c.models.generate_content(
        model=TRANSCRIBE,
        contents=[
            types.Part.from_bytes(data=data,mime_type="audio/wav"),
            "Transcribe exactly. Return accurate word-level timestamps. Do not translate."
        ],
        config=types.GenerateContentConfig(
            audio_transcription_config=cfg
        )
    ))

def translate(c,items,lang):
    if lang=="No translation":return items
    out=[]
    for i in range(0,len(items),15):
        batch=items[i:i+15]
        prompt=f"""Translate each subtitle line into {lang}.
Return JSON array only, same order.
Input:
{[x["text"] for x in batch]}"""
        schema=types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING)
        )
        try:
            r=retry(lambda:c.models.generate_content(
                model=TRANSLATE,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            ))
            v=val(r,"parsed")
            if not isinstance(v,list):v=json.loads(val(r,"text","[]"))
            if len(v)!=len(batch):raise ValueError()
        except:
            v=[x["text"] for x in batch]
        for j,x in enumerate(batch):
            out.append({"text":str(v[j]),"start":x["start"],"end":x["end"]})
    return out

def ass_time(x):
    x=max(0,float(x))
    return f"{int(x//3600)}:{int(x%3600//60):02d}:{x%60:05.2f}"

FONT_DIR=os.path.join(os.path.dirname(__file__),"fonts")
FONT=os.path.join(FONT_DIR,"NotoSansKhmer-Regular.ttf")
FONT_URL="https://raw.githubusercontent.com/ghostlypi/NotoSans/main/NotoSansKhmer-Regular.ttf"

def font():
    os.makedirs(FONT_DIR,exist_ok=True)
    if not os.path.isfile(FONT):
        urllib.request.urlretrieve(FONT_URL,FONT)
    return FONT

def make_ass(items,path):
    font()
    h="""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    with open(path,"w",encoding="utf-8-sig") as f:
        f.write(h)
        for x in items:
            t=x["text"].replace("\\","\\\\").replace("{","\\{").replace("}","\\}")
            f.write(f'Dialogue: 0,{ass_time(x["start"])},{ass_time(x["end"])},Default,,0,0,0,,{t}\n')

def burn(video,ass,out):
    d=FONT_DIR.replace("\\","/")
    a=ass.replace("\\","/")
    cmd=[
        ffmpeg(),"-y","-i",video,
        "-vf",f"ass=filename='{a}':fontsdir='{d}':shaping=complex",
        "-map","0:v:0","-map","0:a?","-c:v","libx264",
        "-preset","veryfast","-crf","20","-c:a","copy",
        "-movflags","+faststart",out
    ]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError(r.stderr.decode(errors="ignore")[-3000:])

def extract(video,audio):
    cmd=[ffmpeg(),"-y","-i",video,"-vn","-ac","1","-ar","16000","-f","wav",audio]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError("មិនអាចយកសំឡេងពីវីដេអូបាន")

def download(url,out):
    try:
        import yt_dlp
        opt={
            "outtmpl":out,
            "format":"bv*+ba/b",
            "merge_output_format":"mp4",
            "noplaylist":True,
            "quiet":True,
            "ffmpeg_location":ffmpeg()
        }
        with yt_dlp.YoutubeDL(opt) as y: y.download([url])
        if os.path.isfile(out) and os.path.getsize(out)>0:return
    except:pass

    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=60) as r,open(out,"wb") as f:
        while True:
            b=r.read(1024*1024)
            if not b:break
            f.write(b)

# APK
with st.expander("📱 APK"):
    if st.session_state.get("apk_data"):
        name=st.session_state.get("apk_name","app.apk")
        st.success("📦 "+name)
        st.download_button(
            "⬇️ Download APK",
            st.session_state.apk_data,
            file_name=name,
            mime="application/vnd.android.package-archive",
            use_container_width=True
        )
    else:
        st.info("មិនទាន់មាន APK")

    with st.expander("👑 Admin"):
        pw=st.text_input("🔐 Admin Password",type="password")
        apk=st.file_uploader("📤 Upload APK",type=["apk"])
apk_name=st.text_input(
    "✏️ ឈ្មោះ APK ថ្មី",
    placeholder="ឧ. Smey AI 3.2.1"
)
        if st.button("⬆️ Upload APK",use_container_width=True):
            if not apk_pw():
                st.error("សូមកំណត់ APK_ADMIN_PASSWORD ក្នុង Secrets")
            elif pw!=apk_pw():
                st.error("❌ Password មិនត្រឹមត្រូវ")
            elif not apk:
                st.warning("សូមជ្រើស APK")
            else:
                st.session_state.apk_data=apk.getvalue()
                name=apk_name.strip() or os.path.splitext(apk.name)[0]
name=re.sub(r'[\\/:*?"<>|]','',name).strip()
st.session_state.apk_name=name+".apk"
                st.rerun()

# Download
with st.expander("⬇️ Download Video"):
    url=st.text_input("ដាក់ Link វីដេអូ")
    if st.button("⬇️ Download"):
        if not url.strip():
            st.warning("សូមដាក់ Link")
        else:
            try:
                f=tempfile.NamedTemporaryFile(delete=False,suffix=".mp4")
                f.close()
                with st.spinner("កំពុង Download..."):
                    download(url.strip(),f.name)
                st.video(f.name)
                with open(f.name,"rb") as x:
                    st.download_button(
                        "📥 Download MP4",
                        x,
                        file_name="download.mp4",
                        mime="video/mp4"
                    )
            except Exception as e:
                st.error(f"❌ Download មិនបាន: {e}")

# Free Voice
with st.expander("🎙️ Text → Free Voice"):
    text=st.text_area("បញ្ចូលអត្ថបទ")
    lang=st.selectbox("ភាសា",["Khmer","Chinese","English"])
    lm={"Khmer":"km","Chinese":"zh-CN","English":"en"}

    if st.button("🎙️ Generate Voice"):
        if not text.strip():
            st.warning("សូមបញ្ចូលអត្ថបទ")
        else:
            try:
                f=tempfile.NamedTemporaryFile(delete=False,suffix=".mp3")
                f.close()
                with st.spinner("កំពុងបង្កើតសំឡេង..."):
                    gTTS(text=text,lang=lm[lang],slow=False).save(f.name)
                with open(f.name,"rb") as x:data=x.read()
                st.audio(data,format="audio/mp3")
                st.download_button(
                    "📥 Download Voice",
                    data,
                    file_name="smey_voice.mp3",
                    mime="audio/mpeg"
                )
            except Exception as e:
                st.error(f"❌ Voice Error: {e}")

# Auto Caption
st.divider()
st.subheader("🎬 Auto Caption")

source=st.selectbox(
    "ភាសាសំឡេងដើម",
    ["Auto","Chinese","Khmer"]
)

target=st.selectbox(
    "ភាសា Caption",
    ["Khmer","Chinese","No translation"]
)

video=st.file_uploader(
    "📤 Upload Video",
    type=["mp4","mov","mkv","webm","avi"]
)

if video:
    st.video(video)

if st.button("🚀 Auto Caption",type="primary"):

    if not key():
        st.error("សូមដាក់ GEMINI_API_KEY ក្នុង Secrets")
        st.stop()

    if not video:
        st.warning("សូម Upload Video ជាមុន")
        st.stop()

    tmp=tempfile.mkdtemp()
    inp=os.path.join(tmp,"input.mp4")
    audio=os.path.join(tmp,"audio.wav")
    ass=os.path.join(tmp,"caption.ass")
    out=os.path.join(tmp,"Smey_Auto_Caption.mp4")

    try:
        with open(inp,"wb") as f:
            f.write(video.getbuffer())

        c=client()

        with st.spinner("🎧 កំពុងយកសំឡេង..."):
            extract(inp,audio)

        with st.spinner("📝 កំពុងស្តាប់ និងរក Word Timing..."):
            r=transcribe(
                c,
                audio,
                source if source!="Auto" else None
            )

        w=words_from(r)

        if not w:
            raise RuntimeError("រកមិនឃើញ Word Timing")

        g=groups(w)

        with st.spinner("🔄 កំពុងបកប្រែ Caption..."):
            final=translate(c,g,target)

        with st.spinner("🎞️ កំពុងបង្កើត Caption..."):
            make_ass(final,ass)

        with st.spinner("🔥 កំពុងបញ្ចូល Caption ទៅ MP4..."):
            burn(inp,ass,out)

        st.success("✅ Auto Caption រួចរាល់!")
        st.video(out)

        with open(out,"rb") as f:
            st.download_button(
                "📥 Download MP4",
                f,
                file_name="Smey_Auto_Caption.mp4",
                mime="video/mp4"
            )

    except Exception as e:
        st.error(f"❌ Error: {e}")
