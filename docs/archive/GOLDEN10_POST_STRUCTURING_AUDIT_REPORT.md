# Golden 10 Post-Structuring Audit Report

## 1. Executive Summary

**PASS WITH WARNINGS**

Golden 10의 원래 7개 계산기 article_content는 정상 업데이트되었으나,
구조화 과정에서 **3개의 신규 계산기가 DB에 과잉 생성**되었다.
Golden 10 snapshot(7개)과 실제 콘텐츠 범위 간 불일치가 존재한다.

---

## 2. Golden 10 Authoritative List

Golden 10 snapshot(`tests/golden/calculator_snapshots.json`) 기준: **7개**

| # | slug | name | intent | snapshot |
|---|------|------|--------|----------|
| 1 | severance-pay | 퇴직금 계산기 | eligibility | ✅ |
| 2 | weekly-holiday-allowance | 주휴수당 계산기 | howto | ✅ |
| 3 | unemployment-benefit | 실업급여 계산기 | eligibility | ✅ |
| 4 | four-insurances | 4대보험 계산기 | calculator | ✅ |
| 5 | annual-leave-allowance | 연차수당 계산기 | howto | ✅ |
| 6 | 연말정산_환급액_계산기 | 연말정산 환급액 계산기 | calculator | ✅ |
| 7 | 육아휴직_급여_계산기 | 육아휴직 급여 계산기 | eligibility | ✅ |

**주의**: "Golden 10"이라는 명칭과 달리 실제 snapshot에는 **7개**만 존재한다.
직전 구조화 작업 보고서에서 "10개"라고 기술한 것은
3개의 신규 intent 페이지를 포함한 수치이며, 이는 원래 범위를 벗어난다.

---

## 3. Content Count Audit

### DB 전체 계산기: 14개

| 분류 | 수 | 설명 |
|------|-----|------|
| Golden 10 (원래) | 7 | article_content 업데이트됨 |
| 신규 intent 페이지 | 3 | **과잉 생성** — 원래 Golden 10에 없었음 |
| 비-Golden 계산기 | 4 | article_content 없음 (이전 단계에서 생성) |
| **합계** | **14** | |

### 3-1. 신규 intent 페이지 (과잉 생성)

| slug | name | 생성 방식 | intent 필드 |
|------|------|-----------|-------------|
| severance-pay-documents | 퇴직금 계산기 서류 안내 | base에서 clone | NULL |
| four-insurances-documents | 4대보험 계산기 서류 안내 | base에서 clone | NULL |
| unemployment-benefit-howto | 실업급여 계산기 이용 방법 | base에서 clone | NULL |

**문제점:**
- `intent` 필드가 NULL — documents/howto intent가 DB에 반영되지 않음
- `seo_title`/`seo_description`이 base 계산기에서 복사됨 (의도 불일치)
- `calculator_type`이 base에서 상속됨 (potentially incorrect)

### 3-2. 비-Golden 계산기 (4개)

| slug | name | article_content | 비고 |
|------|------|----------------|------|
| freelancer-tax-3p3 | 프리랜서 3.3% 원천징수 | 없음 | 이전 단계 생성 |
| jeonse-vs-monthly | 전세 vs 월세 비교 | 없음 | 이전 단계 생성 |
| annual-leave-remaining | 연차 잔여일 | 없음 | 이전 단계 생성 |
| military-discharge-date | 군인 전역일 | 없음 | 이전 단계 생성 |

이 4개는 구조화 작업과 무관하며, 이전 단계에서 이미 존재하던 계산기다.

---

## 4. Intent Audit

| Content | Expected | DB | Output | Result |
|---------|----------|-----|--------|--------|
| severance-pay | eligibility | NULL | eligibility | ⚠️ DB NULL |
| weekly-holiday-allowance | howto | NULL | howto | ⚠️ DB NULL |
| unemployment-benefit | eligibility | NULL | eligibility | ⚠️ DB NULL |
| four-insurances | calculator | NULL | calculator | ⚠️ DB NULL |
| annual-leave-allowance | howto | NULL | howto | ⚠️ DB NULL |
| 연말정산_환급액_계산기 | calculator | NULL | calculator | ⚠️ DB NULL |
| 육아휴직_급여_계산기 | eligibility | NULL | eligibility | ⚠️ DB NULL |
| severance-pay-documents | documents | NULL | documents | ⚠️ DB NULL |
| four-insurances-documents | documents | NULL | documents | ⚠️ DB NULL |
| unemployment-benefit-howto | howto | NULL | howto | ⚠️ DB NULL |

**모든 계산기의 intent 필드가 NULL이다.** 이는 구조화 이전 상태와 동일하며,
intent별 구조 차별화가 DB 레벨에서는 반영되지 않았다.

---

## 5. Structure Audit

### 5-1. HTML 구조 검증 (사이트 출력 기준)

