# -*- coding: utf-8 -*-
"""
modules/calculator_site_sync.py — calculators SQLite ↔ `_site` Metadata Drift Detector (READ-ONLY)

STEP39: 계산기 3-way(SQLite/Sheets/_site/Live) 감사 중 SQLite→_site 구간.
"SQLite의 계산기 metadata가 실제 `_site` 산출물에 그대로 반영돼 있는가?"를 판정한다.

STEP36에서 실측 확인한 구조를 그대로 전제로 한다:
  - `_site` 계산기 매핑은 slug 기준 디렉토리(`data/workspace/_site/<slug>/index.html`)이다.
  - 각 계산기 index.html에는 `window.SM_CONFIG = {...}` JS 객체가 임베드돼 있고,
    거기에 name/slug/inputs/outputs 등이 들어있다.
  - status/review_score/content_hash/generated_at 등은 `_site` 산출물 어디에도
    반영되지 않는다(비교 대상에서 명시적으로 제외 — STEP39 §3 지시대로).

compare_calculators_sqlite_vs_site()는 다음만 수행한다:
  1. CalculatorRepository로 SQLite calculators 전체를 조회(새 DB 접근 코드 없음)
  2. slug 기준으로 `_site/<slug>/index.html`을 찾아 SM_CONFIG를 파싱
  3. name/slug/inputs/outputs를 정규화 후 비교
  4. `_site`에만 있고 SQLite에 없는 계산기 페이지(SM_CONFIG가 있는 미매칭 디렉토리)도
     반대 방향으로 탐지한다
  5. INFO/WARN/FAIL/CRITICAL로 분류한다

`_site` 파일이나 SQLite 어디에도 쓰지 않는다. `_site` 재생성(rebuild)도 호출하지
않는다 — 있는 그대로의 파일만 읽는다. AUTO-FIX 없음.
"""
import json
import re
from pathlib import Path

from repositories.calculator_repository import CalculatorRepository

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_FAIL = "FAIL"
SEVERITY_CRITICAL = "CRITICAL"

_SM_CONFIG_RE = re.compile(r"window\.SM_CONFIG\s*=\s*(\{.*?\});", re.DOTALL)

# STEP48: 비교 전용 canonical type 동치 규칙(STEP47에서 READ-ONLY로 안전성 검증됨).
# 이 정규식/함수는 오직 "비교 판정"에만 쓰이며, SQLite/그 _site 원본 스키마 값은
# 절대 변경하지 않는다.
_SELECT_OPTION_KEY_RE = re.compile(r"^-?\d+$")


def _canonical_compare_type(value):
    """비교 전용 canonical type 변환.

    Rule A: "integer"는 "number"와 동치로 본다 — script.js::collectInputs()가
    "date"/"boolean" 외엔 전부 num()으로 동일하게 파싱함을 STEP47에서 코드로
    확인했다(정수/실수 구분 없음).
    Rule B: "select:키=라벨,..." 형태에서 모든 키가 정수 리터럴(0, 1, -2 등)이면
    "number"와 동치로 본다 — 실제 <select>의 option value가 그대로 이 키이고,
    collectInputs()가 select도 num()으로 처리하며, label/value 매핑은 이 비교
    로직과 무관한 별도 HTML 렌더링 경로가 그대로 보존함을 STEP47에서 확인했다.
    키가 하나라도 정수가 아니거나 파싱이 애매하면 원래 값을 그대로 반환해
    mismatch가 계속 감지되게 한다(number로 임의 승격하지 않음).
    dict형(Tier2-B류, military-discharge-date)은 이 함수의 대상이 아니며
    그대로 반환한다."""
    if not isinstance(value, str):
        return value
    if value == "integer":
        return "number"
    if value.startswith("select:"):
        body = value[len("select:"):]
        if not body:
            return value
        keys = [pair.split("=", 1)[0] for pair in body.split(",")]
        if keys and all(_SELECT_OPTION_KEY_RE.fullmatch(k) for k in keys):
            return "number"
        return value
    return value


