# Calculator Scheduler 최종 재검수 — READ-ONLY 진단 보고서

**작업일시:** 2026-08-21  
**작업자:** Buffy (Codebuff)  
**버전:** HEAD 27afbe2  
**진단 유형:** READ-ONLY (코드 수정 없음)

---

## Executive Summary

Calculator Scheduler는 현재 **OFF 상태**이며, 코드 수준에서 다음이 확인되었습니다.

1. **Calculator Line은 WordPress Publisher와 Image Pipeline를 호출합니다** — 이는 "웹앱 전용 라인"이 아닙니다.
2. **Calculator Line과 Blog Line은 lock/schedule/history에서 완전히 격리되어 있습니다.**
3. **자동 실행 경로는 모두 차단된 상태입니다.**

**FINAL VERDICT: PASS WITH ISSUES** ⚠️

---

## STEP 0: 현재 상태

| 항목 | 값 |
|------|-----|
| HEAD | 27afbe2 |
| PUBLISH_SCHEDULE.enabled | **False** |
| PUBLISH_MODE | calculator |
| BLOG_SCHEDULE.enabled | **False** |
| BLOG_SCHEDULE.mode | draft |
| DB tables | **비어있음** (calculators 테이블 없음) |
| Python processes | **0** |
| Windows Task Scheduler | **CalcMate 작업 없음** |
| run_scheduler.bat | `.disabled` |

---

## STEP 1: Calculator Scheduler 진입점

```
Dashboard (PUBLISH_SCHEDULE.enabled)
  → cfg["scheduler_line"] = "calculator"
  → _start_scheduler_thread() [dashboard.py:71]
  → thread: "scheduler-loop"
  → run_scheduler_loop(cfg, resolve_publish_fn(cfg))
  → PUBLISH_MODE="calculator"
  → run_calculator_once [modules/calculator_pipeline.py:253]
```

**확인:** `resolve_publish_fn()`은 `PUBLISH_MODE="calculator"`일 때 `run_calculator_once`를 반환합니다.

**확인:** `run_calculator_once`는 `blog_scheduler_adapter`를 **import하지 않습니다.**

| 검사 항목 | 결과 |
|-----------|------|
| run_calculator_once 호출 | **PASS** ✅ |
| run_blog_once 호출 | **없음** ✅ |
| blog_scheduler_adapter import | **없음** ✅ |

---

## STEP 2: Calculator / Blog 격리

### Lock 격리

| 라인 | lock 경로 |
|------|-----------|
| Calculator | `data/schedule/scheduler.lock` |
| Blog | `data/schedule/blog/scheduler.lock` |
| **격리** | **PASS** ✅ |

### Schedule 격리

| 라인 | schedule 경로 |
|------|---------------|
| Calculator | `data/schedule/today_schedule.json` |
| Blog | `data/schedule/blog/today_schedule.json` |
| **격리** | **PASS** ✅ |

### History 격리

| 라인 | history 경로 |
|------|-------------|
| Calculator | `data/schedule/history.jsonl` |
| Blog | `data/schedule/blog/history.jsonl` |
| **격리** | **PASS** ✅ |

### scheduler_line 분리

| 라인 | scheduler_line |
|------|----------------|
| Calculator | `"calculator"` |
| Blog | `"blog"` |
| **격리** | **PASS** ✅ |

---

## STEP 3: Dashboard 제어

| 항목 | Calculator | Blog | 독립성 |
|------|-----------|------|--------|
| ON/OFF | `PUBLISH_SCHEDULE.enabled` | `BLOG_SCHEDULE.enabled` | **PASS** ✅ |
| 스레드 | `scheduler-loop` | `blog-scheduler-loop` | **PASS** ✅ |
| 설정 저장 | `PUBLISH_SCHEDULE` | `BLOG_SCHEDULE` | **PASS** ✅ |

---

## STEP 4: Config 연결

| 설정 | Calculator 사용 | Blog 사용 |
|------|----------------|-----------|
| `PUBLISH_SCHEDULE` | **YES** ✅ | NO |
| `BLOG_SCHEDULE` | NO | **YES** ✅ |
| `scheduler_line` | `"calculator"` | `"blog"` |

---

## STEP 5: ⚠️ Calculator 목적지 — CRITICAL FINDING

### 현재 설계 (이전 보고서 기준)

```
Calculator Line → Calculator 생성/관리 → 웹앱
Blog Line → Blog 생성/발행 → WordPress
```

### 실제 코드 동작

```
Calculator Scheduler
  → run_calculator_once()
  → calculator_pipeline.py
  → image_generator.generate()      ← Image Pipeline 호출 ✅
  → publisher.publish()             ← WordPress Publisher 호출 ✅
  → art_repo.save()                 ← DB write ✅
```

### 발견된 문제

**[ISSUE]**
- **파일:** `modules/calculator_pipeline.py`
- **위치:** lines 547-611
- **현상:** Calculator Line이 WordPress Publisher와 Image Pipeline를 직접 호출
- **원인:** 기존 Calculator Pipeline가 "계산기 키워드 기반 SEO 글 생성 + WP 발행" 경로
- **영향:** Calculator Scheduler가 ON이면 WordPress에 자동 발행됨
- **수정 대상 파일:** `modules/calculator_pipeline.py`
- **수정 우선순위:** P1 (운영 전 확인 필요)

### 상세 분석

```python
# calculator_pipeline.py:547-556
from . import publisher  # WP 발행 시점에만 로드
pub = publisher.publish(post_id, {...}, final_html, image_urls, cfg)
```

