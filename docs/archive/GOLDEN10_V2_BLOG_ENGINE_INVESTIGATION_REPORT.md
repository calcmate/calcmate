# Golden 10 V2 Blog Engine Investigation Report

## 1. Golden 10 Source

10건의 authoritative source: `docs/GOLDEN10_CONTENT_STRUCTURING_REPORT.md`

| # | slug | intent | content identity |
|---|------|--------|------------------|
| 1 | severance-pay | eligibility | (severance-pay, eligibility) |
| 2 | weekly-holiday-allowance | howto | (weekly-holiday-allowance, howto) |
| 3 | unemployment-benefit | eligibility | (unemployment-benefit, eligibility) |
| 4 | four-insurances | calculator | (four-insurances, calculator) |
| 5 | annual-leave-allowance | howto | (annual-leave-allowance, howto) |
| 6 | severance-pay-documents | documents | (severance-pay, documents) |
| 7 | 육아휴직_급여_계산기 | eligibility | (육아휴직_급여_계산기, eligibility) |
| 8 | 연말정산_환급액_계산기 | calculator | (연말정산_환급액_계산기, calculator) |
| 9 | unemployment-benefit-howto | howto | (unemployment-benefit, howto) |
| 10 | four-insurances-documents | documents | (four-insurances, documents) |

---

## 2. Current Generation Path

현재 실제 생성 경로:

```
scheduler.py (execute_due_post)
  → calculator_pipeline.py (run_calculator_once)
    → CalculatorCollector.collect() [DB: calculators 테이블]
    → score_keywords()
    → for each keyword:
      → generate_seo()
      → generate_faq()
      → _write_article() [고정 7-H2 템플릿, intent 미사용]
      → art_repo.save() [articles 테이블에 저장]
```

**사이트 생성 경로:**

```
app_generator.py
  → calculators 테이블의 article_content 읽기
  → HTML 렌더링
  → data/workspace/_site/ 출력
```

**핵심**: 파이프라인은 `articles` 테이블에 저장하고, 사이트는 `calculators` 테이블의 `article_content`를 읽는다. 서로 다른 테이블.

---

## 3. V2 Blog Engine

| 구성요소 | 파일 | 존재 | 실행 가능 | 호출됨 | 상태 |
|----------|------|------|-----------|--------|------|
| `__init__.py` | `content/blog/__init__.py` | ✅ | ❌ | ❌ | **STUB** — "stub, 미호출" |
| `prompt.py` | `content/blog/prompt.py` | ✅ | ❌ | ❌ | **STUB** — NotImplementedError |
| `template.py` | `content/blog/template.py` | ✅ | ❌ | ❌ | **STUB** — NotImplementedError |
| `writer.py` | `content/blog/writer.py` | ✅ | ❌ | ❌ | **STUB** — NotImplementedError |

### 상세

**`content/blog/prompt.py`**:
```python
def get_blog_article_prompt(post: dict, intent: str = None) -> tuple:
    raise NotImplementedError("blog prompt engine not yet implemented")
```

**`content/blog/writer.py`**:
```python
def generate_blog_article(cfg: dict, post: dict, intent: str = None) -> str:
    raise NotImplementedError("blog writer engine not yet implemented")
```

**`content/blog/template.py`**:
```python
def build_blog_html(post: dict) -> str:
    raise NotImplementedError("blog template engine not yet implemented")
```

**`content/blog/__init__.py`**:
```python
# content.blog — 블로그 콘텐츠 엔진 (stub, 미호출)
```

**결론**: V2 Blog Engine은 **설계만 존재하며 구현되지 않았다.** 모든 함수가 NotImplementedError를 발생시킨다.

---

## 4. Intent

### 4-1. intent 지원 코드 존재 여부

| 위치 | intent 지원 | 상태 |
|------|-------------|------|
| `content/calculator/prompt.py` | ✅ eligibility/documents/howto/calculator 분기 | **실행 가능** |
| `content/calculator/writer.py` | ✅ intent 파라미터 전달 | **실행 가능** |
| `modules/calculator_pipeline.py` | ❌ `_write_article()`가 intent 미사용 | **연결 안됨** |
| `content/blog/prompt.py` | ✅ intent 파라미터 시그니처 존재 | **STUB** |
| `content/blog/writer.py` | ✅ intent 파라미터 시그니처 존재 | **STUB** |

