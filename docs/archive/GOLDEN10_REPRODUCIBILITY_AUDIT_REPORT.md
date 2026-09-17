# Golden 10 블로그 콘텐츠 기준 확정 + 재현성 점검 보고서

## Overall: PASS WITH WARNINGS

---

## 1. Golden 10 Identity — 10/10 PASS

| # | slug | topic | intent | title | 현재 상태 |
|---|------|-------|--------|-------|-----------|
| 1 | severance-pay | 퇴직금 | eligibility | 퇴직금 계산기 | ✅ DB + 사이트 |
| 2 | weekly-holiday-allowance | 주휴수당 | howto | 주휴수당 계산기 | ✅ DB + 사이트 |
| 3 | unemployment-benefit | 실업급여 | eligibility | 실업급여 계산기 | ✅ DB + 사이트 |
| 4 | four-insurances | 4대보험 | calculator | 4대보험 계산기 | ✅ DB + 사이트 |
| 5 | annual-leave-allowance | 연차수당 | howto | 연차수당 계산기 | ✅ DB + 사이트 |
| 6 | severance-pay-documents | 퇴직금 | documents | 퇴직금 계산기 서류 안내 | ✅ DB + 사이트 |
| 7 | 육아휴직_급여_계산기 | 육아휴직 | eligibility | 육아휴직 급여 계산기 | ✅ DB + 사이트 |
| 8 | 연말정산_환급액_계산기 | 연말정산 | calculator | 연말정산 환급액 계산기 | ✅ DB + 사이트 |
| 9 | unemployment-benefit-howto | 실업급여 | howto | 실업급여 계산기 이용 방법 | ✅ DB + 사이트 |
| 10 | four-insurances-documents | 4대보험 | documents | 4대보험 계산기 서류 안내 | ✅ DB + 사이트 |

---

## 2. Golden 10 → Scheduler 연결

| 구분 | 수 | 설명 |
|------|-----|------|
| Golden 10 블로그 콘텐츠 | 10 | slug + intent 조합 |
| 계산기 DB records | 14 | 7 Golden + 3 intent variant + 4 non-Golden |
| Calculator snapshot | 7 | 회귀 검증용 (블로그 콘텐츠 수와 무관) |

**"snapshot 7개 = Golden 10 7개"라는 잘못된 해석은 저장소 어디에도 존재하지 않음** ✅

---

## 3. 스케줄 라인 추적

### 실제 코드 흐름

```
Schedule Input (modules/scheduler.py)
  → generate_today_schedule()
  → get_due_posts()
  → run_calculator_once() (modules/calculator_pipeline.py)
    → CalculatorCollector.collect() (modules/collector/calculator.py)
      → DB: repo.get_active() → 활성 계산기 전체
    → score_keywords() (modules/strategist_calculator.py)
    → for each keyword:
      → generate_seo() (modules/calculator_seo_generator.py)
      → generate_faq() (modules/calculator_faq_generator.py)
      → _write_article() (modules/calculator_pipeline.py)
        → content/calculator/writer.py: generate_article()
          → content/calculator/prompt.py: get_article_prompt(intent=)
      → WordPress publish
```

### 핵심 발견

`calculator_pipeline.py`의 `_write_article()` 함수에 다음 주석이 존재:

```python
# calculator 엔진은 항상 고정 7-H2 템플릿 사용 — intent 분기 없음
# (eligibility/documents/howto 템플릿은 V2 블로그 엔진용으로 content/blog/ 에 예약됨)
```

**즉, 현재 파이프라인은 intent를 전달하지 않으며, 항상 동일한 템플릿으로 콘텐츠를 생성한다.**

### intent 지원 경로

`content/calculator/prompt.py`의 `get_article_prompt()`는 intent별 템플릿을 지원:
- eligibility: 지급 대상 → 근로시간 조건 → 제외 대상 → 계산 방법 → FAQ
- documents: 필수 서류 목록 → 서류 발급 방법 → 제출 기한 → 주의사항 → FAQ
- howto: 이용 절차 → 계산 예시 → 주의사항 → FAQ
- calculator: 계산 원리 → 지급 조건 → 계산 예시 → FAQ