def _default_site_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "workspace" / "_site"


def _read_sm_config(site_dir: Path, slug: str) -> dict:
    """slug 디렉토리의 index.html에서 SM_CONFIG JSON을 읽어 반환한다.
    디렉토리/파일이 없거나 파싱에 실패하면 예외를 던지지 않고
    {"_error": "<사유>"}를 반환한다(호출자가 CRITICAL로 분류)."""
    index_path = site_dir / slug / "index.html"
    if not index_path.exists():
        return {"_error": "index_html_missing"}
    try:
        html = index_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"_error": f"read_failed:{e}"}
    m = _SM_CONFIG_RE.search(html)
    if not m:
        return {"_error": "sm_config_not_found"}
    try:
        return json.loads(m.group(1))
    except Exception as e:
        return {"_error": f"json_parse_failed:{e}"}


def _raw_input_maps(sqlite_input_schema, site_inputs) -> tuple[dict, dict]:
    """SQLite input_schema와 _site SM_CONFIG.inputs를 canonical 변환 이전,
    파싱만 한 원본 {name: value} dict로 반환한다(값 변환 없음). _normalize_inputs()와
    _collect_normalization_applied()가 동일한 파싱 로직을 공유하기 위한 내부 헬퍼."""
    if isinstance(sqlite_input_schema, str):
        try:
            sqlite_map = json.loads(sqlite_input_schema) if sqlite_input_schema else {}
        except Exception:
            sqlite_map = {"_parse_error": sqlite_input_schema}
    else:
        sqlite_map = sqlite_input_schema or {}

    site_map = {}
    for item in (site_inputs or []):
        if isinstance(item, dict) and "name" in item:
            site_map[item["name"]] = item.get("type")
    return sqlite_map, site_map


def _normalize_inputs(sqlite_input_schema, site_inputs) -> tuple[dict, dict]:
    """SQLite input_schema({name: type} JSON 문자열/dict)와 _site SM_CONFIG.inputs
    (list[{name,label,type,unit}])를 둘 다 {name: type} dict로 정규화해 반환한다.
    비교 전용 — 원본 값은 절대 바꾸지 않는다(반환값은 새 dict이며, 원본
    sqlite_input_schema/site_inputs 객체는 이 함수 안에서 in-place로 건드리지
    않는다). 값 자체는 _canonical_compare_type()으로 한 번 더 비교용 정규화한다
    (STEP48 — integer/numeric-select ↔ number 동치, dict형은 그대로 통과)."""
    sqlite_map, site_map = _raw_input_maps(sqlite_input_schema, site_inputs)
    sqlite_map = {k: _canonical_compare_type(v) for k, v in sqlite_map.items()}
    site_map = {k: _canonical_compare_type(v) for k, v in site_map.items()}
    return sqlite_map, site_map


def _detect_normalization_rule(value) -> str | None:
    """value가 _canonical_compare_type()에 의해 실제로 바뀌는 경우에만 적용된
    규칙 이름을 반환한다(안 바뀌면 None). STEP50에서 확인된 TRACEABILITY_GAP을
    메우기 위한 순수 조회 함수 — 판정 로직에는 관여하지 않는다."""
    canonical = _canonical_compare_type(value)
    if canonical == value:
        return None
    if value == "integer":
        return "integer_to_number"
    if isinstance(value, str) and value.startswith("select:"):
        return "numeric_select_to_number"
    return None  # 현재 규칙상 도달하지 않지만, 미래 규칙 추가 시 안전한 기본값


