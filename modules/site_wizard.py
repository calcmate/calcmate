# -*- coding: utf-8 -*-
"""
modules/site_wizard.py — 사이트/계산기 생성 마법사 서비스 (v12 신규)

대시보드에서 코드 수정 없이 새 블로그/계산기/사이트를 추가하기 위한 로직.
- 6개 유형 지원: 블로그 / 계산기 / 정책정보 / 금융 / 제휴마케팅 / 사용자정의
- 유형별 기본 설정(site_type, monetization, content_mode, AI 프로필) 자동 부여
- 블로그/사이트 → sites 시트, 계산기 → calculators 시트 자동 등록
- WordPress 앱 비밀번호는 secrets.yaml(wordpress_profiles)에 저장(보안)
- 검증: 필수값 누락 / 중복 도메인 / 중복 사이트명 차단

각 함수는 (ok: bool, message: str) 를 반환한다.
"""
import json
import re
import uuid
from datetime import datetime

from adapters.db.factory import get_db_adapter, get_calculator_storage_adapter
from repositories.site_repository import SiteRepository
from repositories.calculator_repository import CalculatorRepository
from .logger import get_logger

LOG = get_logger()

# ── 유형 정의 (기본 설정 자동 부여) ───────────────────────────────
#   site_type 은 collector/factory 라우팅 키와 일치해야 한다.
#   (policy / calculator / finance / affiliate / custom)
TYPE_DEFS = {
    "블로그":     {"site_type": "custom",     "monetization": "adsense",   "content_mode": "blog",   "needs_wp": True,  "uses_rss": True},
    "계산기":     {"site_type": "calculator", "monetization": "adsense",   "content_mode": "tool",   "needs_wp": False, "uses_rss": False},
    "정책정보":   {"site_type": "policy",     "monetization": "adsense",   "content_mode": "info",   "needs_wp": True,  "uses_rss": True},
    "금융":       {"site_type": "finance",    "monetization": "affiliate", "content_mode": "info",   "needs_wp": True,  "uses_rss": True},
    "제휴마케팅": {"site_type": "affiliate",  "monetization": "affiliate", "content_mode": "review", "needs_wp": True,  "uses_rss": True},
    "사용자정의": {"site_type": "custom",     "monetization": "adsense",   "content_mode": "blog",   "needs_wp": True,  "uses_rss": True},
}
SITE_TYPES = list(TYPE_DEFS.keys())

# 기본 AI 프로필 (ai_provider.AI_PROFILE_MAP 키와 일치)
DEFAULT_AI = {"research_ai": "gemini_flash", "writing_ai": "gpt4o", "review_ai": "claude_sonnet"}

# collect()가 아직 stub인 유형 (사용자 안내용)
STUB_TYPES = {"finance", "affiliate"}


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", (text or "").strip()).strip("_").lower()
    return s or uuid.uuid4().hex[:6]


def _repos(cfg: dict):
    # STEP109: sites는 기존 get_db_adapter(DualAdapter, Sheets-primary)를 그대로 유지하고,
    # calculators만 get_calculator_storage_adapter(SQLiteFirstAdapter, SQLite MAIN)로 분리한다
    # (STEP108에서 확인된 blind spot 수정 — sites storage 정책은 변경하지 않음).
    site_db = get_db_adapter(cfg)
    calculator_db = get_calculator_storage_adapter(cfg)
    return SiteRepository(site_db, cfg), CalculatorRepository(calculator_db)


# ── 조회 ──────────────────────────────────────────────────────────
def list_sites(cfg: dict) -> list:
    site_repo, _ = _repos(cfg)
    return site_repo.get_all()


def list_calculators(cfg: dict) -> list:
    _, calc_repo = _repos(cfg)
    return calc_repo.get_all()


# ── 검증 ──────────────────────────────────────────────────────────
def _validate_site(cfg: dict, site_name: str, domain: str, required: dict) -> str | None:
    """필수값/중복 검증. 오류 메시지(str) 또는 None(정상)."""
    for label, val in required.items():
        if not str(val or "").strip():
            return f"필수값 누락: {label}"
    try:
        existing = list_sites(cfg)
    except Exception as e:
        return f"기존 사이트 조회 실패(시트 권한 확인): {e}"
    name_l = site_name.strip().lower()
    dom_l = (domain or "").strip().lower()
    for s in existing:
        if str(s.get("site_name", "")).strip().lower() == name_l:
            return f"중복 사이트명: '{site_name}' 이미 등록됨"
        if dom_l and str(s.get("domain", "")).strip().lower() == dom_l:
            return f"중복 도메인: '{domain}' 이미 등록됨"
    return None


