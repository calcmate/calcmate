# ARCHITECTURE — 계산기 콘텐츠 파이프라인

> SalaryMate 계산기 플랫폼의 전체 흐름. (정책/RSS 블로그 12단계 파이프라인은 `main.py`/루트 README 참조 —
> 이 문서는 **계산기 생성→발행** 경로에 집중한다.)

## 전체 흐름

```
App Factory ──(신규 계산기 생성)──▶ Registry ──▶ Generator ──▶ Writer ──▶ Gate(G1~G8)
                                                                              │
                                                                              ▼
                                                          Score(S1~S6, GPT) ──▶ Retry/HOLD
                                                                              │
                                                                       PASS/WARN
                                                                              ▼
                                                                        WordPress 발행
```

각 단계 담당 모듈:

| 단계 | 모듈 | 역할 |
|------|------|------|
| App Factory | `modules/app_factory.py` | AI로 신규 계산기(스펙/코드/SEO) 생성 → calculators 시트 + `registry_auto.yaml` 기록 |
| Registry | `docs/legal_basis.draft.yaml` + `docs/registry_auto.yaml`, `modules/registry_loader.py` | 계산기 메타데이터의 **단일 소스**(slug/compute/legal/관련계산기). 상세: [REGISTRY.md](REGISTRY.md) |
| Generator | `modules/app_generator.py` | 계산기 정적앱(index.html/style.css/script.js) 생성. compute 분기·관련카드를 **registry에서만** 읽음 |
| Writer | `modules/calculator_pipeline.py::_write_article` | 본문 생성. 프롬프트 = 정적 프롬프트 + 문체 블록 + **legal_basis 블록** + 재생성 보완지시 |
| Gate | `modules/publish_quality.py::check_gates` + `_check_g8` | 결정론 코드 검사(GPT 미사용). G1~G8 |
| Score | `modules/publish_quality.py::_score_with_gpt` | GPT 채점 S1~S6. PASS≥90 / WARN≥80 / REWRITE<80 |
| Retry/HOLD | `modules/calculator_pipeline.py::run_calculator_once` | REWRITE면 전체재생성 재시도(MAX_TOTAL_RETRY). 한도 초과 시 "품질보류" HOLD |
| 발행 | `modules/publisher.py` | WordPress REST 발행/수정/삭제/복원(이 파일에서만) |

## Gate (G1~G8) — 결정론, GPT 미사용

`check_gates`(body/final_html) + `_check_g8`(legal_basis 대조). 모두 코드가 직접 판정한다.

| Gate | 검사 | 등급 |
|------|------|------|
| G1 | 본문 길이(MIN~MAX_LENGTH) | major |
| G2 | H2 개수(MIN~MAX_H2) | major |
| G3 | FAQ 개수(≥MIN_FAQ) | major |
| G4 | 계산 예시 개수(≥MIN_EXAMPLES) | major |
| G5 | 내부링크(≥MIN_INTERNAL_LINKS) + `href="#"` 0개 | critical |
| G6 | CTA 개수(=CTA_COUNT, 초과분 자동제거) | critical |
| G7 | AI 문체 금지표현(AI_STYLE_BLOCKLIST) | minor |
| **G8** | **legal_basis 대조**: law/article/authority 언급(채워진 필드만) + forbidden_articles/phrases | critical |

G8은 legal_basis의 검증된 값이 본문에 실재하는지 **문자열 매칭**으로 판정한다(GPT 환각 방지의 최종 방어선).

## Score (S1~S6) — GPT 채점, Gate와 책임 분리

`CALC_REVIEW_PROVIDER`/`CALC_REVIEW_MODEL`(기본 openai/gpt-4o)로 채점. **Gate가 결정론적으로 확정한
"존재/형식"은 Score가 재판정하지 않는다**(작업지시서 F 정리):

| Score | 판정 | Gate와의 경계 |
|-------|------|---------------|
| S1 | 계산 예시 **품질**(formula 일치·조건 다양성) | 예시 '개수'는 G4 소관 |
| S2 | 법적 근거 설명의 **맥락 적합성** | 존재/정확성은 G8 소관 |
| S3 | 적용 연도 명시 | **evergreen 계산기는 면제**(registry `content.evergreen`) |
| S4 | 문체 자연스러움 | 특정 금지표현은 G7 소관 |
| S5 | 고유 정보(중복 회피) | Gate 미커버 순수 질적 |
| S6 | 검색 의도 충족(비중·균형) | 섹션 '존재'는 Gate 소관 |

