from flask import Flask, request, jsonify
import os, json, base64, io, re
from datetime import datetime

app = Flask(__name__)

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
GEMINI_KEY   = os.environ.get('GEMINI_API_KEY', '')

def sb_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }

def sb_storage_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
    }

@app.after_request
def add_cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    r.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE,OPTIONS'
    return r

@app.route('/')
def index():
    return '雜記本 API ✅'

# ── 規則分類 ──
def auto_classify(text, url='', item_type='text'):
    if item_type == 'image': return 'image'
    s = (text + ' ' + url).lower()
    if any(k in s for k in ['shopee','momo','pchome','蝦皮','amazon','yahoo購物','購物','order','cart']): return 'shopping'
    if any(k in s for k in ['食記','餐廳','菜單','foodpanda','ubereats','外送','美食','好吃','料理']): return 'food'
    if any(k in s for k in ['instagram','facebook','twitter','threads','tiktok','ig.me','fb.com','x.com']): return 'social'
    if any(k in s for k in ['youtube','netflix','twitch','podcast','youtu.be','影片','直播']): return 'media'
    if any(k in s for k in ['新聞','報導','文章','教學','知識','how','why','what']): return 'info'
    if item_type == 'url': return 'url'
    return 'note'

# ── AI 分類 + 摘要 ──
def ai_classify_and_summarize(text, url=''):
    if not GEMINI_KEY: return None, None
    import requests as req
    prompt = f"""分析以下內容，回傳 JSON（不要加其他文字）：
內容：{text[:500]}
網址：{url}

回傳格式：
{{"category": "shopping|food|social|media|info|note|url|image|other", "summary": "一句話摘要（20字以內）"}}"""
    try:
        r = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}',
            json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':0,'maxOutputTokens':100,'thinkingConfig':{'thinkingBudget':0}}},
            timeout=15
        )
        if r.status_code == 200:
            t = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            t = t.replace('```json','').replace('```','').strip()
            d = json.loads(t)
            return d.get('category','other'), d.get('summary','')
    except: pass
    return None, None

