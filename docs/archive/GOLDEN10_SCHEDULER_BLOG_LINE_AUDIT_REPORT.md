# Golden 10 → Scheduler 블로그 라인 연결 전수검사 보고서

## 1. Executive Summary

**Final Verdict: PASS WITH WARNINGS**

Golden 10 블로그 콘텐츠 10건의 Scheduler 연결 가능성을 전수검사한 결과:

- **Dry-run: 10/10 PASS** — 모든 콘텐츠가 intent별 구조로 정상 생성
- **Overwrite Risk: HIGH RISK** — calculator_pipeline이 기존 article_content를 덮어쓸 가능성
- **Scheduler → Blog line: 미연결** — 현재 Scheduler는 calculator_pipeline만 호출
- **DB intent: 없음** — calculators 테이블에 intent 컬럼 부재

---

## 2. Scheduler 구조

### 현재 Scheduler 호출 체인

```
run_scheduler_loop(cfg, run_once_fn)
  → execute_due_post(cfg, sched, entry, run_once_fn)
    → run_once_fn(cfg, max_count=1)

run_once_fn은 resolve_publish_fn(cfg)에 의해 결정:
  - PUBLISH_MODE="calculator" (기본):
    → run_calculator_once (modules/calculator_pipeline.py)
  - PUBLISH_MODE="rss":
    → run_once (modules/main.py)
```

### 핵심 발견

Scheduler는 **오직 calculator_pipeline**만 호출한다.

`content/blog/writer.py`는 Scheduler 호출 체인에 **존재하지 않는다**.

---

## 3. Blog Line 구조

### 현재 blog adapter

| 파일 | 역할 | 상태 |
|------|------|------|
| `content/blog/__init__.py` | 패키지 선언 | ✅ 정상 |
| `content/blog/writer.py` | 콘텐츠 생성 (intent별 mock + AI 경로) | ✅ 정상 |
| `content/blog/prompt.py` | 프롬프트 어댑터 (calculator prompt 재사용) | ✅ 정상 |
| `content/blog/template.py` | HTML 조립 + FAQ JSON-LD | ✅ 정상 |

### blog adapter 특징

- **DB write 없음** — isolated output만 생성
- **intent 지원** — eligibility/howto/documents/calculator 4종
- **Scheduler와 독립** — 현재 어디서도 호출되지 않음

---

## 4. Calculator Line / Blog Line 경계

### Calculator Line (현재 운영)

```
Scheduler
  → calculator_pipeline.run_calculator_once()
  → _write_article() (고정 7-H2 템플릿, intent 무시)
  → DB UPDATE calculators.article_content
  → image_generator → publisher → WP 발행
```

### Blog Line (신규, 미연결)

```
[Scheduler] ──── ✗ 미연결 ──── content/blog/writer.py
                                     ↓
                              intent별 템플릿
                                     ↓
                              isolated output (DB 미저장)
```

### 경계 분리 상태

| 항목 | Calculator Line | Blog Line |
|------|----------------|-----------|
| Scheduler 연결 | ✅ 연결 | ❌ 미연결 |
| intent 지원 | ❌ 고정 7-H2 | ✅ 4종 intent |
| DB write | ✅ article_content | ❌ 없음 |
| WP 발행 | ✅ 있음 | ❌ 없음 |
| 이미지 생성 | ✅ 있음 | ❌ 없음 |

---

## 5. Scheduler 입력 데이터 계약

### 현재 Scheduler가 사용하는 입력

| 데이터 | 존재 | 전달 경로 | Blog line 전달 |
|--------|------|-----------|----------------|
| slug | ✅ | calculator.collector | ❌ |
| keyword | ✅ | calculator.collector | ❌ |
| SEO | ✅ | generate_seo() | ❌ |
| FAQ | ✅ | generate_faq() | ❌ |
| intent | ❌ | 없음 | ❌ |
| ContentRequest | ❌ | 없음 | ❌ |
| example_context | ❌ | 없음 | ❌ |

### 핵심 발견

**Scheduler는 intent를 어디서도 가져오지 않는다.**

현재 `calculator_pipeline._write_article()`에 `intent` 파라미터가 존재하지만:
1. Scheduler에서 intent를 전달하지 않음
2. `_write_article()`이 intent를 실제로 사용하지 않음 (고정 7-H2 템플릿)

---

## 6. Overwrite Risk 분석

### 현재 상태

```
calculator_pipeline._write_article()
  → DB UPDATE calculators.article_content
  → 항상 고정 7-H2 템플릿 사용
  → intent 파라미터 무시
```

### 위험 시나리오

**Scheduler가 calculator_pipeline을 실행하면:**

1. `run_calculator_once()` 호출
2. `_write_article()` 실행 (고정 7-H2)
3. `calculators.article_content` 덮어쓰기
4. **기존 Golden 10 intent별 구조 손실**

### 판정: HIGH RISK