그러나 `calculator_pipeline.py`는 이 템플릿을 **사용하지 않는다**.

---

## 4. 재현성 검사

| 콘텐츠 | 기존 결과 | 입력 데이터 | 생성 entrypoint | 재생성 가능 | 문제 |
|--------|-----------|-------------|-----------------|-------------|------|
| (severance-pay, eligibility) | ✅ | ✅ | ⚠️ | ⚠️ | 파이프라인 intent 미전달 |
| (weekly-holiday-allowance, howto) | ✅ | ✅ | ⚠️ | ⚠️ | 동일 |
| (unemployment-benefit, eligibility) | ✅ | ✅ | ⚠️ | ⚠️ | 동일 |
| (four-insurances, calculator) | ✅ | ✅ | ⚠️ | ⚠️ | 동일 |
| (annual-leave-allowance, howto) | ✅ | ✅ | ⚠️ | ⚠️ | 동일 |
| (severance-pay, documents) | ✅ | ✅ | ❌ | ❌ | 파이프라인 documents 지원 없음 |
| (육아휴직_급여_계산기, eligibility) | ✅ | ✅ | ⚠️ | ⚠️ | 파이프라인 intent 미전달 |
| (연말정산_환급액_계산기, calculator) | ✅ | ✅ | ⚠️ | ⚠️ | 동일 |
| (unemployment-benefit, howto) | ✅ | ✅ | ❌ | ❌ | 파이프라인 howto 지원 없음 |
| (four-insurances, documents) | ✅ | ✅ | ❌ | ❌ | 파이프라인 documents 지원 없음 |

### 핵심 판정

현재 Golden 10 콘텐츠는:

1. **"입력 데이터만 있으면 파이프라인을 통해 다시 만들어낼 수 있는 상태"가 아니다**
2. **"이미 완성된 HTML을 DB에 넣어둔 상태"다**
3. `_golden10_restructure.py`가 **파이프라인을 우회하여** 직접 HTML을 DB에 기록했다

---

## 5. 구조화 작업 범위 확인

### 변경됨 ✅

| 항목 | 변경 여부 |
|------|-----------|
| H1 | 변경됨 (intent별 차별화) |
| 도입부 | 변경됨 (검색 의도 대응) |
| H2 구조 | 변경됨 (intent별 차별화) |
| 표 | 추가됨 (7개) |
| FAQ | 추가됨 (인라인 dl) |
| intent별 구조 | 적용됨 |
| 계산기 링크 | 유지 |
| article_content | 변경됨 (7개 업데이트 + 3개 신규) |

### 변경되지 않음 ✅

| 항목 | 변경 여부 |
|------|-----------|
| 계산기 계산 로직 | 없음 |
| Registry | 없음 |
| SSOT | 없음 |
| Scheduler | 없음 |
| WordPress | 없음 |
| Image Pipeline | 없음 |

---

## 6. DB 안전성

READ-ONLY. 변경 0건.

| 확인 항목 | 결과 |
|-----------|------|
| 전체 계산기 | 14개 |
| article_content 보유 | 10개 |
| article_content 없음 | 4개 (비-Golden) |
| intent 필드 | ALL NULL |
| 비정상 record | 없음 |
| created_at 이상 | 없음 (clone 시 base 복사) |

---

## 7. 사이트 출력

Golden 10 10건: **10/10 PASS**

| 항목 | 결과 |
|------|------|
| 페이지 존재 | 10/10 |
| H1=1 | 10/10 |
| H2≥4 | 10/10 |
| FAQ | 10/10 |
| 계산기 링크 | 10/10 |
| Meta description | 10/10 |
| Broken link | 0 |
| 중복 페이지 | 0 |

---

## 8. 보호 대상

