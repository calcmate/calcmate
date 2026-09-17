# Blog Scheduler Dashboard WP Integration Report

**Final Verdict: READY FOR BLOG SCHEDULER ON** ✅

---

## 1. 작업 전 상태

| 항목 | 값 |
|------|-----|
| HEAD | `27afbe2` |
| Branch | `master` |
| DB hash | `33e10f342b7fd81da7f9806864e0eccb` |
| Calculator Scheduler | OFF |
| Blog Scheduler | 구현 완료 (기본 OFF) |
| run_scheduler.bat | `.disabled` |
| Windows Task Scheduler | 없음 |

---

## 2. 기존 스케줄 구조

```
[Calculator Line] (현재 OFF)
Dashboard
  → PUBLISH_SCHEDULE.enabled=false
  → 스레드 미시작

[Blog Line] (신규, 현재 OFF)
Dashboard
  → BLOG_SCHEDULE.enabled=false
  → 스레드 미시작

[Sync Line] (변경 없음)
run_sync.bat
  → run_sync.py
  → WP→Sheets 동기화
```

---

## 3. Dashboard 관리 방식

### 기존 Calculator Scheduler

```yaml
PUBLISH_SCHEDULE:
  enabled: false      ← OFF
  failure_mode: retry_in_slot
  weekday:
  - start: 06:00
    end: 06:30
  weekend:
  - start: 06:00
    end: 06:30
```

### 신규 Blog Scheduler

```yaml
BLOG_SCHEDULE:
  enabled: false      ← OFF (기본값)
  mode: draft         ← draft 또는 publish
  publish_slots:
  - start: "10:00"
    end: "10:30"
  weekday_only: false
```

### 차이점

| 항목 | Calculator | Blog |
|------|-----------|------|
| enabled | false | false |
| mode | calculator/rss | draft/publish |
| publish function | run_calculator_once | run_blog_once_wp |
| DB write | articles 테이블 | 없음 |
| WordPress | publisher.py | publisher.py (mode=publish) |
| Image | image_pipeline | 없음 |

---

## 4. Blog Line 연결 구조

```
[Blog Line - Dry-run mode (기본)]
run_blog_scheduler.py run
  → blog_scheduler_adapter.run_blog_once()
    → Golden 10 Contract
      → Blog Adapter
        → content.blog.writer
          → AI generation (또는 mock)
            → isolated output만 저장

[Blog Line - Publish mode]
run_blog_scheduler.py publish
  → blog_scheduler_adapter.run_blog_once_wp()
    → Golden 10 Contract
      → Blog Adapter
        → AI generation
          → 기존 publisher.py
            → WordPress REST API

[Dashboard Blog Scheduler]
dashboard.py
  → BLOG_SCHEDULE.enabled=true
    → _start_blog_scheduler_thread()
      → modules.scheduler.run_scheduler_loop()
        → resolve_blog_publish_fn(cfg)
          → BLOG_SCHEDULE.mode=publish → run_blog_once_wp
          → BLOG_SCHEDULE.mode=draft  → run_blog_once
```

---

## 5. 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `config/config.yaml` | `BLOG_SCHEDULE` 섹션 추가 |
| `main.py` | `resolve_blog_publish_fn()` 추가 |
| `dashboard.py` | `_start_blog_scheduler_thread()` 추가 |
| `modules/blog_scheduler_adapter.py` | `run_blog_once_wp()`, `_check_wp_duplicate()` 추가 |
| `scripts/run_blog_scheduler.py` | `publish` 서브커맨드 추가 |

---

## 6. DB 변경 여부

| 측정 시점 | DB hash |
|-----------|---------|
| 작업 전 | `33e10f342b7fd81da7f9806864e0eccb` |
| Dry-run 후 | `33e10f342b7fd81da7f9806864e0eccb` |
| WP 테스트 후 | `33e10f342b7fd81da7f9806864e0eccb` |
| Regression 후 | `33e10f342b7fd81da7f9806864e0eccb` |

**DB UNCHANGED** ✅

---

## 7. Golden 10 검증

- Dry-run: **10/10 PASS**
- Structure: **10/10 PASS**
- Golden hash: **10/10 UNCHANGED**

---

## 8. Dry-run 결과

```
[Blog Scheduler] Full Verification
  Dry-run:      10/10 produced
  Structure:    10/10 PASS
  DB hash:      UNCHANGED
  Golden hash:  UNCHANGED
  DB write:     0
  WP call:      0
  Img call:     0
  FINAL: PASS
```

---

## 9. WordPress 테스트 결과

WordPress 자격증명 미설정 상태:

- `is_wordpress_ready()`: False
- `run_blog_once_wp()` → fallback to `run_blog_once()` (isolated output)
- DB hash: UNCHANGED
- WP call: 0

**WordPress 미연결 시 안전한 fallback** ✅

---

## 10. Calculator Scheduler 보호 결과

| 확인 항목 | 결과 |
|-----------|------|
| PUBLISH_SCHEDULE.enabled | false |
| Calculator 스레드 | 미시작 |
| run_scheduler.bat | .disabled |
| Calculator pipeline 호출 | Blog Line에서 미호출 |
| calculators.article_content | 변경 없음 |

**Calculator Scheduler 보호** ✅

---

## 11. run_sync 보호 결과

| 확인 항목 | 결과 |
|-----------|------|
| run_sync.bat | 변경 없음 |
| run_sync.py | 변경 없음 |
| content_sync | 별도 스레드, 독립 동작 |
| WP→Sheets 동기화 | 영향 없음 |

**run_sync 보호** ✅

---

## 12. Regression 결과

```
945 passed, 4 skipped in 103.31s
```

기존 baseline과 완전 동일.

**Regression PASS** ✅

---

## 13. 최종 운영 방법

### 현재 상태: 모두 OFF

```
Calculator Scheduler: OFF
Blog Scheduler: OFF
run_sync: 정상 동작
```

### Blog Scheduler ON 방법

**방법 1: config 변경**

```yaml
BLOG_SCHEDULE:
  enabled: true
  mode: draft      # 또는 publish
```

Dashboard 재시작 시 자동으로 blog-scheduler-loop 스레드 시작.

**방법 2: CLI 실행**

```bash
# Dry-run (isolated output만)
python scripts/run_blog_scheduler.py run

# WordPress 발행 테스트 (1건)
python scripts/run_blog_scheduler.py publish

# 전체 검증
python scripts/run_blog_scheduler.py full
```

### WordPress 발행 활성화

1. `config/wordpress.yaml`에 자격증명 설정
2. `BLOG_SCHEDULE.mode: publish`로 변경
3. Dashboard 재시작

---

## 14. 남은 위험/주의사항

| 위험 | 상태 | 설명 |
|------|------|------|
| WordPress 자격증명 미설정 | 알려져 있음 | `config/wordpress.yaml` 설정 필요 |
| WP 중복 발행 | 방지 구현됨 | `_check_wp_duplicate()`로 slug 검색 |
| Calculator Line 잠재 충돌 | 없음 | 완전 분리 |
| AI 품질 변동 | 알려져 있음 | 매 생성 시 내용 변동 가능 |
| BLOG_SCHEDULE.enabled=true 시 자동 실행 | 의도됨 | Dashboard 시작 시 스레드 자동 시작 |

### 추가 권장사항

1. **WordPress 카테고리 설정** — Blog 콘텐츠용 카테고리 생성
2. **WP 자격증명 테스트** — 실제 발행 전 WP 연결 확인
3. **운영 모드 정의** — draft→publish 점진적 전환
4. **발행 로그 모니터링** — 첫 1주간 결과 모니터링
