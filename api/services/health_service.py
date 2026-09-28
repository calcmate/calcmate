"""api/services/health_service.py — 로컬 application/data 상태 조회 (STEP 18-M).

외부 서비스(WordPress/GitHub/Cloudflare/Google Sheets/Telegram/Image API/OpenRouter)는
절대 호출하지 않는다. 이 서비스가 확인하는 것은 다음 두 가지뿐이다:
  1) 기존 Scheduler(WorkerManager)의 실제 상태 조회 재사용(재구현하지 않음, STEP 18-I-A)
  2) 보호 대상 파일들의 단순 존재 여부(exists()만 — 해시 비교/내용 검증은 하지 않는다.
     baseline 해시를 하드코딩하지 않는다는 이번 STEP의 원칙을 따른다)
"""
import json
from pathlib import Path

from api.services.worker_manager import get_worker_manager

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DATA_FILES = {
    "database": _PROJECT_ROOT / "data" / "blog_auto.db",
    "config": _PROJECT_ROOT / "config" / "config.yaml",
    "registry": _PROJECT_ROOT / "docs" / "registry_auto.yaml",
    "labor_af": _PROJECT_ROOT / "docs" / "registry" / "labor_af.yaml",
    "pipeline_log": _PROJECT_ROOT / "data" / "logs" / "pipeline.log",
}


def get_health_details() -> dict:
    wm = get_worker_manager()
    return {
        "application": {
            "fastapi": "healthy",
        },
        "schedulers": wm.get_status(),
        "data": {name: path.exists() for name, path in _DATA_FILES.items()},
    }


# ── STEP S3: 외부 서비스 실질 헬스체크(Streamlit "🏥 헬스체크 센터" 이관) ──────
# 위 get_health_details()와 달리 실제 외부 API(OpenAI/Claude/Gemini/Sheets/Drive/
# WordPress)를 호출한다. dashboard.py의 hc_mod.run()/critical_passed()를 그대로
# 재사용하며, 판정 로직은 재구현하지 않는다(읽기 전용 재사용).
def get_external_health_cache() -> dict:
    """마지막 실질 헬스체크 결과를 캐시 파일에서 그대로 읽는다(재실행하지 않음).

    dashboard.py의 _read_health_cache()는 프로젝트 루트의 data/logs/health_last.json을
    읽지만, 실제로 health_monitor.run()이 쓰는 경로는 modules/utils/data/logs/
    health_last.json이다(두 경로가 서로 다른 기존 Streamlit 버그). 이 함수는 실제로
    갱신되는 쪽인 health_monitor.RESULT_PATH를 그대로 사용한다.
    """
    from modules.utils import health_monitor as hc_mod

    if not hc_mod.RESULT_PATH.exists():
        return {"available": False, "timestamp": None, "checks": {}, "critical_passed": None}
    try:
        results = json.loads(hc_mod.RESULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "timestamp": None, "checks": {}, "critical_passed": None}
    return _shape_results(results, hc_mod)


def run_external_health_check() -> dict:
    """실시간으로 실질 헬스체크를 실행한다(외부 API 실제 호출, 비용/시간 발생).

    개별 체크의 실패(FAIL)는 health_monitor.run() 내부에서 이미 각자 처리된다.
    여기서 잡는 예외는 그 바깥(예: config.yaml 자체가 깨져 load_config()가
    실패하는 경우)만 대상이며, 명확한 실패 상태로 반환한다(원본 함수는 수정하지
    않는다 — 새 API 경계에서만 방어한다).
    """
    from modules.config_loader import load_config
    from modules.utils import health_monitor as hc_mod

    try:
        cfg = load_config()
        results = hc_mod.run(cfg)
    except Exception as e:
        return {"available": False, "timestamp": None, "checks": {},
                "critical_passed": False, "error": str(e)}
    return _shape_results(results, hc_mod)


def _shape_results(results: dict, hc_mod) -> dict:
    checks = {k: v for k, v in results.items() if k != "timestamp"}
    return {
        "available": True,
        "timestamp": results.get("timestamp"),
        "checks": checks,
        "critical_passed": hc_mod.critical_passed(results),
    }
