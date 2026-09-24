import os,re,json,tempfile,subprocess,urllib.request
import streamlit as st
from gtts import gTTS
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="🇰🇭 Smey Auto Caption",page_icon="🇰🇭")
st.title("🇰🇭 Smey Auto Caption")

T_MODEL="gemini-3.5-transcribe"
L_MODEL="gemini-3.1-flash-lite"

def ff():
    return imageio_ffmpeg.get_ffmpeg_exe()

def secret(name):
    try:return str(st.secrets.get(name,"") or "").strip()
    except:return ""

def client():
    return genai.Client(api_key=secret("GEMINI_API_KEY"))

def val(x,k,d=None):
    return x.get(k,d) if isinstance(x,dict) else getattr(x,k,d)

def num(x):
    try:return float(str(x).replace("s",""))
    except:return 0

def transcribe(c,path,lang):
    with open(path,"rb") as f:data=f.read()
    kw={"word_timestamp":True}
    if lang=="Khmer":kw["language_codes"]=["km-KH"]
    if lang=="Chinese":kw["language_codes"]=["cmn-Hans-CN"]
    cfg=types.AudioTranscriptionConfig(**kw)
    return c.models.generate_content(
        model=T_MODEL,
        contents=[
            types.Part.from_bytes(data=data,mime_type="audio/wav"),
            "Transcribe exactly. Return accurate word-level timestamps."
        ],
        config=types.GenerateContentConfig(
            audio_transcription_config=cfg
        )
    )

def get_words(r):
    out=[]
    def add(w):
        t=val(w,"word",val(w,"text",""))
        if not t:return
        s=val(w,"start_offset",val(w,"start_time",val(w,"start",0)))
        e=val(w,"end_offset",val(w,"end_time",val(w,"end",s)))
        out.append({"text":str(t),"s":num(s),"e":num(e)})
    for c in val(r,"candidates",[]) or []:
        for p in val(val(c,"content"),"parts",[]) or []:
            for w in val(val(p,"audio_transcription"),"words",[]) or []:add(w)
    for w in val(val(r,"audio_transcription"),"words",[]) or []:add(w)
    return out

def make_groups(words):
    out=[];cur=[]
    for w in words:
        if cur and (len(cur)>=12 or w["e"]-cur[0]["s"]>=5):
            out.append(cur);cur=[]
        cur.append(w)
    if cur:out.append(cur)
    return [
        {"text":" ".join(w["text"] for w in g),
         "s":g[0]["s"],"e":g[-1]["e"]}
        for g in out
    ]

def translate(c,groups,lang):
    if lang=="No translation":return groups
    out=[]
    for i in range(0,len(groups),15):
        b=groups[i:i+15]
        prompt=f"Translate each line to {lang}. Return JSON array only, same order:\n{[x['text'] for x in b]}"
        schema=types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING)
        )
        try:
            r=c.models.generate_content(
                model=L_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            )
            v=val(r,"parsed")
            if not isinstance(v,list):
                v=json.loads(val(r,"text","[]"))
            if len(v)!=len(b):raise ValueError()
        except:
            v=[x["text"] for x in b]
        for j,x in enumerate(b):
            out.append({"text":str(v[j]),"s":x["s"],"e":x["e"]})
    return out

def tm(x):
    x=max(0,float(x))
    return f"{int(x//3600)}:{int(x%3600//60):02d}:{x%60:05.2f}"

FONT_DIR="fonts"
FONT="fonts/NotoSansKhmer-Regular.ttf"
FONT_URL="https://raw.githubusercontent.com/ghostlypi/NotoSans/main/NotoSansKhmer-Regular.ttf"

