# -*- coding: utf-8 -*-
"""tests/test_step_4h4_app_factory_concurrency.py — STEP 4-H-4: App Factory
동시성 위험 실제 재현 + save_app() 직렬화 락 검증.

이 파일은 두 부분으로 구성된다.

1. **락 없이 재현**: modules.app_factory._save_app_locked()(락으로 감싸이기
   전의 실제 저장 로직)를 두 스레드에서 동시에 호출해, "중복 확인(read) 통과
   → 저장(write)" 사이의 TOCTOU가 실제로 (a) DB에 동일 slug 중복 행을 만들고
   (b) v3 Registry(_af.yaml, 전체 파일을 매번 다시 쓰는 구조)에서 한쪽 결과가
   조용히 유실되는지 결정론적으로 증명한다(threading.Barrier로 두 스레드의
   "쓰기 시점 재확인" 읽기를 강제로 동시에 만든다).

2. **락으로 검증**: 공개 함수 save_app()(STEP 4-H-4에서 추가한
   _SAVE_APP_LOCK으로 전체가 직렬화됨)을 두 스레드에서 동시에 호출해, 위
   문제가 더 이상 발생하지 않는지(동일 slug는 정확히 하나만 성공, 서로 다른
   slug는 둘 다 안전하게 성공) 확인한다.

실제 AI API 호출 없음(_chat monkeypatch), 실제 DB/Registry에는 쓰지 않음
(fake repo + tmp_path 격리 Registry만 사용).
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

import modules.app_factory as af
import modules.registry_loader as registry_loader
from modules.app_factory import save_app, _save_app_locked
from tests.test_ca1b4_p1b_scope_exclusions_prompt import _capture_chat

CFG = {"DB_ADAPTER": "memory"}


class _FakeDb:
    def __init__(self):
        self.deleted = []

    def delete(self, table, id_):
        self.deleted.append((table, id_))


def _make_fake_calc_repo(shared_rows):
    """thread-safe에 가깝게: dict 연산 자체는 GIL 아래 원자적이라 별도 락 없이도
    이 테스트 목적(실제 DB 유사 대역)에는 충분하다."""

    class _Repo:
        def __init__(self, db):
            self.db = db

        def get_all(self):
            return [dict(r) for r in shared_rows.values()]

        def save(self, data):
            _id = f"calc_{uuid_counter()}"
            row = dict(data)
            row["id"] = _id
            shared_rows[_id] = row
            return _id

        def delete(self, id_):
            shared_rows.pop(id_, None)

    return _Repo


_counter_lock = threading.Lock()
_counter = [0]


def uuid_counter():
    with _counter_lock:
        _counter[0] += 1
        return _counter[0]


class _FakeTplRepo:
    def __init__(self, db):
        self.db = db

    def save(self, data):
        return f"tpl_{uuid_counter()}"


def _gen_app(name):
    """generate_app()을 실제로 호출하되 _chat만 mock — AI 호출 없음."""
    from modules.app_factory import generate_app
    return generate_app(CFG, name, category="세금/세법", desc="설명", tier=2)


def _setup(monkeypatch, tmp_path, chat_mock=True):
    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    monkeypatch.setattr(registry_loader, "_REG_DIR", reg_dir)
    monkeypatch.setattr(af, "_REG_DIR", reg_dir)
    # add_auto_entry()가 쓰는 registry_auto.yaml 경로(_AUTO_PATH)는 _REG_DIR과
    # 완전히 별개의 모듈 상수라 위 두 줄만으로는 격리되지 않는다 — 반드시 함께
    # 격리해야 한다(격리 누락 시 실제 운영 docs/registry_auto.yaml에 테스트
    # slug가 그대로 기록됨 — 이 STEP에서 실제로 재현되어 즉시 수정함).
    monkeypatch.setattr(registry_loader, "_AUTO_PATH", tmp_path / "registry_auto.yaml")
    registry_loader.invalidate()

    shared_rows = {}
    fake_db = _FakeDb()
    monkeypatch.setattr(af, "get_db_adapter", lambda cfg: fake_db)
    # IRP-23: app_templates 저장은 get_template_storage_adapter(cfg)를 거치므로
    # (SQLite-원본/Sheets-백업 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_template_storage_adapter", lambda cfg: fake_db)
    # STEP93: calculators 저장은 get_calculator_storage_adapter(cfg)를 거치므로
    # (SQLite MAIN/Sheets BACKUP 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_calculator_storage_adapter", lambda cfg: fake_db)
    monkeypatch.setattr(af, "CalculatorRepository", _make_fake_calc_repo(shared_rows))
    monkeypatch.setattr(af, "TemplateRepository", _FakeTplRepo)
    monkeypatch.setattr(af, "_write_calculator_index", lambda *a, **k: None)
    monkeypatch.setattr(af, "_save_contract_instance", lambda *a, **k: None)
    monkeypatch.setattr(af, "save_af_checklist", lambda *a, **k: None)
    if chat_mock:
        monkeypatch.setattr(af, "_chat", _capture_chat([]))
    return reg_dir, shared_rows, fake_db


def _barrier_wrapped_yaml_dump(n: int = 2, timeout: float = 5):
    """_write_registry_v3()는 "읽기(load_registry_v3) → dict 병합 → yaml.dump →
    write_text"를 한 번의 함수 호출 안에서 순서대로 수행한다. yaml.dump() 직전에
    barrier로 두 스레드를 동기화하면, "둘 다 상대의 아직 반영되지 않은 상태를
    읽어 각자 dict를 만든 뒤, 그 결과를 파일에 쓴다"는 진짜 lost-update 상황을
    시스템 부하/스레드 스케줄링과 무관하게 결정론적으로 재현할 수 있다(barrier
    이후에야 write_text가 실행되므로, 두 스레드의 읽기는 반드시 상대의 쓰기보다
    먼저 끝나 있다 — 초기 구현은 load_registry_v3 호출 시점에서만 동기화했는데,
    그 경우 이후 실제 파일 쓰기 완료 순서는 스레드 스케줄러에 맡겨져 전체 스위트
    실행처럼 부하가 다르면 결과가 흔들렸다. 이 STEP에서 해당 문제를 발견해
    "쓰기 직전"으로 동기화 지점을 옮겨 수정했다)."""
    barrier = threading.Barrier(n, timeout=timeout)
    lock = threading.Lock()
    arrived = set()
    orig_dump = yaml.dump

    def wrapper(data, *a, **k):
        tid = threading.get_ident()
        with lock:
            first_time = tid not in arrived
            arrived.add(tid)
        if first_time:
            barrier.wait()
        return orig_dump(data, *a, **k)

    return wrapper


# ══════════════════════════════════════════════════════════════════════════
# 1) 락 없이 재현 — _save_app_locked()를 직접 두 스레드에서 동시 호출
# ══════════════════════════════════════════════════════════════════════════

def test_race_without_lock_causes_duplicate_db_rows_and_lost_registry_entry(tmp_path, monkeypatch):
    reg_dir, shared_rows, fake_db = _setup(monkeypatch, tmp_path)
    # Step A(registry_auto.yaml 스테이징)는 이 테스트의 관심사가 아니므로 no-op 처리해,
    # yaml.dump barrier가 오직 Step B(_write_registry_v3)의 쓰기 직전에서만 동기화되게 한다.
    monkeypatch.setattr(registry_loader, "add_auto_entry", lambda *a, **k: None)
    monkeypatch.setattr(yaml, "dump", _barrier_wrapped_yaml_dump())

    appA = _gen_app("동시생성 계산기A")
    appB = _gen_app("동시생성 계산기B")

    results = {}

    def _run(key, app):
        results[key] = _save_app_locked(CFG, app, slug="race-calc")

    tA = threading.Thread(target=_run, args=("A", appA))
    tB = threading.Thread(target=_run, args=("B", appB))
    tA.start()
    tB.start()
    tA.join(timeout=10)
    tB.join(timeout=10)

    ok_a, msg_a = results["A"]
    ok_b, msg_b = results["B"]

    # 핵심 재현: 락이 없으면 "중복 확인 → PASS"가 둘 다 일어난 뒤 저장하므로
    # 서버 입장에선 두 요청 다 성공한 것처럼 보인다 — 위험 신호가 없다.
    assert ok_a is True and ok_b is True, (
        f"두 요청 모두 성공 처리되는 것 자체가 문제(TOCTOU): a={ok_a}/{msg_a}, b={ok_b}/{msg_b}"
    )

    db_rows_for_slug = [r for r in shared_rows.values() if r.get("slug") == "race-calc"]
    assert len(db_rows_for_slug) == 2, "DB에 동일 slug 중복 행이 2개 생겨야 재현 성공"

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    assert len(yaml_files) == 1
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    # 두 스레드 다 같은 slug 키에 썼으므로 Registry에는 정확히 1개만 남는다
    # (나중에 쓴 쪽이 이긴다) — 즉 둘 중 하나의 DB 행은 이제 Registry에서 보이지
    # 않는 "고아"가 된다. save_app()은 "성공"이라고 답했는데도 그렇다.
    assert list(data.keys()).count("race-calc") == 1


def test_race_without_lock_different_slugs_same_category_can_clobber_each_other(tmp_path, monkeypatch):
    """더 놀라운 사실: slug가 겹치지 않아도, 같은 category(=같은 _af.yaml 파일)에
    동시에 등록하면 파일 전체 재작성 방식 때문에 한쪽 엔트리가 통째로 사라질 수
    있다(진짜 slug 충돌이 없는데도 데이터 유실)."""
    reg_dir, shared_rows, fake_db = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(registry_loader, "add_auto_entry", lambda *a, **k: None)
    monkeypatch.setattr(yaml, "dump", _barrier_wrapped_yaml_dump())

    appA = _gen_app("서로다른슬러그A")
    appB = _gen_app("서로다른슬러그B")

    results = {}

    def _run(key, app, slug):
        results[key] = _save_app_locked(CFG, app, slug=slug)

    tA = threading.Thread(target=_run, args=("A", appA, "race-diff-a"))
    tB = threading.Thread(target=_run, args=("B", appB, "race-diff-b"))
    tA.start()
    tB.start()
    tA.join(timeout=10)
    tB.join(timeout=10)

    assert results["A"][0] is True and results["B"][0] is True

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    present = {"race-diff-a", "race-diff-b"} & set(data.keys())
    # 이 STEP이 실제로 보여주는 위험: 두 slug가 전혀 겹치지 않는데도 Registry
    # 전체 파일 재작성 방식 때문에 하나가 사라질 수 있다(정확히 1개만 남음).
    assert len(present) == 1, (
        f"서로 다른 slug인데도 한쪽이 Registry에서 사라져야 재현 성공: 실제 present={present}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 2) 락으로 검증 — 공개 save_app()을 두 스레드에서 동시 호출
# ══════════════════════════════════════════════════════════════════════════

def test_lock_serializes_concurrent_same_slug_save_app_only_one_succeeds(tmp_path, monkeypatch):
    """Test A(§4): 동일 slug로 동시에 save_app()을 호출하면 _SAVE_APP_LOCK이
    직렬화해 정확히 하나만 성공하고, 나머지는 명확한 중복 오류를 받아야 한다."""
    reg_dir, shared_rows, fake_db = _setup(monkeypatch, tmp_path)
    # 락으로 전체가 직렬화되므로 barrier를 걸지 않는다 — 걸면 두 번째 스레드가
    # 락을 아예 획득하지 못해 barrier에서 영원히 대기(데드락)하게 된다.

    appA = _gen_app("락검증A")
    appB = _gen_app("락검증B")
    results = {}

    def _run(key, app):
        results[key] = save_app(CFG, app, slug="lock-race-calc")

    tA = threading.Thread(target=_run, args=("A", appA))
    tB = threading.Thread(target=_run, args=("B", appB))
    tA.start()
    tB.start()
    tA.join(timeout=10)
    tB.join(timeout=10)

    ok_a, msg_a = results["A"]
    ok_b, msg_b = results["B"]
    successes = [ok for ok in (ok_a, ok_b) if ok]
    failures_msgs = [m for ok, m in (( ok_a, msg_a), (ok_b, msg_b)) if not ok]

    assert len(successes) == 1, f"정확히 하나만 성공해야 한다: a={ok_a}, b={ok_b}"
    assert len(failures_msgs) == 1
    assert "이미 등록됨" in failures_msgs[0]

    db_rows_for_slug = [r for r in shared_rows.values() if r.get("slug") == "lock-race-calc"]
    assert len(db_rows_for_slug) == 1, "DB에도 정확히 1개 행만 있어야 한다(중복 없음)"

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert list(data.keys()).count("lock-race-calc") == 1


def test_lock_serializes_concurrent_different_slugs_both_succeed_independently(tmp_path, monkeypatch):
    """Test B(§4): 서로 다른 slug는 락으로 직렬화되어도 서로 영향을 주지 않고
    둘 다 정상 등록되어야 한다(순서만 강제될 뿐 데이터 유실은 없어야 한다)."""
    reg_dir, shared_rows, fake_db = _setup(monkeypatch, tmp_path)

    appA = _gen_app("독립슬러그A")
    appB = _gen_app("독립슬러그B")
    results = {}

    def _run(key, app, slug):
        results[key] = save_app(CFG, app, slug=slug)

    tA = threading.Thread(target=_run, args=("A", appA, "indep-a"))
    tB = threading.Thread(target=_run, args=("B", appB, "indep-b"))
    tA.start()
    tB.start()
    tA.join(timeout=10)
    tB.join(timeout=10)

    assert results["A"][0] is True, results["A"]
    assert results["B"][0] is True, results["B"]

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert "indep-a" in data and "indep-b" in data, (
        "서로 다른 slug는 둘 다 유실 없이 Registry에 남아야 한다"
    )

    slugs_in_db = sorted(r.get("slug") for r in shared_rows.values())
    assert slugs_in_db == ["indep-a", "indep-b"]


def test_lock_does_not_break_step4h3_orphan_self_heal_on_retry(tmp_path, monkeypatch):
    """Test C(§4): 첫 저장이 Registry 기록 단계에서 실패해 고아(DB만 존재)가
    생겨도, 락이 추가된 뒤에도 STEP 4-H-3의 자동 정리가 그대로 동작해 동일
    slug로 재시도하면 정상 복구되어야 한다(순차 호출 — 락이 재진입 문제를
    일으키지 않는지도 함께 확인)."""
    reg_dir, shared_rows, fake_db = _setup(monkeypatch, tmp_path)

    call_count = {"n": 0}
    orig_write = af._write_registry_v3

    def _boom_once(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated registry write failure")
        return orig_write(*a, **k)

    monkeypatch.setattr(af, "_write_registry_v3", _boom_once)

    app1 = _gen_app("재시도계산기")
    ok1, msg1 = save_app(CFG, app1, slug="retry-after-fail-calc")
    assert ok1 is True  # save_app()은 registry 실패를 경고로만 처리(기존 동작)
    assert "⚠️" in msg1

    orphan_rows = [r for r in shared_rows.values() if r.get("slug") == "retry-after-fail-calc"]
    assert len(orphan_rows) == 1  # DB에는 저장됐지만 Registry에는 없는 고아 상태

    app2 = _gen_app("재시도계산기 재생성")
    ok2, msg2 = save_app(CFG, app2, slug="retry-after-fail-calc")
    assert ok2 is True, msg2

    rows_after = [r for r in shared_rows.values() if r.get("slug") == "retry-after-fail-calc"]
    assert len(rows_after) == 1, "고아가 정리되고 새로 하나만 남아야 한다(중복 아님)"
    assert rows_after[0]["name"] == "재시도계산기 재생성"

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert "retry-after-fail-calc" in data
