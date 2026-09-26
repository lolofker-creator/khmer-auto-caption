import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import time
import wave
import json
import asyncio
from gtts import gTTS
import asyncio
import streamlit as st
import imageio_ffmpeg
st.set_page_config(page_title='Smey AI Dubbing', page_icon='🇰🇭', layout='centered', initial_sidebar_state='collapsed')

# ===== OFFICIAL USER LOGO — external PNG, no Base64 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SMEY_LOGO_PATH = os.path.join(BASE_DIR, 'smey_ai_dubbing_logo.png')

# ===== BEAUTIFUL UI v13 — mobile hero style =====
st.markdown(r"""
<style>
.stApp{background:radial-gradient(circle at 50% -8%,rgba(40,91,180,.16),transparent 34%),linear-gradient(180deg,#070b12 0%,#0b111b 48%,#06090e 100%);color:#f7f8fb}
[data-testid="stHeader"]{background:transparent}
#MainMenu,footer{visibility:hidden}
.block-container{max-width:760px;padding:12px 16px 38px}
.smey-hero{text-align:center;margin:0 auto 18px}
.smey-title{font-size:43px;line-height:1.02;font-weight:950;letter-spacing:-1.5px;margin:0}
.smey-title .white{color:#f5f7fb}.smey-title .blue{color:#66d7ff}
.smey-sub{font-size:14px;color:#e8edf6;line-height:1.7;margin:15px auto 18px;max-width:690px}
.smey-flow{color:#f1f4f8;font-weight:650}.smey-flow .arrow{color:#62cfff;padding:0 3px}
.smey-features{margin:8px 0 22px;padding:2px 4px 0}
.smey-guide{border:1px solid rgba(255,255,255,.10);border-radius:18px;padding:15px 16px;margin:4px 0 18px;background:linear-gradient(145deg,rgba(255,68,55,.13),rgba(255,255,255,.035));box-shadow:0 12px 30px rgba(0,0,0,.20)}
.smey-guide-title{font-size:18px;font-weight:900;margin-bottom:6px;color:#f7f8fb}.smey-guide-sub{font-size:12px;color:#bfc8d6;line-height:1.55;margin-bottom:8px}.smey-step{display:flex;gap:9px;align-items:flex-start;padding:6px 0;font-size:12.5px;line-height:1.55;color:#eef1f6}.smey-num{min-width:23px;height:23px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(255,74,55,.20);border:1px solid rgba(255,100,80,.30);font-weight:900;color:#fff}.smey-step b{color:#5bcfff}
.smey-feature{display:flex;align-items:center;gap:14px;padding:8px 0;color:#f3f5f9;font-size:15px;line-height:1.45}
.smey-icon{width:42px;height:42px;min-width:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:23px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);box-shadow:0 7px 20px rgba(0,0,0,.18)}
.smey-icon.mic{color:#18e5dd}.smey-icon.cap{color:#55bfff}.smey-icon.voice{color:#ff5366}.smey-icon.img{color:#d46cff}.smey-icon.down{color:#2ee9aa}
.smey-feature b{color:#4dc8ff}
.smey-contact{text-align:center;margin:8px 0 20px;font-size:13px;color:#cdd5e2}.smey-contact a{color:#3db8ff!important;text-decoration:none!important;font-weight:800}
.smey-divider{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.14),transparent);margin:8px 0 20px}
.smey-real-controls{margin:0 0 14px;padding:14px 16px;border:1px solid rgba(255,255,255,.10);border-radius:18px;background:rgba(255,255,255,.035)}
.smey-real-title{font-size:16px;font-weight:900;color:#f3f6fb}.smey-real-sub{font-size:12px;color:#aeb8c8;margin-top:4px}
.smey-dubbing-top{margin:2px 0 14px}
[data-testid="stExpander"]{border:1px solid rgba(255,255,255,.10)!important;border-radius:19px!important;background:rgba(16,20,28,.86)!important;box-shadow:0 12px 34px rgba(0,0,0,.20);overflow:hidden}
[data-testid="stExpander"] summary{font-weight:850!important}
[data-baseweb="select"]>div,.stTextInput input,[data-testid="stFileUploaderDropzone"]{border-radius:14px!important;border-color:rgba(255,255,255,.13)!important;background:rgba(255,255,255,.045)!important}
[data-testid="stFileUploaderDropzone"]{padding:17px!important}
.stButton>button,.stDownloadButton>button{border-radius:14px!important;min-height:46px!important;font-weight:850!important;border:1px solid rgba(255,255,255,.11)!important}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-1px);filter:brightness(1.06);box-shadow:0 9px 24px rgba(0,0,0,.24)}
[data-testid="stStatusWidget"],[data-testid="stAlert"]{border-radius:16px!important}
[data-testid="stVideo"] video{border-radius:18px;box-shadow:0 14px 35px rgba(0,0,0,.30)}
@media(max-width:700px){.block-container{padding:8px 12px 28px}.smey-title{font-size:34px}.smey-sub{font-size:12.5px;margin-top:12px}.smey-feature{font-size:13px;gap:10px;padding:7px 0}.smey-icon{width:37px;height:37px;min-width:37px;font-size:20px;border-radius:10px}.smey-guide{padding:13px 14px;border-radius:16px}.smey-guide-title{font-size:16px}.smey-guide-sub,.smey-step{font-size:11.5px}}
</style>
""", unsafe_allow_html=True)

# ===== ONLY AI DUBBING + VOICE CLONE UI =====
# Keep the existing working Dubbing and Voice Clone functions intact.
# Hide/remove the old hero, guide, contact, and other upper UI.

dubbing_slot = st.empty()

