@echo off
REM ============================================================
REM  run_wp_blog_sync.bat — WP Publish -> blog_articles 자동 등록 런처(STEP186)
REM  (대시보드 실행 여부와 무관하게 독립 프로세스로 구동)
REM
REM  기존 run_scheduler.bat(발행 슬롯)/run_sync.bat(WP<->Sheets)은 수정하지
REM  않는다 — 이 배치파일은 완전히 별도의 진입점이며, lock 파일도
REM  data/schedule/wp_blog_sync.lock 로 분리되어 있어 서로 겹치지 않는다.
REM
REM  ※ run_sync.bat과 동일한 이유로, Windows Task Scheduler에 등록할 때는
REM    "시간(HH:MM)" 트리거가 아니라 "로그온 시 상시 실행" 트리거로 걸어야
REM    한다 — 실제 폴링 주기는 modules/wp_blog_sync.py의 run_wp_blog_sync_loop
REM    내부(poll_seconds)에서 처리한다. 이 STEP에서는 Task Scheduler 등록
REM    자체는 하지 않는다(파일만 준비).
REM
REM  중복 실행 방지: data/schedule/wp_blog_sync.lock(파일 mtime 기반 stale-lock)
REM  으로 동시 실행을 막는다. 대시보드 내장 scheduler/content-sync 스레드와는
REM  별도 lock이라 서로 겹치지 않는다.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"

:loop
echo [%date% %time%] wp-blog-sync starting >> "data\logs\wp_blog_sync_stdout.log"
".venv\Scripts\python.exe" -c "from modules.config_loader import load_config; from modules.wp_blog_sync import run_wp_blog_sync_loop; run_wp_blog_sync_loop(load_config())" >> "data\logs\wp_blog_sync_stdout.log" 2>&1
echo [%date% %time%] wp-blog-sync exited (code %errorlevel%) - restarting in 30s >> "data\logs\wp_blog_sync_stdout.log"
timeout /t 30 /nobreak >nul
goto loop
