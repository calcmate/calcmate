# -*- coding: utf-8 -*-
"""api/services/generation_job_store.py — STEP 4-H-4: App Factory 생성 API를
실제로 구현하기 전에 "장시간 AI 생성 → Job 상태 추적" 구조를 검증하기 위한
최소 구현.

이 STEP에서 결정한 사항 (지시서 §7/§8):

- **선택지 A: ThreadPoolExecutor + in-memory Job store**를 채택했다.
  Celery/Redis/RQ 같은 외부 Queue는 이번 STEP에서 도입 금지(지시서 §7)이며,
  App Factory 생성은 "운영자가 가끔 누르는 저빈도 관리자 작업"이지 공개
  트래픽을 받는 API가 아니므로 외부 큐 인프라를 새로 들이는 비용이 이점보다
  크다고 판단했다.
- **동시 실행 제한 = 1** (max_concurrent, 기본값). AI 호출은 비용/시간이 크므로
  여러 건이 동시에 도는 것을 막는다. 이미 실행 중일 때 새 요청은 **큐잉하지
  않고 즉시 거부**한다 — 저빈도 관리자 도구에서는 "얼마나 기다려야 하는지 알 수
  없는 대기열"보다 "지금은 안 됨, 완료 후 다시 시도"가 훨씬 단순하고 명확하다.
  대기열 UI/취소 기능은 이번 STEP 범위 밖(P2)이다.
- **서버 재시작 시 in-memory Job은 전부 유실**된다. 이는 의도적으로 받아들인
  제약이다 — Job은 generate_app()의 "미확정" 결과만 담고, save_app()으로
  확정 저장되기 전 단계이므로 재시작 후 재생성을 요구해도 데이터 유실이
  아니다(이미 저장된 계산기가 사라지는 것이 아님).
- **result에 민감정보를 담지 않는다**: GenerationJob은 cfg/API 키 등을
  절대 보관하지 않는다 — 생성을 실행하는 target 콜러블은 외부(호출자)가
  cfg를 클로저로 들고 있을 뿐, Job 객체 자체에는 저장하지 않는다.

이 모듈은 generate_app()을 호출하지 않는다 — Job 상태 전이 자체만 다룬다.
실제로 무엇을 실행할지(target)는 호출자가 주입한다. 이번 STEP에서는
FastAPI 라우터에 연결하지 않는다(실제 Generate API 구현은 다음 STEP).
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

STATUSES = ("queued", "running", "succeeded", "failed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class GenerationJob:
    job_id: str
    status: str
    slug_or_name: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict] = None

    def to_public_dict(self) -> dict:
        """API 응답으로 노출할 dict. cfg/API 키 등은 애초에 이 객체에 없으므로
        별도 마스킹 없이 그대로 노출해도 안전하다."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "slug_or_name": self.slug_or_name,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class GenerationJobStore:
    """max_concurrent(기본 1) ThreadPoolExecutor + in-memory dict Job store."""

    def __init__(self, max_concurrent: int = 1):
        self._jobs: dict[str, GenerationJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._running_count = 0
        self._max_concurrent = max_concurrent

    def submit(self, slug_or_name: str, target: Callable[[], dict]) -> tuple[bool, str, Optional[str]]:
        """새 생성 작업을 제출한다.

        이미 max_concurrent만큼 실행 중이면 큐잉하지 않고 즉시 거부한다(§8).
        반환: (accepted, message, job_id). accepted=False면 job_id는 None.
        """
        with self._lock:
            if self._running_count >= self._max_concurrent:
                return False, "이미 생성 작업이 실행 중입니다. 완료 후 다시 시도하세요.", None
            job_id = uuid.uuid4().hex
            job = GenerationJob(
                job_id=job_id, status="queued", slug_or_name=slug_or_name,
                created_at=_now_iso(),
            )
            self._jobs[job_id] = job
            self._running_count += 1

        self._executor.submit(self._run, job_id, target)
        return True, "생성 작업이 시작되었습니다.", job_id

    def _run(self, job_id: str, target: Callable[[], dict]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = _now_iso()
        try:
            result = target()
            with self._lock:
                job.status = "succeeded"
                job.result = result
                job.finished_at = _now_iso()
        except Exception as e:
            with self._lock:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = _now_iso()
        finally:
            with self._lock:
                self._running_count -= 1

    def get(self, job_id: str) -> Optional[GenerationJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def running_count(self) -> int:
        with self._lock:
            return self._running_count

    def replace_result(self, job_id: str, result: dict) -> bool:
        """완료된 Job의 result를 교체한다(Mode A preview 저장 후 생성물 제거용).
        Job이 없거나 succeeded가 아니면 False."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "succeeded":
                return False
            job.result = result
            return True

    def remove(self, job_id: str) -> Optional[GenerationJob]:
        """완료(succeeded/failed)된 Job을 store에서 제거하고 반환한다(Mode A preview
        폐기용). queued/running Job은 제거하지 않고 None을 반환한다."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("queued", "running"):
                return None
            return self._jobs.pop(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


# STEP 4-H-5: api/services/worker_manager.py의 get_worker_manager()와 동일한
# 프로세스 내 단일 인스턴스 패턴(중복 생성 방지).
_store: Optional[GenerationJobStore] = None


def get_job_store() -> GenerationJobStore:
    """프로세스 내 단일 GenerationJobStore 인스턴스를 반환한다."""
    global _store
    if _store is None:
        _store = GenerationJobStore(max_concurrent=1)
    return _store
