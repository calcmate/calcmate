# -*- coding: utf-8 -*-
"""
modules/calculator_3way_sync.py — calculators SQLite ↔ Google Sheets Drift Detector (READ-ONLY)

STEP35: 계산기 3-way(SQLite/Sheets/_site/Live) 감사(STEP34) 중 1단계.
"현재 SQLite와 Sheets의 calculators 데이터가 실제로 일치하는가?"를 판정한다.

compare_calculators_sqlite_vs_sheets()는 다음만 수행한다:
  1. SQLiteAdapter/SheetsAdapter로 calculators 전체를 각각 조회
     (CalculatorRepository 재사용 — 새 Sheets/SQLite 접근 코드를 만들지 않는다)
  2. id 기준으로 매칭 — 한쪽에만 있으면 CRITICAL, 같은 id가 중복되면 CRITICAL
     (CalculatorRepository.save()의 DuplicateCalculatorIdError와 동일한 원칙:
      임의로 하나를 골라 비교하지 않고 명시적으로 CRITICAL 처리한다)
  3. 매칭된 각 쌍을 COMPARE_FIELDS 기준으로 비교한다. 원본 값은 절대 바꾸지
     않고, 비교 전용 _normalize()로 표현형 차이(0 vs "0", None vs "" 등)만
     흡수한다 — STEP22~32에서 다룬 falsy 직렬화 결함을 이 비교 단계에서
     false positive로 재현하지 않기 위함이다.
  4. INFO(완전 일치)/WARN(비핵심 필드만 차이)/FAIL(운영 데이터 불일치)/
     CRITICAL(id 자체 불일치·중복·저장소 접근 실패)로 분류한다.

SQLite/Sheets 어디에도 쓰지 않는다(get_all()만 호출). AUTO-FIX 없음.
이 함수의 결과를 sync_runs/sync_log_entries에 실제로 저장하는 것은 이
STEP의 범위가 아니다(다음 STEP에서 사람 승인 후 연결) — 단, 반환 형태는
SyncLogRepository.insert_run()/insert_entry()가 기대하는 필드(severity별
카운트, run 단위 요약)와 곧바로 맞물리도록 설계했다.

DualAdapter(Sheets-primary/SQLite-secondary)는 그대로 두고 건드리지 않는다.
이 비교 함수는 DualAdapter를 거치지 않고 SQLiteAdapter/SheetsAdapter에
직접 연결한다 — DualAdapter의 읽기는 Sheets 우선 하나만 반환하므로 그
경유로는애초에 두 저장소의 드리프트 자체를 관측할 수 없다. config.yaml의
DB_ADAPTER 설정은 이 모듈이 읽지도 바꾸지도 않는다.
"""
from pathlib import Path
from repositories.calculator_repository import CalculatorRepository

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_FAIL = "FAIL"
SEVERITY_CRITICAL = "CRITICAL"

# 운영 데이터 "동일성" 판단에 필요한 핵심 필드만 비교한다(전체 컬럼 비교 아님).
# sync_status/created_at/updated_at/generated_at 등 저장소별 내부 기록 필드는
# 제외한다 — sync_status는 DualAdapter가 저장소마다 다르게 기록하는 내부
# 상태(STEP34에서 확인)이고, updated_at류는 쓰기 순서/재시도에 따라 두 저장소가
# 원천적으로 다른 시각을 가질 수 있어 그 차이 자체는 "데이터 불일치"가 아니다.
COMPARE_FIELDS = [
    "slug", "name", "status", "category",
    "review_score", "review_status", "review_attempts", "reviewed_at",
]

# reviewed_at만 다르고 나머지 COMPARE_FIELDS가 전부 동일하면 WARN(타임스탬프성
# 드리프트 — 검수 결과 자체는 같음)로만 처리한다. 그 외 필드 불일치는 FAIL.
SOFT_FIELDS = {"reviewed_at"}


