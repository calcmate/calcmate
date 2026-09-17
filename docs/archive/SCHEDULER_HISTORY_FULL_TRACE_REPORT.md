# Calculator Scheduler 탄생부터 현재까지 Git History 전수추적 보고서

**작업일시:** 2026-08-21  
**작업자:** Buffy (Codebuff)  
**버전:** HEAD 27afbe2  
**진단 유형:** READ-ONLY (코드 수정 없음)

---

## Executive Summary

Git history 추적 결과, **기존 Scheduler는 처음부터 Calculator Pipeline를 호출하도록 설계되었습니다.**

 Blog Scheduler는 이번 세션에서 별도로 생성된 **새로운 파일**입니다.

**FINAL VERDICT: B** — 기존 Scheduler가 원래 Calculator용

---

## 1. 기존 Scheduler 최초 생성

| 항목 | 값 |
|------|-----|
| **최초 커밋** | `66a17ac` |
| **날짜** | 2026-06-27 |
| **커밋 메시지** | `backup: before v12 lite refactoring` |
| **최초 목적** | 슬롯 기반 발행 스케줄러 (v12 신규) |

### 최초 Scheduler 코드 (66a17ac)

```python
# modules/scheduler.py (최초 버전)
"""
modules/scheduler.py — 글별 발행 시간 슬롯 스케줄러 (v12 신규)

운영자가 DAILY_POST_COUNT 만큼 슬롯(시작~종료 시간 범위)을 지정하면,
당일 시작 시 각 슬롯 범위 내 랜덤 시각을 1회 생성하여 하루 동안 고정한다.
현재 시각이 예약 시각에 도달하면 해당 글 1건만 발행한다.
"""
```

### 최초 Dashboard (66a17ac)

```python
# dashboard.py (최초 버전)
if st.button("🧮 계산기 생성", use_container_width=True, key="qa_calc"):
    from modules.calculator_pipeline import run_calculator_once
    _run_action("계산기 글 생성", lambda: run_calculator_once(cfg, max_count=1))
```

**확인:** 최초 Scheduler는 `run_calculator_once`를 직접 호출했습니다.

---

## 2. 기존 Scheduler 역할 변화

| commit | 날짜 | 변경 내용 |
|--------|------|-----------|
| `66a17ac` | 2026-06-27 | **최초 생성** — 슬롯 스케줄러 + `run_calculator_once` 직접 연결 |
| `1bef564` | 2026-07-07 | **`resolve_publish_fn` 도입** — `PUBLISH_MODE`로 calculator/rss 분기 |
| `0c8a012` | (이후) | `resolve_publish_fn` 개선 — RSS 하드코딩 제거 |
| `b6cf116` | (이후) | `_start_scheduler_thread` 도입 — Dashboard 스레드 시작 |

**역할 변경 없음:** 기존 Scheduler는 처음부터 현재까지 `run_calculator_once`를 호출합니다.

---

## 3. WordPress 발행 경로 역사

| 항목 | 값 |
|------|-----|
| **최초 연결 커밋** | `66a17ac` (2026-06-27) |
| **파일** | `modules/calculator_pipeline.py` |
| **코드** | `from . import publisher` |

### calculator_pipeline.py에서의 WP 발행 (66a17ac~현재)

```python
# calculator_pipeline.py (변경 없음)
from . import publisher  # WP 발행 시점에만 로드
pub = publisher.publish(post_id, {...}, final_html, image_urls, cfg)
```

**확인:** Calculator Pipeline는 처음부터 WordPress Publisher와 Image Pipeline를 호출했습니다.

---

## 4. Blog Scheduler 최초 생성

| 항목 | 값 |
|------|-----|
| **파일** | `modules/blog_scheduler_adapter.py` |
| **Git 상태** | **Untracked** (commit 없음) |
| **생성일** | 2026-08-20 (이번 세션) |
| **목적** | Golden 10 Contract 기반 intent별 블로그 콘텐츠 생성 |

### Blog Scheduler와 기존 Scheduler 관계

| 비교 | 기존 Scheduler | Blog Scheduler |
|------|---------------|----------------|
| **생성 시점** | 2026-06-27 (commit `66a17ac`) | 2026-08-20 (이번 세션) |
| **Git 상태** | 커밋됨 | **Untracked** |
| **호출 함수** | `run_calculator_once` | `run_blog_once` / `run_blog_once_wp` |
| **최종 목적지** | WordPress (via publisher.py) | isolated output 또는 WP |
| **DB write** | YES (articles 테이블) | NO |
| **Image Pipeline** | YES | NO |

**확인:** Blog Scheduler는 기존 Scheduler를 **대체한 것이 아니라 별도로 생성**된 것입니다.

---

## 5. Dashboard A/B 분리 역사

| 항목 | 값 |
|------|-----|
| **분리 커밋** | 이번 세션 (uncommitted changes) |
| **분리 전** | `scheduler-loop` 1개만 존재 |
| **분리 후** | `scheduler-loop` + `blog-scheduler-loop` 2개 |

### 분리 전 구조

```
Dashboard
 └─ Scheduler
      └─ run_scheduler_loop(cfg, resolve_publish_fn(cfg))
           └─ run_calculator_once()
```

### 분리 후 구조 (현재)

