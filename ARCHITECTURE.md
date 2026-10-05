# ARCHITECTURE.md — 블로그자동화 v12 Lite / SalaryMate 구조

> 실제 소스 코드 기준(2026-06-30, Sprint 2A/2B + Calculator Reviewer 개선 반영).
> 2026-10 갱신: UI Layer만 현재 구조로 정정(Streamlit `dashboard.py`/`setup_wizard`/`assets/css` 제거 → React + FastAPI).
> 그 외 계층·12단계 설명은 2026-06-30 당시 구조 기록이다. 대시보드 최신 구조는 `docs/ARCHITECTURE.md` 참고.

---

## 1. 핵심 계층 (개념 모델)
모든 운영은 아래 계층으로 결정된다.
```
Site                (사이트 1개 = 운영 단위)
   ↓
Platform            (WordPress / Calculator — 독립, 복수 선택 가능)
   ↓
Feature             (Platform별 하위 기능 + 공통 기능)
   ↓
Settings            (Global 기본값 → Site Override)
   ↓
Pipeline            (활성 Platform + Feature 조합으로 자동 결정)
   ↓
12-Step Workflow    (블로그) / Calculator Workflow (계산기)
```

**Platform 독립 원칙**
- WordPress와 Calculator는 **서로 독립적인 Platform**이다. 동시에 활성화될 수 있고, 각각 독립된 Feature 목록을 가지며, 하나를 꺼도 다른 하나에 영향이 없다.
- 저장: sites 시트의 `platforms`(JSON) / `features`(JSON) 컬럼(Site Wizard 작성).
- 실행: 대시보드 통합 `▶ 실행` 버튼이 선택 Site의 `platforms`를 읽어 Pipeline 자동 결정
  (Calculator만→계산기 / WordPress만→블로그12단계 / 둘다→순차 또는 운영자 선택).

| Platform | Feature | Pipeline |
|----------|---------|----------|
| WordPress | 글작성/자동발행/SEO/이미지/카테고리 | RSS·정책 12단계 |
| Calculator | 계산기생성/SEO글/FAQ/AI Reviewer/HTML | 계산기 Workflow |
| 공통 | Scheduler/Telegram/AI Assistant/Analytics/Cost/Retry | — |

---

## 2. 5계층 (소스 구조)
```
┌──────────────────────────────────────────────────────────────────┐
│ UI Layer       React (frontend/) — 공식 Dashboard UI               │
│ API Layer      FastAPI (api/routers · api/services) · scripts/*.bat │
├──────────────────────────────────────────────────────────────────┤
│ Business Layer main.py(run_once/_process_one: 12단계)               │
│   파이프라인   cleaner·strategist·planner·writer·editor·            │
│               duplicate_checker·image_generator·publisher·history   │
│   수집기       collector/{policy,calculator,finance,affiliate,factory}│
│   계산기엔진   formula_engine·app_generator· │
│               calculator_{seo,faq,content,image_prompt}_generator·  │
│               calculator_reviewer·calculator_pipeline·app_factory·  │
│               github_deployer·internal_link_engine·site_mode_manager│
│   운영/확장   scheduler·backup_manager·strategy_room·ai_workspace·pipeline_status·dashboard_cache·         │
│               ai_workspace·pipeline_status·dashboard_cache·         │
│               ai_assistant·cost_manager·retry_queue·image_fallback· │
│               telegram_ops·telegram_notifier                        │
│   AI/공통     ai_provider·ai_roles·logger(BudgetTracker)·           │
│               config_loader(config.yaml+secrets.yaml 병합)·utils    │
├──────────────────────────────────────────────────────────────────┤
│ Repository     repositories/{article,site,calculator,template}_repo │
│                + 브릿지 sheet_sync·db_manager·site_manager          │
├──────────────────────────────────────────────────────────────────┤
│ Adapter        db/{sheets,sqlite,postgres*}  storage/{drive,local,s3*}│
│                (factory가 config로 선택)   *=stub                   │
├──────────────────────────────────────────────────────────────────┤
│ External       OpenAI·Anthropic·Google GenAI·Pollinations·         │
│                WordPress REST·Google Sheets·Google Drive·GitHub API │
└──────────────────────────────────────────────────────────────────┘
```

