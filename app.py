import os,re,json,time,tempfile,subprocess,urllib.request,urllib.parse,urllib.error,wave
import streamlit as st
from gtts import gTTS
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title='ðŸ‡°ðŸ‡­ Smey Auto Caption',page_icon='ðŸ‡°ðŸ‡­')
st.title('ðŸ‡°ðŸ‡­ Smey Auto Caption')
st.caption('Gemini â†’ Caption â†’ Auto Translate â†’ MP4')
st.markdown('ðŸ“© **Telegram:** [@Smeytk](https://t.me/Smeytk)')
TM='gemini-3.5-transcribe'; LM='gemini-3.1-flash-lite'
BASE=os.path.dirname(os.path.abspath(__file__)); FD=os.path.join(BASE,'fonts'); FP=os.path.join(FD,'NotoSansKhmer-Regular.ttf')
FU='https://raw.githubusercontent.com/ghostlypi/NotoSans/main/NotoSansKhmer-Regular.ttf'
ff=lambda:imageio_ffmpeg.get_ffmpeg_exe()
def sec(k):
    try:return str(st.secrets.get(k,'') or '').strip()
    except:return ''
def val(o,k,d=None):return o.get(k,d) if isinstance(o,dict) else getattr(o,k,d)
def retry(fn):
    for i in range(4):
        try:return fn()
        except Exception as e:
            if i==3 or not any(x in str(e).lower() for x in ('429','500','502','503','504','unavailable','resource_exhausted')):raise
            time.sleep(2**i)

def sb(method,path,data=None,ctype='application/json',timeout=180):
    base=sec('SUPABASE_URL').rstrip('/'); key=sec('SUPABASE_SERVICE_KEY')
    if not base or not key:raise RuntimeError('áž€áŸ†ážŽážáŸ‹ SUPABASE_URL áž“áž·áž„ SUPABASE_SERVICE_KEY áž€áŸ’áž“áž»áž„ Secrets')
    h={'apikey':key,'Authorization':f'Bearer {key}'}
    if ctype:h['Content-Type']=ctype
    try:
        with urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=h,method=method),timeout=timeout) as r:return r.read()
    except urllib.error.HTTPError as e:raise RuntimeError(f'Supabase HTTP {e.code}: {e.read().decode(errors="ignore")}')

def apk_list():
    b=json.dumps({'prefix':'','limit':100,'offset':0,'sortBy':{'column':'name','order':'asc'}}).encode()
    x=json.loads(sb('POST','/storage/v1/object/list/apk',b).decode() or '[]')
    return [i['name'] for i in x if i.get('name','').lower().endswith('.apk')]
