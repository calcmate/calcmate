# -*- coding: utf-8 -*-
"""
content/blog/template.py — 블로그 콘텐츠 HTML 템플릿 어댑터

Golden 10 재현성 테스트를 위한 최소 HTML 조립 로직.
"""
import json

# Mapping of slugs to their required institution links.
# Each entry is a list of (display_name, url) tuples.
# This is used by build_blog_html to display slug-specific institution links.
SLUG_LINKS = {
    'severance-pay': [
        ('고용노동부', 'https://www.moel.go.kr'),
    ],
    'weekly-holiday-allowance': [
        ('고용노동부', 'https://www.moel.go.kr'),
    ],
    'unemployment-benefit': [
        ('고용노동부', 'https://www.moel.go.kr'),
        ('고용24', 'https://www.work24.go.kr'),
    ],
    'four-insurances': [
        ('국민연금공단', 'https://www.nps.or.kr'),
        ('국민건강보험공단', 'https://www.nhis.or.kr'),
        ('근로복지공단', 'https://www.comwel.or.kr'),
    ],
    'annual-leave-allowance': [
        ('고용노동부', 'https://www.moel.go.kr'),
    ],
    'severance-pay-documents': [
        ('고용노동부', 'https://www.moel.go.kr'),
        ('근로복지공단', 'https://www.comwel.or.kr'),
    ],
    '육아휴직_급여_계산기': [
        ('고용노동부', 'https://www.moel.go.kr'),
        ('고용24', 'https://www.work24.go.kr'),
    ],
    '연말정산_환급액_계산기': [
        ('국세청', 'https://www.nts.go.kr'),
        ('국세청 홈택스', 'https://www.hometax.go.kr'),
    ],
    'unemployment-benefit-howto': [
        ('고용노동부', 'https://www.moel.go.kr'),
        ('고용24', 'https://www.work24.go.kr'),
    ],
    'four-insurances-documents': [
        ('국민연금공단', 'https://www.nps.or.kr'),
        ('국민건강보험공단', 'https://www.nhis.or.kr'),
        ('근로복지공단', 'https://www.comwel.or.kr'),
    ],
}


def build_blog_html(body: str, faq: list = None, calc_slug: str = "", calc_name: str = "") -> str:
    """블로그 콘텐츠 HTML 조립 — body HTML + 인라인 FAQ + 계산기 CTA.

    기존 Golden 10 사이트 출력과 동일한 구조를 유지한다.
    """
    parts = [body]

    # 인라인 FAQ (<dl> 형식)
    if faq:
        faq_html = '<h2>FAQ</h2>\n<dl class="faq-list">\n'
        for item in faq:
            q = item.get("question", "")
            a = item.get("answer", "")
            if q and a:
                faq_html += f'  <dt>{q}</dt>\n  <dd>{a}</dd>\n'
        faq_html += '</dl>\n'
        # FAQ가 이미 body에 없을 때만 추가
        if '<dl class="faq-list">' not in body and '<dl>' not in body:
            parts.append(faq_html)

    # 공식 기관 안내 (slug별 맞춤 링크)
    calc_slug_param = calc_slug or ''
    link_items = SLUG_LINKS.get(calc_slug_param, [])
    if link_items:
        link_html = '<p>관련 기관:</p>\n'
        for name, url in link_items:
            link_html += f'<a href="{url}" target="_blank" rel="noopener noreferrer">{name}</a> '
        parts.append(link_html)

    # 계산기 CTA
    if calc_slug and calc_name:
        # calc_name이 이미 "계산기"로 끝나는 경우 중복 방지
        if calc_name.endswith("계산기"):
            cta_name = calc_name
        else:
            cta_name = f"{calc_name} 계산기"
        cta_html = f'''
<div class="cm-blog-cta">
    <p>직접 계산해보시려면 <a href="https://calcmate.kr/{calc_slug}/" target="_blank" rel="noopener noreferrer">{cta_name}</a>를 이용해보세요.</p>
</div>
'''
        parts.append(cta_html)

    return ''.join(parts)


def build_blog_jsonld(post: dict, faq: list = None) -> dict:
    """블로그 JSON-LD 메타데이터 — FAQ Schema."""
    if not faq:
        return {}

    items = []
    for item in faq:
        q = item.get("question", "")
        a = item.get("answer", "")
        if q and a:
            items.append({
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": a,
                }
            })

    if not items:
        return {}

    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": items,
    }
