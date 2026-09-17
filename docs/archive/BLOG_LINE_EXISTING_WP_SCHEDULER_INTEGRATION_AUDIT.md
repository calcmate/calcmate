# Blog Line ↔ 기존 WordPress 발행 스케줄 통합 감사 보고서

**Final Verdict: READY FOR INTEGRATION** ✅

---

## 1. Executive Summary

기존 로컬 WordPress 발행 스케줄과 새 Blog Line을 전수 조사한 결과, **두 라인은 완전히 분리**되어 있다.

- Blog Line은 DB/WordPress/Image에 **접근하지 않는다**
- 기존 스케줄은 Calculator Line을 사용하며 Blog Line과 **공유 자원이 없다**
- 충돌 가능성: **없음**
- 통합 권장: **Option B (독립 Blog 스케줄)**

---

## 2. 기존 스케줄 정체

### 기존 발행 스케줄의 정체: "Calculator Slot-Based Publishing"

| 항목 | 값 |
|------|-----|
| **무엇을 스케줄하는가** | 계산기 콘텐츠 발행 (1일 슬롯별 1건) |
| **언제 실행되는가** | 매일 설정된 시간 슬롯 (기본 06:00~19:00) |
| **entrypoint** | `dashboard.py` → `_start_scheduler_thread()` |
| **Python 시작점** | `modules/scheduler.py:run_scheduler_loop()` |
| **호출하는 함수** | `run_once_fn(cfg, max_count=1)` |
| **PUBLISH_MODE=calculator** | `modules/calculator_pipeline.py:run_calculator_once()` |
| **PUBLISH_MODE=rss** | `main.py:run_once()` (RSS 수집→발행) |
| **데이터 읽기** | `calculators` 테이블, `site_collectors`, RSS |
| **데이터 생성** | `articles` 테이블, WordPress Post |
| **DB 변경** | 예 (articles 테이블 INSERT) |
| **WordPress 호출** | 예 (`modules/publisher.py` → REST API) |
| **Image Pipeline** | 예 (칼럼 이미지 생성) |

### 두 가지 PUBLISH_MODE

```
PUBLISH_MODE=calculator (기본):
  scheduler → run_calculator_once() → calculator_pipeline → publisher → WordPress

PUBLISH_MODE=rss:
  scheduler → run_once() → RSS collector → writer → publisher → WordPress
```

---

## 3. 기존 로컬 WordPress 발행 흐름

```
Dashboard (Streamlit)
  │
  ├─ PUBLISH_SCHEDULE.enabled=true && OPERATION_MODE=scheduled ?
  │   YES → _start_scheduler_thread()
  │          │
  │          └─ modules/scheduler.py:run_scheduler_loop()
  │               │
  │               ├─ 매 30초 poll
  │               ├─ ensure_today_schedule() → 슬롯 생성
  │               ├─ get_due_posts() → 시간 도래 글 확인
  │               └─ execute_due_post()
  │                    │
  │                    └─ run_once_fn(cfg, max_count=1)
  │                         │
  │                         ├─ PUBLISH_MODE=calculator
  │                         │   → calculator_pipeline.run_calculator_once()
  │                         │     → content/calculator/writer.py (AI 생성)
  │                         │     → modules/publisher.py (WordPress REST API)
  │                         │     → articles 테이블 (DB 저장)
  │                         │
  │                         └─ PUBLISH_MODE=rss
  │                             → main.py.run_once()
  │                               → RSS collector
  │                               → writer.write_draft()
  │                               → editor.edit()
  │                               → modules/publisher.py (WordPress REST API)
  │                               → articles 테이블 (DB 저장)
  │
  ├─ CONTENT_SYNC.run_at=03:00
  │   └─ _start_content_sync_thread()
  │        └─ modules/content_sync.py → WP→Sheets 동기화 (역방향)
  │
  └─ run_scheduler.bat (DISABLED)
      └─ main.py --scheduler → run_scheduler_loop() (독립 프로세스)
```

### WordPress 발행 상세 (`modules/publisher.py`)

```
publisher.publish(post_id, seo_data, html_body, image_urls, cfg)
  │
  ├─ _wordpress_api(seo, html, wp_imgs, cfg)
  │   → POST https://salarymate.test/wp-json/wp/v2/posts
  │   → WordPress REST API (Basic Auth)
  │
  ├─ upload_media(fpath, cfg)
  │   → POST https://salarymate.test/wp-json/wp/v2/media
  │   → 미디어 업로드
  │
  └─ return {status, wp_post_id, wp_permalink, wordpress_url, ...}
```

### WordPress 설정 (`config/wordpress.yaml`)

```yaml
wordpress:
  url: "https://salarymate.test"
  username: ""          ← 비어있음
  app_password: ""      ← 비어있음
  default_status:
    PASS: draft
    WARNING: draft
    REWRITE: blocked
    HOLD: blocked
```

**현재 WordPress 자격증명이 비어있어 실제 발행은 불가능한 상태.**

---

