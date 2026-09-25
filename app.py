import os, base64, subprocess, tempfile, wave, json, urllib.request
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="ðŸ‡°ðŸ‡­ Smey AI Dubbing", page_icon="ðŸŽ™ï¸")
st.title("ðŸ‡°ðŸ‡­ Smey AI Dubbing")
st.caption("ðŸŽµ ážšáž€áŸ’ážŸáž¶áž—áŸ’áž›áŸáž„ážŠáž¾áž˜ â€¢ ðŸ”‡ ážŠáž€ážŸáŸ†áž¡áŸáž„áž“áž·áž™áž¶áž™ â€¢ ðŸ‡°ðŸ‡­ áž”áž€áž”áŸ’ážšáŸ‚ážáŸ’áž˜áŸ‚ážš â€¢ ðŸŽ™ï¸ ážŸáŸŠáž¸ Timing")

LANG = {
    "ðŸ‡¨ðŸ‡³ ä¸­æ–‡": ("Chinese", "zh-CN"),
    "ðŸ‡¬ðŸ‡§ English": ("English", "en-US"),
    "ðŸ‡»ðŸ‡³ Tiáº¿ng Viá»‡t": ("Vietnamese", "vi-VN"),
    "ðŸ‡°ðŸ‡· í•œêµ­ì–´": ("Korean", "ko-KR"),
    "ðŸ‡¯ðŸ‡µ æ—¥æœ¬èªž": ("Japanese", "ja-JP"),
    "ðŸ‡°ðŸ‡­ ážáŸ’áž˜áŸ‚ážš": ("Khmer", "km-KH"),
}
VOICES = {
    "Kore â€” Firm": "Kore", "Puck â€” Upbeat": "Puck",
    "Charon â€” Informative": "Charon", "Fenrir â€” Excitable": "Fenrir",
    "Leda â€” Youthful": "Leda", "Aoede â€” Breezy": "Aoede",
}

def ff(a):
    e = imageio_ffmpeg.get_ffmpeg_exe()
    p = subprocess.run([e, "-hide_banner", "-loglevel", "error", "-nostdin"] + a,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="ignore")[-3000:])

def sec(x):
    try: return float(str(x).replace("s", ""))
    except: return 0.0

def get_words(r):
    return [a for s in getattr(r,"steps",[]) or []
              for c in getattr(s,"content",[]) or []
              for a in getattr(c,"annotations",[]) or []
              if getattr(a,"type",None)=="word_info"]

def make_groups(ws):
    out=[]; cur=[]; start=end=None
    for w in ws:
        t=str(getattr(w,"text","") or "").strip()
        if not t: continue
        s,e=sec(getattr(w,"start_offset","")),sec(getattr(w,"end_offset",""))
        if start is None: start=s
        cur.append(t); end=e
        if len(cur)>=6 or e-start>=2.5:
            out.append([start,end," ".join(cur)]); cur=[]; start=end=None
    if cur: out.append([start,end," ".join(cur)])
    return out

def translate_khmer(client, gs, source):
    if source == "ðŸ‡°ðŸ‡­ ážáŸ’áž˜áŸ‚ážš": return gs
    p = f"""Translate the following spoken dialogue from {LANG[source][0]} into natural spoken Khmer.
Keep the exact meaning. Do not add information. Do not summarize.
Return ONLY a JSON array, exactly one Khmer sentence/string per input, same order.

"""
    p += "\n".join(f"{i+1}. {g[2]}" for i,g in enumerate(gs))
    r = client.models.generate_content(
        model="gemini-3.6-flash", contents=p,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[str]))
    if not r.parsed or len(r.parsed) != len(gs):
        raise ValueError("áž€áž¶ážšáž”áž€áž”áŸ’ážšáŸ‚áž˜áž·áž“ážáŸ’ážšáž¼ážœáž…áŸ†áž“áž½áž“áž‘áŸ")
    return [[g[0],g[1],str(t).strip()] for g,t in zip(gs,r.parsed)]

