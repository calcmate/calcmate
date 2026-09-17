# Golden 10 Content Identity Audit

## 1. Scope

본 보고서는 **Golden 10 블로그 콘텐츠 10건**의 정체성과 현재 상태를 확정하기 위한 READ-ONLY 전수조사 결과다.

계산기 로직, 운영 DB, SSOT, 스케줄러, WordPress 등은 수정하지 않았다.

---

## 2. Authoritative Golden 10

**Golden 10은 "계산기 7개"가 아니라 "블로그 콘텐츠 10건"이다.**

근거: `docs/GOLDEN10_CONTENT_STRUCTURING_REPORT.md` (구조화 이전 전수검사 보고서)

| # | Calculator/Topic | Intent | Content Identity | 과거 근거 |
|---|------------------|--------|------------------|-----------|
| 1 | severance-pay | eligibility | (severance-pay, eligibility) | GOLDEN10_REPORT #1 |
| 2 | weekly-holiday-allowance | howto | (weekly-holiday-allowance, howto) | GOLDEN10_REPORT #2 |
| 3 | unemployment-benefit | eligibility | (unemployment-benefit, eligibility) | GOLDEN10_REPORT #3 |
| 4 | four-insurances | calculator | (four-insurances, calculator) | GOLDEN10_REPORT #4 |
| 5 | annual-leave-allowance | howto | (annual-leave-allowance, howto) | GOLDEN10_REPORT #5 |
| 6 | severance-pay | documents | (severance-pay, documents) | GOLDEN10_REPORT #6 |
| 7 | 육아휴직_급여_계산기 | eligibility | (육아휴직_급여_계산기, eligibility) | GOLDEN10_REPORT #7 |
| 8 | 연말정산_환급액_계산기 | calculator | (연말정산_환급액_계산기, calculator) | GOLDEN10_REPORT #8 |
| 9 | unemployment-benefit | howto | (unemployment-benefit, howto) | GOLDEN10_REPORT #9 |
| 10 | four-insurances | documents | (four-insurances, documents) | GOLDEN10_REPORT #10 |

**3개 calculator가 2개 intent를 가지며, 총 10개 블로그 콘텐츠가 존재한다:**
- severance-pay: eligibility + documents
- unemployment-benefit: eligibility + howto
- four-insurances: calculator + documents

---

## 3. Evidence

### 3-1. GOLDEN10_CONTENT_STRUCTURING_REPORT.md

구조화 작업 **이전**에 작성된 전수검사 보고서로, 10개 전체를 명시하고 있다.

특히 #6, #9, #10에 대해 intent 키워드 검증 결과를 기록하고 있으며:
- #6 severance-pay / documents: WARN — "서류", "제출", "발급" 누락
- #9 unemployment-benefit / howto: PASS — "절차", "방법", "예시" 포함
- #10 four-insurances / documents: WARN — "서류", "제출", "발급" 누락

이는 이 3개 콘텐츠가 **구조화 이전부터 Golden 10의 일부로 정의되어 있었음**을 입증한다.

### 3-2. content/calculator/prompt.py

intent별 템플릿이 이미 구현되어 있다:
- `eligibility`: 지급 대상 → 근로시간 조건 → 제외 대상 → 계산 방법 → FAQ
- `documents`: 필수 서류 목록 → 서류 발급 방법 → 제출 기한 및 절차 → 주의사항 → FAQ
- `howto`: 이용 절차 → 계산 예시 → 주의사항 → FAQ
- `calculator`: 계산 원리 → 지급 조건 → 계산 예시 → FAQ

### 3-3. _golden10_restructure.py

3개를 "(NEW)"로 표시:
- `# 2. severance-pay / documents (NEW)`
- `# 6. four-insurances / documents (NEW)`
- `# 10. unemployment-benefit / howto (NEW)`

"NEW"는 **DB에 신규 row가 생성됨**을 의미하며, Golden 10 목록에서 새로 추가됨을 의미하지 않는다.

### 3-4. Golden snapshot

`tests/golden/calculator_snapshots.json`에는 **7개 calculator**만 기록되어 있다.

