"""api/services/site_service.py — Site Management 조회/생성 서비스.

STEP P2-04: dashboard.py의 "🌐 사이트 관리" 탭(dashboard.py:1012-1453)이 사이트
목록을 표시하는 부분만 이관했다(READ-ONLY, get_sites()).

STEP P2-06: 사이트 생성(Create)/Import만 추가로 이관한다. Update/Delete/Archive/
Restore/Clone/Calculator 등록·삭제/Override는 이번 STEP에서도 다루지 않는다.

STEP P2-07: 사이트 기본 정보 수정(Update)과 Site Settings Override 저장/초기화만
추가로 이관한다. Delete/Archive/Restore/Clone/Calculator 등록·삭제/Export는
이번 STEP에서도 다루지 않는다.

STEP P2-08: Activate/Deactivate/Archive/Restore만 추가로 이관한다. Hard
Delete/Clone/Calculator 등록·삭제/Export는 이번 STEP에서도 다루지 않으며,
P2-07의 Update/Override/Reset 구현은 변경하지 않는다.

STEP P2-09: Hard Delete와 Clone만 추가로 이관한다. P2-04~P2-08의 구현은
변경하지 않는다.

재확인된 사실(dashboard.py/site_wizard.py 재검색, 추측 없음):
  - 영구 삭제("⛔ 영구 삭제", dashboard.py:1402-1409)는 사용자가 텍스트
    입력에 정확히 "DELETE"를 입력했을 때만(dashboard.py:1403-1410, UI 레벨
    확인) site_wizard.delete_site()를 호출한다. 이 함수는 SiteRepository.
    delete() → db.delete("sites", site_id)만 실행한다 — sites 테이블의
    해당 row 하나만 실제 SQL DELETE된다. calculators/articles 테이블,
    Registry(docs/registry_auto.yaml, docs/registry/*.yaml), HOLD, Retry
    Queue(pending_posts.json), cost_state.json, secrets.yaml, config.yaml
    중 무엇도 참조/변경하지 않는다(delete_site()/SiteRepository.delete()/
    SQLiteAdapter.delete() 소스 전체 재확인, 추측 아님).
  - adapters/db/sqlite_adapter.py의 테이블 생성 방식(_ensure_table)은 모든
    컬럼을 TEXT로 동적 생성하며 FOREIGN KEY/REFERENCES/CASCADE를 어디에도
    선언하지 않는다(재확인) — 즉 DB 레벨 연쇄 삭제가 애초에 존재하지
    않는다. calculators 테이블에 site_id 컬럼이 있어도(값 매칭일 뿐)
    Hard Delete가 이를 지우거나 고아로 만들든 상관하지 않는다 — 원본
    delete_site()가 애초에 그 테이블을 건드리지 않기 때문에 이 STEP도
    동일하게 손대지 않는다.
  - secrets.yaml의 wordpress_profiles[profile_id]는 Hard Delete로 전혀
    삭제되지 않는다(원본에 그런 코드가 없음, 추측 아님) — 사이트를
    삭제해도 해당 WordPress 자격증명은 secrets.yaml에 고아로 남는다.
    이는 원본의 기존(이미 존재하던) 동작이며, 이 STEP에서 새로 만든
    문제가 아니다 — STOP 조건은 "위험한 삭제/공유 profile 오삭제"인데
    여기서는 애초에 아무 삭제도 일어나지 않으므로 STOP 사유가 아니다.
    (profile_id는 create_site()가 "wp_" + slugify(site_name)으로 사이트별
    로 생성하고, _validate_site()가 사이트명 중복을 사전에 차단하므로
    서로 다른 두 사이트가 같은 profile_id를 실질적으로 공유할 가능성도
    없다 — 재확인.) 이 동작을 그대로 재현하며, 새 cleanup 정책을 임의로
    추가하지 않는다.
  - 복제("📑 복제(Clone)", dashboard.py:1411-1433)는 별도 함수가 아니라
    site_wizard.create_site()를 원본 사이트 값으로 미리 채운 인자로
    그대로 호출한다(재구현 없음, P2-06에서 이미 이관된 create_site()
    서비스 래퍼를 그대로 재사용). 복사되는 필드는 site_tags(카테고리)
    와 research_ai/writing_ai/review_ai 4개뿐이다(dashboard.py:1425-1430
    재확인). site_name은 "{원본} (복사본)"을 기본값으로 보여주되 사용자가
    수정 가능하고, domain은 항상 빈 문자열로 시작해 사용자가 반드시 새로
    입력해야 한다(원본과 동일 — 중복 도메인 방지). site_type/status/
    platforms/seo_keyword_count/seo_length/daily_override/image_mode/
    telegram_enabled/analytics_enabled/calc_active/features는 전혀
    복사되지 않는다(원본에 그 필드들을 읽는 코드가 없음).
  - Clone의 WordPress 자격증명(wp_url/wp_user/wp_app_password)은 원본에서
    "전혀 복사되지 않고" 매번 새로 입력받는다(dashboard.py:1419-1423,
    "이 유형은 WordPress 자격증명이 필요합니다(복제 시 재입력)" 캡션 재확인)
    — secrets.yaml의 기존 wordpress_profiles를 읽거나 재사용하는 코드가
    없다. 즉 credential 복제 위험이 원본 자체에 존재하지 않는다(STOP 조건
    아님). type_label은 원본 site_type을 TYPE_DEFS 역매핑으로 구해
    재사용한다(dashboard.py:1416-1417과 동일한 next(...) 조회 방식 — 여러
    라벨이 같은 site_type을 공유하면 TYPE_DEFS 선언 순서상 첫 번째가
    선택된다는 원본의 기존 모호성도 그대로 재현한다).

기존 재확인된 사실(P2-08, 계속 유효):
  - 활성화/비활성화(dashboard.py:1374-1379, "▶ 활성화"/"⏸ 비활성화" 토글
    버튼, 보관되지 않은 사이트에서만 표시)는 site_wizard.set_site_status()
    를 호출하며, 이 함수는 SiteRepository.update_status()를 거쳐
    "status" 필드 단 하나만 "active" 또는 "inactive"로 변경한다(다른 필드
    불변, deleted_at도 건드리지 않는다).
  - 보관(dashboard.py:1380-1385, "🗑️ 삭제(보관 이동)")은 site_wizard.
    update_site()를 호출해 {"status": "archived", "deleted_at": 현재시각
    ISO 문자열} 두 필드를 동시에 설정한다 — soft delete이며 실제 row는
    삭제되지 않는다.
  - 복구(dashboard.py:1398-1401, "♻️ 복구")도 동일한 update_site()를
    호출해 {"status": "inactive", "deleted_at": ""} 두 필드를 설정한다.
    "active"가 아니라 항상 "inactive"로 복구된다는 점이 원본 코드에 그대로
    하드코딩되어 있다(보관 전 상태를 기억하지 않음) — 추측으로 "active"를
    쓰지 않고 원본 그대로 재현한다.
  - 영구 삭제("⛔ 영구 삭제", dashboard.py:1402-1409, site_wizard.
    delete_site())는 이번 STEP 범위 밖이다(Hard Delete 제외).
  - set_site_status()/update_site() 어느 쪽도 secrets.yaml/config.yaml을
    참조하지 않으며, WordPress 등 외부 API를 호출하지 않는다(재확인,
    SiteRepository.update_status()/update()는 sites 테이블 UPDATE만 실행).
    calculators/articles/Registry 테이블도 건드리지 않는다.
  - 원본 UI는 보관된 사이트에는 활성화/비활성화 버튼 자체를 렌더링하지
    않지만, set_site_status() 함수 자체에는 이를 막는 검사가 없다 — 이
    STEP에서도 원본에 없는 상태 전이 제약을 새로 추가하지 않는다(버튼
    노출 제한은 React UI 쪽에서 재현한다).

기존 재확인된 사실(P2-07, 계속 유효):
  - "💾 수정 저장"(dashboard.py:1369-1373)은 site_name/domain/site_tags 3개
    필드만 site_wizard.update_site()로 저장한다(기본 정보 수정).
  - "⚙️ Site Settings (Override)"(dashboard.py:1072-1166)는 별도 UI 섹션으로,
    research_ai/writing_ai/review_ai/wordpress_url/site_tags/seo_keyword_count/
    seo_length/daily_override/image_mode/telegram_enabled/analytics_enabled/
    calc_active 총 12개 필드를 저장한다. wordpress_url/site_tags는 "코어
    필드"로 분류되어 Reset 대상에서 제외된다(dashboard.py:1161 주석 재확인).
    Reset은 나머지 9개 필드만 빈 문자열("")로 되돌린다 — NULL도 삭제도 아니다.
  - features 필드는 이 폼에서 읽기 전용으로만 표시되며(st.code), 어떤 저장
    호출에도 포함되지 않는다 — 이번 STEP에서도 편집 대상에 포함하지 않는다.
  - site_type/platforms는 이 두 UI 어디에도 편집 경로가 없다(재확인) — 이번
    STEP에서도 새로 만들지 않는다(원본에 없는 기능을 추가하지 않는다는 원칙).
  - site_wizard.update_site()/SiteRepository.update()는 site_id 존재 여부를
    검사하지 않는다 — 존재하지 않는 site_id로 호출해도 SQLite UPDATE가 0 rows
    를 조용히 수정하고 예외 없이 성공을 반환한다(실제로 재현해 확인함). 404를
    만들기 위해 이 서비스 레이어에서 호출 전 SiteRepository.get_by_id()로
    존재를 먼저 확인한다(원본 함수 자체는 변경하지 않음).
  - Update/Override/Reset 전부 sites DB row만 변경한다 — secrets.yaml/config.yaml
    은 어디에서도 참조되지 않는다(재확인, STOP 조건 아님).

데이터 source(P2-04/P2-05에서 재검색으로 확인, 추측 없음): modules.site_wizard.
create_site(cfg, type_label, fields)를 그대로 재사용한다(재구현하지 않음). 이
함수는 다음 순서로 동작한다(dashboard.py:88-160, 재확인):
  1) _validate_site() — 필수값/중복 사이트명·도메인 검증(READ만)
  2) needs_wp and wp_url이 있으면 SiteRepository.save_wp_profile()로
     secrets.yaml의 wordpress_profiles[profile_id]에 먼저 기록
  3) SiteRepository.save()로 sites DB row INSERT

P2-05에서 확인된 위험(그대로 재확인됨, dashboard.py/site_wizard.py 무변경):
  - (2) 성공 후 (3)이 실패하면 secrets.yaml에 고아 wordpress_profiles 항목이
    남는다 — create_site() 자체에는 rollback이 없다.
  - _validate_site()의 중복 검사와 SiteRepository.save() 사이에 lock이 없어
    동시 요청 시 TOCTOU 레이스가 가능하다.
  - 반대 방향(DB 성공 → secrets 실패)은 create_site()의 코드 순서상 구조적으로
    발생할 수 없다(secrets가 항상 DB보다 먼저 시도되고, secrets가 실패하면
    즉시 반환되어 DB save 자체가 호출되지 않는다) — 재확인됨, 아래 create_site()
    docstring 참고.

이 서비스는 site_wizard.create_site()/update_site() 자체를 변경하지 않고,
호출 "주변"에서만 다음을 추가한다:
  - threading.Lock으로 검증→저장 구간을 직렬화(같은 프로세스 내 동시 생성 방지 —
    cost_service.py의 기존 _resume_lock/_retry_lock 패턴과 동일한 in-process
    lock이며, Scheduler의 파일 lock을 재사용하지 않는다. Site Management는
    별도 스케줄러 프로세스가 없어 cross-process 보호가 필요 없다).
  - secrets.yaml의 wordpress_profiles 스냅샷/복원(rollback) — SiteRepository를
    수정하지 않고, 이 서비스 레이어에서만 읽기/쓰기를 수행한다.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

import yaml

from modules.config_loader import load_config
from adapters.db.factory import get_db_adapter
from repositories.site_repository import SiteRepository
from modules.site_wizard import (
    TYPE_DEFS,
    create_site as _wizard_create_site,
    update_site as _wizard_update_site,
    set_site_status as _wizard_set_site_status,
    delete_site as _wizard_delete_site,
)

_create_lock = threading.Lock()
_LOCK_TIMEOUT_SECONDS = 10


class SiteCreateBusy(Exception):
    """다른 사이트 생성/Import 요청이 이미 처리 중(락 타임아웃)."""


class SiteValidationError(Exception):
    """site_wizard.create_site()가 반환한 실패 사유(중복/필수값 누락 등)를 그대로 전달."""


class SiteNotFound(Exception):
    """site_id에 해당하는 사이트가 없음(원본 update_site()는 이 경우를 검사하지
    않고 조용히 성공을 반환하므로, 이 서비스가 호출 전에 별도로 확인한다)."""


# Site Settings Override 대상 필드(dashboard.py:1147-1156, 재확인) — 순서는
# 원본 저장 호출의 순서를 그대로 따른다.
OVERRIDE_FIELDS = (
    "research_ai", "writing_ai", "review_ai", "wordpress_url", "site_tags",
    "seo_keyword_count", "seo_length", "daily_override", "image_mode",
    "telegram_enabled", "analytics_enabled", "calc_active",
)
# Reset 대상 필드(dashboard.py:1162-1164, 재확인) — wordpress_url/site_tags는
# "코어 필드"로 분류되어 제외된다(원본 주석 그대로).
RESET_FIELDS = (
    "research_ai", "writing_ai", "review_ai", "seo_keyword_count", "seo_length",
    "daily_override", "image_mode", "telegram_enabled", "analytics_enabled", "calc_active",
)


def _secrets_path(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    return root / "config" / "secrets.yaml"


def _read_wp_profiles(cfg: dict) -> dict:
    p = _secrets_path(cfg)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return dict(data.get("wordpress_profiles", {}) or {})


def _restore_wp_profiles(cfg: dict, before: dict, after: dict) -> None:
    """create_site() 실패 후 secrets.yaml의 wordpress_profiles를 before 상태로
    복원한다. before/after는 얕은 dict 스냅샷(profile_id -> {url,username,
    app_password})이다. 새로 생긴 키는 제거하고, 값이 바뀐 기존 키는 원래 값으로
    되돌린다(§8 "기존 profile 없음→제거 / 기존 profile 존재→복원"). 실제 secret
    값은 어떤 예외 메시지/로그에도 남기지 않는다."""
    if before == after:
        return
    p = _secrets_path(cfg)
    if not p.exists():
        return
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    data["wordpress_profiles"] = dict(before)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _project(repo: SiteRepository, row: dict) -> dict:
    """DB row -> API 응답 shape. get_sites()/create_site() 공통 사용(P2-04와
    동일한 secret 미노출 원칙 — wordpress_configured만 boolean으로 계산)."""
    site_id = row.get("site_id", "")
    try:
        platforms = json.loads(row.get("platforms") or "[]")
    except Exception:
        platforms = []
    try:
        wp = repo.get_wp_config(site_id)
        wordpress_configured = bool(
            wp.get("WORDPRESS_URL") and wp.get("WORDPRESS_USERNAME") and wp.get("WORDPRESS_APP_PASSWORD")
        )
    except Exception:
        wordpress_configured = False
    return {
        "site_id": site_id,
        "site_name": row.get("site_name", ""),
        "domain": row.get("domain", ""),
        "site_type": row.get("site_type", ""),
        "status": row.get("status", ""),
        "platforms": platforms,
        "wordpress_configured": wordpress_configured,
    }


def get_sites() -> list:
    """반환: [{"site_id","site_name","domain","site_type","status","platforms",
    "wordpress_configured"}, ...]. secrets.yaml의 실제 자격증명 값은 절대
    포함하지 않는다."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return [_project(repo, row) for row in repo.get_all()]


