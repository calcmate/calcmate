# -*- coding: utf-8 -*-
"""
modules/calculator_seo_generator.py — 계산기 SEO 메타 자동 생성 (v12.0)
출력: seo_title / seo_description / seo_keywords
"""
from datetime import datetime
import re

from .ai_roles import make_provider
from .ai_provider import build_provider_for_role
from .utils.parser import parse_json_lenient
from .logger import get_logger, BudgetTracker
from . import calculator_prompt_manager as PM

LOG = get_logger()


# 계산기 카테고리 → intent 매핑 (prompt.py와 동일)
_CATEGORY_TO_INTENT = {
    '건강/체질량지수': 'health_metric',
    '건강': 'health_metric',
    '퇴직/연차': 'labor_money',
    '퇴직/연차/기타': 'labor_money',
    '고용/실업': 'welfare_benefit',
    '고용/실업/기타': 'welfare_benefit',
    '세금': 'tax_insurance',
    '세금/환급': 'tax_insurance',
    '사회보험': 'tax_insurance',
    '세금/기타': 'tax_insurance',
    '부동산': 'housing_finance',
    '부동산/중개': 'housing_finance',
    '기타': 'general_calculator',
    '기타/일반': 'general_calculator',
    '연차/휴가': 'general_calculator',
    '기타/일반/기타': 'general_calculator',
    '건강/기타': 'general_calculator',
}

def _get_intent_from_category(calc: dict) -> str:
    """계산기 카테고리에서 intent를 결정한다."""
    category = calc.get('category', '') or ''
    return _CATEGORY_TO_INTENT.get(category.strip(), 'general_calculator')


def _normalize_seo_title(title: str) -> str:
    """SEO 제목에서 en-dash(–), em-dash(—)를 일반 하이픈(-)으로 변환."""
    if not title:
        return title
    # en-dash(–), em-dash(—) → 하이픈(-)
    title = title.replace('\u2013', '-').replace('\u2014', '-')
    # 연속된 공백 정리
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _seo_pair(cfg: dict, calc: dict) -> dict:
    """calc dict 기반 SEO 1회 생성(제목+메타). 모델 규칙: MODEL_WRITER."""
    system, user = PM.get_seo_prompt(calc)
    provider, model = build_provider_for_role("writing", cfg)
    text, tokens = provider.chat(system, user, model, max_tokens=400)
    try:
        BudgetTracker(cfg).record(model, tokens)
    except Exception as _e:
        LOG.warning("토큰 비용 기록 실패: %s", _e)
    d = parse_json_lenient(text)
    name = calc.get("name", "")
    # intent 결정 (calculator intent 분기 로직과 일치)
    intent = _get_intent_from_category(calc)
    seo_title = _normalize_seo_title(d.get("seo_title") or f"{datetime.now().year} {name} | 자동 계산")
    # intent별 SEO description fallback
    base = name.replace("계산기", "").strip()
    fallback_desc = {
        'health_metric': f"{name.replace('계산기','').strip()} 계산 방법과 판정 기준을 확인하고 자동 계산기를 이용해보세요.",
        'labor_money': f"{name.replace('계산기','').strip()} 지급 조건과 계산 방법을 확인하고 자동 계산기를 이용해보세요.",
        'welfare_benefit': f"{name.replace('계산기','').strip()} 지급 조건과 신청 방법을 확인하고 자동 계산기를 이용해보세요.",
        'tax_insurance': f"{name.replace('계산기','').strip()} 납부/공제 기준과 계산 방법을 확인하고 자동 계산기를 이용해보세요.",
        'housing_finance': f"{name.replace('계산기','').strip()} 계산 기준과 계산 방법을 확인하고 자동 계산기를 이용해보세요.",
        'general_calculator': f"{name.replace('계산기','').strip()} 계산 방법과 기준을 확인하고 자동 계산기를 이용해보세요.",
    }.get(_get_intent_from_category(calc), f"{name.replace('계산기','').strip()} 계산 방법과 기준을 확인하고 자동 계산기를 이용해보세요.")
    
    seo_title = _normalize_seo_title(d.get("seo_title") or f"{datetime.now().year} {name} | 자동 계산")
    return {
        "seo_title": seo_title,
        "seo_description": d.get("seo_description") or f"{name.replace('계산기','').strip()} 계산 방법과 기준을 확인하고 자동 계산기를 이용해보세요.",
    }


def generate_seo_title(cfg: dict, calc: dict) -> str:
    """SEO 제목 생성(지시서 함수). calc dict 입력."""
    try:
        return _seo_pair(cfg, calc)["seo_title"]
    except Exception as e:
        LOG.warning("SEO 제목 생성 실패 → 기본값: %s", e)
        return _normalize_seo_title(f"{datetime.now().year} {calc.get('name','')} | 자동 계산")


def generate_meta_description(cfg: dict, calc: dict) -> str:
    """SEO 메타설명 생성(지시서 함수). calc dict 입력."""
    try:
        return _seo_pair(cfg, calc)["seo_description"]
    except Exception as e:
        LOG.warning("메타설명 생성 실패 → 기본값: %s", e)
        base = calc.get("name", "").replace("계산기", "").strip()
        return f"{base} 계산 방법과 기준을 확인하고 자동 계산기로 즉시 계산해보세요."


def generate_seo(cfg: dict, name: str, keyword: str = "", intent: str = None) -> dict:
    year = datetime.now().year
    
    # 2. 제목 생성 규칙 - eligibility intent일 경우
    if intent == "eligibility":
        base = name.replace("계산기", "").strip()
        seo_title = f"{year} {base} 지급 조건은? 핵심 자격요건 쉽게 설명"
    else:
        # 기존 로직
        seo_title = None

    system = ("너는 SEO 전문가다. 주어진 계산기/키워드에 대한 SEO 메타데이터를 작성하라. "
              "규칙: "
              "1) seo_title은 28~40자, 연도 포함. "
              "2) 타겟 키워드를 제목에 반드시 포함할 것(예: '계산법' 키워드면 '계산법'이 제목에 있어야 함). "
              "3) 서로 다른 키워드는 반드시 서로 다른 제목을 만들 것 — '총정리/가이드/안내' 등 동일 suffix로 수렴 금지. "
              "순수 JSON만 반환: "
              '{"seo_title":"","seo_description":"","seo_keywords":[]}')
    user = f"계산기명: {name}\n타겟 키워드: {keyword or name}\n연도: {year}"
    
    try:
        provider, model = make_provider(cfg, "writer")
        text, tokens = provider.chat(system, user, model, max_tokens=500)
        try:
            BudgetTracker(cfg).record(model, tokens)
        except Exception as _e:
            LOG.warning("토큰 비용 기록/조회 실패: %s", _e)
        d = parse_json_lenient(text)
        
        # intent가 지정되었고 생성된 제목보다 규칙 제목이 우선되어야 한다면 덮어쓰기
        final_title = seo_title if seo_title else d.get("seo_title", "")
        
        return {
            "seo_title": final_title or f"{year} {name} | 자동 계산",
            "seo_description": d.get("seo_description", ""),
            "seo_keywords": d.get("seo_keywords", []),
        }
    except Exception as e:
        LOG.warning("SEO 생성 실패(%s) → 기본값: %s", name, e)
        base = name.replace("계산기", "").strip()
        final_title = seo_title if seo_title else f"{year} {name} | 자동 계산"
        return {
            "seo_title": final_title,
            "seo_description": f"{base} 지급 기준과 계산 방법을 확인하고 자동 계산기를 이용해보세요.",
            "seo_keywords": [keyword or name, f"{base} 계산", f"{base} 계산법"],
        }
