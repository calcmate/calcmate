# 블로그자동화 v12 Lite / SalaryMate 플랫폼

> 정부정책(RSS) 블로그 자동화 + 계산기 콘텐츠 플랫폼 + AI 운영센터(Streamlit).
> 본 문서는 **실제 소스 코드 기준**. Python 85개 파일.

---

## 📚 문서 지도 (여기부터)
프로젝트를 처음 본다면 이 순서로 읽으세요.

```
README (이 문서, 5분 개요)
  └▶ MASTER_ROADMAP.md ── 프로젝트 목표·완료·로드맵 한눈에 (기준 문서)
        ├▶ docs/ARCHITECTURE.md ── 계산기 파이프라인 전체 흐름 (Gate/Score)
        │     └▶ docs/REGISTRY.md ── Registry 2.0 (단일 소스, legal, HOLD)
        │     └▶ docs/APP_FACTORY.md ── 신규 계산기 생성 (slug/name)
        ├▶ docs/OPERATIONS.md ── 운영자 절차 (추가→legal→발행→관찰→수정)
        ├▶ docs/DEVELOPER_GUIDE.md ── 개발자 (구조·규칙·스냅샷 테스트)
        ├▶ BACKLOG.md ── 미완 작업 (HIGH/MED/LOW)
        ├▶ KNOWN_ISSUES.md ── 알려진 문제 (원인·영향·우회·개선)
        └▶ CHANGELOG.md ── 버전 이력 (git 기준)
```
> 루트의 구버전 문서(`ARCHITECTURE.md`/`FILE_STRUCTURE.md`/`ROADMAP.md`)는 정책 12단계 중심의 이전 버전입니다.
> 계산기 서브시스템 최신 문서는 위 `docs/` 및 `MASTER_ROADMAP.md`를 기준으로 삼으세요.

---

## 1. 프로젝트 소개
- **목적**: RSS/계산기 키워드를 수집 → AI로 SEO 글·계산기 페이지 생성·검수 → 이미지 → WordPress/GitHub Pages 발행까지 무인 자동화. 운영은 Streamlit 대시보드.
- **버전**: v12 Lite (12단계 파이프라인 코어는 v11.6 계승, UI/운영 슬림화).
- **두 갈래 콘텐츠**: ① 정책/RSS 블로그(`run_once` 12단계) ② 계산기 플랫폼(생성→AI검수→정적앱→배포).

## 2. 주요 기능
| 영역 | 기능 |
|------|------|
| 수집 | RSS(정책, feedparser), 계산기 키워드(DB) |
| 생성 | 정제→전략(M0/M2)→SEO(M1)→작성(M3)→검수(M4)→이미지→발행 (12단계) |
| 계산기 | Formula/Form Engine, v1 UI 템플릿, 템플릿 5종, App Generator, **AI Reviewer(GPT 검수·자동수정)**, Site Mode |
| 운영비서 | **AI Assistant**(GPT/Claude/Gemini 채팅 + 워크스페이스 파일도구 + 승인 게이트 + 메모리/태스크/분석) |
| 운영 자동화 | **Cost Manager**(80%경고/100%정지/익일재개) · **Retry Queue**(WP 재발행) · **Image Fallback** · **Telegram**(이벤트 ON/OFF) |
| 사이트 | Site Manager(현재Site 셀렉터/안전삭제/복제/Export·Import) · 5단계 Site Wizard · Site Settings Override |
| 스케줄 | 평일·주말 슬롯 + 랜덤 예약 + 실패모드 3종 (예약발행 단일화) |
| 데이터 | Sheets/SQLite(DB), Drive/Local(Storage) 어댑터 |
| 보안 | **Secrets 분리**(config/secrets.yaml, gitignore) |

## 3. 현재 Dashboard 구조
Streamlit **8그룹 2단 네비게이션**(그룹 → 하위 페이지). `dashboard.py`의 `NAV_GROUPS`.