### 계층 책임
- **UI**: 운영자 조작/모니터링. 로컬 파일(budget.json/health_last.json/today_schedule.json/dashboard_cache.db) + Repository 경유.
- **Business**: `run_once`가 수집→12단계 오케스트레이션. 계산기 엔진은 별도 경로. AI 호출은 `ai_provider` 단일화.
- **Repository**: 도메인 CRUD. 브릿지가 기존 호출부 보존.
- **Adapter**: `DB_ADAPTER`/`STORAGE_ADAPTER`로 무중단 전환. gspread/Drive 직접호출은 어댑터 내부 캡슐화.
- **보안(Sprint 2B)**: 민감정보는 `config/secrets.yaml`(gitignore). `config_loader.merge_secrets`가 런타임 병합(secrets 우선) → 기존 flat 키(`cfg["OPENAI_API_KEY"]` 등) 그대로 사용.

---

## 3. 12-Step Workflow (블로그/정책)
```
Dashboard / scripts / Scheduler
   ▼ main.run_once(cfg, max_count=N)  ─ 예산 선차단 → 수집 → 목표만큼 _process_one
STEP1 수집(collector.factory)
STEP2 정제(cleaner)        ▶ STEP3 중복검사(dup_checker)
STEP5 전략(strategist M0)  ▶ STEP6 SEO(planner M1)
STEP7 작성(writer M3)      ▶ STEP8 검수(editor M4, Claude→GPT)
STEP9 파싱 ▶ STEP10 이미지(image_generator→Drive)
STEP11 발행(publisher, WP 미구축 시 graceful skip) ▶ STEP12 기록(sheet_sync/BudgetTracker)
```
> STEP4 = history_loader(최근 제목, 내부 사용). AI 호출은 모두 `ai_provider` 경유, 비용은 `BudgetTracker`로 모델별 누적 → `cost_manager`(예산 정지/재개).

## 4. Calculator Workflow
```
계산기 등록(seed/Wizard/App Factory)
  ├ formula_engine(AST 안전 수식)
  ▼
calculator_content_generator.auto_generate_all()
  SEO → FAQ → 본문 → 이미지프롬프트
  ▼
calculator_reviewer.auto_review_and_fix()  ─ GPT 검수(CALC_REVIEW_*),
  total=항목평균(0~100), REWRITE 시 SEO/FAQ/본문 자동 재생성 ×최대2 → 재채점
  상태: AUTO_APPROVED / AUTO_REWRITTEN / NEEDS_REVIEW
  ▼
CalculatorRepository.update_generated()  (시드는 upsert_by_slug로 기존 본문 보존)
  ▼
app_generator → index/style/script ▶ github_deployer → GitHub Pages(토큰 시)
```
> Site Mode(`site_mode_manager`): pre_adsense/post_adsense/growth → 광고/관련/공유/리포트 노출 제어.

## 5. 스케줄러 흐름
```
run_scheduler_loop(--scheduler) ─ 폴링
  ensure_today_schedule ─ 날짜 변경 시 generate_today_schedule(슬롯→랜덤예약) → today_schedule.json
  get_due_posts(now) ─▶ execute_due_post ─▶ run_once(max_count=1)
  상태전이(pending→running→completed/failed/retry) + 실패모드(none/retry_in_slot/next_slot)
```

---

## 6. 설계 원칙
- **Platform 독립 + 확장 우선**: Platform 추가만으로 라우팅 확장(RSS/Affiliate/Shorts/SaaS). 12단계 코어 보존.
- **Adapter→Repository 강제**: 데이터 접근은 Repository 경유.
- **Graceful Degradation**: WP 미구축/시트403/AI429에서 크래시 없이 대기·폴백·로깅.
- **AI 자동 품질**: 계산기 생성물은 Reviewer가 자동 검수·수정(GPT, 항목평균 점수).
- **비용 가시성·통제**: 모든 AI 호출 BudgetTracker 누적 → Cost Manager 자동 정지/재개.
- **보안 분리**: 민감정보 secrets.yaml 격리, 런타임 병합.