## Retry / HOLD

- REWRITE 결과면 직전 `failed_rules`를 writer에 주입해 **전체 재생성**, `MAX_TOTAL_RETRY`까지.
- Critical 연속 실패가 `CRITICAL_RETRY_LIMIT` 도달 시 Telegram 알림.
- 한도 초과에도 REWRITE면 발행하지 않고 **"품질보류"**(자동 재도전 대상) 저장.
- 재평가 게이트: 같은 writer 프롬프트 버전(`_prompt_version`=writer 프롬프트 sha1)으로 HOLD된 계산기는 재도전 스킵.
  프롬프트가 바뀌면 재도전.

## legal 미검증 차단 (BLOCK_UNVERIFIED_LEGAL)

App Factory 신규 계산기는 legal이 비어 있다(`needs_human_legal: true`). `QUALITY_GATE.BLOCK_UNVERIFIED_LEGAL: true`(기본)
이면 **GPT 호출 전에 즉시 품질보류**로 차단해 검증 안 된 법적 주장이 발행되는 것을 막는다. 사람이 legal을 채우면 자동 해제.
상세: [REGISTRY.md](REGISTRY.md), [APP_FACTORY.md](APP_FACTORY.md).

## Dashboard Architecture

> 현재: React = 공식 Dashboard UI(`frontend/`), FastAPI = 공식 Dashboard Backend(`api/`).
> Streamlit Dashboard(`dashboard.py`, `modules/setup_wizard.py`)는 React/FastAPI 이관 완료 후 **제거되었다**(`dashboard.py` `6c9f78c`, `modules/setup_wizard.py` `ee475e5`).
> (이력: Streamlit은 이관 기간 동안 legacy migration source(이관 원본)로만 취급되었다.)

```
React (frontend/)
  ↓
FastAPI (api/routers → api/services)
  ↓
CalcMate modules (modules/, repositories/, adapters/)
  ↓
DB / Registry / Content / WP
```

### 현재 상태

| 계층 | 현재 구현 | 상태 |
|------|-----------|------|
| UI | React + Vite (`frontend/src/`) | 운영 중 (공식 UI) |
| UI (이력) | Streamlit (`dashboard.py` 3989줄, 8그룹 2단 네비) + `modules/setup_wizard.py` | 제거됨 (`6c9f78c`, `ee475e5`) |
| Backend | FastAPI (`api/`) — 20개 서비스, 13개 라우터 | 운영 중 (공식 Backend) |
| 스케줄러 | FastAPI WorkerManager (구 Streamlit 백그라운드 스레드는 제거됨) | FastAPI 단독 |
| 설정 저장 | FastAPI: ConfigService.patch_* (구 Streamlit의 config.yaml 직접 YAML 치환은 제거됨) | FastAPI 단독 |

### 목표 상태

```
New Dashboard Feature
        ↓
React Page/Component (frontend/src/pages/, frontend/src/components/)
        ↓
frontend/src/api/client.js (getJson/getJsonAuth/sendJson)
        ↓
FastAPI Router (api/routers/<domain>.py)
        ↓
FastAPI Service (api/services/<domain>_service.py)
        ↓
modules/repositories/data layer
```

Streamlit은 제거되었으며 **이 흐름에 포함되지 않는다**. 이관 기간에는 Streamlit 코드
(`dashboard.py`, `modules/setup_wizard.py`)를 참고용(legacy source)으로만 사용했다 — 원본은 git 이력(삭제 커밋 `ee475e5`/`6c9f78c` 이전)에서 확인한다.

### 핵심 규칙