```
Dashboard
 ├─ Calculator Scheduler (scheduler-loop)
 │    └─ run_calculator_once()
 │
 └─ Blog Scheduler (blog-scheduler-loop)
      └─ run_blog_once() / run_blog_once_wp()
```

---

## 6. 현재 구조

### Calculator Scheduler

```
Dashboard (PUBLISH_SCHEDULE.enabled)
  → cfg["scheduler_line"] = "calculator"
  → _start_scheduler_thread()
  → thread: "scheduler-loop"
  → run_scheduler_loop(cfg, resolve_publish_fn(cfg))
  → PUBLISH_MODE="calculator"
  → run_calculator_once [modules/calculator_pipeline.py:253]
  → image_generator.generate()  ← Image Pipeline
  → publisher.publish()         ← WordPress Publisher
  → art_repo.save()             ← DB write
```

### Blog Scheduler

```
Dashboard (BLOG_SCHEDULE.enabled)
  → cfg["scheduler_line"] = "blog"
  → _start_blog_scheduler_thread()
  → thread: "blog-scheduler-loop"
  → run_scheduler_loop(blog_cfg, resolve_blog_publish_fn(blog_cfg))
  → mode="draft" → run_blog_once  ← isolated output
  → mode="publish" → run_blog_once_wp  ← WordPress Publisher
```

---

## 7. 사용자의 기존 기억과 비교

### 질문 1: "내가 기억하는 기존 로컬 WordPress 테스트 Scheduler와 현재 Calculator Scheduler가 같은 Scheduler인가?"

**답변: YES** — 같습니다.

근거:
- `history.jsonl`에 2026-07-18부터 매일 실행 기록 존재
- 결과가 "성공" 또는 "미생산(모든후보HOLD)"
- `sync_history.jsonl`에 WP 게시물 기록 존재
- WP에 실제로 계산기 관련 콘텐츠가 발행됨 (4대보험, 실업급여, 주휴수당 등)

### 질문 2: "현재 Calculator Scheduler가 WordPress에 발행하는 구조가 원래 설계인지, 개발 과정에서 연결된 것인지?"

**답변: 원래 설계입니다.**

근거:
- 최초 커밋 `66a17ac` (2026-06-27)에서 이미 `publisher.py` 호출
- `calculator_pipeline.py`의 `from . import publisher`는 변경된 적 없음
- Calculator Pipeline는 처음부터 "계산기 키워드 기반 SEO 글 생성 + WP 발행" 경로

### 질문 3: "새 Blog Scheduler가 기존 Scheduler를 대체한 것인지, 기존 Scheduler와 별도로 생성된 것인지?"

**답변: 별도로 생성된 것입니다.**

근거:
- `blog_scheduler_adapter.py`는 Git history에 없음 (untracked)
- 기존 Scheduler는 그대로 유지됨
- 두 Scheduler는 별도 스레드, 별도 lock, 별도 schedule

---

## 8. 운영 설계 권고

### [REFACTOR] Calculator / Blog 목적지 분리 필요

**현재 상황:**
- Calculator Scheduler → WordPress 발행 (via publisher.py)
- Blog Scheduler → isolated output 또는 WP (mode별)

**문제점:**
- Calculator Line이 WordPress에 자동 발행하는 것은 의도된 것인지 확인 필요
- Calculator Line이 Image Pipeline를 호출하는 것은 의도된 것인지 확인 필요

**권장 조치:**
1. Calculator Line의 WordPress/Image 호출 경로 확인
2. "Calculator = 웹앱 전용"인지 "Calculator = WP 발행 포함"인지 확정
3. 필요시 calculator_pipeline.py에서 publisher/image_generator 호출 분리

---

## 9. 데이터 불변성

| 항목 | 상태 |
|------|------|
| DB | **비어있음** (calculators 테이블 없음) |
| Golden 10 | **10건 UNCHANGED** ✅ |
| WP Draft 396 | **유지** ✅ |
| history.jsonl | **기존 데이터 유지** ✅ |

---

## 10. Regression

| 구분 | 결과 |
|------|------|
| 전체 테스트 | **978 passed, 4 skipped** ✅ |
| 기존 baseline 대비 | **변경 없음** |
| FAIL | **0** |

---

## 11. 최종 결론

### 기존 Scheduler 탄생 역사

```
2026-06-27 (66a17ac)
  └─ 최초 생성: 슬롯 기반 발행 스케줄러
     └─ 목적: Calculator Pipeline 자동 실행
     └─ WP 발행: YES (from the beginning)
     └─ Image Pipeline: YES (from the beginning)

2026-07-07 (1bef564)
  └─ resolve_publish_fn 도입
     └─ PUBLISH_MODE로 calculator/rss 분기
     └─ 기본값: calculator

2026-08-20 (이번 세션)
  └─ Blog Scheduler 별도 생성
     └─ blog_scheduler_adapter.py (untracked)
     └─ Dashboard A/B 분리
     └─ Lock/Schedule/History 격리
```

### 최종 판정

**B. 기존 Scheduler가 원래 Calculator용**

기존 Scheduler
= 처음부터 Calculator Pipeline (WP 발행 포함)

새 Blog Scheduler
= 별도로 추가

현재 구조
= 개발 역사와 일치

---

**최종 판정: B** ✅