| 그룹 | 하위 페이지 |
|------|-------------|
| 🏠 Dashboard | 운영센터(현재Site·5KPI·Workflow·진행현황) · 현황 |
| 📝 Content | 발행 목록 · 작업 보드 · AI Workspace · 전략회의실 |
| 🧮 Calculator | App Factory · 계산기 관리 |
| 📅 Scheduler | 오늘 발행 일정 · AI Pipeline · **사이트 관리** |
| 💰 Revenue | 비용 모니터(Cost/Retry) |
| 📡 Logs | 오류 로그 · 실시간 로그 · 헬스체크 |
| 🔧 Settings | 설정(AI역할·모델·WP·Telegram) |
| 🤖 AI Assistant | AI Assistant |

## 4. 지원 Platform
**WordPress와 Calculator는 서로 독립적인 Platform이다.** 동시 활성 가능하며 각각 독립된 Feature 목록을 가진다(Site Wizard에서 선택, sites 시트 `platforms`/`features` 컬럼 저장).

- **WordPress**: 글 작성 / 자동 발행 / SEO / 이미지 업로드 / 카테고리 → RSS·정책 12단계 파이프라인.
- **Calculator**: 계산기 생성 / SEO 글 / FAQ / AI Reviewer / HTML 생성 → 계산기 파이프라인.
- **공통**: Scheduler / Telegram / AI Assistant / Analytics / Cost Manager / Retry Queue.

## 계산기 품질 파이프라인 & Registry 2.0
계산기 콘텐츠는 **Registry(단일 소스) → Generator → Writer → Gate(G1~G8) → Score(S1~S6) → Retry/HOLD → WordPress** 흐름을 탄다.
- **Registry 2.0**: 계산기 메타데이터(slug/계산방식/legal/관련계산기)를 `docs/legal_basis.draft.yaml`(사람 큐레이션) + `docs/registry_auto.yaml`(App Factory 자동)로 관리하고 `registry_loader`가 merge(큐레이션 우선). 하드코딩 폴백은 제거되어 registry가 유일 소스.
- **식별자 분리**: `slug`(영문, 폴더/URL/내부) vs `name`(한글, 화면). 신규 계산기는 App Factory에서 영문 slug 직접 입력.
- **Gate(결정론) vs Score(GPT) 책임 분리**: "존재/형식/개수"는 Gate, "품질/맥락"만 Score. **G8**은 legal_basis 검증값을 문자열 매칭으로 확인(환각 방지).
- **legal 미검증 차단**: 신규 계산기는 legal이 채워질 때까지 발행 HOLD(`BLOCK_UNVERIFIED_LEGAL`). 사람이 legal 입력 시 자동 해제.

