# -*- coding: utf-8 -*-
"""modules/registry_loader.py — calculator_registry 통합 로더 (RMS G-1)

두 소스를 merge해서 slug→entry dict 반환:
  - docs/legal_basis.master.yaml : RMS 승인 완료(계산기가 실제로 읽는 파일). **우선**.
  - docs/registry_auto.yaml       : App Factory(save_app)가 자동생성. 사람이 직접 편집하지 않음.

동일 slug가 양쪽에 있으면 **master(legal_basis.master.yaml)가 항상 우선**.
→ 법령 변경은 반드시 rms_promote.py 워크플로(DETECTED→DRAFT→APPROVED→PROMOTED)를 통해서만
  master.yaml에 반영됨. draft.yaml을 직접 수정해도 계산기에 반영되지 않음.

app_generator / calculator_pipeline / publish_quality 세 로더가 이 함수에 위임(단일 소스).
"""
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_CURATED_PATH = _BASE / "docs" / "legal_basis.master.yaml"
_AUTO_PATH = _BASE / "docs" / "registry_auto.yaml"

_cache = None


def _read_yaml(path: Path) -> dict:
    """YAML 파일 → dict(schema_version 제거). 없거나 파싱 실패 시 {}."""
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    data.pop("schema_version", None)
    return data


def load_registry(force: bool = False) -> dict:
    """slug→entry. auto 위에 curated를 덮어써 curated 우선. 1회 캐시(force=True 시 재로딩)."""
    global _cache
    if _cache is None or force:
        merged = dict(_read_yaml(_AUTO_PATH))      # 자동 먼저
        merged.update(_read_yaml(_CURATED_PATH))   # 큐레이션이 덮어씀(동일 slug 우선)
        _cache = merged
    return _cache


def invalidate():
    """캐시 무효화(App Factory가 registry_auto.yaml에 쓴 직후 등)."""
    global _cache, _lm_cache, _reg_cache
    _cache = None
    _lm_cache = None
    _reg_cache = None


# ── Sprint B-1: legal_master/ + registry/ 병행 로더(SSOT 신구조) ──────────
# 기존 load_registry(slug 단위 legal_basis.draft.yaml)와 별개로 추가만 함(프로덕션 영향 0).
# resolve(slug) 가 기존 load_registry().get(slug) 와 동일 결과를 내도록 설계(검증됨).
_LM_DIR = _BASE / "docs" / "legal_master"
_REG_DIR = _BASE / "docs" / "registry"
_lm_cache = None
_reg_cache = None


def _read_dir(d: Path) -> dict:
    """디렉토리 내 *.yaml 을 merge(키=entity_id 또는 slug). 없으면 {}."""
    merged = {}
    if d.exists():
        for f in sorted(d.glob("*.yaml")):
            part = _read_yaml(f)   # schema_version 제거 포함
            if isinstance(part, dict):
                merged.update(part)
    return merged


def load_legal_master(force: bool = False) -> dict:
    """entity_id → 법령필드 dict. legal_master/*.yaml merge. 1회 캐시."""
    global _lm_cache
    if _lm_cache is None or force:
        _lm_cache = _read_dir(_LM_DIR)
    return _lm_cache


def load_registry_v3(force: bool = False) -> dict:
    """slug → 계산기필드(+legal_refs) dict. registry/*.yaml merge. 1회 캐시."""
    global _reg_cache
    if _reg_cache is None or force:
        _reg_cache = _read_dir(_REG_DIR)
    return _reg_cache


def resolve(slug: str, force: bool = False) -> dict | None:
    """slug → (참조 법령 필드 + 계산기 필드) 병합 dict. 기존 load_registry().get(slug)와 동등.
    법령 필드 먼저, 계산기 필드 나중(겹침 없음). 신구조 미존재 시 None."""
    reg = load_registry_v3(force)
    r = reg.get(slug)
    if r is None:
        return None
    merged: dict = {}
    for ref in r.get("legal_refs", []) or []:
        merged.update(load_legal_master(force).get(ref, {}))
    merged.update(r)   # 계산기 필드(legal_refs 포함)
    return merged


def find_impacted(entity_id: str, force: bool = False) -> list[str]:
    """법령 엔티티 ID를 참조하는 계산기 slug 목록(legal_refs 역인덱스 = 조회 View).
    설계 §6/§9: 저장하지 않고 registry에서 매번 도출(SSOT). '법령 변경 → 영향 계산기'의 기반."""
    reg = load_registry_v3(force)
    eid = str(entity_id)
    return [slug for slug, r in reg.items()
            if eid in ((r or {}).get("legal_refs") or [])]


# ── 법률 분류(legal_requirement) — needs_human_legal 게이트와 분리 ──────────
# v3 App Factory 엔트리(docs/registry/*_af.yaml)에 명시적으로 기록된 경우에만 적용한다.
# 필드가 없는 기존 계산기는 게이트별 기존 규칙(legacy)을 그대로 따른다 — article과
# deploy는 기존 규칙이 서로 다르므로 하나의 공통 fallback으로 합치지 않는다.
LEGAL_REQUIREMENT_VALUES = ("REQUIRED", "NOT_REQUIRED", "REVIEW")
LEGAL_GATES = ("article", "deploy")