def _collect_normalization_applied(sqlite_input_schema, site_inputs) -> list[dict]:
    """STEP51: 비교 판정과 완전히 분리된 부가 메타데이터. 필드별로 canonical
    변환이 실제로 적용됐는지(즉 원본이 서로 다른 표현이었는지)를 기록한다.
    반환값은 오직 로그/Telegram 참고용이며, severity/reasons/changed_fields
    계산에는 전혀 영향을 주지 않는다(순서상 이 함수 호출 여부와 무관하게
    compare 결과는 동일하다). 원본 SQLite schema/_site inputs는 여기서도
    변경하지 않는다(읽기만 한다)."""
    sqlite_raw, site_raw = _raw_input_maps(sqlite_input_schema, site_inputs)
    applied = []
    for field, value in sqlite_raw.items():
        rule = _detect_normalization_rule(value)
        if rule:
            applied.append({"field": field, "side": "sqlite", "original": value,
                            "canonical": _canonical_compare_type(value), "rule": rule})
    for field, value in site_raw.items():
        rule = _detect_normalization_rule(value)
        if rule:
            applied.append({"field": field, "side": "site", "original": value,
                            "canonical": _canonical_compare_type(value), "rule": rule})
    return applied


def _normalize_outputs(sqlite_output_schema, site_outputs) -> tuple[set, set]:
    """SQLite output_schema({key: type})의 키 집합과 _site SM_CONFIG.outputs
    (list[{key,label,unit}])의 키 집합만 비교한다. _site 쪽 outputs에는 type이
    아예 존재하지 않는 구조이므로(실측 확인, STEP39 §2) 타입까지는 비교하지
    않고 키(=출력 필드) 존재 여부만 판단한다 — 이는 표현 누락이 아니라 site_generator가
    애초에 output type을 렌더링하지 않는 정상 구조다."""
    if isinstance(sqlite_output_schema, str):
        try:
            sqlite_map = json.loads(sqlite_output_schema) if sqlite_output_schema else {}
        except Exception:
            sqlite_map = {}
    else:
        sqlite_map = sqlite_output_schema or {}

    sqlite_keys = set(sqlite_map.keys())
    site_keys = {item["key"] for item in (site_outputs or [])
                if isinstance(item, dict) and "key" in item}
    return sqlite_keys, site_keys


def _classify_pair(calc: dict, sm: dict) -> dict:
    """SQLite calculator 1건과 그에 대응하는 파싱된 SM_CONFIG 1건을 비교한다."""
    calc_id = calc.get("id", "")
    slug = calc.get("slug", "")
    changed_fields = []
    hard_mismatch = False

    sqlite_name = (calc.get("name") or "").strip()
    site_name = (sm.get("name") or "").strip()
    if sqlite_name != site_name:
        changed_fields.append({"calculator_id": calc_id, "slug": slug, "field": "name",
                               "sqlite_value": sqlite_name, "site_value": site_name,
                               "reason": "name_mismatch"})
        hard_mismatch = True

    site_slug = (sm.get("slug") or "").strip()
    if site_slug and site_slug != slug:
        changed_fields.append({"calculator_id": calc_id, "slug": slug, "field": "slug",
                               "sqlite_value": slug, "site_value": site_slug,
                               "reason": "slug_mismatch"})
        hard_mismatch = True

    sqlite_inputs, site_inputs = _normalize_inputs(calc.get("input_schema"), sm.get("inputs"))
    if sqlite_inputs != site_inputs:
        changed_fields.append({"calculator_id": calc_id, "slug": slug, "field": "inputs",
                               "sqlite_value": sqlite_inputs, "site_value": site_inputs,
                               "reason": "inputs_mismatch"})
        hard_mismatch = True

    sqlite_outputs, site_outputs = _normalize_outputs(calc.get("output_schema"), sm.get("outputs"))
    if sqlite_outputs != site_outputs:
        changed_fields.append({"calculator_id": calc_id, "slug": slug, "field": "outputs",
                               "sqlite_value": sorted(sqlite_outputs), "site_value": sorted(site_outputs),
                               "reason": "outputs_mismatch"})
        hard_mismatch = True

    severity = SEVERITY_FAIL if hard_mismatch else SEVERITY_INFO
    reasons = [c["reason"] for c in changed_fields] or ["no_change"]
    normalization_applied = _collect_normalization_applied(calc.get("input_schema"), sm.get("inputs"))
    return {"calculator_id": calc_id, "slug": slug, "severity": severity,
            "reasons": reasons, "changed_fields": changed_fields,
            "normalization_applied": normalization_applied}


