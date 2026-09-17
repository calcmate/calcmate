# CalcMate Dashboard 최종 운영 전수검수 보고서

**작업일:** 2026-08-21  
**작업 범위:** READ-ONLY 전수검수 (코드 수정 없음)  
**FINAL VERDICT:** PASS WITH WARNINGS

---

## Executive Summary

Dashboard가 Calculator Line과 Blog Line을 독립적으로 관리·제어하는 구조를 전수검사한 결과, **라인 자체는 완전히 분리**되어 있으나, **Scheduler 인프라(lock, schedule 파일, config 슬롯)**를 공유하는 구조적 이슈가 발견되었다.

현재 두 스케줄러 모두 **OFF** 상태이므로 실시간 충돌은 발생하지 않으나, 향후 양쪽을 동시에 ON할 경우 lock 경합과 schedule 파일 충돌이 예상된다.

---

## STEP 0. 작업 전 상태

| 항목 | 값 |
|------|-----|
| HEAD | `27afbe2` |
| branch | `master` |
| Calculator Scheduler | `PUBLISH_SCHEDULE.enabled: false` |
| Blog Scheduler | `BLOG_SCHEDULE.enabled: false` |
| CONTENT_SYNC | `enabled: true` (매일 03:00) |
| OPERATION_MODE | `scheduled` |
| DAILY_POST_COUNT | `1` |
| Python processes | `run_sync.py` 2개만 (WP→Sheets 동기화) |
| Windows Task Scheduler | CalcMate 등록 없음 |
| run_scheduler.bat | `.disabled` |
| DB hash | `33e10f342b7fd81da7f9806864e0eccb` |
| Golden 10 hash | 10/10 UNCHANGED |

---

## STEP 1. Dashboard 구조 추적

### 1-1. Calculator Schedule UI

**위치:** `dashboard.py` → `📅 오늘 발행 일정` 탭 (line 887~)

| 기능 | 경로 | 상태 |
|------|------|------|
| ON/OFF toggle | `st.toggle("스케줄러 사용(enabled)")` → `PUBLISH_SCHEDULE.enabled` | ✅ |
| 발행 건수 | `st.number_input("하루 발행 개수")` → `DAILY_POST_COUNT` | ✅ |
| 발행 시간(평일) | `_slot_editor("weekday")` → `PUBLISH_SCHEDULE.weekday` | ✅ |
| 발행 시간(주말) | `_slot_editor("weekend")` → `PUBLISH_SCHEDULE.weekend` | ✅ |
| 실패 모드 | `st.selectbox("실패 처리 모드")` → `PUBLISH_SCHEDULE.failure_mode` | ✅ |
| 설정 저장 | `yaml.dump()` → `config.yaml` + `load_cfg.clear()` | ✅ |
| 실행 상태 | `_alive = threading.enumerate()` → `scheduler-loop` 스레드 확인 | ✅ |
| 마지막 실행 | 슬롯 `completed_at` / `actual_time` | ✅ |
| 다음 실행 | `summarize()["next"]` | ✅ |
| 오류 상태 | `result` 필드 (미생산/오류/HOLD) | ✅ |
| 즉시발행 | `immediate_publish()` | ✅ |
| 재시도 | `execute_due_post()` | ✅ |

**진입 경로:**
```
Dashboard UI (📅 오늘 발행 일정)
  → 슬롯 설정 저장 (config.yaml)
  → PUBLISH_SCHEDULE.enabled = true
  → Dashboard 시작 시 _start_scheduler_thread()
  → threading.Thread(name="scheduler-loop")
  → run_scheduler_loop(cfg, resolve_publish_fn(cfg))
  → resolve_publish_fn() → run_calculator_once
```

### 1-2. Blog Schedule UI

**위치:** `config/config.yaml` → `BLOG_SCHEDULE` 섹션

| 기능 | 현재 상태 | 비고 |
|------|-----------|------|
| ON/OFF | `BLOG_SCHEDULE.enabled: false` | config에서만 제어 |
| mode | `draft` | draft/publish 선택 가능 |
| publish_slots | `[{start: "10:00", end: "10:30"}]` | 기록됨 |
| daily_count | `None` | 미설정 |
| failure_mode | `None` | 미설정 |
| **Dashboard UI** | **없음** | ⚠️ Calculator와 달리 UI 없음 |

**진입 경로:**
```
Dashboard 시작 시
  → cfg.get("BLOG_SCHEDULE", {}).get("enabled", False)
  → False → _start_blog_scheduler_thread() 호출 안 함
  
만약 enabled=true라면:
  → _start_blog_scheduler_thread()
  → threading.Thread(name="blog-scheduler-loop")
  → run_scheduler_loop(cfg, resolve_blog_publish_fn(cfg))
  → resolve_blog_publish_fn() → run_blog_once (draft) 또는 run_blog_once_wp (publish)
```

