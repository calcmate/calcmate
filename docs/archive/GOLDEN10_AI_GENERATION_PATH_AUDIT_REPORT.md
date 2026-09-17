# Golden 10 AI Generation Path Audit Report

## Final Verdict

**PASS**

---

## 1. 실제 AI 호출 경로

```
content/blog/writer.py
  -> generate_blog_article(cfg, calc, intent=intent)
    -> if OPENAI_API_KEY in cfg:
         content.calculator.writer.generate_article(cfg, calc, ..., intent=intent)
           -> PM.get_article_prompt(calc, seo, faq, example_context, intent=intent)
           -> build_provider_for_role("writing", cfg)
           -> provider.chat(system, user, model, max_tokens=4000)
           -> cleaner.parse_html_body(text)
```

intent는 `prompt.py`의 `get_article_prompt()`까지 정확하게 전달됨.

---

## 2. Provider / Model

| 항목 | 값 |
|------|-----|
| API Key | `sk-proj-...` (164 chars) |
| Provider | OpenAI (via ai_provider.py) |
| Role | writing (MODEL_WRITER) |
| max_tokens | 4000 |

---

## 3. API 호출 결과 (4건)

| # | slug | intent | status | len | h2 | faq | time |
|---|------|--------|--------|-----|----|-----|------|
| 1 | severance-pay | eligibility | PASS | 1336 | 5 | yes | 15.7s |
| 2 | weekly-holiday-allowance | howto | PASS | 1481 | 4 | yes | 13.1s |
| 3 | severance-pay-documents | documents | PASS | 1741 | 5 | yes | 15.7s |
| 4 | four-insurances | calculator | PASS | 1858 | 4 | yes | 16.7s |

**총 API 호출: 4건**
**총 소요시간: ~61초**

---

## 4. Intent별 구조 검증

### eligibility (severance-pay)
- H2: 지급 대상, 근로시간 조건, 제외 대상, 계산 방법, FAQ
- intent 일치: YES (대상/조건 중심)
- PASS

### howto (weekly-holiday-allowance)
- H2: 이용 절차, 계산 예시, 주의사항, FAQ
- intent 일치: YES (절차/방법 중심)
- PASS

### documents (severance-pay-documents)
- H2: 필수 서류 목록, 서류 발급 방법, 제출 기한 및 절차, 주의사항, FAQ
- intent 일치: YES (서류 중심)
- PASS

### calculator (four-insurances)
- H2: 계산 원리, 지급 조건, 주의사항, FAQ
- intent 일치: YES (계산 중심, 실제 요율 포함)
- PASS

---

## 5. 품질 전수검수

| 항목 | eligibility | howto | documents | calculator |
|------|-------------|-------|-----------|------------|
| H1=0 (정상) | OK | OK | OK | OK |
| H2 >= 2 | 5 | 4 | 5 | 4 |
| FAQ | yes | yes | yes | yes |
| 도입부 | yes | yes | yes | yes |
| intent match | YES | YES | YES | YES |
| placeholder | none | none | none | none |
| 반복 문장 | 없음 | 없음 | 없음 | 없음 |

**주의**: H1=0은 정상. `generate_article()`이 body만 반환하고, `site_generator.py`가 H1을 추가함.

---

## 6. DB 불변성

| 항목 | 작업 전 | 작업 후 | 결과 |
|------|---------|---------|------|
| DB hash | `33e10f342b7fd81da7f9806864e0eccb` | `33e10f342b7fd81da7f9806864e0eccb` | UNCHANGED |
| Golden 10 hash | 10건 기록 | 10건 동일 | UNCHANGED |
| calculators 테이블 | 변경 없음 | 변경 없음 | UNCHANGED |
| articles 테이블 | 변경 없음 | 변경 없음 | UNCHANGED |

---

## 7. 격리 검증

| 항목 | 결과 |
|------|------|
| calculators.article_content write | **0건** |
| articles table write | **0건** |
| WordPress REST API | **0건** |
| Image API | **0건** |
| Scheduler 시작 | **없음** |
| production output 수정 | **없음** |
| isolated output만 생성 | **YES** |

---

## 8. Regression

```
945 passed, 4 skipped in 102.58s
```

이전 기준(945 passed, 4 skipped)과 동일. **회귀 없음**.

---

## 9. 출력 위치

```
data/reproduction/golden10_ai/
    severance-pay/severance-pay_eligibility_ai.html
    severance-pay/severance-pay_eligibility_ai_meta.json
    weekly-holiday-allowance/weekly-holiday-allowance_howto_ai.html
    weekly-holiday-allowance/weekly-holiday-allowance_howto_ai_meta.json
    severance-pay-documents/severance-pay-documents_documents_ai.html
    severance-pay-documents/severance-pay-documents_documents_ai_meta.json
    four-insurances/four-insurances_calculator_ai.html
    four-insurances/four-insurances_calculator_ai_meta.json
```

---

## 10. Checklist

- [x] 실제 AI 4개 대표 생성 완료
- [x] eligibility PASS
- [x] howto PASS
- [x] documents PASS
- [x] calculator PASS
- [x] intent 전달 PASS
- [x] isolated output만 생성
- [x] Golden 10 원본 변경 0
- [x] DB 변경 0
- [x] Calculator line 변경 0
- [x] Scheduler 자동 실행 없음
- [x] WordPress 호출 0
- [x] Image 호출 0
- [x] API key 노출 0
- [x] Regression 이상 없음

---

## 11. 다음 단계

1. **나머지 6건 AI 생성** — 10/10 전체 AI 경로 검증
2. **Scheduler Blog line ON** — 실제 자동 실행 연결
3. **Golden 10 스냅샷 갱신** — AI 생성 결과를 기준으로 스냅샷 확장
4. **品質 기준 고정** — intent별 품질 게이트 설정