### 4-2. Golden 10 intent 데이터 위치

| slug | intent | DB intent 필드 | slug 매핑 | 코드 상수 | 생성라인 전달 |
|------|--------|---------------|-----------|-----------|--------------|
| severance-pay | eligibility | NULL | ❌ | ❌ | ❌ |
| weekly-holiday-allowance | howto | NULL | ❌ | ❌ | ❌ |
| unemployment-benefit | eligibility | NULL | ❌ | ❌ | ❌ |
| four-insurances | calculator | NULL | ❌ | ❌ | ❌ |
| annual-leave-allowance | howto | NULL | ❌ | ❌ | ❌ |
| severance-pay-documents | documents | NULL | ✅ (slug에 "documents") | ❌ | ❌ |
| 육아휴직_급여_계산기 | eligibility | NULL | ❌ | ❌ | ❌ |
| 연말정산_환급액_계산기 | calculator | NULL | ❌ | ❌ | ❌ |
| unemployment-benefit-howto | howto | NULL | ✅ (slug에 "howto") | ❌ | ❌ |
| four-insurances-documents | documents | NULL | ✅ (slug에 "documents") | ❌ | ❌ |

**intent 데이터는 `GOLDEN10_CONTENT_STRUCTURING_REPORT.md`에만 존재한다.** DB, 코드, slug 매핑 어디에도 formal하게 기록되지 않았다.

---

## 5. Example Context

| slug | example_context | source | generator 전달 | article 반영 |
|------|----------------|--------|----------------|-------------|
| severance-pay | 없음 | — | ❌ | ❌ |
| weekly-holiday-allowance | 없음 | — | ❌ | ❌ |
| unemployment-benefit | 없음 | — | ❌ | ❌ |
| four-insurances | 없음 | — | ❌ | ❌ |
| annual-leave-allowance | 없음 | — | ❌ | ❌ |
| severance-pay-documents | 없음 | — | ❌ | ❌ |
| 육아휴직_급여_계산기 | 없음 | — | ❌ | ❌ |
| 연말정산_환급액_계산기 | 없음 | — | ❌ | ❌ |
| unemployment-benefit-howto | 없음 | — | ❌ | ❌ |
| four-insurances-documents | 없음 | — | ❌ | ❌ |

**example_context는 Golden 10에 존재하지 않는다.**

---

## 6. SSOT

| slug | SSOT | source | generator 전달 | article 반영 |
|------|------|--------|----------------|-------------|
| severance-pay | ✅ | `_load_legal_basis()` → `registry_loader` | ⚠️ 파이프라인에서 `_legal_basis_block()`으로 전달 | ✅ (법적 근거 인용) |
| weekly-holiday-allowance | ✅ | 동일 | ⚠️ 동일 | ✅ |
| unemployment-benefit | ✅ | 동일 | ⚠️ 동일 | ✅ |
| four-insurances | ✅ | 동일 | ⚠️ 동일 | ✅ |
| annual-leave-allowance | ✅ | 동일 | ⚠️ 동일 | ✅ |
| severance-pay-documents | ⚠️ | base와 동일 | ❌ (파이프라인이 document intent 미지원) | ❌ |
| 육아휴직_급여_계산기 | ✅ | 동일 | ⚠️ 동일 | ✅ |
| 연말정산_환급액_계산기 | ✅ | 동일 | ⚠️ 동일 | ✅ |
| unemployment-benefit-howto | ⚠️ | base와 동일 | ❌ (파이프라인이 howto intent 미지원) | ❌ |
| four-insurances-documents | ⚠️ | base와 동일 | ❌ (파이프라인이 document intent 미지원) | ❌ |

---

## 7. Scheduler

실제 호출 체인:

```
scheduler.py: execute_due_post(cfg, sched, entry, run_once_fn)
  → run_once_fn(cfg, max_count=1)
    → calculator_pipeline.py: run_calculator_once(cfg, max_count=1)
      → CalculatorCollector.collect()
      → for each keyword:
        → generate_seo()
        → generate_faq()
        → _write_article()  ← 고정 템플릿, intent 미사용
        → art_repo.save()
```