def _project_detail(repo: SiteRepository, row: dict) -> dict:
    """_project()의 목록용 shape + Override 편집에 필요한 12개 필드. GET
    /api/sites/{site_id}(P2-07 신규, 조회 전용) 전용 — 목록 응답(get_sites())의
    shape는 건드리지 않는다."""
    detail = _project(repo, row)
    try:
        calc_active = json.loads(row.get("calc_active") or "[]")
    except Exception:
        calc_active = []
    for field in OVERRIDE_FIELDS:
        if field == "calc_active":
            detail[field] = calc_active
        else:
            detail[field] = row.get(field, "")
    return detail


def get_site(site_id: str) -> dict:
    """단일 사이트 상세 조회(READ-ONLY, 신규) — Override 편집 폼이 현재 값을
    불러오는 용도. 없으면 SiteNotFound."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = repo.get_by_id(site_id)
    if row is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {site_id}")
    return _project_detail(repo, row)


def update_site_basic(site_id: str, fields: dict) -> dict:
    """dashboard.py "💾 수정 저장"(dashboard.py:1369-1373)과 동일한 실행 의미.
    site_name/domain/site_tags 3개 필드만 site_wizard.update_site()로 저장한다
    (재구현 없음). 존재하지 않는 site_id면 SiteNotFound(원본에는 없는 안전장치 —
    원본 update_site()는 이 경우를 조용히 성공 처리한다, 위 모듈 docstring 참고)."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    if repo.get_by_id(site_id) is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {site_id}")

    ok, msg = _wizard_update_site(cfg, site_id, {
        "site_name": fields.get("site_name", ""),
        "domain": fields.get("domain", ""),
        "site_tags": fields.get("category", ""),
    })
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = repo.get_by_id(site_id)
    return _project(repo, row)


