# -*- coding: utf-8 -*-
"""tests/test_step_4h4_generation_job_store.py — STEP 4-H-4: 장시간 AI 생성을
위한 최소 Job 상태 구조(GenerationJobStore) 검증.

실제 generate_app()을 호출하지 않는다 — target은 전부 테스트용 mock 함수다.
실제 AI API 호출 없음. 실제 DB/Registry에도 쓰지 않는다(이 모듈 자체가 순수
in-memory 구조라 애초에 파일 시스템/DB에 접근하지 않는다).
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from api.services.generation_job_store import GenerationJobStore, STATUSES


def test_job_lifecycle_queued_running_succeeded():
    store = GenerationJobStore(max_concurrent=1)
    started = threading.Event()
    release = threading.Event()

    def _target():
        started.set()
        release.wait(timeout=5)
        return {"name": "생성됨", "html": "<html></html>"}

    accepted, msg, job_id = store.submit("테스트계산기", _target)
    assert accepted is True
    assert job_id is not None

    # 아주 잠깐의 창(=running으로 전이되기 전)에는 queued일 수도 있으므로
    # started 이벤트로 "실행이 시작됐다"는 사실 자체를 기다린다.
    assert started.wait(timeout=5)
    job = store.get(job_id)
    assert job.status in ("queued", "running")

    # started가 set된 시점 이후엔 이미 status="running"으로 전이된 뒤여야 한다
    # (store._run이 started.set() 이전에 status를 running으로 바꾸므로).
    time.sleep(0.05)
    job = store.get(job_id)
    assert job.status == "running"
    assert job.started_at is not None
    assert job.finished_at is None

    release.set()
    for _ in range(50):
        if store.get(job_id).status != "running":
            break
        time.sleep(0.05)

    job = store.get(job_id)
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.result == {"name": "생성됨", "html": "<html></html>"}
    assert job.error is None
    store.shutdown()


def test_job_lifecycle_queued_running_failed():
    store = GenerationJobStore(max_concurrent=1)

    def _boom():
        raise RuntimeError("AI 호출 실패(mock)")

    accepted, msg, job_id = store.submit("실패계산기", _boom)
    assert accepted is True

    for _ in range(50):
        if store.get(job_id).status in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    job = store.get(job_id)
    assert job.status == "failed"
    assert job.result is None
    assert "AI 호출 실패" in job.error
    store.shutdown()


def test_get_unknown_job_returns_none():
    store = GenerationJobStore(max_concurrent=1)
    assert store.get("does-not-exist") is None
    store.shutdown()


def test_max_concurrent_one_rejects_second_submission_immediately():
    """§8: 이미 실행 중이면 큐잉하지 않고 즉시 거부한다."""
    store = GenerationJobStore(max_concurrent=1)
    release = threading.Event()
    started = threading.Event()

    def _slow():
        started.set()
        release.wait(timeout=5)
        return {"ok": True}

    ok1, msg1, job1 = store.submit("A", _slow)
    assert ok1 is True
    assert started.wait(timeout=5)

    # A가 아직 실행 중인 동안 B를 제출하면 즉시(대기 없이) 거부되어야 한다.
    ok2, msg2, job2 = store.submit("B", lambda: {"ok": True})
    assert ok2 is False
    assert job2 is None
    assert "실행 중" in msg2

    release.set()
    for _ in range(50):
        if store.get(job1).status != "running":
            break
        time.sleep(0.05)
    assert store.get(job1).status == "succeeded"
    store.shutdown()


def test_after_completion_new_submission_is_accepted():
    store = GenerationJobStore(max_concurrent=1)

    ok1, _, job1 = store.submit("A", lambda: {"ok": True})
    for _ in range(50):
        if store.get(job1).status == "succeeded":
            break
        time.sleep(0.02)
    assert store.get(job1).status == "succeeded"

    ok2, _, job2 = store.submit("B", lambda: {"ok": True})
    assert ok2 is True
    assert job2 is not None
    assert job2 != job1
    store.shutdown()


def test_public_dict_never_leaks_cfg_or_secrets():
    """Job 객체/공개 dict 어디에도 cfg나 API 키가 보관되지 않는지 확인한다.
    target 클로저가 cfg를 들고 있더라도, GenerationJob 자체는 cfg를 저장하지
    않으므로 to_public_dict()에는 절대 나타날 수 없다."""
    store = GenerationJobStore(max_concurrent=1)
    fake_cfg = {"OPENAI_API_KEY": "sk-should-never-leak", "SECRET": "top-secret"}

    def _target():
        # cfg를 클로저로 참조하지만 결과에는 절대 포함시키지 않는다(실제 generate_app()도
        # 이런 형태로 호출될 것을 가정한 목).
        assert fake_cfg["OPENAI_API_KEY"]  # 사용은 하되
        return {"name": "안전한결과"}

    _, _, job_id = store.submit("보안테스트", _target)
    for _ in range(50):
        if store.get(job_id).status == "succeeded":
            break
        time.sleep(0.02)

    public = store.get(job_id).to_public_dict()
    dumped = str(public)
    assert "sk-should-never-leak" not in dumped
    assert "top-secret" not in dumped
    store.shutdown()


def test_all_expected_statuses_are_declared():
    assert set(STATUSES) == {"queued", "running", "succeeded", "failed"}
