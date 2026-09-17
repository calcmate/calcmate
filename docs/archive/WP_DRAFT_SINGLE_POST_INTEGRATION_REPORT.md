# WP Draft 1건 실증 발행 통합 보고서

**DATE**: 2026-08-20  
**FINAL VERDICT**: PASS

---

## 1. 작업 목적

Golden 10 Blog Line → Local WordPress 실제 발행 경로를  
`severance-pay / eligibility` 1건으로 실증한다.

---

## 2. 작업 전 상태

| 항목 | 상태 |
|------|------|
| HEAD | `27afbe2` |
| Calculator Scheduler | OFF (`enabled: false`) |
| Blog Scheduler | OFF (`BLOG_SCHEDULE.enabled: false`) |
| run_scheduler.bat | `.disabled` |
| WP URL | `http://salarymate.test` |
| WP Auth | PASS (user_id=1, SalaryMate) |
| Golden 10 | 10/10 present |
| DB calculators | 14 rows |

---

## 3. AI 생성 결과

| 항목 | 결과 |
|------|------|
| slug | `severance-pay` |
| intent | `eligibility` |
| title | 퇴직금 받을 수 있나요? 자격 요건과 계산 방법 |
| 생성 시간 | 16.8s |
| 본문 길이 | 1,399 chars |
| H2 수 | 5 |
| FAQ 존재 | Yes |
| 계산기 링크 | Yes |

**Blog Line 경로:**
```
Golden 10 Contract
  → get_golden10("severance-pay")
  → intent = "eligibility"
  → generate_blog_article(cfg, calc, intent="eligibility")
  → content.calculator.writer.generate_article(intent="eligibility")
  → OPENAI_API_KEY → actual AI provider
  → HTML body (1,399 chars)
```

---

## 4. WordPress Draft 발행 결과

| 항목 | 결과 |
|------|------|
| HTTP status | **201 Created** |
| WP Post ID | **396** |
| slug | `severance-pay` |
| status | **draft** |
| link | `http://salarymate.test/?p=396` |
| title | 퇴직금 받을 수 있나요? 자격 요건과 계산 방법 |

**draft 확인:**
- `status == "draft"` ✅
- `publish/pending/private` 아님 ✅
- 공개 발행 아님 ✅

---

## 5. WP Draft 콘텐츠 검증

| 항목 | 결과 |
|------|------|
| H1 | 0 (정상 — site template에서 추가) |
| H2 | 5 |
| FAQ section | Present |
| Calculator link | Present |
| eligibility 구조 | 지급 대상 / 근로시간 조건 / 제외 대상 / 계산 방법 / FAQ |
| 콘텐츠 길이 | 1,384 chars |

---

## 6. 이미지 호출 검증

| 항목 | 결과 |
|------|------|
| Image Pipeline | **0 calls** |
| image_generator | **0 calls** |
| WP media upload | **0** |

---

## 7. DB 불변성 검증

| 항목 | Before | After | Changed |
|------|--------|-------|---------|
| severance-pay hash | `fd7485f2bf979771` | `fd7485f2bf979771` | **NO** |
| annual-leave-allowance | `b7a8a00c4c8141eb` | `b7a8a00c4c8141eb` | **NO** |
| four-insurances | `0a3f4542a215c159` | `0a3f4542a215c159` | **NO** |
| four-insurances-documents | `3dffb9ce76e795c5` | `3dffb9ce76e795c5` | **NO** |
| severance-pay-documents | `f9464d5547a45573` | `f9464d5547a45573` | **NO** |
| unemployment-benefit | `cc30d4df20295706` | `cc30d4df20295706` | **NO** |
| unemployment-benefit-howto | `b3d0e210fc43c7c8` | `b3d0e210fc43c7c8` | **NO** |
| weekly-holiday-allowance | `b5377776b3a8512d` | `b5377776b3a8512d` | **NO** |
| 연말정산_환급액_계산기 | `150f74ca101acf1c` | `150f74ca101acf1c` | **NO** |
| 육아휴직_급여_계산기 | `3f94bf851923954e` | `3f94bf851923954e` | **NO** |

**Golden 10 10/10 UNCHANGED** ✅

---

## 8. Calculator Line 격리

| 항목 | 결과 |
|------|------|
| calculator_pipeline.py | NOT called |
| auto_generate_all | NOT called |
| calculators rows | 14 (unchanged) |
| calculator article_content | UNCHANGED |
| SSOT | UNCHANGED |

---

## 9. 중복 방지 검증

| 항목 | 결과 |
|------|------|
| WP에 `severance-pay` slug 게시물 | 1건 (방금 생성한 draft #396) |
| 기존 published 글과 중복 | 없음 |

---

## 10. Scheduler 상태

| 항목 | 상태 |
|------|------|
| Calculator Scheduler | OFF |
| Blog Scheduler | OFF |
| Windows Task Scheduler | 변경 없음 |
| run_scheduler.bat | disabled |
| Scheduler process | 없음 |

---

## 11. Regression

```
945 passed, 4 skipped (102.00s)
```

기존 baseline과 완전 동일. 회귀 0건.

---

## 12. Git 변경 사항

WP Draft 발행으로 인한 소스 코드 변경: **없음**  
격리 출력만 생성:
- `data/reproduction/wp_draft_test/severance_pay_result.json`

---

## 13. 최종 판정

| 조건 | 결과 |
|------|------|
| severance-pay 1건만 테스트 | ✅ |
| 실제 AI 생성 성공 | ✅ (16.8s, 1,399 chars) |
| intent=eligibility 정상 | ✅ |
| WP 인증 PASS | ✅ |
| WP Draft 생성 PASS | ✅ (HTTP 201) |
| status=draft | ✅ |
| 기존 WP 게시물 수정/삭제 없음 | ✅ |
| DB Golden 10 hash UNCHANGED | ✅ (10/10) |
| Calculator Line 변경 0건 | ✅ |
| SSOT 변경 0건 | ✅ |
| Image Pipeline 호출 0건 | ✅ |
| WP media 생성 0건 | ✅ |
| Scheduler 자동 실행 없음 | ✅ |
| Windows Task Scheduler 변경 없음 | ✅ |
| Regression PASS | ✅ (945 passed) |

**FINAL VERDICT: PASS** ✅

---

## 14. WP에서 Draft 확인 방법

WordPress 관리자에서 확인:
```
http://salarymate.test/wp-admin/edit.php?post_status=draft
```

또는 REST API:
```
GET http://salarymate.test/wp-json/wp/v2/posts/396
```
