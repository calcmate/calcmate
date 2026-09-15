@echo off
REM ============================================================
REM  run_wp_blog_deploy_live.bat — WP Publish -> index/sitemap 자동 배포
REM  LIVE 전용 런처(STEP202)
REM
REM  기존 run_wp_blog_deploy.bat(dry-run 전용)는 수정하지 않고 그대로 둔다 —
REM  이 파일은 완전히 별도의 신규 진입점이며, 동일한 modules.wp_blog_deploy
REM  worker를 --live 인자만 추가해 실행한다(다른 로직 없음 — git/WP 호출을
REM  이 배치파일 자체에서 직접 하지 않고 전부 기존 worker에 위임).
REM
REM  중복 실행 방지: data/schedule/wp_blog_deploy.lock(modules/wp_blog_deploy.py
REM  내부에서 관리, run_wp_blog_deploy.bat과 동일한 lock을 공유 — 두 BAT을
REM  동시에 실행해도 실제 deploy 작업은 이 lock으로 보호된다).
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist "data\logs" mkdir "data\logs"

:loop
echo [%date% %time%] wp-blog-deploy starting (LIVE) >> "data\logs\wp_blog_deploy_stdout.log"
".venv\Scripts\python.exe" -m modules.wp_blog_deploy --loop --live >> "data\logs\wp_blog_deploy_stdout.log" 2>&1
echo [%date% %time%] wp-blog-deploy exited (code %errorlevel%) - restarting in 30s >> "data\logs\wp_blog_deploy_stdout.log"
timeout /t 30 /nobreak >nul
goto loop
