# CalcMate 저장소 정리 제안서 (분류 전용 — 삭제 미실행)

**작업일시:** 2026-08-22
**작업 유형:** 전수조사 + 분류(KEEP/ARCHIVE/MERGE/REMOVE-CANDIDATE). **실제 삭제/이동/병합 0건.**
**HEAD:** `27afbe2` (branch: `master`) — Calculator Scheduler 제거 작업(직전 세션) 완료 직후 상태.

---

## STEP 0 — 작업 전 상태 보존

```
git status --short | wc -l  → 241 (기존 다수 세션의 M/D/?? 누적, 이번 조사에서 무변경)
git log -5 --oneline        → 27afbe2 / 63af28b / 317e03e / 622f217 / 950dcb6
```

보호 확인(무변경): `modules/scheduler.py`, `modules/calculator_pipeline.py`, `modules/blog_scheduler_adapter.py`, `config/config.yaml`, `dashboard.py`, `main.py` — 전부 직전 Scheduler 제거 작업 이후 그대로. Golden 10(`content/blog/__init__.py` 내 `GOLDEN_10`, 10건) / DB(`data/blog_auto.db`, calculators 14건, 최신 updated_at 2026-08-19 그대로) 무변경 확인.

---

## Executive Summary

- **docs/**: 총 110건(tracked 70 + untracked 40). Untracked 40건 대부분이 **2026-08-17~08-22 사이 동일 주제를 반복 조사한 진단 보고서 체인**(이미지 파이프라인 PoC 8건, Golden10 11건, Blog/WP Scheduler 통합 7건, Calculator Scheduler 역사/제거 6건 등). REMOVE는 없고 대부분 **ARCHIVE 대상**(기록 가치는 있으나 현재 운영에 불필요).
- **scripts/**: 총 179건(tracked 147 + untracked 32). Untracked 32건은 전부 위 이미지 PoC/Golden10 실험의 **일회성 실행 스크립트**(`_` 접두, 재사용 안 됨). `scripts/run_blog_scheduler.py`만 예외(Blog Scheduler 정식 CLI, 보호).
- **tests/**: untracked 8건 중 4건(`test_blog_*`, `test_scheduler_line_isolation`, `test_golden10_protection`)은 **현재 운영에 필수**(보호), 4건(`test_image_pipeline_p1~p4`)은 **연결이 끊긴 고아 모듈**(`image_pipeline/`) 테스트 — REMOVE-CANDIDATE.
- **data/**: 대부분 KEEP/조사만. 단 `data/calcmate.db`(0바이트, 참조 0건)와 `data/{checkpoints,logs,outputs,dlq}`(브레이스 확장 실패로 생긴 빈 디렉토리)는 명백한 죽은 잔재.
- **가장 중요한 발견(STEP3)**: **tracked**(이미 커밋된) 공식 문서 `docs/OPERATIONS.md`와 `docs/OPS_TASK_SCHEDULER_GUIDE.md`가 방금 제거한 `run_scheduler.bat`/`main.py --scheduler`를 운영 절차로 명시하고 있어 **현재 구조와 정면으로 모순**됨 — 최우선 수정 후보.

---

## STEP 3 — 현재 구조와 모순되는 문서 (최우선)

| 파일 | 상태 | 모순 내용 |
|---|---|---|
| `docs/OPERATIONS.md` (tracked) | **수정 필요** | 4행 "스케줄러(`run_scheduler.bat`)로 운영한다", 32행 "스케줄러 상시 실행(run_scheduler.bat) → 슬롯 시각마다 계산기 파이프라인이 자동 발행" — **파일 삭제됨 + 자동발행 경로 자체가 제거됨**. 33행 "수동: main.py --calculator"도 실제로는 `--calculator-id`만 존재(이 문서는 Scheduler 제거 이전부터 이미 부정확했음). |
| `docs/OPS_TASK_SCHEDULER_GUIDE.md` (tracked) | **수정 필요** | 전체가 `main.py --scheduler` + `run_scheduler.bat`를 Windows 작업 스케줄러에 등록하는 절차 — **둘 다 삭제됨**. 단, 같은 문서의 `run_sync.bat`(Content Sync) 관련 절차는 여전히 유효하므로 **문서 전체 삭제가 아니라 Calculator Scheduler 등록 절차 섹션만 제거/수정** 필요. |
| `docs/DASHBOARD_SCHEDULER_CONTROL_FULL_AUDIT_REPORT.md` (untracked) | 모순(역사적 기록으로는 정확) | 지금은 삭제된 "오늘 발행 일정" 탭의 컨트롤 패널(버튼 6개 등)을 상세히 서술 — 작성 시점(08-21)엔 정확했으나 현재는 존재하지 않는 UI. ARCHIVE로 분류하면 "과거 기록"임이 명확해짐. |
| `docs/CALCMATE_FULL_ARCHITECTURE_FINAL_AUDIT_REPORT.md` (untracked) | 모순(역사적 기록으로는 정확) | 08-20 작성, Calculator Scheduler가 아직 존재하던 시점의 "전체 아키텍처" — 제목이 "최종"이라 최신 문서로 오인되기 쉬움. `CALCULATOR_SCHEDULER_REMOVAL_FINAL_REPORT.md`(08-22, 실제 최종 상태)로 대체됨 → ARCHIVE. |
| `docs/DASHBOARD_FINAL_OPERATION_AUDIT_REPORT.md` (untracked) | 모순 1건 | 325행 "Calculator Scheduler ON → 정상 동작 가능" — 지금은 ON 자체가 불가능(코드 제거됨). ARCHIVE. |
| `docs/CALCULATOR_SCHEDULER_FINAL_DIAGNOSTIC_REPORT.md` (untracked) | 모순 아님(초과 서술) | "Calculator Scheduler는 현재 OFF 상태"라고만 서술(제거 이전 시점) — REMOVE_FINAL 리포트로 대체. ARCHIVE. |

나머지 SCHEDULER_HISTORY/OFF_RUNTIME/SHUTDOWN 등은 "당시 시점 기준 정확한 진단"이라 모순이 아니라 **단순 구버전**(ARCHIVE)으로 분류.

---

## docs/ 분류

### KEEP (현재 운영 직결)

```
ARCHITECTURE.md · ROADMAP.md · REGISTRY.md · APP_FACTORY.md · DEVELOPER_GUIDE.md
ISSUES.md · UI_INDEPENDENCE.md · QUALITY_STANDARD_V1.2.md · CALCULATOR_QUALITY_STANDARD_V1.0.md
CALCULATOR_CHANGELOG.md · LEGAL_PLATFORM_DESIGN.md · LEGAL_BASIS_SPLIT_DESIGN.md
LEGAL_BASIS_AUDIT.md · RMS_SCHEDULER_SETUP.md(RMS=법령/요율 감지, Calculator/Blog Scheduler와 무관한 별개 시스템)
RULE_COVERAGE_REPORT.md · RULE_COVERAGE_MEMO.md
docs/CALCULATOR_SCHEDULER_REMOVAL_FINAL_REPORT.md (untracked, 오늘 작성 — 현재 Scheduler 구조의 기준 최종 문서)
docs/GOLDEN10_CONTENT_STRUCTURING_REPORT.md (untracked — Golden10 authoritative source, 다른 문서들이 이걸 인용)
docs/GOLDEN10_AI_GENERATION_10OF10_REPORT.md (untracked — Golden10 AI생성 최신/최종 검증)
docs/CALCULATOR_BLOG_BOUNDARY_FINAL_DIAGNOSTIC_REPORT.md (untracked — Calculator↔Blog 경계 최신 기준 문서)
```

### MERGE (같은 주제 반복 — 기준 문서 + 나머지 ARCHIVE)

| 클러스터 | 기준 문서(KEEP) | 병합/ARCHIVE 대상 |
|---|---|---|
| Calculator Scheduler 역사/제거 (6건) | `CALCULATOR_SCHEDULER_REMOVAL_FINAL_REPORT.md` | `SCHEDULER_HISTORY_FULL_TRACE_REPORT.md`, `SCHEDULER_OFF_RUNTIME_DIAGNOSTIC_REPORT.md`, `SCHEDULER_SHUTDOWN_FINAL_REPORT.md`, `CALCULATOR_SCHEDULER_FINAL_DIAGNOSTIC_REPORT.md`, `CALCULATOR_BLOG_BOUNDARY_FINAL_DIAGNOSTIC_REPORT.md`(이건 경계 검증이라 KEEP과 겹치되 독자 가치 있음 — 유지 권장) |
| Golden10 진화 과정 (9건) | `GOLDEN10_CONTENT_STRUCTURING_REPORT.md` + `GOLDEN10_AI_GENERATION_10OF10_REPORT.md` | `GOLDEN10_CONTENT_STRUCTURING_EXECUTION_REPORT.md`, `GOLDEN10_POST_STRUCTURING_AUDIT_REPORT.md`, `GOLDEN10_CONTENT_IDENTITY_AUDIT_REPORT.md`, `GOLDEN10_REPRODUCIBILITY_AUDIT_REPORT.md`, `GOLDEN10_V2_BLOG_ENGINE_INVESTIGATION_REPORT.md`, `GOLDEN10_BLOG_REPRODUCIBILITY_IMPLEMENTATION_REPORT.md`, `GOLDEN10_SCHEDULER_BLOG_LINE_AUDIT_REPORT.md`, `GOLDEN10_BLOG_LINE_FINAL_VERIFICATION_REPORT.md`, `GOLDEN10_AI_GENERATION_PATH_AUDIT_REPORT.md` |
| Blog Scheduler ON 준비 과정 (4건) | 없음(전부 과정 문서, `CALCULATOR_SCHEDULER_REMOVAL_FINAL_REPORT.md`가 최신 상태 포함) | `BLOG_LINE_EXISTING_WP_SCHEDULER_INTEGRATION_AUDIT.md`, `BLOG_SCHEDULER_DASHBOARD_WP_INTEGRATION_REPORT.md`, `BLOG_SCHEDULER_DRY_RUN_VERIFICATION_REPORT.md`, `BLOG_SCHEDULER_PRE_ON_FINAL_AUDIT_REPORT.md` — 전부 ARCHIVE |
| 이미지 생성 PoC (8건) | 없음(전부 실험 기록, 라이브 코드에 미연결) | `POC_V3_PREMIUM_PROMPT_REPORT.md`, `PROMPT_TEMPLATE_SAMPLE_DNA.md`, `HYBRID_FEASIBILITY_STUDY.md`, `REPRODUCTION_FEASIBILITY_STUDY.md`, `T2_BODY_V3/V4/V5_REPORT.md`, `CALC_V1_PIPELINE_REPORT.md` — 전부 ARCHIVE(디자인 자산으로서 참고가치는 있으므로 REMOVE 아님) |
| WP 연결 검증 (3건) | 없음(전부 과정 문서) | `WP_CONNECTION_VERIFICATION_REPORT.md`, `WP_DRAFT_SINGLE_POST_INTEGRATION_REPORT.md`, `P4_WP_DRAFT_REPORT.md` — ARCHIVE |
| Legacy 정리 (2건) | 없음(둘 다 완료 보고서) | `LEGACY_CONTENT_INVENTORY_REPORT.md`, `LEGACY_37_CLEANUP_REPORT.md` — ARCHIVE(작업 완료 기록) |
| Dashboard 감사 (2건) | 없음 | `DASHBOARD_FINAL_OPERATION_AUDIT_REPORT.md`, `DASHBOARD_SCHEDULER_CONTROL_FULL_AUDIT_REPORT.md` — ARCHIVE(STEP3 모순 있음, 날짜 명시 후 보관 권장) |

### ARCHIVE (역사적 가치, 현재 운영 불필요) — 기타 개별

```
CALCMATE_FULL_ARCHITECTURE_FINAL_AUDIT_REPORT.md · CONTACT_EMAIL_MIGRATION_REPORT.md
P4_5_AUTH_NORMALIZATION_REPORT.md
+ tracked Phase 설계/감사 문서 다수: P2_0~P2_3_*.md, PHASE3_*.md, CA1A~CA4_*.md(20여건),
  TIER2_*.md, H3_FAQ_ENGINE_COMPLETION.md, H4B_COMPETITIVE_ANALYSIS_COMPLETION.md,
  TABLE_BUILDER_INVESTIGATION.md, INLINE_IMAGE_BUILDER_DESIGN.md, TOPIC_EXPANSION_DESIGN.md,
  INTENT_CONTENT_HUB_POLICY_V2.md, V2_ARCHITECTURE_AUDIT.md, DEPLOY_DIAGNOSIS.md,
  CALC10_YEARLY_LEAVE_SCOPE.md, QUALITY_REEVALUATION.md, BUGFIX_CALC_DESIGN_V2.md,
  CALCULATOR_REVIEWER_FIX_RESULT.md, CALC_QUALITY_IMPROVEMENT_RESULT.md
  (전부 tracked·완료된 Phase 산출물. 현재 구조와 직접 모순되지는 않음 — git history에 남아있으므로
   위험 없이 archive 폴더 이동만 하면 됨. 개별 재검토는 실제 정리 실행 시점에.)
```

### REMOVE-CANDIDATE (docs)

없음. **문서는 삭제보다 ARCHIVE 이동을 권장** — 특히 위 STEP3 표의 5건은 "혼동 소지"가 실질적 위험이므로 archive 시 파일명에 날짜/deprecated 표기 권장(예: `docs/_archive/2026-08/`).

---

## scripts/ 분류

### KEEP (보호 대상, STEP6/STEP7)

```
scripts/run_blog_scheduler.py   ← Blog Scheduler 정식 CLI, 절대 보호
```
그 외 tracked 147건 중 `diag_*`/`fix_*`/`regen_*`/`verify_*`/`dump_*` 계열(주휴수당/퇴직금/실업급여/4대보험/연차수당/육아휴직/연말정산 콘텐츠 품질수정 이력, sp2/sp6/sp8/ub/fi/al/pl/yt 코드명)은 **이미 git history에 커밋되어 있어 삭제 압박이 낮음** — 이번 조사에서는 개별 재검토 대신 "완료된 콘텐츠 수정 이력"으로만 표시. 개별 삭제는 다음 라운드에서 참조 검사 후 결정 권장.

### REMOVE-CANDIDATE (untracked, 이미지 PoC/Golden10 일회성 스크립트 31건)

전부 밑줄(`_`) 접두 명명 관례(1회성 실행 후 재사용 안 함) + docs/ 이미지PoC·Golden10 클러스터와 1:1 대응:

```
_calc_v1_gallery_gen.py · _golden10_ai_generation_test.py · _golden10_repro.py
_golden10_restructure.py · _golden10_scheduler_audit.py · _p4_wp_e2e.py
_phase5_followup_poc.py · _phase5_followup_poc_v2.py · _phase5_followup_poc_v3.py
_phase5_followup_poc_v4.py · _phase5_followup_poc_v4flat.py
_phase5_hybrid_poc.py · _phase5_hybrid_poc_v2.py
_phase5_t2_body_v3.py · _phase5_t2_body_v4.py · _phase5_t2_body_v5.py
_phase5c_fix_07_08_images.py · _phase5c_review_gen.py
_phase5e_regen_09thumb.py · _phase5e_regen_images.py · _phase5e_step5b_regen_04_07.py
_poc_all6_gallery_gen.py · _poc_v3_gallery_gen.py · _poc_v4_gallery_gen.py
_repro_gallery_gen.py · _reproduction_study.py
_t2v3_gallery_gen.py · _t2v4_gallery_gen.py · _t2v5_gallery_gen.py
gen_preview.py · phase5_3_full_regen.py
```
- **이유**: 전부 `image_pipeline/`(고아 모듈, Calculator/Blog 어느 라인에도 연결 안 됨) 또는 `data/phase5-followup/` 실험용 이미지 생성 PoC의 1회성 실행 스크립트.
- **참조**: `grep -R` 결과 서로 docs/*.md에서만 인용되고(실행 기록), 다른 `.py` 코드에서 import되는 곳 0건.
- **대체 파일**: 없음(실험 종료, 후속 없음).
- **위험도**: LOW(코드 어디서도 import 안 됨, 삭제해도 live 파이프라인 무영향). 단 archive 우선 권장(디자인 실험 재현 필요 시 참고용).

### 참조 재확인 필요(REMOVE 보류)

```
scripts/_verify_rewrite_phase_d.py   ← hasattr(args,"scheduler") 단언(이제 실패함) — 이미 임무 완료된 1회성 검증 스크립트, 재실행 안 되므로 REMOVE 가능하나 아직 확정 안 함
```

---

## tests/ 분류 (STEP9)

### KEEP (필수, 삭제 절대 금지)

```
tests/test_blog_schedule_slots.py     ← Blog Schedule 슬롯 로직 검증
tests/test_blog_scheduler.py          ← Blog Scheduler 자체 검증
tests/test_scheduler_line_isolation.py ← Calculator/Blog 공유 인프라(modules/scheduler.py) 격리 검증
tests/test_golden10_protection.py     ← Golden 10 보호 검증
```
전부 `pytest tests/ -q` 회귀에서 정상 통과 확인(975 passed에 포함, 실패 목록에 없음).

### REMOVE-CANDIDATE (고아 모듈 테스트, 4건)

```
tests/test_image_pipeline_p1.py, p2.py, p3.py, p4.py
```
- **이유**: `image_pipeline/`(고아 패키지, Calculator·Blog 어느 라인에서도 import 안 됨)를 테스트. p1/p2/p3는 **매 회귀마다 반복 실패**하는 cp949 인코딩 이슈의 원인 파일 그 자체.
- **참조**: `image_pipeline/pipeline.py` 자체 코드는 존재하나 라이브 파이프라인 미연결.
- **대체**: 없음.
- **위험도**: LOW(제거해도 라이브 기능 영향 없음) — 단, `image_pipeline/`을 향후 실제로 쓸 계획이 있다면 삭제 대신 cp949 인코딩 버그 수정이 맞는 선택. **사용자 확인 필요**(image_pipeline을 계속 개발할지, 폐기할지).

### `scripts/test_draft_verify.py` 현재 상태 (STEP9 지시 확인)

이미 `if __name__ == "__main__":` guard 적용 완료(직전 세션에서 처리). pytest 자동 탐색 시 더 이상 실행되지 않음 — **REMOVE-CANDIDATE 아님, 그대로 KEEP**.

---

## data/ 분류 (STEP8, 조사만·삭제 없음)

| 경로 | 상태 | 근거 |
|---|---|---|
| `data/schedule/` | KEEP | Calculator 스케줄 실행 이력(2026-06~08-20). Scheduler 코드는 제거됐지만 **과거 발행 이력 데이터 자체는 감사 기록**이므로 보존. |
| `data/schedule/blog/` | 존재하지 않음 | Blog Scheduler가 아직 한 번도 실행된 적 없어 미생성 — 정상. |
| `data/reproduction/` | KEEP | Blog Scheduler의 isolated output 디렉토리(draft 모드 산출물 경로) — 라이브 기능 대상. |
| `data/workspace/_site/` | KEEP | Calculator 정적 웹앱 출력(App Factory 결과물) — 라이브. |
| `data/backup/` | KEEP | DB 백업(`SalaryMate_DB_backup_20260805_before_reset`) + history/sheet 백업 — 안전장치, 삭제 절대 금지. |
| `data/legal/` | KEEP | 법령/요율 감지 시스템 관련 — STEP12 보호 대상. |
| `data/phase5-followup/`(3.3MB) | ARCHIVE 후보 | 이미지 PoC 실험 산출물 전체(위 docs 이미지PoC 클러스터의 출력물). 라이브 미사용, 그러나 디자인 참고자료로 가치 있어 이동 보관 권장. |
| `data/calcmate.db` | **REMOVE-CANDIDATE** | 0바이트, 코드 전체 검색 결과 참조 0건(실제 사용 DB는 `data/blog_auto.db`). 리브랜딩(SalaryMate→CalcMate) 과정에서 생성된 빈 스텁으로 추정. 위험도 LOW. |
| `data/{checkpoints,logs,outputs,dlq}` | **REMOVE-CANDIDATE** | 디렉토리명이 문자 그대로 `{checkpoints,logs,outputs,dlq}` — 과거 `mkdir -p data/{...}` 브레이스 확장이 실패해 생성된 빈 폴더(2026-06-20, 완전히 빈 상태, git 미추적). 위험도 LOW(완전히 비어있음 확인). |
| `docs/_backup_ca1b/` | KEEP (분류상 data지만 docs/에 위치) | legal_basis/registry 백업 스냅샷 — 안전장치. 위치가 `docs/` 인 것 자체가 misplace(문서가 아니라 데이터 백업)이므로 실제 정리 시 `data/backup/`으로 이동 권장(삭제 아님). |

---

## STEP 11 — REMOVE CANDIDATE 최종 목록 (형식대로)

1. **`data/calcmate.db`**
   이유: 0바이트, 리브랜딩 과정의 빈 스텁으로 추정
   참조: 코드 전체 검색 0건
   대체 파일: `data/blog_auto.db`(실사용 DB)
   위험도: **LOW**

2. **`data/{checkpoints,logs,outputs,dlq}`** (디렉토리)
   이유: 브레이스 확장 실패로 생긴 빈 폴더
   참조: 0건, 완전히 빈 상태 확인
   대체 파일: 없음(애초에 4개 별도 폴더가 의도였으나 이미 각각 `data/logs/`, `data/dlq/` 등으로 정상 존재)
   위험도: **LOW**

3. **untracked `scripts/_*.py` 31건**(이미지 PoC/Golden10 일회성 스크립트, 위 목록 전체)
   이유: 실험 종료, 고아 모듈(`image_pipeline/`) 또는 완료된 Golden10 구조화 작업 대상
   참조: 서로 docs 인용 외 코드 import 0건
   대체 파일: 없음
   위험도: **LOW**(단, 디자인 실험 재현 가치가 있어 ARCHIVE 우선 권장)

4. **`tests/test_image_pipeline_p1~p4.py`**
   이유: 고아 모듈(`image_pipeline/`) 테스트, p1~p3는 상시 실패 원인
   참조: `image_pipeline/` 자체는 존재하나 라이브 미연결
   대체 파일: 없음
   위험도: **LOW**(단, image_pipeline 향후 계획 여부 사용자 확인 필요 — REMOVE보다 먼저 "이 모듈을 계속 쓸지" 결정 필요)

문서는 REMOVE-CANDIDATE 없음(전부 ARCHIVE 권장, 위 MERGE 표 참조).

---

## STEP 12 — 삭제 금지 확인(재확인, 위반 없음)

```
modules/ · tests/ · config/ · content/ · data/ (전체)  → 개별 파일 단위로만 후보 표시, 디렉토리 자체 삭제 후보 없음
Golden 10 / DB / Blog Scheduler / Calculator 수동 생성 코드 → 전부 KEEP 확인됨
법령/요율 감지 시스템(RMS) → docs/RMS_SCHEDULER_SETUP.md 포함 KEEP
배포/서버 요구사항 문서 → 검색 결과 별도 발견 안 됨(존재 시 KEEP 원칙 동일 적용)
최종 아키텍처 문서(ARCHITECTURE.md) → KEEP
```

---

## STEP 14 — 중단 조건 점검 결과

이번 조사에서 다음 중단 조건에 해당해 REMOVE 결정을 보류한 항목:
- `tests/test_image_pipeline_p1~p4.py` — 삭제 시 "image_pipeline 폐기"라는 더 큰 설계 결정이 선행되어야 함(테스트만 지워서 해결할 문제 아님) → **사용자 결정 필요**
- `docs/_backup_ca1b/`, `data/backup/` — data/DB 관련이라 STEP8 원칙상 삭제 금지, 이동만 제안

---

## 결론 — 이번 단계 완료 조건

전수조사 + 분류안 작성 완료. **실제 파일 삭제·이동·병합 0건 수행**. 위 REMOVE-CANDIDATE 4개 그룹 + MERGE 5개 클러스터에 대해 사용자 승인 시 다음 단계(실제 정리 실행)로 진행 가능.
