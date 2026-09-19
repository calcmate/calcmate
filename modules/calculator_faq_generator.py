# -*- coding: utf-8 -*-
"""
modules/calculator_faq_generator.py — 계산기 FAQ 자동 생성 (SalaryMate)
출력: FAQ 5~10개 [{"question","answer"}]  (모델 규칙: MODEL_WRITER)

주: app_generator/calculator_pipeline 등 기존 소비자는 q/a 또는 question/answer
    양쪽을 허용하도록 처리되어 있어 하위호환 유지.
"""
from .ai_provider import build_provider_for_role
from .utils.parser import parse_json_lenient
from .logger import get_logger, BudgetTracker
from . import calculator_prompt_manager as PM

LOG = get_logger()


def generate_faq(cfg, name_or_calc, n: int = 6, n_max: int = 8, example_context: dict = None) -> list:
    """name(str) 또는 calc(dict) 입력 모두 허용. FAQ 6~8개 반환(6필수항목 포함).
    example_context: CALCMATE-BLOG-QUALITY-STEP135 — 결정론적 계산 예시(verified_examples/
    facts)를 FAQ 프롬프트에 그대로 전달한다. None이면 기존과 동일하게 동작한다."""
    calc = name_or_calc if isinstance(name_or_calc, dict) else {"name": str(name_or_calc)}
    name = calc.get("name", "")
    try:
        system, user = PM.get_faq_prompt(calc, n, n_max, example_context=example_context)
        provider, model = build_provider_for_role("writing", cfg)
        text, tokens = provider.chat(system, user, model, max_tokens=1200)
        try:
            BudgetTracker(cfg).record(model, tokens)
        except Exception as _e:
            LOG.warning("토큰 비용 기록 실패: %s", _e)
        faq = parse_json_lenient(text).get("faq", [])
        if isinstance(faq, list) and faq:
            return faq[:n_max]
        raise ValueError("빈 FAQ")
    except Exception as e:
        LOG.warning("FAQ 생성 실패(%s) → 기본 FAQ: %s", name, e)
        base = name.replace("계산기", "").strip()
        return [
            {"question": f"{base}은(는) 누구나 받을 수 있나요?", "answer": "조건에 따라 다릅니다. 자격 요건을 확인하세요."},
            {"question": f"{base} 계산 기준은 무엇인가요?", "answer": "법정 기준에 따라 산정됩니다."},
            {"question": f"{base} 계산기는 어떻게 사용하나요?", "answer": "값을 입력하고 계산하기 버튼을 누르면 됩니다."},
            {"question": f"{base} 계산 시 주의할 점은?", "answer": "입력값의 단위와 기준 기간을 정확히 확인하세요."},
            {"question": f"{base} 관련 문의는 어디에 하나요?", "answer": "관할 기관 또는 고용노동부 상담센터를 이용하세요."},
        ][:n_max]