## 4. Dashboard ON/OFF 동작

| 조건 | 동작 |
|------|------|
| `PUBLISH_SCHEDULE.enabled=true` + `OPERATION_MODE=scheduled` | 스레드 시작 |
| `PUBLISH_SCHEDULE.enabled=false` | 스레드 **미시작** |
| `run_scheduler.bat` (독립 프로세스) | **.disabled** (이름 변경) |

**현재 상태: `PUBLISH_SCHEDULE.enabled: false` → 스케줄러 스레드 미시작**

Dashboard OFF가 제어하는 것:
- Dashboard 내부 `scheduler-loop` 스레드만 ON/OFF
- `run_scheduler.bat` 독립 프로세스에는 **영향 없음** (이전 발견)
- `run_sync.bat` (WP→Sheets 동기화)에도 **영향 없음**

---

## 5. 새 Blog Line 구조

```
scripts/run_blog_scheduler.py (CLI)
  │
  ├─ full    → 전체 검증 (dry-run + validate + protection)
  ├─ run     → Golden 10 전체 dry-run
  ├─ validate → 기존 콘텐츠 구조 검증
  └─ single  → 단일 dry-run (--slug X --intent Y)
       │
       └─ modules/blog_scheduler_adapter.py
            │
            ├─ Golden 10 Contract (content/blog/__init__.py)
            │   → 10건 slug/intent/title
            │
            ├─ BlogScheduleRequest.validate()
            │   → intent 검증
            │   → Golden 10 Contract 일치 확인
            │
            ├─ content/blog/writer.py:generate_blog_article()
            │   │
            │   ├─ OPENAI_API_KEY 있음 → content.calculator.writer.generate_article()
            │   │   → content/calculator/prompt.py (intent별 프롬프트)
            │   │   → AI provider (OpenAI/OpenRouter)
            │   │   → HTML body 반환
            │   │
            │   └─ OPENAI_API_KEY 없음 → intent별 mock
            │
            └─ Isolated output 저장
                → data/reproduction/scheduler_blog/
                → HTML 파일 + metadata JSON
```

### Blog Line 보장

| 항목 | 보장 |
|------|------|
| DB write | **0건** |
| WordPress 호출 | **0건** |
| Image Pipeline | **0건** |
| calculators.article_content | **변경 없음** |
| articles 테이블 | **변경 없음** |

---

## 6. Blog → WordPress 연결 상태

| 단계 | 상태 |
|------|------|
| Blog generation | `content/blog/writer.py` |
| → DB | **NOT CONNECTED** |
| → article storage | **NOT CONNECTED** |
| → WordPress publisher | **NOT CONNECTED** |
| → WordPress REST API | **NOT CONNECTED** |

**Blog Line은 현재 WordPress에 연결되어 있지 않다.**

`run_blog_scheduler.py`는 다음만 수행:
1. AI 콘텐츠 생성
2. Isolated 파일 저장
3. 구조 검증

실제 WordPress 발행을 위해서는 별도 연결이 필요하다.

---

## 7. Golden 10 보호 상태

| 측정 시점 | DB hash | Golden 10 hash |
|-----------|---------|----------------|
| 작업 전 | `33e10f342b7fd81da7f9806864e0eccb` | 10/10 unchanged |
| Dry-run 후 | `33e10f342b7fd81da7f9806864e0eccb` | 10/10 unchanged |
| AI 1건 후 | `33e10f342b7fd81da7f9806864e0eccb` | 10/10 unchanged |

**Golden 10 UNCHANGED** ✅

---

## 8. DB 보호 상태

- `calculators` 테이블: **변경 없음**
- `articles` 테이블: **변경 없음**
- `app_templates` 테이블: **변경 없음**
- DB hash: **동일** (`33e10f342b7fd81da7f9806864e0eccb`)

**DB UNCHANGED** ✅

---

## 9. 충돌 검사