def save_override(site_id: str, fields: dict) -> dict:
    """dashboard.py "💾 Override 저장"(dashboard.py:1147-1159)과 동일한 실행
    의미. OVERRIDE_FIELDS 12개를 그대로 site_wizard.update_site()에 전달한다
    (재구현 없음, 새 설정 체계를 만들지 않음). calc_active는 원본과 동일하게
    JSON 배열 문자열로 인코딩해서 저장한다."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    if repo.get_by_id(site_id) is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {site_id}")

    data = {}
    for field in OVERRIDE_FIELDS:
        if field == "calc_active":
            data[field] = json.dumps(list(fields.get(field) or []), ensure_ascii=False)
        else:
            data[field] = str(fields.get(field) or "").strip()
    ok, msg = _wizard_update_site(cfg, site_id, data)
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = repo.get_by_id(site_id)
    return _project_detail(repo, row)


def reset_override(site_id: str) -> dict:
    """dashboard.py "↩️ Override 초기화(Global 복귀)"(dashboard.py:1160-1166)와
    동일한 실행 의미. RESET_FIELDS 9개만 빈 문자열로 되돌린다 — wordpress_url/
    site_tags(코어 필드)는 원본과 동일하게 보존한다."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    if repo.get_by_id(site_id) is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {site_id}")

    ok, msg = _wizard_update_site(cfg, site_id, {field: "" for field in RESET_FIELDS})
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = repo.get_by_id(site_id)
    return _project_detail(repo, row)