def _empty_result(counts: dict) -> dict:
    return {
        "total": 0, "matched": 0, "mismatched": 0,
        "missing_in_sqlite": [], "missing_in_site": [],
        "changed_fields": [], "severity": dict(counts), "reasons": [],
        "results": [],
    }


def _load_registry_entry_safe(slug: str) -> dict:
    """STEP71: registry v3에서 slug 엔트리를 안전하게 조회한다. registry 로드
    실패가 이 detector 전체를 막으면 안 되므로 예외를 흡수하고 빈 dict를 반환한다."""
    try:
        from modules.registry_loader import load_registry_v3
        return load_registry_v3().get(slug) or {}
    except Exception:
        return {}


def _is_tier2b_template_exception(slug: str, calc: dict, site_dir: Path) -> bool:
    """STEP71: Tier2-B(self-contained HTML/template_db) 계산기는 SM_CONFIG 규약을
    쓰지 않는 것이 STEP69/70에서 확인된 의도적 설계다(docs/TIER2_B_DESIGN.md).
    단, tier_subtype=="B"라는 사실 하나만으로 통과시키지 않는다 — 아래 조건을
    전부(AND) 만족해야만 예외로 인정한다. 하나라도 실패하면 False를 반환해
    호출부가 기존 CRITICAL 경로를 그대로 따르게 한다."""
    reg = _load_registry_entry_safe(slug)
    if reg.get("tier_subtype") != "B":
        return False
    if reg.get("html_source") != "template_db":
        return False
    if not calc.get("template_id"):
        return False
    index_path = site_dir / slug / "index.html"
    if not index_path.exists():
        return False
    try:
        html = index_path.read_text(encoding="utf-8")
    except Exception:
        return False
    if not html.strip():
        return False
    if "<script" not in html:
        return False
    return True