TRANSCRIBE_MODEL = 'gemini-3.5-transcribe'
TRANSLATE_MODEL = 'gemini-3.1-flash-lite'
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
        raise RuntimeError('សូមកំណត់ SUPABASE_URL និង SUPABASE_SERVICE_KEY ក្នុង Secrets')
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
        raise RuntimeError('APK ធំពេក។ អតិបរមា 50MB')
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
            raise RuntimeError('Font file ដែលទាញយកមកមានទំហំមិនត្រឹមត្រូវ')
        with open(FONT_PATH, 'wb') as f:
            f.write(data)
        return FONT_PATH
    except Exception as e:
        raise RuntimeError(f'មិនអាចរក/ទាញយក Noto Sans Khmer Font បាន។ សូមពិនិត្យ Internet របស់ Streamlit Cloud។\n{e}') from e

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

def transcribe_local(audio_path, source_language):
    """Free local transcription with word timestamps. No Gemini quota."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            'សូមបន្ថែម faster-whisper ក្នុង requirements.txt រួច Deploy ម្តងទៀត។'
        ) from exc

    # CPU/int8 keeps the free Streamlit deployment practical.
    model = WhisperModel('small', device='cpu', compute_type='int8')
    lang = None
    if source_language == 'Chinese':
        lang = 'zh'
    elif source_language == 'Khmer':
        lang = 'km'

    segments, _info = model.transcribe(
        audio_path,
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    words = []
    for segment in segments:
        for word in (getattr(segment, 'words', None) or []):
            text = (getattr(word, 'word', '') or '').strip()
            if not text:
                continue
            start = float(getattr(word, 'start', segment.start) or segment.start)
            end = float(getattr(word, 'end', segment.end) or segment.end)
            words.append({'text': text, 'start': start, 'end': end})

    return words


def transcribe_reference_text(audio_path, source_language='Auto'):
    """Transcribe Voice Reference text for prompt-based VoxCPM cloning.

    This is intentionally separate from word-timestamp transcription. A short
    reference can have valid segment text but no word objects, especially with
    VAD/very short audio. We therefore disable VAD and read segment.text.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('ត្រូវការ faster-whisper សម្រាប់ Auto Voice Reference Text') from exc

    lang = None
    if source_language == 'Chinese':
        lang = 'zh'
    elif source_language == 'Khmer':
        lang = 'km'
    elif source_language == 'English':
        lang = 'en'

    model = WhisperModel('small', device='cpu', compute_type='int8')
    segments, _info = model.transcribe(
        audio_path,
        language=lang,
        word_timestamps=False,
        vad_filter=False,
        beam_size=5,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    parts = []
    for segment in segments:
        text = (getattr(segment, 'text', '') or '').strip()
        if text:
            parts.append(text)
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


def _detect_source_language(text, source_language='Auto'):
    """Resolve the source language reliably when UI is set to Auto."""
    if source_language and source_language != 'Auto':
        return {'Chinese': 'zh-CN', 'Khmer': 'km-KM', 'English': 'en-US'}.get(
            source_language, 'en-US'
        )
    if re.search(r'[\u3400-\u9FFF]', text):
        return 'zh-CN'
    if re.search(r'[\u1780-\u17FF]', text):
        return 'km-KM'
    return 'en-US'


def _mymemory_translate(text, target_language, source_language='auto'):
    """Free MyMemory translation fallback.

    Uses RFC3066 language codes and checks responseStatus so API error text
    is never mistaken for a successful translation.
    """
    if not text.strip():
        return text

    target_map = {
        'Khmer': 'km-KM',
        'Chinese': 'zh-CN',
        'English': 'en-US',
    }
    target = target_map.get(target_language)
    if not target:
        return text

    source = _detect_source_language(text, source_language)

    # MyMemory documents a 500-byte maximum for q. Keep a safety margin.
    raw = text.strip()
    if len(raw.encode('utf-8')) > 480:
        parts = []
        current = ''
        for piece in re.split(r'(?<=[.!?。！？])\s+|\s+', raw):
            candidate = (current + ' ' + piece).strip()
            if candidate and len(candidate.encode('utf-8')) <= 480:
                current = candidate
            else:
                if current:
                    parts.append(current)
                current = piece
        if current:
            parts.append(current)
        if len(parts) > 1:
            translated_parts = [
                _mymemory_translate(part, target_language, source_language)
                for part in parts
            ]
            return ' '.join(translated_parts)

    params = {
        'q': raw,
        'langpair': f'{source}|{target}',
        'mt': '1',
    }

    # Optional email can increase MyMemory's anonymous daily allowance.
    # It is only used if the user has explicitly configured it.
    email = secret('MYMEMORY_EMAIL')
    if email:
        params['de'] = email

    url = (
        'https://api.mymemory.translated.net/get?'
        + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    )

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Android 12; Mobile)',
            'Accept': 'application/json',
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode('utf-8'))

    status = str(data.get('responseStatus', ''))
    details = str(data.get('responseDetails', '') or '').strip()
    result = str(
        data.get('responseData', {}).get('translatedText', '')
    ).strip()

    if status not in ('', '200'):
        raise RuntimeError(
            f'MyMemory HTTP/status {status}: {details or result or "unknown error"}'
        )
    if not result:
        raise RuntimeError('MyMemory មិនបានបញ្ជូនលទ្ធផល')
    if result.upper() == raw.upper():
        # Same text can be legitimate for names/numbers, but it is not useful
        # as a Chinese/English -> Khmer translation.
        if target_language == 'Khmer' and not re.search(r'[\u1780-\u17FF]', result):
            raise RuntimeError('MyMemory មិនបានបកប្រែទៅជាខ្មែរ')
    low = result.lower()
    if any(x in low for x in (
        'invalid target language',
        'invalid source language',
        'please select',
        'error',
        'limit exceeded',
        'quota',
    )):
        raise RuntimeError(f'MyMemory Translation: {result}')

    return result