상세: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/REGISTRY.md`](docs/REGISTRY.md) · [`docs/APP_FACTORY.md`](docs/APP_FACTORY.md) · [`docs/OPERATIONS.md`](docs/OPERATIONS.md) · [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)

## 5. AI Provider 구조
모든 AI 호출은 `modules/ai_provider.py`로 단일화(OpenAI/Anthropic/Google GenAI). 키는 `secrets.yaml`에서 병합 주입.

| 역할 | 모듈 | 현재 모델 | config 키 |
|------|------|-----------|-----------|
| Orchestrator(M0) | strategist | OpenAI gpt-4o | `ORCHESTRATOR_PROVIDER`/`MODEL_ORCHESTRATOR` |
| Planner(M1) | planner | Gemini gemini-2.5-flash | `PLANNER_PROVIDER`/`MODEL_PLANNER` |
| Writer(M3) | writer | OpenAI gpt-4o-mini | `WRITER_PROVIDER`/`MODEL_WRITER` |
| Editor(M4, 블로그 검수) | editor | Claude claude-sonnet-4-6 → fallback gpt-4o | `EDITOR_PROVIDER`/`MODEL_EDITOR` |
| Cleaner | cleaner | OpenAI gpt-4o | `MODEL_CLEANER` |
| **Calculator Reviewer** | calculator_reviewer | **OpenAI gpt-4o** | **`CALC_REVIEW_PROVIDER`/`CALC_REVIEW_MODEL`** |
| Image | image_generator | Pollinations(무료) | `IMAGE_PROVIDER` |

> 계산기 검수는 블로그 editor(Claude)와 **분리된 전용 키**를 사용한다(자기검수 방지). 확장 기능(App Factory/AI Workspace)은 `ai_roles.py`(`AI_ROLES`) 역할표를 별도로 사용.

## 6. 프로젝트 폴더 구조
요약(상세는 `FILE_STRUCTURE.md`):
```
main.py · dashboard.py · health_check.py
config/   config.yaml · secrets.yaml · secrets.example.yaml · score_weights.yaml · site_mode.yaml
modules/  파이프라인·계산기엔진·AI/운영(ai_assistant/cost_manager/retry_queue/telegram_ops 등)
repositories/ · adapters/(db,storage) · scripts/ · templates/ · prompts/ · docs/
```

## 7. 최초 설치
1. **Python 3.11+** (검증 3.12 venv).
2. 의존성: `python -m venv .venv` → `.venv\Scripts\python.exe -m pip install -r requirements.txt`
   (openai, anthropic, google-genai, gspread, google-api-python-client, feedparser, streamlit, pandas, numpy, Pillow, pyyaml, requests)
3. Google: `credentials.json`(서비스계정) + 시트/드라이브를 서비스 계정 이메일에 **편집자 공유**. 최초 미설정 시 대시보드가 설정 마법사 자동 표시.

## 8. Secrets 설정 🔐
민감정보는 `config/config.yaml`이 아닌 **`config/secrets.yaml`**(gitignore, 미추적)에 둔다. `ConfigLoader`가 런타임에 두 파일을 병합(secrets 우선)하므로 기존 코드는 그대로 동작.
```
1) cp config/secrets.example.yaml config/secrets.yaml
2) secrets.yaml에 실제 키 입력
   OPENAI_API_KEY / CLAUDE_API_KEY / GEMINI_API_KEY
   WORDPRESS_APP_PASSWORD / TELEGRAM_BOT_TOKEN
   (사이트별 WP 프로필은 wordpress_profiles, AI 키 슬롯은 ai_keys)
