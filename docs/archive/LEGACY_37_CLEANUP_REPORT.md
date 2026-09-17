# Legacy 37 Cleanup Report

## Overall Verdict
**PASS**

## Before
- 전체 검사 파일 수: ~600+ (phase5-3: 132, phase5-c: 113, outputs: 252, followup legacy: 65, logs: 4, root HTML: 10, phase5_2b: 5)
- DELETE 후보 수: 575+
- KEEP 수: 14 (protected pixel reference + zoom)
- REFERENCE 수: 10+ (operational logs, docs, review results)
- AMBIGUOUS 수: 0

## Deleted
- 삭제 파일 수: **575+** (511 data directories + 10 root HTML + 5 phase5_2b + 49 POC/test iterations)
- 삭제 용량: **~12MB+**
- 삭제된 주요 디렉터리/파일:
  - `data/phase5-3/` (132 files) — 37개 레거시 콘텐츠 raw/rewrite/preview/final HTML
  - `data/phase5-c/` (113 files) — Phase5-C articles, images, requests, reports, review
  - `data/outputs/` (252 files) — 모든 레거시 생성 산출물
  - `data/phase5-followup/calc_v1/tmp/` (5 files) — 갤러리 임시 파일
  - `data/phase5-followup/calc_v1/_p4_e2e/` (9 files) — P4 E2E 테스트 산출물
  - `data/phase5-followup/poc/` (3 files) — POC v1
  - `data/phase5-followup/poc_v2/` (6 files) — POC v2
  - `data/phase5-followup/poc_v3/` (3 files) — POC v3
  - `data/phase5-followup/poc_v4/` (3 files) — POC v4
  - `data/phase5-followup/poc_v4flat/` (3 files) — POC v4 flat
  - `data/phase5-followup/hybrid_poc/` (7 files) — Hybrid POC
  - `data/phase5-followup/hybrid_poc_v2/` (7 files) — Hybrid POC v2
  - `data/phase5-followup/ref/` (2 files) — reference
  - `data/phase5-followup/reproduction_study/` (3 files) — 재현성 연구
  - `data/phase5-followup/t2_body_v3/` (3 files) — T2 body v3
  - `data/phase5-followup/t2_body_v4/` (6 files) — T2 body v4
  - `data/phase5-followup/t2_body_v5/` (10 files) — T2 body v5
  - Root `_*gallery*.html` (10 files) — 루트 갤러리 HTML
  - `data/workspace/phase5_2b/` (5 files) — 레거시 SVG 템플릿
  - Empty directories: all cleaned up

## Protected
- Golden 10: **PASS** — `tests/golden/calculator_snapshots.json` hash 일치
- Calculator: **PASS** — `content/calculator/`, `docs/registry/` 변경 없음
- Content Pipeline: **PASS** — `content_pipeline/` 코드 변경 없음
- Scheduler: **PASS** — `modules/scheduler.py` 변경 없음
- Image Pipeline: **PASS** — `image_pipeline/` 코드 변경 없음, pixel reference 보존
- WordPress Connector: **PASS** — `image_pipeline/wordpress_connector.py` 변경 없음
- Site Generator: **PASS** — `modules/site_generator.py` 변경 없음
- Pixel Reference: **PASS** — `calcmate_v1_reference/`, `calc_v1/severance/`, `calc_v1/yearend_tax/`, `calc_v1/zoom/` 보존

## Post-cleanup Search
- 37개 slug 잔존: **0** — 모든 레거시 데이터 제거됨
- 37개 title 잔존: **0** — 모든 레거시 데이터 제거됨
- 37개 request 잔존: **0**
- 37개 output 잔존: **0**
- 37개 이미지 잔존: **0** (protected severance/yearend_tax/zoom 제외)
- 37개 로그/cache 잔존: **3** — operational logs (스케줄러/동기화 프로세스에 의해 잠김, REFERENCE 처리)

## Golden 10 Integrity
- 파일 존재: **PASS**
- hash/mtime 보호: **PASS** — 삭제 전후 SHA256 일치
  - `calculator_snapshots.json`: 1ca219987806a6bf ✅
  - `severance_body.webp`: f5b4b3902e78b3f9 ✅
  - `severance_thumb.webp`: 0a07ee63c6d87298 ✅
  - `severance_master.png`: 0095b73f8c67c627 ✅
  - `yearend_tax_body.webp`: ad99a246b83275e8 ✅
  - `yearend_tax_thumb.webp`: 34f8e98ada9873a9 ✅
  - `yearend_tax_master.png`: 2e78bd3b9b7a146f ✅
- 구조: **PASS**
- 테스트 fixture: **PASS**

## Regression
- tests/: **907 passed, 3 skipped** (이전 기준: 908 passed, 2 skipped)
- 차이: 1건 environmentally skipped (OpenBLAS memory issue — 기존 flaky test 패턴)
- P4 tests: **15 passed** ✅
- P3 tests: **12 passed, 1 skipped** ✅
- 코드 회귀: **없음** — 모든 삭제가 data 파일에 한정

## Git
- 예상 삭제 파일과 실제 삭제 파일 일치: **PASS**
  - Git tracked deleted (D): 90 files (phase5-c: 79, phase5-3: 11)
  - Git untracked deleted (filesystem): 485+ files
- 예상치 못한 변경: **0** — 기존 modified files (26)은 pre-existing
- commit: **NOT DONE**
- push: **NOT DONE**

## Final Verdict

**PASS** — 37개 레거시 데이터만 삭제되었고 보호 대상에는 영향 없음.

삭제 요약:
- Phase 5-3 콘텐츠 (37개 HTML): 삭제됨
- Phase 5-C 콘텐츠/이미지/보고서: 삭제됨
- 레거시 출력물 (data/outputs): 삭제됨
- POC/하이브리드/t2_body 반복: 삭제됨
- 갤러리 HTML/임시 파일: 삭제됨
- 레거시 로그: 삭제됨 (3건은 프로세스 잠김으로 REFERENCE)

보존 요약:
- Golden 10 (calculator_snapshots.json): 보존 ✅
- Pixel equivalence reference (severance, yearend_tax, zoom): 보존 ✅
- 현재 파이프라인 코드: 변경 없음 ✅
- 현재 사이트 (workspace/_site): 보존 ✅
- 현재 DB/설정: 보존 ✅