def _google_translate_once(text, target_language, source_language='auto', host='translate.googleapis.com'):
    target_map = {'Khmer': 'km', 'Chinese': 'zh-CN', 'English': 'en'}
    target = target_map.get(target_language)
    if not target:
        return text

    source = _detect_source_language(text, source_language)
    source = {'km-KM': 'km', 'en-US': 'en'}.get(source, source)

    url = (
        f'https://{host}/translate_a/single?client=gtx'
        f'&sl={urllib.parse.quote(source)}&tl={urllib.parse.quote(target)}'
        '&dt=t&q=' + urllib.parse.quote(text)
    )
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Android 12; Mobile)',
            'Accept': 'application/json,text/plain,*/*',
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode('utf-8'))

    parts = data[0] if isinstance(data, list) and data else []
    result = ''.join(
        str(part[0])
        for part in parts
        if isinstance(part, list) and part and part[0]
    ).strip()
    if not result:
        raise RuntimeError('Google Translation មិនបានបញ្ជូនលទ្ធផល')
    return result


def _google_free_translate(text, target_language, source_language='auto', attempts=2):
    """Free translation: MyMemory first, then Google as a second fallback.

    This avoids making Google the only dependency and fixes the previous
    failure where Google HTTP 429 caused every segment to fail.
    """
    if not text.strip():
        return text

    errors = []

    # Primary free provider: MyMemory.
    try:
        result = _mymemory_translate(text, target_language, source_language)
        if _translation_is_valid(result, target_language):
            return result.strip()
        errors.append('MyMemory លទ្ធផលមិនមែនជាភាសាគោលដៅ')
    except Exception as exc:
        errors.append(f'MyMemory: {exc}')

    # Secondary free provider: Google web endpoint.
    for host in ('translate.googleapis.com', 'translate.google.com'):
        for attempt in range(attempts):
            try:
                result = _google_translate_once(
                    text, target_language, source_language, host=host
                )
                if _translation_is_valid(result, target_language):
                    return result
                errors.append(f'Google {host}: លទ្ធផលមិនមែនជាភាសាគោលដៅ')
                break
            except urllib.error.HTTPError as exc:
                errors.append(f'Google {host} HTTP {exc.code}')
                if exc.code not in (429, 502, 503, 504):
                    break
                if attempt < attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
            except Exception as exc:
                errors.append(f'Google {host}: {exc}')
                break

    raise RuntimeError(' | '.join(errors[-4:]))


def _translate_batch(texts, target_language, source_language='Auto'):
    """Translate segments one by one to keep timing alignment exact."""
    results = []
    for text in texts:
        result = _google_free_translate(
            text,
            target_language,
            source_language,
            attempts=2,
        )
        results.append(result)
        # Small delay prevents a burst against free endpoints.
        time.sleep(0.35)
    return results

def _translation_is_valid(text, target_language):
    text = text.strip()
    if not text:
        return False
    if target_language == 'Khmer':
        return bool(re.search(r'[\u1780-\u17FF]', text))
    if target_language == 'Chinese':
        return bool(re.search(r'[\u3400-\u9FFF]', text))
    if target_language == 'English':
        return bool(re.search(r'[A-Za-z]', text))
    return True


def translate_groups(client, groups, target_language, source_language='Auto'):
    """Free translation with batching + 429 backoff.

    Gemini is not used for translation. This keeps the existing Dubbing
    pipeline intact while reducing the burst of requests that caused HTTP 429.
    """
    if not groups or target_language == 'No translation':
        return groups

    source_texts = [
        item['text'].replace('\n', ' ').strip()
        for item in groups
    ]

    translated_texts = _translate_batch(
        source_texts,
        target_language,
        source_language,
    )

    if len(translated_texts) != len(groups):
        raise RuntimeError(
            f'Free Translation returned {len(translated_texts)}/{len(groups)} segments'
        )

    translated = []
    failed = []

    for index, (item, result) in enumerate(
        zip(groups, translated_texts),
        start=1,
    ):
        try:
            if not _translation_is_valid(result, target_language):
                raise RuntimeError('លទ្ធផលមិនមែនជាភាសាគោលដៅ')

            translated.append({
                'text': result,
                'start': item['start'],
                'end': item['end'],
            })
        except Exception as exc:
            failed.append((index, str(exc)))

    if failed:
        sample = '; '.join(
            f'#{i}: {err}' for i, err in failed[:3]
        )
        raise RuntimeError(
            f'Free Translation failed សម្រាប់ {len(failed)}/{len(groups)} ប្រយោគ។ {sample}'
        )

    return translated



