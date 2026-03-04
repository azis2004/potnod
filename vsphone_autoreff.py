"""
TopNod Auto-Reff Bot — Pure VSPhone API
========================================
Jalanin di Railway / Render / Koyeb tanpa butuh ADB lokal.
Semua kontrol lewat VSPhone HTTP API.

REQUIREMENTS:
    pip install requests opencv-python-headless numpy pillow pytesseract beautifulsoup4 hmac

ENV VARIABLES (set di Railway):
    VSPHONE_ACCESS_KEY  = Access Key ID lo
    VSPHONE_SECRET_KEY  = Secret Access Key lo
    VSPHONE_HOST        = api.vsphone.com
    PAD_CODES           = AC11010000031,AC11010000032  (pisah koma)
    ACCOUNTS_TARGET     = 50
"""

import os
import re
import io
import json
import time
import hmac
import hashlib
import random
import string
import requests
import logging
import numpy as np
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urlencode

try:
    import cv2
    from PIL import Image
    import pytesseract
    OCR_OK = True
except ImportError:
    OCR_OK = False

# ============================================================
#  CONFIG — dari Environment Variables (Railway)
# ============================================================

ACCESS_KEY = os.getenv("VSPHONE_ACCESS_KEY", "PS9jcJCkqIYi79PnOzXoEFDrPxsfXOXB")
SECRET_KEY = os.getenv("VSPHONE_SECRET_KEY", "iugve27EONOZ9Hl1JvvYEWKa")
HOST       = os.getenv("VSPHONE_HOST", "api.vsphone.com")
API_BASE   = f"https://{HOST}"

PAD_CODES = [
    p.strip()
    for p in os.getenv("PAD_CODES", "ISIKAN_PAD_CODE_LO").split(",")
    if p.strip()
]

ACCOUNTS_TARGET = int(os.getenv("ACCOUNTS_TARGET", "50"))
REFF_PER_MASTER = 5
AKUN_PER_VSP    = 2

APK_URL     = "https://statistic.topnod.com/TopNod.apk"
APK_LOCAL   = "/sdcard/Download/TopNod.apk"
OUTPUT_FILE = "akun_topnod.json"

# ============================================================
#  LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("topnod")

def loginfo(msg): log.info(msg)
def logerr(msg):  log.error(f"❌ {msg}")

# ============================================================
#  VSPHONE API — AK/SK Authentication
# ============================================================

def _sign_request(method, path, params=None, body=None):
    """
    Generate signature untuk VSPhone AK/SK auth.
    Format: HMAC-SHA256 dari canonical string.
    """
    timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    nonce     = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

    # Canonical string: method + path + timestamp + nonce + sorted params
    canonical_parts = [method.upper(), path, timestamp, nonce]

    if params:
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        canonical_parts.append(sorted_params)

    if body:
        body_str = json.dumps(body, separators=(',', ':'), sort_keys=True)
        canonical_parts.append(body_str)

    canonical = "\n".join(canonical_parts)

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-Access-Key"  : ACCESS_KEY,
        "X-Timestamp"   : timestamp,
        "X-Nonce"       : nonce,
        "X-Signature"   : signature,
        "Content-Type"  : "application/json",
    }

def api(endpoint, payload=None, method="POST"):
    """Generic VSPhone API call dengan AK/SK auth."""
    url     = f"{API_BASE}{endpoint}"
    headers = _sign_request(method, endpoint, body=payload)

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=payload, timeout=30)
        else:
            r = requests.post(url, headers=headers, json=payload or {}, timeout=30)

        # Coba parse response
        try:
            data = r.json()
        except:
            logerr(f"Non-JSON response: {r.text[:200]}")
            return None

        # VSPhone bisa return code 200 (HTTP) dengan data.code berbeda
        code = data.get("code") or data.get("status") or data.get("retCode")
        if str(code) in ("200", "0", "success"):
            return data.get("data") or data.get("result") or data
        else:
            logerr(f"API {endpoint}: code={code} msg={data.get('msg', data.get('message', '?'))}")
            return None

    except Exception as e:
        logerr(f"Request {endpoint}: {e}")
        return None

