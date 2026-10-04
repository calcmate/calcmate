# 품질보류 재평가 (Quality HOLD Re-evaluation)

계산기 SEO 글이 품질검수(Gate→Score)에서 반복 실패하면 **품질보류(HOLD)** 상태로 저장되어
발행되지 않는다. 이후 운영자가 legal_basis / 품질 게이트 / writer 프롬프트를 개선하면,
**옛 HOLD가 현재 기준에서도 여전히 HOLD인지 자동으로 재평가**되어 통과 가능하면 다시 발행된다.

이 문서는 그 재평가 시스템의 설계를 기록한다.
관련 코드: `modules/calculator_pipeline.py`, `repositories/article_repository.py`, `main.py`(CLI), `dashboard.py`(버튼 — 작성 당시 legacy Streamlit, 현재 삭제됨).

---

## 1. quality_signature — 재평가의 기준

`_quality_signature(cfg, calc)` (calculator_pipeline.py). 계산기 1개당 하나의 sha1[:8] 해시.
**품질 판정에 영향을 주는 모든 입력**을 합쳐 해시한다:

| 구성 요소 | 출처 | 왜 포함하나 |
|---|---|---|
| writer 프롬프트 | `prompts/calculator_writer_prompt.txt` | 본문 생성 방식이 바뀜 |
| 품질 게이트 규칙 | `cfg.QUALITY_GATE` (G1~G8 임계) | 통과 기준이 바뀜 |
| 스코어 임계 | `cfg.QUALITY_SCORE` (PASS/WARN) | 발행 판정선이 바뀜 |
| G7 금지문체 | `cfg.AI_STYLE_BLOCKLIST` | 문체 게이트가 바뀜 |
| 해당 계산기 legal_basis | registry의 판정영향 필드(`_LEGAL_SIG_FIELDS`) | G8/writer 근거가 바뀜 |

- **slug 단위**다. 한 계산기의 legal을 고치면 그 계산기의 서명만 바뀌고, 다른 계산기는 영향 없음
  (불필요한 전체 재생성/비용 방지).
- legal_basis는 표시용 필드(name/emoji 등)를 제외하고 판정에 실제 쓰이는 필드만 넣는다
  (`law, article, related_articles, authority, forbidden_articles, forbidden_phrases, needs_human_legal, writer_note`).

HOLD가 생성될 때 이 서명이 그 글 행의 `quality_prompt_version` 컬럼에 저장된다.

---

## 2. 언제 재평가되는가

재평가를 위한 **별도 트리거 코드는 없다.** 서명을 확장한 것만으로 기존 게이트가 자동 수행한다.

파이프라인 후보 순회 중 각 계산기에서:

```
현재 서명 sig = _quality_signature(cfg, calc)
if has_quality_hold(cid, prompt_version=sig):   # 저장 서명 == 현재 서명인 HOLD가 있으면
    hold_skip → 스킵                            #   재도전 무의미 (기준 안 바뀜)
else:
    통과 → 재생성 시도                           #   저장 서명 != 현재 서명 → 재도전
```

- **자동(기본):** legal/게이트/프롬프트를 고치면 서명이 바뀌어, 다음 스케줄 실행에서 그 계산기가
  자동으로 재도전 대상이 된다. 운영자 개입 불필요.
- **수동(운영 도구):** 지금 즉시 확인/실행하고 싶을 때.
  - CLI: `python main.py --reevaluate-hold [--apply] [--only-slug <slug>]`
  - 대시보드: Calculator Builder → "♻️ 품질보류 재평가" (리포트 / 즉시 실행)

---

## 3. 재평가 분류 — released / blocked / already_published / legal_pending

`reevaluate_holds(cfg, apply, only_slug)`가 각 품질보류 행을 아래로 분류한다:

| 분류 | 조건 | 의미 / 처리 |
|---|---|---|
| **released** | 저장 서명 ≠ 현재 서명 **AND** 아직 미발행(count_active < max) | 재도전 대상. `--apply` 시 재생성 |
| **blocked** | 저장 서명 == 현재 서명 | 기준 안 바뀜 → 유지(재시도 무의미) |
| **already_published** | 저장 서명 ≠ 현재 서명 **AND** 이미 발행됨(count_active ≥ max) | 재생성으로 이미 해소됨 → 옛 HOLD 정리 대상 |
| **legal_pending** | legal 미검증 sentinel(`legal_unverified`) HOLD | legal_basis 입력 필요(별도 경로, 서명 무관) |

> `--apply` 없이(dry-run)는 **리포트만** 하고 시트를 바꾸지 않는다(비용 0). `--apply`일 때만 아래 처리를 수행.

---

## 4. resolved(재처리완료) 처리 규칙 — 상태 정리

HOLD가 재생성으로 발행되면 **새 발행완료 행이 추가**되고, **옛 HOLD 행은 삭제하지 않고**
`상태값: 재처리완료`로 바꾸고 history를 남긴다. `ArticleRepository.resolve_holds_for_calculator()`.

- **삭제하지 않는 이유:** 감사(audit) 추적. 왜/언제 해소됐는지 이력이 남아야 원인 추적이 가능.
- 남기는 history 이벤트:
  ```json
  {"event":"quality_hold_released","at":"2026-07-08T23:01:41",
   "reason":"quality_signature_changed"|"already_published_on_reeval",
   "new_signature":"d8026b14","published_post_id":"31"}
  ```
- 정리가 일어나는 시점(둘 다):
  1. **파이프라인 발행 성공 시(자동):** 재생성이 실제 발행(`status==published`)되면, 같은 계산기의
     옛 품질보류 행을 그 자리에서 재처리완료로 정리(방금 발행한 새 행은 제외). → 앞으로는 잔존이 안 생김.
  2. **재평가 --apply 시(청소):** 과거에 이미 발행됐지만 옛 HOLD가 남아있는 경우(`already_published`)를
     재처리완료로 정리.
- `재처리완료`는 `INACTIVE_ARTICLE_STATUSES`에 포함 → 발행 카운트에서 제외되고, `품질보류`가 아니므로
  재평가 리포트/게이트에서 더 이상 잡히지 않는다(리포트 정확성 유지).

---

## 5. 새 행 생성 방식과 기존 HOLD 행의 관계

재생성은 기존 HOLD 행을 **수정**하지 않는다. 항상 **새 글 행을 생성(save)**한다.

```
품질보류 행 (옛 서명)          ← 삭제 안 함, '재처리완료'로 상태만 변경 (+history)
      │  재평가(서명 변경 감지)
      ▼
발행완료 행 (새 서명)          ← 새로 생성. wp_post_id / 발행URL 보유
```

- 한 계산기에 대해 시트에 최대 여러 행이 공존할 수 있으나, 상태로 구분된다:
  `발행완료`(현재 발행본) / `재처리완료`(해소된 옛 HOLD, 이력) / `품질보류`(아직 미해결).
- `count_active_articles`는 `발행완료`만 세고 나머지(품질보류/재처리완료)는 제외하므로,
  `MAX_ARTICLES_PER_CALCULATOR` 상한 판정과 중복(dup) 스킵이 정확히 유지된다.

---

## 6. 한계 / 후속 과제

- **재생성 성공을 보장하지 않는다.** 서명이 바뀌면 "재도전"할 뿐, 재생성 결과가 다시 REWRITE면
  새 HOLD가 생긴다(다른 실패 원인일 수 있음).
- **발행 성공 알림 미구현.** 재평가로 되살아나 발행돼도 현재 Telegram 알림은 없다(실패/HOLD/예산만 알림).
- legal 미검증(`legal_pending`)은 이 서명 재평가와 별개 경로다. legal_basis에 값을 채우면
  `_legal_unverified`가 False가 되어 게이트가 자동 통과한다.