def translate_clone_groups_strict(groups, target_language, source_language='Auto'):
    """Strict Voice Clone translation. Never allow source-language text to reach VoxCPM when Khmer is requested."""
    if not groups:
        return groups
    if target_language != 'Khmer':
        return translate_groups(None, groups, target_language, source_language)

    out = []
    failures = []
    for index, item in enumerate(groups, start=1):
        src = str(item.get('text', '')).replace('\n', ' ').strip()
        if not src:
            continue
        result = None
        errors = []

        # Force Chinese/Khmer source explicitly instead of relying on a provider's detection.
        detected = _detect_source_language(src, source_language)
        source_codes = [detected]
        if detected != 'zh-CN' and re.search(r'[\u3400-\u9FFF]', src):
            source_codes.insert(0, 'zh-CN')

        for source_code in source_codes:
            try:
                # Google endpoint with explicit tl=km is the primary path here.
                url = (
                    'https://translate.googleapis.com/translate_a/single?client=gtx'
                    f'&sl={urllib.parse.quote(source_code)}&tl=km&dt=t&q='
                    + urllib.parse.quote(src)
                )
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=25) as response:
                    data = json.loads(response.read().decode('utf-8'))
                parts = data[0] if isinstance(data, list) and data else []
                candidate = ''.join(
                    str(part[0]) for part in parts
                    if isinstance(part, list) and part and part[0]
                ).strip()
                if candidate and _translation_is_valid(candidate, 'Khmer'):
                    result = candidate
                    break
                errors.append('Google returned non-Khmer text')
            except Exception as exc:
                errors.append(str(exc))

        if result is None:
            try:
                candidate = _mymemory_translate(src, 'Khmer', 'Chinese' if 'zh-CN' in source_codes else source_language)
                if _translation_is_valid(candidate, 'Khmer'):
                    result = candidate
            except Exception as exc:
                errors.append(f'MyMemory: {exc}')

        if result is None or not _translation_is_valid(result, 'Khmer'):
            failures.append((index, src[:80], '; '.join(errors[-2:])))
            continue

        out.append({'text': result, 'start': item['start'], 'end': item['end']})

    if failures:
        sample = '; '.join(f'#{i}: {src} -> {err}' for i, src, err in failures[:2])
        raise RuntimeError('Voice Clone បកប្រែទៅខ្មែរមិនបាន។ មិនអនុញ្ញាតឱ្យប្រើអត្ថបទចិនដើមជំនួសទេ: ' + sample)
    if not out:
        raise RuntimeError('Voice Clone មិនមានអត្ថបទខ្មែរសម្រាប់បង្កើតសំឡេង')
    return out

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
        raise RuntimeError('FFmpeg បញ្ចូល Caption មិនបាន:\n\n' + error[-5000:])
    return output_path

def extract_audio(video_path, output_wav):
    try:
        import av
        container = av.open(video_path)
        stream = next((s for s in container.streams if s.type == 'audio'), None)
        if stream is None:
            raise RuntimeError('រកមិនឃើញ Audio ក្នុងវីដេអូ')
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
            raise RuntimeError('Audio ទទេ')
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
            raise RuntimeError('មិនអាច Extract Audio បាន:\n\n' + error[-4000:])
        return output_wav

def free_tts(text, output_mp3, language='km'):
    text = text.strip()
    if not text:
        raise ValueError('សូមបញ្ចូលអត្ថបទ')
    tts = gTTS(text=text, lang=language, slow=False)
    tts.save(output_mp3)
    return output_mp3

def edge_tts_voice(text, output_mp3, voice, rate='+0%', pitch='+0Hz'):
    text = text.strip()
    if not text:
        raise ValueError('សូមបញ្ចូលអត្ថបទ')
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError('សូមបន្ថែម edge-tts ក្នុង requirements.txt')

    async def run():
        last = None
        for _ in range(3):
            try:
                communicate = edge_tts.Communicate(
                    text, voice, rate=rate, pitch=pitch, volume='+0%'
                )
                await communicate.save(output_mp3)
                if os.path.isfile(output_mp3) and os.path.getsize(output_mp3) > 1000:
                    return
            except Exception as e:
                last = e
                await asyncio.sleep(1)
        raise RuntimeError(f'Khmer Neural Voice មិនបានបង្កើតសំឡេង: {last}')

    asyncio.run(run())
    return output_mp3

def natural_rate_for_duration(text, target_seconds):
    # Human-like Khmer pacing: avoid aggressive speed changes that make AI speech sound robotic.
    chars = max(1, len(re.sub(r'\s+', '', text)))
    natural_seconds = max(0.9, chars / 6.2)
    ratio = natural_seconds / max(0.35, target_seconds)
    percent = int(round((ratio - 1.0) * 100))
    # Keep Edge Neural prosody close to normal human speech.
    percent = max(-18, min(18, percent))
    return f'{percent:+d}%'


def audio_duration(path):
    command=[ffmpeg(), '-i', path, '-f', 'null', '-']
    result=subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text=result.stderr.decode('utf-8', errors='ignore')
    m=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not m:
        return 0.0
    return int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))

def fit_audio_to_duration(input_audio, output_audio, target_seconds):
    target_seconds=max(0.15, float(target_seconds))
    actual=audio_duration(input_audio)
    if actual <= 0:
        raise RuntimeError('រកមិនឃើញរយៈពេលសំឡេង Dubbing')
    ratio=actual/target_seconds
    # Keep time-stretch close to 1.0 so consonants and vowels remain natural.
    filters=[]
    while ratio>1.35:
        filters.append('atempo=1.35'); ratio/=1.35
    while ratio<0.74:
        filters.append('atempo=0.74'); ratio/=0.74
    filters.append(f'atempo={ratio:.6f}')
    # Gentle broadcast-style cleanup: warmth, clarity and controlled dynamics.
    filters.insert(0, 'highpass=f=65')
    filters.insert(1, 'lowpass=f=14000')
    filters.insert(2, 'acompressor=threshold=-20dB:ratio=2.2:attack=18:release=140:makeup=2')
    cmd=[ffmpeg(),'-y','-i',input_audio,'-af',','.join(filters),'-ac','2','-ar','48000',output_audio]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode!=0:
        raise RuntimeError(r.stderr.decode('utf-8',errors='ignore')[-3000:])
    return output_audio

