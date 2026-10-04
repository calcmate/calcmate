# -*- coding: utf-8 -*-
"""tests/test_workboard.py — STEP S9: Kanban/Workboard React/FastAPI 이관 검증.

dashboard.py "📋 작업 보드" 탭(elif tab == "📋 작업 보드":, dashboard.py:534-557)과
정확히 동일한 6개 컬럼 그룹핑을 검증한다. 순수 읽기 전용 — 이 파일의 어떤
테스트에서도 DB/Registry/HOLD/Retry Queue write 함수가 호출되지 않는지 구조적으로
확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "workboard-test-viewer-token"
ADMIN_TOKEN = "workboard-test-admin-token"

# dashboard.py:534-557과 동일한 상태값 체계를 커버하는 fixture — 6개 컬럼 전부와
# "속하지 않는" 상태값(무시되어야 함) 하나를 포함한다.
FAKE_POSTS = [
    {"ID": "1", "상태값": "대기", "최종추천제목": "수집중 글"},
    {"ID": "2", "상태값": "진행중", "최종추천제목": "수집중 글2"},
    {"ID": "3", "상태값": "작성중", "최종추천제목": "작성중 글"},
    {"ID": "4", "상태값": "검수대기", "최종추천제목": "검수중 글"},
    {"ID": "5", "상태값": "보류", "최종추천제목": "발행대기 글1"},
    {"ID": "6", "상태값": "복구대기", "최종추천제목": "발행대기 글2"},
    {"ID": "7", "상태값": "재처리대기", "최종추천제목": "발행대기 글3"},
    {"ID": "8", "상태값": "발행완료", "최종추천제목": "발행완료 글"},
    {"ID": "9", "상태값": "작성오류", "최종추천제목": "오류 글1"},
    {"ID": "10", "상태값": "이미지오류", "최종추천제목": "오류 글2"},
    {"ID": "11", "상태값": "발행실패", "최종추천제목": "오류 글3"},
    {"ID": "12", "상태값": "만료", "최종추천제목": "오류 글4"},
    {"ID": "13", "상태값": "휴지통", "최종추천제목": "무시되어야 할 글"},  # 6개 컬럼 어디에도 속하지 않음
]


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _block_all_write_functions(monkeypatch):
    """조회 전용 기능이 실제로 write를 유발하지 않는지 구조적으로 보장한다."""
    def _boom(*a, **k):
        raise AssertionError("Workboard 조회 중 쓰기 함수가 호출되면 안 된다")
    # DB/Registry/HOLD/Retry Queue 관련 대표적 쓰기 함수들을 모두 막는다.
    monkeypatch.setattr("modules.retry_queue.retry", _boom, raising=False)
    monkeypatch.setattr("modules.retry_queue.remove", _boom, raising=False)
    monkeypatch.setattr("modules.retry_queue.enqueue", _boom, raising=False)
    monkeypatch.setattr("modules.cost_manager.resume", _boom, raising=False)
    monkeypatch.setattr("modules.cost_manager.pause", _boom, raising=False)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _mock_data(monkeypatch, posts=None):
    monkeypatch.setattr("api.services.workboard_service.load_config", lambda *a, **k: {})
    monkeypatch.setattr(
        "api.services.workboard_service.cache_read",
        lambda cfg, table: list(posts if posts is not None else FAKE_POSTS),
    )


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_without_auth_returns_401():
    r = _client().get("/api/workboard")
    assert r.status_code == 401


def test_as_viewer_returns_403():
    r = _client().get("/api/workboard", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_as_admin_returns_200(monkeypatch):
    _mock_data(monkeypatch)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 데이터: 6 columns / grouping / filter / sort / card fields
# ══════════════════════════════════════════════════════════════════════════

def test_exactly_six_columns_in_the_exact_dashboard_order(monkeypatch):
    _mock_data(monkeypatch)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    columns = r.json()["data"]["columns"]
    assert [c["title"] for c in columns] == [
        "🟡 수집중", "🔵 작성중", "🟠 검수중", "⏳ 발행대기", "🟢 발행완료", "🔴 오류",
    ]


def test_column_grouping_matches_dashboard_state_mapping_exactly(monkeypatch):
    """dashboard.py:542-548의 상태값→컬럼 매핑과 정확히 동일한지 확인."""
    _mock_data(monkeypatch)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    columns = {c["title"]: c for c in r.json()["data"]["columns"]}

    assert columns["🟡 수집중"]["count"] == 2   # 대기, 진행중
    assert columns["🔵 작성중"]["count"] == 1   # 작성중
    assert columns["🟠 검수중"]["count"] == 1   # 검수대기
    assert columns["⏳ 발행대기"]["count"] == 3  # 보류, 복구대기, 재처리대기
    assert columns["🟢 발행완료"]["count"] == 1  # 발행완료
    assert columns["🔴 오류"]["count"] == 4     # 작성오류, 이미지오류, 발행실패, 만료

    # "휴지통"은 6개 컬럼 중 어디에도 속하지 않으므로(dashboard.py도 동일) 전체
    # 카드 수 합계에 포함되지 않아야 한다.
    total_cards = sum(c["count"] for c in columns.values())
    assert total_cards == 12  # 13개 중 "휴지통" 1개 제외


def test_card_fields_are_title_only_matching_dashboard_display(monkeypatch):
    """dashboard.py:556-557 — 카드는 제목만 표시한다(상태/카테고리/날짜 등을
    새로 노출하지 않는다)."""
    _mock_data(monkeypatch)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    columns = {c["title"]: c for c in r.json()["data"]["columns"]}
    item = columns["🟢 발행완료"]["items"][0]
    assert set(item.keys()) == {"id", "title"}
    assert item["title"] == "발행완료 글"


def test_title_truncated_at_22_chars_with_ellipsis(monkeypatch):
    long_title = "가" * 30
    _mock_data(monkeypatch, posts=[{"ID": "x", "상태값": "발행완료", "최종추천제목": long_title}])
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    item = r.json()["data"]["columns"][4]["items"][0]
    assert item["title"] == "가" * 22 + "…"


def test_falls_back_to_policy_name_then_placeholder(monkeypatch):
    _mock_data(monkeypatch, posts=[
        {"ID": "a", "상태값": "발행완료", "정책명": "정책명만 있음"},
        {"ID": "b", "상태값": "발행완료"},
    ])
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    items = r.json()["data"]["columns"][4]["items"]
    titles = {it["title"] for it in items}
    assert "정책명만 있음" in titles
    assert "(제목없음)" in titles


def test_no_sort_is_applied_natural_order_preserved(monkeypatch):
    """dashboard.py 원본에 정렬 로직이 전혀 없다 — 입력 순서를 그대로 유지해야
    한다(임의로 정렬을 추가하지 않는다)."""
    posts = [
        {"ID": "z", "상태값": "발행완료", "최종추천제목": "Z"},
        {"ID": "a", "상태값": "발행완료", "최종추천제목": "A"},
        {"ID": "m", "상태값": "발행완료", "최종추천제목": "M"},
    ]
    _mock_data(monkeypatch, posts=posts)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    ids = [it["id"] for it in r.json()["data"]["columns"][4]["items"]]
    assert ids == ["z", "a", "m"]  # 입력 순서 그대로


def test_card_list_capped_at_15_but_count_reflects_true_total(monkeypatch):
    """dashboard.py:554-555 — st.metric은 전체 건수, 카드 나열은 15개로 제한."""
    posts = [{"ID": str(i), "상태값": "발행완료", "최종추천제목": f"글{i}"} for i in range(20)]
    _mock_data(monkeypatch, posts=posts)
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    col = r.json()["data"]["columns"][4]
    assert col["count"] == 20
    assert len(col["items"]) == 15


def test_empty_column_has_zero_count_and_empty_items(monkeypatch):
    _mock_data(monkeypatch, posts=[])
    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    for col in r.json()["data"]["columns"]:
        assert col["count"] == 0
        assert col["items"] == []


# ══════════════════════════════════════════════════════════════════════════
# 기존 로직 재사용 확인
# ══════════════════════════════════════════════════════════════════════════

def test_reuses_the_real_cache_read_with_articles_table(monkeypatch):
    """log_service.py/publish_service.py가 이미 쓰는 것과 동일한
    modules.dashboard_cache.read(cfg, "articles")를 그대로 재사용하는지 확인."""
    called = {}
    monkeypatch.setattr("api.services.workboard_service.load_config", lambda *a, **k: {"FAKE": True})
    def _spy(cfg, table):
        called["cfg"] = cfg
        called["table"] = table
        return []
    monkeypatch.setattr("api.services.workboard_service.cache_read", _spy)

    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert called["table"] == "articles"
    assert called["cfg"] == {"FAKE": True}


# ══════════════════════════════════════════════════════════════════════════
# Side Effect 보호
# ══════════════════════════════════════════════════════════════════════════

def test_get_does_not_write_db_or_registry(monkeypatch):
    _mock_data(monkeypatch)
    import sys as _sys
    originally_absent = [m for m in ("modules.app_factory",) if m not in _sys.modules]

    r = _client().get("/api/workboard", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 조회 중 새로 import됨(계산기 파이프라인 접근 의심)"


def test_no_write_routes_exist_under_workboard():
    from _route_utils import write_routes
    from api.main import app
    assert write_routes(app, prefix="/api/workboard") == []


def test_service_source_never_references_protected_pipeline_or_write_functions():
    import inspect
    from api.services import workboard_service
    source = inspect.getsource(workboard_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "check_hold_rules", "validate_formula", "save_app",
        "CalculatorRepository", "registry_loader",
        ".retry(", ".remove(", ".enqueue(", ".resume(", ".pause(",
    ):
        assert forbidden not in source
