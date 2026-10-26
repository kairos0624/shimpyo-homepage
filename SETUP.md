# 쉼표 예약 관리 시스템 V14.9

## 주요 기능
- 예약 신청: 이름, 전화번호, 상담 종류, 날짜, 시간, 개인정보 수집 동의
- 관리자 `/admin`: 신청 내역, 승인/거절/대기 변경, 영구 삭제
- 같은 날짜·시간의 **승인 완료** 예약은 데이터베이스 고유 인덱스와 트랜잭션으로 중복 승인 불가
- 미확정 신청은 같은 시간에 여러 건 접수될 수 있음(센터장님이 한 건만 승인)
- 승인/거절 시 고객에게 자동 연락하지 않음. 관리자가 별도로 연락 필요

## 로컬 설치 (Python 3.10+)
```
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
관리자 암호와 비밀 키는 서버 환경변수로 설정합니다. 예시 값은 실제 운영에 사용하지 마세요.
```
# Linux/macOS 예시
export SHIMPYO_ADMIN_PASSWORD='관리자만아는강력한비밀번호'
export SHIMPYO_SECRET_KEY='충분히길고무작위인32자이상의보안키값'
export SHIMPYO_COOKIE_SECURE=0  # HTTP 로컬 개발에서만
python server.py
```
브라우저: http://127.0.0.1:8000/booking.html / http://127.0.0.1:8000/admin

## 실제 공개 전 필수
1. HTTPS 지원 호스팅에 배포하고 `SHIMPYO_COOKIE_SECURE=1` 유지. Flask 개발 서버 대신 Waitress 등 운영 서버 사용.
2. 관리자 페이지 접근 제한, 관리자 암호 보안 관리, 로그인 시도 제한을 추가로 적용.
3. 개인정보 처리방침과 수집·이용 동의 문구를 센터의 실제 보관 기간/처리 방식에 맞게 확정. 민감한 상담 내용은 이 양식에 입력받지 않음.
4. 데이터베이스 `private/reservations.sqlite3` 백업·접근권한·보관기간 및 파기 절차 마련. 백업에도 개인정보 포함됨.
5. 문자 알림은 자동 발송되지 않음. 승인/거절 후 신청자에게 직접 연락.
6. 운영 서버의 시간대를 `Asia/Seoul`로 설정. 개인정보 처리와 보안에 관한 전문가 점검 권장.
7. `SHIMPYO_DB_PATH`로 DB 경로 변경 가능. DB는 웹 정적 경로에서 제공하지 않음.

**중요:** HTML 파일을 더블클릭해 여는 경우 온라인 신청 기능은 작동하지 않습니다. 서버 실행이 필요합니다. 이 패키지는 운영을 위한 초기 구현이며 배포와 보안 설정이 완료된 상태가 아닙니다.