def make_dubbing_audio(groups, voice, temp_dir, total_duration):
    # Generate one natural neural voice per subtitle segment, then fit each segment
    # to its original timing so speech starts/stops with the speaker's timing.
    segment_paths=[]
    for i,item in enumerate(groups):
        raw=os.path.join(temp_dir,f'dub_raw_{i:04d}.mp3')
        fitted=os.path.join(temp_dir,f'dub_fit_{i:04d}.wav')
        target_len = max(0.25, item['end'] - item['start'])
        if voice.startswith('km-KH-'):
            rate = natural_rate_for_duration(item['text'], target_len)
            generated = edge_tts_voice(item['text'], raw, voice, rate=rate, pitch='+0Hz')
        else:
            generated = edge_tts_voice(item['text'], raw, voice)
        # Khmer AI Voice អាចបង្កើតជា WAV ខណៈ fallback អាចជា MP3; ប្រើ path ដែលបាន return ពិតៗ
        source_audio = generated if generated and os.path.isfile(generated) else raw
        if not os.path.isfile(source_audio):
            raise RuntimeError('មិនបានបង្កើតសំឡេង Dubbing សម្រាប់ប្រយោគនេះ')
        fit_audio_to_duration(source_audio, fitted, max(0.25,item['end']-item['start']))
        segment_paths.append((item['start'], fitted))
    silent=os.path.join(temp_dir,'dub_silent.wav')
    cmd=[ffmpeg(),'-y','-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo', '-t',str(max(total_duration,0.1)), '-c:a','pcm_s16le',silent]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode!=0: raise RuntimeError('បង្កើត timeline សំឡេងមិនបាន')
    inputs=['-i',silent]
    for _,path in segment_paths: inputs += ['-i',path]
    filters=[]
    labels=[]
    for idx,(start,_) in enumerate(segment_paths, start=1):
        label=f'a{idx}'
        filters.append(f'[{idx}:a]adelay={int(start*1000)}:all=1[{label}]')
        labels.append(f'[{label}]')
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0[dub]')
    out=os.path.join(temp_dir,'dubbing.wav')
    cmd=[ffmpeg(),'-y']+inputs+['-filter_complex',';'.join(filters),'-map','[dub]','-t',str(total_duration),'-c:a','pcm_s16le',out]
    r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode!=0: raise RuntimeError(r.stderr.decode('utf-8',errors='ignore')[-4000:])
    return out

