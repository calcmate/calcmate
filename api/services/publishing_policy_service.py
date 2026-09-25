# -*- coding: utf-8 -*-
"""api/services/publishing_policy_service.py — Publishing Policy 조회/미리보기
서비스 (CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01).

modules.publishing_policy(정책 검증/랜덤 시각 생성)와 modules.scheduler(cfg 로딩)를
그대로 호출하는 thin wrapper다 — 랜덤 생성 알고리즘이나 검증 규칙을 이 파일에
재구현하지 않는다. 실제 예약 생성(modules.publishing_planner.run_planner_once())은
이 STEP의 범위가 아니며(감사 결론대로), 이 서비스는 정책 조회/저장/미리보기까지만
담당한다.

config.yaml 조회/저장 자체(ALLOWED_SECTIONS 화이트리스트, 원자적 쓰기)는
api.services.config_service.ConfigService에 위임한다 — 이 파일에서 config.yaml을
직접 열거나 쓰지 않는다.
"""
from datetime import date, timedelta

from modules import publishing_policy as PP
from api.services.config_service import ConfigService

PREVIEW_DAYS = 7


def get_policy() -> dict:
    """PUBLISHING_POLICY 섹션을 반환한다. config.yaml에 이 키가 아직 없으면(현재
    실제 운영 상태) ConfigService.get_section()이 빈 dict({})를 돌려주는데,
    이는 modules.publishing_policy.load_policy()의 기존 계약(키가 없으면
    PP.DEFAULT_POLICY로 fallback, dashboard.py도 동일하게 동작)과 다르다 —
    여기서 그 기존 fallback 계약을 그대로 재현한다(새 기본값을 만들지 않고
    PP.DEFAULT_POLICY를 그대로 재사용)."""
    section = ConfigService().get_section("PUBLISHING_POLICY")
    return section if section else PP.DEFAULT_POLICY


def patch_policy(policy: dict) -> dict:
    """PUBLISHING_POLICY 저장. 검증은 ConfigService.patch_publishing_policy()가
    modules.publishing_policy.validate_policy()로 수행한다(이 함수는 그 결과를
    그대로 반환할 뿐 검증을 다시 하지 않는다)."""
    return ConfigService().patch_publishing_policy(policy)


def get_auto_publishing() -> dict:
    return ConfigService().get_section("AUTO_PUBLISHING")


def patch_auto_publishing(enabled: bool) -> dict:
    return ConfigService().patch_auto_publishing(enabled)


def preview(policy: dict, days: int = PREVIEW_DAYS) -> dict:
    """향후 days일간(기본 7일) 정책 기준 예상 발행 시각을 계산만 한다
    (modules.publishing_policy.candidate_times_for_date() 그대로 호출).

    DB/WP/AI/Topic Pool을 전혀 호출하지 않으며 실제 예약(add_oneoff_reservation)도
    생성하지 않는다 — 순수 계산 결과만 반환한다(dashboard.py의 기존 Preview
    섹션과 동일한 read-only 계약).

    policy가 유효하지 않으면(fail-closed) 예외를 그대로 전달한다 — 호출자
    (router)가 이를 validation error로 변환해 응답한다."""
    errors = PP.validate_policy(policy)
    if errors:
        raise ValueError(f"PUBLISHING_POLICY 검증 실패: {errors}")

    today = date.today()
    days_out = []
    for offset in range(days):
        d = today + timedelta(days=offset)
        weekday_key = PP.weekday_key_for_date(d)
        entry = policy["weekdays"][weekday_key]
        # candidate_times_for_date()는 entry["time_ranges"]와 정확히 같은 순서로
        # range별 랜덤 시각 1개씩을 반환한다(modules/publishing_policy.py 계약) —
        # i번째 결과가 i번째 range에 대응하므로 정렬하지 않고 그 순서를 그대로
        # start/end와 짝지어야 한다(정렬하면 range-slot 대응이 깨진다).
        times = PP.candidate_times_for_date(policy, d)
        days_out.append({
            "date": d.isoformat(),
            "weekday": weekday_key,
            "slots": [
                {
                    "scheduled_at": f"{d.isoformat()}T{t}:00+09:00",
                    "start": entry["time_ranges"][i]["start"],
                    "end": entry["time_ranges"][i]["end"],
                }
                for i, t in enumerate(times)
            ],
        })

    return {"timezone": PP.ALLOWED_TIMEZONE, "days": days_out}
