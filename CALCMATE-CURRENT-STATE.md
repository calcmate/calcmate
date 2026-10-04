# CALCMATE-CURRENT-STATE

작업 경계 규칙은 `CALCMATE-WORKSTREAMS.md`를 본다.
이 문서는 **2026-09-28 기준 저장소 상태를 코드와 데이터로 확인한 스냅샷**이다.
코드로 확인하지 못한 항목은 "미검증"으로 표시했다.
이후 작업자는 이 문서와 실제 `git` 상태가 다르면 STOP한다.

---

## 1. Git

기준 HEAD는 이 문서를 추가한 커밋의 **부모** 커밋이다.

| 항목 | 값 |
|---|---|
| HEAD (기준) | `4e535b3` feat: mount React Dashboard routers |
| origin/master | `bc44a53` (로컬이 10커밋 앞섬, push 안 함) |
| staged | 0 |
| unstaged (tracked dirty) | 75 파일 |
| untracked | 5,800 파일 (이 문서 2개 제외) |

이관 관련 최근 커밋:

| SHA | 내용 |
|---|---|
| `4e535b3` | A2: React Dashboard 라우터 11개 mount + STEP 18 라우터/서비스 19개 |
| `b5e2bdc` | A1: 계산기 생성 API FastAPI 이관 (`calculators` 라우터, job store, `review_center` P0-1 게이트, `app_factory` lock/고아 정리/체크리스트 폴백) |
| `d2fd3cd` | sync log repository |
| `563b5f8` | WordPress blog deploy 모듈 |
| `04b9480` | FastAPI scheduler 서비스 |
| `1dadbb7` | topic publishing planner |
| `d7949d5` | one-off 블로그 예약 코어 |
| `36ec7ab` | `calculator_service` (SQLite-first 저장 경로) |

### 현재 dirty 상태 (수정·정리 금지)

최상위 경로별 개수 (합계 75):

| 경로 | 개수 | 파일 |
|---|---|---|
| `modules/` | 17 | app_factory, calc_webapp_pipeline, calculator_pipeline, calculator_seed, calculator_seo_generator, cleaner, config_loader, content_integrity, content_sync, formula_engine, review_center, scheduler, setup_wizard(**삭제 D**), site_generator, telegram_notifier, wp_blog_sync, `utils/data/logs/health_last.json` |
| `logs/` | 14 | `logs/content_pipeline/*.json` |
| `tests/` | 12 | 테스트 파일 |
| `docs/` | 7 | `ARCHITECTURE.md`, `OPS_TASK_SCHEDULER_GUIDE.md`, `calculator_index.json`, `contract_schema/registry.yaml`, `legal_master/tax.yaml`, `registry/labor_af.yaml`, `registry_auto.yaml` |
| `api/` | 5 | `routers/publishing_policy.py`, `routers/scheduler.py`, `routers/settings.py`, `services/config_service.py`, `services/publishing_policy_service.py` |
| `frontend/` | 4 | `src/api/client.js`, `src/components/BlogSchedulerPanel.jsx`, 테스트 2 |
| `content/` | 3 | `blog/writer.py`, `calculator/prompt.py`, `calculator/writer.py` |
| 루트 | 3 | `dashboard.py`, `requirements.txt`, `run_sync.py` |
| 기타 | 10 | `repositories/`(article, calculator) 2, `content_pipeline/` 2, `scripts/`(`_rebuild_site.py`, `run_blog_scheduler.py`) 2, `tools/dev_assistant.py`, `templates/calculators/assets/components.js`, `data/sync/pending_sync.json`, `config/config.yaml` |

확인된 그룹 (여기에 없는 파일은 **소유 미분류 — 건드리지 않는다**):

