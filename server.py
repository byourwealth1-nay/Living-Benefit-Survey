#!/usr/bin/env python3
"""Living Benefits Survey V2 local demo server. Python 3.10+, no third-party dependencies.

Not a production deployment: see README for required security/compliance controls.
"""
import base64
import hashlib
import hmac
import http.cookies
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get('SURVEY_DB', str(BASE / 'data' / 'living_benefits.sqlite3')))
WEB = BASE / 'web'
HOST = os.environ.get('SURVEY_HOST', '127.0.0.1')
PORT = int(os.environ.get('SURVEY_PORT', '8787'))
SECURE_COOKIES = os.environ.get('SURVEY_SECURE_COOKIES', '') == '1'
SESSION_AGE = 8 * 3600
INVITE_AGE = 7 * 86400
MAX_JSON = 200_000
CONSENT_VERSION = '2026-10-v1-DEMO'
NOW = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')
DISEASES = ['โรคมะเร็ง', 'โรคปอดระยะสุดท้าย', 'โรคไตวายเรื้อรัง', 'โรคหลอดเลือดสมองแตก ตีบ หรืออุดตัน', 'กล้ามเนื้อหัวใจตายจากการขาดเลือด', 'โรคอัลไซเมอร์', 'โรคอื่น ๆ']
BEHAVIORS = ['สูบบุหรี่ หรือได้รับมลพิษจากบุหรี่', 'ดื่มแอลกอฮอล์ เหล้า เบียร์', 'กินไม่เลือก กินรสจัด หวาน มัน เค็ม', 'ไม่ออกกำลังกาย หรือออกกำลังกายไม่เพียงพอ', 'เครียดบ่อย และภาวะจิตใจที่แย่ลง', 'ครอบครัวมีประวัติป่วยด้วยกลุ่มโรคร้ายแรง']
TEXT_KEYS = ['customer', 'age', 'phone', 'advisor', 'advisorPhone', 'otherDisease', 'responsible', 'housePayment', 'houseBalance', 'carPayment', 'carBalance', 'household', 'educationSemester', 'termsPerYear', 'parents', 'travel', 'others', 'reserveYears', 'desiredOverride', 'ciOnce', 'ciRepeat', 'ciDailyFund', 'ciDailyRate']
MONEY_KEYS = ['housePayment', 'houseBalance', 'carPayment', 'carBalance', 'household', 'educationSemester', 'parents', 'travel', 'others', 'desiredOverride', 'ciOnce', 'ciRepeat', 'ciDailyFund', 'ciDailyRate']


