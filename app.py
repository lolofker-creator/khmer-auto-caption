import os
import re
import subprocess
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import time
import wave
import json
from gtts import gTTS
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg
st.set_page_config(page_title='ðŸ‡°ðŸ‡­ Smey Auto Caption', page_icon='ðŸ‡°ðŸ‡­')
st.title('ðŸ‡°ðŸ‡­ Smey Auto Caption')
st.caption('Gemini â†’ Caption â†’ Auto Translate â†’ MP4')
st.markdown('ðŸ“© **áž‘áŸ†áž“áž¶áž€áŸ‹áž‘áŸ†áž“áž„áž˜áŸ’áž…áž¶ážŸáŸ‹áž€áž˜áŸ’áž˜ážœáž·áž’áž¸:** [Telegram @Smeytk](https://t.me/Smeytk)')
TRANSCRIBE_MODEL = 'gemini-3.5-transcribe'
TRANSLATE_MODEL = 'gemini-3.1-flash-lite'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, 'fonts')
FONT_PATH = os.path.join(FONT_DIR, 'NotoSansKhmer-Regular.ttf')
FONT_URL = 'https://raw.githubusercontent.com/ghostlypi/NotoSans/main/NotoSansKhmer-Regular.ttf'

def get_value(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()

def get_api_key():
    try:
        key = st.secrets.get('GEMINI_API_KEY', '')
    except Exception:
        key = ''
    return str(key or os.getenv('GEMINI_API_KEY', '')).strip()

def secret(name):
    try:
        return str(st.secrets.get(name, '') or '').strip()
    except Exception:
        return ''

def supabase(method, path, data=None, ctype=None, timeout=180):
    base, key = secret('SUPABASE_URL').rstrip('/'), secret('SUPABASE_SERVICE_KEY')
    if not base or not key:
        raise RuntimeError('ážŸáž¼áž˜áž€áŸ†ážŽážáŸ‹ SUPABASE_URL áž“áž·áž„ SUPABASE_SERVICE_KEY áž€áŸ’áž“áž»áž„ Secrets')
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    if ctype: headers['Content-Type'] = ctype
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Supabase HTTP {e.code}: {msg or e.reason}') from e

def apk_list():
    body = json.dumps({'prefix':'','limit':100,'offset':0,'sortBy':{'column':'name','order':'asc'}}).encode()
    raw = supabase('POST', '/storage/v1/object/list/apk', body, 'application/json')
    return [x['name'] for x in json.loads(raw or b'[]') if x.get('name','').lower().endswith('.apk')]

def apk_upload(name, data):
    if len(data) > 50 * 1024 * 1024:
        raise RuntimeError('APK áž’áŸ†áž–áŸáž€áŸ” áž¢ážáž·áž”ážšáž˜áž¶ 50MB')
    key = secret('SUPABASE_SERVICE_KEY')
    base = secret('SUPABASE_URL').rstrip('/')
    # Create/update private bucket
    settings = json.dumps({'id':'apk','name':'apk','public':False,'file_size_limit':50*1024*1024,'allowed_mime_types':['application/vnd.android.package-archive']}).encode()
    try:
        supabase('POST','/storage/v1/bucket',settings,'application/json')
    except RuntimeError as e:
        if '409' in str(e) or 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
            try: supabase('PUT','/storage/v1/bucket/apk',settings,'application/json')
            except Exception: pass
        else: raise
    old = apk_list()
    path = urllib.parse.quote(name, safe='')
    req = urllib.request.Request(base + f'/storage/v1/object/apk/{path}', data=data, headers={
        'apikey':key,'Authorization':f'Bearer {key}','Content-Type':'application/vnd.android.package-archive','x-upsert':'true'
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=180): pass
    except urllib.error.HTTPError as e:
        msg=e.read().decode('utf-8',errors='ignore')
        raise RuntimeError(f'Supabase Upload HTTP {e.code}: {msg or e.reason}') from e
    for old_name in old:
        if old_name != name:
            body=json.dumps({'prefixes':[old_name]}).encode()
            supabase('DELETE','/storage/v1/object/apk',body,'application/json')

def apk_download():
    names=apk_list()
    if not names: return None,None
    name=names[0]
    path=urllib.parse.quote(name,safe='')
    return name, supabase('GET',f'/storage/v1/object/apk/{path}',timeout=180)

def ass_time(value):
    value = max(0.0, float(value))
    h = int(value // 3600)
    m = int(value % 3600 // 60)
    s = value % 60
    return f'{h}:{m:02d}:{s:05.2f}'

@st.cache_resource
def get_gemini_client(api_key):
    return genai.Client(api_key=api_key)

def retry_gemini(call, attempts=4, delay=2):
    last_error = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            temporary = any((code in message for code in ('429', '500', '502', '503', '504', 'unavailable', 'resource_exhausted')))
            if not temporary or attempt == attempts - 1:
                raise
            time.sleep(delay * 2 ** attempt)
    raise last_error

def ensure_khmer_font():
    os.makedirs(FONT_DIR, exist_ok=True)
    if os.path.isfile(FONT_PATH) and os.path.getsize(FONT_PATH) > 10000:
        return FONT_PATH
    try:
        request = urllib.request.Request(FONT_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        if len(data) < 10000:
            raise RuntimeError('Font file ážŠáŸ‚áž›áž‘áž¶áž‰áž™áž€áž˜áž€áž˜áž¶áž“áž‘áŸ†áž áŸ†áž˜áž·áž“ážáŸ’ážšáž¹áž˜ážáŸ’ážšáž¼ážœ')
        with open(FONT_PATH, 'wb') as f:
            f.write(data)
        return FONT_PATH
    except Exception as e:
        raise RuntimeError(f'áž˜áž·áž“áž¢áž¶áž…ážšáž€/áž‘áž¶áž‰áž™áž€ Noto Sans Khmer Font áž”áž¶áž“áŸ” ážŸáž¼áž˜áž–áž·áž“áž·ážáŸ’áž™ Internet ážšáž”ážŸáŸ‹ Streamlit CloudáŸ”\n{e}') from e

def parse_duration(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith('s'):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return 0.0

def add_word(result, word, start=None, end=None):
    text = get_value(word, 'word', None)
    if text is None:
        text = get_value(word, 'text', '')
    if not text:
        return
    if start is None:
        start = get_value(word, 'start_offset', None)
    if start is None:
        start = get_value(word, 'start_time', None)
    if start is None:
        start = get_value(word, 'start', 0)
    if end is None:
        end = get_value(word, 'end_offset', None)
    if end is None:
        end = get_value(word, 'end_time', None)
    if end is None:
        end = get_value(word, 'end', start)
    result.append({'text': str(text), 'start': parse_duration(start), 'end': parse_duration(end)})

def words_from(response):
    words = []
    for candidate in get_value(response, 'candidates', []) or []:
        content = get_value(candidate, 'content', None)
        for part in get_value(content, 'parts', []) or []:
            transcription = get_value(part, 'audio_transcription', None)
            if transcription is None:
                continue
            current_words = get_value(transcription, 'words', []) or []
            for word in current_words:
                add_word(words, word)
    transcription = get_value(response, 'audio_transcription', None)
    if transcription is not None:
        for word in get_value(transcription, 'words', []) or []:
            add_word(words, word)
    direct_words = get_value(response, 'words', None)
    if direct_words:
        for word in direct_words:
            add_word(words, word)
    annotations = get_value(response, 'annotations', None)
    if annotations:
        for item in annotations:
            if get_value(item, 'type', '') == 'word_info':
                add_word(words, item)
    return words

def detect_language(text):
    khmer = len(re.findall('[\\u1780-\\u17FF]', text))
    chinese = len(re.findall('[\\u4E00-\\u9FFF]', text))
    if khmer > chinese and khmer > 0:
        return 'Khmer'
    if chinese > 0:
        return 'Chinese'
    return 'Unknown'

def make_groups(words, max_words=12, max_seconds=5.0):
    groups = []
    current = []
    for word in words:
        if not current:
            current = [word]
            continue
        duration = word['end'] - current[0]['start']
        if len(current) >= max_words or duration >= max_seconds:
            groups.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        groups.append(current)
    result = []
    for group in groups:
        text = ' '.join((x['text'] for x in group)).strip()
        if text:
            result.append({'text': text, 'start': group[0]['start'], 'end': group[-1]['end']})
    return result

def transcribe(client, audio_path, source_language):
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    prompt = 'Transcribe the spoken audio exactly. Return accurate word-level timestamps. Do not translate the speech.'
    language_codes = None
    if source_language == 'Chinese':
        language_codes = ['cmn-Hans-CN']
    elif source_language == 'Khmer':
        language_codes = ['km-KH']
    transcription_kwargs = {'word_timestamp': True}
    if language_codes:
        transcription_kwargs['language_codes'] = language_codes
    transcription_config = types.AudioTranscriptionConfig(**transcription_kwargs)

    def call():
        return client.models.generate_content(model=TRANSCRIBE_MODEL, contents=[types.Part.from_bytes(data=audio_data, mime_type='audio/wav'), prompt], config=types.GenerateContentConfig(audio_transcription_config=transcription_config))
    return retry_gemini(call)

def translate_groups(client, groups, target_language):
    if not groups or target_language == 'No translation':
        return groups
    translated = []
    batch_size = 15
    for start in range(0, len(groups), batch_size):
        batch = groups[start:start + batch_size]
        texts = [item['text'] for item in batch]
        prompt = f'Translate each subtitle line into {target_language}.\nReturn exactly one translated line per input line, in the same order. Do not add explanations. Keep names and numbers accurate.\n\nInput:\n{texts}'
        schema = types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING))

        def call():
            return client.models.generate_content(model=TRANSLATE_MODEL, contents=prompt, config=types.GenerateContentConfig(response_mime_type='application/json', response_schema=schema))
        try:
            response = retry_gemini(call)
            values = get_value(response, 'parsed', None)
            if values is None:
                raw = get_value(response, 'text', '') or ''
                try:
                    values = json.loads(raw)
                except Exception:
                    values = []
            if not isinstance(values, list) or len(values) != len(batch):
                raise RuntimeError('Translation response áž˜áž·áž“ážáŸ’ážšáž¹áž˜ážáŸ’ážšáž¼ážœ')
        except Exception as exc:
            st.warning('âš ï¸ Gemini Translation áž˜áž·áž“áž‘áž¶áž“áŸ‹áž¢áž¶áž…áž”áŸ’ážšáž¾áž”áž¶áž“áŸ” Caption áž“áž¹áž„ážšáž€áŸ’ážŸáž¶áž—áž¶ážŸáž¶ážŠáž¾áž˜ážŸáž˜áŸ’ážšáž¶áž”áŸ‹áž•áŸ’áž“áŸ‚áž€áž“áŸáŸ‡áŸ”')
            values = [item['text'] for item in batch]
        for index, item in enumerate(batch):
            translated.append({'text': str(values[index]), 'start': item['start'], 'end': item['end']})
    return translated
ASS_HEADER = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Noto Sans Khmer,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,55,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'

def make_ass(groups, ass_path):
    with open(ass_path, 'w', encoding='utf-8-sig') as f:
        f.write(ASS_HEADER)
        for item in groups:
            text = item['text'].replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}').replace('\n', '\\N')
            f.write(f"Dialogue: 0,{ass_time(item['start'])},{ass_time(item['end'])},Default,,0,0,0,,{text}\n")

def burn(video_path, ass_path, output_path):
    ensure_khmer_font()
    font_dir = FONT_DIR.replace('\\', '/')
    ass_file = ass_path.replace('\\', '/')
    vf = f"ass=filename='{ass_file}':fontsdir='{font_dir}':shaping=complex"
    command = [ffmpeg(), '-y', '-i', video_path, '-vf', vf, '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-c:a', 'copy', '-movflags', '+faststart', output_path]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        error = result.stderr.decode('utf-8', errors='ignore')
        raise RuntimeError('FFmpeg áž”áž‰áŸ’áž…áž¼áž› Caption áž˜áž·áž“áž”áž¶áž“:\n\n' + error[-5000:])
    return output_path

def extract_audio(video_path, output_wav):
    try:
        import av
        container = av.open(video_path)
        stream = next((s for s in container.streams if s.type == 'audio'), None)
        if stream is None:
            raise RuntimeError('ážšáž€áž˜áž·áž“ážƒáž¾áž‰ Audio áž€áŸ’áž“áž»áž„ážœáž¸ážŠáŸáž¢áž¼')
        resampler = av.audio.resampler.AudioResampler(format='s16', layout='mono', rate=16000)
        pcm = bytearray()
        for frame in container.decode(stream):
            frames = resampler.resample(frame)
            if not isinstance(frames, list):
                frames = [frames]
            for converted in frames:
                for plane in converted.planes:
                    pcm.extend(plane.to_bytes())
        container.close()
        if not pcm:
            raise RuntimeError('Audio áž‘áž‘áŸ')
        with wave.open(output_wav, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(pcm))
        return output_wav
    except Exception:
        command = [ffmpeg(), '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', output_wav]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            error = result.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError('áž˜áž·áž“áž¢áž¶áž… Extract Audio áž”áž¶áž“:\n\n' + error[-4000:])
        return output_wav

def free_tts(text, output_mp3, language='km'):
    text = text.strip()
    if not text:
        raise ValueError('ážŸáž¼áž˜áž”áž‰áŸ’áž…áž¼áž›áž¢ážáŸ’ážáž”áž‘')
    tts = gTTS(text=text, lang=language, slow=False)
    tts.save(output_mp3)
    return output_mp3
MEDIA_RE = re.compile(r"https?://[^\s\"'<>]+?(?:\.mp4|\.m3u8|\.webm|\.mov|\.mkv)(?:\?[^\s\"'<>]*)?", re.I)

def find_media_urls(html):
    return list(dict.fromkeys(MEDIA_RE.findall(html)))

def download_media_url(url, output_path):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r, open(output_path, 'wb') as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return output_path

def page_media_download(page_url, output_path):
    req = urllib.request.Request(page_url, headers={'User-Agent': 'Mozilla/5.0 (Android 10; Mobile) AppleWebKit/537.36 Chrome/120 Safari/537.36'})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode('utf-8', errors='ignore')
    for url in find_media_urls(html):
        try:
            return download_media_url(url, output_path)
        except Exception:
            pass
    raise RuntimeError('ážšáž€áž˜áž·áž“ážƒáž¾áž‰ážœáž¸ážŠáŸáž¢áž¼áž€áŸ’áž“áž»áž„ Link áž“áŸáŸ‡')

def webpage_download(page_url, output_path):
    # Direct video URL
    if re.search(r'\.(?:mp4|m3u8|webm|mov|mkv)(?:\?|$)', page_url, re.I):
        try:
            return download_media_url(page_url, output_path)
        except Exception:
            pass

    # Supported sites
    try:
        import yt_dlp
        options = {
            'outtmpl': output_path,
            'format': 'bv*+ba/b',
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg(),
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([page_url])
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        base = os.path.splitext(output_path)[0]
        for ext in ('.mp4', '.webm', '.mkv'):
            candidate = base + ext
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                if candidate != output_path:
                    os.replace(candidate, output_path)
                return output_path
    except Exception:
        pass

    # Public pages containing a media URL
    return page_media_download(page_url, output_path)

with st.expander('â¬‡ï¸ Download Video'):
    page_url = st.text_input('ážŠáž¶áž€áŸ‹ Link ážœáž¸ážŠáŸáž¢áž¼ áž¬ Page', placeholder='https://...')
    if st.button('â¬‡ï¸ Download'):
        if not page_url.strip():
            st.warning('ážŸáž¼áž˜ážŠáž¶áž€áŸ‹ Link áž‡áž¶áž˜áž»áž“')
        else:
            try:
                with st.spinner('áž€áŸ†áž–áž»áž„ Download...'):
                    output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                    output.close()
                    webpage_download(page_url.strip(), output.name)
                st.success('âœ… ážšáž½áž…ážšáž¶áž›áŸ‹')
                st.video(output.name)
                with open(output.name, 'rb') as f:
                    st.download_button('ðŸ“¥ áž‘áž¶áž‰áž™áž€ážœáž¸ážŠáŸáž¢áž¼', f, file_name='download.mp4', mime='video/mp4')
            except Exception:
                st.error('áž˜áž·áž“áž¢áž¶áž… Download Link áž“áŸáŸ‡áž”áž¶áž“áž‘áŸáŸ” Link áž¢áž¶áž…áž‡áž¶ Private/Login/DRM áž¬áž˜áž·áž“áž˜áž¶áž“ážœáž¸ážŠáŸáž¢áž¼ážŠáŸ‚áž›áž¢áž¶áž…áž‘áž¶áž‰áž™áž€áž”áž¶áž“áŸ”')

with st.expander('ðŸŽ™ï¸ Text â†’ Free Voice'):
    tts_text = st.text_area('áž”áž‰áŸ’áž…áž¼áž›áž¢ážáŸ’ážáž”áž‘', height=120, key='tts_text', placeholder='ážŸážšážŸáŸážšáž¢ážáŸ’ážáž”áž‘ážŠáŸ‚áž›áž…áž„áŸ‹áž”áž˜áŸ’áž›áŸ‚áž„áž‡áž¶ážŸáŸ†áž¡áŸáž„...')
    tts_language = st.selectbox('áž—áž¶ážŸáž¶ážŸáŸ†áž¡áŸáž„', ['Khmer', 'Chinese', 'English'], key='tts_language')
    tts_lang_map = {'Khmer': 'km', 'Chinese': 'zh-CN', 'English': 'en'}
    if st.button('ðŸŽ™ï¸ Generate Voice', key='free_tts_button'):
        if not tts_text.strip():
            st.warning('ážŸáž¼áž˜áž”áž‰áŸ’áž…áž¼áž›áž¢ážáŸ’ážáž”áž‘áž‡áž¶áž˜áž»áž“')
        else:
            try:
                output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                output.close()
                with st.spinner('áž€áŸ†áž–áž»áž„áž”áž„áŸ’áž€áž¾ážážŸáŸ†áž¡áŸáž„ Free...'):
                    free_tts(tts_text, output.name, tts_lang_map[tts_language])
                with open(output.name, 'rb') as f:
                    audio_data = f.read()
                st.audio(audio_data, format='audio/mp3')
                st.download_button('ðŸ“¥ Download Voice', audio_data, file_name='smey_voice.mp3', mime='audio/mpeg', key='download_free_voice')
            except Exception as e:
                st.error(f'âŒ Voice Error: {e}')
with st.expander('ðŸ“± APK'):
    try:
        apk_name, apk_data = apk_download()
        if apk_data and apk_name:
            st.success(f'ðŸ“¦ {apk_name}')
            st.download_button('â¬‡ï¸ Download APK', apk_data, file_name=apk_name, mime='application/vnd.android.package-archive', use_container_width=True, key='apk_download')
        else:
            st.info('áž˜áž·áž“áž‘áž¶áž“áŸ‹áž˜áž¶áž“ APK')
    except Exception as e:
        st.warning(f'âš ï¸ APK Storage: {e}')

    with st.expander('ðŸ‘‘ Admin'):
        password=st.text_input('ðŸ” Password',type='password',key='apk_password')
        uploaded=st.file_uploader('ðŸ“¤ Upload APK',type=['apk'],key='apk_file')
        custom=st.text_input('âœï¸ ážˆáŸ’áž˜áŸ„áŸ‡ APK',placeholder='áž§. Smey AI VIP 1',key='apk_name_input')
        if st.button('â¬†ï¸ Upload APK',use_container_width=True,key='apk_upload_button'):
            admin=secret('APK_ADMIN_PASSWORD')
            if not admin: st.error('ážŸáž¼áž˜áž€áŸ†ážŽážáŸ‹ APK_ADMIN_PASSWORD áž€áŸ’áž“áž»áž„ Secrets')
            elif password != admin: st.error('âŒ Password áž˜áž·áž“ážáŸ’ážšáž¹áž˜ážáŸ’ážšáž¼ážœ')
            elif not uploaded: st.warning('âš ï¸ ážŸáž¼áž˜áž‡áŸ’ážšáž¾ážŸ APK')
            else:
                name=re.sub(r'[\\/:*?"<>|]','',custom.strip() or os.path.splitext(uploaded.name)[0]).strip() or 'app'
                if not name.lower().endswith('.apk'): name += '.apk'
                try:
                    with st.spinner('áž€áŸ†áž–áž»áž„ Upload APK áž‘áŸ… Supabase...'):
                        apk_upload(name,uploaded.getvalue())
                    st.success(f'âœ… Upload ážšáž½áž…ážšáž¶áž›áŸ‹: {name}')
                    st.rerun()
                except Exception as e: st.error(f'âŒ Upload APK áž˜áž·áž“áž”áž¶áž“: {e}')

st.divider()
st.subheader('ðŸŽ¬ Auto Caption')
api_key = get_api_key()
source_language = st.selectbox('áž—áž¶ážŸáž¶ážŸáŸ†áž¡áŸáž„ážŠáž¾áž˜', ['Auto', 'Chinese', 'Khmer'])
target_language = st.selectbox('áž—áž¶ážŸáž¶ Caption', ['Khmer', 'Chinese', 'No translation'])
uploaded_video = st.file_uploader('ðŸ“¤ Upload Video', type=['mp4', 'mov', 'mkv', 'webm', 'avi'])
if uploaded_video:
    st.video(uploaded_video)
if st.button('ðŸš€ Auto Caption', type='primary'):
    if not api_key:
        st.error('áž˜áž·áž“áž‘áž¶áž“áŸ‹áž€áŸ†ážŽážáŸ‹ GEMINI_API_KEY áž€áŸ’áž“áž»áž„ Streamlit Secrets áž‘áŸáŸ”')
        st.stop()
    if not uploaded_video:
        st.warning('ážŸáž¼áž˜ Upload Video áž‡áž¶áž˜áž»áž“')
        st.stop()
    client = get_gemini_client(api_key)
    temp_dir = tempfile.mkdtemp()
    input_video = os.path.join(temp_dir, 'input.mp4')
    audio_path = os.path.join(temp_dir, 'audio.wav')
    ass_path = os.path.join(temp_dir, 'captions.ass')
    output_video = os.path.join(temp_dir, 'Smey_Auto_Caption.mp4')
    try:
        with open(input_video, 'wb') as f:
            f.write(uploaded_video.getbuffer())
        with st.status('áž€áŸ†áž–áž»áž„ážŠáŸ†ážŽáž¾ážšáž€áž¶ážš Auto Caption...', expanded=True) as status:
            st.write('ðŸŽ§ 1/5 áž€áŸ†áž–áž»áž„áž™áž€ážŸáŸ†áž¡áŸáž„áž–áž¸ážœáž¸ážŠáŸáž¢áž¼...')
            extract_audio(input_video, audio_path)
            st.write('ðŸ“ 2/5 áž€áŸ†áž–áž»áž„ážŸáŸ’ážáž¶áž”áŸ‹ áž“áž·áž„áž€áŸ†ážŽážáŸ‹ Word Timing...')
            transcription = transcribe(client, audio_path, source_language if source_language != 'Auto' else None)
            words = words_from(transcription)
            if not words:
                raise RuntimeError('Gemini áž˜áž·áž“áž”áž¶áž“áž•áŸ’ážáž›áŸ‹ Word TimingáŸ” ážŸáž¼áž˜ážŸáž¶áž€áž›áŸ’áž”áž„áž˜áŸ’ážáž„áž‘áŸ€ážáŸ”')
            groups = make_groups(words)
            full_text = ' '.join((item['text'] for item in groups))
            detected = detect_language(full_text)
            st.write(f'ðŸŒ áž—áž¶ážŸáž¶ážŠáŸ‚áž›áž”áž¶áž“ážšáž€ážƒáž¾áž‰: **{detected}**')
            st.write('ðŸ”„ 3/5 áž€áŸ†áž–áž»áž„áž”áž€áž”áŸ’ážšáŸ‚ Caption...')
            final_groups = translate_groups(client, groups, target_language)
            st.write('ðŸŽžï¸ 4/5 áž€áŸ†áž–áž»áž„áž”áž„áŸ’áž€áž¾áž Caption...')
            make_ass(final_groups, ass_path)
            st.write('ðŸ”¥ 5/5 áž€áŸ†áž–áž»áž„áž”áž‰áŸ’áž…áž¼áž› Caption áž‘áŸ…áž€áŸ’áž“áž»áž„ MP4...')
            burn(input_video, ass_path, output_video)
            status.update(label='âœ… Auto Caption ážšáž½áž…ážšáž¶áž›áŸ‹!', state='complete')
        st.success(f'ážšáž€ážƒáž¾áž‰ {len(final_groups)} Caption')
        st.subheader('ðŸ“ Caption Preview')
        for item in final_groups:
            st.write(f"`{ass_time(item['start'])} â†’ {ass_time(item['end'])}`  {item['text']}")
        st.subheader('ðŸŽ¬ Result')
        st.video(output_video)
        with open(output_video, 'rb') as f:
            st.download_button('ðŸ“¥ Download MP4', f, file_name='Smey_Auto_Caption.mp4', mime='video/mp4')
    except Exception as e:
        st.error(f'âŒ Auto Caption áž˜áž·áž“áž¢áž¶áž…áž”áž‰áŸ’áž…áž”áŸ‹áž”áž¶áž“: {e}')
