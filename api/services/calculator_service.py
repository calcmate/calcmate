"""api/services/calculator_service.py — Calculator 조회 서비스 (STEP 18-F).

기존 CalculatorRepository / modules.registry_loader / modules.site_snapshot를 그대로
호출한다. 이번 STEP은 조회 전용이며 생성/삭제/배포 로직은 이 파일에 존재하지 않는다.

dashboard.py의 "🧮 계산기 관리" 탭(dashboard.py:1457-1948)과 동일한 필터를 사용한다:
Registry v3(docs/registry/*.yaml)에 등록된 slug만 노출한다(Golden10 documents/howto처럼
calculators 테이블에는 있지만 Registry v3에는 없는 행은 목록에서 제외 — 기존 화면과 동일 동작).
"""
import json

from modules.config_loader import load_config
from adapters.db.factory import get_calculator_storage_adapter
from repositories.calculator_repository import CalculatorRepository
from modules.registry_loader import load_registry_v3
from modules.site_snapshot import read_site_snapshot

_ARTICLE_PREVIEW_MAX_LEN = 2000


class CalculatorNotFound(Exception):
    """요청한 slug가 Registry v3 또는 DB에 없는 경우."""


class CalculatorFormulaValidationError(Exception):
    """modules.formula_engine.validate_formula()가 실패한 경우. 메시지를 그대로 전달한다."""


class CalculatorPromoteError(Exception):
    """modules.app_factory.promote_to_ready()가 (False, msg)를 반환한 경우.
    체크리스트 미완료 / App Factory 계산기가 아님 / Registry 파일 읽기 실패 등을
    전부 이 예외 하나로 통일해 라우터에서 400으로 매핑한다."""


class CalculatorChecklistError(Exception):
    """알 수 없는 체크리스트 항목 id / App Factory 계산기가 아님 / Registry 파일
    읽기 실패 등 modules.app_factory.save_af_checklist()가 raise하는 ValueError·
    RuntimeError를 이 예외 하나로 통일해 라우터에서 400으로 매핑한다."""


def _repo_and_cfg():
    cfg = load_config()
    return CalculatorRepository(get_calculator_storage_adapter(cfg)), cfg


def _registry() -> dict:
    return load_registry_v3(force=True)


def _summarize(calc: dict, v3_reg: dict) -> dict:
    slug = calc.get("slug", "")
    v3e = v3_reg.get(slug) or {}
    is_hold = v3e.get("source") == "app_factory" and v3e.get("status") == "HOLD"
    return {
        "id": calc.get("id", ""),
        "slug": slug,
        "name": calc.get("name", ""),
        "db_status": calc.get("status", ""),
        "updated_at": calc.get("updated_at", ""),
        "published_url": calc.get("published_url", ""),
        "is_deployed": bool(calc.get("published_url")),
        "registry_status": v3e.get("status"),
        "is_legal_hold": is_hold,
        "tier": v3e.get("tier"),
    }


def _get_calc_or_raise(slug: str):
    repo, cfg = _repo_and_cfg()
    v3_reg = _registry()
    if slug not in v3_reg:
        raise CalculatorNotFound(slug)
    calc = repo.get_by_slug(slug)
    if not calc:
        raise CalculatorNotFound(slug)
    return calc, v3_reg, cfg


def list_calculators() -> list:
    repo, _cfg = _repo_and_cfg()
    v3_reg = _registry()
    calcs = [c for c in repo.get_all() if c.get("slug") in v3_reg]
    return [_summarize(c, v3_reg) for c in calcs]


def get_calculator(slug: str) -> dict:
    calc, v3_reg, _cfg = _get_calc_or_raise(slug)
    return _summarize(calc, v3_reg)


def get_calculator_content(slug: str) -> dict:
    """콘텐츠는 원문 그대로 반환한다(서버에서 HTML을 해석/삽입하지 않음).
    프런트엔드가 텍스트로만 렌더링해 XSS를 방지하는 것을 전제로 한다."""
    calc, _v3_reg, _cfg = _get_calc_or_raise(slug)

    faq = calc.get("faq")
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except (ValueError, TypeError):
            faq = None

    article = calc.get("article_content") or ""
    truncated = len(article) > _ARTICLE_PREVIEW_MAX_LEN

    return {
        "seo_title": calc.get("seo_title", ""),
        "seo_description": calc.get("seo_description") or calc.get("seo_desc", ""),
        "faq": faq,
        "article_content": article[:_ARTICLE_PREVIEW_MAX_LEN],
        "article_length": len(article),
        "article_truncated": truncated,
    }