def khmer_tts(text,out):
    data=json.dumps({"text":text,"voice":"sovann"}).encode()
    req=urllib.request.Request(
        "https://doslarb.cloud/api/v1/tts", data=data,
        headers={"Authorization":f"Bearer {st.secrets['DOSLARB_API_KEY']}",
                 "Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req,timeout=60) as r: b=r.read()
    mp3=out.replace(".wav",".mp3")
    open(mp3,"wb").write(b)
    ff(["-y","-i",mp3,"-ar","24000","-ac","1","-c:a","pcm_s16le",out])
    os.remove(mp3)

def gemini_tts(client,text,out,voice):
    p=f"""Speak ONLY this Khmer dialogue naturally and clearly.
Do not add words. Do not explain anything.
Dialogue:
{text}"""
    r=client.interactions.create(
        model="gemini-3.1-flash-tts-preview", input=p,
        response_format={"type":"audio"},
        generation_config={"speech_config":[{"voice":voice}]})
    b=base64.b64decode(r.output_audio.data)
    with wave.open(out,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b)

def fit_wav(src,dst,duration):
    # Force generated speech to fit the original dialogue window.
    if duration <= 0: raise ValueError("Bad timing")
    ff(["-y","-i",src,"-af",
        f"apad,atrim=0:{duration},asetpts=N/SR/TB",
        "-ar","24000","-ac","1","-c:a","pcm_s16le",dst])

def separate_audio(video, vocal, music):
    # Requires demucs in requirements.txt.
    import subprocess
    p=subprocess.run(
        ["python","-m","demucs","--two-stems=vocals","-n","htdemucs",
         "-o",os.path.dirname(vocal),video],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError("Demucs áž˜áž·áž“áž¢áž¶áž…áž”áŸ†áž”áŸ‚áž€ Voice/Music áž”áž¶áž“áŸ”")
    base=os.path.splitext(os.path.basename(video))[0]
    root=os.path.join(os.path.dirname(vocal),"htdemucs","htdemucs",base)
    vv=os.path.join(root,"vocals.wav")
    aa=os.path.join(root,"no_vocals.wav")
    if not os.path.exists(vv) or not os.path.exists(aa):
        raise RuntimeError("ážšáž€áž¯áž€ážŸáž¶ážš Music/Voice áž˜áž·áž“ážƒáž¾áž‰")
    import shutil
    shutil.copy(vv,vocal); shutil.copy(aa,music)

def build_dub(client,gs,tmp,voice):
    parts=[]
    for i,(s,e,text) in enumerate(gs):
        raw=os.path.join(tmp,f"raw{i}.wav")
        fit=os.path.join(tmp,f"fit{i}.wav")
        khmer_tts(text,raw) if voice=="Sovann" else gemini_tts(client,text,raw,voice)
        fit_wav(raw,fit,max(0.15,e-s))
        parts.append((fit,s))
    ins=[]; fl=[]
    for i,(p,s) in enumerate(parts):
        ins += ["-i",p]
        fl.append(f"[{i}:a]adelay={max(0,int(s*1000))}:all=1[a{i}]")
    labels="".join(f"[a{i}]" for i in range(len(parts)))
    fl.append(f"{labels}amix=inputs={len(parts)}:duration=longest:normalize=0[out]")
    out=os.path.join(tmp,"dub.m4a")
    ff(ins+["-filter_complex",";".join(fl),"-map","[out]",
            "-ar","48000","-ac","2","-c:a","aac","-b:a","192k","-y",out])
    return out

def final_mix(video,music,dub,out):
    # Music remains; generated Khmer voice is placed over it.
    ff(["-y","-i",music,"-i",dub,
        "-filter_complex","[0:a]volume=0.95[m];[1:a]volume=1.0[v];[m][v]amix=inputs=2:duration=first:dropout_transition=0[out]",
        "-map","0:v:0","-map","[out]","-c:v","copy","-c:a","aac","-b:a","192k",
        "-movflags","+faststart",out])

source=st.selectbox("ðŸŒ áž—áž¶ážŸáž¶ážŠáž¾áž˜",list(LANG.keys()))
voice_label=st.selectbox("ðŸŽ¤ ážŸáž˜áŸ’áž›áŸáž„ážáŸ’áž˜áŸ‚ážš",list(VOICES.keys()))
video=st.file_uploader("ðŸŽ¥ áž‡áŸ’ážšáž¾ážŸážœáž¸ážŠáŸáž¢áž¼",type=["mp4","mov","mkv","webm"])

if video and st.button("ðŸŽ™ï¸ DUBBING â†’ ážáŸ’áž˜áŸ‚ážš",use_container_width=True):
    with tempfile.TemporaryDirectory() as tmp:
        inp=os.path.join(tmp,"input.mp4")
        wav=os.path.join(tmp,"audio.wav")
        vocals=os.path.join(tmp,"vocals.wav")
        music=os.path.join(tmp,"music.wav")
        open(inp,"wb").write(video.getbuffer())
        try:
            client=genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

            with st.spinner("ðŸŽ™ï¸ ážŸáŸ’áž‚áž¶áž›áŸ‹ážŸáŸ†áž¡áŸáž„ áž“áž·áž„ Timing..."):
                ff(["-y","-i",inp,"-vn","-ac","1","-ar","16000",
                    "-c:a","pcm_s16le",wav])
                af=client.files.upload(file=wav)
                r=client.interactions.create(
                    model="gemini-3.5-transcribe",
                    input=[{"type":"audio","uri":af.uri,"mime_type":af.mime_type}],
                    generation_config={"transcription_config":{
                        "language_codes":[LANG[source][1]],
                        "mode":{"type":"verbatim","timestamp_granularities":["word"]}}})
                gs=make_groups(get_words(r))
                if not gs: raise ValueError("ážšáž€áž˜áž·áž“ážƒáž¾áž‰ážŸáŸ†áž¡áŸáž„áž“áž·áž™áž¶áž™")

            with st.spinner("ðŸ‡°ðŸ‡­ áž”áž€áž”áŸ’ážšáŸ‚áž‡áž¶ážáŸ’áž˜áŸ‚ážš..."):
                gs=translate_khmer(client,gs,source)

            with st.spinner("ðŸŽµ áž”áŸ†áž”áŸ‚áž€ážŸáŸ†áž¡áŸáž„áž“áž·áž™áž¶áž™áž…áŸáž‰áž–áž¸áž—áŸ’áž›áŸáž„..."):
                separate_audio(inp,vocals,music)

            with st.spinner("ðŸ—£ï¸ áž”áž„áŸ’áž€áž¾ážážŸáŸ†áž¡áŸáž„ážáŸ’áž˜áŸ‚ážš áž“áž·áž„ážŸáŸŠáž¸ Timing..."):
                voice="Sovann" if source=="ðŸ‡°ðŸ‡­ ážáŸ’áž˜áŸ‚ážš" else VOICES[voice_label]
                dub=build_dub(client,gs,tmp,voice)

            with st.spinner("ðŸŽ¬ áž›áž¶áž™áž—áŸ’áž›áŸáž„ážŠáž¾áž˜ + ážŸáŸ†áž¡áŸáž„ážáŸ’áž˜áŸ‚ážš..."):
                out=os.path.join(tmp,"Smey_AI_Dubbing_KH.mp4")
                final_mix(inp,music,dub,out)

            data=open(out,"rb").read()
            st.success("âœ… ážšáž½áž…ážšáž¶áž›áŸ‹ â€” áž—áŸ’áž›áŸáž„áž“áŸ… ážŸáŸ†áž¡áŸáž„áž“áž·áž™áž¶áž™áž”áŸ’ážŠáž¼ážšáž‡áž¶ážáŸ’áž˜áŸ‚ážš")
            st.video(data)
            st.download_button("â¬‡ï¸ áž‘áž¶áž‰áž™áž€ MP4",data=data,
                               file_name="Smey_AI_Dubbing_KH.mp4",
                               mime="video/mp4",use_container_width=True)
        except Exception as e:
            st.error("âŒ Dubbing áž˜áž¶áž“áž”áž‰áŸ’áž áž¶")
            st.exception(e)
