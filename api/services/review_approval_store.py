# -*- coding: utf-8 -*-
"""api/services/review_approval_store.py — STEP S1: Human Review Approval 상태 저장소.

dashboard.py "🧮 계산기 관리" 탭의 "👤 사람 검수" 단계(dashboard.py:1753-1796)가 실제로
어떻게 구현되어 있는지 확인한 결과, 그 승인 상태는 DB/Registry 어디에도 저장되지 않고
`st.session_state[f"cm_reviewed_{cid}"]`(브라우저 세션 메모리)에만 존재했다 — Streamlit
프로세스가 재시작되면 사라지는, 원래부터 "미확정 중간 상태"였다. 여기서는 그 안전 의미를
그대로 유지하되(DB/Registry 스키마 변경 없음, 영구 저장 아님), 다음 두 가지를 서버 측에서
검증 가능하게 만든다.

  1) 승인 여부를 서버가 기억한다(React의 disabled 버튼만으로는 실제 API 우회를 막을 수
     없으므로 — client가 보내는 "approved=true"를 신뢰하지 않는다).
  2) 승인은 특정 스냅샷 내용(index.html+style.css+script.js의 해시)에 귀속된다 — 승인
     이후 Build가 다시 실행되어 내용이 달라지면(해시 불일치) 그 승인은 자동으로 무효가
     된다. Streamlit은 "재생성 버튼을 누르는 행위 자체"로 무조건 초기화했지만(내용이
     실제로 같아도 초기화됨), 여기서는 "내용이 실제로 바뀌었는가"로 판단해 동일한 안전
     의미(재검수 없이 이전 승인을 재사용할 수 없다)를 더 정확하게 재현한다.

api/services/generation_job_store.py와 동일한 설계 원칙을 그대로 따른다: 외부 큐/DB 없이
in-memory dict + threading.Lock, 프로세스 재시작 시 전부 유실(Streamlit의 session_state와
동일한 성격의 "미확정 상태"이므로 유실이 데이터 손실이 아니다 — 이미 저장된 계산기가
사라지는 게 아님), 프로세스 내 단일 인스턴스 패턴.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ReviewApproval:
    slug: str
    snapshot_hash: str
    approved_by: str
    approved_at: str


class ReviewApprovalStore:
    """slug → 최신 승인(ReviewApproval) 1건. in-memory, 프로세스 재시작 시 유실(의도적)."""

    def __init__(self):
        self._approvals: dict[str, ReviewApproval] = {}
        self._lock = threading.Lock()

    def approve(self, slug: str, snapshot_hash: str, approved_by: str) -> ReviewApproval:
        with self._lock:
            appr = ReviewApproval(
                slug=slug, snapshot_hash=snapshot_hash,
                approved_by=approved_by, approved_at=_now_iso(),
            )
            self._approvals[slug] = appr
            return appr

    def unapprove(self, slug: str) -> None:
        with self._lock:
            self._approvals.pop(slug, None)

    def get(self, slug: str) -> Optional[ReviewApproval]:
        with self._lock:
            return self._approvals.get(slug)

    def is_approved_for(self, slug: str, snapshot_hash: str) -> bool:
        """slug에 대한 최신 승인이 존재하고, 그 승인이 정확히 이 snapshot_hash에
        대한 것인지 확인한다. Build가 재실행되어 내용이 바뀌면(해시 불일치) False."""
        with self._lock:
            appr = self._approvals.get(slug)
            return appr is not None and appr.snapshot_hash == snapshot_hash


_store: Optional[ReviewApprovalStore] = None


def get_review_approval_store() -> ReviewApprovalStore:
    """api/services/generation_job_store.py::get_job_store()와 동일한 프로세스 내
    단일 인스턴스 패턴(중복 생성 방지)."""
    global _store
    if _store is None:
        _store = ReviewApprovalStore()
    return _store
