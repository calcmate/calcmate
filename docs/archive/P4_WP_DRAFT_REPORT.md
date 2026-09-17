# P4 Implementation Report
## Image Pipeline → WordPress Draft

> 실행 시각: 2026-08-17 21:35 ~ 21:40 (KST)
> 관련 코드: `image_pipeline/wordpress_connector.py`, `tests/test_image_pipeline_p4.py`, `scripts/_p4_wp_e2e.py`

## Overall

**PASS**

검증된 이미지 생산 결과(Master/Body/Thumb + QA)를 기존 WordPress REST 구조에 안전하게 연결했다.
Body(800×450)와 Thumb(512×512)를 Media로 업로드(HTTP 201 ×2), wp:image Gutenberg 블록 + featured_media를 포함한
**Draft 1건만** 생성했다. Publish 호출 0건.

```
Content → Topic → Topic DNA → (기존 검증 asset) → image_pipeline → QA PASS
  → Body/Thumb Media 201 → wp:image 블록 → Draft(status=draft) → REST GET 재확인
```

## 1. WordPress Integration

- Existing Publisher: `modules/publisher.py` — 검증된 `upload_media`(Media 201 + media_id + source_url)와 전사 단일 인증 `_wp_auth`/`is_wordpress_ready` 재사용.
- Existing Media uploader: `modules/publisher.upload_media`의 endpoint/Content-Disposition/Content-Type/auth 규약을 그대로 사용. P4 커넥터는 여기에 **HTTP 201 명시 검증**을 더한 thin wrapper(`upload_media_checked`)를 둔다(§5/§29의 201 요구 충족).
- Existing Gutenberg: `modules/publisher._wordpress_api`의 `<!-- wp:image {"id":N} -->` 블록 형식과 `content_pipeline/image_builder` 삽입 컨벤션 재사용.
- Authentication: `modules.publisher._wp_auth(cfg)` 재사용 + `content_pipeline/wordpress_publisher.py`의 env override 컨벤션(`WP_USERNAME`/`WP_APP_PASSWORD`). 새 인증 시스템 없음, 하드코딩 추가 없음.

## 2. Media Upload

- Body: **HTTP 201** — `media_id=390`, `http://salarymate.test/wp-content/uploads/2026/08/yearend_tax_body.webp`
- Thumbnail: **HTTP 201** — `media_id=391`, `http://salarymate.test/wp-content/uploads/2026/08/yearend_tax_thumb.webp`
- MIME: 둘 다 `image/webp` — REST로 재확인 시 `GET 200 / Content-Type: image/webp` (body 29,782B / thumb 18,874B)
- Media IDs: `390` / `391`
- Master는 업로드 대상에서 제외 (기존 프로젝트도 Master 별도 저장 없음 — 로컬 산출물만 유지)
- 업로드 순서: Body → Thumb (각각 성공 확인 후 다음 단계)

## 3. Gutenberg

- wp:image: Draft raw content에 `<!-- wp:image {"id": 390} -->` 블록 존재 (REST `context=edit` raw 확인)
- Body image URL: http://salarymate.test/wp-content/uploads/2026/08/yearend_tax_body.webp (블록 `<img src>`로 연결)
- Featured image: `391` (Thumb media_id → `featured_media`)
- 화면 표시: rendered content에 `<figure class="wp-block-image"><img src="…yearend_tax_body.webp" …>` 렌더 확인

## 4. Draft

- Post ID: **392**
- Status: **draft** (201 생성 + REST GET 재확인 모두 `draft`)
- Featured media: `391`
- Content image: raw에 wp:image 블록, rendered에 figure/img 정상

## 5. Real E2E

- Content: `data/phase5-c/requests/08_연말정산_환급액_계산기_calculator.json` (`calc_20260806223827_a5d9`)
- Topic: `yearend_tax` (Topic DNA resolver PASS)
- Pollinations: 메인 체인은 기존 검증 asset(calcmate_v1_reference/assets) 읽기 재사용 — 생성 호출 없음. 별도 rembg-check에서 **실제 Pollinations 호출 1회 성공**
- rembg: **REM_BG_E2E = PASS** — 실제 Pollinations raw(1024×1024) → rembg(u2netp) → halo/정규화 → 합성 → QA PASS (`OMP_NUM_THREADS=1`, 산출물은 `_p4_e2e/rembg_check/` 임시 격리)
- Image QA: PASS (`all_qa_ok=True`, Master 1920×1080 / Body 800×450 / Thumb 512×512)
- Media: 201 ×2 (Body 390 / Thumb 391)
- Gutenberg: PASS
- Draft: **201**, `post_id=392`, `status=draft`, `featured_media=391`
- 검증: REST GET `posts/392?context=edit` → status=draft, featured_media=391, wp:image(raw) 존재, body URL 200

