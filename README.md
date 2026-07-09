# 스마트 영농관리 웹앱 (Smart Farm Management Web App)

농업인을 위한 반응형(모바일/PC) 영농 관리 웹 애플리케이션입니다.
Flask + SQLAlchemy 기반 백엔드와 바닐라 JS SPA 프론트엔드로 구성되어 있으며,
PWA(Progressive Web App)로 설치하여 사용할 수 있습니다.

## 주요 기능

- 로그인 / 회원가입 (관리자 · 농민 역할 구분)
- 대시보드 (통계 카드, Chart.js 차트, 다가오는 작업/최근 일지, 등급/요금제 배지)
- 작물 관리, 영농 일지, 작업 일정(칸반), 재고 관리
- AI 작물 진단 (사진 업로드 기반 모의 진단 엔진)
- 농산물 시세, 날씨 예보(지역 검색 · 실시간 새로고침), 농약 정보 검색
- 정부 지원사업, 농업진흥청 새소식(카테고리 · 실시간 새로고침 토글), 농작업 안전 정보
- 커뮤니티 게시판: RDA 스타일 게시판(번호/제목/작성자/날짜/조회수/첨부 표시),
  상단 고정 공지, 카테고리 탭, 검색, 페이지네이션
- 농업 유용 링크 모음 (카테고리별 정리)
- 출하 관리 (거래처, 수량, 단가, 합계 자동 계산)
- 요금제(Pricing) 페이지: 월간/연간 토글, 플랜 비교, 프로모션 코드 입력 및 할인 적용,
  구독/업그레이드/다운그레이드
- 회원 등급 시스템 (일반회원 · 우수회원 · VIP · VVIP · 관리자) — 등급별 할인율 자동 적용
- 관리자 전용 요금제 면제(waiver) 처리
- 관리자 페이지:
  - 대시보드 통계 (전체 회원수, 활성 구독, 등급/요금제 분포 등)
  - 사용자 관리: 등급/요금제/면제 인라인 수정, 다중 선택 일괄 처리(활성화/비활성화/등급변경/삭제)
  - 요금제(Plan) 관리 CRUD
  - 등급(Grade) 관리 CRUD
  - 프로모션 코드(PromoCode) 관리 CRUD
  - 농업 링크(Link) 관리 CRUD
- 모바일: 하단 네비게이션 + 더보기 시트 / 데스크톱: 좌측 사이드바
- PWA manifest + service worker (오프라인 캐싱)
- 사진 업로드 (`static/uploads`)

## 기술 스택

- Backend: Flask, Flask-SQLAlchemy, Flask-Login, SQLite
- Frontend: Vanilla JS (SPA 방식), Chart.js, Lucide Icons, Pretendard 폰트
- 스타일: 모바일 퍼스트 반응형 CSS (그린 자연 테마)

## 설치 및 실행 방법

```bash
# 1. 가상환경 생성 (선택)
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # macOS/Linux

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 서버 실행
python app.py
```

브라우저에서 `http://localhost:5000` 접속.
최초 실행 시 `farm.db` SQLite 데이터베이스와 데모 데이터가 자동 생성됩니다.

Windows에서는 `start_server.bat` 파일을 더블클릭하면 패키지 설치 →
IP 주소 확인 → 서버 실행까지 한 번에 처리됩니다.

## 모바일 데이터(LTE/5G)로 외부에서 접속하기

기본 설정상 서버는 `0.0.0.0:5000` 으로 바인딩되어 있어 같은 네트워크의
다른 기기뿐 아니라, 아래 방법을 이용하면 **Wi-Fi 없이 LTE/5G 데이터로도**
접속할 수 있습니다.

### 방법 1) ngrok 공개 URL 사용 (가장 간단, 권장)