---

## STEP 2. Calculator Line 검증

| 검사 항목 | 결과 | 비고 |
|-----------|------|------|
| Calculator → Blog import | **0건** ✅ | `calculator_pipeline.py`에서 blog 관련 import 없음 |
| Blog Scheduler 호출 | **없음** ✅ | Calculator 라인에서 blog 호출 안 함 |
| WordPress 발행 | `publisher.publish()` 경유 ✅ | Calculator 전용 발행 경로 |
| Calculator 설정 → Blog 영향 | **없음** ✅ | 별도 config 섹션 |
| Calculator ON/OFF → 실제 scheduler 반영 | **반영** ✅ | `PUBLISH_SCHEDULE.enabled` → thread 시작 조건 |
| 최종 목적지 | **웹앱** ✅ | `data/workspace/_site/` |

---

## STEP 3. Blog Line 검증

| 검사 항목 | 결과 | 비고 |
|-----------|------|------|
| Blog → Calculator Pipeline import | **0건** ✅ | `blog_scheduler_adapter.py`에서 `calculator_pipeline` 미import |
| Calculator Scheduler 호출 | **없음** ✅ | 독립 스레드 |
| Blog 설정 → Calculator 영향 | **없음** ✅ | 별도 config 섹션 |
| Blog ON/OFF → 실제 scheduler 반영 | **반영** ✅ | `BLOG_SCHEDULE.enabled` → thread 시작 조건 |
| WordPress 연결 | **PASS** ✅ | `http://salarymate.test`, user=geminia |
| 중복 발행 방지 | `_check_wp_duplicate()` ✅ | slug 기반 WP 검색 |
| Draft/Publish 모드 | `mode` 설정 ✅ | `draft`=격리출력 / `publish`=WP 발행 |
| 실패 시 fallback | `run_blog_once()` isolated output ✅ | WP 미연결 시 격리 출력 |
| DB write | **0건** ✅ | calculators/articles 테이블 미접근 |
| 최종 목적지 | **WordPress** ✅ | |

---

## STEP 4. Scheduler 독립성 검증

### 4-1. 스레드 독립성

| 구분 | Calculator | Blog |
|------|------------|------|
| 스레드 이름 | `scheduler-loop` | `blog-scheduler-loop` |
| 시작 조건 | `PUBLISH_SCHEDULE.enabled == True` | `BLOG_SCHEDULE.enabled == True` |
| thread target | `run_scheduler_loop(cfg, resolve_publish_fn)` | `run_scheduler_loop(cfg, resolve_blog_publish_fn)` |
| duplicate guard | `threading.enumerate()` 확인 ✅ | `threading.enumerate()` 확인 ✅ |

### ⚠️ 4-2. 공유 자원 충돌 (P1)

| 공유 자원 | Calculator 사용 | Blog 사용 | 충돌 위험 |
|-----------|----------------|-----------|-----------|
| `data/schedule/scheduler.lock` | ✅ | ✅ | **동일 파일** ⚠️ |
| `data/schedule/today_schedule.json` | ✅ | ✅ | **동일 파일** ⚠️ |
| `data/schedule/history.jsonl` | ✅ | ✅ | **동일 파일** ⚠️ |
| `PUBLISH_SCHEDULE` slots | ✅ | ❌ | — |
| `BLOG_SCHEDULE` slots | ❌ | 기록됨 | — |
| `config.yaml` | ✅ | ✅ | 읽기만 (write 없음) |

**상세 분석:**

1. **Lock 경합**: 두 스케줄러가 동일한 `scheduler.lock`을 사용. 한쪽이 lock을 잡으면 다른 쪽은 "다른 실행이 진행 중"으로 건너뜀.

2. **Schedule 파일 충돌**: `run_scheduler_loop()` 내부의 `ensure_today_schedule()`이 `PUBLISH_SCHEDULE` 기반으로 `today_schedule.json`을 생성. Blog 스케줄러도 동일 함수를 호출하므로, Blog 스케줄러는 Blog 전용 슬롯이 아니라 Calculator 슬롯을 사용.

3. **后果**: 현재 두 스케줄러 모두 OFF이므로 실시간 충돌 없음. 그러나 양쪽 ON 시:
   - 한쪽이 lock을 잡으면 다른 쪽 idle
   - 같은 schedule 파일에서 서로 다른 `run_once_fn`을 호출하려 함
   - Blog 스케줄러의 `publish_slots` 설정이 실제로 사용되지 않음

---

## STEP 5. 발행 건수 검증

| 항목 | Calculator | Blog |
|------|------------|------|
| 설정 위치 | `DAILY_POST_COUNT` | `BLOG_SCHEDULE.daily_count` (None) |
| Dashboard UI | `st.number_input` ✅ | **없음** ⚠️ |
| Scheduler 적용 | `get_slots_for()` → slot 수 = 건수 ✅ | `run_scheduler_loop`에서 `max_count=1` 고정 |
| 독립 제어 | **가능** ✅ | **config만** (UI 미구현) |