| 대상 | 상태 |
|------|------|
| Calculator source | UNCHANGED ✅ |
| Registry | UNCHANGED ✅ |
| Calculator snapshots | UNCHANGED ✅ |
| SSOT | UNCHANGED ✅ |
| Scheduler | UNCHANGED ✅ |
| WordPress connector | UNCHANGED ✅ |
| Image Pipeline | UNCHANGED ✅ |
| Phase5-E reference | UNCHANGED ✅ |
| Pixel reference | UNCHANGED ✅ |

---

## 9. Regression

| 테스트 | 결과 |
|--------|------|
| 전체 pytest | **907 passed, 3 skipped** |
| 이전 기준 | 907 passed, 3 skipped |
| 차이 | 0 |
| 코드 회귀 | 없음 |

---

## 10. Issues

### WARN-1: 파이프라인 intent 미전달

**위험도**: 중간

`calculator_pipeline.py`의 `_write_article()`이 intent를 `_write_article()`에 전달하지만,
최종 `content/calculator/writer.py`의 `generate_article()`에서 intent를 `prompt.py`에 전달하는 구조이나,
`calculator_pipeline.py`의 `_write_article()` 자체가 intent 분기를 사용하지 않는다.

현재 파이프라인은 모든 계산기에 대해 동일한 템플릿으로 콘텐츠를 생성한다.

### WARN-2: 재현성 격리

**위험도**: 중간

현재 Golden 10 콘텐츠는 파이프라인을 통해 생성된 것이 아니라
`_golden10_restructure.py`가 직접 DB에 기록한 것이다.

만약 파이프라인이 실제로 실행되면:
- 기존 article_content가 덮어써짐
- intent별 구조가 아닌 동일 템플릿으로 재생성됨
- 표/FAQ/구조화 개선이 사라질 수 있음

### WARN-3: 신규 3개 계산기의 파이프라인 처리

**위험도**: 낮음

`severance-pay-documents`, `four-insurances-documents`, `unemployment-benefit-howto`는
DB에 존재하므로 `CalculatorCollector`에 의해 수집된다.

그러나 파이프라인은 이들을 "별도 intent의 콘텐츠"가 아니라
"독립적인 계산기"로 처리한다.

---

## 11. Final Verdict

**PASS WITH WARNINGS**

### 통과 항목

- [x] Golden 10 = 10건 확정
- [x] 10건 DB 존재 확인
- [x] 10건 사이트 출력 확인
- [x] 계산기/블로그 개념 분리 완료
- [x] 보호 대상 변경 0건
- [x] 회귀 테스트 PASS
- [x] Git 변경 없음

### 경고 항목

1. **파이프라인이 intent별 구조화 콘텐츠를 지원하지 않음** — 재현성 테스트 시 주의 필요
2. **현재 콘텐츠가 파이프라인 우회로 생성됨** — 파이프라인 재실행 시 덮어쓰기 위험
3. **"14 regenerated"는 계산기 페이지 재생성이며, 블로그 콘텐츠 재생성이 아님**

---

## 12. Recommendation

### 재현성 테스트 전 필요 조치

**파이프라인 intent 지원 구현이 선행되어야 한다.**

현재 상태에서 파이프라인을 실행하면:
- intent별 구조화된 콘텐츠가 **기존 동일 템플릿 콘텐츠로 덮어씌워짐**
- Golden 10의 구조화 개선(표, FAQ, intent별 H2)이 **손실됨**

### 권장 순서

1. `calculator_pipeline.py`의 `_write_article()`에 intent 전달 로직 추가
2. `content/calculator/writer.py`의 `generate_article()`이 intent를 실제로 사용하도록 보장
3. Golden 10 각 콘텐츠에 대한 intent 메타데이터 DB 설정
4. 파이프라인 재현성 테스트 실행
5. 기존 article_content와 재생성 결과 비교

### 또는

현재 구조화된 콘텐츠를 보호하기 위해:
- 파이프라인에서 article_content가 이미 존재하는 계산기를 **스킵**하는 정책 유지
- 재현성 테스트는 별도 환경에서 intent 파이미터와 함께 독립 실행
