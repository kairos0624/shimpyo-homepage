"""심리상담 쉼표 예약 관리 서버. 운영 시 HTTPS 역방향 프록시 및 환경변수 필수."""
import os, re, sqlite3, secrets, time, json, urllib.parse, urllib.request, urllib.error, logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
KST=ZoneInfo("Asia/Seoul")
def local_today(): return datetime.now(KST).date()
def local_now(): return datetime.now(KST).isoformat(timespec="seconds")
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect, render_template_string, abort
from werkzeug.security import check_password_hash, generate_password_hash

BASE=Path(__file__).resolve().parent
DB=Path(os.environ.get('SHIMPYO_DB_PATH', str(BASE/'private'/'reservations.sqlite3'))).resolve()
ADMIN_PASSWORD=os.environ.get('SHIMPYO_ADMIN_PASSWORD','')
SECRET=os.environ.get('SHIMPYO_SECRET_KEY','')
KAKAO_REST_KEY=os.environ.get('SHIMPYO_KAKAO_REST_KEY','').strip()
KAKAO_CLIENT_SECRET=os.environ.get('SHIMPYO_KAKAO_CLIENT_SECRET','').strip()
KAKAO_REDIRECT_URI=os.environ.get('SHIMPYO_KAKAO_REDIRECT_URI','https://shimpyo-homepage.onrender.com/auth/kakao/callback').strip()
if not ADMIN_PASSWORD or not SECRET or len(SECRET)<32:
    raise RuntimeError('운영 전 SHIMPYO_ADMIN_PASSWORD 와 32자 이상 SHIMPYO_SECRET_KEY 를 설정하세요.')
