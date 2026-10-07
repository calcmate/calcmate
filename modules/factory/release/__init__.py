# -*- coding: utf-8 -*-
"""
modules.factory.release — Release Manifest

8개 하위 버전 + 상위 release_version (SemVer).
Manifest 생성/검증만 구현, 실제 배포는 별도 단계.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class VersionBundle:
    """8개 하위 버전 묶음."""
    spec_version: str = "0.1.0"
    semantics_version: str = "0.1.0"
    evidence_version: str = "0.1.0"
    parameter_version: str = "0.1.0"
    engine_version: str = "0.1.0"
    ui_version: str = "0.1.0"
    content_version: str = "0.1.0"
    validation_version: str = "0.1.0"

    def to_dict(self) -> dict:
        return {
            "spec_version": self.spec_version,
            "semantics_version": self.semantics_version,
            "evidence_version": self.evidence_version,
            "parameter_version": self.parameter_version,
            "engine_version": self.engine_version,
            "ui_version": self.ui_version,
            "content_version": self.content_version,
            "validation_version": self.validation_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VersionBundle":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def bump(self, component: str, level: str = "patch") -> "VersionBundle":
        """특정 컴포넌트 버전 증가 (major/minor/patch)."""
        import re
        current = getattr(self, component)
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", current)
        if not match:
            return self
        major, minor, patch = map(int, match.groups())
        if level == "major":
            major += 1
            minor = 0
            patch = 0
        elif level == "minor":
            minor += 1
            patch = 0
        else:  # patch
            patch += 1
        new_version = f"{major}.{minor}.{patch}"
        new_bundle = VersionBundle(**self.to_dict())
        setattr(new_bundle, component, new_version)
        return new_bundle


@dataclass
class ReleaseManifest:
    """Release Manifest — 계산기 배포 메타데이터."""
    calculator_id: str
    slug: str
    release_version: str = "0.1.0"  # 상위 SemVer
    versions: VersionBundle = field(default_factory=VersionBundle)

    released_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    approved_by: str = ""
    approval_role: str = ""  # legal_reviewer | product_owner | admin

    # 아티팩트 참조
    parity_report_ref: str | None = None
    spec_ref: str | None = None
    semantics_ref: str | None = None
    evidence_ref: str | None = None
    ground_truth_ref: str | None = None
    engine_ref: str | None = None
    ui_ref: str | None = None
    content_ref: str | None = None

    # 메타데이터
    changelog: str = ""
    breaking_changes: bool = False
    migration_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "calculator_id": self.calculator_id,
            "slug": self.slug,
            "release_version": self.release_version,
            "versions": self.versions.to_dict(),
            "released_at": self.released_at,
            "approved_by": self.approved_by,
            "approval_role": self.approval_role,
            "parity_report_ref": self.parity_report_ref,
            "spec_ref": self.spec_ref,
            "semantics_ref": self.semantics_ref,
            "evidence_ref": self.evidence_ref,
            "ground_truth_ref": self.ground_truth_ref,
            "engine_ref": self.engine_ref,
            "ui_ref": self.ui_ref,
            "content_ref": self.content_ref,
            "changelog": self.changelog,
            "breaking_changes": self.breaking_changes,
            "migration_notes": self.migration_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReleaseManifest":
        versions_data = data.get("versions", {})
        versions = VersionBundle.from_dict(versions_data)
        return cls(
            calculator_id=data.get("calculator_id", ""),
            slug=data.get("slug", ""),
            release_version=data.get("release_version", "0.1.0"),
            versions=versions,
            released_at=data.get("released_at", datetime.utcnow().isoformat()),
            approved_by=data.get("approved_by", ""),
            approval_role=data.get("approval_role", ""),
            parity_report_ref=data.get("parity_report_ref"),
            spec_ref=data.get("spec_ref"),
            semantics_ref=data.get("semantics_ref"),
            evidence_ref=data.get("evidence_ref"),
            ground_truth_ref=data.get("ground_truth_ref"),
            engine_ref=data.get("engine_ref"),
            ui_ref=data.get("ui_ref"),
            content_ref=data.get("content_ref"),
            changelog=data.get("changelog", ""),
            breaking_changes=data.get("breaking_changes", False),
            migration_notes=data.get("migration_notes", ""),
        )


class ReleaseManifestValidator:
    """Release Manifest 유효성 검증."""

    REQUIRED_FIELDS = [
        "calculator_id", "slug", "release_version",
        "approved_by", "approval_role", "released_at",
    ]
    REQUIRED_VERSIONS = [
        "spec_version", "semantics_version", "evidence_version",
        "parameter_version", "engine_version", "ui_version",
        "content_version", "validation_version",
    ]

    @classmethod
    def validate(cls, manifest: ReleaseManifest) -> tuple[bool, list[str]]:
        errors = []

        # 필수 필드 검증
        for field in cls.REQUIRED_FIELDS:
            if not getattr(manifest, field, None):
                errors.append(f"Missing required field: {field}")

        # 버전 필드 검증
        versions_dict = manifest.versions.to_dict()
        for v in cls.REQUIRED_VERSIONS:
            if not versions_dict.get(v):
                errors.append(f"Missing version: {v}")

        # SemVer 형식 검증
        import re
        semver_pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$"
        if not re.match(semver_pattern, manifest.release_version):
            errors.append(f"Invalid release_version format (must be SemVer): {manifest.release_version}")

        for v in cls.REQUIRED_VERSIONS:
            if not re.match(semver_pattern, versions_dict.get(v, "")):
                errors.append(f"Invalid version format for {v}: {versions_dict.get(v)}")

        # 승인 역할 검증
        valid_roles = {"legal_reviewer", "product_owner", "admin"}
        if manifest.approval_role and manifest.approval_role not in valid_roles:
            errors.append(f"Invalid approval_role: {manifest.approval_role}")

        return len(errors) == 0, errors


class ReleaseRegistry:
    """Release Manifest 저장소 (MVP: 인메모리)."""

    def __init__(self):
        self._store: dict[str, ReleaseManifest] = {}  # calculator_id -> latest manifest
        self._history: dict[str, list[ReleaseManifest]] = {}  # calculator_id -> all manifests

    def add(self, manifest: ReleaseManifest) -> ReleaseManifest:
        if manifest.calculator_id not in self._store:
            self._store[manifest.calculator_id] = manifest
            self._history[manifest.calculator_id] = []
        else:
            # 기존 것을 히스토리로 이동
            self._history[manifest.calculator_id].append(self._store[manifest.calculator_id])
            self._store[manifest.calculator_id] = manifest
        return manifest

    def get_latest(self, calculator_id: str) -> ReleaseManifest | None:
        return self._store.get(calculator_id)

    def get_history(self, calculator_id: str) -> list[ReleaseManifest]:
        return self._history.get(calculator_id, [])

    def get_by_version(self, calculator_id: str, release_version: str) -> ReleaseManifest | None:
        for m in self._history.get(calculator_id, []):
            if m.release_version == release_version:
                return m
        latest = self._store.get(calculator_id)
        if latest and latest.release_version == release_version:
            return latest
        return None

    def all_latest(self) -> list[ReleaseManifest]:
        return list(self._store.values())


_global_release_registry: ReleaseRegistry | None = None


def get_release_registry() -> ReleaseRegistry:
    global _global_release_registry
    if _global_release_registry is None:
        _global_release_registry = ReleaseRegistry()
    return _global_release_registry


def create_release_manifest(
    calculator_id: str,
    slug: str,
    spec: Any,
    semantics: Any,
    evidence_registry: Any,
    ground_truth_suite: Any,
    engine: Any,
    ui_schema: Any,
    content_package: Any,
    parity_report_ref: str,
    approved_by: str,
    approval_role: str,
    changelog: str = "",
    breaking_changes: bool = False,
) -> ReleaseManifest:
    """
    모든 구성요소로부터 Release Manifest 생성.
    실제로는 각 구성요소의 버전을 추출해 묶음.
    """
    # 버전 추출 (실제로는 각 구성요소의 version 필드에서)
    versions = VersionBundle(
        spec_version=getattr(spec.version, "spec", "0.1.0"),
        semantics_version=getattr(semantics, "version", "0.1.0"),
        evidence_version="0.1.0",  # evidence_registry에서 추출
        parameter_version="0.1.0",
        engine_version=getattr(engine, "engine_version", "0.1.0"),
        ui_version="0.1.0",
        content_version=getattr(content_package, "version", "0.1.0"),
        validation_version="0.1.0",
    )

    # 다음 release_version 결정 (patch 증가)
    release_version = "0.1.0"  # 실제로는 기존 manifest 확인 후 증가

    manifest = ReleaseManifest(
        calculator_id=calculator_id,
        slug=slug,
        release_version=release_version,
        versions=versions,
        approved_by=approved_by,
        approval_role=approval_role,
        parity_report_ref=parity_report_ref,
        spec_ref=f"spec_{calculator_id}",
        semantics_ref=f"semantics_{calculator_id}",
        evidence_ref=f"evidence_{calculator_id}",
        ground_truth_ref=f"ground_truth_{calculator_id}",
        engine_ref=f"engine_{calculator_id}",
        ui_ref=f"ui_{calculator_id}",
        content_ref=f"content_{calculator_id}",
        changelog=changelog,
        breaking_changes=breaking_changes,
    )
    return manifest