1. 먼저 `start_server.bat` (또는 `python app.py`)을 실행해 Flask 서버를 켭니다.
2. 새 명령 프롬프트 창에서 `start_ngrok.bat` 을 실행합니다.
   - ngrok이 설치되어 있지 않다면 [ngrok 다운로드 페이지](https://ngrok.com/download)에서
     Windows용 zip을 내려받아 압축을 풀고, `ngrok.exe`를 이 프로젝트 폴더나
     시스템 PATH에 두세요.
   - 최초 1회, [ngrok 대시보드](https://dashboard.ngrok.com/get-started/your-authtoken)에서
     인증토큰을 발급받아 아래 명령으로 등록해야 합니다.
     ```bash
     ngrok config add-authtoken <발급받은_토큰>
     ```
3. 실행하면 다음과 같은 형태의 로그가 출력됩니다.
   ```
   Forwarding   https://xxxx-xxxx.ngrok-free.dev -> http://localhost:5000
   ```
4. 이 `https://xxxx-xxxx.ngrok-free.dev` 주소가 **외부(모바일 데이터 포함)에서
   접속 가능한 공개 URL**입니다. 이 주소를 안드로이드 앱이나 모바일 브라우저에
   입력하면 Wi-Fi 없이도 접속됩니다.
   - 무료 ngrok 계정은 프로그램을 재시작할 때마다 URL이 바뀔 수 있습니다.
   - 안드로이드 앱에서는 API 서버 주소를 이 ngrok 주소로 설정하세요
     (CORS는 서버에서 모든 origin을 허용하도록 이미 설정되어 있습니다).

### 방법 2) 공유기 포트포워딩 설정 (ngrok 없이 사용)

1. **로컬 IP 확인**: `start_server.bat` 실행 시 콘솔에 표시되거나,
   명령 프롬프트에서 `ipconfig` 실행 후 `IPv4 주소` 항목을 확인합니다
   (예: `192.168.0.10`).
2. **공인(외부) IP 확인**: 브라우저에서 [https://www.myip.com](https://www.myip.com)
   접속하거나 PowerShell에서 아래 명령 실행:
   ```powershell
   (Invoke-WebRequest -uri "https://api.ipify.org").Content
   ```
3. **공유기 관리자 페이지 접속**: 브라우저에서 공유기 게이트웨이 주소
   (보통 `192.168.0.1` 또는 `192.168.1.1`)로 접속 후 관리자 계정으로 로그인합니다.
4. **포트포워딩(가상서버) 메뉴에서 규칙 추가**:
   - 외부 포트: `5000`
   - 내부 포트: `5000`
   - 내부 IP: 위에서 확인한 이 PC의 로컬 IP (예: `192.168.0.10`)
   - 프로토콜: TCP
5. 설정 저장 후, 모바일 데이터(Wi-Fi 끄고 LTE/5G)로 브라우저에서
   `http://<공인IP>:5000` 으로 접속합니다.
   - 통신사에 따라 이동통신망(Carrier-grade NAT)이 적용되어 공인 IP가
     외부에서 직접 접근되지 않을 수 있습니다. 이 경우 방법 1의 ngrok을
     사용하는 것이 훨씬 안정적입니다.
   - 공인 IP는 통신사/공유기 설정에 따라 주기적으로 바뀔 수 있습니다
     (고정 IP가 아닌 경우). 고정 IP가 필요하면 ISP에 문의하거나 DDNS
     서비스를 이용하세요.
   - 보안을 위해 실제 배포 시에는 `app.py`의 `SECRET_KEY`를 반드시
     변경하고, 방화벽에서 필요한 포트만 허용하시기 바랍니다.

## 데모 계정

| 구분 | 이메일 | 비밀번호 |
|---|---|---|
| 관리자 | cksdudd102@naver.com | 1q2w3e4r~@ |
| 일반 농민 | farmer@farm.com | farm1234 |

로그인 화면 하단의 "관리자 데모" / "농민 데모" 버튼으로 원클릭 로그인이 가능합니다.

## 프로젝트 구조

```
farm-webapp/
├── app.py                  # Flask 백엔드 (모델, 라우트, 시드 데이터)
├── requirements.txt
├── start_server.bat        # 패키지 설치 + 서버 실행 + IP 확인 (Windows)
├── start_ngrok.bat         # ngrok 터널 실행 (모바일 데이터 외부 접속용)
├── manifest.json           # PWA manifest
├── service-worker.js       # PWA 서비스 워커
├── farm.db                 # SQLite DB (최초 실행 시 자동 생성)
├── templates/
│   ├── login.html          # 로그인/회원가입 페이지
│   └── index.html          # 메인 SPA 셸 (모든 페이지 포함)
└── static/
    ├── css/style.css       # 반응형 스타일시트
    ├── js/app.js           # SPA 로직 및 AJAX 통신
    ├── icons/              # PWA 아이콘
    └── uploads/            # 업로드된 사진 저장 폴더
```

## 데이터베이스 테이블

`users`, `crops`, `journals`, `tasks`, `inventory`, `shipments`, `posts`,
`diagnoses`, `rda_notices`, `plans`, `subscriptions`, `plan_change_logs`,
`promo_codes`, `grades`, `links`

## 참고 사항

- AI 작물 진단, 농산물 시세, 날씨 예보, 농약 정보, 정부 지원사업 데이터는
  데모/개발 목적의 모의(mock) 데이터입니다. 실제 서비스 연동 시 각 공공 API
  (농촌진흥청, 농넷, 기상청 등)로 교체하시기 바랍니다.
- `app.config["SECRET_KEY"]`는 운영 환경 배포 전 반드시 변경하세요.
