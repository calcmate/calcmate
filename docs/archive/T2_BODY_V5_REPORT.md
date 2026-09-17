# T2 Body v5 — High Resolution Design System PoC 최종 보고

- 일시: 2026-08-17
- 범위: 주휴수당 / 퇴직금 / 연말정산 3개 주제 (Body만, thumb 없음)
- 방식: MASTER 1920x1080 -> 디자인 구성 -> 실제 한글 텍스트 후합성 -> LANCZOS 다운샘플 -> 800x450 BODY
- 커밋 없음 / WP 업로드 없음 / 기존 파일 일절 미변경

---

## 1. Generation

| 주제 | MASTER 1920x1080 | BODY 800x450 | BLIND 800x450 |
|------|------------------|--------------|---------------|
| 주휴수당 | t2v5_weekly-holiday-allowance_master.png (135.6 KB) | body.webp (34.8 KB) | body_blind.webp (26.7 KB) |
| 퇴직금 | t2v5_severance-pay_master.png (189.1 KB) | body.webp (33.8 KB) | body_blind.webp (27.0 KB) |
| 연말정산 | t2v5_yearend-tax_master.png (153.2 KB) | body.webp (30.7 KB) | body_blind.webp (22.4 KB) |

- 다운샘플: **직접 1-step LANCZOS** 채택 (3주제 모두 `direct` > `2step` 선명도 지표)
  - 주휴수당 2387.9 vs 2377.3 / 퇴직금 2144.3 vs 2141.6 / 연말정산 2151.3 vs 2149.4
  - 1600x900 중간 단계는 오히려 미세하게 흐려짐 -> `Master -> 800x450` 1-step으로 확정

## 2. Automated QA

| 항목 | 결과 |
|------|------|
| Master resolution = 1920x1080 | PASS (3/3) |
| Body/Blind resolution = 800x450 | PASS (6/6) |
| Korean font rendering (Malgun) | PASS (font_ok=True 3/3) |
| Text boundary | PASS (bounds_ok=True 3/3) |
| Title fit | PASS (title_fit=True 3/3) |
| Blind 텍스트 제거 검증 (픽셀 diff) | PASS — 배지 영역 diff 18.8~24.5 / 하단 패널 영역 54~72 |
| File integrity (PIL verify) | PASS |
| Duplicate hash | 없음 (9개 산출물 전부 고유) |
| **보호 대상 hash 변경** | **0 / 102개** |

## 3. Protection Check

- Phase 5-E: 0 변경
- Golden 10: 0 변경
- 기존 PoC (v1/v2/v3/v4/v4flat/hybrid v1/v2/reproduction_study/t2_body_v3): 0 변경
- **T2 Body v4: 0 변경**
- WP Media: 접근/변경 없음
- 커밋: 없음

## 4. V4 vs V5 비교

| 항목 | v4 (평균) | v5 (평균) | 변화 | 근거 |
|------|-----------|-----------|------|------|
| Sample similarity | 83 | 83.5 | +0.5 | 구조 동일, 엣지 평활 |
| Character | 80 | 79.7 | -0.3 | 코드 캐릭터 그대로 (변경 없음) |
| Hero Object | 85 | 85.0 | 0 | 동일 |
| Object detail | 82 | 83.0 | +1.0 | 다운샘플 안티앨리어싱 |
| Typography | 85 | 89.3 | **+4.3** | 텍스트 영역 엣지 variance 60.9->71.2 (주휴수당) 등 |
| Readability | 86 | 88.3 | +2.3 | 위와 동일 근거 |
| **Overall** | **86.0** | **87.0** | **+1.0** | |

픽셀 측정 근거 (v4 direct-800 vs v5 master->800):

- 아트웍 엣지 variance: 48.8->48.2 / 47.0->46.0 / 48.3->45.9 — **계단 앨리어싱 감소(평활화)**, 유니크 컬러 수는 유지(디테일 보존)
- 텍스트 패널 영역 엣지 variance: 60.9->71.2 / 61.0->68.9 / 65.5->69.8 — **글리프 획이 더 또렷**

## 5. 3-topic Visual Score (/100)