def _normalize(value):
    """비교 전용 정규화. 원본 값은 절대 변경하지 않는다 — 반환값은 오직 이
    비교 함수 내부에서만 쓰인다(Repository/Adapter에 다시 쓰지 않음).

    - None과 공백뿐인 문자열은 "빈 값"으로 동일 취급한다(STEP24~32에서 이미
      확립된 프로젝트 관례 — None은 어댑터가 빈 문자열로 저장하는 기존 동작을
      그대로 둔다는 원칙과 같은 선상).
    - bool/int/float/숫자형 문자열은 정수로 떨어지면 정수 표기 문자열로
      통일한다(0, "0", 0.0, False가 전부 "0"으로 같아지도록).
    - 그 외는 str() + strip()으로 통일한다.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    s = str(value).strip()
    if s == "":
        return ""
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return s


def _classify_pair(calc_id: str, slug: str, sqlite_row: dict, sheets_row: dict) -> dict:
    """매칭된 SQLite/Sheets 행 1쌍을 비교해 판정 dict를 반환한다."""
    changed_fields = []
    hard_mismatch = False
    soft_mismatch = False

    for field in COMPARE_FIELDS:
        sv_raw = sqlite_row.get(field)
        hv_raw = sheets_row.get(field)
        if _normalize(sv_raw) == _normalize(hv_raw):
            continue
        changed_fields.append({
            "calculator_id": calc_id, "slug": slug, "field": field,
            "sqlite_value": sv_raw, "sheets_value": hv_raw,
            "reason": f"{field}_changed",
        })
        if field in SOFT_FIELDS:
            soft_mismatch = True
        else:
            hard_mismatch = True

    if hard_mismatch:
        severity = SEVERITY_FAIL
    elif soft_mismatch:
        severity = SEVERITY_WARN
    else:
        severity = SEVERITY_INFO

    reasons = [c["reason"] for c in changed_fields] or ["no_change"]
    return {"calculator_id": calc_id, "slug": slug, "severity": severity,
            "reasons": reasons, "changed_fields": changed_fields}


def _empty_result(counts: dict) -> dict:
    return {
        "total": 0, "matched": 0, "mismatched": 0,
        "missing_in_sqlite": [], "missing_in_sheets": [],
        "changed_fields": [], "severity": dict(counts), "reasons": [],
        "results": [],
    }


def compare_calculators_sqlite_vs_sheets(cfg: dict, sqlite_repo=None, sheets_repo=None) -> dict:
    """calculators SQLite↔Sheets 비교(READ-ONLY). 어디에도 쓰지 않는다.

    sqlite_repo/sheets_repo를 주입하지 않으면 실제 SQLiteAdapter/SheetsAdapter로
    직접 연결한다. 테스트에서는 get_all()만 구현한 스텁을 주입해 격리한다.

    반환:
      {total, matched, mismatched, missing_in_sqlite, missing_in_sheets,
       changed_fields, severity({INFO,WARN,FAIL,CRITICAL}), reasons, results}
    """
    counts = {SEVERITY_INFO: 0, SEVERITY_WARN: 0, SEVERITY_FAIL: 0, SEVERITY_CRITICAL: 0}

    try:
        if sqlite_repo is None:
            from adapters.db.sqlite_adapter import SQLiteAdapter
            sqlite_repo = CalculatorRepository(SQLiteAdapter(cfg))
        sqlite_rows = sqlite_repo.get_all()
    except Exception as e:
        out = _empty_result(counts)
        out["severity"][SEVERITY_CRITICAL] = 1
        out["reasons"] = [f"sqlite_access_failed: {e}"]
        out["results"] = [{"calculator_id": None, "slug": None, "severity": SEVERITY_CRITICAL,
                            "reasons": [f"sqlite_access_failed: {e}"], "changed_fields": []}]
        return out

    try:
        if sheets_repo is None:
            from adapters.db.sheets_adapter import SheetsAdapter
            sheets_repo = CalculatorRepository(SheetsAdapter(cfg))
        sheets_rows = sheets_repo.get_all()
    except Exception as e:
        out = _empty_result(counts)
        out["severity"][SEVERITY_CRITICAL] = 1
        out["reasons"] = [f"sheets_access_failed: {e}"]
        out["results"] = [{"calculator_id": None, "slug": None, "severity": SEVERITY_CRITICAL,
                            "reasons": [f"sheets_access_failed: {e}"], "changed_fields": []}]
        return out

    def _group_by_id(rows):
        grouped = {}
        for r in rows:
            grouped.setdefault(str(r.get("id", "")), []).append(r)
        return grouped

    sqlite_by_id = _group_by_id(sqlite_rows)
    sheets_by_id = _group_by_id(sheets_rows)

    all_ids = sorted(cid for cid in (set(sqlite_by_id) | set(sheets_by_id)) if cid)

    results = []
    changed_fields_all = []
    reasons_all = []
    missing_in_sqlite = []
    missing_in_sheets = []

    for cid in all_ids:
        s_matches = sqlite_by_id.get(cid, [])
        h_matches = sheets_by_id.get(cid, [])
        slug_hint = (s_matches[0].get("slug") if s_matches
                     else h_matches[0].get("slug") if h_matches else "")

        if len(s_matches) > 1 or len(h_matches) > 1:
            reasons = []
            if len(s_matches) > 1:
                reasons.append(f"duplicate_id_in_sqlite(count={len(s_matches)})")
            if len(h_matches) > 1:
                reasons.append(f"duplicate_id_in_sheets(count={len(h_matches)})")
            results.append({"calculator_id": cid, "slug": slug_hint, "severity": SEVERITY_CRITICAL,
                            "reasons": reasons, "changed_fields": []})
            counts[SEVERITY_CRITICAL] += 1
            reasons_all.extend(reasons)
            continue

        if not s_matches:
            missing_in_sqlite.append(cid)
            results.append({"calculator_id": cid, "slug": slug_hint, "severity": SEVERITY_CRITICAL,
                            "reasons": ["missing_in_sqlite"], "changed_fields": []})
            counts[SEVERITY_CRITICAL] += 1
            reasons_all.append("missing_in_sqlite")
            continue

        if not h_matches:
            missing_in_sheets.append(cid)
            results.append({"calculator_id": cid, "slug": slug_hint, "severity": SEVERITY_CRITICAL,
                            "reasons": ["missing_in_sheets"], "changed_fields": []})
            counts[SEVERITY_CRITICAL] += 1
            reasons_all.append("missing_in_sheets")
            continue

        entry = _classify_pair(cid, slug_hint, s_matches[0], h_matches[0])
        results.append(entry)
        counts[entry["severity"]] += 1
        if entry["changed_fields"]:
            changed_fields_all.extend(entry["changed_fields"])
            reasons_all.extend(entry["reasons"])

    total = len(all_ids)
    matched = counts[SEVERITY_INFO]
    mismatched = total - matched

    return {
        "total": total,
        "matched": matched,
        "mismatched": mismatched,
        "missing_in_sqlite": missing_in_sqlite,
        "missing_in_sheets": missing_in_sheets,
        "changed_fields": changed_fields_all,
        "severity": dict(counts),
        "reasons": reasons_all,
        "results": results,
    }


# ── STEP37: sync_runs/sync_log_calculator_entries 저장(판정 로직과 완전 분리) ──
_RESULT_PRIORITY = [SEVERITY_CRITICAL, SEVERITY_FAIL, SEVERITY_WARN]  # 없으면 PASS
RUN_RESULT_PASS = "PASS"


def _aggregate_result(severity_counts: dict) -> str:
    for sev in _RESULT_PRIORITY:
        if severity_counts.get(sev, 0) > 0:
            return sev
    return RUN_RESULT_PASS


def _to_log_reason(reason: str) -> str:
    """저장용 reason 문자열 변환(STEP37 §7 어휘에 맞춤). "field_changed" ->
    "field_mismatch"로만 바꾸고, 그 외(no_change/missing_in_*/duplicate_id_in_*)는
    이미 구조화된 문자열이라 그대로 둔다. compare_calculators_sqlite_vs_sheets()가
    반환하는 원본 reasons 자체는 건드리지 않는다(이 변환은 로그 저장 시점에만 적용)."""
    if reason.endswith("_changed"):
        return reason[: -len("_changed")] + "_mismatch"
    return reason


def run_calculator_3way_sync_and_log(cfg: dict, sqlite_repo=None, sheets_repo=None,
                                      log_repo=None) -> dict:
    """compare_calculators_sqlite_vs_sheets()를 그대로 호출하고(판정 로직 무변경),
    그 결과를 sync_runs(target="calculators")/sync_log_calculator_entries에
    저장한다. 로그 저장이 실패해도 판정 결과는 그대로 반환한다
    (blog_articles_sync.run_blog_articles_sync_and_log()와 동일한 원칙 —
    "판정 성공 + 로그 저장 실패"를 분리한다. DB INSERT 실패가 drift 판정 자체의
    실패로 바뀌지 않는다).

    반환: compare_calculators_sqlite_vs_sheets()의 모든 키 + 다음을 추가:
      result: CRITICAL>FAIL>WARN 우선순위로 정한 이번 run 전체 판정(없으면 PASS)
      run_id: 로그 저장에 성공했을 때만 값이 채워짐(실패 시 None)
      log_result: "saved" | "failed"
      log_error: 실패 사유 요약(성공 시 None)

    SQLite/Sheets calculators 테이블에는 이 함수도 어디에도 쓰지 않는다.
    허용되는 유일한 쓰기는 sync_runs/sync_log_calculator_entries INSERT뿐이다.
    """
    import time
    from datetime import datetime

    started_at = datetime.now().isoformat()
    t0 = time.monotonic()

    comparison = compare_calculators_sqlite_vs_sheets(cfg, sqlite_repo=sqlite_repo,
                                                       sheets_repo=sheets_repo)

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
        run_id = generate_run_id("calculators")

        log_repo.create_run({
            "run_id": run_id, "target": "calculators",
            "started_at": started_at, "finished_at": finished_at, "duration_ms": duration_ms,
            "result": out["result"], "total_count": comparison["total"],
            "info_count": counts[SEVERITY_INFO], "warn_count": counts[SEVERITY_WARN],
            "fail_count": counts[SEVERITY_FAIL], "critical_count": counts[SEVERITY_CRITICAL],
        })

        for r in comparison["results"]:
            reasons_str = ",".join(_to_log_reason(x) for x in r["reasons"])
            log_repo.insert_calculator_entry({
                "entry_id": generate_entry_id("calculators"), "run_id": run_id,
                "calculator_id": r.get("calculator_id") or "",
                "slug": r.get("slug") or "",
                "severity": r["severity"], "reasons": reasons_str,
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
        _notify_drift_result(cfg, out)

    return out


# ── STEP38: WARN/FAIL/CRITICAL만 Telegram sync_mismatch 알림(INFO/PASS는 전송 안 함) ──
_LEVEL_BY_SEVERITY = {SEVERITY_WARN: "WARNING", SEVERITY_FAIL: "ERROR",
                      SEVERITY_CRITICAL: "CRITICAL"}
_MAX_LISTED_ENTRIES = 10  # 메시지 과다 방지(content_sync.py::_notify_anomalies와 동일 원칙)


def _build_mismatch_message(out: dict) -> tuple[str, str]:
    """(title, detail) 반환. calculator 전체 row/JSON/HTML/본문/시크릿은 절대
    포함하지 않는다 — calculator_id/slug/severity/reasons(정규화된 짧은 문자열)만 담는다."""
    counts = out["severity"]
    title = "[CalcMate sync_mismatch] calculators drift"
    lines = [
        f"target: calculators",
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
        reasons = ",".join(_to_log_reason(x) for x in r["reasons"])
        lines.append(
            f"calculator_id: {r.get('calculator_id')}\n"
            f"slug: {r.get('slug')}\n"
            f"severity: {r['severity']}\n"
            f"reason: {reasons}"
        )
    if len(problems) > _MAX_LISTED_ENTRIES:
        lines.append(f"…외 {len(problems) - _MAX_LISTED_ENTRIES}건")
    return title, "\n".join(lines)


def _notify_drift_result(cfg: dict, out: dict) -> None:
    """out["result"](WARN/FAIL/CRITICAL)에 맞춰 telegram_ops.notify_level()을
    호출한다. 새 Telegram 전송 함수를 만들지 않고 기존 단일 진입점을 그대로
    재사용한다. 실패해도 예외를 흡수하고 out["telegram_result"]/["telegram_error"]에만
    기록한다 — drift 판정 결과(out["result"] 등)는 절대 건드리지 않는다."""
    level = _LEVEL_BY_SEVERITY.get(out["result"])
    if level is None:
        return
    try:
        from modules import telegram_ops
        title, detail = _build_mismatch_message(out)
        telegram_ops.notify_level(cfg, level, title, detail, event="sync_mismatch")
        out["telegram_result"] = "sent"
    except Exception as e:
        out["telegram_result"] = "failed"
        out["telegram_error"] = str(e)[:300]


# ══════════════════════════════════════════════════════════════════
# STEP74: 진짜 3-Way(SQLite/Sheets/_site) 판정 — 순수 classifier + 조합 wrapper
#
# 기존 compare_calculators_sqlite_vs_sheets()(이 파일)와
# calculator_site_sync.compare_calculators_sqlite_vs_site()는 단 한 줄도
# 수정하지 않는다. 이 섹션은 그 두 pairwise 결과를 "조합"만 한다 — 별도의
# Sheets↔_site 전용 adapter/repository는 만들지 않는다. 자동 스케줄러/
# Dashboard/Telegram 자동 연결은 이 STEP에서 하지 않는다(STEP75 이후 범위).
# ══════════════════════════════════════════════════════════════════

CLASSIFICATION_MATCH = "MATCH"
CLASSIFICATION_BACKUP_DRIFT = "BACKUP_DRIFT"
CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT = "DEPLOYED_ARTIFACT_DRIFT"
CLASSIFICATION_SQLITE_MAIN_DRIFT = "SQLITE_MAIN_DRIFT"
CLASSIFICATION_THREE_WAY_CONFLICT = "THREE_WAY_CONFLICT"
CLASSIFICATION_INTENTIONAL_HOLD = "INTENTIONAL_HOLD"
CLASSIFICATION_TEMPLATE_EXCEPTION = "TEMPLATE_EXCEPTION"

# STEP74 §8: "실제 배포 결과"는 현재 로컬 _site 파일 스냅샷 기준이다(Live HTTP
# 검증 아님) — STEP73 진단에서 확인된 사실을 결과에 명시적으로 남긴다.
DEPLOYED_RESULT_SOURCE = "local_site_artifact"

# STEP74 §7: SQLite↔Sheets가 실제로 비교하는 필드는 COMPARE_FIELDS(8개)뿐이다.
# 아래 필드들은 이번 STEP에서 비교 대상으로 추가하지 않고, 결과의 "coverage"에
# "아직 비교되지 않는다"는 사실만 명시한다(범위 확장은 별도 STEP).
UNCOMPARED_FIELDS = [
    "input_schema", "output_schema", "formula",
    "published_url", "description", "seo_desc",
]


def classify_three_way(sqlite_sheets_same: bool, sqlite_sheets_severity: str,
                        sqlite_site_same: bool, sqlite_site_severity: str,
                        sheets_site_same: bool,
                        intentional_hold: bool = False,
                        template_exception: bool = False) -> dict:
    """순수 함수 — I/O를 전혀 하지 않는다(테스트에서 직접 호출 가능).

    intentional_hold/template_exception은 호출부가 이미 registry/Tier2-B
    검증을 마친 결과만 전달해야 한다 — 이 함수 자체는 registry를 조회하지
    않으며, "조회 실패 시 정상으로 완화하지 않는다"는 원칙은 호출부
    (compare_calculators_three_way)의 책임이다.

    반환: {"classification": str, "severity": str}
    """
    if template_exception:
        return {"classification": CLASSIFICATION_TEMPLATE_EXCEPTION, "severity": SEVERITY_INFO}
    if intentional_hold:
        return {"classification": CLASSIFICATION_INTENTIONAL_HOLD, "severity": SEVERITY_INFO}

    if sqlite_sheets_same and sqlite_site_same:
        return {"classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO}

    if not sqlite_sheets_same and sqlite_site_same:
        # SQLite MAIN과 Sheets BACKUP만 다르고, 배포 결과는 SQLite와 일치.
        return {"classification": CLASSIFICATION_BACKUP_DRIFT, "severity": sqlite_sheets_severity}

    if sqlite_sheets_same and not sqlite_site_same:
        # SQLite MAIN과 Sheets BACKUP은 일치, 배포 결과만 뒤처짐/실패.
        return {"classification": CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT, "severity": sqlite_site_severity}

    # 여기부터는 sqlite_sheets_same == False and sqlite_site_same == False.
    if sheets_site_same:
        # Sheets와 배포 결과는 서로 일치하는데 SQLite MAIN만 다르다 — SQLite가
        # "틀렸다"고 단정하지 않고, SQLite MAIN 쪽이 나머지 둘과 다르다는
        # 사실만 명확히 표시한다(원인 판단은 사람의 몫).
        return {"classification": CLASSIFICATION_SQLITE_MAIN_DRIFT, "severity": SEVERITY_FAIL}

    return {"classification": CLASSIFICATION_THREE_WAY_CONFLICT, "severity": SEVERITY_CRITICAL}


def _sheets_and_site_agree(cfg: dict, slug: str, sheets_repo, site_dir) -> bool:
    """SQLite가 Sheets/_site 둘 다와 다른 극히 드문 경우에만 호출된다(그 외
    경우는 transitivity로 이미 결정 가능해 이 함수를 호출할 필요가 없다).
    새 adapter를 만들지 않고, 기존 pairwise 비교가 이미 쓰는 것과 동일한
    SheetsAdapter/_read_sm_config를 재사용해 name/slug만 직접 대조한다."""
    from pathlib import Path
    from modules.calculator_site_sync import _read_sm_config, _default_site_dir

    try:
        if sheets_repo is None:
            from adapters.db.sheets_adapter import SheetsAdapter
            sheets_repo = CalculatorRepository(SheetsAdapter(cfg or {}))
        sheets_rows = [r for r in sheets_repo.get_all() if str(r.get("slug", "")) == slug]
    except Exception:
        return False
    if not sheets_rows:
        return False
    sheets_row = sheets_rows[0]

    sd = Path(site_dir) if site_dir is not None else _default_site_dir()
    sm = _read_sm_config(sd, slug)
    if "_error" in sm:
        return False

    return (_normalize(sheets_row.get("name")) == _normalize(sm.get("name"))
            and str(sheets_row.get("slug", "")) == str(sm.get("slug", "")))


def compare_calculators_three_way(cfg: dict, sqlite_repo=None, sheets_repo=None,
                                   site_dir=None, sheets_vs_sqlite_out: dict = None,
                                   sqlite_vs_site_out: dict = None) -> dict:
    """SQLite/Sheets/_site 세 축을 조합한 3-Way 판정(READ-ONLY, 어디에도 쓰지
    않음). 기존 compare_calculators_sqlite_vs_sheets()와 calculator_site_sync.
    compare_calculators_sqlite_vs_site()를 그대로 재사용하고 그 결과만
    조합한다.

    sheets_vs_sqlite_out/sqlite_vs_site_out을 주입하면 그 결과를 그대로 쓰고
    다시 계산하지 않는다(테스트 격리 및 이중 조회 방지용).

    반환: {total, results, counts, deployed_result_source, coverage}
    """
    from modules.calculator_site_sync import (
        compare_calculators_sqlite_vs_site,
        _load_registry_entry_safe,
    )

    sheets_out = sheets_vs_sqlite_out if sheets_vs_sqlite_out is not None else \
        compare_calculators_sqlite_vs_sheets(cfg, sqlite_repo=sqlite_repo, sheets_repo=sheets_repo)
    site_out = sqlite_vs_site_out if sqlite_vs_site_out is not None else \
        compare_calculators_sqlite_vs_site(cfg, sqlite_repo=sqlite_repo, site_dir=site_dir)

    sheets_by_slug = {r.get("slug"): r for r in sheets_out.get("results", []) if r.get("slug")}
    site_by_slug = {r.get("slug"): r for r in site_out.get("results", []) if r.get("slug")}

    all_slugs = sorted(set(sheets_by_slug) | set(site_by_slug))

    results = []
    counts: dict = {}
    for slug in all_slugs:
        sh = sheets_by_slug.get(slug)
        st = site_by_slug.get(slug)

        sqlite_sheets_same = bool(sh) and sh["severity"] == SEVERITY_INFO
        sqlite_sheets_severity = sh["severity"] if sh else SEVERITY_CRITICAL

        sqlite_site_same = bool(st) and st["severity"] == SEVERITY_INFO
        sqlite_site_severity = st["severity"] if st else SEVERITY_CRITICAL

        template_exception = bool(st) and st.get("reasons") == ["tier2b_template_exception_verified"]

        intentional_hold = False
        if (st and not template_exception and st["severity"] == SEVERITY_CRITICAL
                and st.get("reasons") == ["index_html_missing"]):
            # STEP74 §5: registry 조회 실패 시 절대 정상으로 완화하지 않는다 —
            # _load_registry_entry_safe()는 조회 실패 시 {}를 반환하므로
            # status가 "HOLD"로 확인될 때만 intentional_hold=True가 된다.
            reg = _load_registry_entry_safe(slug)
            intentional_hold = reg.get("status") == "HOLD"

        sheets_site_same = True
        if (not sqlite_sheets_same and not sqlite_site_same
                and not template_exception and not intentional_hold):
            sheets_site_same = _sheets_and_site_agree(cfg, slug, sheets_repo, site_dir)

        result = classify_three_way(
            sqlite_sheets_same, sqlite_sheets_severity,
            sqlite_site_same, sqlite_site_severity,
            sheets_site_same,
            intentional_hold=intentional_hold,
            template_exception=template_exception,
        )
        result["slug"] = slug
        result["calculator_id"] = (sh or st or {}).get("calculator_id")
        results.append(result)
        counts[result["classification"]] = counts.get(result["classification"], 0) + 1

    return {
        "total": len(all_slugs),
        "results": results,
        "counts": counts,
        "deployed_result_source": DEPLOYED_RESULT_SOURCE,
        "coverage": {
            "compared_fields": list(COMPARE_FIELDS),
            "uncompared_fields": list(UNCOMPARED_FIELDS),
        },
    }


# ══════════════════════════════════════════════════════════════════
# STEP75: 3-Way 이상감지 → Telegram 자동 알림 연결
#
# compare_calculators_three_way()의 판정 결과 자체는 절대 바꾸지 않는다(이
# 함수는 그 결과를 "읽기만" 하고 별도의 알림 리스트를 반환한다). 스케줄러/
# Dashboard/복구 로직 어디에도 새로 연결하지 않는다 — 이 함수를 실제로
# 호출하는 것은 이 STEP의 범위 밖(사람이 수동으로, 또는 향후 STEP에서 결정).
# ══════════════════════════════════════════════════════════════════

# 알림 대상: 이 4개 classification + severity가 WARN/FAIL/CRITICAL일 때만.
# MATCH/INTENTIONAL_HOLD/TEMPLATE_EXCEPTION은 여기 없으므로 절대 알림 대상이
# 되지 않는다(재분류하지 않고 그냥 continue로 건너뛴다).
_THREE_WAY_ANOMALY_CLASSIFICATIONS = {
    CLASSIFICATION_BACKUP_DRIFT,
    CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT,
    CLASSIFICATION_SQLITE_MAIN_DRIFT,
    CLASSIFICATION_THREE_WAY_CONFLICT,
}
_THREE_WAY_ANOMALY_SEVERITIES = {SEVERITY_WARN, SEVERITY_FAIL, SEVERITY_CRITICAL}
_THREE_WAY_LEVEL_BY_SEVERITY = {
    SEVERITY_WARN: "WARNING", SEVERITY_FAIL: "ERROR", SEVERITY_CRITICAL: "CRITICAL",
}


def _build_three_way_anomaly_message(entry: dict, sheets_by_slug: dict, site_by_slug: dict,
                                      deployed_result_source: str, run_id) -> tuple[str, str]:
    """(title, detail) 반환. slug/calculator_id/reason(짧은 문자열)만 담고
    row 전체/HTML 원문은 절대 포함하지 않는다."""
    slug = entry.get("slug")
    sh = sheets_by_slug.get(slug) or {}
    st = site_by_slug.get(slug) or {}
    sheets_axis = "MATCH" if (not sh) or sh.get("severity") == SEVERITY_INFO else "DRIFT"
    site_axis = "MATCH" if (not st) or st.get("severity") == SEVERITY_INFO else "DRIFT"
    reasons = list(sh.get("reasons") or []) + list(st.get("reasons") or [])
    reason = ", ".join(r for r in reasons if r and r != "no_change") or "unknown"

    title = "[CalcMate 3-Way 이상감지]"
    lines = [
        f"result: {entry.get('classification')}",
        f"severity: {entry.get('severity')}",
        f"calculator: {slug}",
        f"calculator_id: {entry.get('calculator_id')}",
        f"reason: {reason}",
        f"run_id: {run_id if run_id else '(no run_id)'}",
        f"deployed_result_source: {deployed_result_source}",
        f"SQLite ↔ Sheets: {sheets_axis}",
        f"SQLite ↔ _site: {site_axis}",
    ]
    return title, "\n".join(lines)


def notify_three_way_anomalies(cfg: dict, three_way_out: dict, sheets_out: dict = None,
                                site_out: dict = None, run_id=None) -> list:
    """STEP75: 3-Way 판정 결과 중 실제 이상만 Telegram으로 알린다.

    알림 대상: classification이 BACKUP_DRIFT/DEPLOYED_ARTIFACT_DRIFT/
    SQLITE_MAIN_DRIFT/THREE_WAY_CONFLICT 이고 severity가 WARN/FAIL/CRITICAL일
    때만. MATCH/INTENTIONAL_HOLD/TEMPLATE_EXCEPTION은 절대 알리지 않으며,
    이 함수는 그것들을 다른 severity로 재분류하지도 않는다(그냥 건너뜀).

    three_way_out은 읽기만 하고 절대 수정하지 않는다 — 반환값은 항상 새
    리스트다. 같은 (run_id, calculator_id, classification, severity) 조합은
    이 함수 1회 호출 내에서 한 번만 알린다(메모리 dedup — DB schema 추가 없음,
    같은 실행 범위를 벗어나는 영구 이력은 이 STEP 범위 밖).

    Telegram 호출이 실패해도 예외를 흡수하고 해당 항목의 telegram_result에만
    기록한다 — 다른 항목이나 detector 결과에는 전혀 영향을 주지 않는다.
    """
    sheets_by_slug = {r.get("slug"): r for r in (sheets_out or {}).get("results", []) if r.get("slug")}
    site_by_slug = {r.get("slug"): r for r in (site_out or {}).get("results", []) if r.get("slug")}
    deployed_result_source = three_way_out.get("deployed_result_source", DEPLOYED_RESULT_SOURCE)

    seen = set()
    notifications = []
    for entry in three_way_out.get("results", []):
        classification = entry.get("classification")
        severity = entry.get("severity")
        if classification not in _THREE_WAY_ANOMALY_CLASSIFICATIONS:
            continue
        if severity not in _THREE_WAY_ANOMALY_SEVERITIES:
            continue

        dedup_key = (run_id, entry.get("calculator_id"), classification, severity)
        record = {"slug": entry.get("slug"), "calculator_id": entry.get("calculator_id"),
                  "classification": classification, "severity": severity}
        if dedup_key in seen:
            record["telegram_result"] = "skipped_duplicate"
            notifications.append(record)
            continue
        seen.add(dedup_key)

        title, detail = _build_three_way_anomaly_message(
            entry, sheets_by_slug, site_by_slug, deployed_result_source, run_id)
        level = _THREE_WAY_LEVEL_BY_SEVERITY.get(severity, "ERROR")
        try:
            from modules import telegram_ops
            telegram_ops.notify_level(cfg, level, title, detail, event="sync_mismatch")
            record["telegram_result"] = "sent"
        except Exception as e:
            record["telegram_result"] = "failed"
            record["telegram_error"] = str(e)[:300]
        notifications.append(record)

    return notifications


# ══════════════════════════════════════════════════════════════════
# STEP76: 기존 운영 실행 경로용 안전 진입점
#
# 이 함수는 어떤 예외도 호출자에게 전파하지 않는다 — 3-Way 감지/알림은
# observability 계층이며, 이것이 실패해도 기존 Calculator 웹앱 생성/배포 같은
# 핵심 운영 작업 자체가 실패해서는 안 된다는 원칙(STEP76 §5)을 여기서 지킨다.
# compare_calculators_sqlite_vs_sheets()/calculator_site_sync.
# compare_calculators_sqlite_vs_site()/compare_calculators_three_way()/
# notify_three_way_anomalies() 중 어느 것도 이 함수 안에서 수정하지 않는다 —
# 그대로 순서대로 호출만 한다.
# ══════════════════════════════════════════════════════════════════
from .logger import get_logger as _get_logger

LOG = _get_logger()


def run_three_way_anomaly_check_safely(cfg: dict, run_id=None) -> dict:
    """기존 운영 실행 경로(예: calc_webapp 스케줄러)에서 호출하기 위한 안전
    진입점. SQLite↔Sheets, SQLite↔_site를 각각 조회하고 3-Way로 조합한 뒤,
    이상이 있으면 Telegram으로 알린다(notify_three_way_anomalies의 4개
    classification+WARN/FAIL/CRITICAL 규칙 그대로 적용 — 이 함수는 그 규칙을
    바꾸지 않는다).

    이 함수 안에서 발생하는 모든 예외는 흡수되고 {"status": "error", ...}로만
    반환된다 — 호출자의 실제 운영 작업(생성/배포 등)에는 절대 영향을 주지
    않는다."""
    try:
        sheets_out = compare_calculators_sqlite_vs_sheets(cfg)
        from modules.calculator_site_sync import compare_calculators_sqlite_vs_site
        site_out = compare_calculators_sqlite_vs_site(cfg)
        three_way_out = compare_calculators_three_way(
            cfg, sheets_vs_sqlite_out=sheets_out, sqlite_vs_site_out=site_out)
        notifications = notify_three_way_anomalies(
            cfg, three_way_out, sheets_out=sheets_out, site_out=site_out, run_id=run_id)
        return {"status": "ok", "counts": three_way_out.get("counts", {}),
                "notifications": notifications}
    except Exception as e:
        LOG.warning("[3way] 이상감지 실행 실패(기존 운영 작업에는 영향 없음): %s", e)
        return {"status": "error", "error": str(e)[:300]}


# ══════════════════════════════════════════════════════════════════
# STEP78: Live 배포 결과(calcmate.kr) 최소 검증 — 관측 전용 축 추가
#
# 기존 7개 classification/classify_three_way()/두 pairwise detector는 단 한
# 줄도 수정하지 않는다. 이 섹션은 local `_site`와 실제 공개 URL을 비교해
# 별도의 live_status만 만든다 — 그 값을 기존 3-way 판정에 강제로 편입시키지
# 않는다(STEP77 조사에서 확인된 대로 GitHub Pages 커스텀 도메인 리다이렉트가
# 안정적이고 Cloudflare 캐시가 비활성이라 HTTP GET 방식이 안전하다고 판단됨).
# ══════════════════════════════════════════════════════════════════

LIVE_MATCH = "MATCH"
LIVE_MATCH_NORMALIZED = "MATCH_NORMALIZED"
LIVE_DEPLOYED_DRIFT = "DEPLOYED_LIVE_DRIFT"
LIVE_UNAVAILABLE = "LIVE_UNAVAILABLE"

LIVE_BASE_URL = "https://calcmate.kr"


def build_live_url(slug: str) -> str:
    """slug → 실제 공개 URL. 순수 함수 — 네트워크/DB/파일 접근 없음, 부작용 없음.
    기존 published_url 필드는 읽지도 쓰지도 않는다(STEP77에서 확인된 대로 일부
    구 슬러그는 published_url이 여전히 calcmate.github.io를 가리키지만, 그
    값과 무관하게 이 헬퍼는 항상 canonical 도메인을 직접 구성한다)."""
    return f"{LIVE_BASE_URL}/{slug}/"


def normalize_live_compare_bytes(data: bytes) -> bytes:
    """STEP80: Live 비교 전용 최소 정규화 — CRLF(\\r\\n) → LF(\\n) 치환만 한다.
    순수 함수(파일/DB/HTTP 접근 없음, 전역 상태 변경 없음). strip/HTML minify/
    공백 제거/encoding 변환/DOM 재구성/script 수정은 절대 하지 않는다(STEP79에서
    정책 검증됨 — 이 하나의 치환만으로 local↔live 완전 동일성이 확인됐으므로
    그 이상은 허용하지 않는다)."""
    return data.replace(b"\r\n", b"\n")


def _classify_live_request_error(exc: Exception) -> str:
    """requests 예외를 timeout/dns_failure/connection_failure/invalid_response로
    분류한다(콘텐츠 불일치와 절대 혼동하지 않기 위함, STEP78 §3)."""
    import requests
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        msg = str(exc).lower()
        if ("name or service not known" in msg or "getaddrinfo failed" in msg
                or "nodename nor servname" in msg or "name resolution" in msg):
            return "dns_failure"
        return "connection_failure"
    return "invalid_response"


def compare_local_site_vs_live(slug: str, local_html_path, timeout: float = 10.0) -> dict:
    """local `_site/<slug>/index.html`과 실제 공개 URL(https://calcmate.kr/<slug>/)을
    READ-ONLY로 비교한다. GET 요청 1회만 수행하며 어디에도 쓰지 않는다.

    반환(live_status 구조, STEP78 §5 + STEP80 §5 + STEP86 §3/§4):
      {"status": "MATCH"|"MATCH_NORMALIZED"|"DEPLOYED_LIVE_DRIFT"|"LIVE_UNAVAILABLE",
       "requested_url": str, "final_url": str|None,
       "local_sha256": str|None, "live_sha256": str|None,
       "http_status": int|None, "error_type": str|None,
       "local_artifact_exists": bool,
       # HTTP 응답을 실제로 받은 경우에만 추가로 포함(STEP85 캐시 오탐 진단 근거):
       "cache_control": str|None, "cf_cache_status": str|None, "age": str|None,
       "etag": str|None, "last_modified": str|None,
       # MATCH_NORMALIZED일 때만 추가로 포함:
       "normalization": "crlf_to_lf", "local_sha256_normalized": str, "live_sha256_normalized": str}

    판정 순서(STEP80 §4): raw 일치 → MATCH. raw 불일치 시 CRLF→LF 정규화 후
    재비교 → 일치하면 MATCH_NORMALIZED(정규화는 CRLF→LF 하나만 허용 —
    strip/minify/공백제거/encoding변환/DOM재구성은 절대 하지 않음). 그래도
    다르면 DEPLOYED_LIVE_DRIFT.

    STEP86: local 파일이 없어도(local_artifact_exists=False) Live HTTP GET은
    항상 실행한다 — STEP85에서 확인된 대로, local이 없다는 이유만으로 조기
    반환하면 실제 Live 상태(정상 노출 지속/진짜 제거됨/캐시 오탐 등)를 영원히
    확인할 수 없다. local 존재 여부는 모든 반환 경로에 독립 metadata
    (local_artifact_exists)로만 기록하고, 기존 status/error_type 판정 우선순위
    (HTTP 오류 > 콘텐츠 비교)와 기존 enum(MATCH/MATCH_NORMALIZED/
    DEPLOYED_LIVE_DRIFT/LIVE_UNAVAILABLE)은 그대로 둔다 — 새 상태를 추가하지
    않는다. local이 없어 콘텐츠 비교 자체가 불가능한 채로 HTTP 200을 받은
    경우에는 기존과 동일하게 status=LIVE_UNAVAILABLE, error_type=
    "local_file_missing"으로 표시하되(하위 호환 유지), 이번엔 실제로 GET을
    수행했으므로 http_status/live_sha256/캐시 헤더는 실측값을 담는다(STEP84/85가
    바로 이 정보가 없어 "200인데 왜 안 보이나"를 즉시 판별하지 못했던 사례).

    HTML 본문 자체는 절대 반환값에 담지 않는다(해시만 비교/기록).
    리다이렉트가 발생하면(STEP77에서 확인된 GitHub Pages 커스텀 도메인
    리다이렉트 등) 최종 URL의 응답 본문을 사용한다 — 요청 URL 문자열이
    다르다는 이유만으로 DRIFT 처리하지 않는다."""
    import hashlib

    requested_url = build_live_url(slug)
    local_path = Path(local_html_path)

    local_artifact_exists = local_path.exists()
    local_bytes = None
    local_sha256 = None

    if local_artifact_exists:
        try:
            local_bytes = local_path.read_bytes()
        except Exception:
            return {"status": LIVE_UNAVAILABLE, "requested_url": requested_url,
                    "final_url": None, "local_sha256": None, "live_sha256": None,
                    "http_status": None, "error_type": "local_read_failed",
                    "local_artifact_exists": local_artifact_exists}
        local_sha256 = hashlib.sha256(local_bytes).hexdigest()

    try:
        import requests
        resp = requests.get(requested_url, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return {"status": LIVE_UNAVAILABLE, "requested_url": requested_url,
                "final_url": None, "local_sha256": local_sha256, "live_sha256": None,
                "http_status": None, "error_type": _classify_live_request_error(e),
                "local_artifact_exists": local_artifact_exists}

    final_url = resp.url
    http_status = resp.status_code
    cache_meta = {
        "cache_control": resp.headers.get("Cache-Control"),
        "cf_cache_status": resp.headers.get("CF-Cache-Status"),
        "age": resp.headers.get("Age"),
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
    }

    if http_status >= 500:
        error_type = "http_5xx"
    elif http_status >= 400:
        error_type = "http_4xx"
    elif http_status != 200:
        error_type = "unexpected_status"
    else:
        error_type = None

    if error_type is not None:
        return {"status": LIVE_UNAVAILABLE, "requested_url": requested_url,
                "final_url": final_url, "local_sha256": local_sha256, "live_sha256": None,
                "http_status": http_status, "error_type": error_type,
                "local_artifact_exists": local_artifact_exists, **cache_meta}

    live_sha256 = hashlib.sha256(resp.content).hexdigest()

    if not local_artifact_exists:
        # local 비교 기준이 없어 MATCH/DRIFT 판정은 불가능하지만, GET은 실제로
        # 수행했으므로 그 결과(200/live_sha256/캐시 헤더)는 그대로 보존한다.
        return {"status": LIVE_UNAVAILABLE, "requested_url": requested_url,
                "final_url": final_url, "local_sha256": None, "live_sha256": live_sha256,
                "http_status": http_status, "error_type": "local_file_missing",
                "local_artifact_exists": False, **cache_meta}

    # 1차: raw byte 완전 일치
    if live_sha256 == local_sha256:
        return {"status": LIVE_MATCH, "requested_url": requested_url, "final_url": final_url,
                "local_sha256": local_sha256, "live_sha256": live_sha256,
                "http_status": http_status, "error_type": None,
                "local_artifact_exists": True, **cache_meta}

    # 2차: CRLF→LF 정규화 후 일치(STEP79에서 안전성 검증된 유일한 정규화)
    local_normalized = normalize_live_compare_bytes(local_bytes)
    live_normalized = normalize_live_compare_bytes(resp.content)
    if local_normalized == live_normalized:
        return {"status": LIVE_MATCH_NORMALIZED, "requested_url": requested_url, "final_url": final_url,
                "local_sha256": local_sha256, "live_sha256": live_sha256,
                "http_status": http_status, "error_type": None,
                "local_artifact_exists": True,
                "normalization": "crlf_to_lf",
                "local_sha256_normalized": hashlib.sha256(local_normalized).hexdigest(),
                "live_sha256_normalized": hashlib.sha256(live_normalized).hexdigest(),
                **cache_meta}

    # 3차: 정규화 후에도 다름 — 실제 콘텐츠 드리프트
    return {"status": LIVE_DEPLOYED_DRIFT, "requested_url": requested_url, "final_url": final_url,
            "local_sha256": local_sha256, "live_sha256": live_sha256,
            "http_status": http_status, "error_type": None,
            "local_artifact_exists": True, **cache_meta}


def attach_live_status_to_three_way(three_way_out: dict, site_dir=None, timeout: float = 10.0,
                                     slugs: list = None) -> dict:
    """기존 3-way 결과(three_way_out)를 그대로 두고, 각 result 항목에
    "live_status" 키만 추가한 새 dict를 반환한다(원본은 수정하지 않음 —
    STEP76까지의 원칙과 동일하게 detector 결과 불변).

    기존 classification/severity/reason은 절대 바꾸지 않는다 — Live 상태는
    독립적인 관측 축으로만 첨부된다(STEP78 §6).

    slugs를 지정하면 그 slug들에 대해서만 Live 검증을 수행한다(전체 계산기를
    매번 GET하면 외부 요청 부담이 크므로 — 이 함수 자체는 slug 선택 정책을
    강제하지 않고 호출부가 결정하게 둔다)."""
    from modules.calculator_site_sync import _default_site_dir

    sd = Path(site_dir) if site_dir is not None else _default_site_dir()
    target_slugs = set(slugs) if slugs is not None else {r.get("slug") for r in three_way_out.get("results", [])}

    new_results = []
    for entry in three_way_out.get("results", []):
        entry_copy = dict(entry)
        slug = entry.get("slug")
        if slug in target_slugs:
            local_path = sd / slug / "index.html"
            try:
                entry_copy["live_status"] = compare_local_site_vs_live(slug, local_path, timeout=timeout)
            except Exception as e:
                # 한 slug의 Live 검증이 예기치 않게 터져도 나머지 slug 처리와
                # 기존 3-way 결과(entry_copy의 classification/severity/reason)에는
                # 전혀 영향을 주지 않는다 — observability 축의 실패는 격리한다.
                LOG.warning("[3way-live] %s Live 검증 실패(격리됨): %s", slug, e)
                entry_copy["live_status"] = {
                    "status": LIVE_UNAVAILABLE, "requested_url": build_live_url(slug),
                    "final_url": None, "local_sha256": None, "live_sha256": None,
                    "http_status": None, "error_type": "internal_error",
                    "local_artifact_exists": None,
                }
        new_results.append(entry_copy)

    out_copy = dict(three_way_out)
    out_copy["results"] = new_results
    return out_copy


# ══════════════════════════════════════════════════════════════════
# STEP83: 독립 Live Health Check — 자동 운영 체인(run_calc_webapp_once →
# run_three_way_anomaly_check_safely)과 완전히 분리된 진입점.
#
# STEP82의 결정("B. Live 독립 검증 유지")을 그대로 구현한다. 이 함수는
# run_calc_webapp_once()/run_three_way_anomaly_check_safely()/Dashboard/
# Scheduler 어디에서도 호출하지 않는다 — 사람이 명시적으로 호출해야만
# 실행되는 완전히 독립적인 진입점이다. 기존 compare_local_site_vs_live()/
# normalize_live_compare_bytes()의 MATCH/MATCH_NORMALIZED/DEPLOYED_LIVE_DRIFT/
# LIVE_UNAVAILABLE 판정 정책은 단 한 줄도 재구현하지 않고 그대로 재사용한다.
# ══════════════════════════════════════════════════════════════════

def run_live_health_check(cfg: dict, slugs: list = None, site_dir=None,
                           timeout: float = 10.0, sqlite_repo=None) -> dict:
    """local `_site` ↔ 실제 공개 Live URL을 계산기별로 순차 검사한다
    (READ-ONLY, 관찰 전용 — DB/Sheets/_site/Registry/pending_sync/sync_log/
    sync_runs 어디에도 쓰지 않는다. Telegram도 호출하지 않는다).

    slugs=None이면 SQLite calculators 전체(현재 운영 대상)를 대상으로 하고,
    slugs=["slug1", ...]로 지정하면 그 slug들만 검사한다(배포 직후 특정
    계산기만 확인하는 용도).

    순차 GET 1건씩만 수행한다 — 병렬/재시도/무한 루프 없음(STEP83 §6).
    한 slug의 검사가 예기치 않게 예외를 던져도 전체 실행은 중단되지 않고
    해당 slug만 LIVE_UNAVAILABLE(error_type="internal_error")로 기록된다.

    반환: {"status": "ok"|"error", "counts": {status: count, ...}, "results": [...]}
    각 result: {"slug": str, **compare_local_site_vs_live()의 반환 필드}
    """
    from modules.calculator_site_sync import _default_site_dir

    if slugs is None:
        if sqlite_repo is None:
            from adapters.db.sqlite_adapter import SQLiteAdapter
            sqlite_repo = CalculatorRepository(SQLiteAdapter(cfg or {}))
        try:
            rows = sqlite_repo.get_all()
        except Exception as e:
            return {"status": "error", "error": str(e)[:300], "counts": {}, "results": []}
        target_slugs = sorted({str(r.get("slug", "")) for r in rows if r.get("slug")})
    else:
        target_slugs = list(slugs)

    sd = Path(site_dir) if site_dir is not None else _default_site_dir()

    results = []
    counts: dict = {}
    for slug in target_slugs:
        local_path = sd / slug / "index.html"
        try:
            r = compare_local_site_vs_live(slug, local_path, timeout=timeout)
        except Exception as e:
            LOG.warning("[live-health] %s Live Health Check 실패(격리됨, 나머지 계속 진행): %s", slug, e)
            r = {"status": LIVE_UNAVAILABLE, "requested_url": build_live_url(slug),
                 "final_url": None, "local_sha256": None, "live_sha256": None,
                 "http_status": None, "error_type": "internal_error",
                 "local_artifact_exists": None}
        entry = {"slug": slug, **r}
        results.append(entry)
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {"status": "ok", "counts": counts, "results": results}