# ── Device management ─────────────────────────────────────

def enable_adb(pad_code):
    api("/vsphone/api/padApi/adb/enable", {"padCode": pad_code, "enable": True})
    time.sleep(2)

def reset_device(pad_code):
    loginfo(f"Reset device {pad_code}...")
    api("/vsphone/api/padApi/replacePad", {"padCode": pad_code, "countryCode": "ID"})
    time.sleep(15)

def install_apk(pad_code):
    """Download + install APK di dalam cloud device via shell command."""
    loginfo("Download APK...")
    api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": f"wget -O {APK_LOCAL} '{APK_URL}'"
    })
    time.sleep(20)

    loginfo("Install APK...")
    api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": f"pm install -r {APK_LOCAL}"
    })
    time.sleep(8)

def get_package_name(pad_code):
    """Detect package name TopNod."""
    result = api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": "pm list packages | grep -i topnod"
    })
    time.sleep(3)
    if result:
        out = str(result)
        m = re.search(r'package:([\w.]+)', out)
        if m:
            pkg = m.group(1)
            loginfo(f"Package: {pkg}")
            return pkg
    return "com.topnod.app"

# ── Touch & Input via API ─────────────────────────────────

def tap(pad_code, x, y):
    """Tap koordinat via VSPhone simulateTouch API."""
    api("/vsphone/api/padApi/simulateTouch", {
        "padCode"  : pad_code,
        "x"        : x,
        "y"        : y,
        "eventType": 0   # 0 = tap
    })
    time.sleep(random.uniform(1.5, 2.5))

def swipe(pad_code, x1, y1, x2, y2, duration=800):
    """Swipe dari titik A ke B."""
    api("/vsphone/api/padApi/simulateTouch", {
        "padCode"    : pad_code,
        "startX"     : x1,
        "startY"     : y1,
        "endX"       : x2,
        "endY"       : y2,
        "duration"   : duration,
        "eventType"  : 1   # 1 = swipe
    })
    time.sleep(1)

def input_text(pad_code, text):
    """Input teks via ADB shell command."""
    escaped = text.replace(" ", "%s").replace("@", "\\@").replace(".", "\\.")
    api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": f"input text '{escaped}'"
    })
    time.sleep(1)

def open_app(pad_code, package):
    """Buka aplikasi."""
    loginfo(f"Buka {package}")
    api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": f"monkey -p {package} 1"
    })
    time.sleep(4)

def clear_app(pad_code, package):
    """Clear data app (= logout otomatis)."""
    api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": f"pm clear {package}"
    })
    time.sleep(2)

def read_clipboard(pad_code):
    """Baca isi clipboard."""
    result = api("/vsphone/api/padApi/asyncCmd", {
        "padCodes": [pad_code],
        "cmd": "dumpsys clipboard 2>/dev/null | grep -o 'text=[^ ]*' | head -1"
    })
    time.sleep(2)
    if result:
        out = str(result)
        m = re.search(r'text=([A-Z0-9_]{6,25})', out)
        if m:
            return m.group(1)
    return None

# ── Screenshot & OCR ─────────────────────────────────────