# ── 생성: 블로그/정책/금융/제휴/사용자정의 (sites 시트) ───────────
def create_site(cfg: dict, type_label: str, fields: dict) -> tuple:
    """sites 시트에 사이트 1건 등록. type_label 은 TYPE_DEFS 키."""
    if type_label not in TYPE_DEFS:
        return False, f"알 수 없는 유형: {type_label}"
    spec = TYPE_DEFS[type_label]

    site_name = (fields.get("site_name") or "").strip()
    domain    = (fields.get("domain") or "").strip()
    category  = (fields.get("category") or "").strip()

    # 필수값: 사이트명 + 도메인 (+ WP 필요 유형은 WP 3종)
    required = {"사이트명": site_name, "도메인": domain}
    if spec["needs_wp"]:
        required.update({
            "WordPress URL": fields.get("wp_url"),
            "WordPress ID": fields.get("wp_user"),
            "App Password": fields.get("wp_app_password"),
        })
    err = _validate_site(cfg, site_name, domain, required)
    if err:
        return False, err

    site_repo, _ = _repos(cfg)
    # 같은 초에 여러 사이트를 만들어도 충돌하지 않도록 uuid 접미사
    site_id = "site_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]

    # WP 프로필 → secrets.yaml
    profile_id = ""
    if spec["needs_wp"] and (fields.get("wp_url") or "").strip():
        profile_id = "wp_" + _slug(site_name)
        try:
            site_repo.save_wp_profile(
                profile_id,
                fields.get("wp_url", "").strip(),
                fields.get("wp_user", "").strip(),
                fields.get("wp_app_password", "").strip(),
            )
        except Exception as e:
            return False, f"WP 자격증명 저장 실패(secrets.yaml): {e}"

    # rss_sources: 콤마구분 문자열 → JSON 배열 문자열
    rss_raw = (fields.get("rss_sources") or "").strip()
    rss_list = [u.strip() for u in re.split(r"[,\n]", rss_raw) if u.strip()] if rss_raw else []

    row = {
        "site_id": site_id,
        "site_name": site_name,
        "domain": domain,
        "site_type": spec["site_type"],
        "monetization_type": spec["monetization"],
        "wordpress_url": fields.get("wp_url", "").strip() if spec["needs_wp"] else "",
        "wordpress_profile_id": profile_id,
        "rss_sources": json.dumps(rss_list, ensure_ascii=False),
        "content_mode": (fields.get("content_mode") or spec["content_mode"]),
        "research_ai": fields.get("research_ai") or DEFAULT_AI["research_ai"],
        "writing_ai":  fields.get("writing_ai")  or DEFAULT_AI["writing_ai"],
        "review_ai":   fields.get("review_ai")   or DEFAULT_AI["review_ai"],
        "publish_mode": "auto",
        "site_tags": category,
        "site_priority": "5",
        "status": "active",
        "created_at": datetime.now().isoformat(),
    }
    try:
        site_repo.save(row)
    except Exception as e:
        return False, f"sites 시트 등록 실패(시트 권한 확인): {e}"

    note = ""
    if spec["site_type"] in STUB_TYPES:
        note = f" (참고: '{spec['site_type']}' 수집기는 아직 미구현 — 수집 0건)"
    LOG.info("사이트 등록: %s (%s, %s)", site_name, type_label, site_id)
    return True, f"✅ '{site_name}' 등록 완료 [{type_label}/{spec['site_type']}]{note}"


# ── 생성: 계산기 (calculators 시트) ───────────────────────────────
def create_calculator(cfg: dict, fields: dict) -> tuple:
    name = (fields.get("name") or "").strip()
    desc = (fields.get("description") or "").strip()
    category = (fields.get("category") or "").strip()
    if not name:
        return False, "필수값 누락: 계산기명"

    _, calc_repo = _repos(cfg)
    try:
        existing = calc_repo.get_all()
    except Exception as e:
        return False, f"기존 계산기 조회 실패(시트 권한 확인): {e}"
    if any(str(c.get("name", "")).strip().lower() == name.lower() for c in existing):
        return False, f"중복 계산기명: '{name}' 이미 등록됨"

    row = {
        "name": name,
        "slug": _slug(name),
        "category": category,
        "calculator_type": "general",
        "seo_desc": desc,
        "site_id": (fields.get("site_id") or "").strip(),
        "status": "active",   # 수집기에 즉시 노출되도록 active
    }
    try:
        calc_repo.save(row)
    except Exception as e:
        return False, f"calculators 시트 등록 실패(시트 권한 확인): {e}"
    LOG.info("계산기 등록: %s", name)
    return True, f"✅ 계산기 '{name}' 등록 완료"


# ── 관리: 상태변경 / 삭제 ─────────────────────────────────────────
def set_site_status(cfg: dict, site_id: str, status: str) -> tuple:
    site_repo, _ = _repos(cfg)
    try:
        site_repo.update_status(site_id, status)
        return True, f"상태 변경: {site_id} → {status}"
    except Exception as e:
        return False, f"상태 변경 실패: {e}"


def update_site(cfg: dict, site_id: str, data: dict) -> tuple:
    site_repo, _ = _repos(cfg)
    try:
        site_repo.update(site_id, data)
        return True, f"수정 완료: {site_id}"
    except Exception as e:
        return False, f"수정 실패: {e}"


def delete_site(cfg: dict, site_id: str) -> tuple:
    site_repo, _ = _repos(cfg)
    try:
        site_repo.delete(site_id)
        return True, f"삭제 완료: {site_id}"
    except Exception as e:
        return False, f"삭제 실패: {e}"


def delete_calculator(cfg: dict, calc_id: str) -> tuple:
    # STEP109: calculators 삭제는 get_calculator_storage_adapter(SQLite MAIN)로 라우팅한다.
    db = get_calculator_storage_adapter(cfg)
    try:
        db.delete("calculators", calc_id)
        return True, f"계산기 삭제 완료: {calc_id}"
    except Exception as e:
        return False, f"계산기 삭제 실패: {e}"