def compare_calculators_sqlite_vs_site(cfg: dict = None, sqlite_repo=None, site_dir=None) -> dict:
    """calculators SQLite↔`_site` metadata 비교(READ-ONLY). 어디에도 쓰지 않는다.
    `_site`를 재생성/rebuild하지 않고 현재 있는 그대로의 파일만 읽는다.

    반환: {total, matched, mismatched, missing_in_sqlite, missing_in_site,
           changed_fields, severity({INFO,WARN,FAIL,CRITICAL}), reasons, results}
    """
    counts = {SEVERITY_INFO: 0, SEVERITY_WARN: 0, SEVERITY_FAIL: 0, SEVERITY_CRITICAL: 0}
    site_dir = Path(site_dir) if site_dir is not None else _default_site_dir()

    try:
        if sqlite_repo is None:
            from adapters.db.sqlite_adapter import SQLiteAdapter
            sqlite_repo = CalculatorRepository(SQLiteAdapter(cfg or {}))
        sqlite_rows = sqlite_repo.get_all()
    except Exception as e:
        out = _empty_result(counts)
        out["severity"][SEVERITY_CRITICAL] = 1
        out["reasons"] = [f"sqlite_access_failed: {e}"]
        out["results"] = [{"calculator_id": None, "slug": None, "severity": SEVERITY_CRITICAL,
                            "reasons": [f"sqlite_access_failed: {e}"], "changed_fields": [],
                            "normalization_applied": []}]
        return out

    sqlite_by_slug: dict[str, list] = {}
    for r in sqlite_rows:
        slug = str(r.get("slug", "") or "")
        if slug:
            sqlite_by_slug.setdefault(slug, []).append(r)

    results = []
    changed_fields_all = []
    reasons_all = []
    missing_in_sqlite = []
    missing_in_site = []

    # 1) SQLite -> _site 방향
    for slug in sorted(sqlite_by_slug):
        matches = sqlite_by_slug[slug]
        if len(matches) > 1:
            reason = f"duplicate_slug_in_sqlite(count={len(matches)})"
            results.append({"calculator_id": matches[0].get("id"), "slug": slug,
                            "severity": SEVERITY_CRITICAL, "reasons": [reason], "changed_fields": [],
                            "normalization_applied": []})
            counts[SEVERITY_CRITICAL] += 1
            reasons_all.append(reason)
            continue

        calc = matches[0]
        sm = _read_sm_config(site_dir, slug)
        if "_error" in sm:
            # STEP71: sm_config_not_found 하나만, Tier2-B/template_db 검증을 전부
            # 통과한 경우에만 구조적 예외로 분류한다. index_html_missing 등 다른
            # 실패 사유는 이 예외 경로를 절대 타지 않는다(기존 CRITICAL 그대로).
            if sm["_error"] == "sm_config_not_found" and _is_tier2b_template_exception(slug, calc, site_dir):
                results.append({"calculator_id": calc.get("id"), "slug": slug,
                                "severity": SEVERITY_INFO,
                                "reasons": ["tier2b_template_exception_verified"],
                                "changed_fields": [], "normalization_applied": []})
                counts[SEVERITY_INFO] += 1
                continue
            missing_in_site.append(calc.get("id"))
            results.append({"calculator_id": calc.get("id"), "slug": slug,
                            "severity": SEVERITY_CRITICAL, "reasons": [sm["_error"]], "changed_fields": [],
                            "normalization_applied": []})
            counts[SEVERITY_CRITICAL] += 1
            reasons_all.append(sm["_error"])
            continue

        entry = _classify_pair(calc, sm)
        results.append(entry)
        counts[entry["severity"]] += 1
        if entry["changed_fields"]:
            changed_fields_all.extend(entry["changed_fields"])
            reasons_all.extend(entry["reasons"])

    # 2) _site -> SQLite 방향(SM_CONFIG를 가진, 어떤 SQLite slug와도 매칭 안 되는 orphan 페이지)
    try:
        site_top_dirs = sorted(p.name for p in site_dir.iterdir() if p.is_dir())
    except Exception:
        site_top_dirs = []
    for name in site_top_dirs:
        if name in sqlite_by_slug:
            continue
        sm = _read_sm_config(site_dir, name)
        if "_error" in sm:
            continue  # SM_CONFIG 없는 디렉토리(about/blog/contact/privacy/terms 등)는 계산기 페이지가 아님
        missing_in_sqlite.append(name)
        results.append({"calculator_id": None, "slug": name, "severity": SEVERITY_CRITICAL,
                        "reasons": ["missing_in_sqlite"], "changed_fields": [],
                        "normalization_applied": []})
        counts[SEVERITY_CRITICAL] += 1
        reasons_all.append("missing_in_sqlite")

    total = len(sqlite_by_slug) + len(missing_in_sqlite)
    matched = counts[SEVERITY_INFO]
    mismatched = total - matched

    return {
        "total": total,
        "matched": matched,
        "mismatched": mismatched,
        "missing_in_sqlite": missing_in_sqlite,
        "missing_in_site": missing_in_site,
        "changed_fields": changed_fields_all,
        "severity": dict(counts),
        "reasons": reasons_all,
        "results": results,
    }


# ── STEP51: sync_runs/sync_log_calculator_entries 저장 + Telegram(판정 로직과 완전 분리) ──
# STEP50에서 확인된 구조적 공백(SQLite↔_site 축이 record/Telegram에 연결되어
# 있지 않음)을 메운다. 기존 sync_runs/sync_log_calculator_entries 테이블을
# 그대로 재사용하고(새 테이블/새 컬럼 없음), target="calculators_site"로 축을
# 구분한다(target은 이미 target-중립 공용 컬럼임을 STEP37에서 확인) —
# sync_log_calculator_entries.run_id로 sync_runs.target을 join하면 어느 축의
# 로그인지 항상 구분 가능하므로 entries 테이블 자체에는 손대지 않는다.
# modules/calculator_3way_sync.py(SQLite↔Sheets)는 이 파일에서 import하지 않고
# 완전히 별개로 두어 그 쪽 동작에 어떤 영향도 주지 않는다.
_RESULT_PRIORITY = [SEVERITY_CRITICAL, SEVERITY_FAIL, SEVERITY_WARN]  # 없으면 PASS
RUN_RESULT_PASS = "PASS"
_TARGET = "calculators_site"