Calculator Line은 다음을 수행합니다:
1. SEO 글 생성 (`generate_seo`)
2. FAQ 생성 (`generate_faq`)
3. 계산기 위젯 생성 (`generate_calculator`)
4. **이미지 생성 (`image_generator.generate`)** ← Image Pipeline
5. **WordPress 발행 (`publisher.publish`)** ← WP Publisher
6. **DB 저장 (`art_repo.save`)** ← Articles 테이블

---

## STEP 6: DB 영향 범위

| 라인 | DB 접근 |
|------|---------|
| Calculator | `art_repo.save()` → articles 테이블 |
| Blog | DB write **없음** (isolated output만 생성) |

**확인:** Calculator Line이 articles 테이블에 write하지만, Blog Line은 write하지 않습니다.

---

## STEP 7: 법령/요율 변경 감지

| 항목 | 상태 |
|------|------|
| 시스템 | `revision_detector.py` (Detect Only) |
| 자동 반영 | **없음** ✅ |
| 알림 | Telegram 알림 후 사람 판단 |
| Calculator/Blog 독립성 | **PASS** ✅ |

---

## STEP 8: 자동 실행 위험

| 경로 | 상태 |
|------|------|
| `run_scheduler.bat` | `.disabled` ✅ |
| `main.py --scheduler` | `--scheduler` 플래그 필요 ✅ |
| Dashboard thread | `PUBLISH_SCHEDULE.enabled=False` → 미시작 ✅ |
| Windows Task Scheduler | **CalcMate 작업 없음** ✅ |

**자동 실행 위험: 없음** ✅

---

## STEP 9: Dry-run 시뮬레이션

| 항목 | 결과 |
|------|------|
| Schedule 생성 | **PASS** ✅ |
| callback 선택 | `run_calculator_once` ✅ |
| Module | `modules.calculator_pipeline` ✅ |

---

## STEP 10: 동시성 검증

| 검사 항목 | 결과 |
|-----------|------|
| 동일 lock 사용 | **없음** ✅ |
| 동일 schedule 파일 | **없음** ✅ |
| 동일 history 파일 | **없음** ✅ |
| 전역 변수 공유 | **없음** ✅ |
| config mutation | **없음** ✅ |
| callback 교체 | **없음** ✅ |
| DB 충돌 | **Calculator만 write** ✅ |
| WP 호출 충돌 | **Calculator만 call** ✅ |

---

## STEP 11: P1/P2 재확인

| 문제 | 상태 |
|------|------|
| calculators 테이블 비어있음 | **동일** (DB tables: []) |
| WP Draft 89건 적체 | **확인 불가** (네트워크 미접속) |
| Blog ON/OFF 재시작 필요 | **동일** (`@st.cache_resource`) |

---

## STEP 12: Regression

| 구분 | 결과 |
|------|------|
| 전체 테스트 | **978 passed, 4 skipped** ✅ |
| 기존 baseline 대비 | **변경 없음** |
| FAIL | **0** |

---

## STEP 13: 최종 판정

| 항목 | 결과 |
|------|------|
| Calculator Scheduler 진입점 | **PASS** ✅ |
| run_calculator_once 연결 | **PASS** ✅ |
| Blog Scheduler 격리 | **PASS** ✅ |
| Lock 격리 | **PASS** ✅ |
| Schedule 격리 | **PASS** ✅ |
| History 격리 | **PASS** ✅ |
| Dashboard 제어 | **PASS** ✅ |
| 발행 건수 제어 | **PASS** ✅ |
| 발행 시간 제어 | **PASS** ✅ |
| 실행 상태 표시 | **PASS** ✅ |
| 마지막/다음 실행 | **PASS** ✅ |
| 오류 상태 | **PASS** ✅ |
| Calculator 목적지 | **⚠️ WARN** |
| DB 격리 | **PASS** ✅ |
| 법령/요율 Detect Only | **PASS** ✅ |
| 자동 실행 위험 | **PASS** ✅ |
| Dry-run | **PASS** ✅ |
| Regression | **PASS** ✅ |

---

## FINAL VERDICT

**PASS WITH ISSUES** ⚠️

### 핵심 발견

**Calculator Line은 "웹앱 전용 라인"이 아닙니다.**

현재 `calculator_pipeline.py`는 다음을 수행합니다:
1. SEO 글 생성
2. FAQ 생성
3. 계산기 위젯 생성
4. **이미지 생성 (Image Pipeline)**
5. **WordPress 발행 (Publisher)**
6. **DB 저장 (articles 테이블)**

이것은 Blog Line과 동일한 WordPress 발행 경로를 사용합니다.

### 수정이 필요한 사항

| 문제 | 파일 | 우선순위 |
|------|------|----------|
| Calculator Line이 WP/Image를 직접 호출 | `modules/calculator_pipeline.py` | **P1** |

### 수정하지 않은 사항

| 항목 | 이유 |
|------|------|
| Calculator Pipeline 코드 | READ-ONLY 진단 |
| DB 데이터 | READ-ONLY 진단 |
| config 설정 | READ-ONLY 진단 |
| WP Draft 정리 | READ-ONLY 진단 |

### 다음 단계

1. **Calculator Line의 WordPress/Image 호출 경로 확인** — 현재 설계 의도와 일치하는지 검증
2. **Calculator Line이 "웹앱 전용"인지 "WP 발행 포함"인지 확정**
3. **필요시 calculator_pipeline.py에서 publisher/image_generator 호출 분리**

---

**최종 판정: PASS WITH ISSUES** ⚠️