- 기존 Golden 10 article_content가 고정 템플릿으로 덮어써질 가능성
- 복구 불가능 (원본 임의 저장 안 함)

### 안전 장치

현재 다음 조건이 충족되면 안전:

1. `MAX_ARTICLES_PER_CALCULATOR = 1` (기본값)
2. `has_quality_hold()`가 기존 article을 보유한 계산기를 스킵
3. `existing_by_calc` 중복 필터가 동일 계산기를 스킵

그러나:
- **재시도/replay 시** article_content가 덮어씌워질 수 있음
- **품질보류 해제 시** article_content가 새로 생성됨

---

## 7. Intent Source 확인

### 현재 intent가 존재하는 위치

| 위치 | 존재 | 형식 |
|------|------|------|
| GOLDEN_10 (scripts/_golden10_repro.py) | ✅ | 코드 내 상수 |
| GOLDEN_10 보고서 (.md) | ✅ | 문서 |
| DB (calculators.intent) | ❌ | 컬럼 없음 |
| ContentRequest | ❌ | 구조 없음 |
| Scheduler 설정 | ❌ | 없음 |

### 핵심 발견

**Intent는 오직 코드의 GOLDEN_10 상수에만 존재한다.**

DB에도, Scheduler에도, ContentRequest에도 intent가 없다.

---

## 8. 1건 Dry-Run 결과 (severance-pay / eligibility)

| 항목 | 결과 |
|------|------|
| ContentRequest 생성 | ✅ JSON 저장 |
| Blog adapter 호출 | ✅ 성공 |
| intent = eligibility | ✅ 확인 |
| H1 = 0 (DB 스타일) | ✅ 정상 (site template이 H1 추가) |
| H2 ≥ 3 | ✅ 5개 |
| FAQ 존재 | ✅ `<dl>` 형식 |
| 계산기 링크 | ✅ 존재 |
| intent별 H2 | ✅ "지급 대상", "근로시간 조건", "제외 대상" 등 |
| 기존 DB 변경 | ✅ 0건 |
| WordPress 호출 | ✅ 0건 |
| Image 호출 | ✅ 0건 |

---

## 9. Golden 10 전체 Dry-Run 결과 (10건)

| slug | intent | DB | H1 | H2 | FAQ | Link | IH2 | Status |
|------|--------|-----|-----|-----|-----|------|-----|--------|
| severance-pay | eligibility | Y | 0 | 5 | Y | Y | Y | **PASS** |
| weekly-holiday-allowance | howto | Y | 0 | 4 | Y | Y | Y | **PASS** |
| unemployment-benefit | eligibility | Y | 0 | 5 | Y | Y | Y | **PASS** |
| four-insurances | calculator | Y | 0 | 4 | Y | Y | Y | **PASS** |
| annual-leave-allowance | howto | Y | 0 | 4 | Y | Y | Y | **PASS** |
| severance-pay-documents | documents | Y | 0 | 5 | Y | Y | Y | **PASS** |
| 육아휴직_급여_계산기 | eligibility | Y | 0 | 5 | Y | Y | Y | **PASS** |
| 연말정산_환급액_계산기 | calculator | Y | 0 | 4 | Y | Y | Y | **PASS** |
| unemployment-benefit-howto | howto | Y | 0 | 4 | Y | Y | Y | **PASS** |
| four-insurances-documents | documents | Y | 0 | 5 | Y | Y | Y | **PASS** |

**Total: 10/10 PASS**

---

## 10. DB 변경 여부

| 항목 | 결과 |
|------|------|
| DB hash before | `f631f4e07bfe1670ab9745f549e94bd7` |
| DB hash after | `f631f4e07bfe1670ab9745f549e94bd7` |
| DB changed | **NO — SAFE** |

---

## 11. 보호 대상 시스템

| 시스템 | 상태 | 변경 |
|--------|------|------|
| calculator computation | UNCHANGED | ✅ |
| calculator registry | UNCHANGED | ✅ |
| SSOT | UNCHANGED | ✅ |
| Scheduler | UNCHANGED | ✅ |
| WordPress connector | UNCHANGED | ✅ |
| image_pipeline | UNCHANGED | ✅ |
| Golden 10 원본 | UNCHANGED | ✅ |

---

## 12. Regression

| 항목 | 결과 |
|------|------|
| pytest tests/ | **907 passed, 3 skipped** |
| 이전 기준 | 907 passed, 3 skipped |
| Regression | **0건** |

---

## 13. Git 변경 목록

### 이번 작업으로 변경된 파일

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `content/blog/__init__.py` | M | blog adapter 패키지 (stub → adapter) |
| `content/blog/prompt.py` | M | blog 프롬프트 어댑터 |
| `content/blog/template.py` | M | blog HTML 템플릿 |
| `content/blog/writer.py` | M | blog writer 어댑터 |
| `scripts/_golden10_repro.py` | NEW | 재현성 테스트 스크립트 |
| `scripts/_golden10_scheduler_audit.py` | NEW |_scheduler 전수검사 스크립트 |