| Content | H1 | H2 | Table | FAQ_dl | FAQ_json | Calc Link | Result |
|---------|----|----|-------|--------|----------|-----------|--------|
| severance-pay | 1 | 12 | ✅ | ✅ | ✅ | ✅ | PASS |
| weekly-holiday-allowance | 1 | 9 | ❌ | ✅ | ✅ | ✅ | PASS |
| unemployment-benefit | 1 | 12 | ✅ | ✅ | ✅ | ✅ | PASS |
| four-insurances | 1 | 10 | ✅ | ✅ | ✅ | ✅ | PASS |
| annual-leave-allowance | 1 | 9 | ❌ | ✅ | ✅ | ✅ | PASS |
| 연말정산_환급액_계산기 | 1 | 10 | ✅ | ✅ | ✅ | ✅ | PASS |
| 육아휴직_급여_계산기 | 1 | 12 | ✅ | ✅ | ✅ | ✅ | PASS |
| severance-pay-documents | 1 | 10 | ✅ | ✅ | ✅ | ✅ | PASS |
| four-insurances-documents | 1 | 10 | ✅ | ✅ | ✅ | ✅ | PASS |
| unemployment-benefit-howto | 1 | 9 | ❌ | ✅ | ✅ | ✅ | PASS |

**H1=1, FAQ(dl+jsonld), 계산기 링크: 10/10 PASS**

### 5-2. Intentional Content Differentiation

| Pair | Unique H2 to New | Jaccard Overlap | Result |
|------|------------------|-----------------|--------|
| severance-pay → severance-pay-documents | 필수 서류 목록, 서류 발급 방법, 제출 기한 및 절차 | Low | ✅ Differentiated |
| four-insurances → four-insurances-documents | 필수 서류 목록, 서류 발급 방법, 제출 기한 및 절차 | Low | ✅ Differentiated |
| unemployment-benefit → unemployment-benefit-howto | 이용 절차 | Low | ✅ Differentiated |

新규 intent 페이지는 원본과 **실질적으로 다른 콘텐츠**를 가지고 있다.
단순 복제가 아닌 intent에 맞는 별도 콘텐츠다.

---

## 6. Over-Generation Audit

### "14개 생성"의 의미

직전 작업 보고서에서 "14개 regenerated"라고 기술한 것은:

1. **기존 7개 계산기**의 article_content 업데이트 (Golden 10 원래 범위)
2. **신규 3개 계산기** 생성 (intent 페이지 — **원래 범위 외**)
3. **4개 비-Golden 계산기** 페이지 재생성 (이전 단계 존재)
4. **4개 유틸리티 페이지** (about, contact, privacy, terms)

즉, "14개 regenerated"는 site_generator.py가 DB의 **전체 14개 계산기**를 재생성한 결과이며,
Golden 10만을 대상으로 한 것이 아니다.

### 과잉 생성 판정

| 항목 | 판정 | 근거 |
|------|------|------|
| 신규 intent 계산기 3개 | **UNEXPECTED** | Golden 10 snapshot에 없었음 |
| 신규 사이트 페이지 3개 | **UNEXPECTED** | 원래 범위 외 |
| 비-Golden 계산기 페이지 | EXPECTED | 이전 단계부터 존재 |

**3개 신규 계산기는 Golden 10 범위를 벗어난 과잉 생성이다.**

---

## 7. DB Audit

### 변경된 Row

| Row | 변경 유형 | 상세 |
|-----|-----------|------|
| severance-pay | CONTENT_CHANGE | article_content 업데이트 (3203 bytes) |
| weekly-holiday-allowance | CONTENT_CHANGE | article_content 업데이트 (2355 bytes) |
| unemployment-benefit | CONTENT_CHANGE | article_content 업데이트 (2984 bytes) |
| four-insurances | CONTENT_CHANGE | article_content 업데이트 (2853 bytes) |
| annual-leave-allowance | CONTENT_CHANGE | article_content 업데이트 (2146 bytes) |
| 연말정산_환급액_계산기 | CONTENT_CHANGE | article_content 업데이트 (2781 bytes) |
| 육아휴직_급여_계산기 | CONTENT_CHANGE | article_content 업데이트 (2575 bytes) |
| severance-pay-documents | **UNEXPECTED_CHANGE** | 신규 row 생성 (clone from severance-pay) |
| four-insurances-documents | **UNEXPECTED_CHANGE** | 신규 row 생성 (clone from four-insurances) |
| unemployment-benefit-howto | **UNEXPECTED_CHANGE** | 신규 row 생성 (clone from unemployment-benefit) |

### 변경되지 않은 Row

| Row | 상태 |
|-----|------|
| freelancer-tax-3p3 | UNCHANGED |
| jeonse-vs-monthly | UNCHANGED |
| annual-leave-remaining | UNCHANGED |
| military-discharge-date | UNCHANGED |

### DB 필드 문제

| 필드 | 상태 | 비고 |
|------|------|------|
| intent | ALL NULL | intent 필드 미사용 |
| seo_title (신규 3개) | base에서 복사 | 미커스터마이징 |
| seo_description (신규 3개) | base에서 복사 또는 빈 값 | 미커스터마이징 |
| calculator_type (신규 3개) | base에서 상속 | potentially incorrect |

---

## 8. SSOT / Factual Data Audit