def apk_upload(name,data):
    base=sec('SUPABASE_URL').rstrip('/'); key=sec('SUPABASE_SERVICE_KEY')
    if len(data)>50*1024*1024:raise RuntimeError('APK áž›áž¾ážŸ 50MB')
    try:sb('POST','/storage/v1/bucket',json.dumps({'id':'apk','name':'apk','public':False,'file_size_limit':52428800,'allowed_mime_types':['application/vnd.android.package-archive']}).encode())
    except Exception as e:
        if '409' not in str(e) and 'already' not in str(e).lower():raise
    old=apk_list(); path=urllib.parse.quote(name,safe='')
    h={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':'application/vnd.android.package-archive','x-upsert':'true'}
    with urllib.request.urlopen(urllib.request.Request(f'{base}/storage/v1/object/apk/{path}',data=data,headers=h,method='POST'),timeout=180):pass
    if old:
        b=json.dumps({'prefixes':[x for x in old if x!=name]}).encode(); sb('DELETE','/storage/v1/object/apk',b)
def apk_get():
    n=apk_list()
    if not n:return None,None
    name=n[0]; p=urllib.parse.quote(name,safe='')
    return name,sb('GET',f'/storage/v1/object/apk/{p}',None,None,180)

def font():
    os.makedirs(FD,exist_ok=True)
    if not os.path.isfile(FP):
        with urllib.request.urlopen(FU,timeout=30) as r:open(FP,'wb').write(r.read())
    return FP
def at(v):
    v=max(0,float(v));return f'{int(v//3600)}:{int(v%3600//60):02d}:{v%60:05.2f}'
@st.cache_resource
def client(k):return genai.Client(api_key=k)
def duration(v):
    try:return float(str(v).replace('s',''))
    except:return 0
def words(r):
    out=[]
    def add(w):
        t=val(w,'word',val(w,'text','')); s=val(w,'start_offset',val(w,'start_time',val(w,'start',0))); e=val(w,'end_offset',val(w,'end_time',val(w,'end',s)))
        if t:out.append({'text':str(t),'start':duration(s),'end':duration(e)})
    for c in val(r,'candidates',[]) or []:
        for p in val(val(c,'content',None),'parts',[]) or []:
            for w in val(val(p,'audio_transcription',None),'words',[]) or []:add(w)
    for w in val(val(r,'audio_transcription',None),'words',[]) or []:add(w)
    for w in val(r,'words',[]) or []:add(w)
    return out
def transcribe(c,a,lang):
    data=open(a,'rb').read(); kw={'word_timestamp':True}
    if lang=='Chinese':kw['language_codes']=['cmn-Hans-CN']
    if lang=='Khmer':kw['language_codes']=['km-KH']
    cfg=types.AudioTranscriptionConfig(**kw)
    return retry(lambda:c.models.generate_content(model=TM,contents=[types.Part.from_bytes(data=data,mime_type='audio/wav'),'Transcribe exactly. Return accurate word-level timestamps. Do not translate.'],config=types.GenerateContentConfig(audio_transcription_config=cfg)))
def groups(ws):
    out=[]; cur=[]
    for w in ws:
        if cur and (len(cur)>=12 or w['end']-cur[0]['start']>=5):out.append(cur);cur=[]
        cur.append(w)
    if cur:out.append(cur)
    return [{'text':' '.join(w['text'] for w in g),'start':g[0]['start'],'end':g[-1]['end']} for g in out]
def translate(c,g,lang):
    if not g or lang=='No translation':return g
    out=[]
    for i in range(0,len(g),15):
        b=g[i:i+15]; p=f'Translate each line into {lang}. Return exactly one line per input, same order. No explanations.\n{[x["text"] for x in b]}'
        schema=types.Schema(type=types.Type.ARRAY,items=types.Schema(type=types.Type.STRING))
        try:
            r=retry(lambda:c.models.generate_content(model=LM,contents=p,config=types.GenerateContentConfig(response_mime_type='application/json',response_schema=schema)))
            x=val(r,'parsed',None) or json.loads(val(r,'text','[]'))
            if not isinstance(x,list) or len(x)!=len(b):raise ValueError()
        except:x=[z['text'] for z in b]
        out += [{'text':str(x[j]),'start':z['start'],'end':z['end']} for j,z in enumerate(b)]
    return out
def ass(gs,p):
    h='''[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    with open(p,'w',encoding='utf-8-sig') as f:
        f.write(h+''.join(f"Dialogue: 0,{at(x['start'])},{at(x['end'])},Default,,0,0,0,,{x['text'].replace(chr(92),chr(92)*2).replace('{','\\{').replace('}','\\}').replace(chr(10),'\\N')}\n" for x in gs))
def burn(v,a,o):
    font();vf=f"ass=filename='{a.replace(chr(92),'/')}':fontsdir='{FD.replace(chr(92),'/')}':shaping=complex"
    r=subprocess.run([ff(),'-y','-i',v,'-vf',vf,'-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','copy','-movflags','+faststart',o],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError(r.stderr.decode(errors='ignore')[-3000:])
def audio(v,o):
    r=subprocess.run([ff(),'-y','-i',v,'-vn','-ac','1','-ar','16000','-f','wav',o],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError('Extract Audio áž˜áž·áž“áž”áž¶áž“')
def tts(t,o,l):gTTS(t.strip(),lang=l).save(o)

def download(url,o):
    if re.search(r'\.(mp4|m3u8|webm|mov|mkv)(\?|$)',url,re.I):
        urllib.request.urlretrieve(url,o);return o
    import yt_dlp
    with yt_dlp.YoutubeDL({'outtmpl':o,'format':'bv*+ba/b','merge_output_format':'mp4','noplaylist':True,'quiet':True,'ffmpeg_location':ff()}) as y: y.download([url])
    if os.path.exists(o):return o
    raise RuntimeError('Download áž˜áž·áž“áž”áž¶áž“')

with st.expander('â¬‡ï¸ Download Video'):
    u=st.text_input('ážŠáž¶áž€áŸ‹ Link ážœáž¸ážŠáŸáž¢áž¼ áž¬ Page')
    if st.button('â¬‡ï¸ Download'):
        try:
            o=tempfile.mktemp('.mp4');download(u.strip(),o);st.video(o);st.download_button('ðŸ“¥ Download',open(o,'rb'),'download.mp4','video/mp4')
        except Exception as e:st.error(f'âŒ {e}')
with st.expander('ðŸŽ™ï¸ Text â†’ Free Voice'):
    t=st.text_area('áž”áž‰áŸ’áž…áž¼áž›áž¢ážáŸ’ážáž”áž‘'); l=st.selectbox('áž—áž¶ážŸáž¶ážŸáŸ†áž¡áŸáž„',['Khmer','Chinese','English']); lm={'Khmer':'km','Chinese':'zh-CN','English':'en'}
    if st.button('ðŸŽ™ï¸ Generate Voice'):
        try:
            o=tempfile.mktemp('.mp3');tts(t,o,lm[l]);d=open(o,'rb').read();st.audio(d);st.download_button('ðŸ“¥ Download Voice',d,'smey_voice.mp3','audio/mpeg')
        except Exception as e:st.error(f'âŒ {e}')
with st.expander('ðŸ“± APK'):
    try:
        n,d=apk_get()
        if d:st.success(f'ðŸ“¦ {n}');st.download_button('â¬‡ï¸ Download APK',d,n,'application/vnd.android.package-archive',use_container_width=True)
        else:st.info('áž˜áž·áž“áž‘áž¶áž“áŸ‹áž˜áž¶áž“ APK')
    except Exception as e:st.warning(f'âš ï¸ APK: {e}')
    with st.expander('ðŸ‘‘ Admin'):
        pw=st.text_input('ðŸ” Password',type='password');up=st.file_uploader('ðŸ“¤ Upload APK',type=['apk']);name=st.text_input('âœï¸ ážˆáŸ’áž˜áŸ„áŸ‡ APK')
        if st.button('â¬†ï¸ Upload APK',use_container_width=True):
            if not sec('APK_ADMIN_PASSWORD'):st.error('áž€áŸ†ážŽážáŸ‹ APK_ADMIN_PASSWORD áž€áŸ’áž“áž»áž„ Secrets')
            elif pw!=sec('APK_ADMIN_PASSWORD'):st.error('âŒ Password áž˜áž·áž“ážáŸ’ážšáž¹áž˜ážáŸ’ážšáž¼ážœ')
            elif not up:st.warning('âš ï¸ ážŸáž¼áž˜áž‡áŸ’ážšáž¾ážŸ APK')
            else:
                try:
                    n=re.sub(r'[^A-Za-z0-9_.,!*$@=;:+?()\- ]','',name.strip() or os.path.splitext(up.name)[0]) or 'app';n+= '' if n.lower().endswith('.apk') else '.apk';apk_upload(n,up.getvalue());st.success(f'âœ… {n}');st.rerun()
                except Exception as e:st.error(f'âŒ {e}')

st.divider();st.subheader('ðŸŽ¬ Auto Caption')
key=sec('GEMINI_API_KEY'); src=st.selectbox('áž—áž¶ážŸáž¶ážŸáŸ†áž¡áŸáž„ážŠáž¾áž˜',['Auto','Chinese','Khmer']);tar=st.selectbox('áž—áž¶ážŸáž¶ Caption',['Khmer','Chinese','No translation']);video=st.file_uploader('ðŸ“¤ Upload Video',type=['mp4','mov','mkv','webm','avi'])
if video:st.video(video)
if st.button('ðŸš€ Auto Caption',type='primary'):
    if not key:st.error('áž˜áž·áž“áž‘áž¶áž“áŸ‹áž€áŸ†ážŽážáŸ‹ GEMINI_API_KEY');st.stop()
    if not video:st.warning('ážŸáž¼áž˜ Upload Video áž‡áž¶áž˜áž»áž“');st.stop()
    d=tempfile.mkdtemp();iv=os.path.join(d,'input.mp4');aw=os.path.join(d,'audio.wav');ap=os.path.join(d,'cap.ass');ov=os.path.join(d,'Smey_Auto_Caption.mp4');open(iv,'wb').write(video.getbuffer())
    try:
        with st.status('áž€áŸ†áž–áž»áž„ážŠáŸ†ážŽáž¾ážšáž€áž¶ážš...',expanded=True):
            audio(iv,aw);w=words(transcribe(client(key),aw,None if src=='Auto' else src));g=groups(w)
            if not g:raise RuntimeError('Gemini áž˜áž·áž“áž”áž¶áž“áž•áŸ’ážáž›áŸ‹ Word Timing')
            fg=translate(client(key),g,tar);ass(fg,ap);burn(iv,ap,ov)
        st.success(f'ážšáž€ážƒáž¾áž‰ {len(fg)} Caption');st.video(ov);st.download_button('ðŸ“¥ Download MP4',open(ov,'rb'),'Smey_Auto_Caption.mp4','video/mp4')
    except Exception as e:st.error(f'âŒ Auto Caption áž˜áž·áž“áž¢áž¶áž…áž”áž‰áŸ’áž…áž”áŸ‹áž”áž¶áž“: {e}')