# ── 擷取網址預覽 ──
def fetch_url_preview(url):
    import requests as req
    domain = re.sub(r'^https?://(www.)?', '', url).split('/')[0]

    # IG 特別處理（貼文抓不到，顯示固定格式）
    if re.search(r'instagram\.com/p/', url) or re.search(r'instagram\.com/tv/', url):
        return {
            'title': 'Instagram 貼文',
            'image': '',
            'description': '點擊查看 Instagram 內容',
            'domain': 'instagram.com',
            'icon': '📸'
        }

    # YouTube 特別處理
    yt_match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)', url)
    if yt_match:
        vid_id = yt_match.group(1)
        try:
            oembed = req.get(f'https://www.youtube.com/oembed?url={url}&format=json', timeout=8)
            if oembed.status_code == 200:
                data = oembed.json()
                return {
                    'title': data.get('title', 'YouTube 影片')[:80],
                    'image': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg',
                    'description': data.get('author_name', ''),
                    'domain': 'youtube.com',
                    'type': 'youtube',
                    'video_id': vid_id,
                }
        except:
            pass
        return {
            'title': 'YouTube 影片',
            'image': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg',
            'description': '',
            'domain': 'youtube.com',
            'type': 'youtube',
            'video_id': vid_id,
        }

    try:
        r = req.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0 (compatible; Twitterbot/1.0)'}, allow_redirects=True)
        html = r.text[:15000]

        title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else url

        og_img = ''
        og_img = ''
        for pat in [
            r"property=['\"]og:image['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"content=['\"]([^'\"]+)['\"][^>]+property=['\"]og:image['\"]",
            r"name=['\"]twitter:image['\"][^>]+content=['\"]([^'\"]+)['\"]",
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m and m.group(1).startswith('http'):
                og_img = m.group(1)
                break

        og_desc = ''
        for pat in [
            r"property=['\"]og:description['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"name=['\"]description['\"][^>]+content=['\"]([^'\"]+)['\"]",
            r"content=['\"]([^'\"]+)['\"][^>]+name=['\"]description['\"]",
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                og_desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:120]
                break

        return {'title': title[:80], 'image': og_img, 'description': og_desc, 'domain': domain, 'icon': shop_icon}
    except Exception as e:
        print(f"[fetch_url_preview] error: {e}")
        return {'title': url[:60], 'image': '', 'description': '', 'domain': domain, 'icon': shop_icon}

# ── 上傳圖片到 Supabase Storage ──
def upload_image(b64_data, filename, user_id):
    import requests as req
    try:
        img_bytes = base64.b64decode(b64_data)
        path = f"{user_id}/{filename}"
        r = req.post(
            f"{SUPABASE_URL}/storage/v1/object/notes-images/{path}",
            headers={**sb_storage_headers(), 'Content-Type': 'image/jpeg'},
            data=img_bytes, timeout=30
        )
        if r.status_code in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/notes-images/{path}"
    except Exception as e:
        print(f"[upload_image] error: {e}")
    return None

# ── 新增筆記 ──
@app.route('/api/notes', methods=['POST', 'OPTIONS'])
def add_note():
    if request.method == 'OPTIONS': return '', 204
    import requests as req

    body = request.json or {}
    user_id   = body.get('user_id', 'default')
    item_type = body.get('type', 'note')  # note|url|image
    content   = body.get('content', '')
    url       = body.get('url', '')
    image_b64 = body.get('image', '')
    tags      = body.get('tags', [])
    use_ai    = body.get('use_ai', False)

    note = {
        'user_id':    user_id,
        'type':       item_type,
        'content':    content,
        'url':        url,
        'tags':       tags,
        'created_at': datetime.utcnow().isoformat(),
        'category':   'other',
        'summary':    '',
        'preview':    {},
        'image_url':  '',
    }

    # 處理圖片上傳
    if item_type == 'image' and image_b64:
        fname = f"{int(datetime.utcnow().timestamp())}.jpg"
        # 轉 JPEG
        try:
            from PIL import Image, ImageOps
            img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB','L'): img = img.convert('RGB')
            w, h = img.size
            if max(w,h) > 1920:
                r = 1920/max(w,h)
                img = img.resize((int(w*r),int(h*r)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            image_b64 = base64.b64encode(buf.getvalue()).decode()
        except: pass
        img_url = upload_image(image_b64, fname, user_id)
        if img_url: note['image_url'] = img_url
        note['category'] = 'image'

    # 處理網址預覽
    elif item_type == 'url' and url:
        preview = fetch_url_preview(url)
        note['preview'] = preview
        note['content'] = preview.get('title', url)
        note['category'] = auto_classify(preview.get('title','') + ' ' + preview.get('description',''), url, 'url')

    # 文字筆記
    else:
        note['category'] = auto_classify(content, '', item_type)

    # AI 分類和摘要（可選）
    if use_ai and GEMINI_KEY and item_type != 'image':
        ai_cat, ai_sum = ai_classify_and_summarize(content or note['content'], url)
        if ai_cat: note['category'] = ai_cat
        if ai_sum: note['summary'] = ai_sum

    # 存到 Supabase
    r = req.post(
        f"{SUPABASE_URL}/rest/v1/notes",
        headers={**sb_headers(), 'Prefer': 'return=representation'},
        json=note, timeout=15
    )
    if r.status_code in (200, 201):
        return jsonify({'success': True, 'note': r.json()[0] if r.json() else note})
    return jsonify({'success': False, 'error': r.text[:200]})

# ── 取得筆記列表 ──
@app.route('/api/notes', methods=['GET'])
def get_notes():
    import requests as req
    user_id  = request.args.get('user_id', 'default')
    category = request.args.get('category', '')
    search   = request.args.get('search', '')
    limit    = request.args.get('limit', 50)

    url = f"{SUPABASE_URL}/rest/v1/notes?user_id=eq.{user_id}&order=created_at.desc&limit={limit}"
    if category: url += f"&category=eq.{category}"

    r = req.get(url, headers=sb_headers(), timeout=15)
    if r.status_code == 200:
        notes = r.json()
        # 前端搜尋
        if search:
            s = search.lower()
            notes = [n for n in notes if
                s in (n.get('content','') or '').lower() or
                s in (n.get('url','') or '').lower() or
                s in (n.get('summary','') or '').lower() or
                any(s in t.lower() for t in (n.get('tags') or []))]
        return jsonify({'success': True, 'notes': notes})
    return jsonify({'success': False, 'error': r.text[:200]})

# ── 刪除筆記 ──
@app.route('/api/notes/<note_id>', methods=['DELETE', 'OPTIONS'])
def delete_note(note_id):
    if request.method == 'OPTIONS': return '', 204
    import requests as req
    r = req.delete(
        f"{SUPABASE_URL}/rest/v1/notes?id=eq.{note_id}",
        headers=sb_headers(), timeout=15
    )
    return jsonify({'success': r.status_code in (200, 204)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port)