### 기존 미커밋 변경 (이전 작업)

- `data/phase5-3/` 삭제 (레거시 정리)
- `data/phase5-c/` 삭제 (레거시 정리)
- `data/outputs/` 삭제 (레거시 정리)
- 기타 레거시 파일 삭제

### 보호 대상 변경

**0건** — calculator_pipeline, scheduler, SSOT, DB 모두 변경 없음.

---

## 14. 최종 판정

### PASS 조건 체크리스트

- [x] Scheduler 구조 전수조사 완료
- [x] Blog line / Calculator line 경계 확인
- [x] intent 전달 경로 확인
- [x] ContentRequest 계약 확인
- [ ] Overwrite Risk SAFE → **HIGH RISK**
- [x] severance-pay dry-run PASS
- [x] Golden 10 dry-run 10/10 PASS
- [x] DB 변경 0
- [x] Golden 10 원본 변경 0
- [x] SSOT 변경 0
- [x] Calculator computation 변경 0
- [x] WordPress 호출 0
- [x] Image 호출 0
- [x] Regression PASS
- [x] Git 보호 PASS

### Final Verdict

**PASS WITH WARNINGS**

Dry-run은 10/10 통과했으나, **Overwrite Risk가 HIGH RISK**로 판정됨.

---

## 15. 발견된 문제와 권장 사항

### Problem 1: Overwrite Risk

**현재**: `calculator_pipeline._write_article()`이 항상 고정 7-H2 템플릿을 사용하여 `calculators.article_content`를 덮어씀.

**위험**: Scheduler가 calculator_pipeline을 replay하면 Golden 10의 intent별 구조가 손실됨.

**권장 해결**:
1. `calculator_pipeline._write_article()`에 `intent` 분기 추가
2. 또는 `blog adapter`를 별도 entrypoint로 연결
3. 또는 기존 article_content가 있으면 skip하는 보호 모드 추가

### Problem 2: Intent 미전달

**현재**: Scheduler가 intent를 어디서도 가져오지 않음.

**위험**: Scheduler가 intent를 모른 채 블로그 콘텐츠를 생성하면 고정 템플릿 사용.

**권장 해결**:
1. DB에 intent 컬럼 추가
2. 또는 GOLDEN_10 contract를 기반으로 intent 매핑
3. 또는 ContentRequest에 intent 필드 추가

### Problem 3: Blog line 미연결

**현재**: `content/blog/writer.py`가 어디서도 호출되지 않음.

**위험**: 재현성 테스트만 가능하고, 실제 Scheduler에서 사용 불가.

**권장 해결**:
1. Scheduler에 blog mode 추가 (`PUBLISH_MODE="blog"`)
2. 또는 `resolve_publish_fn`에 blog adapter 연결
3. 또는 별도 blog scheduler entrypoint 생성

---

## 16. 다음 단계 권장

### 우선순위 1: Overwrite 방지 (최소 변경)

```python
# calculator_pipeline.py의 _write_article()에서:
# 기존 article_content가 있으면 skip (덮어쓰기 방지)
if calc.get("article_content"):
    LOG.info("기존 article_content 보존 — skip")
    return calc["article_content"], 0
```

### 우선순위 2: Intent 주입

```python
# scheduler가 intent를 전달할 수 있는 구조
# 또는 GOLDEN_10 contract를 기반으로 slug → intent 매핑
GOLDEN_10_INTENTS = {
    "severance-pay": "eligibility",
    "weekly-holiday-allowance": "howto",
    ...
}
```

### 우선순위 3: Blog line 연결

```python
# main.py의 resolve_publish_fn에 blog mode 추가
if mode == "blog":
    from content.blog.writer import generate_blog_article
    return generate_blog_article
```

---

## 17. 결론

현재 Golden 10 블로그 콘텐츠는:

1. **blog adapter로 재현 가능** ✅ (10/10 dry-run PASS)
2. **Scheduler와는 미연결** ⚠️ (calculator_pipeline만 호출)
3. **Overwrite Risk 존재** ⚠️ (고정 템플릿으로 덮어쓰기 가능)
4. **Intent 미전달** ⚠️ (DB에도 Scheduler에도 없음)

Scheduler 연결을 완료하려면:

1. `calculator_pipeline`에 intent 분기 또는 article 보호 모드
2. DB에 intent 컬럼 추가
3. Scheduler에 blog entrypoint 연결

이 작업들은 **별도 후속 작업**으로 수행해야 하며,
현재 상태에서 Scheduler를 실행하면 **Golden 10이 손상될 위험**이 있다.

---

## 보고서 위치

`docs/GOLDEN10_SCHEDULER_BLOG_LINE_AUDIT_REPORT.md`