| 그룹 | 대상 | 영역 |
|---|---|---|
| 계산기 품질 작업 (미커밋) | `app_factory` 나머지 hunk(저장소 전환 H16 등, formula 재시도, schema gate 호출), `formula_engine` H1, `review_center` H1–H17, `calculator_repository` | CALCULATOR (채택 여부 OWNER DECISION) |
| 계산기 운영 데이터 | `docs/registry_auto.yaml`, `docs/registry/labor_af.yaml`, `docs/calculator_index.json`, `docs/contract_schema/registry.yaml` | CALCULATOR 데이터 |
| 대시보드 API/UI 작업 (미커밋) | `api/` 5개 파일, `frontend/src/api/client.js`, `BlogSchedulerPanel.jsx` | INFRA / BLOG UI |
| 미커밋 B hunk | `modules/config_loader.py` C1/C4, `modules/scheduler.py` S6–S8 | INFRA / BLOG |
| 설정·동기화 데이터 | `config/config.yaml`, `data/sync/pending_sync.json` | INFRA |
| Streamlit legacy | `dashboard.py`, `modules/setup_wizard.py`(D) | legacy |

---

## 2. ARCHITECTURE

| 구성 | 상태 | 근거 |
|---|---|---|
| React | 공식 UI | `frontend/`, `BASE_URL`은 기본 `''` (`frontend/src/api/client.js:12`) |
| Vite proxy | `/api` → `http://127.0.0.1:8000` | `frontend/vite.config.js` |
| FastAPI | 공식 backend, 라우터 14개 mount | `api/main.py` (`app = FastAPI`) |
| 실행 스크립트 | `start_dashboard.bat` (untracked): uvicorn `--host 127.0.0.1 --port 8000` + Vite `127.0.0.1:5173` | `start_dashboard.bat:69`, `:93` |
| Streamlit | **제거됨.** `dashboard.py` 삭제(`6c9f78c`), `scripts/install.bat`의 Streamlit 실행 블록 제거. 삭제된 legacy launcher: `scripts/run_dashboard.bat`, `scripts/start_dashboard_autostart.bat` | 재도입 금지 |
| 인증 | `CALCMATE_DASHBOARD_LOCAL_MODE=1`(Windows 사용자 환경변수)이면 모든 요청이 local-admin | `api/auth/dependencies.py` |
| CORS / Origin 검사 | 없음 (HARDEN-01, HOLD) | `api/` 전체 검색 |
| 프론트엔드 커밋 상태 | `frontend/src`는 10개 파일만 tracked. `Calculators.jsx`, `CalculatorDetail.jsx` 등 대부분 untracked | `git ls-files` |

migration 상태: 계산기 생성 API(A1)와 대시보드 라우터(A2)는 커밋됐다.
나머지 Streamlit 전용 기능(AI Assistant/Workspace, 설정 일부, 설정 마법사 대체 등)은 미이관이다.

---

## 3. CALCULATOR

| 단계 | 경로 | 상태 |
|---|---|---|
| 생성 | `Calculators.jsx` → `POST /api/calculators/generate`(Mode A) / `/generate/contract`(Mode B) → `calculator_service` → `generation_job_store`(메모리) → `app_factory.generate_app` / `generate_app_with_contract` | 사용 가능 |
| job 조회 | `GET /api/calculators/generate/{job_id}`, `/generate/contract/{job_id}` | 사용 가능 |
| 검토 | `CalculatorDetail.jsx`: checklist/formula PATCH, `review/approve·unapprove`(메모리, 재시작 시 소실), `promote`(`_af.yaml` status → READY) | 사용 가능 |
| 저장 | `app_factory.save_app` (Mode A는 job 안에서 자동, Mode B는 `/generate/contract/{job_id}/save`) | 사용 가능 |
| Build | `POST /api/calculators/{slug}/build` → `write_site_snapshot` → `data/workspace/_site/{slug}/`만 씀 | 사용 가능 |
| Deploy | `POST /api/calculators/{slug}/deploy` → `github_deployer.deploy_app` → GitHub `calcmate/calcmate` → `https://calcmate.github.io/calcmate/{slug}/` → DB `published_url` | **HOLD (배포 대상 결정 필요)** |

관련 커밋: `b5e2bdc`(A1), `36ec7ab`(`calculator_service`), `4e535b3`(라우터 mount).

실행 시 주의:

- 서버는 worktree에서 실행되므로 미커밋 품질 hunk(저장소 전환, schema gate, formula 재시도, checklist 변경)가 함께 적용된다.
- 저장 한 번이 다음 파일을 다시 쓴다.
  - `registry_auto.yaml`, `_af.yaml`: 전체 재작성이지만 기존 항목은 바이트 동일 (메모리에서 재현해 확인)
  - `calculator_index.json`: calculators DB 기준 전량 재생성 → 현재 파일의 **5건이 사라진다**
    - IRP 잔재 2건: `irp-tax-credit-v2`, `연금저축_irp_세액공제_계산기`
    - Golden10 slug 3건: `four-insurances-documents`, `severance-pay-documents`, `unemployment-benefit-howto`

데이터 현황:

- calculators DB 14건: 모두 active, 모두 `published_url` 있음 (host: `calcmate.github.io` 10건, `calcmate.kr` 4건)
- v3 registry 14건 (READY 6)
- IRP 2건은 DB에 없고 registry/index에만 남은 잔재

현재 HOLD: Deploy, `calculator_index` 재생성 동작, 운영 데이터 처리 방침.

---

## 4. BLOG

### URL 구조

```
Public / Production:  https://calcmate.kr/blog/     (blog_articles.canonical_url 11/11)
WordPress Origin:     https://blog.genon.app         (blog_articles.wp_permalink 11/11)
```

- `blog.genon.app`은 origin이며 공개 URL이 아니다. Cloudflare 설정은 변경하지 않는다.

### WordPress 대상 해석 (코드 사실)

- `config/config.yaml`의 `WORDPRESS_URL` = host **`salarymate.test`** (SalaryMate 로컬 WP, **사용 금지**)
- production = `config/secrets.yaml`의 `wordpress.url` = host `blog.genon.app`. `load_config(wp_target="production")`일 때만 적용된다.

| 경로 | WP 대상 |
|---|---|
| FastAPI one-off/blog worker (`api/services/worker_manager.py`, `CALCMATE_WP_TARGET`) | production |
| `api/services/publishing_planner_service.py` (`CALCMATE_WP_TARGET`) | production |
| `modules/content_sync.py` (`_production_wp_cfg`) | production |
| `api/services/blog_scheduler_service._blog_cfg()` — React 수동 run-once / Golden10 1회 실행 | **기본값 = salarymate.test** |
| `api/services/publish_service` (WP 수정/휴지통/복원), `cost_service` (retry 발행), `health_service` (외부 점검) | **기본값 = salarymate.test** |
| `scripts/run_blog_oneoff_scheduler_loop.py` | `_wp_target` 미설정 → one-off 루프가 예약을 소비하지 않음 |
| `modules/wp_blog_deploy.py` (Windows 작업 `\블로그배포`) | `load_config()` 기본값. 실제 조회 대상 **미검증** |

→ 위 "기본값 = salarymate.test" 경로는 **FOUND → OWNER DECISION** 대상이다. 신규 BLOG 작업에 사용하지 않는다.

### 생산 단계

| 단계 | 경로 | 상태 |
|---|---|---|
| Topic 생성 | `modules/topic_pool.create_topic` 존재. **API/UI 없음** (생성은 HOLD 모듈 `topic_candidate_generator`에만 있음) | 수정 필요 |
| Approval | `topic_pool.transition_status(..., "approved")` 존재(candidate→approved 허용). **호출 경로 없음** | 수정 필요 |
| One-off 예약 | `POST /api/scheduler/blog/oneoff` → `create_oneoff_reservation` (topic이 approved여야 함) | 사용 가능, 승인 공백 때문에 막힘 |
| One-off 실행 | FastAPI worker만 동작 가능. `AUTO_PUBLISHING` 또는 `BLOG_SCHEDULE`이 켜져야 시작하고, 켜지면 기한 지난 예약을 모두 즉시 실행 | 수정 필요 |
| WP Draft | `topic_publish_adapter.run_topic_once_wp` → writer(AI) → 무결성 검사 → WP 중복 확인 → `publish(status="draft", category_name=topic.category, comment_status="closed", 이미지 없음)` | 코드 존재, 실행 경로 없음 |
| WP Publish | 같은 경로, `mode=publish` | 코드 존재, 실행 경로 없음 |
| Recurring scheduler | `BLOG_SCHEDULE.enabled=false` | HOLD |