def evaluate_legal_requirement(entry: dict, force: bool = False) -> tuple[bool, str]:
    """명시적 legal_requirement 판정 → (cleared, reason).
    REQUIRED는 legal_refs가 1개 이상이고 모두 legal_master에서 해석될 때만 통과.
    REVIEW·허용되지 않은 값은 통과하지 않는다."""
    value = (entry or {}).get("legal_requirement")
    if value == "NOT_REQUIRED":
        return True, "legal_requirement=NOT_REQUIRED"
    if value == "REQUIRED":
        refs = (entry or {}).get("legal_refs") or []
        if not isinstance(refs, list) or not refs:
            return False, "legal_requirement=REQUIRED이나 legal_refs가 없습니다"
        master = load_legal_master(force=True) if force else load_legal_master()
        missing = [r for r in refs if not isinstance(r, str) or r not in master]
        if missing:
            return False, f"legal_requirement=REQUIRED이나 legal_master에 없는 legal_refs: {missing}"
        return True, f"legal_requirement=REQUIRED (legal_refs {len(refs)}개 확인)"
    if value == "REVIEW":
        return False, "legal_requirement=REVIEW — 법률 분류 검토가 완료되지 않았습니다"
    return False, f"허용되지 않은 legal_requirement 값: {value!r}"


def legal_gate(slug: str, gate: str, force: bool = False) -> tuple[bool, str, bool]:
    """게이트별 법률 판정 → (cleared, reason, explicit).
    explicit=True: v3 엔트리에 legal_requirement가 있어 분류로 판정함.
    explicit=False: 기존 규칙 — article: needs_human_legal AND law/article/authority 전부 공백이면 차단,
                     deploy: needs_human_legal이면 차단."""
    if gate not in LEGAL_GATES:
        raise ValueError(f"알 수 없는 legal gate: {gate!r}")
    v3_entry = (load_registry_v3(force=True) if force else load_registry_v3()).get(slug) or {}
    if "legal_requirement" in v3_entry:
        cleared, reason = evaluate_legal_requirement(v3_entry, force)
        return cleared, reason, True
    lb = (load_registry(force=True) if force else load_registry()).get(slug) or {}
    if gate == "article":
        blocked = (isinstance(lb, dict) and bool(lb.get("needs_human_legal"))
                   and not (lb.get("law") or lb.get("article") or lb.get("authority")))
    else:
        blocked = bool(lb.get("needs_human_legal"))
    return (not blocked), ("needs_human_legal" if blocked else "legacy"), False


def legal_cleared(slug: str, gate: str, force: bool = False) -> bool:
    """legal_gate()의 통과 여부만 반환."""
    return legal_gate(slug, gate, force)[0]


def calculator_name(slug: str) -> str:
    """slug → 사람 가독 이름(registry.name). 없으면 slug 그대로(알림 표기용)."""
    r = load_registry_v3().get(slug) or {}
    return r.get("name") or slug


_AUTO_HEADER = (
    "# registry_auto.yaml — App Factory 자동생성 계산기 registry (RMS G-1)\n"
    "#\n"
    "# ⚠️ 이 파일은 App Factory(modules/app_factory.save_app)가 자동으로 씁니다. 사람이 직접 편집하지 마세요.\n"
    "# 자동생성 엔트리는 legal(law/article/authority 등) 전부 null + needs_human_legal: true 입니다.\n"
    "# 정식 legal 검증이 끝나면 rms_promote.py 워크플로를 통해 docs/legal_basis.master.yaml 에 승격하세요\n"
    "# (동일 slug는 master.yaml 이 우선하므로, 승격 후 이 파일의 항목은 자동으로 무시됩니다).\n"
)


def add_auto_entry(slug: str, entry: dict) -> None:
    """registry_auto.yaml에 엔트리 추가/갱신(PyYAML safe_dump — 자동생성 전용이라 포맷 보존 불필요).
    헤더 주석 재삽입, 캐시 무효화. slug가 이미 있으면 덮어씀(재생성 대응)."""
    import yaml
    data = _read_yaml(_AUTO_PATH)   # 기존 엔트리(없으면 {})
    data[str(slug)] = entry
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    _AUTO_PATH.write_text(_AUTO_HEADER + "\n" + body, encoding="utf-8")
    invalidate()


def remove_auto_entry(slug: str) -> bool:
    """registry_auto.yaml에서 slug 엔트리 제거. 존재하지 않으면 False 반환."""
    import yaml
    data = _read_yaml(_AUTO_PATH)
    if str(slug) not in data:
        return False
    del data[str(slug)]
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    _AUTO_PATH.write_text(_AUTO_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    return True
