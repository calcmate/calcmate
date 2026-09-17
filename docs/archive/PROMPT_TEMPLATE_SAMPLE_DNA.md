# CalcMate 이미지 — 목표 샘플 디자인 DNA 역분석 & 프롬프트 템플릿

> 기준 샘플: Gemini 생성 "연말정산 가이드" 2패널 + "연차수당 가이드" 2패널 (16:9 썸네일 / 1:1 가이드)
> 용도: Phase 5 이미지 재생성(주휴수당 / 퇴직금 / 연말정산)의 Stage A 프롬프트 기준
> 원칙: 샘플 내용 복제가 아니라 **디자인 언어(스타일 시스템)** 재현. 텍스트는 AI가 만들지 않고 Pillow 후처리로 합성.

---

## 1. 샘플 역분석 (20항)

### 1) 전체 아트 스타일
한국형 "카드뉴스 / 블로그 썸네일" 편집 일러스트. flat 2D 벡터 + 인포그래픽 그리드의 하이브리드.
개별 오브젝트 그림이 아니라 **완성된 포스터/템플릿**처럼 보이는 상업용 디자인. 밝고 전문적, 유머 없음.

### 2) 일러스트/벡터/렌더링 특성
완전 flat 셰이딩. 오브젝트 = 단색 면 + 볼드 아웃라인. 그라데이션은 배경에만 극히 가볍게.
반사·광택·텍스처 없음. 톤 단계는 2~3단계(베이스/하이라이트/아웃라인)로 제한.