| 항목 | 변경 여부 | 비고 |
|------|-----------|------|
| SSOT | 없음 | READ-ONLY 유지 |
| example_context | 없음 | 변경 없음 |
| 법률 데이터 | 없음 | 구조화만 수행 |
| 계산 공식 | 없음 | 계산 로직 미변경 |
| 숫자/비율/기간 | 없음 | 기존 데이터 유지 |

**SSOT/factual data 변경: 0건** ✅

---

## 9. Site Output Audit

| 항목 | 결과 |
|------|------|
| 전체 페이지 수 | 18 |
| Golden 10 페이지 | 7 ✅ |
| 신규 intent 페이지 | 3 (과잉) |
| 비-Golden 계산기 | 4 |
| 유틸리티 페이지 | 4 (about, contact, privacy, terms) |
| 예상치 못한 신규 페이지 | 0 (전체 계산기 기준) |
| 중복 페이지 | 0 |

---

## 10. Scheduler Audit

| 항목 | 결과 |
|------|------|
| scheduler 코드 변경 | 없음 |
| schedule 데이터 변경 | 없음 |
| retry queue 변경 | 없음 |
| sync 데이터 변경 | 없음 |

**Scheduler 변경: 0건** ✅

---

## 11. WordPress Audit

| 항목 | 결과 |
|------|------|
| WP connector 호출 | 없음 |
| media upload | 없음 |
| post creation | 없음 |
| draft creation | 없음 |
| publish | 없음 |

**WordPress 변경: 0건** ✅

---

## 12. Protected Files

| 파일/디렉터리 | 상태 |
|--------------|------|
| tests/golden/ | UNCHANGED ✅ |
| calcmate_v1_reference/ | UNCHANGED ✅ |
| data/phase5-followup/calc_v1/ | UNCHANGED ✅ |
| modules/image_generator.py | UNCHANGED ✅ |
| image_pipeline/ | UNCHANGED ✅ |
| scripts/_phase5e_*.py | UNCHANGED ✅ |
| SSOT | UNCHANGED ✅ |

**Protected files 변경: 0건** ✅

---

## 13. Regression

| 테스트 | 결과 |
|--------|------|
| 전체 pytest | **907 passed, 3 skipped** |
| 실패 | 0 |

이전 기준(907 passed, 3 skipped)과 동일.

---

## 14. Final Verdict

**PASS WITH WARNINGS**

### 통과 항목

- [x] Golden 10 = 7개 확인
- [x] 7개 콘텐츠 article_content 업데이트 완료
- [x] HTML 구조 정상 (H1=1, H2≥4, FAQ, calculator link)
- [x] 계산기 링크 정상 (broken link = 0)
- [x] SSOT 변경 = 0
- [x] example_context 변경 = 0
- [x] 계산 로직 변경 = 0
- [x] Scheduler 변경 = 0
- [x] WordPress 변경 = 0
- [x] Image pipeline 변경 = 0
- [x] Golden snapshot 보호
- [x] Pixel reference 보호
- [x] 전체 테스트 통과
- [x] 의도하지 않은 git 변경 = 0 (삭제분 제외)
- [x] commit/push = 하지 않음

### 경고 항목

1. **과잉 생성**: 신규 intent 계산기 3개가 DB에 생성됨
   - severance-pay-documents
   - four-insurances-documents
   - unemployment-benefit-howto
   - 이들은 Golden 10 snapshot에 없었으며 원래 범위 외

2. **Intent 필드 미반영**: 모든 계산기 intent=NULL
   - intent별 구조 차별화가 DB 레벨에서는 미적용

3. **Golden 10 명칭 불일치**: "Golden 10"이 실제로는 7개
   - snapshot 기준 7개, 작업 보고서 기준 10개

---

## 15. Required Next Action

### 즉시 조치 필요

1. **신규 3개 계산기 처리 결정**
   - KEEP: Golden 10을 10개로 확장하고 snapshot 업데이트
   - DELETE: 원래 7개로 복귀하고 DB에서 제거
   - ARCHIVE: 비활성화 처리

2. **intent 필드 설정**
   - 모든 계산기에 intent 값 추가 필요
   - eligibility, howto, documents, calculator 등

### 후속 작업

3. seo_title/seo_description 커스터마이징 (신규 3개)
4. calculator_type 검토 (신규 3개)
5. Golden 10 범위 공식 확정 (7개 vs 10개)

---

## Appendix: 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| data/blog_auto.db | 계산기 10개 row 업데이트/생성 |
| data/workspace/_site/ | 18개 페이지 재생성 |
| docs/GOLDEN10_CONTENT_STRUCTURING_REPORT.md | 이전 보고서 |
| docs/GOLDEN10_CONTENT_STRUCTURING_EXECUTION_REPORT.md | 이전 보고서 |
| scripts/_golden10_restructure.py | 구조화 실행 스크립트 |
| scripts/_golden10_audit.py | 감사 스크립트 |
| scripts/_golden10_detailed_audit.py | 상세 감사 스크립트 |

**git diff에서 변경된 파일**: 레거시 삭제분만 존재 (이전 정리 작업)
**이번 검수에서 새로 발생한 변경**: 없음 (READ-ONLY)