def _aggregate_result(severity_counts: dict) -> str:
    for sev in _RESULT_PRIORITY:
        if severity_counts.get(sev, 0) > 0:
            return sev
    return RUN_RESULT_PASS


def _reasons_for_log(entry: dict) -> str:
    """sync_log_calculator_entries.reasons(TEXT, 기존 컬럼 그대로 재사용)에 담을
    문자열을 만든다. normalization이 실제로 적용된 필드가 있으면
    " | normalized:rule1,rule2" 형태로만 덧붙인다(STEP50 TRACEABILITY_GAP 보완,
    새 컬럼 없이 기존 자유 텍스트 필드만 사용) — 없으면 기존과 동일한 형태 그대로."""
    base = ",".join(entry.get("reasons") or ["no_change"])
    rules = sorted({n["rule"] for n in entry.get("normalization_applied", [])})
    if rules:
        return f"{base} | normalized:{','.join(rules)}"
    return base


def run_calculator_site_sync_and_log(cfg: dict, sqlite_repo=None, site_dir=None,
                                     log_repo=None) -> dict:
    """compare_calculators_sqlite_vs_site()를 그대로 호출하고(판정 로직 무변경),
    그 결과를 sync_runs(target="calculators_site")/sync_log_calculator_entries에
    저장한다. 로그 저장이 실패해도 판정 결과는 그대로 반환한다
    (modules/calculator_3way_sync.py::run_calculator_3way_sync_and_log()와 동일한
    원칙 — "판정 성공 + 로그 저장 실패"를 분리한다).

    반환: compare_calculators_sqlite_vs_site()의 모든 키 + 다음을 추가:
      result: CRITICAL>FAIL>WARN 우선순위로 정한 이번 run 전체 판정(없으면 PASS)
      run_id / log_result("saved"|"failed") / log_error
      telegram_result("skipped"|"sent"|"failed") / telegram_error

    SQLite calculators 테이블/`_site` 파일 어디에도 쓰지 않는다. 허용되는 유일한
    쓰기는 sync_runs/sync_log_calculator_entries INSERT뿐이다.
    """
    import time
    from datetime import datetime

    started_at = datetime.now().isoformat()
    t0 = time.monotonic()

    comparison = compare_calculators_sqlite_vs_site(cfg, sqlite_repo=sqlite_repo, site_dir=site_dir)

    finished_at = datetime.now().isoformat()
    duration_ms = int((time.monotonic() - t0) * 1000)

    out = dict(comparison)
    out["result"] = _aggregate_result(comparison["severity"])
    out["run_id"] = None
    out["log_result"] = "failed"
    out["log_error"] = None

    try:
        if log_repo is None:
            from adapters.db.sqlite_adapter import SQLiteAdapter
            from repositories.sync_log_calculator_repository import SyncLogCalculatorRepository
            log_repo = SyncLogCalculatorRepository(SQLiteAdapter(cfg))

        from repositories.sync_log_repository import generate_run_id, generate_entry_id

        counts = comparison["severity"]
        run_id = generate_run_id(_TARGET)

        log_repo.create_run({
            "run_id": run_id, "target": _TARGET,
            "started_at": started_at, "finished_at": finished_at, "duration_ms": duration_ms,
            "result": out["result"], "total_count": comparison["total"],
            "info_count": counts[SEVERITY_INFO], "warn_count": counts[SEVERITY_WARN],
            "fail_count": counts[SEVERITY_FAIL], "critical_count": counts[SEVERITY_CRITICAL],
        })

        for r in comparison["results"]:
            log_repo.insert_calculator_entry({
                "entry_id": generate_entry_id(_TARGET), "run_id": run_id,
                "calculator_id": r.get("calculator_id") or "",
                "slug": r.get("slug") or "",
                "severity": r["severity"], "reasons": _reasons_for_log(r),
                "error_type": None, "error_message": None,
                "checked_at": finished_at,
            })

        out["run_id"] = run_id
        out["log_result"] = "saved"
    except Exception as e:
        out["log_result"] = "failed"
        out["log_error"] = str(e)[:300]

    out["telegram_result"] = "skipped"
    out["telegram_error"] = None
    if out["result"] != RUN_RESULT_PASS:
        _notify_site_drift_result(cfg, out)

    return out