---

## STEP 6. 발행 시간 검증

| 항목 | Calculator | Blog |
|------|------------|------|
| 설정 위치 | `PUBLISH_SCHEDULE.weekday/weekend` | `BLOG_SCHEDULE.publish_slots` |
| Dashboard UI | **있음** (평일/주말 분리 슬롯 에디터) ✅ | **없음** ⚠️ |
| 저장 경로 | `config.yaml` → `yaml.dump()` | config에 기록됨 |
| 시간 반영 | `get_slots_for()` → 슬롯 기반 ✅ | `run_scheduler_loop` → 동일 schedule 파일 사용 |
| timezone | 로컬 시간 기준 ✅ | 동일 |
| 잘못된 시간 | `validate_slots()` 검증 ✅ | — |

---

## STEP 7. 실행 상태 검증

| 상태 | Dashboard 표시 | 실제 상태 | 일치 |
|------|---------------|-----------|------|
| OFF | `🔴 정지` | 스레드 미시작 | ✅ |
| ON+live | `🟢 Running` | `scheduler-loop` alive | ✅ |
| Paused | `🔴 Paused(중지)` | cost_manager paused | ✅ |
| Next run | `summarize()["next"]` | pending 슬롯 기준 | ✅ |

**상태 표시 진실성:** PASS ✅  
Dashboard의 ON/OFF 표시가 실제 스레드 상태와 일치함.

---

## STEP 8. 재시작 안정성

| 항목 | 결과 | 비고 |
|------|------|------|
| Calculator 설정 유지 | **유지** ✅ | `config.yaml`에 영속 저장 |
| Blog 설정 유지 | **유지** ✅ | `config.yaml`에 영속 저장 |
| 스레드 중복 방지 | **방지** ✅ | `threading.enumerate()` 가드 |
| 유령 프로세스 | **없음** | daemon 스레드 (Dashboard 종료 시 자동 소멸) |
| lock 중복 | `scheduler.lock` stale 30분 → 자동 해제 ✅ | |

---

## STEP 9. 법령/요율 변경 감지 시스템

| 항목 | 상태 | 비고 |
|------|------|------|
| Entry point | `main.py --detect-revisions` | CLI 전용 |
| Scheduler 연결 | **없음** ✅ | 자동 스케줄 없음 |
| 실행 주기 | 수동 | Dashboard에서 자동 실행 안 됨 |
| SSOT 비교 | `data/legal/revision_state.json` | hash/etag 비교 |
| 변경 알림 | Telegram | `telegram_ops.notify_level()` |
| Detect-only | **유지** ✅ | 자동 콘텐츠 변경 없음 |
| Calculator Line 연결 | `find_impacted()` → 영향 대상 식별 | 읽기만 |
| Blog Line 연결 | **없음** | 감지 후 사람이 판단 |
| Dashboard 표시 | **없음** ⚠️ | 법령 감지 상태를 Dashboard에서 확인 불가 |
| 생성 라인과 혼동 | **없음** ✅ | 완전히 별도 모듈 |

---

## STEP 10. 최종 목적지 검증

| 라인 | 의도 | 실제 경로 | 검증 |
|------|------|-----------|------|
| Calculator → 웹앱 | ✅ | `data/workspace/_site/` | ✅ |
| Blog → WordPress | ✅ | `publisher.publish()` → WP REST API | ✅ |
| Calculator → WordPress | 금지 | `publisher.py` 호출하지 않음 | ✅ |
| Blog → Calculator App | 금지 | `calculator_pipeline` 미사용 | ✅ |

---

## STEP 11. 안전성 검증

| 보호 대상 | 상태 | 비고 |
|-----------|------|------|
| Golden 10 | **UNCHANGED** ✅ | 10/10 hash 동일 |
| calculators.article_content | **UNCHANGED** ✅ | |
| Calculator logic | **UNCHANGED** ✅ | |
| SSOT | **UNCHANGED** ✅ | |
| Registry | **UNCHANGED** ✅ | |
| Image Pipeline | **미호출** ✅ | |
| WordPress 기존 데이터 | **UNCHANGED** ✅ | |
| DB | `33e10f342b7fd81da7f9806864e0eccb` 동일 ✅ | |

---

## STEP 12. Regression

| 테스트 | 결과 |
|--------|------|
| 전체 regression | **945 passed, 4 skipped** ✅ |
| 기존 baseline 대비 | **변경 없음** ✅ |
| 신규 failure | **없음** ✅ |

---

## STEP 13. 문제 분류

### [P1] 운영 전 수정 필요