1. **새로운 Dashboard 기능은 Streamlit에 구현하지 않는다.**
2. **새로운 Dashboard UI는 React frontend에 구현한다.**
3. **새로운 backend/API 기능은 FastAPI에 구현한다.**
4. **React는 FastAPI API를 통해 backend와 통신한다.**
5. `dashboard.py`와 `modules/setup_wizard.py`는 이관 원본(legacy source)이었으며 현재 삭제되었다(git 이력으로만 참고).
6. Streamlit을 재도입하지 않는다. 과거 Streamlit 동작을 참고할 때는 git 이력만 사용하고, **신규 기능을 Streamlit으로 구현해서는 안 된다.**
7. 새로운 `st.*`, `streamlit.*`, `st.session_state` 사용을 신규 Dashboard 기능에 추가하지 않는다.
8. 새로운 BAT/스크립트에 `streamlit run`을 추가하지 않는다.
9. 기능 추가가 필요하면 먼저 FastAPI router/service와 React page/component/API client 구조를 검토한다.

### 이관 완료 현황 (2026-09 기준, 2026-10 Streamlit 제거 반영)

| 기능 | Streamlit | FastAPI API | React UI | 상태 |
|------|-----------|-------------|----------|------|
| 운영센터 KPI | ✅ | ✅ `/api/dashboard/kpi` | ✅ `DashboardKpiPanel` | 완료 |
| 파이프라인 다이어그램 | ✅ | ✅ `/api/dashboard/pipeline-status` | ✅ `DashboardPipelineStatusPanel` | 완료 |
| 진행 현황 | ✅ | ✅ `/api/dashboard/progress` | ✅ `DashboardProgressPanel` | 완료 |
| 현황 탭 | ✅ | ✅ `/api/dashboard/status-summary` | ✅ `DashboardStatusSummaryPanel` | 완료 |
| AI Pipeline Monitor | ✅ | ✅ `/api/dashboard/ai-pipeline` | ✅ `DashboardAiPipelinePanel` | 완료 |
| 작업 보드 | ✅ | ✅ `/api/workboard` | ✅ `Workboard` | 완료 |
| 발행 목록/수정/휴지통 | ✅ | ✅ `/api/publish`, `/api/trash` | ✅ `Publish`, `Trash` | 완료 |
| Blog Schedule (반복/One-off/Planner) | ✅ | ✅ `/api/scheduler/blog/*` | ✅ `BlogSchedulerPanel` | 완료 |
| Calculator 관리 (전체) | ✅ | ✅ `/api/calculators/*` | ✅ `Calculators`, `CalculatorDetail` | 완료 |
| App Factory (Mode A/B) | ✅ | ✅ `/api/calculators/generate/*` | ✅ `GenerateCalculatorPanel` + `ContractModePanel` | 완료 |
| 비용 모니터 | ✅ | ✅ `/api/costs` | ✅ `CostPanel` | 완료 |
| 오류 로그 | ✅ | ✅ `/api/logs/errors` | ✅ `ErrorLogPanel` | 완료 |
| 실시간 로그 | ✅ | ✅ `/api/logs/live` | ✅ `LiveLogPanel` | 완료 (폴링) |
| 헬스체크 | ✅ | ✅ `/api/health/*` | ✅ `Health` | 완료 |
| 전략회의실 | ✅ | ✅ `/api/strategy-room/run` | ✅ `StrategyRoom` | 완료 |
| 설정 (General/Image-Google) | ✅ | ✅ `/api/settings/*` | ✅ `Settings` + Panels | 부분 |
| 동기화 복구 | ✅ | ✅ `/api/scheduler/content-sync/*` | ✅ `PendingSync` | 완료 |
| 초기 설정 마법사 | ✅ | ❌ | ❌ | 미이관 (Streamlit과 함께 삭제) |
| AI Assistant | ✅ | ✅ `/api/assistant/*` | ✅ `AiAssistant` | 완료 |
| 사이트 마법사 | ✅ | ✅ `/api/sites/*` | ✅ `SiteWizard`(5단계) | 완료 |

### 신규 기능 추가 시 체크리스트

- [ ] FastAPI router(`api/routers/<domain>.py`)에 endpoint 추가
- [ ] FastAPI service(`api/services/<domain>_service.py`)에 비즈니스 로직 추가
- [ ] `frontend/src/api/client.js`에 API client 함수 추가
- [ ] `frontend/src/pages/<Feature>.jsx` 페이지 생성
- [ ] `frontend/src/components/<Feature>Panel.jsx` 컴포넌트 생성
- [ ] `frontend/src/App.jsx`에 `<Route>` 등록
- [ ] Streamlit(`st.*`, `streamlit run`) **재도입하지 않음** 확인