**V2 Blog Engine은 이 호출 체인에 존재하지 않는다.**

---

## 8. Overwrite Risk

### 현재 calculator pipeline 실행 시:

| 대상 | 위험도 | 근거 |
|------|--------|------|
| `calculators` 테이블의 `article_content` | **SAFE** ✅ | 파이프라인은 `articles` 테이블에 저장 |
| `articles` 테이블 | 없음 | 새로 생성됨 (기존 데이터와 무관) |
| 사이트 출력 (`_site/`) | **SAFE** ✅ | `calculators.article_content`에서 읽음 |
| Golden 10 구조화 결과 | **SAFE** ✅ | `calculators.article_content`에 저장되어 있음 |

**파이프라인을 실행해도 Golden 10 article_content는 덮어쓰여지지 않는다.**

단, 파이프라인이 `articles` 테이블에 새 레코드를 생성할 수 있으며, 이는 별도 데이터다.

### 사이트 재생성 시:

`_rebuild_site.py` 또는 `app_generator.py`가 실행되면:
- `calculators.article_content`를 읽어 사이트 페이지 생성
- Golden 10 article_content가 그대로 사용됨
- **SAFE** ✅

---

## 9. Phase5 Design vs Current Implementation

| 구성요소 | 설계 (Phase5) | 현재 구현 | 연결 상태 |
|----------|---------------|-----------|-----------|
| ContentRequest | ✅ 설계됨 | ⚠️ `CalculatorCollector`로 대체 | 부분 연결 |
| intent | ✅ `prompt.py`에 4개 템플릿 | ❌ 파이프라인에서 미전달 | **미연결** |
| example_context | ✅ `writer.py`에 파라미터 | ❌ 파이프라인에서 미전달 | **미연결** |
| SEO | ✅ `generate_seo()` | ✅ 실행됨 | 연결 |
| article structure | ✅ intent별 H2 분기 | ❌ 고정 7-H2 | **미연결** |
| FAQ | ✅ `generate_faq()` | ✅ 실행됨 | 연결 |
| legal context | ✅ `_legal_basis_block()` | ✅ 실행됨 | 연결 |
| quality gates | ✅ `content_quality` | ✅ 실행됨 | 연결 |
| V2 Blog Engine | ✅ `content/blog/` | ❌ STUB (NotImplementedError) | **미구현** |

---

## 10. Final Verdict

**BLOCKED — V2 ENGINE EXISTS BUT NOT CONNECTED**

### 핵심 장애물

1. **V2 Blog Engine (`content/blog/`)**: 파일과 함수 시그니처는 존재하나 모든 구현이 STUB (NotImplementedError)
2. **파이프라인 intent 미연결**: `calculator_pipeline.py`의 `_write_article()`이 intent를 받지만 사용하지 않음
3. **intent DB 누락**: Golden 10의 intent가 DB에 기록되지 않음 (ALL NULL)
4. **example_context 미연결**: 파이프라인이 example_context를 전달하지 않음

### 안전성 확인

- ✅ 파이프라인 실행 시 Golden 10 article_content 덮어쓰기 위험 **없음**
- ✅ 사이트 출력은 `calculators.article_content`에서 읽음
- ✅ 보호 대상 변경 0건

---

## 11. 다음에 수정해야 할 것 (최소 범위)

### Option A: V2 Blog Engine 구현

1. `content/blog/writer.py`의 `generate_blog_article()` 구현
2. `content/blog/prompt.py`의 `get_blog_article_prompt()` 구현
3. `content/blog/template.py`의 `build_blog_html()` 구현
4. V2 Blog Engine을 스케줄러에 연결

### Option B: 기존 파이프라인에 intent 지원 추가 (더 빠름)

1. `calculator_pipeline.py`의 `_write_article()`에서 intent를 사용하도록 수정
2. Golden 10 10건의 intent를 DB에 설정
3. 재현성 테스트 실행

### Option C: 현재 상태 유지 (안전)

- 현재 Golden 10은 `_golden10_restructure.py`로 수동 생성됨
- 파이프라인은 article_content를 건드리지 않음
- 재현성 테스트는 별도 환경에서 intent와 함께 독립 실행

**가장 적은 변경으로 재현성을 확보하려면 Option B를 권장한다.**
