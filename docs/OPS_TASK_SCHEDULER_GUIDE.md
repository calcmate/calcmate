# 운영 가이드 — Content Sync / Scheduler 자동 실행 (FastAPI Worker)

> **중요:** Streamlit 대시보드(`dashboard.py`)와 Root 독립 launcher(`run_sync.py`, `run_sync.bat`)는 제거되었다.
> Content Sync 및 Scheduler의 자동 실행은 이제 **`\CalcMate-FastAPI` Task로 기동되는 FastAPI Worker**가 담당한다.
> Calculator 자동 Scheduler(`run_scheduler.bat`/`main.py --scheduler`)도 제거되었다(Calculator는 수동 생성).

---

## 현재 운영 구조

| 구성 | 상태 | 비고 |
|------|------|------|
| Task Scheduler `\CalcMate-FastAPI` | **Running** | FastAPI + Worker 단일 자동 owner |
| Task Scheduler `\블로그배포` | **Running** | `run_wp_blog_deploy_live.bat` (wp_blog_deploy 루프) |
| Task Scheduler `\블로그1회예약` | **REMOVED** | 삭제됨(2026-10-04, Action BAT 부재 legacy Task) |
| Streamlit Content Sync owner | **REMOVED** | `dashboard.py` 삭제됨 |
| Root launcher (`run_sync.py/bat`) | **REMOVED** | 삭제됨 |
| `scripts/run_sync.bat` | **REMOVED** | 삭제됨(삭제된 `run_sync.py`를 호출하던 one-shot launcher) |

---

## `\CalcMate-FastAPI` Task 구성 (실제 등록값)

| 항목 | 값 |
|------|----|
| 실행 | `cmd.exe /c` → `.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000` |
| 작업 폴더 | `cd /d "C:\Users\연수\Desktop\블로그자동_v12"` (명령 안에서 이동) |
| 환경변수 | `CALCMATE_FASTAPI_WORKER_MODE=1`, `CALCMATE_WP_TARGET=production` |
| Trigger | Logon (로그온 시 시작) |
| 실행 수준 | Highest |
| MultipleInstances | IgnoreNew (실행 중 재시작 요청은 무시됨) |
| ExecutionTimeLimit | PT0S (시간 제한 없음) |
| 실패 시 재시작 | RestartCount 3, RestartInterval PT1M |

FastAPI는 `127.0.0.1:8000`에만 바인딩한다. 외부 인터페이스(`0.0.0.0`)로 열지 않는다.

수동 실행(개발/점검용, 운영 Task와 동일한 바인딩):
```powershell
$env:CALCMATE_FASTAPI_WORKER_MODE="1"
$env:CALCMATE_WP_TARGET="production"
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
운영 Task가 실행 중일 때는 같은 포트로 수동 실행하지 않는다.

---

## FastAPI Worker 자동 실행 조건

FastAPI lifespan(`api/main.py`)에서 `WorkerManager`를 초기화하고, 각 worker를 설정에 따라 시작한다.

| Worker | 시작 조건 |
|--------|-----------|
| `content_sync` | `CONTENT_SYNC.enabled=true` **그리고** `CALCMATE_FASTAPI_WORKER_MODE=1` |
| `blog` | `BLOG_SCHEDULE.enabled=true` |
| `oneoff` | `BLOG_SCHEDULE.enabled=true` 또는 `AUTO_PUBLISHING.enabled=true` |
| `publishing_planner` | `AUTO_PUBLISHING.enabled=true` **그리고** `CALCMATE_FASTAPI_WORKER_MODE=1` |
| `wp_blog_sync` | `WP_BLOG_SYNC.enabled=true` **그리고** `CALCMATE_FASTAPI_WORKER_MODE=1` |
| `calc_webapp` | `CALC_WEBAPP_SCHEDULE.enabled=true` **그리고** `CALCMATE_FASTAPI_WORKER_MODE=1` |

Content Sync worker는 `content-sync-loop` 스레드에서 `run_sync_loop()`를 실행하며,
매일 `CONTENT_SYNC.run_at`(기본 03:00)에 1회 동기화한다.

---

## 상태 확인

### Worker 상태 API (인증 불필요, 조회 전용)
```bash
GET /api/scheduler/content-sync/status
```

응답 예시:
```json
{
  "success": true,
  "data": {
    "enabled": true,
    "running": true,
    "thread_alive": true,
    "pending_count": 0,
    "processing_count": 0,
    "failed_count": 0,
    "total_queued": 0
  }
}
```

### 수동 실행 API (**admin 인증 필요**)
```bash
POST /api/scheduler/content-sync/run-once
Authorization: Bearer <admin token>
Content-Type: application/json
{"mode": "recent"}
```
- `require_admin` 의존성으로 보호된다. 토큰 값은 문서에 기록하지 않는다.
- 다른 Content Sync 실행이 lock을 보유 중이면 `LOCK_CONFLICT`로 거부된다.

---

## Lock 보호

- Content Sync: `data/schedule/content_sync.lock`
- Blog Scheduler: `data/schedule/blog/scheduler.lock`
- Calculator WebApp Scheduler: `data/schedule/calc_webapp/scheduler.lock`
- O_CREAT|O_EXCL atomic acquisition, owner token(PID, process_start_time, UUID, timestamp)
- Stale recovery는 owner 종료/PID 재사용이 확인된 경우에만 수행(owner 확인 불가 시 lock 유지)
- Release는 자신이 획득한 token과 일치할 때만 수행

Content Sync worker와 수동 실행 API(`/content-sync/run-once`)는 같은 `content_sync.lock`을 사용하므로 동시에 실행되지 않는다.

---

## 장애 대응 / 롤백

FastAPI Worker에 문제가 있을 경우:

1. 상태 확인: `GET /api/health`, `GET /api/scheduler/content-sync/status`
2. FastAPI 재시작(`\CalcMate-FastAPI`는 IgnoreNew이므로 중지 후 시작):
   ```powershell
   Stop-ScheduledTask  -TaskName "CalcMate-FastAPI"
   Start-ScheduledTask -TaskName "CalcMate-FastAPI"
   ```
3. Content Sync 자동 실행만 멈추려면 `config.yaml`의 `CONTENT_SYNC.enabled`를 `false`로 바꾼 뒤 FastAPI를 재시작한다.

Streamlit 기반 실행 경로와 Root launcher는 제거되었으므로 롤백 대상이 아니다.

---

# Blog / Calculator WebApp Scheduler

현재 Blog Scheduler와 Calculator WebApp Scheduler는 위 표의 조건에 따라 **FastAPI Worker**(`blog`, `calc_webapp`)로 실행된다.
별도 Windows 작업 스케줄러 등록은 사용하지 않는다.

## 과거 구조 (migration 완료, 현재 운영에서는 사용하지 않음)

- 과거에는 `dashboard.py`(Streamlit) 모듈 최상위의 `_start_blog_scheduler_thread()` /
  `_start_calc_webapp_scheduler_thread()`가 브라우저 세션 접속 시 스레드를 기동했다.
- 이를 대체하려던 독립 launcher(`run_blog_scheduler.bat`, `run_calc_webapp_scheduler.bat`)의
  작업 스케줄러 등록 절차가 이 문서에 있었으나, 해당 launcher는 등록되지 않았고 현재 저장소에 없다.
- Streamlit 제거로 위 경로는 모두 FastAPI Worker로 이관 완료되었다.