| # | 문제 | 파일 | 현재 동작 | 기대 동작 | 영향 |
|---|------|------|-----------|-----------|------|
| 1 | **Scheduler lock 공유** | `modules/scheduler.py` | Calculator/Blog 동일 `scheduler.lock` 사용 | 라인별 독립 lock | 양쪽 ON 시 한쪽이 lock 경합으로 대기 |
| 2 | **Schedule 파일 공유** | `modules/scheduler.py` | Calculator/Blog 동일 `today_schedule.json` 사용 | 라인별 독립 schedule | Blog 스케줄러가 Calculator 슬롯 기반으로 동작 |
| 3 | **Blog Schedule UI 미구현** | `dashboard.py` | Blog는 config에서만 ON/OFF 제어 | Dashboard에서 독립 제어 | 운영 편의성 저하 |
| 4 | **BLOG_SCHEDULE.slots 미사용** | `modules/scheduler.py` | `run_scheduler_loop`가 `PUBLISH_SCHEDULE` 기반 schedule 생성 | Blog 전용 schedule | `BLOG_SCHEDULE.publish_slots` 설정이 사실상 무의미 |

### [P2] 운영 후 수정 가능

| # | 문제 | 비고 |
|---|------|------|
| 5 | 법령감지 Dashboard 표시 없음 | CLI에서만 실행 가능 |
| 6 | Blog `daily_count` 미설정 | 기본값 없음 |
| 7 | Blog `failure_mode` 미설정 | 기본값 없음 |

### [INFO] 관찰사항

| # | 항목 | 비고 |
|---|------|------|
| 8 | Calculator 슬롯 평일 1개, 주말 1개 | 현재 설정 |
| 9 | WP draft 89건 적체 | 기존 발행분 |
| 10 | CONTENT_SYNC 매일 03:00 실행 | 정상 동작 |

---

## STEP 14. 최종 판정

| 영역 | 상태 |
|------|------|
| Calculator Dashboard | **PASS** |
| Blog Dashboard | **WARN** (UI 미구현) |
| Calculator ON/OFF | **PASS** |
| Blog ON/OFF | **PASS** (config만) |
| Calculator 발행 건수 | **PASS** |
| Blog 발행 건수 | **WARN** (config만) |
| Calculator 발행 시간 | **PASS** |
| Blog 발행 시간 | **WARN** (Calculator 슬롯 공유) |
| 실행 상태 | **PASS** |
| 마지막 실행 | **PASS** |
| 다음 실행 | **PASS** |
| 오류 상태 | **PASS** |
| Scheduler 독립성 | **WARN** (lock/schedule 공유) |
| Dashboard 재시작 | **PASS** |
| 법령/요율 감지 | **PASS** (Detect-only) |
| Calculator → 웹앱 | **PASS** |
| Blog → WordPress | **PASS** |
| Golden 10 보호 | **PASS** |
| DB 무결성 | **PASS** |
| Regression | **PASS** |

---

## 1. 운영 가능 여부

**Conditionally READY** — 현재 두 스케줄러 모두 OFF 상태이므로 충돌 없음. 

단독 실행 시:
- Calculator Scheduler ON → **정상 동작 가능**
- Blog Scheduler ON → **정상 동작 가능** (단, PUBLISH_SCHEDULE 슬롯 사용)

동시 ON 시:
- lock 경합으로 한쪽이 대기하는 구조적 문제 존재
- **동시 ON은 현재 권장하지 않음**

## 2. 운영 전 반드시 수정할 문제

| 우선순위 | 문제 | 수정 방향 |
|----------|------|-----------|
| **P1-1** | lock/schedule 파일 공유 | `run_scheduler_loop()`에 `schedule_dir` 파라미터 추가, 라인별 독립 경로 |
| **P1-2** | Blog Schedule UI 미구현 | Dashboard에 Blog 전용 스케줄 탭 추가 |
| **P1-3** | BLOG_SCHEDULE.slots 미사용 | Blog 스케줄러가 자체 schedule 파일 사용하도록 변경 |

## 3. 운영 후 수정 가능한 문제

- 법령감지 Dashboard 표시
- Blog daily_count/failure_mode 기본값 설정

## 4. 다음 작업 순서

1. **[P1] Scheduler 라인별 격리** — lock + schedule 파일 분리 (가장 시급)
2. **[P1] Blog Schedule UI** — Dashboard에 Blog 전용 탭 추가
3. **Blog Scheduler 단독 ON 테스트** — Calculator OFF 상태에서 Blog만 실행
4. **동시 ON 테스트** — 격리 구조 구현 후 동시 동작 검증

---

## 현재에서 건드리면 안 되는 항목

- Golden 10 원본 article_content
- calculator_pipeline.py 계산 로직
- SSOT (legal_basis.master.yaml)
- registry
- run_sync.py / run_sync.bat
- WordPress 기존 게시물
- config/wordpress.yaml 자격증명