### 3) 색상 팔레트
- 배경: 라이트 블루 계열 (≈ #E8F4FE ~ #D6EAFE)
- 프라이머리: 로열 블루(≈ #2563EB) / 딥 네이비 헤더(≈ #1E3A8A)
- 액센트: 오렌지(≈ #F97316) — 원형 halo
- 서브: 그린(≈ #22C55E, 돈/확인), 레드(≈ #EF4444, X/중요 표시), 옐로우(≈ #FACC15, 스파클/코인)
- 카드: 화이트. 타이포: 네이비/블랙 + 화이트 아웃라인

### 4) 명도와 채도
고명도 · 중~고채도. 헤더 바를 제외한 어두운 영역 없음. 채도는 강하되 과포화 아님 —
파랑 계열이 전체 톤을 잡고, 오렌지/그린이 포인트로만 사용.

### 5) 조명과 그림자
조명 개념 없음. 오브젝트 아래 옅은 블루그레이 **flat cast shadow** 하나만 허용.
어두운 드롭 섀도/무드 조명 금지.

### 6) 입체감과 깊이
원근감 대신 **레이어 겹침(overlap)**으로 깊이 표현:
후면 오렌지 halo 원 → 중앙 캐릭터 → 전경 데스크/오브젝트. 3겹 구조.

### 7) 선의 특징
굵고 균일한 **둥근 아웃라인**(딥 네이비/블랙). 모든 모서리는 rounded.
날카로운 선 없음, 부드러운 곡선 위주.

### 8) 캐릭터 표현 방식
2~3등신 단순화 벡터 캐릭터. **흰 셔츠 + 네임텍 랜야드** (브랜드 일관성),
미소, 엄지척/포인팅 포즈. 단색 옷, 단순 팔/손.

### 9) 얼굴/인물 표현 방식
클로즈업 **전혀 없음** — 항상 중경~전신. 피부 단색 + 단순 눈(호/점) + 미소 라인.
밝고 친근한 표정. 손은 미트형(디테일 최소).

### 10) 주요 오브젝트 표현 방식
"미니어처 씬"급 아이콘 — 단순 아이콘이 아니라 읽을 거리 있는 오브젝트:
빨간 스프링 달력, $ 돈봉투/동전/자루, 문서+돋보기, 계산기, 노트북, 신용카드, 상승 차트, 은행 건물.
각 오브젝트가 흰 카드 위에 올라 "정보 단위"로 읽힘.

### 11) 배경 구성
연블루 단색 + 캐릭터 뒤 **대형 오렌지 원형 halo** + 옅은 스파클/컨페티.
상단 딥 네이비 헤더 바 + 하단 푸터 바의 "프레임" 구조. 복잡한 실내 없음.

### 12) 정보 밀도
**높은 정보 밀도** — 화면에 8~12개 오브젝트가 있지만 그리드/링 배치로 정돈됨.
"풍부하지만 산만하지 않음"이 핵심.

### 13) 오브젝트 배치와 composition
- 상단: 제목 존 (여백 확보)
- 중앙: 포컬 캐릭터 + 오렌지 halo, 주변에 플로팅 정보 오브젝트 **링 배열**
- 하단: 전경 데스크 / 2x2 그리드 카드
- 3단 구조의 균형 잡힌(대칭에 가까운) 구도

### 14) focal point
중앙 캐릭터(가슴 앞 오브젝트 — 돈봉투/타블렛). 오렌지 원이 시선을 중앙으로 집중시킴.

### 15) 여백의 사용
의도적 여백 — 상단/측면 배경은 비우고, halo 주변·카드 사이에 통풍.
"밝고 여유 있는" 인상의 핵심 요소.

### 16) 전문성/상업적 디자인 느낌
컬러 시스템 + 그리드 + 둥근 모서리 + 헤더/푸터 프레임의 **일관된 템플릿 구조**.
"시리즈 전체가 같은 규칙으로 그려진다"는 신뢰감이 고급스러움의 원천.

### 17) 금융/핀테크 정보 콘텐츠에 어울리는 요소
계산기·달력·서류·돈봉투·동전·상승 차트·신용카드 = "계산/정산" 메타포.
블루(신뢰) + 오렌지(활기) 컬러 심리. 밝고 친근 → 정보성 콘텐츠와 최적.

### 18) 고품질로 보이는 핵심 요소
① 일관된 팔레트 시스템 ② 통일된 볼드 라인/라운드 스타일
③ 명확한 3단 레이아웃(헤더-미들-푸터) ④ 오브젝트 디테일의 밀도
⑤ 캐릭터 브랜드 일관성(랜야드/셔츠) ⑥ 볼드 타이포 + 아웃라인 처리

### 19) 피해야 할 요소
실사/포토리얼, 시네마틱 무드 조명, 복잡한 실내 배경, AI 생성 텍스트(오타 왜곡),
얼굴 클로즈업, 과도한 그라데이션/그림자, 과포화, 무질서한 오브젝트 배치, 차가운 다크 톤.

### 20) 프롬프트 필수 요소
flat vector / bold rounded outline / light blue background / large orange circular halo /
Korean office worker with lanyard / floating symbolic objects in ring layout /
white rounded cards / sparkles & confetti / high information density / clean negative space /
bright cheerful mood / no text (후처리 합성).

---

## 2. 공통 이미지 생성 프롬프트 템플릿

```
[STYLE]
flat vector illustration, clean bold line art with uniform rounded outlines,
modern Korean card-news editorial infographic style,
premium fintech editorial illustration, polished commercial template design,
bold but professional colors, bright and friendly mood

[COLOR]
consistent color system: soft light blue background,
royal blue primary, deep navy accents,
vivid orange highlight elements, green secondary accent,
white rounded cards, yellow sparkle highlights,
flat colors with only 2-3 tone levels, no oversaturation

[LIGHTING]
flat even lighting, bright cheerful daylight mood,
no realistic shadows, only one soft light-blue flat cast shadow under objects,
no dramatic or moody lighting

[COMPOSITION]
central focal subject with a large orange circular halo behind it,
floating symbolic information objects arranged in a balanced ring around the center,
foreground desk objects at the bottom, clean layered depth by overlap,
clear negative space at the top and sides, balanced symmetrical layout

[SUBJECT]
(주제별 상세 — 아래 3종 참조)

[VISUAL INFORMATION]
(주제 핵심 개념을 텍스트 없이 전달하는 상징 오브젝트,
각 오브젝트는 미니어처 씬 수준의 디테일, 8-10개 배치)

[BACKGROUND]
simple flat light blue background, no complex interior,
subtle star sparkles and confetti decoration,
thin rounded frame border

[QUALITY]
high resolution, crisp clean edges, sufficient detail,
high information density yet clean and organized,
consistent style across the whole series,
professional art direction, visually striking but not cluttered

[NEGATIVE PROMPT]
no text, no letters, no words, no numbers, no digits,
no Korean characters, no typography, no labels, no captions,
no logos, no watermarks, no UI elements, no screenshot,
not photorealistic, no realistic shading, no cinematic lighting,
no moody atmosphere, no complex background, no face close-up,
no distorted hands, no duplicated objects, no excessive clutter,
no oversaturated colors, no random typography, no written language
```

---

## 3. 주제별 실제 프롬프트

### ① 주휴수당 계산기

```
[STYLE]
flat vector illustration, clean bold line art with uniform rounded outlines,
modern Korean card-news editorial infographic style,
premium fintech editorial illustration, bold but professional colors,
bright and friendly mood

[COLOR]
consistent color system: soft light blue background,
royal blue primary, deep navy accents,
vivid orange circular halo, green pay elements, white rounded cards,
flat colors, no oversaturation

[LIGHTING]
flat even lighting, bright cheerful daylight mood,
one soft light-blue flat cast shadow under objects, no dramatic lighting

[COMPOSITION]
central smiling Korean office worker with blue lanyard giving a thumbs up,
large orange circular halo behind the worker,
floating symbolic objects arranged in a balanced ring around the center:
a wall calendar with marked work days, a round clock showing weekly work hours,
a pay envelope with coins, floating golden coins and confetti,
foreground desk with calculator and papers at the bottom,
clear negative space at top and sides

[SUBJECT]
cheerful Korean office worker in white shirt and blue lanyard ID badge,
weekly holiday pay concept, work-time tracking theme

[VISUAL INFORMATION]
weekly wall calendar with checkmarked work days, clock showing work hours,
pay envelope with coins, small calculator, floating coins,
subtle star sparkles — all conveying weekly holiday pay without any text

[BACKGROUND]
simple flat light blue background, no complex interior,
subtle sparkles and confetti, thin rounded frame border

[QUALITY]
high resolution, crisp edges, high information density yet clean,
consistent series style, professional art direction

[NEGATIVE PROMPT]
no text, no letters, no numbers, no Korean characters, no typography,
no logos, no watermarks, not photorealistic, no realistic shading,
no cinematic lighting, no face close-up, no distorted hands,
no duplicated objects, no clutter, no oversaturation, no written language
```

### ② 퇴직금 계산기

```
[STYLE]
flat vector illustration, clean bold line art with uniform rounded outlines,
modern Korean card-news editorial infographic style,
premium fintech editorial illustration, bold but professional colors,
bright and friendly mood

[COLOR]
consistent color system: soft light blue background,
royal blue primary, deep navy accents,
vivid orange circular halo, green money elements, white rounded cards,
flat colors, no oversaturation

[LIGHTING]
flat even lighting, bright cheerful daylight mood,
one soft light-blue flat cast shadow under objects, no dramatic lighting

[COMPOSITION]
central smiling Korean office worker with blue lanyard holding service documents,
large orange circular halo behind the worker,
floating symbolic objects arranged in a balanced ring around the center:
a years-of-service wall calendar with marked long duration,
a stack of service and resignation documents, a calculator,
a small upward growth chart, golden coins, floating confetti,
foreground desk at the bottom, clear negative space at top and sides

[SUBJECT]
cheerful Korean office worker in white shirt and blue lanyard ID badge,
long-term employment and retirement allowance concept,
career timeline theme

[VISUAL INFORMATION]
years-of-service calendar, service documents, calculator, growth chart,
golden coins — conveying accumulated severance pay without any text

[BACKGROUND]
simple flat light blue background, no complex interior,
subtle sparkles and confetti, thin rounded frame border

[QUALITY]
high resolution, crisp edges, high information density yet clean,
consistent series style, professional art direction

[NEGATIVE PROMPT]
no text, no letters, no numbers, no Korean characters, no typography,
no logos, no watermarks, not photorealistic, no realistic shading,
no cinematic lighting, no face close-up, no distorted hands,
no duplicated objects, no clutter, no oversaturation, no written language
```

### ③ 연말정산 환급액 계산기

```
[STYLE]
flat vector illustration, clean bold line art with uniform rounded outlines,
modern Korean card-news editorial infographic style,
premium fintech editorial illustration, bold but professional colors,
bright and friendly mood

[COLOR]
consistent color system: soft light blue background,
royal blue primary, deep navy accents,
vivid orange circular halo, green refund money elements, white rounded cards,
flat colors, no oversaturation

[LIGHTING]
flat even lighting, bright cheerful daylight mood,
one soft light-blue flat cast shadow under objects, no dramatic lighting

[COMPOSITION]
central smiling Korean office worker with blue lanyard holding a refund pay envelope,
large orange circular halo behind the worker,
floating symbolic objects arranged in a balanced ring around the center:
tax receipts and annual tax return documents with a magnifying glass,
a calculator, a year-end calendar page, refund golden coins,
floating confetti, foreground desk at the bottom,
clear negative space at top and sides

[SUBJECT]
cheerful Korean office worker in white shirt and blue lanyard ID badge,
year-end tax settlement and refund calculation theme

[VISUAL INFORMATION]
receipts, tax return documents, calculator, magnifying glass,
year-end calendar, refund coins — conveying refund calculation without any text

[BACKGROUND]
simple flat light blue background, no complex interior,
subtle sparkles and confetti, thin rounded frame border

[QUALITY]
high resolution, crisp edges, high information density yet clean,
consistent series style, professional art direction

[NEGATIVE PROMPT]
no text, no letters, no numbers, no Korean characters, no typography,
no logos, no watermarks, not photorealistic, no realistic shading,
no cinematic lighting, no face close-up, no distorted hands,
no duplicated objects, no clutter, no oversaturation, no written language
```

---

## 4. 현재 PoC 프롬프트 대비 변경 핵심 요소 (v3 / v4)

| # | 변경 요소 | 현재 PoC (v3/v4) | 샘플 DNA 기준 변경 방향 |
|---|-----------|------------------|------------------------|
| 1 | **스타일 축 정렬** | v3: cinematic lighting, realistic material, dimensional objects, rich depth (샘플과 정반대) / v4: flat이지만 "일반적" flat | 샘플의 flat 카드뉴스 방향으로 통일. 실사/시네마틱 단어 완전 제거 |
| 2 | **색 시스템 구체화** | "blue and orange palette" 수준의 모호한 지시 | 배경 라이트 블루 + 네이비/로열 블루 + 오렌지 halo + 그린/화이트 카드의 **역할별 색 지정** |
| 3 | **오렌지 원형 halo** | 없음 | 시선 집중의 핵심 장치 — 중앙 캐릭터 뒤 대형 오렌지 원 명시 |
| 4 | **캐릭터 규칙** | v4 "필요할 때만" (실제 미포함) | 흰 셔츠 + 랜야드 + 엄지척의 **브랜드 캐릭터를 항상 포함**, 얼굴 클로즈업 금지 |
| 5 | **라인/라운드 스펙** | "clean line art" 수준 | **bold uniform rounded outline**, 모든 모서리 rounded 명시 |
| 6 | **오브젝트 배치** | 배치 지시 없음 (무질서 발생) | "focal 주변 **링 배열** + 하단 전경 데스크"의 3단 구도 명시 |
| 7 | **정보 밀도 수치화** | "sufficient detail" | "8~10개 상징 오브젝트, 미니어처 씬 수준 디테일"로 구체화 |
| 8 | **데코 요소** | 없음 | 스파클/컨페티/플로팅 코인 추가 (밝고 축제적인 분위기) |
| 9 | **그림자 규칙** | 없음 | "flat cast shadow 1개만" 명시 (flat 특성 유지) |
| 10 | **구조화된 프롬프트** | 단일 문장 나열(주제+스타일+네거티브 concat) | [STYLE][COLOR][LIGHTING][COMPOSITION][SUBJECT][VISUAL INFORMATION][BACKGROUND][QUALITY] **섹션 템플릿** — 일관성·편집 용이성 확보 |
| 11 | **네거티브** | "not childish cartoon" 포함 (샘플은 실제로 cartoonish) | "not childish"로 완화 — 샘플의 웹툰형 캐릭터를 배제하지 않도록 |
| 12 | **텍스트 합성 영역** | 하단 ~28% 패널이 AI 아트웍을 가림 | 샘플은 상단 제목 존이 분리 — **상단 타이틀 존을 비워두고**, 하단 오브젝트 중심 배치로 텍스트 합성 영역과 충돌 방지 |

> 주의: 샘플의 볼드 아웃라인 타이포는 Pillow 합성 레이어(제목/부제)에서
> "화이트 아웃라인 + 네이비 볼드" 스타일로 재현하는 것이 자연스러움.
> AI가 이미지 안에 타이포를 만들지 않도록 하는 것이 전제.