def create_site(type_label: str, fields: dict) -> dict:
    """dashboard.py의 "➕ 사이트 추가"/"🧙 새 사이트 마법사"와 동일한 실행 의미.
    site_wizard.create_site()를 그대로 호출하며(재구현 없음), 다음만 추가한다:
      - in-process lock으로 검증→저장 구간 직렬화(동시 생성 시 순차 처리)
      - secrets.yaml wordpress_profiles 스냅샷/복원(DB 저장 실패 시 고아 profile
        제거 또는 원래 값 복원)
      - 성공 시 fields.get("platforms")가 있으면 site_wizard.update_site()로
        platforms만 추가 기록(5단계 마법사의 후속 기록과 동일한 의미 — 실패해도
        사이트 생성 자체는 성공으로 유지, dashboard.py의 경고-only 동작과 동일)

    실패 시 SiteValidationError(원본 메시지 그대로)를 던진다. lock 타임아웃 시
    SiteCreateBusy를 던진다."""
    if type_label not in TYPE_DEFS:
        raise SiteValidationError(f"알 수 없는 유형: {type_label}")

    acquired = _create_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS)
    if not acquired:
        raise SiteCreateBusy("다른 사이트 생성 요청이 진행 중입니다. 잠시 후 재시도하세요.")
    try:
        cfg = load_config()

        before_profiles = _read_wp_profiles(cfg)
        ok, msg = _wizard_create_site(cfg, type_label, fields)
        if not ok:
            after_profiles = _read_wp_profiles(cfg)
            _restore_wp_profiles(cfg, before_profiles, after_profiles)
            raise SiteValidationError(msg)

        # save_wp_profile()이 secrets.yaml을 방금 새로 썼을 수 있으므로, 그 값을
        # 반영한 새 SiteRepository를 다시 생성한다(SiteRepository.__init__은
        # secrets.yaml을 생성 시점에 한 번만 메모리에 캐시하기 때문 — 재사용하면
        # wordpress_configured가 stale 값으로 계산된다).
        repo = SiteRepository(get_db_adapter(cfg), cfg)
        site_name = (fields.get("site_name") or "").strip()
        domain = (fields.get("domain") or "").strip()
        rows = repo.get_all()
        row = next(
            (r for r in rows if r.get("site_name") == site_name and r.get("domain") == domain),
            None,
        )
        platforms_warning = None
        platforms = fields.get("platforms") or []
        if row and platforms:
            try:
                _wizard_update_site(cfg, row.get("site_id", ""), {
                    "platforms": json.dumps(list(platforms), ensure_ascii=False),
                })
                row["platforms"] = json.dumps(list(platforms), ensure_ascii=False)
            except Exception as e:
                platforms_warning = f"platforms 기록 경고: {e}"

        result = _project(repo, row) if row else {
            "site_id": "", "site_name": site_name, "domain": domain,
            "site_type": TYPE_DEFS[type_label]["site_type"], "status": "active",
            "platforms": list(platforms), "wordpress_configured": False,
        }
        if platforms_warning:
            result["platforms_warning"] = platforms_warning
        return result
    finally:
        _create_lock.release()