3) 실행
```
> ⚠️ secrets.yaml은 절대 커밋하지 말 것. 외부 노출 시 키 재발급 필수.

## 9. Dashboard 실행
`start_dashboard.bat` (루트) — FastAPI(`127.0.0.1:8000`) + React/Vite(`127.0.0.1:5173`) 기동 후 브라우저 오픈. (legacy Streamlit `dashboard.py` 실행 스크립트는 제거됨)

## 10. Scheduler 실행
`scripts/run_scheduler.bat` (= `main.py --scheduler`). **유일한 상시 운영 방식.** 평일/주말 슬롯 + 랜덤 예약시각으로 시각별 1건 발행(today_schedule.json 영속, 실패모드 3종).
- 단발: `scripts/run_pipeline.bat` (`--once`, DAILY_POST_COUNT만큼)
- 검증: `scripts/run_dryrun.bat` (`--dry-run`, 헬스체크+설정 검증)
- 전략회의실: `scripts/run_strategy_room.bat` (`--strategy-room`)
- 계산기: `main.py --calculator` / 시드 `--seed-calculators`
- 캐시 워밍: `scripts/sync_cache.bat`

## 11. WordPress 연결
`WORDPRESS_URL`/`WORDPRESS_USERNAME`(config) + `WORDPRESS_APP_PASSWORD`(secrets, Application Password). 미설정/placeholder(example.com)면 `is_wordpress_ready=False` → 발행 단계 **graceful skip**(크래시 없음). 사이트별 발행은 `secrets.yaml`의 `wordpress_profiles`.

## 12. Telegram 설정
`TELEGRAM_BOT_TOKEN`(secrets) + `TELEGRAM_CHAT_ID`(config). Settings 탭에서 입력·**테스트 전송** 가능. **이벤트 ON/OFF 토글**(`TELEGRAM_EVENTS`: error/budget/daily_summary/publish_request) — telegram_ops 경유 이벤트에 적용. 키 미설정 시 무동작. (양방향은 `TELEGRAM_BIDIRECTIONAL_DESIGN.md` 설계만)

## 13. 운영 순서
```
1) secrets.yaml 설정 + Google 공유 + (선택)WordPress
2) run_dryrun.bat 로 헬스체크(6서비스 OK 확인)
3) start_dashboard.bat(React+FastAPI) 로 사이트/계산기 등록·설정
4) run_scheduler.bat 상시 실행(예약 발행)
5) 대시보드에서 비용/Retry/로그/헬스 모니터링
```

## 14. 실전 배포 절차
```
1) secrets.yaml의 placeholder 제거 + 실제 키/WP 자격 입력 (배포 전 키 재발급 권장)
2) WORDPRESS_URL/USERNAME/APP_PASSWORD 실서버 값 입력 → run_dryrun 으로 wordpress OK 확인
3) DAILY_POST_COUNT/예산(DAILY_AI_BUDGET·MONTHLY_AI_BUDGET) 확정
4) PUBLISH_SCHEDULE 슬롯 설정(Scheduler 탭)
5) run_scheduler.bat 상시 가동
6) 첫 발행 결과 검수 → ADSENSE_MODE(pre→post) 전환
```

## 15. Troubleshooting
| 증상 | 원인/조치 |
|------|-----------|
| AI 호출 실패(KeyError API_KEY) | secrets.yaml 미작성 → example 복사 후 키 입력 |
| Google Sheet 403 | 시트를 서비스 계정 이메일에 편집자 공유. 임시로 `DB_ADAPTER: sqlite` 폴백 가능 |
| WordPress 발행 안 됨 | example.com/temp placeholder → 실값 입력. `is_wordpress_ready` 통과 필요 |
| 계산기 본문 0자 | 시드만 됨(본문 미생성) → 계산기 관리에서 자동생성 실행. 시드는 slug upsert로 기존 본문 보존 |
| 계산기 검수가 늘 낮음 | GPT 검수 + total 평균 정규화 적용됨. 콘텐츠 품질 이슈는 프롬프트 보강 영역 |
| Telegram 미수신 | BOT_TOKEN(secrets)+CHAT_ID(config) 둘 다 필요, Settings 테스트 전송으로 확인 |
| 이미지 생성 실패 | Pollinations/Gemini 일시 오류 → Image Fallback(브랜드 이미지)로 대체 |

---

## 더 읽기
**기준 문서**: [`MASTER_ROADMAP`](MASTER_ROADMAP.md) · [`BACKLOG`](BACKLOG.md) · [`KNOWN_ISSUES`](KNOWN_ISSUES.md) · [`CHANGELOG`](CHANGELOG.md)
**계산기 서브시스템(docs/)**: [`ARCHITECTURE`](docs/ARCHITECTURE.md) · [`REGISTRY`](docs/REGISTRY.md) · [`APP_FACTORY`](docs/APP_FACTORY.md) · [`OPERATIONS`](docs/OPERATIONS.md) · [`DEVELOPER_GUIDE`](docs/DEVELOPER_GUIDE.md)
**기타(구버전/보조)**: `FILE_STRUCTURE.md` · `ROADMAP.md` · `CHANGELOG_AI.md` · `SPRINT_2A_REPORT.md`·`SPRINT_2B_REPORT.md` · `docs/QUALITY_STANDARD_V1.2.md`

---

## Project Status
| 항목 | 상태 |
|------|------|
| **Version** | v12 Lite |
| **Current Sprint** | Sprint 2B Complete (+ Calculator Reviewer Fix, Secrets 분리) |
| **완성도** | 코어 파이프라인·계산기·대시보드·운영 자동화 동작. 런타임 Override 소비/실서버 WP 미완 |
| **Deployment** | Ready for Production Test (WordPress 실서버 구축 시 발행 가능) |
| **남은 작업** | WordPress 실전 배포 · Site Override 런타임 배선 · provision 가드 · Telegram 미배선 이벤트/양방향 · 노출 키 재발급 |
