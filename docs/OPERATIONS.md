# OPERATIONS — 운영 절차

> 계산기 신규 추가부터 발행·관찰·수정까지의 운영 흐름. 대시보드(React+FastAPI, 루트 `start_dashboard.bat`)로 운영한다.
> Calculator는 자동 Scheduler 없이 **수동 생성**(App Factory/계산기 관리)이 기준이며,
> 예약 자동 발행이 필요한 라인은 Blog(Golden 10 → Blog Schedule → WordPress)뿐이다.

## 1) 신규 계산기 추가

```
대시보드 🧮 Calculator ▸ App Factory
  → 이름(한글)/카테고리/설명 입력 → 🏭 자동 생성 → 미리보기
  → 영문 slug 입력(예: annual-tax-settlement) → 💾 저장
결과: calculators 시트 + registry_auto.yaml 엔트리 자동 생성(legal 비어있음, HOLD 상태)
```

상세: [APP_FACTORY.md](APP_FACTORY.md).

## 2) legal 입력 (발행 전제 조건)

신규 계산기는 legal이 없어 발행이 **품질보류(HOLD)**된다. 발행하려면 사람이 법적 근거를 검증해 입력한다.

```
docs/legal_basis.draft.yaml 편집 — 해당 slug에 law/article/authority 등 입력
  ⚠️ legal은 반드시 사람이 검증(law.go.kr 등). AI에게 조사시키면 환각 위험.
  ⚠️ registry_auto.yaml이 아니라 legal_basis.draft.yaml에 적는다("승격").
```

입력 후 다음 실행부터 자동으로 정상 파이프라인(G8 포함)에 진입한다.

## 3) 발행

```
대시보드 🧮 계산기 관리(또는 🏠 운영센터 빠른 실행) ▸ "🧮 계산기 생성" → run_calculator_once() 1회 실행
또는 CLI: python main.py --calculator-id <id>
```

Calculator는 자동 Scheduler가 제거되어 위 수동 트리거로만 실행된다(예약 자동 발행 없음).

파이프라인: writer 생성 → Gate(G1~G8) → Score(S1~S6) → PASS/WARN이면 WordPress 발행,
REWRITE면 재생성(최대 MAX_TOTAL_RETRY), 한도 초과 시 품질보류.

## 4) 관찰

| 볼 곳 | 무엇 |
|-------|------|
| 대시보드 📝 Content ▸ 발행 목록 | 발행완료/검수대기/수정됨/품질보류 상태, quality_score |
| 마스터_DB(articles 시트) | quality_* 필드, history(publish/quality_hold 등) |
| 대시보드 📡 Logs | 오류·실시간 로그·헬스체크 |
| Telegram | 발행 성공 · 모든 후보 HOLD · 후보 소진 알림(이벤트 ON 시) |
| 대시보드 📝 Blog Schedule | Blog 예약 발행 설정/상태(Calculator는 자동 스케줄 없음 — 발행 목록에서 결과 확인) |

**품질보류(HOLD)가 뜨면**: legal 미검증(신규 계산기 legal 미입력)인지, 아니면 Score 반복 실패인지 구분.
- legal 미검증 → 2)번 legal 입력
- Score 반복 실패 → 해당 계산기 콘텐츠/프롬프트 점검

## 5) 수정

- **글 수정**: 대시보드 발행 목록 ✏️ 수정(publisher.update_post) → 상태 "수정됨"
- **글 삭제/복원**: 🗑 삭제(휴지통) / 🗑️ 휴지통 탭에서 복원
- **계산기 legal 정정**: legal_basis.draft.yaml 편집 → 재발행 시 반영
- **품질보류 재도전**: writer 프롬프트가 바뀌면(prompt_version 변경) 자동 재평가. legal-HOLD는 legal 채우면 자동 해제

## 참고 — 예산/비용

`DAILY_AI_BUDGET`/`MONTHLY_AI_BUDGET` 초과 시 파이프라인 중단(Cost Manager). 대시보드 💰 Revenue에서 모니터.

## 참고 — 알아둘 운영 특성

- `MAX_ARTICLES_PER_CALCULATOR`(기본 1): 계산기당 활성 발행글 상한. 도달 시 그 계산기는 "중복"으로 스킵.
- 4대보험 계산기는 요율(국민연금 4.5%/건강 3.545%/고용 0.9%)이 formula에 하드코딩 → **연 1회 formula 코드
  갱신 필요**(콘텐츠 갱신과 별개). registry에 `content.evergreen: false / update_cycle: yearly`로 표식됨.