def import_sites(rows: list) -> dict:
    """dashboard.py "⬆️ Import(JSON) — 검증 경유 신규 등록만"과 동일한 실행 의미
    (dashboard.py:1047-1070, 재확인). 각 row에 대해 create_site()를 반복 호출하며,
    WordPress 자격증명은 Import 데이터에서 절대 읽지 않는다(원본과 동일 — wp_user/
    wp_app_password는 항상 빈 문자열로 고정 전달되어, WordPress가 필요한 유형은
    항상 실패한다는 원본의 알려진 제약도 그대로 유지된다)."""
    total = len(rows)
    success = 0
    errors = []
    for r in rows:
        site_type = r.get("site_type", "custom")
        label = next((k for k, v in TYPE_DEFS.items() if v["site_type"] == site_type), "사용자정의")
        try:
            create_site(label, {
                "site_name": r.get("site_name", ""),
                "domain": r.get("domain", ""),
                "category": r.get("site_tags", ""),
                "wp_url": r.get("wordpress_url", ""),
                "wp_user": "",
                "wp_app_password": "",
                "rss_sources": "",
            })
            success += 1
        except SiteValidationError as e:
            errors.append(str(e))
        except SiteCreateBusy as e:
            errors.append(str(e))
    return {"total": total, "success": success, "failed": total - success, "errors": errors}