def get_screenshot(pad_code):
    """
    Ambil screenshot dari VSPhone API.
    Return: numpy array BGR atau None.
    """
    result = api("/vsphone/api/padApi/getLongGenerateUrl", {
        "padCodes": [pad_code]
    })
    if not result:
        return None
    try:
        url = result[0].get("url", "") if isinstance(result, list) else result.get("url", "")
        if not url:
            return None
        r = requests.get(url, timeout=15)
        arr = np.frombuffer(r.content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        logerr(f"Screenshot error: {e}")
        return None

def ocr_region(img, x, y, w, h, config="--psm 6"):
    """OCR area tertentu dari screenshot."""
    if not OCR_OK or img is None:
        return ""
    crop   = img[y:y+h, x:x+w]
    gray   = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, th  = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return pytesseract.image_to_string(Image.fromarray(th), config=config)

def get_spins_left(pad_code):
    """Baca jumlah spin tersisa dari layar."""
    screen = get_screenshot(pad_code)
    if screen is None:
        return 1
    # Area tengah roda SPIN: "X left"
    text = ocr_region(screen, 250, 580, 200, 100, "--psm 7")
    m = re.search(r'(\d+)\s*left', text, re.IGNORECASE)
    return int(m.group(1)) if m else 0

# ============================================================
#  SLIDE CAPTCHA SOLVER — via screenshot + API swipe
# ============================================================

def find_gap_x(bg_img):
    """Deteksi posisi gap di background captcha (3 method voting)."""
    h, w   = bg_img.shape[:2]
    margin = int(w * 0.15)
    candidates = []

    gray    = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Method 1: Canny edge
    edges = cv2.Canny(blurred, 30, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) < 400:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        if x < margin:
            continue
        ratio = cw / ch if ch > 0 else 0
        if 0.5 < ratio < 2.0:
            candidates.append((x + cw // 2, cv2.contourArea(cnt)))

    # Method 2: Brightness drop
    col_b = np.mean(blurred, axis=0)
    cb_n  = (col_b - col_b.min()) / (col_b.max() - col_b.min() + 1e-6)
    for x in range(margin, w - margin):
        if cb_n[x] < 0.35:
            candidates.append((x, (0.35 - cb_n[x]) * 1000))

    # Method 3: Laplacian
    lap    = cv2.Laplacian(blurred, cv2.CV_64F)
    colVar = np.var(np.absolute(lap), axis=0)
    colVar[:margin] = colVar[-margin:] = 0
    peak = int(np.argmax(colVar))
    if peak > margin:
        candidates.append((peak, float(colVar[peak])))

    if not candidates:
        return w // 2

    # Vote by clustering
    clusters = {}
    for cx, score in candidates:
        b = (cx // 30) * 30
        if b not in clusters:
            clusters[b] = {"xs": [], "score": 0}
        clusters[b]["xs"].append(cx)
        clusters[b]["score"] += score

    best = max(clusters.values(), key=lambda v: (len(v["xs"]), v["score"]))
    return int(sum(best["xs"]) / len(best["xs"]))

def solve_captcha(pad_code):
    """
    Solve slide captcha via screenshot + VSPhone swipe API.
    Koordinat dari screenshot asli TopNod.
    """
    # Koordinat di layar (720px wide device)
    BG_X, BG_Y, BG_W, BG_H       = 165, 535, 370, 440  # area background captcha
    PIECE_X, PIECE_Y              = 90, 760              # posisi puzzle piece
    SLIDER_X, SLIDER_Y            = 137, 1053            # posisi tombol >>

    for attempt in range(3):
        loginfo(f"Captcha attempt {attempt+1}/3...")
        screen = get_screenshot(pad_code)
        if screen is None:
            time.sleep(2)
            continue

        bg_crop = screen[BG_Y:BG_Y+BG_H, BG_X:BG_X+BG_W]

        # Deteksi gap
        gap_rel_x  = find_gap_x(bg_crop)
        gap_abs_x  = BG_X + gap_rel_x
        distance   = gap_abs_x - PIECE_X + random.randint(-4, 4)

        loginfo(f"Gap di x={gap_abs_x}, swipe {distance}px")

        # Human-like swipe: pecah jadi beberapa step
        steps    = 8
        cur_x    = SLIDER_X
        target_x = SLIDER_X + distance

        for i in range(steps):
            t_cur  = i / steps
            t_next = (i + 1) / steps
            e_cur  = 3*t_cur**2  - 2*t_cur**3
            e_next = 3*t_next**2 - 2*t_next**3
            step_d = int((e_next - e_cur) * distance)
            next_x = cur_x + step_d
            dur    = int(60 + 50 * abs(0.5 - t_cur))
            swipe(pad_code, cur_x, SLIDER_Y, next_x, SLIDER_Y, dur)
            cur_x  = next_x

        time.sleep(2.5)

        # Verifikasi: screenshot lagi, cek apakah captcha hilang
        screen2 = get_screenshot(pad_code)
        if screen2 is not None:
            diff = cv2.absdiff(
                cv2.resize(screen[BG_Y:BG_Y+BG_H, BG_X:BG_X+BG_W], (100, 50)),
                cv2.resize(screen2[BG_Y:BG_Y+BG_H, BG_X:BG_X+BG_W], (100, 50))
            )
            if diff.mean() > 10:
                loginfo("✅ Captcha solved!")
                return True

        time.sleep(1.5)

    logerr("Captcha gagal setelah 3 attempts")
    return False

# ============================================================
#  KUKU.LU EMAIL — 283+ Domain Rotation
# ============================================================

_KUKULU_BASE    = "https://m.kuku.lu"
_kukulu_session = requests.Session()
_kukulu_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36"
})
_all_domains  = []
_used_domains = []

PRIORITY_DOMAIN  = "boxfi.uk"
FALLBACK_DOMAINS = [
    "6url.com", "r4.im", "x24.im", "vomoto.com",
    "urhen.com", "kuku.lu", "ae.ge", "ahk.jp",
]

def _kukulu_init():
    global _all_domains
    try:
        r    = _kukulu_session.get(f"{_KUKULU_BASE}/en.php", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        sel  = soup.find("select", {"name": "domain"})
        if sel:
            _all_domains = [o.get("value","") for o in sel.find_all("option") if o.get("value")]
            loginfo(f"kuku.lu: {len(_all_domains)} domain tersedia")
    except Exception as e:
        logerr(f"kuku.lu init: {e}")
        _all_domains = [PRIORITY_DOMAIN] + FALLBACK_DOMAINS

def _rand_str(n): return ''.join(random.choices(string.ascii_lowercase, k=n))
def _rand_num(n): return ''.join(random.choices(string.digits, k=n))

def get_temp_email():
    global _used_domains
    if not _all_domains:
        _kukulu_init()

    # 80% boxfi.uk, 20% domain lain
    domain = PRIORITY_DOMAIN if random.random() < 0.8 else \
             random.choice([d for d in _all_domains if d not in _used_domains[-10:]] or FALLBACK_DOMAINS)

    _used_domains.append(domain)
    username   = _rand_str(8) + _rand_num(4)
    email_addr = f"{username}@{domain}"

    # Register di kuku.lu
    try:
        _kukulu_session.post(f"{_KUKULU_BASE}/create.php", data={
            "address": username, "domain": domain
        }, timeout=10, allow_redirects=True)
    except:
        pass

    loginfo(f"Email: {email_addr}")
    return email_addr, {"email": email_addr, "user": username, "domain": domain}

def check_inbox(meta, timeout=120):
    """Poll inbox kuku.lu sampai email OTP datang."""
    user   = meta["user"]
    domain = meta["domain"]
    loginfo(f"Tunggu OTP di {meta['email']}...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            r = _kukulu_session.get(
                f"{_KUKULU_BASE}/inbox.php",
                params={"address": user, "domain": domain},
                timeout=10
            )
            soup  = BeautifulSoup(r.text, "html.parser")
            items = soup.find_all("div", class_="mail") or \
                    soup.find_all("tr", class_=re.compile("mail"))
            if items:
                link = items[0].find("a")
                if link and link.get("href"):
                    href = link["href"]
                    if not href.startswith("http"):
                        href = f"{_KUKULU_BASE}/{href}"
                    r2   = _kukulu_session.get(href, timeout=10)
                    soup2 = BeautifulSoup(r2.text, "html.parser")
                    body  = soup2.find("div", class_=re.compile("body|content|message"))
                    return body.get_text(" ", strip=True) if body else r2.text
        except:
            pass
        time.sleep(6)

    logerr("Timeout inbox")
    return None

def extract_otp(body):
    m = re.findall(r'\b\d{4,6}\b', body or "")
    if m:
        loginfo(f"OTP: {m[0]}")
        return m[0]
    return None

# ============================================================
#  UI COORDINATES (dari screenshot asli TopNod, 720px wide)
# ============================================================

UI = {
    # Create wallet
    "field_email"    : (353, 490),
    "field_otp"      : (353, 660),
    "field_referral" : (353, 835),
    "btn_next"       : (353, 1007),

    # Set password
    "field_password" : (353, 620),
    "field_confirm"  : (353, 880),
    "btn_continue"   : (353, 1355),

    # Biometric
    "btn_skip"       : (611, 140),
    "btn_setup_later": (353, 1355),

    # Home & event
    "banner_event"   : (353, 210),

    # Spin
    "btn_spin"       : (353, 660),
    "btn_claim"      : (551, 1330),
    "btn_ok"         : (353, 955),

    # Invite popup
    "btn_invite"     : (563, 1023),
    "icon_copy_reff" : (463, 1152),
    "btn_close_popup": (637, 670),
}

def generate_password():
    return _rand_str(6).capitalize() + _rand_num(4) + "!"

# ============================================================
#  SAVE ACCOUNTS
# ============================================================

def save_account(data):
    accounts = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                accounts = json.load(f)
        except:
            pass
    accounts.append(data)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)

# ============================================================
#  CORE FLOWS
# ============================================================

def navigate_to_spin(pad_code):
    tap(pad_code, *UI["banner_event"])
    time.sleep(3)

def claim_and_spin_once(pad_code):
    """Claim 1 spin (untuk akun reff baru) dan spin."""
    tap(pad_code, *UI["btn_claim"])
    time.sleep(2)
    tap(pad_code, *UI["btn_ok"])
    time.sleep(2)
    loginfo("Spin!")
    tap(pad_code, *UI["btn_spin"])
    time.sleep(5)
    tap(pad_code, 353, 800)   # close result popup
    time.sleep(1)

def spin_all(pad_code):
    """Spin semua spin tersedia (untuk akun utama)."""
    for _ in range(REFF_PER_MASTER + 2):
        spins = get_spins_left(pad_code)
        if spins == 0:
            loginfo("Semua spin habis.")
            break
        loginfo(f"Spin! ({spins} tersisa)")
        tap(pad_code, *UI["btn_spin"])
        time.sleep(5)
        tap(pad_code, 353, 800)
        time.sleep(1)

def get_reff_code(pad_code):
    """Ambil referral code akun saat ini via Invite → copy."""
    loginfo("Ambil referral code...")
    tap(pad_code, *UI["btn_invite"])
    time.sleep(2)
    tap(pad_code, *UI["icon_copy_reff"])
    time.sleep(1)

    code = read_clipboard(pad_code)

    # Fallback: OCR
    if not code:
        screen = get_screenshot(pad_code)
        if screen is not None:
            text = ocr_region(screen, 75, 1110, 460, 75, "--psm 7")
            m    = re.search(r'[A-Z][A-Z0-9_]{5,20}', text)
            if m:
                code = m.group(0)

    tap(pad_code, *UI["btn_close_popup"])
    time.sleep(1)

    if code:
        loginfo(f"Referral code: {code}")
    else:
        logerr("Gagal ambil referral code!")

    return code

def _do_register(pad_code, pkg, email, meta, reff_code=""):
    """
    Core registration flow.
    Return: (success, password) atau (False, None)
    """
    clear_app(pad_code, pkg)
    open_app(pad_code, pkg)
    time.sleep(4)

    # Isi email
    tap(pad_code, *UI["field_email"])
    input_text(pad_code, email)

    # Isi 
