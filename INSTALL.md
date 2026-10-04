# 블로그자동화 v12 — 설치 가이드

---

## 사전 준비 체크리스트

설치 전에 아래 항목을 먼저 준비하세요.

```
□ Python 3.11 이상 설치
□ Google Cloud 서비스 계정 JSON 다운로드
□ Google Sheets API 활성화
□ Google Drive API 활성화
□ OpenAI API 키
□ Anthropic API 키
□ Google Gemini API 키
□ WordPress 사이트 (REST API 활성화 상태)
□ WordPress 앱 비밀번호 생성
```

---

## STEP 1 — Python 설치 확인

```bash
python --version
# Python 3.11.x 이상이어야 함
```

설치되어 있지 않으면 https://www.python.org/downloads/ 에서 3.11 이상 다운로드.  
**설치 시 "Add Python to PATH" 체크 필수.**

---

## STEP 2 — 프로젝트 압축 해제

`blog_auto_v12.zip`을 원하는 폴더에 압축 해제합니다.

```
C:\Users\연수\Desktop\blog_auto_v12\   ← 예시 경로
```

---

## STEP 3 — 설치 스크립트 실행

`scripts\install.bat` 더블클릭 또는 터미널에서 실행.

```
scripts\install.bat
```

자동으로 수행하는 작업:
1. 가상환경 `.venv` 생성
2. 패키지 설치 (`requirements.txt`)
3. `data/` 하위 디렉토리 생성
4. `config/score_weights.yaml` 기본 파일 생성

---

## STEP 4 — Google Cloud 서비스 계정 준비

### 4-1. Google Cloud Console 접속

https://console.cloud.google.com/

### 4-2. API 활성화

좌측 메뉴 → **API 및 서비스** → **라이브러리**

아래 두 가지를 검색하여 각각 **사용** 버튼 클릭:
- `Google Sheets API`
- `Google Drive API`

### 4-3. 서비스 계정 생성

좌측 메뉴 → **IAM 및 관리자** → **서비스 계정**

1. **서비스 계정 만들기** 클릭
2. 이름 입력 (예: `blog-auto`) → **만들기 및 계속**
3. 역할 선택 → **편집자** → **완료**

### 4-4. JSON 키 다운로드

생성된 서비스 계정 클릭 → **키** 탭 → **키 추가** → **JSON**

다운로드된 파일을 프로젝트 루트에 `credentials.json` 이름으로 저장:

```
blog_auto_v12/
└─ credentials.json   ← 여기에 배치
```

---

## STEP 5 — 대시보드 실행 및 Setup Wizard

루트의 `start_dashboard.bat` 더블클릭 (FastAPI `127.0.0.1:8000` + React/Vite `127.0.0.1:5173`).

브라우저에서 자동으로 `http://127.0.0.1:5173` 열림.
> 참고: 아래 Setup Wizard(`config.yaml` 미존재 시 자동 시작)는 legacy Streamlit `dashboard.py` 동작이며 React/FastAPI에는 이관되지 않았습니다. (Streamlit 실행 스크립트는 제거됨)

---

## STEP 6 — Setup Wizard 진행

### 1단계: 서비스 계정 JSON 업로드

`credentials.json` 파일을 업로드합니다.  
(STEP 4에서 루트에 이미 배치했다면 자동 인식)

---

### 2단계: Google Sheets / Drive 자동 생성

**🚀 자동 생성** 버튼을 클릭하면:

```
생성 항목:

Google Drive
  blog_auto_v12/        ← 루트 폴더
    images/             ← 이미지 저장
    backups/            ← 백업 저장
    placeholders/       ← 이미지 미생성 시 대체

Google Sheets
  블로그자동화_v12      ← 스프레드시트
    마스터_DB           ← 콘텐츠 작업 목록
    운영로그            ← 실행 로그
    sites               ← 사이트 설정
    calculators         ← 계산기 메타
    app_templates       ← 템플릿 라이브러리
    app_factory_queue   ← App Factory 큐 (예약)
    app_factory_logs    ← App Factory 로그 (예약)
```

생성 완료 후 Sheet URL과 Drive ID가 자동으로 `config.yaml`에 저장됩니다.

> **자동 생성이 실패하는 경우**: API 활성화 여부 재확인 후,  
> 수동으로 Sheet ID와 Drive 폴더 ID를 직접 입력하는 탭을 사용하세요.

---

### 3단계: AI API 키 입력

| 항목 | 용도 | 발급처 |
|---|---|---|
| Gemini API Key | M1 리서치 (AIza...) | https://aistudio.google.com/app/apikey |
| OpenAI API Key | M0 총괄 + M3 작성 (sk-...) | https://platform.openai.com/api-keys |
| Claude API Key | M4 검수 (sk-ant-...) | https://console.anthropic.com/ |

> 최소 1개 이상 입력 필요. 모두 입력하면 AI 역할 분담이 최적화됩니다.

---

### 4단계: WordPress 계정 설정

#### WordPress 앱 비밀번호 생성 방법

1. WordPress 관리자 → **사용자** → **프로필**
2. 페이지 하단 **애플리케이션 비밀번호** 섹션
3. 이름 입력 (예: `blog-auto`) → **새 애플리케이션 비밀번호 추가**
4. 생성된 비밀번호 복사 (형식: `xxxx xxxx xxxx xxxx xxxx xxxx`)