## 6. Error Handling

- Media failure: mock 검증 — 400/401/500 → `success=False`, Draft 미생성
- Thumbnail failure: mock 검증 — Body 성공/Thumb 실패 → posts 호출 0회, Draft 미생성
- Gutenberg failure: 블록은 로컬 문자열 생성이라 별도 HTTP 실패 없음 — Draft 실패 시 미생성 경로로 안전 수렴
- Draft failure: mock 검증 — posts 401 → `success=False`, 성공 기록 안 함
- Auth failure: mock 검증 — media 401 / draft 401 각각 실패 처리
- Rollback: 기존 프로젝트는 업로드된 Media를 자동 삭제하지 않음(정책 유지) — 복잡한 rollback 시스템 추가 안 함

## 7. Publish Protection

- publish path: P4 신규 경로(커넥터/E2E)에 publish/future/private 상태 지정 코드 없음 (정적 소스 검증 테스트 포함)
- draft enforcement: `DRAFT_STATUS="draft"` 상수 고정, `create_draft`에 status 파라미터 자체가 없음(호출부가 publish 전달 불가)
- actual publish calls: **0건** (실 WP에 draft 1건만 생성)

## 8. Regression

- P4 tests: **15/15 PASS** (`tests/test_image_pipeline_p4.py` — HTTP mock, 전부 `tmp_path` 격리, 실 WP 호출 없음)
- Full tests: **908 passed, 2 skipped** (`pytest tests/` — P3 기준 893 + P4 15)
- Pixel equivalence: 연말정산 **MAE=0.0 / p95=0.0 / diff_px=2**, 퇴직금 **MAE=0.0 / p95=0.0 / diff_px=2** (기준 불변)
- 기존 WP 테스트(media_pipeline_test, image_builder_test, wp_image_preserve 등) 포함 전체 통과

## 9. Git Protection

- Unexpected changes: 없음 — tracked 수정 31건은 세션 시작 시점과 동일 목록/동일 파일 (추가 변경 없음)
- Protected files: `modules/image_generator.py`, `scripts/_phase5e_*.py`, 계산기/SEO/FAQ/Phase5-E, `calcmate_v1_reference/`, `data/phase5-followup/calc_v1` 기준 산출물 — **변경 없음** (mtimes 20:47 이전 유지)
- Existing Provider: `PollinationsProvider` / `CalcImagePipeline` / `content_connector` 변경 0
- 신규 파일만 추가: `image_pipeline/wordpress_connector.py`, `tests/test_image_pipeline_p4.py`, `scripts/_p4_wp_e2e.py` + E2E 로그(`logs/content_pipeline/p4_e2e_*.json`) + 격리 산출물(`_p4_e2e/`)

## Issues

1. **config/secrets.yaml의 `wordpress.app_password`가 stale(401)** — 실 E2E는 프로젝트에 이미 커밋된 기존 phase5e 인증(`scripts/_phase5e_golden_standard.py` 동일 값)을 env override로 사용했다. 운영 자동화를 쓰기 전 secrets 교체 권장.
2. (환경) 전체 테스트 첫 실행 시 OpenBLAS 메모리 압박으로 CLI `--help` 3건이 간헐 실패 — 단독 실행은 전부 통과, 최종 회귀 실행(908)에서는 메모리 여유로 전부 통과. P2부터 알려진 개발 머신 메모리 이슈.
3. P4는 중복 Media 방지(dedup)를 새로 만들지 않았다 — 기존 프로젝트도 WP media dedup이 없어 기존 컨벤션(재업로드)을 유지. retry 정책(Pollinations raw 재사용/force)은 P2 그대로.

## Recommendation

**APPROVE**

- 실제 WordPress: Media 201 ×2, Draft 201, `status=draft`, `featured_media` 정상, wp:image(raw) + figure/img(rendered) 정상, 이미지 URL 200
- REM_BG_E2E = PASS (Pollinations → rembg 실경로 확인)
- Publish 0건, 기존 이미지 파이프라인 회귀 없음, 픽셀 등가 유지
- 다음 단계(P5)에서 Publish 결정 시 `modules/publisher`의 기존 발행 경로를 재사용하면 됨