def connect():
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('PRAGMA busy_timeout = 5000')
    return con


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try: os.chmod(DB.parent, 0o700)
        except OSError: pass
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, salt TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL, FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS surveys (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('advisor','customer')), status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','revoked')), token_hash TEXT UNIQUE, expires_at INTEGER, created_at TEXT NOT NULL, completed_at TEXT, consent_version TEXT, consent_at TEXT, response_json TEXT, monthly REAL NOT NULL DEFAULT 0, desired REAL NOT NULL DEFAULT 0, covered REAL NOT NULL DEFAULT 0, gap REAL NOT NULL DEFAULT 0, FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_surveys_customer ON surveys(customer_id);
        CREATE INDEX IF NOT EXISTS idx_surveys_status ON surveys(status);
        ''')
    if os.name != 'nt' and DB.exists():
        try: os.chmod(DB, 0o600)
        except OSError: pass


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 420_000).hex()


def setup():
    import getpass
    initialize()
    with connect() as db:
        if db.execute('SELECT COUNT(*) n FROM admins').fetchone()['n']:
            print('มีบัญชีผู้ดูแลอยู่แล้ว ไม่สร้างทับ (database:', DB, ')')
            return
    username = input('ชื่อผู้ใช้สำหรับที่ปรึกษา [advisor]: ').strip() or 'advisor'
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,40}', username):
        sys.exit('ชื่อผู้ใช้ต้องยาว 3–40 ตัวและเป็น a-z, 0-9, _, ., -')
    password = getpass.getpass('ตั้งรหัสผ่าน (อย่างน้อย 12 ตัว): ')
    if len(password) < 12 or len(password) > 256:
        sys.exit('รหัสผ่านต้องยาว 12–256 ตัวอักษร')
    if password != getpass.getpass('ยืนยันรหัสผ่าน: '):
        sys.exit('รหัสผ่านไม่ตรงกัน')
    salt = secrets.token_hex(16)
    with connect() as db:
        db.execute('INSERT INTO admins(username,salt,password_hash,created_at) VALUES(?,?,?,?)', (username, salt, password_hash(password, salt), NOW()))
    print('สร้างบัญชีสำเร็จ: ', username, '\nเปิดแอปโดยรัน: python3 server.py')


def clean_string(value, length=200):
    if not isinstance(value, str): raise ValueError('ข้อมูลข้อความไม่ถูกต้อง')
    value = value.strip()
    if len(value) > length: raise ValueError('ข้อมูลยาวเกินกำหนด')
    return value


def number(value, maximum=1_000_000_000_000):
    if not isinstance(value, (str, int, float)): raise ValueError('ตัวเลขไม่ถูกต้อง')
    try: v = float(str(value).replace(',', '').strip() or '0')
    except ValueError: raise ValueError('ตัวเลขไม่ถูกต้อง')
    if not (0 <= v <= maximum) or not __import__('math').isfinite(v): raise ValueError('ตัวเลขอยู่นอกช่วงที่อนุญาต')
    return v


def sanitize_survey(payload):
    if not isinstance(payload, dict): raise ValueError('รูปแบบแบบสอบถามไม่ถูกต้อง')
    data = {k: clean_string(payload.get(k, ''), 200) for k in TEXT_KEYS}
    for k in MONEY_KEYS: number(data[k])
    for k, mx in [('age', 120), ('termsPerYear', 12), ('reserveYears', 100)]:
        if data[k]: number(data[k], mx)
    data['concern'] = payload.get('concern', '')
    data['risk'] = payload.get('risk', '')
    if data['concern'] not in ['', 'worried', 'not-worried']: raise ValueError('ตัวเลือกความกังวลไม่ถูกต้อง')
    if data['risk'] not in ['', 'self', 'transfer']: raise ValueError('ตัวเลือกความเสี่ยงไม่ถูกต้อง')
    for k, allowed in [('diseases', DISEASES), ('behaviors', BEHAVIORS)]:
        arr = payload.get(k, [])
        if not isinstance(arr, list) or len(arr) > len(allowed) or any(x not in allowed for x in arr): raise ValueError('รายการตัวเลือกไม่ถูกต้อง')
        data[k] = list(dict.fromkeys(arr))
    if data['phone'] and not re.fullmatch(r'[0-9+()\-\s]{8,25}', data['phone']): raise ValueError('รูปแบบโทรศัพท์ไม่ถูกต้อง')
    monthly = sum(number(data[k]) for k in ['housePayment','carPayment','household','parents','travel','others']) + number(data['educationSemester']) * number(data['termsPerYear'],12) / 12
    desired = (number(data['desiredOverride']) if data['desiredOverride'] else monthly * 12 * number(data['reserveYears'], 100))
    covered = number(data['ciOnce']) + number(data['ciRepeat'])
    return data, {'monthly': round(monthly,2), 'desired': round(desired,2), 'covered': round(covered,2), 'gap': round(max(0,desired-covered),2)}


class App(BaseHTTPRequestHandler):
    server_version = 'LivingBenefitsDemo/2.0'

    def log_message(self, fmt, *args):
        # Never log URL paths: invitation URLs contain bearer secrets.
        sys.stderr.write('%s - %s %s\n' % (self.address_string(), self.command, self.response_status if hasattr(self, 'response_status') else ''))

    def output(self, status, payload, headers=None):
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf8')
        self.send_response(status)
        self.response_status = status
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.security_headers()
        if headers:
            for k, v in headers.items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(raw)

    def security_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

    def serve_static(self, name, mime):
        path = WEB / name
        if not path.is_file(): return self.output(404, {'error':'ไม่พบไฟล์'})
        blob = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(blob)))
        self.security_headers()
        self.end_headers()
        self.wfile.write(blob)

    def json_body(self):
        if self.headers.get('Content-Type','').split(';')[0].strip().lower() != 'application/json': raise ValueError('รองรับเฉพาะ JSON')
        sz = int(self.headers.get('Content-Length','0'))
        if not 0 < sz <= MAX_JSON: raise ValueError('ขนาดคำขอไม่ถูกต้อง')
        try: return json.loads(self.rfile.read(sz))
        except (UnicodeDecodeError, json.JSONDecodeError): raise ValueError('JSON ไม่ถูกต้อง')

    def session(self):
        try:
            cookie = http.cookies.SimpleCookie()
            cookie.load(self.headers.get('Cookie',''))
            token = cookie['lbs_session'].value
            with connect() as db:
                row = db.execute('SELECT admins.id,admins.username,sessions.csrf_token FROM sessions JOIN admins ON admins.id=sessions.admin_id WHERE sessions.token_hash=? AND sessions.expires_at>?', (hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
                return dict(row) if row else None
        except (KeyError, http.cookies.CookieError): return None

    def authorize(self, mutating=False):
        user = self.session()
        if not user: raise PermissionError('กรุณาเข้าสู่ระบบ')
        if mutating and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''), user['csrf_token']): raise PermissionError('CSRF token ไม่ถูกต้อง')
        return user

    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin:
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            if parsed.netloc != self.headers.get('Host') or parsed.scheme not in ('http','https'):
                raise PermissionError('Origin ไม่ได้รับอนุญาต')

    def request_path(self): return urlsplit(self.path).path

    def do_GET(self):
        path = self.request_path()
        try:
            if path in ('/', '/dashboard'): return self.serve_static('dashboard.html','text/html; charset=utf-8')
            if re.fullmatch(r'/s/[a-zA-Z0-9_-]{24,100}',path): return self.serve_static('survey.html','text/html; charset=utf-8')
            if path == '/app.css': return self.serve_static('app.css','text/css; charset=utf-8')
            if path == '/dashboard.js': return self.serve_static('dashboard.js','text/javascript; charset=utf-8')
            if path == '/api/session':
                u = self.session()
                return self.output(200,{'authenticated': bool(u), 'username': u['username'] if u else None,'csrf': u['csrf_token'] if u else None})
            if path.startswith('/api/invite/'):
                token = path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[A-Za-z0-9_-]{24,100}',token): return self.output(404,{'error':'ไม่พบแบบสำรวจ'})
                with connect() as db:
                    row=db.execute('SELECT id FROM surveys WHERE token_hash=? AND status=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),'pending',int(time.time()))).fetchone()
                    return self.output(200,{'open':bool(row),'consentVersion':CONSENT_VERSION})
            self.authorize()
            if path == '/api/overview':
                with connect() as db:
                    total = db.execute('SELECT COUNT(*) n FROM customers').fetchone()['n']
                    surveys = db.execute("SELECT COUNT(*) n, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) complete, SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending, COALESCE(SUM(CASE WHEN status='completed' THEN gap ELSE 0 END),0) gap FROM surveys").fetchone()
                    rows = db.execute('SELECT s.id,s.customer_id,c.name,c.phone,c.notes,s.mode,s.status,s.created_at,s.completed_at,s.expires_at,s.monthly,s.desired,s.covered,s.gap FROM surveys s JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC LIMIT 1000').fetchall()
                    customers=db.execute('SELECT c.id,c.name,c.phone,c.notes,c.created_at, (SELECT COUNT(*) FROM surveys WHERE customer_id=c.id) survey_count FROM customers c ORDER BY c.id DESC LIMIT 1000').fetchall()
                return self.output(200, {'totals':{'customers':total,'surveys':surveys['n'],'completed':surveys['complete'] or 0,'pending':surveys['pending'] or 0,'gap':surveys['gap']},'surveys':[dict(r) for r in rows],'customers':[dict(r) for r in customers]})
            matched = re.fullmatch(r'/api/surveys/(\d+)',path)
            if matched:
                with connect() as db:
                    row=db.execute('SELECT s.*,c.name,c.phone,c.notes FROM surveys s JOIN customers c ON s.customer_id=c.id WHERE s.id=?',(int(matched.group(1)),)).fetchone()
                if not row: return self.output(404,{'error':'ไม่พบแบบสำรวจ'})
                item=dict(row)
                item.pop('token_hash',None)
                item['response']=json.loads(item.pop('response_json')) if item['response_json'] else None
                return self.output(200,item)
            return self.output(404,{'error':'ไม่พบหน้าที่ร้องขอ'})
        except PermissionError as e: return self.output(401,{'error':str(e)})
        except Exception as e:
            print('GET error:', type(e).__name__,file=sys.stderr)
            return self.output(500,{'error':'เซิร์ฟเวอร์ขัดข้อง'})

    def do_POST(self): self.write_action('POST')
    def do_PATCH(self): self.write_action('PATCH')
    def do_DELETE(self): self.write_action('DELETE')

    def write_action(self, method):
        path = self.request_path()
        try:
            self.check_origin()
            if path == '/api/login' and method == 'POST':
                args=self.json_body()
                username=clean_string(args.get('username',''),40)
                password=args.get('password','')
                if not isinstance(password,str) or len(password)>256: raise ValueError('ข้อมูลไม่ถูกต้อง')
                with connect() as db:
                    row=db.execute('SELECT id,salt,password_hash FROM admins WHERE username=?',(username,)).fetchone()
                    salt=row['salt'] if row else '0'*32
                    actual=password_hash(password,salt)
                    if not row or not hmac.compare_digest(actual,row['password_hash']):
                        # Equal work for unknown username; add a short delay for brute-force mitigation in demo.
                        time.sleep(0.3)
                        return self.output(401,{'error':'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'})
                    token=secrets.token_urlsafe(32)
                    csrf=secrets.token_urlsafe(24)
                    db.execute('DELETE FROM sessions WHERE expires_at < ?', (int(time.time()),))
                    db.execute('INSERT INTO sessions(token_hash,admin_id,csrf_token,expires_at) VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],csrf,int(time.time())+SESSION_AGE))
                cookie=f'lbs_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}'+('; Secure' if SECURE_COOKIES else '')
                return self.output(200,{'ok':True}, {'Set-Cookie':cookie})
            if path.startswith('/api/invite/') and method=='POST':
                token=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[A-Za-z0-9_-]{24,100}',token): return self.output(404,{'error':'ไม่พบแบบสำรวจ'})
                args=self.json_body()
                if not isinstance(args,dict) or args.get('consent') is not True or args.get('consentVersion')!=CONSENT_VERSION: raise ValueError('ต้องให้ความยินยอมตามประกาศฉบับปัจจุบัน')
                data, stats = sanitize_survey(args.get('data'))
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute('SELECT id FROM surveys WHERE token_hash=? AND status=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),'pending',int(time.time()))).fetchone()
                    if not row: return self.output(410,{'error':'ลิงก์หมดอายุหรือถูกใช้แล้ว'})
                    db.execute('UPDATE surveys SET status=?,token_hash=NULL,expires_at=NULL,completed_at=?,consent_at=?,consent_version=?,response_json=?,monthly=?,desired=?,covered=?,gap=? WHERE id=?',('completed',NOW(),NOW(),CONSENT_VERSION,json.dumps(data,ensure_ascii=False),stats['monthly'],stats['desired'],stats['covered'],stats['gap'],row['id']))
                return self.output(200,{'ok':True,'stats':stats})
            self.authorize(mutating=True)
            if path == '/api/logout' and method == 'POST':
                cookie=http.cookies.SimpleCookie();cookie.load(self.headers.get('Cookie',''))
                if 'lbs_session' in cookie:
                    with connect() as db: db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(cookie['lbs_session'].value.encode()).hexdigest(),))
                return self.output(200,{'ok':True},{'Set-Cookie':'lbs_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+('; Secure' if SECURE_COOKIES else '')})
            if path == '/api/customers' and method=='POST':
                args=self.json_body()
                name=clean_string(args.get('name',''),120)
                phone=clean_string(args.get('phone',''),25)
                notes=clean_string(args.get('notes',''),1000)
                if len(name)<2: raise ValueError('โปรดระบุชื่อลูกค้าอย่างน้อย 2 ตัวอักษร')
                if phone and not re.fullmatch(r'[0-9+()\-\s]{8,25}',phone): raise ValueError('หมายเลขโทรศัพท์ไม่ถูกต้อง')
                with connect() as db:
                    cur=db.execute('INSERT INTO customers(name,phone,notes,created_at,updated_at) VALUES(?,?,?,?,?)',(name,phone,notes,NOW(),NOW()))
                    id=cur.lastrowid
                return self.output(201,{'id':id})
            matched=re.fullmatch(r'/api/customers/(\d+)',path)
            if matched and method=='PATCH':
                args=self.json_body()
                name=clean_string(args.get('name',''),120);phone=clean_string(args.get('phone',''),25);notes=clean_string(args.get('notes',''),1000)
                if len(name)<2: raise ValueError('โปรดระบุชื่อลูกค้า')
                if phone and not re.fullmatch(r'[0-9+()\-\s]{8,25}',phone): raise ValueError('หมายเลขโทรศัพท์ไม่ถูกต้อง')
                with connect() as db:
                    cur=db.execute('UPDATE customers SET name=?,phone=?,notes=?,updated_at=? WHERE id=?',(name,phone,notes,NOW(),int(matched.group(1))))
                return self.output(200 if cur.rowcount else 404,{'ok':bool(cur.rowcount)})
            if matched and method=='DELETE':
                with connect() as db:
                    cur=db.execute('DELETE FROM customers WHERE id=?',(int(matched.group(1)),))
                return self.output(200 if cur.rowcount else 404,{'ok':bool(cur.rowcount)})
            if path == '/api/invitations' and method=='POST':
                args=self.json_body()
                id=int(args.get('customerId',0)); mode=args.get('mode')
                if mode not in ('advisor','customer'): raise ValueError('โหมดไม่ถูกต้อง')
                with connect() as db:
                    if not db.execute('SELECT id FROM customers WHERE id=?',(id,)).fetchone(): return self.output(404,{'error':'ไม่พบลูกค้า'})
                    token=secrets.token_urlsafe(32)
                    cur=db.execute('INSERT INTO surveys(customer_id,mode,status,token_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)',(id,mode,'pending',hashlib.sha256(token.encode()).hexdigest(),int(time.time())+INVITE_AGE,NOW()))
                return self.output(201,{'id':cur.lastrowid,'path':'/s/'+token,'expiresInDays':7})
            matched=re.fullmatch(r'/api/surveys/(\d+)/renew',path)
            if matched and method=='POST':
                token=secrets.token_urlsafe(32)
                with connect() as db:
                    cur=db.execute('UPDATE surveys SET token_hash=?,expires_at=? WHERE id=? AND status=?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time())+INVITE_AGE,int(matched.group(1)),'pending'))
                if not cur.rowcount: return self.output(409,{'error':'แบบสำรวจไม่พร้อมสร้างลิงก์ใหม่'})
                return self.output(200,{'path':'/s/'+token,'expiresInDays':7})
            matched=re.fullmatch(r'/api/surveys/(\d+)',path)
            if matched and method=='DELETE':
                with connect() as db:
                    cur=db.execute('UPDATE surveys SET status=?,token_hash=NULL,expires_at=NULL WHERE id=? AND status=?',('revoked',int(matched.group(1)),'pending'))
                if not cur.rowcount: return self.output(409,{'error':'ยกเลิกได้เฉพาะแบบสำรวจที่ยังไม่ส่ง'})
                return self.output(200,{'ok':True})
            return self.output(404,{'error':'ไม่พบคำสั่ง'})
        except PermissionError as e: return self.output(403,{'error':str(e)})
        except (ValueError,TypeError,OverflowError) as e: return self.output(400,{'error':str(e)})
        except Exception as e:
            print('Write error:',type(e).__name__,file=sys.stderr)
            return self.output(500,{'error':'เซิร์ฟเวอร์ขัดข้อง'})


def main():
    initialize()
    with connect() as db:
        if not db.execute('SELECT 1 FROM admins LIMIT 1').fetchone():
            print('ยังไม่ได้สร้างผู้ดูแลระบบ กรุณาเรียก: python3 server.py setup')
            sys.exit(1)
    print(f'Living Benefits Survey V2 → http://{HOST}:{PORT}\nฐานข้อมูล: {DB}\nกด Ctrl+C เพื่อหยุด')
    with ThreadingHTTPServer((HOST,PORT),App) as s:
        try: s.serve_forever()
        except KeyboardInterrupt: print('\nปิดเซิร์ฟเวอร์แล้ว')


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='setup': setup()
    else: main()
