# -*- coding: utf-8 -*-
"""tests/test_ca1b4_p1b_scope_exclusions_prompt.py — CA-1B-4 P1-B

Contract.scope_exclusions → AI 생성 Prompt 소비 연결 검증.
- _build_contract_enforcement_prompt(): CONTRACT SCOPE EXCLUSIONS 섹션 (TYPE A/B 구분, 빈값 생략)
- generate_app() writer 단계(u3): [Contract 생성 텍스트 제한] 전달
- retry: retry_sys = sys1 재사용으로 자동 유지

실제 AI API 호출 없음 — _chat()을 monkeypatch로 mock.
실제 docs/contract_schema/instances/에는 쓰지 않음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules.app_factory import _build_contract_enforcement_prompt, generate_app


# ── 공통 mock 헬퍼 ─────────────────────────────────────────────────────────
_DEFAULT_SPEC = ('{"calculator_type":"general","input_schema":{"a":"number"},'
                 '"output_schema":{"result":"number"},"formula":"a","labels":{}}')


def _capture_chat(calls, spec_text=None):
    """_chat() mock — 호출(system/user)을 calls에 기록하고 단계별 응답 반환.

    spec_text: orchestrator(스펙) 단계가 반환할 원문 텍스트 (None이면 유효 스펙).
    반환 형식은 _chat과 동일하게 (text, model, tokens) 3-tuple.
    """
    def mock(cfg, role, system, user, max_tokens=1200):
        calls.append({"role": role, "system": system, "user": user})
        if role == "orchestrator":
            return (spec_text if spec_text is not None else _DEFAULT_SPEC, "gpt", 100)
        if role == "code":
            return ("<html><body>ok</body></html>", "claude", 200)
        if role == "writer":
            return ('{"seo_title":"T","seo_desc":"D","faq":[],"blog_draft":""}',
                    "gpt", 100)
        return ('{"image_prompt_thumbnail":"","image_prompt_body":""}', "gemini", 50)
    return mock


_CONTRACT = {
    "slug": "unemployment-benefit",
    "name": "실업급여 계산기",
    "category": "고용/보험",
    "tier": "Tier2-A",
    "input_fields": ["avg_daily_wage", "age", "employment_months"],
    "output_fields": ["daily_benefit", "total_benefit"],
    "formula": None,
    "formula_status": "pending_validation",
    "scope_exclusions": ["받을 수 있습니다", "받게 됩니다", "수급 대상입니다"],
    "legal_refs": ["employment_insurance_act_40"],
    "test_cases": [],
}


# ── Test 1/2: enforcement prompt — section + TYPE B 원문 포함 ──────────────
def test_enforcement_prompt_includes_scope_exclusions():
    p = _build_contract_enforcement_prompt(_CONTRACT)
    assert "CONTRACT SCOPE EXCLUSIONS" in p
    # "계산 범위 제외가 아니라 생성 텍스트 제한" 의미 명시
    assert "생성 텍스트 제한" in p
    assert "계산 범위/계산식 제외 조건이 아님" in p
    # TYPE B — 사용 금지 표현 원문 그대로
    assert "[사용 금지 표현]" in p
    for phrase in ["받을 수 있습니다", "받게 됩니다", "수급 대상입니다"]:
        assert f"- {phrase}" in p


def test_enforcement_prompt_type_a_forbidden_articles():
    c = dict(_CONTRACT, scope_exclusions=["근로기준법 제34조"],
             legal_refs=["worker_retirement_benefit_act_8"])
    p = _build_contract_enforcement_prompt(c)
    assert "[인용 금지 조항]" in p
    assert "- 근로기준법 제34조" in p


def test_enforcement_prompt_type_a_and_b_separated():
    """TYPE A/B가 하나의 무의미한 목록으로 합쳐지지 않아야 한다."""
    c = dict(_CONTRACT,
             scope_exclusions=["근로기준법 제34조", "받을 수 있습니다"],
             legal_refs=["worker_retirement_benefit_act_8", "employment_insurance_act_40"])
    p = _build_contract_enforcement_prompt(c)
    assert "[인용 금지 조항]" in p and "[사용 금지 표현]" in p
    # 각 유형 헤더 아래 해당 값만
    a_block = p.split("[인용 금지 조항]")[1].split("[사용 금지 표현]")[0]
    b_block = p.split("[사용 금지 표현]")[1]
    assert "근로기준법 제34조" in a_block and "받을 수 있습니다" not in a_block
    assert "받을 수 있습니다" in b_block and "근로기준법 제34조" not in b_block


# ── Test 3: 빈 리스트 → 섹션 없음 + 핵심 구조 유지 ─────────────────────────
def test_enforcement_prompt_empty_list_omits_section():
    c = dict(_CONTRACT, scope_exclusions=[], legal_refs=[])
    p = _build_contract_enforcement_prompt(c)
    assert "CONTRACT SCOPE EXCLUSIONS" not in p
    # 기존 핵심 구조 유지
    assert "CONTRACT LOCK" in p
    assert "【핵심 규칙】" in p
    assert "avg_daily_wage, age, employment_months" in p


# ── Test 4: None → 예외 없음 + 섹션 없음 ───────────────────────────────────
def test_enforcement_prompt_none_no_section():
    c = dict(_CONTRACT, scope_exclusions=None, legal_refs=None)
    p = _build_contract_enforcement_prompt(c)
    assert "CONTRACT SCOPE EXCLUSIONS" not in p


# ── Test 5: 특수문자 → 예외 없음 + 값 보존 ─────────────────────────────────
def test_enforcement_prompt_special_chars():
    c = dict(_CONTRACT, scope_exclusions=[": - \" ' { }", "colon:value"],
             legal_refs=[])
    p = _build_contract_enforcement_prompt(c)
    assert "CONTRACT SCOPE EXCLUSIONS" in p
    assert "- : - \" ' { }" in p
    assert "- colon:value" in p


# ── Test 6: writer 단계(u3) 전달 + spec/code/image 중복 없음 ───────────────
def test_writer_step_receives_scope_exclusions(monkeypatch):
    calls = []
    monkeypatch.setattr("modules.app_factory._chat", _capture_chat(calls))
    result = generate_app({"DB_ADAPTER": "memory"}, "실업급여 계산기",
                          "고용/보험", "", 2, _contract=_CONTRACT)
    assert result["name"] == "실업급여 계산기"
    roles = {c["role"] for c in calls}
    # ISSUE-01 보완: generate_app()의 이미지 프롬프트 단계(_chat role="image")를
    # 제거했다(소비처 0건 확인 — 상세 사유는 modules/app_factory.py의 해당 위치
    # 주석 참고) — "image"는 더 이상 발생하는 role이 아니다.
    assert roles == {"orchestrator", "code", "writer"}
    # writer user에 [Contract 생성 텍스트 제한] + 표현 포함
    writer = next(c for c in calls if c["role"] == "writer")
    assert "[Contract 생성 텍스트 제한" in writer["user"]
    assert "받을 수 있습니다" in writer["user"]
    assert "수급 대상입니다" in writer["user"]
    # orchestrator system: enforcement section 포함
    orch = next(c for c in calls if c["role"] == "orchestrator")
    assert "CONTRACT SCOPE EXCLUSIONS" in orch["system"]
    # code 단계 prompt에 scope 제한 불필요 (중복 주입 없음)
    code = next(c for c in calls if c["role"] == "code")
    assert "Scope Exclusions" not in code["system"] + code["user"]


# ── Test 7: retry 경로에도 scope exclusion 유지 ────────────────────────────
def test_retry_prompt_keeps_scope_exclusions(monkeypatch):
    calls = []
    # 첫 orchestrator 응답 formula가 검증 실패("a + b" — b 미정의) → retry 1회
    _INVALID_SPEC = ('{"calculator_type":"general","input_schema":{"a":"number"},'
                     '"output_schema":{"result":"number"},"formula":"a + b","labels":{}}')
    mock = _capture_chat(calls, spec_text=_INVALID_SPEC)

    def side_effect(cfg, role, system, user, max_tokens=1200):
        # retry(두 번째 orchestrator)는 유효 formula로 응답
        if role == "orchestrator" and len([c for c in calls
                                           if c["role"] == "orchestrator"]) >= 1:
            calls.append({"role": role, "system": system, "user": user})
            return (_DEFAULT_SPEC, "gpt", 100)
        return mock(cfg, role, system, user, max_tokens=max_tokens)
    monkeypatch.setattr("modules.app_factory._chat", side_effect)
    result = generate_app({"DB_ADAPTER": "memory"}, "실업급여 계산기",
                          "고용/보험", "", 2, _contract=_CONTRACT)
    assert result["_steps"] is not None
    orch_calls = [c for c in calls if c["role"] == "orchestrator"]
    assert len(orch_calls) >= 2  # 최초 + retry
    for oc in orch_calls:
        assert "CONTRACT SCOPE EXCLUSIONS" in oc["system"]


# ── Test 8: scope_exclusions 없는 기존 Contract — 정상 동작 ────────────────
def test_no_scope_exclusions_contract_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr("modules.app_factory._chat", _capture_chat(calls))
    c = dict(_CONTRACT, scope_exclusions=[], legal_refs=[])
    result = generate_app({"DB_ADAPTER": "memory"}, "실업급여 계산기",
                          "고용/보험", "", 2, _contract=c)
    assert result["name"] == "실업급여 계산기"
    # writer user에 scope block 없음
    writer = next(c for c in calls if c["role"] == "writer")
    assert "[Contract 생성 텍스트 제한" not in writer["user"]
    # 기존 핵심 필드 유지
    assert result["input_schema"] == {"a": "number"}
