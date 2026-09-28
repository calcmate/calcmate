# CALCMATE-WORKSTREAMS

CalcMate 작업 경계 기준 문서. Claude Code 세션이나 에이전트가 바뀌어도
계산기 / 블로그 / Golden10 / 인프라의 작업 범위를 혼동하지 않기 위한 규칙이다.
현재 상태(커밋, HOLD, 발견 사항)는 `CALCMATE-CURRENT-STATE.md`를 본다.

---

## 1. 아키텍처 기준

신규 기능의 현행 경로는 하나다.

```
React (frontend/, Vite :5173)
  ↓  /api 요청을 Vite proxy가 127.0.0.1:8000으로 전달
FastAPI (api/main.py, :8000)
  ↓
Service / Repository (api/services/, modules/, repositories/, adapters/)
```

### Streamlit = legacy / 폐기 예정

`dashboard.py` 등 기존 Streamlit 코드는 legacy로 취급한다.

금지:

- 신규 기능을 Streamlit에 추가
- React 기능을 Streamlit으로 연결
- 계산기 생산 기능을 Streamlit에 연결
- 블로그 생산 기능을 Streamlit에 연결
- 신규 scheduler / automation을 Streamlit에 연결
- FastAPI 대신 Streamlit을 신규 backend로 사용

허용 (조사 목적만):

- 기존 기능 파악, 이관 대상 확인, 기존 로직 참고, 폐기 전 영향 분석

Streamlit에만 있는 기능이 필요하면 FastAPI/React로 **이관할 대상**으로 기록한다.

---

## 2. WORKSTREAM

네 영역은 서로 독립이다.

```
CALCULATOR  ≠  BLOG  ≠  GOLDEN10        (INFRA는 공통 기반)
```

- CALCULATOR E2E는 BLOG를 검증하지 않는다.
- BLOG E2E는 CALCULATOR를 검증하지 않는다.
- GOLDEN10은 어느 쪽에도 자동으로 포함하지 않는다.

### A. CALCULATOR — 신규 계산기 생산

포함:

- calculator generation (Mode A / Mode B contract)
- generation job, review, checklist, promote
- calculator save (`modules/app_factory.save_app`)
- calculators DB (`calculators`, `app_templates` 테이블)
- calculator registry (`docs/registry_auto.yaml`, `docs/registry/*_af.yaml`)
- `docs/calculator_index.json`
- calculator Build (`data/workspace/_site/{slug}/`)
- 필요한 경우 calculator Deploy (별도 결정 사항)

기본 제외:

- Topic Pool, `blog_articles`, WP 블로그 발행, blog scheduler, blog one-off
- Golden10 유지보수
- Streamlit

### B. BLOG — 신규 블로그 콘텐츠 생산

포함:

- Topic Pool (`topic_pool` 테이블, `modules/topic_pool.py`)
- topic 생성, candidate → approved
- one-off 예약 (`data/schedule/blog/oneoff_schedule.json`)
- one-off 실행
- WP draft / WP publish
- `blog_articles`

기본 제외:

- calculator generation, calculators DB, calculator registry, calculator Build
- Golden10 유지보수
- Streamlit

### C. GOLDEN10 — 기존 운영 자산

- 정의: `content/blog/__init__.py`의 `GOLDEN_10` 목록 10건과 그 WP 게시글.
- 신규 CALCULATOR 생산, 신규 BLOG 생산과 **별개**의 기존 운영 자산이다.
- CALCULATOR 작업에서 Golden10을 자동으로 수정하지 않는다.
- BLOG 작업에서 Golden10을 자동으로 수정하지 않는다.
- 작업이 명시적으로 "GOLDEN10"으로 지정된 경우에만 수정한다.
- Golden10을 발견했다는 이유만으로 현재 작업 범위를 넓히지 않는다.

### D. INFRA — 공통 인프라

예: React, FastAPI, 인증, 공용 서비스, Dashboard 인프라, 설정(config),
migration, 보안/hardening, 공통 API.

INFRA 작업에서도 Streamlit에 신규 기능을 연결하지 않는다.

---

## 3. BLOG WordPress 구조 — Public URL과 Origin 구분

```
사용자
  ↓
https://calcmate.kr/blog/     ← Public / Production URL (canonical 기준)
  ↓
Cloudflare
  ↓
https://blog.genon.app        ← WordPress Origin (backend endpoint)
  ↓
WordPress
```

- `https://calcmate.kr/blog/`: 사용자가 접근하는 실서비스 주소이며 canonical/public URL의 기준이다.
- `https://blog.genon.app`: WordPress origin / backend endpoint다. **공개 URL이라고 표현하지 않는다.**
- Cloudflare 연결을 임의로 변경하지 않는다.

코드/데이터 근거:

- `blog_articles.canonical_url` 11건 모두 `https://calcmate.kr/blog/...`
- `blog_articles.wp_permalink` 11건 모두 `https://blog.genon.app/...`
- `modules/wp_blog_sync.py:207` — canonical `https://calcmate.kr/blog/{slug}/`
- `modules/wp_readonly_client.py:21` — `WP_PRODUCTION_URL = "https://blog.genon.app"`
- production 대상은 `config/secrets.yaml`의 `wordpress.url`(host `blog.genon.app`)이며,
  `modules/config_loader._apply_wp_target(cfg, "production")`을 거칠 때만 적용된다.

---

## 4. SalaryMate WordPress — 사용 금지