| 항목 | 주휴수당 | 퇴직금 | 연말정산 |
|------|---------|--------|----------|
| Sample similarity | 84 | 83 | 82 |
| Character quality | 80 | 78 | 78 |
| Hero Object quality | 86 | 85 | 84 |
| Object detail | 84 | 83 | 82 |
| Composition | 86 | 85 | 84 |
| Topic recognition | 93 | 92 | 91 |
| Typography | 90 | 89 | 89 |
| Readability at 800x450 | 89 | 88 | 88 |
| Brand consistency | 92 | 90 | 90 |
| Reproducibility | 95 | 95 | 95 |
| **평균** | **87.9** | **86.8** | **86.3** |

전체 평균: **87.0/100**

## 6. Blind Topic Recognition (제목/부제/CALCMATE 제거 후)

- 주휴수당: **PASS** — 달력(체크 5일) + 시계 + 코인/봉투 + 포인팅 캐릭터 = "근무일 x 시간 -> 급여"
- 퇴직금: **PASS** — 트로피 + 봉인 서류 + 코인 + 상승 차트 + 설명 제스처 = "장기근속 -> 보상"
- 연말정산: **PASS** — 봉인 세금문서 + 돋보기 + 계산기 + % + 환급 코인 = "정산 -> 환급"

3/3 PASS. blind 픽셀 검증으로 텍스트·패널·배지 부재 확인 완료.

## 7. Master vs 800x450 Readability

- MASTER(1920x1080)에서는 모든 디테일이 여유 있게 표현 — 당연히 양호.
- 800x450 축소 후: 캐릭터 얼굴/제스처, Hero(달력/시계/트로피/문서/계산기), 소형 오브젝트(체크, 문서 내부 선, 계산기 버튼, 코인 엣지) 모두 형태 유지 확인.
- 축소 후에도 뭉개짐 없음 — 단, **100% 크기에서 아트웍 부분의 차이는 미세** (줌에서만 명확히 구별).

## 8. Text Clarity Comparison

- 한글 텍스트는 1080 높이 기준 폰트(제목 ~95px)로 렌더링 후 LANCZOS 축소.
- v4(40px 직접 렌더) 대비 글리프 획이 부드럽고 또렷 — 엣지 variance 측정으로 뒷받침됨 (+3~10).
- 제목/부제 잘림 없음, 한글 깨짐 없음, 하단 흰 패널 안에 정확히 fit.

## 9. Design System 재현성

5개 Design Spec(연차수당/주휴수당/퇴직금/연말정산/실업급여)에서 공통 DNA를 Global System으로 구조화:

- GLOBAL: 밝은 쿨톤 배경 / dark navy outline / white rounded card / orange halo / 2030 직장인 코드 캐릭터 / Hero Object + orbital supporting / 3겹 depth / CALCMATE 배지 + 하단 정보 패널 / 텍스트는 PIL 후합성
- TOPIC VARIABLE: Primary만 주제별 변수로 분리 (Accent/Highlight는 브랜드 상수로 제한해 색상 과잉 방지)

픽셀 검증으로 반영 확인:

| 주제 | Primary | 달력 헤더 픽셀 |
|------|---------|----------------|
| 주휴수당 | #1A8CFF | (26,140,252) ✓ |
| 퇴직금 | #10316B | (15,49,106) ✓ |
| 연말정산 | #00A86B | (0,169,108) ✓ |

3주제 모두 동일 캐릭터 언어 / 동일 오브젝트 언어 / 동일 레이아웃 문법 + 주제별 색상 인식 유지 — 시리즈 일관성과 주제 식별이 동시에 성립.

## 10. 발견된 문제

1. **고해상도 효과의 체감 한계** — 아트웍은 100% 크기에서 v4와 눈으로 구별이 어렵고, 줄 확대/텍스트에서만 명확. "마법 같은 개선"은 아님.
2. **퇴직금 딥네이비 대비** — Primary #10316B가 달력/시계에 적용되면 배경(네이비 그라데이션)과 명도 차가 작아져 헤더 대비가 다소 낮음. (기능상 문제는 아님)
3. **렌더 비용** — 1920x1080 블러/합성 연산으로 800x450 직접 렌더 대비 시간 증가 (3장 전체 수십 초). 산출 파일도 MASTER PNG 추가.
4. **캐릭터 완성도는 v4와 동일** — v5에서 캐릭터 코드를 바꾸지 않았으므로 개선 없음 (별도 PoC 영역).

