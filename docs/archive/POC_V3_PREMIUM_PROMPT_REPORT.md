# Premium Prompt v2 비교 실험 보고서 (PoC v3)

- 일시: 2026-08-17
- 범위: 주휴수당 / 퇴직금 / 연말정산 3장 (body)
- 산출물: `data/phase5-followup/poc_v3/poc3_{key}_body.webp`
- 비교 갤러리: `_poc_v3_abc_gallery.html` (A/B/C 9장)

---

## [Generation]

- 주휴수당: OK — `poc3_weekly-holiday-allowance_body.webp` (19.1KB)
- 퇴직금: OK — `poc3_severance-pay_body.webp` (18.0KB)
- 연말정산: OK — `poc3_yearend-tax_body.webp` (19.5KB)

## [Resolution]

- body: 800×450 (최종, LANCZOS downscale)
- source: **1024×576** — pollinations.ai가 요청 크기(1600×900 / 1280×720 시도)와 무관하게 1024×576으로 캡함.
  브리프 요건(1280×720 이상)은 서비스 제약으로 미달 → 전체 적용 시 고해상도 원본 확보 방안 필요.

## [Visual Quality]

- 기존 Phase 5-E: 사진풍(photo) 이미지 + AI 내장 텍스트. 사실적이나 일러스트 브랜드 느낌 약함.
- 현재 PoC(v1): 깔끔한 flat illustration + Pillow 텍스트. 정돈됐으나 평면적·제너릭.
- Premium Prompt v2: 리얼리스틱/시네마틱 + Pillow 텍스트. 깊이감·조명·재질 표현이 확연히 향상.

## [Comparison]

- 선명도: C ≈ A > B
- 디테일: C > B > A (재질, 반사, 레이어드 구성)
- 깊이감: C > B ≈ A (시네마틱 조명/전경-배경 분리)
- 주제 전달: B > C (flat은 개념 아이콘이 명확; C는 분위기 우선 — 주휴수당은 직관적, 퇴직금/연말정산은 은유적)
- 브랜드 일관성: B ≥ C (B는 3장 톤 통일, C는 연말정산이 과도하게 어두워 편차)
- 상업적 완성도: C > B > A
- 목표 샘플과의 유사 수준: C가 방향성상 가장 근접 (목표 샘플 원본과의 정밀 비교는 육안 대조 필요)

## [Text]

- 잘림: 없음 (전 장 title_fit=True)
- 한글: 정상 (Malgun Gothic 로드 확인, font_ok=True)
- fit: OK — 긴 제목(연말정산 환급액 계산기) 자동 축소 적용

## [Protection]

- 기존 20장 변경: 0 (hash 스냅샷 71개 파일 대조)
- 기존 PoC 변경: 0
- Golden 10 변경: 0
- WP Media 변경: 0

---

## [Final Verdict]

**B — CONDITIONAL**

- 프리미엄 방향(리얼리스틱/시네마틱/깊이감)은 현재 PoC 대비 명확한 개선이고 Q1/Q3/Q6는 충족.
- 단, ① 연말정산 1장이 과도하게 어두운 무드로 3장 톤 일관성(Q5)이 깨지고,
  ② 주제 전달(Q4)이 flat 대비 오히려 은유적으로 약해진 항목이 있음.
  ③ 서비스 해상도 캡(1024×576)으로 고해상도 요건 미달.

## [Recommendation]

다음 단계:
1. 프롬프트 1회 조정 — 공통 "밝고 따뜻한 상업용 조명(bright warm commercial lighting)" 강화 + 주제 은유 요소를 전경에 명시적으로 배치.
2. 동일 시드 계열로 3장 재생성 → A/B/C 재비교.
3. 조정 후 PASS 시 3~5장 추가 재현성 검증 (별도 승인 후에만 전체 적용).
