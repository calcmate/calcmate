# -*- coding: utf-8 -*-
"""
tests/test_oneoff_real_wp_draft_harness.py
CALCMATE-ONEOFF-SCHEDULE-REALTEST-HARNESS-01

execute_due_oneoff()의 resolve_fn 의존성 주입 seam을 이용해 "실제 WordPress
Draft 1건" 테스트를 준비하는 harness. 이 파일을 pytest로 실행해도 실제
WordPress에는 어떤 요청도 나가지 않는다 — 실제 POST를 수행하는 유일한 경로는
run_real_wp_draft_test()뿐이며, 이 함수는:
  1) 이름이 "test_"로 시작하지 않아 pytest가 자동 수집/실행하지 않는다.
  2) 모듈 상수 RUN_REAL_WP_TEST(기본 False)와 인자 confirm(기본 False)이
     "둘 다" True여야만 실제로 진행한다(이중 안전장치).

이 harness는 다음을 절대 사용하지 않는다(CALCMATE-ONEOFF-SCHEDULE-REALTEST-
DESIGN-01에서 확정한 설계):
  - main.resolve_blog_oneoff_publish_fn() / modules.blog_scheduler_adapter.
    run_blog_once_wp() — Golden10[0](severance-pay)이 항상 duplicate-skip되는
    문제를 완전히 회피하기 위해 이 경로를 타지 않는다.
  - content.blog.GOLDEN_10, calculators DB, AI 콘텐츠 생성 — 전혀 조회/호출하지
    않는다.
  - config/config.yaml, config/secrets.yaml — 읽기만 하며 절대 수정하지 않는다.

이 harness가 실제로 사용하는 production 코드는 오직:
  - modules.scheduler.add_oneoff_reservation / get_due_oneoff /
    execute_due_oneoff (기존 one-off 구조, 무수정)
  - modules.publisher.publish (기존 발행 함수, 무수정)
뿐이다.
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.scheduler as sch

KST = ZoneInfo("Asia/Seoul")


# ══════════════════════════════════════════════════════════════════
# 실행 차단 장치 — 기본값은 반드시 False.
# 실제 WP Draft 테스트는 이 값을 True로 바꾸고 run_real_wp_draft_test(confirm=True)
# 를 별도의 명시적 지시(다음 STEP) 없이는 절대 실행하지 않는다.
# ══════════════════════════════════════════════════════════════════
RUN_REAL_WP_TEST = False


# ── 고유 테스트 식별자 ────────────────────────────────────────────

def build_test_identifier() -> dict:
    """Golden10/기존 calculator slug와 절대 충돌하지 않는 고유 테스트 식별자를
    생성한다. timestamp+UUID 기반이라 재실행해도 새 값이 나온다."""
    ts = datetime.now(KST).strftime("%Y%m%dT%H%M%S")
    token = uuid.uuid4().hex[:8]
    return {
        "title": f"[ONEOFF-TEST-DRAFT] {ts}",
        "slug": f"oneoff-test-draft-{ts}-{token}",
        "body": (
            "<p>이 글은 CalcMate 1회성(one-off) 예약 스케줄러의 WordPress Draft "
            "발행 경로를 검증하기 위한 테스트 글입니다. Golden10/실제 계산기 "
            "콘텐츠와 무관하며, 확인 후 삭제 대상입니다.</p>"
        ),
    }


# ── credential/URL 처리 — 파일 수정 없이 메모리에서만 override ─────

def build_test_cfg(real_cfg: dict) -> dict:
    """실제 cfg(load_config() 결과)를 복사해 WordPress 접속 정보만 메모리상으로
    production 값으로 override한다. config/secrets.yaml 파일은 전혀 쓰지 않는다.

    - WORDPRESS_URL(flat, obsolete "salarymate.test")을 nested wordpress.url
      (운영, "genon.app")로 교체.
    - WORDPRESS_APP_PASSWORD(flat, 로컬/테스트용)를 빈 문자열로 만들어
      publisher._app_password()가 nested wordpress.app_password(운영)로
      자동 fallback하도록 만든다(publisher.py 자체는 무수정).
    - WORDPRESS_USERNAME은 flat 값이 이미 production과 동일(geminia)하므로
      그대로 둔다.
    """
    wp = real_cfg.get("wordpress") or {}
    prod_url = wp.get("url", "")
    if not prod_url:
        raise RuntimeError(
            "secrets.yaml의 wordpress.url이 비어있습니다 — production URL을 확인하세요."
        )
    cfg = dict(real_cfg)
    cfg["WORDPRESS_URL"] = prod_url
    cfg["WORDPRESS_APP_PASSWORD"] = ""
    return cfg


def describe_credential_sources(real_cfg: dict) -> dict:
    """실제 secret 값은 절대 반환하지 않는다 — PRESENT/ABSENT와 hostname만."""
    wp = real_cfg.get("wordpress") or {}
    prod_url = wp.get("url", "")
    return {
        "url_source": "config/secrets.yaml:wordpress.url",
        "url_hostname": urlparse(prod_url).hostname if prod_url else None,
        "username_source": "config/config.yaml:WORDPRESS_USERNAME (flat, production과 동일값)",
        "app_password_source": "config/secrets.yaml:wordpress.app_password (nested, production)",
        "app_password_present": bool(wp.get("app_password")),
        "flat_app_password_present_but_ignored": bool(real_cfg.get("WORDPRESS_APP_PASSWORD")),
    }


# ── test-only resolve_fn — run_blog_once_wp/Golden10 미사용, publisher.publish만 사용 ──

def make_test_resolve_fn(test_cfg: dict, identifier: dict):
    """execute_due_oneoff(cfg, entry, resolve_fn)에 주입할 test-only resolve_fn.
    main.resolve_blog_oneoff_publish_fn()도, run_blog_once_wp()도 호출하지
    않는다 — modules.publisher.publish()만 직접 사용한다. mode="publish"는
    이 harness에서 명시적으로 거부한다(draft 전용 harness)."""

    def _resolve(mode: str):
        if mode not in ("draft", "publish"):
            raise ValueError(f"허용되지 않는 mode: {mode!r}")
        if mode != "draft":
            raise RuntimeError("이 harness는 status='draft' 전용입니다(publish 금지).")

        def _run_once(cfg, max_count=1):
            import modules.publisher as publisher
            seo = {
                "seo_title": identifier["title"],
                "seo_description": "1회성 예약 스케줄러 draft 발행 경로 검증용. 삭제 대상.",
                "meta_description": "1회성 예약 스케줄러 draft 발행 경로 검증용. 삭제 대상.",
                "slug": identifier["slug"],
            }
            result = publisher.publish(
                f"oneoff_test_{identifier['slug']}", seo, identifier["body"], {},
                test_cfg, status="draft", comment_status="closed",
            )
            produced = 1 if result.get("status") in ("published", "draft") else 0
            return {
                "produced": produced,
                "wp_post_id": result.get("wp_post_id", ""),
                "wp_permalink": result.get("wp_permalink", ""),
                "wp_status": result.get("status", ""),
                "slug": identifier["slug"],
                "title": identifier["title"],
            }

        return _run_once

    return _resolve


# ── entry 구조 미리 준비(파일에 저장하지 않음) ──────────────────────

def build_dry_entry(scheduled_at: datetime = None) -> dict:
    """add_oneoff_reservation()을 호출하지 않고, 실제 entry와 동일한 shape만
    미리 구성해 구조를 검증한다(파일 write 없음)."""
    scheduled_at = scheduled_at or (datetime.now(KST) - timedelta(minutes=1))
    return {
        "id": f"oneoff_{datetime.now(KST).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "scheduled_at": scheduled_at.isoformat(),
        "mode": "draft",
        "status": "pending",
        "created_at": datetime.now(KST).isoformat(),
        "executed_at": None,
        "result": None,
        "duplicate": False,
    }


# ══════════════════════════════════════════════════════════════════
# 실제 실행 함수 — 이중 안전장치(RUN_REAL_WP_TEST and confirm)를 모두
# 만족해야 하며, 이름이 "test_"로 시작하지 않아 pytest가 자동 실행하지 않는다.
# 이번 STEP에서는 이 함수를 어디에서도 호출하지 않는다.
# ══════════════════════════════════════════════════════════════════

def run_real_wp_draft_test(confirm: bool = False) -> dict:
    """실제 WordPress Draft 1건을 생성한다(다음 별도 STEP에서만 사용 예정).

    사용하는 production 함수(전부 무수정): add_oneoff_reservation,
    get_due_oneoff, execute_due_oneoff, publisher.publish.
    실제 실행 시 data/schedule/blog/oneoff_schedule.json에 1건이 기록된다."""
    if not (RUN_REAL_WP_TEST and confirm):
        raise RuntimeError(
            "실행 차단됨 — RUN_REAL_WP_TEST=True와 confirm=True가 모두 필요합니다. "
            "이는 실수로 실제 WordPress에 POST하는 것을 막기 위한 이중 안전장치입니다."
        )

    from modules.config_loader import load_config
    real_cfg = load_config()
    test_cfg = build_test_cfg(real_cfg)
    test_cfg["_root"] = real_cfg.get("_root") or str(ROOT)
    test_cfg["scheduler_line"] = "blog"

    identifier = build_test_identifier()
    resolve_fn = make_test_resolve_fn(test_cfg, identifier)

    print(f"[harness] target hostname: {describe_credential_sources(real_cfg)['url_hostname']}")
    print(f"[harness] test title: {identifier['title']}")
    print(f"[harness] test slug: {identifier['slug']}")

    when = datetime.now(KST) - timedelta(minutes=1)  # 즉시 due로 만들어 대기 없이 처리
    entry = sch.add_oneoff_reservation(test_cfg, when, "draft")
    due = [e for e in sch.get_due_oneoff(test_cfg) if e["id"] == entry["id"]]
    if not due:
        raise RuntimeError("생성한 예약이 due 목록에서 발견되지 않았습니다 — 중단.")

    status = sch.execute_due_oneoff(test_cfg, due[0], resolve_fn)
    final = [e for e in sch.load_oneoff(test_cfg) if e["id"] == entry["id"]][0]
    print(f"[harness] execute_due_oneoff result: {status}")
    print(f"[harness] wp_post_id: {(final.get('result') or {}).get('wp_post_id')}")
    print(f"[harness] rollback: publisher.delete_post(cfg, wp_post_id, force=False)")
    return final


# ══════════════════════════════════════════════════════════════════
# pytest 수집 대상 — 전부 구조/가드 검증만, 실제 네트워크 호출 없음.
# ══════════════════════════════════════════════════════════════════

def test_safety_guard_default_is_false():
    assert RUN_REAL_WP_TEST is False


def test_run_real_wp_draft_test_blocked_without_confirm():
    with pytest.raises(RuntimeError):
        run_real_wp_draft_test()  # confirm 기본값 False


def test_run_real_wp_draft_test_blocked_even_with_confirm_true():
    """모듈 상수 RUN_REAL_WP_TEST가 False인 한, confirm=True를 넘겨도 차단돼야
    한다(이중 안전장치 중 하나만 만족해서는 실행되지 않음)."""
    with pytest.raises(RuntimeError):
        run_real_wp_draft_test(confirm=True)


def test_build_test_identifier_unique_and_not_golden10():
    from content.blog import GOLDEN_10
    identifier = build_test_identifier()
    golden_slugs = {gc.slug for gc in GOLDEN_10}
    assert identifier["slug"] not in golden_slugs
    assert identifier["slug"].startswith("oneoff-test-draft-")
    assert identifier["title"].startswith("[ONEOFF-TEST-DRAFT]")

    identifier2 = build_test_identifier()
    assert identifier["slug"] != identifier2["slug"], "재호출 시 slug가 충돌하지 않아야 함"


def test_build_test_identifier_not_a_known_calculator_slug():
    """DB 조회 가능하면 14개 계산기 slug와도 겹치지 않는지 추가 확인(READ-ONLY,
    DB write 없음). DB 접근이 안 되는 환경이면 건너뛴다."""
    try:
        from modules.config_loader import load_config
        from adapters.db.factory import get_db_adapter
        cfg = load_config()
        calc_rows = get_db_adapter(cfg).get_all("calculators")
        calc_slugs = {c.get("slug") for c in calc_rows}
    except Exception:
        pytest.skip("DB 접근 불가 — 이 환경에서는 건너뜀")
        return
    identifier = build_test_identifier()
    assert identifier["slug"] not in calc_slugs


def test_build_test_cfg_overrides_url_and_blanks_flat_password_without_touching_files():
    fake_real_cfg = {
        "WORDPRESS_URL": "http://salarymate.test",
        "WORDPRESS_USERNAME": "geminia",
        "WORDPRESS_APP_PASSWORD": "local-test-only-value",
        "wordpress": {"url": "https://blog.genon.app", "username": "geminia",
                      "app_password": "prod-secret-value"},
    }
    test_cfg = build_test_cfg(fake_real_cfg)
    assert test_cfg["WORDPRESS_URL"] == "https://blog.genon.app"
    assert test_cfg["WORDPRESS_APP_PASSWORD"] == ""
    # 원본 dict는 변경되지 않아야 한다(복사본만 override).
    assert fake_real_cfg["WORDPRESS_URL"] == "http://salarymate.test"
    assert fake_real_cfg["WORDPRESS_APP_PASSWORD"] == "local-test-only-value"


def test_build_test_cfg_requires_nested_wordpress_url():
    with pytest.raises(RuntimeError):
        build_test_cfg({"WORDPRESS_URL": "http://salarymate.test", "wordpress": {}})


def test_describe_credential_sources_never_leaks_secret_value():
    fake_real_cfg = {
        "WORDPRESS_APP_PASSWORD": "should-never-appear",
        "wordpress": {"url": "https://blog.genon.app",
                      "app_password": "also-should-never-appear"},
    }
    desc = describe_credential_sources(fake_real_cfg)
    assert desc["url_hostname"] == "blog.genon.app"
    assert isinstance(desc["app_password_present"], bool)
    assert isinstance(desc["flat_app_password_present_but_ignored"], bool)
    serialized = repr(desc)
    assert "should-never-appear" not in serialized
    assert "also-should-never-appear" not in serialized


def test_make_test_resolve_fn_rejects_publish_mode():
    identifier = build_test_identifier()
    resolve_fn = make_test_resolve_fn({}, identifier)
    with pytest.raises(RuntimeError):
        resolve_fn("publish")


def test_make_test_resolve_fn_rejects_invalid_mode():
    identifier = build_test_identifier()
    resolve_fn = make_test_resolve_fn({}, identifier)
    with pytest.raises(ValueError):
        resolve_fn("not_a_mode")


def test_make_test_resolve_fn_draft_calls_publisher_publish_directly_mocked():
    """resolve_fn("draft")가 반환한 run_once_fn을 실제로 호출했을 때
    modules.publisher.publish가 status="draft"로 정확히 호출되는지 확인한다
    (mock — 실제 네트워크 호출 없음). run_blog_once_wp는 전혀 사용되지 않는다."""
    identifier = build_test_identifier()
    test_cfg = {"marker": "test_cfg"}
    resolve_fn = make_test_resolve_fn(test_cfg, identifier)
    run_once_fn = resolve_fn("draft")

    with mock.patch("modules.publisher.publish") as mock_publish:
        mock_publish.return_value = {
            "wp_post_id": 99999,
            "wp_permalink": "https://blog.genon.app/oneoff-test/",
            "status": "draft",
        }
        stats = run_once_fn({}, max_count=1)

    mock_publish.assert_called_once()
    args, kwargs = mock_publish.call_args
    assert kwargs.get("status") == "draft"
    assert args[4] is test_cfg  # cfg 인자가 test_cfg 그대로 전달됐는지
    seo_arg = args[1]
    assert seo_arg["slug"] == identifier["slug"]
    assert seo_arg["seo_title"] == identifier["title"]
    assert stats["produced"] == 1
    assert stats["wp_post_id"] == 99999


def test_build_dry_entry_matches_reservation_shape():
    entry = build_dry_entry()
    required_keys = {"id", "scheduled_at", "mode", "status", "created_at",
                      "executed_at", "result", "duplicate"}
    assert required_keys.issubset(entry.keys())
    assert entry["mode"] == "draft"
    assert entry["status"] == "pending"
    assert entry["executed_at"] is None
    assert entry["result"] is None
    assert entry["duplicate"] is False


def test_full_chain_with_mocked_publisher_no_real_network(tmp_path):
    """harness의 resolve_fn을 실제 production execute_due_oneoff()에 주입해
    전체 흐름(add_oneoff_reservation → execute_due_oneoff → resolve_fn →
    publisher.publish → mark_oneoff_result)이 정상 동작하는지 확인한다.
    modules.publisher.publish를 mock.patch하므로 실제 네트워크 호출은
    발생하지 않는다. tmp_path로 완전히 격리되어 실제 프로젝트 파일도 건드리지
    않는다."""
    cfg = {"_root": str(tmp_path), "scheduler_line": "blog"}
    identifier = build_test_identifier()
    resolve_fn = make_test_resolve_fn(cfg, identifier)

    entry = sch.add_oneoff_reservation(cfg, datetime.now(KST) - timedelta(minutes=1), "draft")

    with mock.patch("modules.publisher.publish") as mock_publish:
        mock_publish.return_value = {
            "wp_post_id": 12345,
            "wp_permalink": "https://blog.genon.app/oneoff-test-draft-xxx/",
            "status": "draft",
        }
        result_status = sch.execute_due_oneoff(cfg, entry, resolve_fn)

    assert result_status == "completed"
    mock_publish.assert_called_once()
    _, kwargs = mock_publish.call_args
    assert kwargs.get("status") == "draft"

    saved = sch.load_oneoff(cfg)
    assert len(saved) == 1
    assert saved[0]["status"] == "completed"
    assert saved[0]["result"]["wp_post_id"] == 12345
    assert saved[0]["result"]["slug"] == identifier["slug"]

    # run_blog_once_wp/GOLDEN_10 경로가 전혀 쓰이지 않았는지 간접 확인 —
    # mock 대상이 modules.publisher.publish 하나뿐이었는데도 완결됐다는 것 자체가
    # run_blog_once_wp를 거치지 않았다는 증거(그 경로였다면 GOLDEN_10/DB 조회가
    # 필요해 이 최소 cfg({"_root":..., "scheduler_line":...})로는 실패했을 것).