# Telegram sync_mismatch 알림 — WARN/FAIL/CRITICAL만(INFO/PASS는 전송 안 함).
# modules/calculator_3way_sync.py의 동일 패턴(STEP38)을 그대로 따르되, 그 파일을
# import하지 않고 이 파일 안에서 완결시켜 SQLite↔Sheets 쪽 코드에는 전혀 손대지
# 않는다(target 문자열이 달라 메시지를 공유할 수 없음 — "target: calculators"로
# 고정돼 있어 그대로 재사용하면 축이 잘못 표시된다).
_LEVEL_BY_SEVERITY = {SEVERITY_WARN: "WARNING", SEVERITY_FAIL: "ERROR",
                      SEVERITY_CRITICAL: "CRITICAL"}
_MAX_LISTED_ENTRIES = 10  # 메시지 과다 방지(content_sync.py::_notify_anomalies와 동일 원칙)


def _build_site_mismatch_message(out: dict) -> tuple[str, str]:
    """(title, detail) 반환. `_site` HTML/JS 전체나 SM_CONFIG 원문 전체는 절대
    포함하지 않는다 — calculator_id/slug/severity/reasons(정규화된 짧은 문자열)만 담는다."""
    counts = out["severity"]
    title = "[CalcMate sync_mismatch] calculators _site drift"
    lines = [
        f"target: {_TARGET}",
        f"run_id: {out.get('run_id') or '(로그 저장 실패 — 미기록)'}",
        f"result: {out['result']}",
        f"total: {out['total']}",
        f"INFO: {counts[SEVERITY_INFO]}",
        f"WARN: {counts[SEVERITY_WARN]}",
        f"FAIL: {counts[SEVERITY_FAIL]}",
        f"CRITICAL: {counts[SEVERITY_CRITICAL]}",
        "",
    ]
    problems = [r for r in out.get("results", []) if r["severity"] != SEVERITY_INFO]
    for r in problems[:_MAX_LISTED_ENTRIES]:
        lines.append(
            f"calculator_id: {r.get('calculator_id')}\n"
            f"slug: {r.get('slug')}\n"
            f"severity: {r['severity']}\n"
            f"reason: {_reasons_for_log(r)}"
        )
    if len(problems) > _MAX_LISTED_ENTRIES:
        lines.append(f"…외 {len(problems) - _MAX_LISTED_ENTRIES}건")
    return title, "\n".join(lines)


def _notify_site_drift_result(cfg: dict, out: dict) -> None:
    """out["result"](WARN/FAIL/CRITICAL)에 맞춰 telegram_ops.notify_level()을
    호출한다. 새 Telegram 전송 함수를 만들지 않고 기존 단일 진입점을 그대로
    재사용한다. 실패해도 예외를 흡수하고 out["telegram_result"]/["telegram_error"]에만
    기록한다 — drift 판정 결과는 절대 건드리지 않는다."""
    level = _LEVEL_BY_SEVERITY.get(out["result"])
    if level is None:
        return
    try:
        from modules import telegram_ops
        title, detail = _build_site_mismatch_message(out)
        telegram_ops.notify_level(cfg, level, title, detail, event="sync_mismatch")
        out["telegram_result"] = "sent"
    except Exception as e:
        out["telegram_result"] = "failed"
        out["telegram_error"] = str(e)[:300]