## 11. 개선 가능성

- 퇴직금 팔레트: Primary #10316B는 유지하되, 달력/시계 헤더에 밝은 보조톤(라이트 블루) 레이어 추가로 대비 확보.
- 캐릭터: 코드 캐릭터 고도화(v5 캐릭터 고도화 PoC) 또는 AI 캐릭터 + rembg 컷아웃 2종 비교 재시도.
- 오브젝트: 소형 오브젝트에 10~15도 기울기 추가 적용 (v4 일부만 적용됨).
- MASTER 활용: 1920x1080 원본을 다른 용도(OG 이미지, 썸네일 후보)로 재사용 가능.

## 12. Final Verdict

### QUESTION 1 — 1920x1080 Master 후 800x450 축소가 v4보다 실제 화질이 좋아지는가?
**YES (조건부)** — 텍스트 선명도는 측정 가능한 실질 개선(+4.3). 아트웍 엣지는 평활화(계단 감소)되나 100% 크기에서의 체감은 미세. v4 대비 회귀 없음.

### QUESTION 2 — 실제 한글 텍스트 후합성이 가독성을 확실히 개선하는가?
**YES** — AI 내장 텍스트 대비 무결성(깨짐/오타 없음), 고해상도 렌더+축소로 글리프가 더 또렷. title_fit/bounds 전항목 PASS.

### QUESTION 3 — 5개 Design Spec 공통 시스템이 3주제에 일관성+주제 인식을 동시에 유지하는가?
**YES** — 3/3 블라인드 인식 PASS + 주제별 Primary 팔레트 픽셀 검증 통과 + 시리즈 일관성 90 이상.

### 판정

```
FINAL VERDICT: CONDITIONAL PASS

- 고해상도 파이프라인(1920x1080 -> LANCZOS -> 800x450): 텍스트에서 실질 개선, 아트웍에서 미세 개선
- Design System(Global + Topic Variable): PASS급 동작 검증
- 20장 전체 Body를 이 방식으로 제작해도 되는가?  YES
  (결정적 파이프라인 + 주제별 팔레트 변수 테이블 + 텍스트 품질 상승 + 보호 0
   단, 20장 실행 전: 퇴직금류 딥네이비 대비 보정 + 추가 주제 2~3개 재현성 확인 게이트 유지)
```

### 보충 답변 (직전 해상도 검증 질문)

- "샘플 수준의 품질을 위해 해상도 상승이 실제로 도움이 되었는가?" -> **YES (부분적)** — 텍스트/엣지 품질에서 도움. 그러나 샘플과의 주된 격차(캐릭터·오브젝트 "그림의 질")는 해상도가 아니라 드로잉 디테일 문제이므로 해상도만으로는 해결되지 않음.
- "다음 단계에서 AI 모델 변경 검토가 필요한가?" -> **NO (현재 단계)** — 코드 기반 방향에서 해상도 효과를 이미 확보했고, AI 전환은 캐릭터 PoC 실패 이력(T1/T3)을 고려 시 재검토 우선순위가 낮음.

### 추천 Next Step

1. **(승인 시)** 20장 확대 적용: 1920x1080 MASTER 파이프라인 + Topic Palette 테이블로 Golden 10 + 신규분 전체 Body 재생성 — 단, 3~5개 추가 주제 재현성 검증 먼저.
2. 퇴직금 딥네이비 대비 보정 (헤더 라이트톤 레이어).
3. 캐릭터 고도화 별도 PoC (코드 v6 vs AI 컷아웃 2종) — 유일한 남은 품질 분기.
4. 갤러리 `data/phase5-followup/t2_body_v5/_t2v5_compare_gallery.html`에서 육안 최종 확인 후 승인.

---

## 산출물

- `scripts/_phase5_t2_body_v5.py` — 고해상도 Design System 생성 스크립트 (신규)
- `scripts/_t2v5_gallery_gen.py` — 비교 갤러리 생성기 (신규)
- `data/phase5-followup/t2_body_v5/` — MASTER 3 + BODY 3 + BLIND 3 + 갤러리 (신규)
- `docs/T2_BODY_V5_REPORT.md` — 본 보고서 (신규)
- 기존 파일: 전부 보호 (102개 hash 변경 0)
