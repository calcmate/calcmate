# SCHEDULER OFF 상태인데 실행되는 문제 — 전수진단 보고서

## Overall

**PASS** — 실행 원인과 오류 원인을 충분한 증거로 확인

---

## 1. 작업 전 Git 상태

- HEAD: `27afbe2`
- Branch: `master`
- 중단된 Blog Line 작업의 변경사항 보존 중 (content/blog/*, content/calculator/writer.py 등)
-本次 진단에서는 변경사항을 수정하지 않음

---

## 2. Scheduler OFF 상태 확인

### config.yaml 현재 값

```yaml
OPERATION_MODE: scheduled
PUBLISH_SCHEDULE:
  enabled: false          ← OFF
  failure_mode: retry_in_slot
  weekday:
    - {start: "06:00", end: "06:30"}
```

### Dashboard 조건 (dashboard.py:99-102)

```python
if cfg.get("OPERATION_MODE", "scheduled") == "scheduled" \
        and (cfg.get("PUBLISH_SCHEDULE") or {}).get("enabled", True):
    _start_scheduler_thread()
```

`PUBLISH_SCHEDULE.enabled = False`이므로 Dashboard 내장 스레드는 시작되지 않는다.

**Dashboard OFF 동작: 정상** ✅

---

## 3. 실제 실행 원인 — `run_scheduler.bat`

### 발견된 독립 실행 경로

```
run_scheduler.bat (프로젝트 루트)
    ↓
main.py --scheduler
    ↓
run_scheduler_loop(cfg, publish_fn)
```

### run_scheduler.bat 내용

```batch
:loop
echo [%date% %time%] publish-scheduler starting >> "data/logs/scheduler_stdout.log"
".venv\Scripts\python.exe" main.py --scheduler >> "data/logs/scheduler_stdout.log" 2>&1
echo [%date% %time%] publish-scheduler exited (code %errorlevel%) - restarting in 10s
timeout /t 10 /nobreak >nul
goto loop
```

### 핵심 문제

**`--scheduler` 플래그는 코드 어디에서도 체크되지 않는다.**

```bash
grep -n "args.scheduler" main.py
# 결과: 0건
```

`main.py`의 `main()` 함수는 모든 인자 분기 후 마지막에 무조건 `run_scheduler_loop()`를 호출한다:

```python
# main.py:501-504
from modules.scheduler import run_scheduler_loop
publish_fn = resolve_publish_fn(cfg)
run_scheduler_loop(cfg, publish_fn)
```

### 로그 증거

```
scheduler_stdout.log:
[2026-07-18  9:47:42] publish-scheduler starting
[2026-08-19  0:01:41] publish-scheduler starting   ← 매일 재시작
```

```
pipeline.log:
2026-08-20 00:00:06 오늘(2026-08-20) 발행 일정 생성: 1건
2026-08-20 06:03:21 ▶ 글1 발행 실행 (예약 06:03)
2026-08-20 06:04:35 [ERROR] 계산기 글 생성 오류: cp949
```

---

## 4. Dashboard OFF ≠ 프로세스 종료

| 상태 | Dashboard 스레드 | run_scheduler.bat 프로세스 |
|------|-----------------|--------------------------|
| Config: enabled=false | 시작 안 함 | **독립 실행 중** |
| Dashboard: 중지 버튼 | 스레드 중지 | **영향 없음** |
| Dashboard: 일시정지 | 스케줄 일시정지 | **영향 없음** |

Dashboard의 ON/OFF는 **Dashboard 내장 스레드**만 제어한다.

`run_scheduler.bat`는 **별도 프로세스**로 실행되며, Dashboard와 완전히 독립적이다.

---

## 5. PRIMARY ERROR

**위치:** `modules/image_generator.py:48`

```python
print(f"🚀 무료 이미지 생성 요청 중 ({kind})...")
```

**원인:** Windows CP949 콘솔에서 `🚀` (U+1F680) 이모지를 출력할 수 없음

```
UnicodeEncodeError: 'cp949' codec can't encode character '\U0001f680'
```

**발생 조건:**
- `run_scheduler.bat` → `main.py --scheduler` → `run_scheduler_loop` → `execute_due_post`
- → `run_calculator_once` → `image_generator.generate()` → `print(f"🚀 ...")`
- → Windows CP949 콘솔 → `UnicodeEncodeError`

** 이 오류로 인해 이미지 생성이 실패하고, 전체 글 생성이 실패한다.**

---

## 6. SECONDARY ERROR

**위치:** `modules/image_generator.py:67`

```python
print(f"❌ [image_generator] {kind} 무료 이미지 생성 실패: {e}")
```

**원인:** PRIMARY 오류의 `e`를 출력하려는데 `❌` (U+274C)도 CP949로 인코딩 불가

```
UnicodeEncodeError: 'cp949' codec can't encode character '\u274c'
```

그리고 `calculator_pipeline.py:630`:

```python
tops.notify(cfg, f"❌ 계산기 글 오류: {e}")
```

여기서도 `❌`가 CP949 오류를 발생시킨다.

**ERROR 메시지:**
```
❌ 계산기 글 오류: 'cp949' codec can't encode character '\u274c'
```

---

## 7. 전체 에러 Chain

```
[run_scheduler.bat] 독립 프로세스 (자동 재시작 루프)
    ↓
[main.py --scheduler] --scheduler 플래그 무시, 무조건 실행
    ↓
[run_scheduler_loop] 30초 poll
    ↓
[execute_due_post] 예약 도래 글 1건 실행
    ↓
[run_calculator_once] 계산기 파이프라인
    ↓
[image_generator._generate_free_image] print("🚀 ...")
    ↓
[UnicodeEncodeError: cp949] ← PRIMARY ERROR
    ↓
[except] print("❌ ...") → [UnicodeEncodeError: cp949] ← SECONDARY
    ↓
[calculator_pipeline] tops.notify("❌ 계산기 글 오류: ...")
    ↓
[telegram_ops.notify] 텔레그램 알림 발송
    ↓
[사용자에게] "❌ 계산기 글 오류: 'cp949' codec can't encode..."
```

---

## 8. Scheduler가 OFF인데 실행되는 정확한 이유

**이유: `run_scheduler.bat`가 Dashboard와 독립적으로 실행되고 있다.**

- `run_scheduler.bat`는 `main.py --scheduler`를 직접 호출
- `--scheduler` 플래그는 코드에서 체크되지 않음
- `main.py`는 마지막에 무조건 `run_scheduler_loop()`를 호출
- `run_scheduler.bat`에는 `goto loop`로 10초 후 자동 재시작 로직 존재
- Dashboard ON/OFF는 이 프로세스에 영향을 주지 않음

---

## 9. Blog Line 작업과의 관계

**관계 없음.**

- PRIMARY ERROR는 `image_generator.py`의 `print()`문에서 발생
- Blog Line 코드는 `content/blog/`에 있으며, `run_calculator_once()`를 호출하지 않음
- 현재 매일 발생하는 오류는 **기존 Calculator Line**에서 독립 발생
- Blog Line 변경사항이 기존 Scheduler 실행 경로에 영향을 주지 않음

---

## 10. 운영 데이터 보호 확인

| 대상 | 변경 여부 |
|------|----------|
| calculators.article_content |UNCHANGED ✅ |
| Golden 10 hash |UNCHANGED ✅ |
| DB hash |UNCHANGED ✅ |
| SSOT |UNCHANGED ✅ |

---

## 11. 권장 수정 순서

### 즉시 수정 (오류 해결)

1. **`modules/image_generator.py`에서 emoji print 제거/수정**
   - `print(f"🚀 ...")` → `LOG.info(...)` 또는 ASCII 문자 사용
   - `print(f"❌ ...")` → `LOG.error(...)` 또는 ASCII 문자 사용

2. **`calculator_pipeline.py:630`에서 emoji 제거**
   - `tops.notify(cfg, f"❌ 계산기 글 오류: {e}")` → `tops.notify(cfg, f"[오류] 계산기 글 오류: {e}")`

### 근본 해결 (독립 실행 차단)

3. **`run_scheduler.bat` 비활성화 또는 삭제**
   - 또는 `main.py`에서 `--scheduler` 플래그를 실제로 체크하도록 수정

4. **config.yaml에서 `OPERATION_MODE: manual`로 변경**
   - Dashboard에서만 스케줄러를 제어하도록 강제

---

## 12. 최종 판정

**PASS**

실행 원인: `run_scheduler.bat` 독립 프로세스 (Dashboard OFF와 무관)
PRIMARY ERROR: `image_generator.py`의 `print("🚀 ...")` CP949 인코딩 오류
SECONDARY ERROR: `print("❌ ...")` CP949 인코딩 오류
Blog Line 관계: 없음
운영 데이터: 변경 없음