def _parse_json_field(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else default
    except (ValueError, TypeError):
        return default


def get_calculator_formula(slug: str) -> dict:
    """STEP 4-G: 수식 편집 화면 전용 조회. 내부 filesystem 경로/Registry 전체/
    secret은 포함하지 않는다(§5) — dashboard.py:1606-1607과 동일한 필드만 노출."""
    calc, _v3_reg, _cfg = _get_calc_or_raise(slug)
    return {
        "slug": slug,
        "name": calc.get("name", ""),
        "formula": calc.get("formula", ""),
        "input_schema": _parse_json_field(calc.get("input_schema"), {}),
        "updated_at": calc.get("updated_at", ""),
    }


def update_calculator_formula(slug: str, formula: str) -> dict:
    """dashboard.py:1614-1619와 동일한 순서(검증 → 성공 시에만 저장)를 그대로
    재사용한다. 실제 검증/저장은 modules.formula_engine.validate_formula()/
    save_formula()가 전담하며, 이 함수는 새 검증/저장 로직을 만들지 않는다.
    검증 실패 시 save_formula()가 호출되지 않으므로 기존 formula 값은
    손상되지 않는다(§9 원자성 원칙 — validate 실패 경로에 write가 없다)."""
    from modules import formula_engine

    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    input_schema = _parse_json_field(calc.get("input_schema"), {})
    ok, msg = formula_engine.validate_formula(formula, input_schema, slug=slug)
    if not ok:
        raise CalculatorFormulaValidationError(msg)
    formula_engine.save_formula(cfg, calc.get("id", ""), formula)
    return get_calculator_formula(slug)


def promote_calculator_to_ready(slug: str) -> dict:
    """dashboard.py의 '✅ READY 전환' 버튼(dashboard.py:1598-1604)과 동일하게
    modules.app_factory.promote_to_ready()를 그대로 재사용한다. 새 Registry 저장
    로직을 만들지 않는다 — Registry 조작(파일 읽기/쓰기/invalidate)은 전부
    promote_to_ready() 내부에 위임한다. 이 함수는 DB를 전혀 읽거나 쓰지 않는다
    (promote_to_ready() 자체가 v3 Registry만 다루고 calculators DB는 건드리지 않음)."""
    from modules import app_factory

    # slug 존재 확인은 기존 헬퍼를 그대로 재사용(다른 조회 endpoint와 동일한 404 규약).
    _get_calc_or_raise(slug)

    ok, msg = app_factory.promote_to_ready(slug)
    if not ok:
        raise CalculatorPromoteError(msg)
    return {"slug": slug, "status": "READY", "message": msg}


def get_calculator_checklist(slug: str) -> dict:
    """dashboard.py:1532의 AF_CM.get_af_checklist() 호출과 동일하다. 새 계산/
    집계 로직을 만들지 않는다 — critical/advisory 분류나 완료 개수 집계는
    프런트엔드가 items를 그대로 받아 계산한다(dashboard.py:1536-1538과 동일한
    책임 분리)."""
    from modules import app_factory

    _get_calc_or_raise(slug)
    return {"slug": slug, "items": app_factory.get_af_checklist(slug)}


def update_calculator_checklist(slug: str, items: list, actor_id: str) -> dict:
    """dashboard.py:1543-1591 체크박스 토글 로직과 동일한 갱신 규칙을 그대로
    재현한다: checked 값이 실제로 바뀐 항목만 checked_by/checked_at을 갱신하고
    (dashboard.py:1554-1562), label/severity/display_value/auto_source 등
    나머지 필드는 절대 건드리지 않는다. 실제 파일 읽기/쓰기/invalidate는 전부
    modules.app_factory.save_af_checklist()에 위임 — 여기서 Registry를 직접
    읽거나 쓰지 않는다."""
    from datetime import datetime, timezone
    from modules import app_factory

    _get_calc_or_raise(slug)
    current = app_factory.get_af_checklist(slug)
    by_id = {i.get("id"): i for i in current}

    unknown = [i["id"] for i in items if i.get("id") not in by_id]
    if unknown:
        raise CalculatorChecklistError(f"알 수 없는 체크리스트 항목 id: {unknown}")

    for patch_item in items:
        target = by_id[patch_item["id"]]
        new_checked = bool(patch_item["checked"])
        if bool(target.get("checked")) != new_checked:
            target["checked"] = new_checked
            target["checked_by"] = actor_id if new_checked else None
            target["checked_at"] = (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if new_checked else None
            )

    try:
        app_factory.save_af_checklist(slug, current)
    except (ValueError, RuntimeError) as e:
        raise CalculatorChecklistError(str(e))

    return {"slug": slug, "items": current}


def get_calculator_status(slug: str) -> dict:
    calc, v3_reg, cfg = _get_calc_or_raise(slug)
    v3e = v3_reg.get(slug) or {}
    is_hold = v3e.get("source") == "app_factory" and v3e.get("status") == "HOLD"
    snapshot = read_site_snapshot(cfg, calc)

    return {
        "db_status": calc.get("status", ""),
        "registry_status": v3e.get("status"),
        "is_legal_hold": is_hold,
        "tier": v3e.get("tier"),
        "has_content": bool(calc.get("article_content")),
        "has_static_site": bool(snapshot),
        "static_files": sorted(snapshot.keys()),
        "published_url": calc.get("published_url", ""),
        "is_deployed": bool(calc.get("published_url")),
    }


class CalculatorGenerateBusyError(Exception):
    """GenerationJobStore가 이미 다른 생성 작업을 실행 중이라 이번 요청을
    거부한 경우(STEP 4-H-4에서 확정한 max_concurrent=1 정책 — 큐잉하지 않고
    즉시 거부). 라우터에서 409로 매핑한다."""


def submit_calculator_generation(
    name: str, category: str, description: str, tier: int, slug: str | None,
) -> dict:
    """dashboard.py '🏭 자동 생성'(Mode A) 버튼과 동일하게 modules.app_factory의
    generate_app()/save_app()을 순서대로, 변경 없이 그대로 호출하는 target을
    api.services.generation_job_store.GenerationJobStore에 제출한다(STEP 4-H-4에서
    확정한 Job 구조/동시성 정책을 그대로 재사용 — 새로 설계하지 않음).

    실제 생성/저장은 백그라운드 스레드에서 실행된다. cfg(비밀 정보 포함)는 이
    함수의 클로저(target) 안에서만 존재하며 Job 객체·API 응답 어디에도 저장되지
    않는다 — Job.result에는 slug/name/message만 담는다(§4/§6).

    ── STEP 4-H-7: Formula Hard Gate ────────────────────────────────────
    generate_app()은 내부적으로 이미 modules.formula_engine.validate_formula()를
    호출해(_suggest_spec()) 결과를 app["_formula_valid"]/app["_formula_msg"]에
    담아 반환한다. dashboard.py의 Mode A 수동 저장 경로는 이 값을 화면에 경고로만
    보여주고 사람이 판단해 저장 버튼을 누르지만(운영자 검토 존재), 이 자동 API
    경로에는 사람이 없어 그 경고가 아무 효과도 없었다 — 검증되지 않은 formula가
    그대로 save_app()까지 통과할 수 있었다(STEP 4-H-7에서 발견). 새 validator를
    만들지 않고, 이미 계산된 이 플래그를 여기서 그대로 확인해 실패 시 저장 자체를
    막는다. save_app()이 (False, msg)를 반환하면(실패) target이 RuntimeError(msg)를
    던져 GenerationJobStore가 이를 status=failed로 기록하게 한다 — save_app() 자체의
    로직(락, 고아 자동정리 등)은 전혀 건드리지 않는다.

    ── P0-1: HTML/JS 생성 완결성 검증 게이트 ────────────────────────────
    generate_app()의 "code"(HTML) 단계가 AI 응답 토큰 한도 부근에서 잘려도
    Formula Hard Gate는 formula만 검사하므로 통과할 수 있었다 — 실측(React
    수동 생성 E2E)으로 이 상태의 HTML이 save_app()까지 도달함을 확인했다.
    modules.review_center.validate_html_js_completeness()(신규, pre_build_qa()와
    동일한 step/label/passed/skipped/detail 리스트 반환)를 Formula Hard Gate
    바로 뒤·save_app() 호출 직전에 추가해 동일한 방식(RuntimeError→Job
    status=failed)으로 차단한다. 이 함수가 검사하는 대상은 generate_app()이
    만든 raw AI HTML(app["html"])이며, app_generator.generate_calculator()가
    배포용으로 별도로 만드는 템플릿 HTML과는 다른 대상이다 — 혼동하지 않는다.
    """
    from modules.config_loader import load_config
    from modules import app_factory
    from modules.review_center import validate_html_js_completeness
    from api.services.generation_job_store import get_job_store

    def _target() -> dict:
        cfg = load_config()
        app = app_factory.generate_app(cfg, name, category=category, desc=description, tier=tier)
        if not app.get("_formula_valid", True):
            raise RuntimeError(f"formula 검증 실패: {app.get('_formula_msg', '')}")
        _html_ok, _html_msg, _html_steps = validate_html_js_completeness(app.get("html", ""))
        if not _html_ok:
            raise RuntimeError(_html_msg)
        ok, msg = app_factory.save_app(cfg, app, slug=slug)
        if not ok:
            raise RuntimeError(msg)
        resolved_slug = (slug or "").strip().lower() or app_factory._slug(name)
        return {"slug": resolved_slug, "name": name, "message": msg}

    store = get_job_store()
    accepted, message, job_id = store.submit(name, _target)
    if not accepted:
        raise CalculatorGenerateBusyError(message)
    job = store.get(job_id)
    return job.to_public_dict()


def get_calculator_generation_job(job_id: str) -> dict:
    """POST /api/calculators/generate가 만든 Job의 현재 상태를 조회한다.
    존재하지 않는 job_id는 CalculatorNotFound로 통일해 라우터가 404로 매핑하게 한다."""
    from api.services.generation_job_store import get_job_store

    job = get_job_store().get(job_id)
    if job is None:
        raise CalculatorNotFound(job_id)
    return job.to_public_dict()


# ══════════════════════════════════════════════════════════════════════════
# P0-2: Build/Deploy — dashboard.py "🧮 계산기 관리" 탭의 "🧮 생성"→QA→"🚀 배포"
# 흐름과 동일한 함수를 재사용한다(modules/app_generator.py, modules/review_center.py,
# modules/github_deployer.py, modules/site_snapshot.py — 전부 기존 코드, 새 생성/QA/
# 배포 로직을 만들지 않음). Streamlit과 달리 여기서는 사람이 화면 사이를 오가며
# 상태를 유지할 수 없으므로(무상태 API), build_calculator()가 매 호출마다
# generate→HTML완결성(P0-1)→Formula→pre_build_qa를 전부 새로 실행해 항상 "지금
# DB 상태 기준" 결과를 반환한다 — 이전 호출의 스냅샷을 신뢰하지 않는다.
# ══════════════════════════════════════════════════════════════════════════

def build_calculator(slug: str) -> dict:
    """계산기 1건의 정적 웹앱(index.html/style.css/script.js)을 재생성하고,
    Formula Hard Gate + HTML/JS 완결성(P0-1) + 기존 pre_build_qa(10단계)를
    전부 통과한 경우에만 data/workspace/_site/{slug}/에 스냅샷을 쓴다.

    반환 dict의 "ok"가 False면 스냅샷은 쓰지 않는다(호출측은 성공으로
    간주하거나 DB/Registry를 변경하면 안 된다)."""
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    from modules import app_generator as AG
    from modules.review_center import validate_html_js_completeness, pre_build_qa
    from modules.site_snapshot import write_site_snapshot

    prev_files = read_site_snapshot(cfg, calc)
    try:
        files = AG.generate_calculator(calc, cfg)
    except Exception as e:
        return {
            "ok": False, "slug": slug, "stage": "generate",
            "message": f"HTML/CSS/JS 생성 실패: {e}",
            "formula_valid": None, "formula_message": None,
            "html_completeness": None, "qa_steps": [], "snapshot_dir": None,
        }

    formula_ok = bool(files.get("_formula_valid", True))
    formula_msg = files.get("_formula_msg", "")

    html_ok, html_msg, html_steps = validate_html_js_completeness(files.get("index.html", ""))

    qa_steps = pre_build_qa(calc, cfg, prev_files=prev_files)
    qa_ok = all(s["passed"] or s["skipped"] for s in qa_steps)

    all_ok = formula_ok and html_ok and qa_ok
    snapshot_dir = None
    if all_ok:
        snapshot_dir = write_site_snapshot(cfg, calc, files)

    return {
        "ok": all_ok,
        "slug": slug,
        "stage": "build",
        "message": "✅ Build 완료" if all_ok else "❌ Build 차단 — 아래 검사 결과를 확인하세요",
        "formula_valid": formula_ok,
        "formula_message": formula_msg,
        "html_completeness": {"ok": html_ok, "message": html_msg, "steps": html_steps},
        "qa_ok": qa_ok,
        "qa_steps": qa_steps,
        "snapshot_dir": snapshot_dir,
    }


def _snapshot_hash(files: dict) -> str:
    """스냅샷(index.html+style.css+script.js) 내용의 SHA-256 해시. Human Review
    Approval을 "지금 이 순간의 정확한 빌드 결과"에 귀속시키기 위한 식별자로 사용한다
    (신규 build_id/버전 스키마를 만들지 않고 기존 스냅샷 파일 내용만으로 계산)."""
    import hashlib
    combined = (files.get("index.html", "") or "") + (files.get("style.css", "") or "") + (files.get("script.js", "") or "")
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get_calculator_review_status(slug: str) -> dict:
    """Human Review Approval 현재 상태를 조회한다. 승인은 "현재 스냅샷 해시"와
    정확히 일치할 때만 유효하다 — Build가 다시 실행되어 스냅샷 내용이 바뀌면
    (해시 불일치) 자동으로 무효화된다(재검수 필요)."""
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    files = read_site_snapshot(cfg, calc)
    has_snapshot = bool(files.get("index.html"))
    current_hash = _snapshot_hash(files) if has_snapshot else None

    from api.services.review_approval_store import get_review_approval_store
    appr = get_review_approval_store().get(slug)
    approved_for_current = bool(has_snapshot and appr and appr.snapshot_hash == current_hash)
    return {
        "slug": slug,
        "has_snapshot": has_snapshot,
        "approved": approved_for_current,
        "approved_by": appr.approved_by if (appr and approved_for_current) else None,
        "approved_at": appr.approved_at if (appr and approved_for_current) else None,
        # stale: 예전에 승인은 했었지만 이후 Build 결과가 달라져(재빌드) 그 승인이
        # 더 이상 현재 스냅샷에 대해 유효하지 않은 상태 — React가 "재검수 필요"로 구분 표시.
        "stale": bool(appr and not approved_for_current),
    }


def approve_calculator_review(slug: str, actor_id: str) -> dict:
    """dashboard.py "✅ 검수 승인" 버튼과 동일한 안전 의미: QA PASS 상태에서만
    승인 가능하다(QA 실패 시 검수 단계로 진행 불가 — dashboard.py:1772-1773).
    build_calculator()를 그대로 재사용해 승인 시점의 최신 스냅샷을 확정하고,
    그 스냅샷 내용의 해시를 승인에 귀속시킨다."""
    _get_calc_or_raise(slug)
    build_result = build_calculator(slug)
    if not build_result["ok"]:
        return {
            "ok": False, "slug": slug,
            "blocked_reason": "🔒 QA 실패 — 사람 검수 단계로 진행할 수 없습니다. Build 결과를 확인하세요.",
            "build_result": build_result,
        }

    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    files = read_site_snapshot(cfg, calc)
    snapshot_hash = _snapshot_hash(files)

    from api.services.review_approval_store import get_review_approval_store
    appr = get_review_approval_store().approve(slug, snapshot_hash, actor_id)
    return {
        "ok": True, "slug": slug, "approved_by": appr.approved_by, "approved_at": appr.approved_at,
        "build_result": build_result,
    }


def unapprove_calculator_review(slug: str) -> dict:
    """dashboard.py "↩️ 승인 취소" 버튼과 동일."""
    _get_calc_or_raise(slug)
    from api.services.review_approval_store import get_review_approval_store
    get_review_approval_store().unapprove(slug)
    return {"ok": True, "slug": slug}


def deploy_calculator(slug: str) -> dict:
    """빌드 게이트를 전부 통과한 경우에만 modules.github_deployer.deploy_app()을
    호출해 GitHub Pages에 배포한다. HOLD 상태 또는 needs_human_legal=true인
    계산기는 build_calculator()조차 호출하지 않고 즉시 차단한다(법적 미검증
    콘텐츠가 실수로도 배포되지 않도록 가장 먼저 확인).

    STEP S1: dashboard.py의 "👤 사람 검수" 단계(QA PASS 후 운영자가 명시적으로
    승인해야 배포 가능 — dashboard.py:1753-1796)가 React/FastAPI 경로에는 없어서
    Build 성공만으로 즉시 배포가 가능했던 안전 게이트 약화를 여기서 복원한다.
    HOLD/needs_human_legal 체크 및 build_calculator() 재사용 순서는 무변경."""
    calc, v3_reg, cfg = _get_calc_or_raise(slug)
    v3e = v3_reg.get(slug) or {}

    is_hold = v3e.get("source") == "app_factory" and v3e.get("status") == "HOLD"
    if is_hold:
        return {
            "ok": False, "slug": slug, "stage": "gate",
            "blocked_reason": "🔒 HOLD 상태 — Legal Hold 검토 완료(READY 전환) 전에는 배포할 수 없습니다.",
            "build_result": None, "published_url": None,
        }

    from modules.registry_loader import load_registry
    auto_entry = load_registry(force=True).get(slug) or {}
    if auto_entry.get("needs_human_legal"):
        return {
            "ok": False, "slug": slug, "stage": "gate",
            "blocked_reason": "🔒 needs_human_legal=true — 법적 근거 검토가 아직 완료되지 않았습니다.",
            "build_result": None, "published_url": None,
        }

    build_result = build_calculator(slug)
    if not build_result["ok"]:
        return {
            "ok": False, "slug": slug, "stage": "build",
            "blocked_reason": "🔒 Build 실패 — 배포 전 검증(Formula/HTML완결성/QA)을 통과하지 못했습니다.",
            "build_result": build_result, "published_url": None,
        }

    # Human Review Approval — 클라이언트가 보내는 값을 신뢰하지 않고, 서버가 기억하는
    # 승인이 "방금 확정한 이 스냅샷"과 정확히 일치하는지 재확인한다.
    files_for_review = read_site_snapshot(cfg, calc)
    current_hash = _snapshot_hash(files_for_review)
    from api.services.review_approval_store import get_review_approval_store
    if not get_review_approval_store().is_approved_for(slug, current_hash):
        return {
            "ok": False, "slug": slug, "stage": "review",
            "blocked_reason": "🔒 사람 검수 승인이 필요합니다 — 검수 승인 후 다시 시도하세요"
                               "(직전 승인 이후 Build 결과가 변경되었다면 재승인이 필요합니다).",
            "build_result": build_result, "published_url": None,
        }

    from modules import github_deployer as GH
    files = read_site_snapshot(cfg, calc)
    deploy_ok, deploy_result = GH.deploy_app(
        cfg, files, repo=cfg.get("GITHUB_REPO", "salarymate-calculators"), subdir=slug,
    )
    if deploy_ok:
        repo, _cfg2 = _repo_and_cfg()
        repo.publish(calc.get("id"), deploy_result)
        return {
            "ok": True, "slug": slug, "stage": "deploy",
            "message": f"✅ 배포 완료: {deploy_result}",
            "build_result": build_result, "published_url": deploy_result,
        }
    return {
        "ok": False, "slug": slug, "stage": "deploy",
        "blocked_reason": f"❌ 배포 실패: {deploy_result}",
        "build_result": build_result, "published_url": None,
    }


def preview_calculator(slug: str) -> dict:
    """data/workspace/_site/{slug}/에 build_calculator()가 실제로 쓴 확정 스냅샷을
    dashboard.py "🔎 앱 미리보기"와 동일한 modules.app_generator.render_inline_calculator()
    로 자체완결 HTML(CSS/JS 인라인)로 변환한다.

    write_site_snapshot()은 build_calculator()의 all_ok=True 분기에서만 호출되므로,
    스냅샷 파일 존재 자체가 "마지막으로 성공한 Build 결과"를 의미한다 — Streamlit
    미리보기(session_state의 QA-미검증 결과도 그대로 보여줌)보다 엄격하게, 실제
    QA를 통과한 산출물만 미리보기 가능으로 표시한다. Preview는 재생성을 수행하지
    않는다(그건 Build 버튼의 역할) — 순수 조회."""
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    files = read_site_snapshot(cfg, calc)

    if not files.get("index.html"):
        return {
            "slug": slug, "previewable": False, "build_status": "not_built",
            "message": "빌드 결과가 없습니다 — 먼저 🧮 Build를 실행하세요.",
            "html": None,
        }

    from modules.app_generator import render_inline_calculator
    try:
        fragment = render_inline_calculator(files)
    except Exception as e:
        return {
            "slug": slug, "previewable": False, "build_status": "render_error",
            "message": f"미리보기 렌더링 실패: {e}",
            "html": None,
        }

    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"</head><body>{fragment}</body></html>"
    )
    return {
        "slug": slug, "previewable": True, "build_status": "built",
        "message": "✅ 미리보기 가능",
        "html": html,
    }


