# Contact Email Migration Report

## 기존 이메일
- `contact@calcmate.kr` (2곳)

## 변경 파일
1. `modules/site_generator.py` — 상수 `_CONTACT_EMAIL` 변경 (소스 오브피트)
2. `data/workspace/_site/contact/index.html` — 생성된 문의 페이지 mailto/display 변경

## 신규 이메일
`calcmate.kr@gmail.com`

## 잔존 여부
**PASS** — 기존 `contact@calcmate.kr` 잔존 0건

## mailto
**PASS** — `mailto:calcmate.kr@gmail.com` 정상 연결

## 기능 영향
없음. 계산 로직, 이미지 파이프라인, WordPress 파이프라인, 디자인 모두 변경 없음.

## 수정 파일 수
2개

## 커밋
없음

## 참고: 수정하지 않은 파일 (분류 C)
- `modules/utils/data/logs/health_last.json` — Google 서비스 계정 이메일 (`blog-982@...iam.gserviceaccount.com`)
- `docs/archive/TODO_NEXT.md` — 동일 서비스 계정 참조
- `docs/archive/STABILITY_REPORT.md` — 동일 서비스 계정 참조

→ 모두 외부 API 인증 관련으로 수정 대상 아님.

## 테스트 영향
- `site_generator` 관련 테스트: 없음 (테스트 파일에서 직접 참조하지 않음)
- 전체 테스트 회귀: 영향 없음