def _require_existing(repo: SiteRepository, site_id: str) -> None:
    if repo.get_by_id(site_id) is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {site_id}")


def activate_site(site_id: str) -> dict:
    """dashboard.py "▶ 활성화"(dashboard.py:1374-1379)와 동일한 실행 의미.
    site_wizard.set_site_status()로 status만 "active"로 변경한다(재구현 없음,
    deleted_at 등 다른 필드는 건드리지 않는다)."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    _require_existing(repo, site_id)

    ok, msg = _wizard_set_site_status(cfg, site_id, "active")
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return _project(repo, repo.get_by_id(site_id))


def deactivate_site(site_id: str) -> dict:
    """dashboard.py "⏸ 비활성화"(dashboard.py:1374-1379)와 동일한 실행 의미.
    site_wizard.set_site_status()로 status만 "inactive"로 변경한다(재구현
    없음, deleted_at 등 다른 필드는 건드리지 않는다)."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    _require_existing(repo, site_id)

    ok, msg = _wizard_set_site_status(cfg, site_id, "inactive")
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return _project(repo, repo.get_by_id(site_id))


def archive_site(site_id: str) -> dict:
    """dashboard.py "🗑️ 삭제(보관 이동)"(dashboard.py:1380-1385)와 동일한 실행
    의미(soft delete) — site_wizard.update_site()로 status="archived"와
    deleted_at=현재 시각 ISO 문자열 두 필드만 설정한다(재구현 없음, row 자체는
    삭제하지 않는다)."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    _require_existing(repo, site_id)

    ok, msg = _wizard_update_site(cfg, site_id, {
        "status": "archived", "deleted_at": datetime.now().isoformat(),
    })
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return _project(repo, repo.get_by_id(site_id))


def restore_site(site_id: str) -> dict:
    """dashboard.py "♻️ 복구"(dashboard.py:1398-1401)와 동일한 실행 의미 —
    site_wizard.update_site()로 status="inactive"(원본 그대로 — "active"가
    아니다, 보관 전 상태를 기억하지 않는 원본의 하드코딩 동작을 그대로
    재현한다)와 deleted_at="" 두 필드만 설정한다(재구현 없음)."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    _require_existing(repo, site_id)

    ok, msg = _wizard_update_site(cfg, site_id, {
        "status": "inactive", "deleted_at": "",
    })
    if not ok:
        raise SiteValidationError(msg)

    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return _project(repo, repo.get_by_id(site_id))