app=Flask(__name__,static_folder=None)
app.config.update(SECRET_KEY=SECRET,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('SHIMPYO_COOKIE_SECURE','1')=='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=8192)
PASSWORD_HASH=generate_password_hash(ADMIN_PASSWORD)
PROGRAMS=['성인 심리상담','커플·부부·가족 상담','아동·청소년 상담','심리검사','노인 심리상담','집단상담','진로상담','기타 상담']
DB.parent.mkdir(parents=True,exist_ok=True)
def db():
 c=sqlite3.connect(str(DB),timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=10000');return c
with db() as c:
 c.executescript("""CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, receipt TEXT UNIQUE NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, program TEXT NOT NULL, day TEXT NOT NULL, slot TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);CREATE UNIQUE INDEX IF NOT EXISTS one_approved_per_slot ON reservations(day,slot) WHERE status='approved';CREATE INDEX IF NOT EXISTS reservations_by_day ON reservations(day,slot);""")
# 카카오 OAuth 토큰은 현재 SQLite에 저장됩니다. Render Free 재배포 시 소실될 수 있습니다.
with db() as c:
 c.execute("CREATE TABLE IF NOT EXISTS kakao_auth (id INTEGER PRIMARY KEY CHECK(id=1), access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, expires_at INTEGER NOT NULL)")

def kakao_post(url, fields, access_token=None):
 if url=='https://kauth.kakao.com/oauth/token' and KAKAO_CLIENT_SECRET:
  fields={**fields,'client_secret':KAKAO_CLIENT_SECRET}
 payload=urllib.parse.urlencode(fields).encode('utf-8')
 headers={'Content-Type':'application/x-www-form-urlencoded;charset=utf-8'}
 if access_token:headers['Authorization']='Bearer '+access_token
 req=urllib.request.Request(url,data=payload,headers=headers,method='POST')
 with urllib.request.urlopen(req,timeout=4) as resp:return json.loads(resp.read().decode('utf-8'))

def kakao_token():
 with db() as c:
  row=c.execute('SELECT access_token,refresh_token,expires_at FROM kakao_auth WHERE id=1').fetchone()
 if not row:return None
 if row['expires_at']>int(time.time())+120:return row['access_token']
 if not KAKAO_REST_KEY:return None
 result=kakao_post('https://kauth.kakao.com/oauth/token',{'grant_type':'refresh_token','client_id':KAKAO_REST_KEY,'refresh_token':row['refresh_token']})
 access=result['access_token'];refresh=result.get('refresh_token',row['refresh_token'])
 with db() as c:c.execute('UPDATE kakao_auth SET access_token=?,refresh_token=?,expires_at=? WHERE id=1',(access,refresh,int(time.time())+int(result.get('expires_in',21600))))
 return access

def notify_kakao(day,slot):
 try:
  token=kakao_token()
  if not token:return
  message={'object_type':'text','text':f'[쉼표 예약 접수]\n{day} {slot}\n새 예약이 접수되었습니다. 관리자 페이지에서 확인해 주세요.','link':{'web_url':'https://shimpyo-homepage.onrender.com/admin','mobile_web_url':'https://shimpyo-homepage.onrender.com/admin'}}
  result=kakao_post('https://kapi.kakao.com/v2/api/talk/memo/default/send',{'template_object':json.dumps(message,ensure_ascii=False)},token)
  if result.get('result_code')!=0:app.logger.warning('카카오 알림 전송 결과 확인 필요')
 except (urllib.error.URLError,ValueError,KeyError,sqlite3.Error,TimeoutError) as exc:
  app.logger.warning('카카오 알림 실패 (%s)',type(exc).__name__)

# In-memory rate limits apply per process; add proxy/WAF limits in production.
_recent={}
def rate_ok(key,limit,window):
 now=time.monotonic(); entries=[t for t in _recent.get(key,[]) if now-t<window]
 if len(entries)>=limit:return False
 entries.append(now);_recent[key]=entries
 if len(_recent)>10000:_recent.clear()
 return True

def valid_slot(day,slot):
 try:d=date.fromisoformat(day)
 except (ValueError,TypeError):return False
 if d<local_today() or d>local_today()+timedelta(days=180):return False
 if not isinstance(slot,str) or not re.fullmatch(r'\d{2}:00',slot):return False
 hour=int(slot[:2]);return d.weekday()!=6 and ((10<=hour<=21) if d.weekday()<5 else (13<=hour<=21))

@app.after_request
def secure(resp):
 resp.headers['X-Content-Type-Options']='nosniff';resp.headers['Content-Security-Policy']="frame-ancestors 'none'; base-uri 'self'; object-src 'none'";resp.headers['X-Frame-Options']='DENY';resp.headers['Referrer-Policy']='strict-origin-when-cross-origin';resp.headers['Cache-Control']='no-store' if request.path.startswith('/admin') or request.path.startswith('/api') else 'no-cache'
 return resp

@app.post('/api/reservations')
def create():
 ip=request.remote_addr or 'unknown'
 if not rate_ok('reserve:'+ip,8,3600):return jsonify(error='신청 횟수가 많습니다. 잠시 후 다시 시도해 주세요.'),429
 data=request.get_json(silent=True)
 if not isinstance(data,dict):return jsonify(error='신청 정보를 확인해 주세요.'),400
 name=str(data.get('name','')).strip();phone=str(data.get('phone','')).strip();program=data.get('program');day=data.get('date');slot=data.get('time')
 if not 1<=len(name)<=50 or not re.fullmatch(r'[0-9+()\- ]{9,20}',phone) or program not in PROGRAMS or not valid_slot(day,slot) or is_blocked(day,slot) or data.get('consent') is not True:return jsonify(error='성함, 연락처, 상담 종류, 희망 일정과 개인정보 동의를 확인해 주세요.'),400
 with db() as c:
  if c.execute('SELECT 1 FROM reservations WHERE day=? AND slot=? AND status=?',(day,slot,'approved')).fetchone():return jsonify(error='이미 확정된 시간입니다. 다른 시간을 선택해 주세요.'),409
  receipt=secrets.token_hex(5).upper();now=local_now()
  c.execute('INSERT INTO reservations(receipt,name,phone,program,day,slot,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(receipt,name,phone,program,day,slot,now,now))
 notify_kakao(day,slot)
 return jsonify(receipt=receipt,status='pending'),201

def admin_required(fn):
 @wraps(fn)
 def wrapped(*a,**kw):
  if not session.get('admin'):return redirect('/admin/login') if request.method=='GET' else (jsonify(error='로그인이 필요합니다.'),401)
  return fn(*a,**kw)
 return wrapped

def csrf_ok():return secrets.compare_digest(str(session.get('csrf','')),str(request.headers.get('X-CSRF-Token',''))) and bool(session.get('csrf'))

LOGIN="""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>쉼표 관리자 로그인</title><style>body{font-family:system-ui;background:#f7f5ee;color:#3d5341;display:grid;place-items:center;min-height:90vh}form{background:white;padding:35px;border-radius:22px;box-shadow:0 12px 35px #263b2114}input,button{padding:12px;border-radius:10px;font:inherit}button{background:#55735b;color:white;border:0}</style><form method="post"><h2>쉼표 예약 관리</h2><p>센터 관리자 전용</p><input type="password" name="password" required placeholder="관리자 비밀번호" autocomplete="current-password"><button>로그인</button><p style="color:#a24a3d">{{error}}</p></form></html>"""
@app.route('/admin/login',methods=['GET','POST'])
def login():
 error=''
 if request.method=='POST':
  if not rate_ok('login:'+(request.remote_addr or 'unknown'),10,900):error='잠시 후 다시 시도해 주세요.'
  elif admin_password_ok(request.form.get('password','')):
   session.clear();session['admin']=True;session['csrf']=secrets.token_urlsafe(32);audit('login');return redirect('/admin')
  else:error='비밀번호를 확인해 주세요.'
 return render_template_string(LOGIN,error=error)

@app.get('/admin/kakao/connect')
@admin_required
def kakao_connect():
 if not KAKAO_REST_KEY:return 'Render에 SHIMPYO_KAKAO_REST_KEY를 먼저 설정해 주세요.',503
 state=secrets.token_urlsafe(32)
 session['kakao_oauth_state']=state
 params={'client_id':KAKAO_REST_KEY,'redirect_uri':KAKAO_REDIRECT_URI,'response_type':'code','state':state,'scope':'talk_message'}
 return redirect('https://kauth.kakao.com/oauth/authorize?'+urllib.parse.urlencode(params))

@app.get('/auth/kakao/callback')
def kakao_callback():
 state=request.args.get('state','')
 expected=session.pop('kakao_oauth_state',None)
 if not expected or not secrets.compare_digest(state,expected) or not session.get('admin'):abort(403)
 code=request.args.get('code','')
 if not code:return '카카오 연결이 취소되었거나 인증 코드를 받지 못했습니다.',400
 try:
  result=kakao_post('https://kauth.kakao.com/oauth/token',{'grant_type':'authorization_code','client_id':KAKAO_REST_KEY,'redirect_uri':KAKAO_REDIRECT_URI,'code':code})
  access=result['access_token'];refresh=result['refresh_token']
  with db() as c:c.execute('INSERT INTO kakao_auth(id,access_token,refresh_token,expires_at) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token,refresh_token=excluded.refresh_token,expires_at=excluded.expires_at',(access,refresh,int(time.time())+int(result.get('expires_in',21600))))
 except urllib.error.HTTPError as exc:
  # Never log request URLs, authorization codes, tokens, or response bodies.
  app.logger.warning('카카오 토큰 요청 실패: HTTP %s (설정된 Redirect URI 및 REST API 키 확인)',exc.code)
  return '카카오 인증 서버에서 요청을 거절했습니다 (HTTP {}). Render 로그의 상태 코드를 확인해 주세요.'.format(exc.code),502
 except (urllib.error.URLError,ValueError,KeyError,sqlite3.Error,TimeoutError) as exc:
  app.logger.warning('카카오 계정 연결 실패 (%s)',type(exc).__name__)
  return '카카오 계정 연결에 실패했습니다. 카카오 로그인 설정과 메시지 권한을 확인해 주세요.',502
 return '카카오 계정 연결 완료! 이제 테스트 예약을 접수하면 연결된 계정의 나와의 채팅으로 알림을 시도합니다.'

@app.get('/admin')
@admin_required
def admin():return send_from_directory(str(BASE),'admin.html')
@app.get('/api/admin/reservations')
@admin_required
def list_reservations():
 with db() as c:rows=c.execute('SELECT id,receipt,name,phone,program,day,slot,status,created_at FROM reservations ORDER BY day DESC,slot DESC,id DESC LIMIT 500').fetchall()
 return jsonify([dict(r) for r in rows])
@app.post('/api/admin/reservations/<int:rid>/status')
@admin_required
def change_status(rid):
 if not csrf_ok():return jsonify(error='보안 확인에 실패했습니다.'),403
 data=request.get_json(silent=True) or {};status=data.get('status')
 if status not in ('approved','rejected','pending'):return jsonify(error='잘못된 상태입니다.'),400
 try:
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   r=c.execute('SELECT id,day,slot FROM reservations WHERE id=?',(rid,)).fetchone()
   if not r:return jsonify(error='신청을 찾을 수 없습니다.'),404
   if status=='approved' and is_blocked(r['day'],r['slot']):return jsonify(error='차단된 시간입니다. 차단을 해제해 주세요.'),409
   if status=='approved' and c.execute('SELECT 1 FROM reservations WHERE day=? AND slot=? AND status=? AND id!=?',(r['day'],r['slot'],'approved',rid)).fetchone():return jsonify(error='해당 시간은 이미 다른 예약이 승인되었습니다.'),409
   c.execute('UPDATE reservations SET status=?,updated_at=? WHERE id=?',(status,local_now(),rid))
 except sqlite3.IntegrityError:return jsonify(error='중복 승인할 수 없습니다.'),409
 audit('status',f'id={rid};status={status}')
 return jsonify(ok=True,status=status)
@app.post('/api/admin/reservations/<int:rid>/delete')
@admin_required
def delete(rid):
 if not csrf_ok():return jsonify(error='보안 확인에 실패했습니다.'),403
 with db() as c:c.execute('DELETE FROM reservations WHERE id=?',(rid,))
 audit('delete',f'id={rid}')
 return jsonify(ok=True)
@app.get('/api/admin/settings')
@admin_required
def admin_settings():
 with db() as c:logs=c.execute('SELECT event,detail,created_at FROM admin_audit ORDER BY id DESC LIMIT 30').fetchall()
 return jsonify(blocks={k:v for k,v in prefs().items() if k.startswith(('closed:','times:'))},logs=[dict(x) for x in logs])
@app.post('/api/admin/settings')
@admin_required
def save_settings():
 if not csrf_ok():return jsonify(error='보안 확인 실패'),403
 d=request.get_json(silent=True) or {};day=d.get('day');slot=d.get('slot');blocked=d.get('blocked')
 try:
  date_value=date.fromisoformat(day)
  if date_value.isoformat()!=day or not local_today()<=date_value<=local_today()+timedelta(days=180):raise ValueError()
 except (TypeError,ValueError):return jsonify(error='날짜를 확인해 주세요.'),400
 if not isinstance(blocked,bool) or (slot is not None and (not isinstance(slot,str) or not re.fullmatch(r'(?:1[0-9]|2[01]):00',slot))):return jsonify(error='시간을 확인해 주세요.'),400
 key=('times:' if slot else 'closed:')+day
 with db() as c:
  old=c.execute('SELECT value FROM admin_settings WHERE key=?',(key,)).fetchone()
  if slot:
   values=set((old['value'] if old else '').split(','));values.discard('')
   if blocked:values.add(slot)
   else:values.discard(slot)
   value=','.join(sorted(values))
  else:value='1' if blocked else '0'
  c.execute('DELETE FROM admin_settings WHERE key=?',(key,))
  c.execute('INSERT INTO admin_settings(key,value) VALUES(?,?)',(key,value))
 audit('block',f'{day} {slot or "all"} {blocked}')
 return jsonify(ok=True)
@app.post('/api/admin/password')
@admin_required
def change_admin_password():
 if not csrf_ok():return jsonify(error='보안 확인 실패'),403
 d=request.get_json(silent=True) or {};old=d.get('old','');new=d.get('new','')
 if not isinstance(old,str) or not admin_password_ok(old):return jsonify(error='현재 비밀번호가 올바르지 않습니다.'),400
 if not isinstance(new,str) or not 12<=len(new)<=128 or new==old:return jsonify(error='새 비밀번호는 기존과 다른 12자 이상이어야 합니다.'),400
 with db() as c:
  c.execute("DELETE FROM admin_settings WHERE key='password_hash'")
  c.execute('INSERT INTO admin_settings(key,value) VALUES(?,?)',('password_hash',generate_password_hash(new)))
 audit('password_change');session.clear();return jsonify(ok=True)
@app.get('/api/admin/export')
@admin_required
def export_reservations():
 import csv,io
 from flask import Response
 with db() as c:rows=c.execute('SELECT receipt,name,phone,program,day,slot,status,created_at FROM reservations ORDER BY day,slot LIMIT 10000').fetchall()
 buf=io.StringIO();w=csv.writer(buf);w.writerow(['접수번호','이름','연락처','상담내용','예약일','예약시간','상태','신청일'])
 for row in rows:w.writerow([("'"+str(row[k]) if str(row[k]).startswith(('=','+','-','@')) else row[k]) for k in ('receipt','name','phone','program','day','slot','status','created_at')])
 audit('export',f'{len(rows)} records')
 return Response('\ufeff'+buf.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="shimpyo-reservations.csv"','Cache-Control':'no-store'})

@app.get('/api/admin/csrf')
@admin_required
def csrf():return jsonify(token=session['csrf'])
@app.post('/admin/logout')
@admin_required
def logout():
 if not csrf_ok():abort(403)
 session.clear();return jsonify(ok=True)
@app.get('/healthz')
def healthz():
 try:
  with db() as c: c.execute('SELECT 1').fetchone()
  return jsonify(status='ok'),200
 except sqlite3.Error:
  return jsonify(status='unavailable'),503
@app.get('/')
def home():return send_from_directory(str(BASE),'index.html')
@app.get('/<path:filename>')
def static_pages(filename):
 if filename in ('server.py','requirements.txt','admin.html','README.txt','SETUP.md') or filename.startswith(('private/','.')):abort(404)
 if not (filename.endswith('.html') or filename.endswith('.css') or filename.endswith('.js') or filename.startswith('assets/')):abort(404)
 return send_from_directory(str(BASE),filename)
if __name__=='__main__':
 app.run(host='127.0.0.1',port=8000,debug=False)