def extract_music_without_dialogue(video_path, output_audio):
    # Stereo: cancel center-panned dialogue while retaining side/background music.
    # Mono: keep only a quiet background bed so the original speech does not dominate.
    probe = subprocess.run([ffmpeg(), '-i', video_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    info = probe.stderr.decode('utf-8', errors='ignore')
    stereo = bool(re.search(r'Audio:.*(?:stereo|2 channels)', info, re.I))
    if stereo:
        af = 'pan=stereo|FL=0.5*FL-0.5*FR|FR=0.5*FR-0.5*FL,volume=1.15'
    else:
        af = 'volume=0.10'
    cmd=[ffmpeg(), '-y', '-i', video_path, '-vn', '-af', af, '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', output_audio]
    r=subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError('មិនអាចរក្សាភ្លេង Background បាន: ' + r.stderr.decode('utf-8', errors='ignore')[-3000:])
    return output_audio

def replace_video_audio(video_path, dubbing_audio, output_path):
    temp_dir=os.path.dirname(output_path)
    music_audio=os.path.join(temp_dir, 'background_music.wav')
    extract_music_without_dialogue(video_path, music_audio)
    cmd=[
        ffmpeg(), '-y', '-i', video_path, '-i', music_audio, '-i', dubbing_audio,
        '-filter_complex',
        '[1:a]volume=0.75[music];[2:a]volume=1.25[dub];'
        '[music][dub]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]',
        '-map','0:v:0','-map','[aout]','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',output_path
    ]
    r=subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError('បញ្ចូលភ្លេងដើម + Dubbing មិនបាន:\n' + r.stderr.decode('utf-8', errors='ignore')[-5000:])
    return output_path

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
    raise RuntimeError('រកមិនឃើញវីដេអូក្នុង Link នេះ')

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



# ============================================================
# VOICE CLONE — VoxCPM2 Remote (additive feature; does not remove AI Dubbing)
# ============================================================
@st.cache_resource(show_spinner=False)
def get_voxcpm_client():
    """Connect to the public Hugging Face VoxCPM-Demo Gradio API.

    The heavy VoxCPM model is NOT installed on Streamlit Cloud. Generation is
    performed by the official OpenBMB demo Space instead.
    """
    try:
        from gradio_client import Client, handle_file
    except ImportError as exc:
        raise RuntimeError('ត្រូវការ gradio_client ក្នុង requirements.txt សម្រាប់ Voice Clone') from exc
    return Client('openbmb/VoxCPM-Demo')


def _save_voxcpm_result(result, output_wav):
    """Normalize Gradio audio output (path/URL/tuple/dict) into a local WAV."""
    import urllib.request
    import numpy as np

    value = result
    if isinstance(value, dict):
        value = value.get('path') or value.get('url') or value.get('value')

    # Some Gradio versions return (sample_rate, numpy_array).
    if isinstance(value, tuple) and len(value) == 2:
        sr, data = value
        try:
            import soundfile as sf
            arr = np.asarray(data)
            sf.write(output_wav, arr, int(sr))
            return output_wav
        except Exception as exc:
            raise RuntimeError(f'VoxCPM audio result មិនអាចសរសេរ WAV: {exc}') from exc

    if hasattr(value, 'path'):
        value = value.path

    if isinstance(value, str):
        if value.startswith('http://') or value.startswith('https://'):
            tmp = output_wav + '.download'
            urllib.request.urlretrieve(value, tmp)
            # The official Space currently returns MP3; ffmpeg converts it.
            result_ff = subprocess.run(
                [ffmpeg(), '-y', '-i', tmp, '-vn', '-ac', '1', '-ar', '16000', output_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if result_ff.returncode != 0:
                raise RuntimeError('VoxCPM remote audio មិនអាចបម្លែងទៅ WAV បាន')
            return output_wav
        if os.path.isfile(value):
            result_ff = subprocess.run(
                [ffmpeg(), '-y', '-i', value, '-vn', '-ac', '1', '-ar', '16000', output_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if result_ff.returncode != 0:
                # It may already be a WAV.
                shutil.copyfile(value, output_wav)
            return output_wav

    raise RuntimeError(f'VoxCPM មិនបានបញ្ជូន audio file ត្រឡប់មកវិញ: {type(result).__name__}')


def voxcpm_remote_clone_segment(text, reference_wav, reference_text, output_wav, control_instruction=''):
    """Generate one cloned-voice segment through the official VoxCPM-Demo API."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text:
        raise ValueError('អត្ថបទសម្រាប់ Voice Clone ទទេ')

    if not os.path.isfile(reference_wav):
        raise RuntimeError('Voice Reference file មិនមាន')

    # Current OpenBMB VoxCPM-Demo exposes the Gradio endpoint /generate with
    # these 8 inputs: text, control, reference audio, prompt-text toggle,
    # prompt text, CFG, normalize, and reference denoise.
    try:
        from gradio_client import handle_file
    except ImportError as exc:
        raise RuntimeError('ត្រូវការ gradio_client សម្រាប់ Voice Clone') from exc

    client = get_voxcpm_client()
    use_prompt_text = bool((reference_text or '').strip())

    # IMPORTANT: New Gradio API expects FileData, not a plain local path.
    # handle_file() creates the required {'path': ..., 'meta': {'_type': 'gradio.FileData'}} payload.
    reference_file = handle_file(reference_wav)

    result = client.predict(
        text,
        (control_instruction or '').strip(),
        reference_file,
        use_prompt_text,
        (reference_text or '').strip() if use_prompt_text else '',
        2.0,
        True,
        False,
        api_name='/generate',
    )
    _save_voxcpm_result(result, output_wav)
    if not os.path.isfile(output_wav) or os.path.getsize(output_wav) < 1000:
        raise RuntimeError('VoxCPM remote មិនបានបង្កើតសំឡេង')
    return output_wav


def make_voice_clone_audio(translated_groups, reference_wav, reference_text, temp_dir, total_duration):
    """Generate cloned-voice segments remotely and place them on the original timeline."""
    timeline = os.path.join(temp_dir, 'voice_clone_timeline.wav')
    segment_files = []

    for i, item in enumerate(translated_groups):
        text = str(item.get('text', '')).strip()
        if not text:
            continue
        start = float(item.get('start', 0.0))
        end = float(item.get('end', start + 0.8))
        if end <= start:
            end = start + 0.8
        raw = os.path.join(temp_dir, f'clone_raw_{i:04d}.wav')
        fitted = os.path.join(temp_dir, f'clone_fit_{i:04d}.wav')
        voxcpm_remote_clone_segment(text, reference_wav, reference_text, raw)
        # Do NOT aggressively squeeze every cloned sentence into the original
        # subtitle duration. That makes VoxCPM speech sound warped/garbled.
        # Keep clone speech close to natural speed; only use gentle time-stretch.
        actual = audio_duration(raw)
        target = max(0.6, end - start)
        ratio = actual / target if actual > 0 else 1.0
        if ratio > 1.25:
            # Cap speed-up at 25%; preserve intelligibility instead of forcing
            # very short Chinese/Khmer segments to play unnaturally fast.
            af = 'atempo=1.25'
        elif ratio < 0.80:
            af = 'atempo=0.80'
        else:
            af = f'atempo={ratio:.6f}'
        cmd_fit = [ffmpeg(), '-y', '-i', raw, '-af', af, '-ac', '1', '-ar', '24000', fitted]
        rr = subprocess.run(cmd_fit, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if rr.returncode != 0:
            raise RuntimeError('Voice Clone audio fitting failed: ' + rr.stderr.decode('utf-8', errors='ignore')[-2000:])
        # Use the real generated duration when it is longer than the subtitle
        # slot; do not cut the cloned words in half.
        generated_end = start + audio_duration(fitted)
        segment_files.append((fitted, start, max(end, generated_end)))

    if not segment_files:
        raise RuntimeError('មិនមានអត្ថបទសម្រាប់ Voice Clone')

    command = [ffmpeg(), '-y', '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-t', str(max(0.2, total_duration)), '-c:a', 'pcm_s16le', timeline]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError('មិនអាចបង្កើត Voice Clone timeline')

    inputs = ['-i', timeline]
    for path, _, _ in segment_files:
        inputs += ['-i', path]
    filters = []
    labels = []
    for idx, (_, start, end) in enumerate(segment_files, start=1):
        label = f'a{idx}'
        filters.append(f'[{idx}:a]adelay={int(start*1000)}:all=1[{label}]')
        labels.append(f'[{label}]')
    filters.append('[0:a]' + ''.join(labels) + f'amix=inputs={len(labels)+1}:duration=longest:normalize=0[vo]')
    mixed = os.path.join(temp_dir, 'voice_clone_mixed.wav')
    command = [ffmpeg(), '-y'] + inputs + ['-filter_complex', ';'.join(filters), '-map', '[vo]', '-t', str(max(0.2, total_duration)), '-ar', '24000', '-ac', '1', mixed]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        err = result.stderr.decode('utf-8', errors='ignore')
        raise RuntimeError('Voice Clone timeline mix failed:\n' + err[-2500:])
    return mixed

with dubbing_slot.container():
    st.markdown('<div class="smey-dubbing-top">', unsafe_allow_html=True)
    with st.expander('🎙️ Dubbing — AI Dubbing + Voice Clone', expanded=True):
        st.caption('🎙️ AI Dubbing មួយកន្លែង — ជ្រើស Dubbing ធម្មតា ឬ Voice Clone។')
        dub_mode = st.radio('🎙️ របៀប Dubbing', ['AI Dubbing ធម្មតា', 'Voice Clone'], horizontal=True, key='dub_mode')

        if dub_mode == 'AI Dubbing ធម្មតា':
                    st.caption('🎙️ Human-like Neural Voice — សំឡេងទន់ ធម្មជាតិ និងកុំឱ្យលឿន/យឺតខ្លាំងពេក។')
                    dub_source = st.selectbox('ភាសាសំឡេងដើម', ['Auto', 'Chinese', 'Khmer'], key='dub_source')
                    dub_target = st.selectbox('ភាសា Dubbing', ['Khmer', 'Chinese', 'English'], key='dub_target')
                    voice_options = {
                        'Khmer': {'🇰🇭 Khmer Neural — Female': 'km-KH-SreymomNeural', '🇰🇭 Khmer Neural — Male': 'km-KH-PisethNeural'},
                        'Chinese': {'ប្រុស': 'zh-CN-YunxiNeural', 'ស្រី': 'zh-CN-XiaoxiaoNeural'},
                        'English': {'ប្រុស': 'en-US-GuyNeural', 'ស្រី': 'en-US-JennyNeural'}
                    }
                    voice_label = st.selectbox('🎤 ជ្រើសសំឡេង', list(voice_options[dub_target].keys()), key='dub_voice')
                    dub_video = st.file_uploader('📤 Upload Video សម្រាប់ Dubbing', type=['mp4','mov','mkv','webm','avi'], key='dub_video')
                    if dub_video:
                        st.video(dub_video)
                    if st.button('🎙️ បង្កើត Dubbing', type='primary', key='dub_button'):
                        if not dub_video:
                            st.warning('សូម Upload Video ជាមុន')
                            st.stop()
                        temp_dir=tempfile.mkdtemp()
                        input_video=os.path.join(temp_dir,'dub_input.mp4')
                        audio_path=os.path.join(temp_dir,'dub_source.wav')
                        output_video=os.path.join(temp_dir,'Smey_AI_Dubbing.mp4')
                        try:
                            with open(input_video,'wb') as f: f.write(dub_video.getbuffer())
                            with st.status('កំពុងបង្កើត Dubbing...', expanded=True) as status:
                                st.write('🎧 1/4 កំពុងស្តាប់សំឡេង និង Word Timing ដោយ Local Whisper (មិនប្រើ Gemini quota)...')
                                extract_audio(input_video,audio_path)
                                words=transcribe_local(audio_path,dub_source if dub_source!='Auto' else None)
                                if not words: raise RuntimeError('រកមិនឃើញ Word Timing')
                                groups=make_groups(words)
                                st.write('🔄 2/4 កំពុងបកប្រែដោយ Free Translation (មិនប្រើ Gemini quota)...')
                                translated=translate_groups(None,groups,dub_target,dub_source)
                                st.write('🎙️ 3/4 កំពុងបង្កើត Neural Voice និង Sync Timing...')
                                total=max((x['end'] for x in groups), default=audio_duration(audio_path))
                                voice=voice_options[dub_target][voice_label]
                                dub_audio=make_dubbing_audio(translated,voice,temp_dir,total)
                                st.write('🎬 4/4 កំពុងប្ដូរសំឡេងចូលវីដេអូ...')
                                replace_video_audio(input_video,dub_audio,output_video)
                                status.update(label='✅ Dubbing រួចរាល់!',state='complete')
                            st.subheader('🎬 Result Dubbing')
                            st.video(output_video)
                            with open(output_video,'rb') as f:
                                dubbing_data = f.read()
                            st.download_button('📥 Download Dubbing MP4', dubbing_data, file_name='Smey_AI_Dubbing.mp4', mime='video/mp4', key='download_dubbing', on_click='ignore')
                            st.info('ℹ️ Human-like Neural Voice: កែល្បឿនតែបន្តិច + កែសំឡេងឱ្យទន់/ច្បាស់ + រក្សា Background Music។ វានៅតែជា AI voice មិនមែនសំឡេងមនុស្សថតផ្ទាល់ទេ។')
                        except Exception as e:
                            st.error(f'❌ Dubbing មិនអាចបញ្ចប់បាន: {e}')



        else:
                    st.info('🎙️ Voice Clone គឺជាមុខងារ Dubbing មួយទៀត។ Upload Voice Reference → Clone Voice → Sync ចូលវីដេអូ។ ប្រើសម្លេងរបស់អ្នក ឬសម្លេងដែលអ្នកមានការអនុញ្ញាត។')
                    clone_source = st.selectbox('ភាសាសំឡេងដើម', ['Auto', 'Chinese', 'Khmer'], key='clone_source')
                    clone_target = st.selectbox('ភាសា Voice Clone Dubbing', ['Khmer', 'Chinese', 'English'], key='clone_target')
                    clone_video = st.file_uploader('📤 Upload Video សម្រាប់ Voice Clone', type=['mp4','mov','mkv','webm','avi'], key='clone_video')
                    clone_reference = st.file_uploader('🎤 Upload Voice Reference', type=['wav','mp3','m4a','aac','ogg','flac'], key='clone_reference')
                    clone_text_hint = st.text_input('📝 Voice Reference Text (Optional)', key='clone_text_hint', placeholder='ទុកទំនេរបាន — App នឹងស្តាប់ Voice Reference ដោយ Whisper ដោយស្វ័យប្រវត្តិ')
                    if clone_video:
                        st.video(clone_video)
                    if clone_reference:
                        st.audio(clone_reference)

                    if st.button('🎙️ Clone Voice + បង្កើត Dubbing', type='primary', key='clone_button'):
                        if not clone_video:
                            st.warning('សូម Upload Video ជាមុន')
                            st.stop()
                        if not clone_reference:
                            st.warning('សូម Upload Voice Reference ជាមុន')
                            st.stop()

                        temp_dir = tempfile.mkdtemp()
                        input_video = os.path.join(temp_dir, 'clone_input.mp4')
                        source_audio = os.path.join(temp_dir, 'clone_source.wav')
                        reference_audio = os.path.join(temp_dir, 'clone_reference.wav')
                        output_video = os.path.join(temp_dir, 'Smey_AI_Voice_Clone.mp4')
                        try:
                            with open(input_video, 'wb') as f:
                                f.write(clone_video.getbuffer())
                            with open(os.path.join(temp_dir, 'reference_upload'), 'wb') as f:
                                f.write(clone_reference.getbuffer())
                            uploaded_reference = os.path.join(temp_dir, 'reference_upload')

                            # Normalize reference audio to WAV for VoxCPM2.
                            result = subprocess.run([ffmpeg(), '-y', '-i', uploaded_reference, '-vn', '-ac', '1', '-ar', '16000', reference_audio], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if result.returncode != 0:
                                raise RuntimeError('Voice Reference audio មិនអាចបម្លែងទៅ WAV បាន')

                            with st.status('កំពុង Clone Voice + Dubbing...', expanded=True) as status:
                                st.write('🎧 1/5 កំពុងស្តាប់សំឡេងដោយ Local Whisper...')
                                extract_audio(input_video, source_audio)
                                words = transcribe_local(source_audio, clone_source if clone_source != 'Auto' else None)
                                if not words:
                                    raise RuntimeError('រកមិនឃើញ Word Timing')
                                groups = make_groups(words)

                                st.write('🔄 2/5 កំពុងបកប្រែដោយ Free Translation...')
                                translated = translate_clone_groups_strict(groups, clone_target, clone_source)
                                if clone_target == 'Khmer' and translated:
                                    st.caption('🇰🇭 Khmer Translation: ' + ' | '.join(x['text'] for x in translated[:3]))

                                st.write('🇰🇭 2/5 បកប្រែទៅជាខ្មែរជាមុនសិន...')
                                st.write('🎙️ 3/5 កំពុង Clone សំឡេងតាម VoxCPM2 Remote (Hugging Face)...')
                                total = max((x['end'] for x in groups), default=audio_duration(source_audio))
                                # VoxCPM-Demo supports prompt-based cloning with reference audio + transcript.
                                # Reference audio is limited to 50 seconds by the official Space,
                                # so keep the upload safely below that limit.
                                reference_text = (clone_text_hint or '').strip()
                                if not reference_text:
                                    st.write('📝 កំពុងស្គាល់អត្ថបទក្នុង Voice Reference ដោយ Local Whisper...')
                                    # Try the selected language first, then Auto, so the user does not
                                    # have to type the reference transcript manually.
                                    ref_attempts = []
                                    if clone_source != 'Auto':
                                        ref_attempts.append(clone_source)
                                    ref_attempts.append('Auto')
                                    for ref_lang in ref_attempts:
                                        try:
                                            candidate = transcribe_reference_text(reference_audio, ref_lang)
                                            if candidate:
                                                reference_text = candidate
                                                break
                                        except Exception:
                                            pass
                                if reference_text:
                                    st.caption(f'📝 Voice Reference Text: {reference_text}')
                                else:
                                    raise RuntimeError('មិនអាចស្គាល់ Voice Reference Text ដោយស្វ័យប្រវត្តិ។ សូមប្រើសំឡេងមនុស្សនិយាយច្បាស់ 5–15 វិនាទី (គ្មានភ្លេង/សំឡេងរំខាន) ឬបញ្ចូល Voice Reference Text ដោយដៃ។')
                                import gc
                                gc.collect()
                                clone_audio = make_voice_clone_audio(translated, reference_audio, reference_text, temp_dir, total)

                                st.write('🎬 4/5 កំពុង Sync + រក្សា Background Music...')
                                replace_video_audio(input_video, clone_audio, output_video)
                                status.update(label='✅ Voice Clone Dubbing រួចរាល់!', state='complete')

                            st.subheader('🎬 Result — Voice Clone')
                            st.video(output_video)
                            with open(output_video, 'rb') as f:
                                clone_data = f.read()
                            st.download_button('📥 Download Voice Clone MP4', clone_data, file_name='Smey_AI_Voice_Clone.mp4', mime='video/mp4', key='download_clone', on_click='ignore')
                            st.caption('Voice Clone Remote: រក្សាសំឡេងធម្មជាតិ មិនបង្ខំល្បឿនខ្លាំងពេក។')
                        except Exception as e:
                            st.error(f'❌ Voice Clone មិនអាចបញ្ចប់បាន: {e}')

