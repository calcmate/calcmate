# -*- coding: utf-8 -*-
"""
modules.factory.evidence — Evidence Layer

법령/요율/판례 등 계산 근거 자료의 표준 모델.
W3C PROV-JSON 호환, dataprov/auditweave/provena 연계 가능.
자동 법령 수집은 구현하지 않음 — 데이터 구조와 validation contract만 정의.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class SourceType(str, Enum):
    """증거 자료 유형."""
    LAW = "LAW"                    # 법률 (예: 소득세법)
    REGULATION = "REGULATION"      # 시행령/시행규칙
    NOTICE = "NOTICE"              # 고시/공고/예규
    PRECEDENT = "PRECEDENT"        # 판례/심판례
    OFFICIAL_TABLE = "OFFICIAL_TABLE"  # 공식 표/요율표
    MANUAL = "MANUAL"              # 매뉴얼/지침/해설서
    OTHER = "OTHER"                # 기타


class VerificationStatus(str, Enum):
    """증거 검증 상태."""
    UNVERIFIED = "UNVERIFIED"  # 미검증 (초기 상태)
    VERIFIED = "VERIFIED"      # 검증 완료
    STALE = "STALE"            # 만료/구버전 (effective_to 경과 등)
    CONFLICT = "CONFLICT"      # 충돌 (동일 파라미터에 서로 다른 증거)


@dataclass
class EvidenceRecord:
    """
    증거 레코드 최소 스키마.

    법령/요율은 특히:
    - 현재 값
    - 효력 시작일 (effective_from)
    - 효력 종료일 (effective_to, OPEN 가능)
    - 출처 (source_url, publisher)
    - 원문 해시 (content_hash)
    를 보존한다.
    """
    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    source_type: SourceType = SourceType.OTHER
    source_url: str = ""
    source_title: str = ""
    publisher: str = ""
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    effective_from: date = field(default_factory=date.today)
    effective_to: date | None = None  # None = OPEN (무기한)
    version: str = "1.0.0"
    content_hash: str = ""  # SHA256 hex
    claim: str = ""  # 이 증거가 지지하는 주장/수치
    parameter_refs: list[str] = field(default_factory=list)  # 연결된 Parameter ID
    calculator_refs: list[str] = field(default_factory=list)  # 연결된 Calculator ID
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    metadata: dict[str, Any] = field(default_factory=dict)  # 확장 메타데이터

    def is_effective_on(self, target_date: date) -> bool:
        """대상 날짜에 효력이 있는지 확인."""
        if self.effective_from > target_date:
            return False
        if self.effective_to is not None and self.effective_to < target_date:
            return False
        return True

    def to_prov_json(self) -> dict:
        """W3C PROV-JSON 호환 직렬화 (dataprov 연계용)."""
        return {
            "entity": {
                f"evidence:{self.evidence_id}": {
                    "prov:type": "prov:Entity",
                    "prov:label": self.source_title,
                    "source_type": self.source_type.value,
                    "source_url": self.source_url,
                    "publisher": self.publisher,
                    "retrieved_at": self.retrieved_at.isoformat() + "Z",
                    "effective_from": self.effective_from.isoformat(),
                    "effective_to": self.effective_to.isoformat() if self.effective_to else "OPEN",
                    "version": self.version,
                    "content_hash": f"sha256:{self.content_hash}",
                    "claim": self.claim,
                }
            }
        }

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type.value,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "publisher": self.publisher,
            "retrieved_at": self.retrieved_at.isoformat(),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else "OPEN",
            "version": self.version,
            "content_hash": self.content_hash,
            "claim": self.claim,
            "parameter_refs": self.parameter_refs,
            "calculator_refs": self.calculator_refs,
            "verification_status": self.verification_status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRecord":
        ev = cls(
            evidence_id=data.get("evidence_id", str(uuid4())),
            source_type=SourceType(data.get("source_type", "OTHER")),
            source_url=data.get("source_url", ""),
            source_title=data.get("source_title", ""),
            publisher=data.get("publisher", ""),
            retrieved_at=datetime.fromisoformat(data["retrieved_at"].replace("Z", "+00:00"))
                if data.get("retrieved_at") else datetime.utcnow(),
            effective_from=date.fromisoformat(data["effective_from"])
                if data.get("effective_from") else date.today(),
            effective_to=date.fromisoformat(data["effective_to"])
                if data.get("effective_to") and data["effective_to"] != "OPEN" else None,
            version=data.get("version", "1.0.0"),
            content_hash=data.get("content_hash", ""),
            claim=data.get("claim", ""),
            parameter_refs=data.get("parameter_refs", []),
            calculator_refs=data.get("calculator_refs", []),
            verification_status=VerificationStatus(data.get("verification_status", "UNVERIFIED")),
            metadata=data.get("metadata", {}),
        )
        return ev


class EvidenceRegistry:
    """
    Evidence 저장소 인터페이스.
    실제 구현은 dataprov/auditweave/provena 어댑터로 위임.
    MVP에서는 인메모리 dict로 동작.
    """

    def __init__(self):
        self._store: dict[str, EvidenceRecord] = {}

    def add(self, evidence: EvidenceRecord) -> EvidenceRecord:
        if evidence.evidence_id in self._store:
            raise ValueError(f"Evidence already exists: {evidence.evidence_id}")
        self._store[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._store.get(evidence_id)

    def update(self, evidence: EvidenceRecord) -> EvidenceRecord:
        if evidence.evidence_id not in self._store:
            raise KeyError(f"Evidence not found: {evidence.evidence_id}")
        self._store[evidence.evidence_id] = evidence
        return evidence

    def delete(self, evidence_id: str) -> bool:
        if evidence_id in self._store:
            del self._store[evidence_id]
            return True
        return False

    def find_by_parameter(self, parameter_id: str) -> list[EvidenceRecord]:
        """특정 파라미터를 참조하는 증거 목록."""
        return [e for e in self._store.values() if parameter_id in e.parameter_refs]

    def find_by_calculator(self, calculator_id: str) -> list[EvidenceRecord]:
        """특정 계산기를 참조하는 증거 목록."""
        return [e for e in self._store.values() if calculator_id in e.calculator_refs]

    def find_effective_on(self, target_date: date, parameter_id: str | None = None) -> list[EvidenceRecord]:
        """특정 날짜에 효력 있는 증거 목록 (파라미터 필터 옵션)."""
        results = [e for e in self._store.values() if e.is_effective_on(target_date)]
        if parameter_id:
            results = [e for e in results if parameter_id in e.parameter_refs]
        return results

    def find_stale_or_conflict(self) -> list[EvidenceRecord]:
        """STALE 또는 CONFLICT 상태인 증거 목록."""
        return [e for e in self._store.values()
                if e.verification_status in (VerificationStatus.STALE, VerificationStatus.CONFLICT)]

    def all(self) -> list[EvidenceRecord]:
        return list(self._store.values())


# 전역 레지스트리 (MVP용)
_global_registry: EvidenceRegistry | None = None


def get_evidence_registry() -> EvidenceRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = EvidenceRegistry()
    return _global_registry


def validate_evidence(evidence: EvidenceRecord) -> tuple[bool, list[str]]:
    """증거 레코드 유효성 검증."""
    errors = []

    if not evidence.source_url:
        errors.append("source_url is required")
    if not evidence.source_title:
        errors.append("source_title is required")
    if not evidence.publisher:
        errors.append("publisher is required")
    if not evidence.claim:
        errors.append("claim is required")
    if not evidence.content_hash:
        errors.append("content_hash is required (SHA256)")
    elif len(evidence.content_hash) != 64:
        errors.append("content_hash must be 64-char SHA256 hex")
    if evidence.effective_to and evidence.effective_to < evidence.effective_from:
        errors.append("effective_to cannot be before effective_from")
    if not evidence.parameter_refs and not evidence.calculator_refs:
        errors.append("at least one parameter_ref or calculator_ref is required")

    return len(errors) == 0, errors