| 충돌 항목 | 기존 스케줄 | Blog Line | 충돌? |
|-----------|-------------|-----------|-------|
| A. 동일 DB table | articles (INSERT) | 없음 | **없음** |
| B. 동일 article_content | calculators.article_content | 없음 | **없음** |
| C. 동일 output directory | data/workspace/_site/ | data/reproduction/ | **없음** |
| D. 동일 WordPress post | WP REST API POST | 없음 | **없음** |
| E. 동일 slug | calculators slug 사용 | Golden 10 slug 사용 | **같은 slug but 다른 경로** |
| F. 동일 scheduler lock | data/schedule/*.lock | 없음 | **없음** |
| G. 동일 queue | data/schedule/*.json | 없음 | **없음** |
| H. 동일 publisher | modules/publisher.py | 미사용 | **없음** |
| I. 동일 image pipeline | image_pipeline/ | 미사용 | **없음** |

**충돌: 없음** ✅

동일 slug를 사용하지만:
- 기존 스케줄: `calculators.article_content`에 저장 + WordPress 발행
- Blog Line: `data/reproduction/scheduler_blog/`에 격리 저장

**별도 경로를 사용하므로 충돌 없음.**

---

## 10. CP949 오류 발생 경로

```
run_scheduler.bat (이전)
  → main.py --scheduler
    → modules/scheduler.py:run_scheduler_loop()
      → execute_due_post()
        → run_calculator_once()
          → calculator_pipeline.py
            → image_generator.py:print("🚀 ...")  ← PRIMARY ERROR
              → CP949 UnicodeEncodeError
                → telegram_ops.notify("❌ 계산기 글 오류: ...")  ← SECONDARY ERROR
                  → ❌도 CP949 UnicodeEncodeError
```

**Blog Line과 무관.** 기존 Calculator Line에서만 발생.

현재 수정 완료:
- `image_generator.py`: `print("🚀❌")` → `LOG.info()`
- `calculator_pipeline.py`: `❌` → `[ERROR]`
- `main.py`: `--scheduler` 미지정 시 return

---

## 11. 실제 AI 1건 검증

| 항목 | 결과 |
|------|------|
| 콘텐츠 | severance-pay / eligibility |
| AI 생성 | SUCCESS (17.0초, 1418 chars) |
| H2 | 지급 대상 / 근로시간 조건 / 제외 대상 / 계산 방법 / FAQ |
| DB hash | UNCHANGED |
| Golden 10 hash | UNCHANGED |
| WordPress | 0건 호출 |

**실제 AI 1건 PASS** ✅

---

## 12. WordPress dry-run 결과

Blog Line에서 WordPress를 호출하지 않으므로 WordPress dry-run은 해당 없음.

**WordPress 호출: 0건** ✅

만약 WordPress 발행이 필요하면:
1. `blog_scheduler_adapter.py`에 publisher 연결 추가
2. `config/wordpress.yaml`에 자격증명 설정
3. Blog 콘텐츠의 WordPress category/slug 설정

---

## 13. Regression 결과

```
945 passed, 4 skipped in 108.46s
```

기존 baseline과 완전 동일.

**Regression PASS** ✅

---

## 14. 추천 운영 구조

### Option B: 독립 Blog 스케줄 (권장)

```
기존 Calculator 스케줄 (OFF 유지):
  dashboard → scheduler → calculator_pipeline → WP
  (현재: OFF, run_scheduler.bat: disabled)

새 Blog 스케줄 (별도 진입점):
  Windows Task Scheduler
    → python scripts/run_blog_scheduler.py run
      → Golden 10 Contract
        → Blog Adapter
          → AI generation
            → isolated output
              → (추후) WordPress publisher 연결

WP→Sheets 동기화 (별도):
  run_sync.bat → run_sync.py
  (매일 03:00, Content Sync)
```

### Option B의 장점

1. **기존 Calculator 스케줄에 영향 없음** — 완전 독립
2. **Blog Line 전용 스케줄** — 의도된 동작만 실행
3. **점진적 연결** — WordPress 발행은 별도 단계로 연결
4. **안전성** — 기존 라인 오염 없음

### Option B의 단점

1. 별도 스케줄 관리 필요
2. 두 스케줄 간 시간 충돌 방지 필요 (동시 발행 시 WP rate limit)

---

## 15. 최종 판정

| 조건 | 결과 |
|------|------|
| 기존 스케줄 정체 확인 | ✅ Calculator Slot-Based Publishing |
| 기존 스케줄 entrypoint 확인 | ✅ dashboard.py → scheduler thread |
| Dashboard ON/OFF 실제 영향 확인 | ✅ 스레드만 제어, 독립 프로세스 무관 |
| 기존 WP 발행 경로 확인 | ✅ publisher.py → WP REST API |
| Blog Line entrypoint 확인 | ✅ run_blog_scheduler.py → blog_adapter |
| Blog Line → WP 연결 여부 | ✅ NOT CONNECTED (격리) |
| Golden 10 보호 확인 | ✅ UNCHANGED |
| DB overwrite 위험 | ✅ Blog Line DB write = 0 |
| WP duplicate 위험 | ✅ Blog Line WP 호출 = 0 |
| Image duplicate 위험 | ✅ Blog Line Image 호출 = 0 |
| 실제 AI 1건 검증 | ✅ PASS |
| WP 실제 호출 0 | ✅ |
| DB 변경 0 | ✅ |
| Golden 10 변경 0 | ✅ |
| Regression PASS | ✅ 945 passed, 4 skipped |

### **FINAL VERDICT: READY FOR INTEGRATION** ✅

---

## 16. 다음 단계

1. **Windows Task Scheduler에 Blog Line 등록** — 매일 1회 `run_blog_scheduler.py run` 실행
2. **WordPress 연결** — `blog_scheduler_adapter.py`에 publisher 추가
3. **WordPress 자격증명 설정** — `config/wordpress.yaml`에 URL/username/app_password
4. **Blog WordPress category** — Blog 콘텐츠용 카테고리 생성
5. **운영 모드 정의** — Calculator Line OFF + Blog Line ON 상태에서의 동작 확인