현재 플래그: `BLOG_SCHEDULE.enabled=false`(mode draft), `AUTO_PUBLISHING.enabled=false`.
Windows 작업: `\블로그1회예약` 삭제됨(2026-10-04). 프로젝트 Task는 `\CalcMate-FastAPI`, `\블로그배포`만 남아 있다.

데이터 현황:

- `topic_pool`: candidate 4, publish_failed 7, published 7, scheduled 1 (approved 0)
- 과거 E2E 예약 2건이 pending 상태다 (**실행 금지, OWNER DECISION 대기**)

| 예약 | 예정 시각 | mode | 연결 topic | topic 상태 |
|---|---|---|---|---|
| `oneoff_20260926125935_54f783` | 2026-09-28 10:36 (기한 지남) | draft | `topic_20260926031332_218bbb` | scheduled |
| `oneoff_20260926133925_d6bced` | 2026-10-02 15:06 | draft | `topic_20260926043334_a2f327` | publish_failed |

---

## 5. GOLDEN10

- 정의: `content/blog/__init__.py:36` `GOLDEN_10` (10건)
- 실행 함수: `modules/blog_scheduler_adapter.run_blog_once_wp`, `main.resolve_blog_publish_fn`
- `blog_articles` 11건 중 WP ID **502–512의 10건이 Golden10**이다. 585는 BMI 계산기 글이다. 11건 모두 `publish`.
- topic_id가 있는 one-off 예약은 `run_topic_once_wp`로만 가므로 Golden10 경로를 타지 않는다.
- 보호 대상: Golden10 게시글, `blog_articles`, Golden10 관련 slug 데이터. CALCULATOR/BLOG 작업에서 자동 수정 금지.
- 교차 영향 (발견 사항): 계산기 저장 시 `calculator_index.json` 재생성이 Golden10 slug 3건을 지운다(§3).
- WP 측 실제 값(category, comment_status, featured_media)은 WP를 조회하지 않아 **미검증**이다.

---

## 6. HOLD (현재 구현하지 않음)

- 계산기 Deploy (배포 대상 결정 전)
- Recurring 블로그 자동 발행
- Health, Costs, Sites, Strategy Room, Workboard, KPI 화면의 추가 작업
- HARDEN-01 (LOCAL_MODE 교차 사이트 POST 차단)
- HARDEN-02 (costs/retry가 기본값으로 실제 발행)
- HARDEN-03 (sites 생성 시 `secrets.yaml` 전체 재작성·덮어쓰기)
- HARDEN-04 (AI 비용 엔드포인트 확인 절차)
- HARDEN-05 (대시보드 캐시가 GET 중 Sheets 조회)
- 계산기 품질 작업(B-1~B-6) 채택 여부
- Streamlit 삭제, 프론트엔드 untracked 정리, 전체 대시보드 정리

## 7. 다음 단계 최소 수정 후보 (미구현)

| ID | 내용 | 분류 |
|---|---|---|
| MVP-MIN-01 | 토픽 승인 API + UI (`transition_status` 재사용, 새 라우터 파일 권장) | REQUIRED |
| MVP-MIN-02 | 토픽 수동 생성 API + UI (`create_topic` 재사용) | REQUIRED |
| MVP-MIN-03 | 지정한 예약 1건만 실행하는 API (production 설정, 기한 지난 예약 일괄 실행 방지) | REQUIRED |
| MVP-MIN-04 | 예약 취소 기능 | OPTIONAL |

## 8. OWNER DECISION 대기

1. 계산기 E2E 전 운영 데이터 처리 방침 (`calculator_index` 5건 소실 포함)
2. 과거 E2E 예약 2건 처리 (KEEP / CANCEL / DELETE / RESCHEDULE)
3. 계산기 배포 대상 (`calcmate.github.io/calcmate` vs `calcmate.kr`)
4. salarymate.test를 기본 대상으로 쓰는 FastAPI 경로(§4 표) 처리
5. `data/workspace/_site/index.html`, `sitemap.xml`의 OWNER (`site_generator` vs `wp_blog_deploy`)