이는 **계산기 해시 추적 대상**이 7개라는 의미이며,
블로그 콘텐츠의 수와 혼동해서는 안 된다.

---

## 4. Current Content Mapping

| # | Content Identity | DB Row | slug | article_content | Site Output | 매핑 |
|---|------------------|--------|------|-----------------|-------------|------|
| 1 | (severance-pay, eligibility) | ✅ | severance-pay | 3203 bytes | ✅ | MATCH |
| 2 | (weekly-holiday-allowance, howto) | ✅ | weekly-holiday-allowance | 2355 bytes | ✅ | MATCH |
| 3 | (unemployment-benefit, eligibility) | ✅ | unemployment-benefit | 2984 bytes | ✅ | MATCH |
| 4 | (four-insurances, calculator) | ✅ | four-insurances | 2853 bytes | ✅ | MATCH |
| 5 | (annual-leave-allowance, howto) | ✅ | annual-leave-allowance | 2146 bytes | ✅ | MATCH |
| 6 | (severance-pay, documents) | ✅ | severance-pay-documents | 2508 bytes | ✅ | MATCH |
| 7 | (육아휴직_급여_계산기, eligibility) | ✅ | 육아휴직_급여_계산기 | 2575 bytes | ✅ | MATCH |
| 8 | (연말정산_환급액_계산기, calculator) | ✅ | 연말정산_환급액_계산기 | 2781 bytes | ✅ | MATCH |
| 9 | (unemployment-benefit, howto) | ✅ | unemployment-benefit-howto | 2296 bytes | ✅ | MATCH |
| 10 | (four-insurances, documents) | ✅ | four-insurances-documents | 2393 bytes | ✅ | MATCH |

**10/10 MATCH** — 모든 Golden 10 블로그 콘텐츠가 DB와 사이트 출력에 존재한다.

---

## 5. Missing

**0건** — Golden 10 중 누락된 콘텐츠가 없다.

---

## 6. Duplicate

**0건** — 동일한 Content Identity가 중복되어 존재하지 않는다.

---

## 7. Additional Content (Golden 10 외)

### 7-1. 비-Golden 계산기 (4개)

| slug | name | article_content | 비고 |
|------|------|----------------|------|
| freelancer-tax-3p3 | 프리랜서 3.3% 원천징수 | 없음 | 이전 단계 생성 |
| jeonse-vs-monthly | 전세 vs 월세 비교 | 없음 | 이전 단계 생성 |
| annual-leave-remaining | 연차 잔여일 | 없음 | 이전 단계 생성 |
| military-discharge-date | 군인 전역일 | 없음 | 이전 단계 생성 |

이 4개는 `content/calculator/prompt.py`의 `_VALID_CALCULATORS` 목록에 포함되어 있으나,
Golden 10 블로그 콘텐츠와는 무관하다.

### 7-2. 유틸리티 페이지 (4개)

about, contact, privacy, terms — 블로그 콘텐츠가 아닌 사이트 공통 페이지.

---

## 8. Calculator vs Blog Content

이번 전수조사에서 가장 중요한 개념 분리:

| 구분 | Calculator Entity | Blog Content Entity |
|------|-------------------|---------------------|
| 정의 | 계산 로직 + 입력/출력 스키마 | article_content (블로그 본문) |
| 식별자 | slug | slug + intent |
| 현재 수 | 14개 | 10개 (Golden) + 0 (비-Golden) |
| snapshot | 7개 (calculator_snapshots.json) | 없음 (별도 snapshot 없음) |
| 예시 | severance-pay (계산기) | (severance-pay, eligibility) + (severance-pay, documents) |

**"Golden 10"은 블로그 콘텐츠 10건을 가리키며, 계산기 7개를 가리키지 않는다.**

---

## 9. "14 Regenerated" 해석

직전 작업에서 "14개 regenerated"라고 보고한 것은:

| 분류 | 수 | 의미 |
|------|-----|------|
| Golden 10 article 업데이트 | 7 | 기존 계산기 7개의 article_content 변경 |
| 신규 intent 페이지 생성 | 3 | Golden 10 미완분 완성 (DB new row) |
| 비-Golden 계산기 페이지 재생성 | 4 | site_generator.py가 DB 전체를 재생성 |
| **합계** | **14** | **site_generator.py의 전체 출력** |

"14 regenerated"는 site_generator.py가 DB의 **전체 14개 계산기**를 재생성한 결과이며,
이것이 곧 "14개 블로그 콘텐츠"라는 의미는 아니다.

실제 블로그 콘텐츠(article_content 보유)는 **10개**다.

---

## 10. DB Status

READ-ONLY로 확인함. 변경 0건.

| 확인 항목 | 결과 |
|-----------|------|
| 전체 계산기 row | 14개 |
| article_content 보유 | 10개 |
| article_content 없음 | 4개 (비-Golden) |
| intent 필드 | ALL NULL |
| created_at (신규 3개) | base 계산기와 동일 (clone 시 복사) |
| updated_at (신규 3개) | 2026-08-19 (구조화 시점) |

---

## 11. Site Status

| 항목 | 결과 |
|------|------|
| 전체 페이지 | 18 |
| Golden 10 페이지 | 10 ✅ |
| 비-Golden 계산기 | 4 |
| 유틸리티 | 4 |
| broken link | 0 |
| H1=1 | 10/10 ✅ |
| FAQ (dl + jsonld) | 10/10 ✅ |
| 계산기 링크 | 10/10 ✅ |

---

## 12. Protected System Status

| 대상 | 상태 |
|------|------|
| Calculator source | UNCHANGED ✅ |
| docs/registry/ | UNCHANGED ✅ |
| tests/golden/ | UNCHANGED ✅ |
| SSOT | UNCHANGED ✅ |
| Scheduler | UNCHANGED ✅ |
| WordPress | UNCHANGED ✅ |
| Image pipeline | UNCHANGED ✅ |
| content pipeline core | UNCHANGED ✅ |

---

## 13. Regression

| 테스트 | 결과 |
|--------|------|
| 전체 pytest | **907 passed, 3 skipped** |
| 환경 문제 | OpenBLAS/PIL 메모리 (기존 flaky) |
| 코드 회귀 | 없음 |

---

## 14. Final Verdict

**PASS**

Golden 10 블로그 콘텐츠 10건이 모두 존재하며, 각 콘텐츠의 정체성이 확인되었다.

| 항목 | 결과 |
|------|------|
| Golden 10 확정 | **10/10** |
| 현재 매칭 | **10/10 MATCH** |
| Missing | **0** |
| Duplicate | **0** |
| Additional (Golden 외) | 4개 비-Golden 계산기 + 4개 유틸리티 |
| 보호 대상 변경 | **0건** |
| 회귀 테스트 | **PASS** |
| Git 변경 | 없음 (READ-ONLY) |

### 이전 보고서의 오류 정정

이전 `GOLDEN10_POST_STRUCTURING_AUDIT_REPORT.md`에서:
- "Golden 10 snapshot = 7개" → **계산기 snapshot의 수**이며, 블로그 콘텐츠 수와 혼동
- "3개 신규 = 과잉 생성" → **Golden 10 미완분 완성**이며, 과잉이 아님
- "DB 14개 = 과잉" → **14개 계산기 record**이며, 블로그 콘텐츠 10건과 혼동

---

## 15. Recommended Next Step

### DONE (이미 완료)
- ✅ Golden 10 블로그 콘텐츠 10건 구조화
- ✅ Intent별 H2 차별화
- ✅ 표/FAQ 추가
- ✅ 사이트 재생성

### FOLLOW-UP (후속 작업)
1. **intent 필드 설정** — DB의 intent NULL 문제 해결
2. **seo_title/seo_description 커스터마이징** — 신규 3개의 메타데이터 보정
3. **Golden snapshot 확장** — 블로그 콘텐츠 10건의 별도 snapshot 고려
4. **비-Golden 계산기 article_content 생성** — 4개 계산기의 블로그 콘텐츠 미생성 상태 해소