기존 SalaryMate 로컬 WordPress는 개발/테스트용 legacy 환경이다.
신규 BLOG 기능은 SalaryMate WP를 대상으로 연결하지 않는다.

금지 대상:

- Topic 실행, AI 콘텐츠 생성 결과 저장, WP Draft, WP Publish
- one-off 실행, Blog Scheduler, BLOG E2E, 신규 WordPress API 연결

BLOG 생산 대상은 반드시 Public `calcmate.kr/blog/` / Origin `blog.genon.app` 구조를 기준으로 한다.

SalaryMate 관련 URL이나 설정을 발견하면 자동으로 바꾸지 않는다.

```
FOUND → CLASSIFY → REPORT → OWNER DECISION
```

주의 (현재 코드 사실): `config/config.yaml`의 `WORDPRESS_URL`은 host `salarymate.test`다.
`load_config()`를 wp_target 없이 호출하는 경로는 이 SalaryMate WP를 대상으로 한다.
어떤 경로가 이에 해당하는지는 `CALCMATE-CURRENT-STATE.md` §4를 본다.

---

## 5. 공유 파일 OWNER / READERS / WRITERS

여러 영역이 참조하더라도 자동으로 공용 수정 영역으로 보지 않는다.
아래는 코드로 writer를 확인한 항목만 적었다. 코드로 확인하지 못한 OWNER는 추측하지 않는다.

| 파일 / 데이터 | OWNER | WRITERS (코드 확인) | 다른 영역 |
|---|---|---|---|
| `calculators`, `app_templates` 테이블 | CALCULATOR | `modules/app_factory.save_app`, `delete_app`; `api/services/calculator_service` (content 생성 `update_generated`, deploy `publish`) | BLOG: READ-ONLY (`topic_pool.calculator_id` 참조) / GOLDEN10: READ-ONLY |
| `docs/registry_auto.yaml` | CALCULATOR | `modules/registry_loader.add_auto_entry` / `remove_auto_entry` (save/delete가 호출) | BLOG, GOLDEN10: READ-ONLY |
| `docs/registry/*_af.yaml` | CALCULATOR | `modules/app_factory._write_registry_v3`, `save_af_checklist`, `promote_to_ready` | BLOG, GOLDEN10: READ-ONLY |
| `docs/calculator_index.json` | CALCULATOR | `modules/app_factory._write_calculator_index` — **calculators DB 기준 전량 재생성** | 실행 코드 reader 없음(루트의 분석 스크립트만 읽음). 현재 파일에는 DB에 없는 Golden10 slug 3건이 들어 있어 재생성 시 사라진다 → GOLDEN10 영향이므로 수정 전 OWNER DECISION |
| `data/workspace/_site/{slug}/` | CALCULATOR | `modules/site_snapshot.write_site_snapshot` (Build) | — |
| `topic_pool` 테이블 | BLOG | `modules/topic_pool` (`create_topic`, `transition_status`, `update_topic`) | CALCULATOR: READ-ONLY |
| `data/schedule/blog/oneoff_schedule.json` | BLOG | `modules/scheduler` (add/save/mark), `modules/publishing_planner`, `api/services/blog_scheduler_service` | — |
| `blog_articles` 테이블 | BLOG | `modules/wp_blog_sync`, `repositories/blog_article_repository` (이 외 writer 후보는 검색 기준이며 호출 경로 미검증) | GOLDEN10: 10건이 Golden10 게시글 기록 |
| `data/sync/pending_sync.json` | INFRA | `adapters/db/dual_adapter` (Sheets OK / SQLite 실패 시 재시도 큐) | — |
| `config/config.yaml` | INFRA | `api/services/config_service` (Settings PATCH), legacy `dashboard.py` 설정 화면 | — |
| `config/secrets.yaml` | INFRA | `repositories/site_repository.save_wp_profile`(sites 생성 시), `api/services/config_service` 외 (검색 기준) | — |

### OWNER 미확정 — 수정 전 OWNER DECISION 필요

| 파일 | 이유 |
|---|---|
| `data/workspace/_site/index.html`, `data/workspace/_site/sitemap.xml` | writer가 두 영역에 있다: `modules/site_generator.py`(사이트 빌드)와 `modules/wp_blog_deploy.py`(`ALLOWED_DEPLOY_FILES`, git commit/push, Windows 작업 `\블로그배포`에서 실행) |

---

## 6. CROSS-WORKSTREAM 규칙

현재 작업과 다른 WORKSTREAM의 코드/데이터를 발견해도 자동으로 범위를 넓히지 않는다.
다른 영역의 수정이 필요해 보이면:

1. 발견
2. 소유 영역 확인
3. 영향 분석
4. 별도 작업으로 분리
5. OWNER 결정

---

## 7. STOP 조건

다음 중 하나라도 해당하면 작업을 멈추고 보고한다.

- 다른 WORKSTREAM 수정이 필요함
- Golden10 수정이 필요함
- SalaryMate WordPress 사용이 필요함
- Streamlit에 신규 기능 연결이 필요함
- FastAPI/React와 Streamlit 중 현행 경로가 불명확함
- 공유 파일 OWNER가 불명확함 (§5 미확정 목록 포함)
- 기존 dirty 변경의 소유 영역이 불명확함
- 실제 저장소 상태와 `CALCMATE-CURRENT-STATE.md` 내용이 다름
- 기록하려는 내용이 실제 코드로 검증되지 않음

임의로 범위를 넓히지 않는다.