# ═══════════════════════════════════════════════════════════════════════════
# P0-4: 콘텐츠 생성(SEO/FAQ/본문/이미지/전체) — React/FastAPI 이관
#
# dashboard.py "🤖 AI 자동 생성" 4개 개별 버튼 + "⚡ 전체 자동생성" 버튼과 동일한
# 생성기(modules.calculator_seo_generator/calculator_faq_generator/
# content.calculator.writer/modules.calculator_image_prompt_generator)를 재사용한다.
#
# 레거시(dashboard.py)와의 의도적 차이(운영 안전성 우선, 기존 동작을 그대로 복사하지
# 않음):
#   1) 개별 4개 버튼은 QA 없이 곧바로 repo.update_generated()를 호출했다 — 여기서는
#      modules.content_qa.run_generation_qa()(빈 콘텐츠/mock 시그니처/cross-calculator
#      contamination)를 모든 endpoint에서 저장 전 게이트로 강제한다.
#   2) "⚡ 전체 자동생성"(auto_generate_all)은 AI Review가 NEEDS_REVIEW여도 항상
#      저장했다 — 여기서는 review_status가 AUTO_APPROVED/AUTO_REWRITTEN일 때만 저장한다.
#   3) 본문(article)의 G-LEGAL-CURRENT는 레거시에서 비차단 warning이었다 — 본문의
#      법적 민감도를 고려해 여기서는 저장 차단 조건으로 승격한다.
#   4) Golden10 보호는 레거시에서 4개 개별 버튼에만 적용되고 있었다(STEP 28-222 주석
#      참고) — 여기서는 5개 endpoint(SEO/FAQ/본문/이미지/전체) 전부에 동일하게 적용한다.
# ═══════════════════════════════════════════════════════════════════════════