def make_ass(groups,path):
    os.makedirs(FONT_DIR,exist_ok=True)
    if not os.path.exists(FONT):
        urllib.request.urlretrieve(FONT_URL,FONT)
    head="""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: D,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    with open(path,"w",encoding="utf-8-sig") as f:
        f.write(head)
        for x in groups:
            t=x["text"].replace("\\","\\\\").replace("{","\\{").replace("}","\\}")
            f.write(f"Dialogue: 0,{tm(x['s'])},{tm(x['e'])},D,,0,0,0,,{t}\n")

def caption(video,ass,out):
    cmd=[
        ff(),"-y","-i",video,
        "-vf",f"ass={ass}:fontsdir={FONT_DIR}",
        "-c:v","libx264","-preset","veryfast","-crf","20",
        "-c:a","copy","-movflags","+faststart",out
    ]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-2000:])

def audio(video,out):
    r=subprocess.run([
        ff(),"-y","-i",video,"-vn","-ac","1","-ar","16000","-f","wav",out
    ],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError("មិនអាចយកសំឡេងបាន")

# APK
with st.expander("📱 APK"):
    if st.session_state.get("apk"):
        name=st.session_state.get("apk_name","app.apk")
        st.download_button(
            "⬇️ Download APK",
            st.session_state.apk,
            file_name=name,
            mime="application/vnd.android.package-archive"
        )
    else:
        st.info("មិនទាន់មាន APK")

    with st.expander("👑 Admin"):
        pw=st.text_input("🔐 Password",type="password")
        apk=st.file_uploader("📤 Upload APK",type=["apk"])
        new_name=st.text_input("✏️ ឈ្មោះ APK")

        if st.button("⬆️ Upload APK"):
            if pw!=secret("APK_ADMIN_PASSWORD"):
                st.error("❌ Password ខុស")
            elif not apk:
                st.warning("សូមជ្រើស APK")
            else:
                name=new_name.strip() or os.path.splitext(apk.name)[0]
                name=re.sub(r'[\\/:*?"<>|]','',name)+".apk"
                st.session_state.apk=apk.getvalue()
                st.session_state.apk_name=name
                st.rerun()

# Free Voice
with st.expander("🎙️ Free Voice"):
    text=st.text_area("បញ្ចូលអត្ថបទ")
    lang=st.selectbox("ភាសា",["Khmer","Chinese","English"])

    if st.button("🎙️ Generate Voice"):
        if not text.strip():
            st.warning("សូមបញ្ចូលអត្ថបទ")
        else:
            code={"Khmer":"km","Chinese":"zh-CN","English":"en"}[lang]
            f=tempfile.NamedTemporaryFile(delete=False,suffix=".mp3")
            f.close()
            gTTS(text=text,lang=code).save(f.name)
            with open(f.name,"rb") as x:data=x.read()
            st.audio(data)
            st.download_button(
                "📥 Download Voice",
                data,
                file_name="smey_voice.mp3"
            )

# Download Video
with st.expander("⬇️ Download Video"):
    url=st.text_input("ដាក់ Link វីដេអូ")
    if st.button("⬇️ Download"):
        try:
            import yt_dlp
            f=tempfile.NamedTemporaryFile(delete=False,suffix=".mp4")
            f.close()
            with yt_dlp.YoutubeDL({
                "outtmpl":f.name,
                "format":"bv*+ba/b",
                "merge_output_format":"mp4",
                "noplaylist":True,
                "quiet":True,
                "ffmpeg_location":ff()
            }) as y:
                y.download([url])
            st.video(f.name)
            with open(f.name,"rb") as x:
                st.download_button("📥 Download MP4",x,file_name="video.mp4")
        except Exception as e:
            st.error(f"❌ {e}")

# Auto Caption
st.subheader("🎬 Auto Caption")

source=st.selectbox(
    "ភាសាសំឡេង",
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
    if not secret("GEMINI_API_KEY"):
        st.error("សូមដាក់ GEMINI_API_KEY ក្នុង Secrets")
        st.stop()

    if not video:
        st.warning("សូម Upload Video")
        st.stop()

    tmp=tempfile.mkdtemp()
    inp=os.path.join(tmp,"input.mp4")
    wav=os.path.join(tmp,"audio.wav")
    ass=os.path.join(tmp,"caption.ass")
    out=os.path.join(tmp,"Smey_Auto_Caption.mp4")

    try:
        with open(inp,"wb") as f:
            f.write(video.getbuffer())

        c=client()

        with st.spinner("🎧 កំពុងយកសំឡេង..."):
            audio(inp,wav)

        with st.spinner("📝 កំពុងស្តាប់..."):
            r=transcribe(
                c,wav,
                source if source!="Auto" else None
            )

        words=get_words(r)

        if not words:
            raise RuntimeError("រកមិនឃើញ Word Timing")

        g=make_groups(words)

        with st.spinner("🔄 កំពុងបកប្រែ..."):
            g=translate(c,g,target)

        with st.spinner("🔥 កំពុងបញ្ចូល Caption..."):
            make_ass(g,ass)
            caption(inp,ass,out)

        st.success("✅ រួចរាល់!")
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