#### 프로필 등록

| 항목 | 예시 |
|---|---|
| 프로필 ID | `wp_salarymate` |
| WordPress URL | `https://salarymate.kr` |
| 사용자명 | `admin` |
| 앱 비밀번호 | `xxxx xxxx xxxx xxxx xxxx xxxx` |

> 계정 정보는 **로컬 `config/secrets.yaml`에만 저장**됩니다.  
> Google Sheets에는 `wp_salarymate`라는 프로필 ID만 기록되어 노출 위험 없음.

---

### 5단계: 운영 설정

| 항목 | 기본값 | 설명 |
|---|---|---|
| 애드센스 모드 | pre | pre=승인 전(학술형) / post=승인 후(마케팅형) |
| 하루 발행 목표 | 3 | 일 최대 발행 건수 |
| 실행 간격 | 24시간 | 스케줄 모드 반복 주기 |
| 일 AI 예산 | $5 | 초과 시 자동 중단 |
| 월 AI 예산 | $100 | 초과 시 자동 중단 |
| 텔레그램 봇 토큰 | (선택) | 발행 알림 수신 |
| 텔레그램 Chat ID | (선택) | 알림 대상 채널 |

**저장 및 완료** 클릭 → `config.yaml` + `secrets.yaml` 자동 생성.

---

## STEP 7 — 첫 번째 사이트 등록

대시보드 → **Site Manager** → **사이트 추가**

SalaryMate 1호기 예시:

```
site_name:          SalaryMate 계산기 허브
domain:             salarymate.kr
site_type:          calculator
monetization_type:  adsense
wordpress_profile_id: wp_salarymate
research_ai:        gemini_flash
writing_ai:         gpt4o
review_ai:          claude_sonnet
publish_mode:       auto
content_mode:       blog
site_tags:          직장인,급여,세금,실업급여,퇴직금
site_priority:      100
```

---

## STEP 8 — 파이프라인 테스트

### 설정 검증만 (API 호출 없음)

```
scripts\run_dryrun.bat
```

### 파이프라인 1회 실행

```
scripts\run_pipeline.bat
```

### 스케줄 반복 실행 (24시간 간격)

```
scripts\run_schedule.bat
```

---

## 설치 후 구조 확인

```
blog_auto_v12/
├─ credentials.json       ✅ 배치 완료
├─ config/
│   ├─ config.yaml        ✅ Setup Wizard에서 자동 생성
│   ├─ secrets.yaml       ✅ WP 계정 + AI 키 저장
│   └─ score_weights.yaml ✅ 설치 스크립트에서 자동 생성
├─ data/
│   ├─ checkpoints/       ✅ 자동 생성
│   ├─ logs/              ✅ 자동 생성
│   ├─ outputs/           ✅ 자동 생성
│   └─ dlq/               ✅ 자동 생성
└─ backups/               ✅ 자동 생성
```

---

## 이후 DB 전환 (홈서버 이전 시)

### Google Sheets → SQLite

`config/config.yaml` 1줄 변경:

```yaml
DB_ADAPTER: sqlite
SQLITE_PATH: data/blog_auto.db
```

### SQLite → PostgreSQL

```yaml
DB_ADAPTER: postgres
POSTGRES_DSN: postgresql://user:pass@localhost:5432/blog_auto
```

> 비즈니스 로직 코드 수정 없음. Adapter 교체만으로 전환 완료.

---

## Google Drive → 로컬 스토리지 전환

```yaml
STORAGE_ADAPTER: local
LOCAL_STORAGE_ROOT: /data/blog_auto/storage
LOCAL_STORAGE_BASE_URL: https://cdn.yourdomain.kr
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `credentials.json` 오류 | 파일 위치 또는 형식 오류 | 루트 폴더에 배치, JSON 형식 확인 |
| Sheets API 403 | API 미활성화 | GCP에서 Sheets/Drive API 활성화 |
| WP 발행 401 | 앱 비밀번호 오류 | WordPress 앱 비밀번호 재생성 |
| 예산 초과 중단 | AI 비용 한도 도달 | config.yaml DAILY_AI_BUDGET 조정 |
| 이미지 생성 실패 | Gemini 키 오류 | PLACEHOLDER_IMAGE_MODE 자동 전환 |
| DLQ 경고 | 3회 연속 발행 실패 | data/dlq/ 파일 확인 후 원인 제거 |

---

## 대시보드 메뉴 안내

| 메뉴 | 기능 |
|---|---|
| 🏠 대시보드 | 오늘 실적 · 예산 현황 · 빠른 실행 |
| 📋 마스터 DB | 콘텐츠 작업 목록 · 상태 관리 |
| 📡 실시간 로그 | 파이프라인 로그 실시간 확인 |
| 🏥 헬스체크 | API 연결 상태 전체 점검 |
| 💰 비용 모니터링 | AI 토큰 사용량 · 예산 현황 |
| 🔧 설정 | config.yaml · secrets.yaml UI 편집 |
| 🏭 App Factory | Coming Soon (DB 슬롯 확보됨) |
