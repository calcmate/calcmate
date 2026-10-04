"""api/services/integrated_run_service.py — Dashboard Quick Action 「▶ 실행」
통합 실행 서비스.

STEP S13: dashboard.py의 "▶ 실행" 버튼(dashboard.py:432-469, render_quick_actions()
의 qa_run)과 동일한 실행 의미를 재현한다. 이 버튼은 새 파이프라인이 아니라
"현재 site의 활성 platforms"에 따라 이미 존재하는 두 entry point 중 하나(또는
둘 다 순차)를 고르는 얇은 dispatcher다 — 새 pipeline을 만들지 않고, STEP S11/
S12에서 이미 lock까지 포함해 구현한 서비스 함수를 그대로 재사용한다:

  - has_wp and has_calc:
      order == "Calculator만" → calculator_quick_action_service.run_once()  (S11)
      order == "WordPress만"  → pipeline_run_service.run_once()             (S12)
      그 외(기본값 "순차(Calculator→WordPress)")
                              → 위 두 서비스를 순서대로 호출, 각 반환값은 모두
                                버리고 고정 문자열만 반환(dashboard.py의
                                _run_seq()가 실제로 이렇게 동작함 — 그대로 재현,
                                수정하지 않음)
  - has_calc만                → calculator_quick_action_service.run_once()
  - 그 외(WordPress-only 또는 site/platform 미설정) → pipeline_run_service.run_once()

site/platform 해석(CALCMATE-STREAMLIT-REMAINING-MIGRATION-CURRENT-SITE-02):
dashboard.py의 _resolve_run_site()와 동일하게 "현재 site"의 platforms를 쓴다.
  - 요청에 site_id가 있으면(React 현재 Site 선택) 서버가 SiteManager.get_by_id()로
    다시 조회해 그 site의 platforms를 쓴다. 상태(active/inactive/archived)와 무관
    — dashboard.py도 선택된 site를 상태 확인 없이 사용했다. 존재하지 않는 site_id는
    IntegratedRunSiteNotFound(첫 번째 site로 조용히 대체하지 않음 — 정상 selectbox
    상태가 아닌 잘못된 요청이므로).
  - site_id가 없으면 dashboard.py의 기본값과 같이 전체 site 목록(상태 무관, 저장소
    순서)의 첫 번째 site를 쓴다. site가 하나도 없으면 platforms=[] → Blog pipeline.
    (이전의 "첫 번째 active site" 임시 해석은 이 계약으로 대체됐다.)

중복 실행 방지: 개별 branch의 lock은 각 서비스가 이미 보유(calculator_quick_
action_service→기존 계산기 lock, pipeline_run_service→기존 blog scheduler
lock) — 이 파일에서 새 lock을 만들지 않는다. "순차" branch는 두 서비스를
차례로 호출할 뿐이며, dashboard.py의 _run_seq()도 두 호출 전체를 감싸는 outer
lock이 없다 — 동일하게 재현한다(전체 combined action에 대한 원자성은 원본에도
없었다는 뜻이며, 이번 STEP에서 새로 추가하지 않는다).
"""
import json as _json

from modules.config_loader import load_config
from modules.site_manager import SiteManager
from api.services import calculator_quick_action_service
from api.services import pipeline_run_service


class IntegratedRunSiteNotFound(Exception):
    """요청한 site_id에 해당하는 site가 없음."""


def _platforms_of(site: dict) -> list:
    # dashboard.py _resolve_run_site(): json.loads(site["platforms"] or "[]"), 실패 시 []
    try:
        return _json.loads(site.get("platforms") or "[]")
    except Exception:
        return []


def _resolve_platforms(cfg: dict) -> list:
    """site_id 없는 요청: dashboard.py 기본 Site(전체 목록의 첫 번째, 상태 무관)."""
    try:
        sites = SiteManager(cfg).get_all_sites()
    except Exception:
        sites = []
    if not sites:
        return []
    return _platforms_of(sites[0])


def _resolve_site_platforms(cfg: dict, site_id: str) -> list:
    """site_id 요청: 서버가 site를 다시 조회한다(클라이언트가 보낸 platforms는 받지 않음)."""
    site = SiteManager(cfg).get_by_id(site_id)
    if not site:
        raise IntegratedRunSiteNotFound(f"존재하지 않는 site_id입니다: {site_id}")
    return _platforms_of(site)


def run_once(order: str = "순차(Calculator→WordPress)", site_id: str = None):
    """dashboard.py qa_run 버튼과 동일한 분기 로직. order는 has_wp and has_calc일
    때만 의미가 있다(기존 st.radio의 3개 값과 동일 문자열) — 그 외에는 무시된다.
    반환: 실행된 branch의 실제 반환값(계산기/블로그 단독 실행 시, dict) 또는
    고정 문자열(순차 실행 시, str — dashboard.py _run_seq()와 동일)."""
    cfg = load_config()
    platforms = _resolve_platforms(cfg) if site_id is None else _resolve_site_platforms(cfg, site_id)
    has_wp = "WordPress" in platforms
    has_calc = "Calculator" in platforms

    if has_wp and has_calc:
        if order == "Calculator만":
            return calculator_quick_action_service.run_once()
        if order == "WordPress만":
            return pipeline_run_service.run_once()
        calculator_quick_action_service.run_once()
        pipeline_run_service.run_once()
        return "계산기→블로그 순차 완료"
    if has_calc:
        return calculator_quick_action_service.run_once()
    return pipeline_run_service.run_once()