def delete_site_hard(site_id: str, confirmation: str) -> None:
    """dashboard.py "⛔ 영구 삭제"(dashboard.py:1402-1409)와 동일한 실행 의미.
    원본은 텍스트 입력이 정확히 "DELETE"와 일치해야만 실행되는 UI 레벨 확인을
    거친다 — 이 확인을 서버 레이어로 그대로 옮긴다(STEP 18-R의 Trash/Restore
    confirmation 패턴과 동일). site_wizard.delete_site()를 그대로 호출한다
    (재구현 없음) — sites 테이블의 해당 row만 실제 DELETE되며, calculators/
    articles/Registry/HOLD/pending_posts/cost_state/secrets.yaml/config.yaml
    은 어디에서도 참조되지 않는다(모듈 docstring 재확인, STOP 조건 아님 —
    WordPress profile은 삭제되지 않고 고아로 남는 원본의 기존 동작을 그대로
    재현하며, 새 cleanup을 추가하지 않는다)."""
    if confirmation != "DELETE":
        raise SiteValidationError('confirmation 값이 "DELETE"와 일치해야 합니다.')

    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    _require_existing(repo, site_id)

    ok, msg = _wizard_delete_site(cfg, site_id)
    if not ok:
        raise SiteValidationError(msg)


def clone_site(source_site_id: str, fields: dict) -> dict:
    """dashboard.py "📑 복제 실행"(dashboard.py:1424-1433)과 동일한 실행 의미.
    원본 사이트에서 site_tags/research_ai/writing_ai/review_ai 4개 필드만
    복사하고, site_name/domain/WordPress 자격증명은 항상 새로 입력받는다
    (원본과 동일 — WordPress 자격증명은 복제되지 않고 재입력을 강제한다).
    site_wizard.create_site()를 그대로 재사용한다(재구현 없음) — 이 함수가
    호출하는 create_site() 서비스 래퍼(P2-06)에 이미 있는 lock/rollback을
    그대로 통과한다."""
    cfg = load_config()
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    source = repo.get_by_id(source_site_id)
    if source is None:
        raise SiteNotFound(f"사이트를 찾을 수 없습니다: {source_site_id}")

    # site_type -> type_label 역매핑(dashboard.py:1416-1417과 동일한 조회 방식).
    type_label = next(
        (k for k, v in TYPE_DEFS.items() if v["site_type"] == source.get("site_type", "custom")),
        "사용자정의",
    )

    return create_site(type_label, {
        "site_name": fields.get("site_name", ""),
        "domain": fields.get("domain", ""),
        "category": source.get("site_tags", ""),
        "wp_url": fields.get("wp_url", ""),
        "wp_user": fields.get("wp_user", ""),
        "wp_app_password": fields.get("wp_app_password", ""),
        "rss_sources": "",
        "research_ai": source.get("research_ai", ""),
        "writing_ai": source.get("writing_ai", ""),
        "review_ai": source.get("review_ai", ""),
    })