def _content_generation_blocked_reason(slug: str) -> str | None:
    """Golden10 보호 콘텐츠는 생성 자체를 시작하지 않는다(레거시 dashboard.py와 동일 정책)."""
    from content.blog import is_golden10
    if is_golden10(slug):
        return "🔒 Golden10 보호 콘텐츠 — 콘텐츠 자동 생성/저장이 차단되었습니다."
    return None


def _other_calculator_names(exclude_slug: str) -> list:
    """cross-calculator contamination 검사용 — Registry v3에 등록된 다른 계산기 이름 목록."""
    repo, _cfg = _repo_and_cfg()
    v3_reg = _registry()
    return [
        c.get("name", "") for c in repo.get_all()
        if c.get("slug") in v3_reg and c.get("slug") != exclude_slug and c.get("name")
    ]


def generate_calculator_content_seo(slug: str) -> dict:
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    blocked = _content_generation_blocked_reason(slug)
    if blocked:
        return {"ok": False, "slug": slug, "saved": False, "blocked_reason": blocked,
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules import calculator_seo_generator as SEOG
    try:
        seo = {"seo_title": SEOG.generate_seo_title(cfg, calc),
               "seo_description": SEOG.generate_meta_description(cfg, calc)}
    except Exception as e:
        return {"ok": False, "slug": slug, "saved": False,
                "blocked_reason": f"SEO 생성 실패: {e}",
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules.content_qa import run_generation_qa
    qa_ok, qa_fails = run_generation_qa(calc, seo=seo, other_calc_names=_other_calculator_names(slug))
    result = {
        "ok": True, "slug": slug, "saved": False,
        "blocked_reason": None if qa_ok else "QA 실패 — 저장하지 않음(아래 실패 목록 확인)",
        "qa": {"ok": qa_ok, "failed": qa_fails},
        "content": seo,
    }
    if qa_ok:
        repo, _cfg2 = _repo_and_cfg()
        repo.update_generated(calc["id"], seo)
        result["saved"] = True
    return result


def generate_calculator_content_faq(slug: str) -> dict:
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    blocked = _content_generation_blocked_reason(slug)
    if blocked:
        return {"ok": False, "slug": slug, "saved": False, "blocked_reason": blocked,
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules.calculator_faq_generator import generate_faq
    try:
        faq = generate_faq(cfg, calc)
    except Exception as e:
        return {"ok": False, "slug": slug, "saved": False,
                "blocked_reason": f"FAQ 생성 실패: {e}",
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules.content_qa import run_generation_qa
    qa_ok, qa_fails = run_generation_qa(calc, faq=faq, other_calc_names=_other_calculator_names(slug))
    result = {
        "ok": True, "slug": slug, "saved": False,
        "blocked_reason": None if qa_ok else "QA 실패 — 저장하지 않음(아래 실패 목록 확인)",
        "qa": {"ok": qa_ok, "failed": qa_fails},
        "content": {"faq": faq},
    }
    if qa_ok:
        repo, _cfg2 = _repo_and_cfg()
        repo.update_generated(calc["id"], {"faq": json.dumps(faq, ensure_ascii=False)})
        result["saved"] = True
    return result


def generate_calculator_content_body(slug: str) -> dict:
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    blocked = _content_generation_blocked_reason(slug)
    if blocked:
        return {"ok": False, "slug": slug, "saved": False, "blocked_reason": blocked,
                "qa": {"ok": False, "failed": []}, "content": None}

    from content.calculator.writer import generate_article
    try:
        from modules.law_ssot import get_ssot_prompt_block
        law_block = get_ssot_prompt_block(slug)
    except Exception:
        law_block = ""
    try:
        article = generate_article(cfg, calc, law_ssot_block=law_block)
    except Exception as e:
        return {"ok": False, "slug": slug, "saved": False,
                "blocked_reason": f"본문 생성 실패: {e}",
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules.content_qa import run_generation_qa
    qa_ok, qa_fails = run_generation_qa(
        calc, article=article, other_calc_names=_other_calculator_names(slug), require_article=True)

    from modules.content_integrity import check_g_legal_current
    try:
        legal_fails = check_g_legal_current(article, slug)
    except Exception as e:
        legal_fails = [{"gate": "G-LEGAL-CURRENT", "grade": "error", "detail": f"게이트 실행 오류: {e}"}]

    all_fails = qa_fails + legal_fails
    ok = len(all_fails) == 0
    result = {
        "ok": True, "slug": slug, "saved": False,
        "blocked_reason": None if ok else "QA/법정수치 검증 실패 — 저장하지 않음(아래 실패 목록 확인)",
        "qa": {"ok": ok, "failed": all_fails},
        "content": {"article_content": article},
    }
    if ok:
        from modules.content_integrity import build_content_tracking_fields
        try:
            tracking = build_content_tracking_fields(article, slug, "api_body_generate")
        except Exception:
            tracking = {}
        repo, _cfg2 = _repo_and_cfg()
        repo.update_generated(calc["id"], {"article_content": article, **tracking})
        result["saved"] = True
    return result


def generate_calculator_content_image(slug: str) -> dict:
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    blocked = _content_generation_blocked_reason(slug)
    if blocked:
        return {"ok": False, "slug": slug, "saved": False, "blocked_reason": blocked,
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules import calculator_image_prompt_generator as IMGG
    try:
        img = {"thumbnail": IMGG.generate_thumbnail_prompt(cfg, calc),
               "body": IMGG.generate_body_prompt(cfg, calc)}
    except Exception as e:
        return {"ok": False, "slug": slug, "saved": False,
                "blocked_reason": f"이미지 프롬프트 생성 실패: {e}",
                "qa": {"ok": False, "failed": []}, "content": None}

    from modules.content_qa import run_generation_qa
    img_text = f"{img['thumbnail']} {img['body']}"
    qa_ok, qa_fails = run_generation_qa(
        calc, article=img_text, img=img, other_calc_names=_other_calculator_names(slug),
        require_identity=False)
    result = {
        "ok": True, "slug": slug, "saved": False,
        "blocked_reason": None if qa_ok else "QA 실패 — 저장하지 않음(아래 실패 목록 확인)",
        "qa": {"ok": qa_ok, "failed": qa_fails},
        "content": {"image_prompt_thumbnail": img["thumbnail"], "image_prompt_body": img["body"]},
    }
    if qa_ok:
        repo, _cfg2 = _repo_and_cfg()
        repo.update_generated(calc["id"], {"image_prompt_thumbnail": img["thumbnail"],
                                            "image_prompt_body": img["body"]})
        result["saved"] = True
    return result


def generate_calculator_content_full(slug: str) -> dict:
    """SEO→FAQ→본문→이미지→(AI Reviewer 자동검수/재작성)까지 기존 auto_generate_all()을
    save=False로 재사용한 뒤, 결정적 QA + review_status가 AUTO_APPROVED/AUTO_REWRITTEN인
    경우에만 이 함수에서 직접 저장한다(레거시는 NEEDS_REVIEW여도 항상 저장했다 — 강화)."""
    calc, _v3_reg, cfg = _get_calc_or_raise(slug)
    blocked = _content_generation_blocked_reason(slug)
    if blocked:
        return {"ok": False, "slug": slug, "saved": False, "blocked_reason": blocked,
                "qa": {"ok": False, "failed": []}, "review": None, "content": None}

    from content.calculator.writer import auto_generate_all
    try:
        gen = auto_generate_all(cfg, calc, save=False, auto_review=True)
    except Exception as e:
        return {"ok": False, "slug": slug, "saved": False,
                "blocked_reason": f"생성 실패: {e}",
                "qa": {"ok": False, "failed": []}, "review": None, "content": None}

    faq = gen.get("faq")
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except (ValueError, TypeError):
            faq = []
    seo = {"seo_title": gen.get("seo_title", ""), "seo_description": gen.get("seo_description", "")}
    article = gen.get("article_content", "")
    img = {"thumbnail": gen.get("image_prompt_thumbnail", ""), "body": gen.get("image_prompt_body", "")}
    content = {
        "seo_title": seo["seo_title"], "seo_description": seo["seo_description"],
        "faq": faq, "article_content": article,
        "image_prompt_thumbnail": img["thumbnail"], "image_prompt_body": img["body"],
    }
    review = {k: gen[k] for k in
              ("review_status", "review_score", "review_reason", "review_attempts", "reviewed_at")
              if k in gen}

    from modules.content_qa import run_generation_qa
    qa_ok, qa_fails = run_generation_qa(
        calc, seo=seo, faq=faq, article=article, img=img,
        other_calc_names=_other_calculator_names(slug), require_article=True)
    if not qa_ok:
        return {"ok": True, "slug": slug, "saved": False,
                "blocked_reason": "결정적 QA 실패 — 저장하지 않음(아래 실패 목록 확인)",
                "qa": {"ok": False, "failed": qa_fails}, "review": review, "content": content}

    review_status = gen.get("review_status")
    if review_status not in ("AUTO_APPROVED", "AUTO_REWRITTEN"):
        return {"ok": True, "slug": slug, "saved": False,
                "blocked_reason": f"AI Review 상태 '{review_status}' — 저장 조건(AUTO_APPROVED/"
                                   f"AUTO_REWRITTEN) 미충족으로 저장하지 않음",
                "qa": {"ok": True, "failed": []}, "review": review, "content": content}

    from modules.content_integrity import build_content_tracking_fields
    try:
        tracking = build_content_tracking_fields(article, slug, "api_full_generate")
    except Exception:
        tracking = {}
    save_payload = dict(content)
    save_payload["faq"] = json.dumps(faq, ensure_ascii=False)
    save_payload.update(tracking)
    save_payload.update(review)

    repo, _cfg2 = _repo_and_cfg()
    repo.update_generated(calc["id"], save_payload)
    return {"ok": True, "slug": slug, "saved": True, "blocked_reason": None,
            "qa": {"ok": True, "failed": []}, "review": review, "content": content}


# ═══════════════════════════════════════════════════════════════════════════
# P0-5: Mode B(Contract 기반 생성) + 실제 샘플 기대값 검증 — React/FastAPI 이관
#
# dashboard.py "📋 Contract 기반 생성" 버튼(dashboard.py:2513 부근)과 동일한 backend
# 함수(modules.app_factory.build_contract/check_hold_rules/generate_app_with_contract/
# save_app, modules.formula_engine.validate_formula_with_samples,
# modules.review_center.check_slug_conflict)를 전부 변경 없이 재사용한다.
# generate_app()/Formula Hard Gate/저장 순서는 이 STEP에서 건드리지 않는다.
#
# 레거시(Streamlit)와의 의도적 차이(계산기 생성 파이프라인 자체는 무변경, "저장 차단"의
# 강제 방식만 안전하게 재구성):
#   1) Streamlit의 "Formula 검증"→"Formula 확정" 2단계는 세션 상태(operator가 수동으로
#      누른 버튼)에 의존했다 — 브라우저에서 disabled 속성은 실제 API 호출을 막지 않으므로,
#      여기서는 생성 요청마다 서버가 validate_formula_with_samples()를 직접 재실행해
#      formula_status를 계산한다(클라이언트가 "확정했다"고 주장하는 값을 신뢰하지 않음).
#      최종 저장 차단 자체는 modules.app_factory.save_app()에 이미 있는 operator_confirmed
#      Hard-Gate(CA-1B-4 P1-C)를 그대로 사용한다 — 이 게이트를 만들거나 바꾸지 않았다.
#   2) Contract 불일치(_contract_validation.valid=False)는 Streamlit에서 저장 버튼을
#      disabled로만 만들었다(save_app() 자체는 이 값을 검사하지 않음) — 실제 API에서는
#      브라우저 밖에서 직접 호출 가능하므로, 저장 endpoint에서 이 값을 명시적으로 재확인해
#      차단한다(validate_against_contract()는 변경하지 않고 그 반환값만 확인).
# ═══════════════════════════════════════════════════════════════════════════

class ContractGenerateBusyError(Exception):
    """Mode A와 GenerationJobStore를 공유하므로(신규 Job 인프라 없음) 동일 사유로 거부됨."""


def check_contract_slug_conflict(slug: str) -> dict:
    """dashboard.py의 실시간 슬러그 중복 확인과 동일 — modules.review_center.
    check_slug_conflict()를 그대로 호출한다(읽기 전용)."""
    from modules.review_center import check_slug_conflict
    cfg = load_config()
    clean_slug = str(slug or "").strip().lower()
    _, conflict, message = check_slug_conflict(clean_slug, cfg)
    return {"slug": clean_slug, "conflict": conflict, "message": message}


def get_contract_prefill(slug: str) -> dict:
    """dashboard.py의 Registry prefill과 동일 — modules.app_factory.
    prefill_contract_from_registry()를 그대로 호출한다(읽기 전용)."""
    from modules import app_factory
    return app_factory.prefill_contract_from_registry(str(slug or "").strip().lower())


def get_contract_instance(slug: str) -> dict:
    """dashboard.py의 "Contract Instance 불러오기"와 동일 — modules.app_factory.
    contract_instance_restore()를 그대로 호출한다(읽기 전용)."""
    from modules import app_factory
    return app_factory.contract_instance_restore(str(slug or "").strip().lower())


def _run_sample_validation(formula, input_fields: list, test_cases: list) -> dict:
    """modules.formula_engine.validate_formula_with_samples()를 그대로 호출하고,
    dashboard.py와 동일한 규칙으로 formula_status를 도출한다:
    valid + 모든 샘플 match + test_cases 존재 → operator_confirmed
    valid(AST/schema)만 통과 → pending_validation
    invalid(Formula Hard Gate 수준에서부터 실패) → formula_invalid"""
    from modules.formula_engine import validate_formula_with_samples
    schema = {f: "number" for f in (input_fields or [])}
    result = validate_formula_with_samples(formula, schema, test_cases or None)
    samples = result.get("sample_results", [])
    failed = [s for s in samples if s.get("match") is False]
    all_samples_pass = bool(result.get("valid")) and len(failed) == 0
    if all_samples_pass and test_cases:
        formula_status = "operator_confirmed"
    elif result.get("valid"):
        formula_status = "pending_validation"
    else:
        formula_status = "formula_invalid"
    return {
        "valid": result.get("valid", False),
        "message": result.get("message", ""),
        "sample_results": samples,
        "all_samples_pass": all_samples_pass,
        "formula_status": formula_status,
    }


def validate_contract_formula(formula, input_fields: list, test_cases: list) -> dict:
    """dashboard.py "🔍 Formula 검증" 버튼과 동일한 사전 검증(생성 전, AI 호출 없음,
    순수 계산). React가 샘플별 PASS/FAIL을 생성 전에 미리 보여주기 위한 조회 endpoint."""
    return _run_sample_validation(formula, input_fields, test_cases)


def submit_contract_generation(*, name: str, category: str, description: str, tier: str,
                                slug: str, input_fields: list, output_fields: list,
                                formula, test_cases: list, scope_exclusions: list,
                                legal_refs: list) -> dict:
    """Mode B(Contract 기반) 생성. dashboard.py "📋 Contract 기반 생성" 버튼과 동일하게
    modules.app_factory.build_contract()/check_hold_rules()/generate_app_with_contract()를
    변경 없이 그대로 호출한다. Mode A(submit_calculator_generation)와 동일한
    GenerationJobStore를 재사용한다(신규 Job 인프라 없음). 자동 저장 없음 — save는
    별도 submit_contract_save()에서 사람이 결과를 검토한 뒤 수행한다(Streamlit의
    "생성 → 결과 검토 → 저장" 2단계 흐름과 동일)."""
    from modules import app_factory
    from api.services.generation_job_store import get_job_store

    def _target() -> dict:
        cfg = load_config()

        pre_gen_validation = None
        formula_status = "not_generated"
        if formula is not None and formula != "":
            pre_gen_validation = _run_sample_validation(formula, input_fields, test_cases)
            formula_status = pre_gen_validation["formula_status"]

        contract = app_factory.build_contract(
            slug=slug, name=name, category=category, tier=tier,
            input_fields=input_fields, output_fields=output_fields,
            formula=formula, formula_status=formula_status,
            scope_exclusions=scope_exclusions, test_cases=test_cases,
            desc=description, legal_refs=legal_refs,
        )
        hold = app_factory.check_hold_rules(contract)
        app = app_factory.generate_app_with_contract(cfg, contract)

        # Contract 검증 결과 패널과 동일 — AI가 실제로 반환한 formula/input_schema
        # 기준으로 샘플 검증을 재실행한다(사전 검증은 Contract 원본 formula 기준).
        post_gen_validation = None
        if contract.get("test_cases") and app.get("formula"):
            post_gen_validation = _run_sample_validation(
                app.get("formula"), list(app.get("input_schema", {}).keys()) or input_fields,
                contract["test_cases"])

        return {
            "slug": contract["slug"],
            "name": name,
            "tier": app.get("tier", 2),
            "formula_valid": app.get("_formula_valid", True),
            "formula_msg": app.get("_formula_msg", ""),
            "hold_messages": hold.get("messages", []),
            "contract": contract,
            "contract_validation": app.get("_contract_validation"),
            "pre_generation_sample_validation": pre_gen_validation,
            "post_generation_sample_validation": post_gen_validation,
            "html_length": len(app.get("html", "") or ""),
            "seo_title": app.get("seo_title", ""),
            "input_schema": app.get("input_schema", {}),
            "output_schema": app.get("output_schema", {}),
            "faq": app.get("faq", []),
            "steps": app.get("_steps", []),
            "app": app,   # 저장 단계(submit_contract_save)에서만 사용
        }

    store = get_job_store()
    accepted, message, job_id = store.submit(f"contract:{slug}", _target)
    if not accepted:
        raise ContractGenerateBusyError(message)
    job = store.get(job_id)
    return job.to_public_dict()


def get_contract_generation_job(job_id: str) -> dict:
    """POST /api/calculators/generate/contract가 만든 Job의 현재 상태를 조회한다.
    Mode A의 get_calculator_generation_job()과 동일한 조회 로직(같은 Job store)."""
    from api.services.generation_job_store import get_job_store

    job = get_job_store().get(job_id)
    if job is None:
        raise CalculatorNotFound(job_id)
    return job.to_public_dict()


def submit_contract_save(job_id: str, slug: str) -> dict:
    """Mode B 생성 Job의 결과를 실제로 저장한다. dashboard.py "💾 calculators +
    app_templates 저장" 버튼과 동일하게 modules.app_factory.save_app()을 그대로
    호출한다 — 새로운 저장 방식을 만들지 않는다.

    save_app()은 이미 contract.formula_status != "operator_confirmed"이면 저장을
    거부하는 Hard-Gate를 갖고 있다(CA-1B-4 P1-C, 변경하지 않음). 여기서는 그에 더해
    Streamlit에서는 저장 버튼의 disabled 속성으로만 막던 Contract 불일치
    (_contract_validation.valid=False, slug/schema/formula drift)도 서버에서 명시적으로
    재확인해 차단한다 — 실제 API는 브라우저 밖에서 직접 호출 가능하므로 disabled
    속성만으로는 안전하지 않기 때문이다(validate_against_contract() 자체는 무변경)."""
    from modules import app_factory
    from api.services.generation_job_store import get_job_store

    job = get_job_store().get(job_id)
    if job is None:
        raise CalculatorNotFound(job_id)
    if job.status != "succeeded" or not job.result:
        return {"ok": False, "slug": slug,
                "blocked_reason": f"생성 작업이 완료되지 않았습니다(상태: {job.status})."}

    app = job.result.get("app")
    if not app:
        return {"ok": False, "slug": slug, "blocked_reason": "생성 결과를 찾을 수 없습니다."}

    contract_validation = app.get("_contract_validation") or {}
    if not contract_validation.get("valid", True):
        return {"ok": False, "slug": slug,
                "blocked_reason": "⛔ Contract 불일치로 저장이 차단됩니다 — "
                                   "slug/schema/formula를 확인하고 Contract를 다시 생성하세요."}

    cfg = load_config()
    ok_, msg = app_factory.save_app(cfg, app, slug=slug)
    return {"ok": ok_, "slug": slug, "message": msg if ok_ else None,
            "blocked_reason": None if ok_ else msg}
