# -*- coding: utf-8 -*-
"""
modules/site_generator.py — CalcMate 사이트 페이지 생성기

생성 대상:
  index.html           메인 홈페이지
  site.css             사이트 공용 CSS (design token 공유)
  about/index.html     서비스 소개
  privacy/index.html   개인정보처리방침
  terms/index.html     이용약관
  contact/index.html   문의하기

deploy_all(cfg) → {path: content} dict — github_deployer.deploy_app과 동일 인터페이스.
"""
from __future__ import annotations

import html as _html
import datetime

# _CALC_DESCS 제거 (P2-2-C) — card_desc는 registry v3에서 공급됨.

_CONTACT_EMAIL = "calcmate.kr@gmail.com"
_EFFECTIVE_DATE = "2026년 8월 6일"

# ── Site CSS ─────────────────────────────────────────────────────────
_SITE_CSS = """\
/* CalcMate Site CSS — design_system.css 토큰 공유 */
:root{
  --c-primary:#2563EB;--c-primary-dark:#1D4ED8;--c-primary-bg:#EFF6FF;
  --c-success:#16A34A;--c-warning:#D97706;--c-danger:#DC2626;
  --c-bg:#F6F8FB;--c-card:#FFFFFF;--c-border:#EAECEF;
  --c-text:#111827;--c-text-sub:#6B7280;--c-text-light:#9CA3AF;
  --c-deep:#2C5AA0;--c-deep-dk:#1E3F74;--c-deep-bg:#EBF1F9;
  --r-card:24px;--r-input:16px;--r-btn:18px;--r-badge:100px;
  --sp-1:8px;--sp-2:16px;--sp-3:24px;--sp-4:32px;--sp-5:48px;
  --shadow-card:0 2px 16px rgba(0,0,0,.07);
  --shadow-btn:0 4px 12px rgba(37,99,235,.25);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:-apple-system,'Apple SD Gothic Neo','Pretendard','Noto Sans KR',sans-serif;
  background:var(--c-bg);color:var(--c-text);font-size:16px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
a{color:var(--c-primary);text-decoration:none}
a:hover{text-decoration:underline}

/* ── 레이아웃 ── */
.cm-wrap{max-width:960px;margin:0 auto;padding:0 var(--sp-2) var(--sp-5)}
.cm-wrap--narrow{max-width:720px;margin:0 auto;padding:0 var(--sp-2) var(--sp-5)}

/* ── 네비게이션 ── */
.cm-nav{background:var(--c-card);border-bottom:1px solid var(--c-border);
  position:sticky;top:0;z-index:200}
.cm-nav-inner{max-width:960px;margin:0 auto;padding:0 var(--sp-2);
  display:flex;align-items:center;justify-content:space-between;height:56px}
.cm-nav-logo{font-size:18px;font-weight:800;color:var(--c-primary);
  letter-spacing:-.5px;text-decoration:none}
.cm-nav-logo:hover{text-decoration:none}
.cm-nav-links{display:flex;gap:var(--sp-2);align-items:center}
.cm-nav-links a{font-size:14px;font-weight:500;color:var(--c-text-sub);text-decoration:none}
.cm-nav-links a:hover{color:var(--c-primary)}

/* ── 히어로 ── */
.cm-hero{padding:var(--sp-5) 0 var(--sp-4);text-align:center}
.cm-hero-logo{font-size:40px;font-weight:900;color:var(--c-primary);
  letter-spacing:-1px;margin-bottom:var(--sp-2)}
.cm-hero-tagline{font-size:18px;font-weight:700;color:var(--c-text);
  margin-bottom:var(--sp-1);letter-spacing:-.3px}
.cm-hero-sub{font-size:15px;color:var(--c-text-sub);margin-bottom:var(--sp-4);line-height:1.7}
.cm-hero-btn{display:inline-flex;align-items:center;gap:8px;
  padding:16px 36px;background:var(--c-primary);color:#fff;
  border-radius:var(--r-btn);font-size:17px;font-weight:700;
  text-decoration:none;box-shadow:var(--shadow-btn);
  transition:background .15s,transform .1s}
.cm-hero-btn:hover{background:var(--c-primary-dark);text-decoration:none;transform:translateY(-1px)}

/* ── 블로그 글 → 계산기 CTA(STEP 16-B) ── */
.cm-blog-cta{display:inline-flex;align-items:center;gap:6px;margin-top:var(--sp-2);
  padding:10px 20px;background:var(--c-primary);color:#fff;
  border-radius:var(--r-btn);font-size:14px;font-weight:700;
  text-decoration:none;transition:background .15s}
.cm-blog-cta:hover{background:var(--c-primary-dark);text-decoration:none}

/* ── 섹션 헤더 ── */
.cm-section{padding:var(--sp-4) 0 0}
.cm-section-title{font-size:20px;font-weight:800;letter-spacing:-.4px;
  margin-bottom:var(--sp-3);text-align:center}

/* ── 계산기 그리드 ── */
.cm-calc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--sp-2);margin-bottom:var(--sp-4)}
.cm-calc-card{background:var(--c-card);border:1.5px solid var(--c-border);
  border-radius:var(--r-card);padding:var(--sp-3);text-decoration:none;
  display:block;transition:border-color .15s,box-shadow .15s,transform .1s;
  box-shadow:var(--shadow-card)}
.cm-calc-card:hover{border-color:var(--c-primary);
  box-shadow:0 4px 24px rgba(37,99,235,.14);transform:translateY(-2px);text-decoration:none}
.cm-calc-emoji{font-size:32px;margin-bottom:var(--sp-1);display:block}
.cm-calc-name{font-size:15px;font-weight:700;color:var(--c-text);
  margin-bottom:6px;letter-spacing:-.2px}
.cm-calc-desc{font-size:13px;color:var(--c-text-sub);line-height:1.6}

/* ── About 섹션 (홈) ── */
.cm-about{background:var(--c-card);border-radius:var(--r-card);
  padding:var(--sp-4);box-shadow:var(--shadow-card);
  border:1px solid var(--c-border);margin-bottom:var(--sp-3)}
.cm-about-title{font-size:18px;font-weight:800;margin-bottom:var(--sp-2);letter-spacing:-.3px}
.cm-about-body{font-size:15px;color:var(--c-text-sub);line-height:1.8}
.cm-about-body p+p{margin-top:var(--sp-2)}

/* ── 이용안내 (홈) ── */
.cm-notice-box{background:#FFFBEB;border:1px solid #FDE68A;
  border-radius:var(--r-card);padding:var(--sp-3);margin-bottom:var(--sp-3)}
.cm-notice-title{font-size:14px;font-weight:700;color:#92400E;margin-bottom:var(--sp-1)}
.cm-notice-list{list-style:none;padding:0}
.cm-notice-list li{font-size:13px;color:#92400E;padding:5px 0;
  display:flex;gap:8px;line-height:1.6}
.cm-notice-list li::before{content:"✓";font-weight:700;flex-shrink:0;margin-top:1px}

/* ── 페이지 콘텐츠 (sub-pages) ── */
.cm-page-hero{padding:var(--sp-4) 0 var(--sp-3)}
.cm-page-title{font-size:26px;font-weight:800;letter-spacing:-.5px;margin-bottom:6px}
.cm-page-sub{font-size:14px;color:var(--c-text-sub)}
.cm-content{background:var(--c-card);border-radius:var(--r-card);
  padding:var(--sp-4);box-shadow:var(--shadow-card);border:1px solid var(--c-border);
  margin-bottom:var(--sp-3)}
.cm-content h2{font-size:16px;font-weight:700;margin:var(--sp-3) 0 var(--sp-1);
  color:var(--c-text);letter-spacing:-.2px}
.cm-content h2:first-child{margin-top:0}
.cm-content p{font-size:14px;color:var(--c-text-sub);line-height:1.8;margin-bottom:var(--sp-1)}
.cm-content p:last-child{margin-bottom:0}
.cm-content ul{padding-left:var(--sp-3);margin-bottom:var(--sp-1)}
.cm-content ul li{font-size:14px;color:var(--c-text-sub);line-height:1.8;padding:2px 0}
.cm-content ol{padding-left:var(--sp-3);margin-bottom:var(--sp-1);counter-reset:cm-ol}
.cm-content ol li{font-size:14px;color:var(--c-text-sub);line-height:1.8;padding:4px 0}
.cm-content .cm-date{font-size:13px;color:var(--c-text-light);margin-top:var(--sp-3)}
.cm-content .cm-contact-email{
  display:inline-block;margin:var(--sp-2) 0;
  padding:12px 24px;background:var(--c-primary-bg);
  border:1.5px solid var(--c-primary);border-radius:var(--r-input);
  color:var(--c-primary);font-size:15px;font-weight:700;
}
.cm-content .cm-note{font-size:13px;color:var(--c-text-light);
  border-left:3px solid var(--c-border);padding-left:var(--sp-2);
  margin-top:var(--sp-1)}

/* ── 푸터 ── */
.cm-footer{text-align:center;padding:var(--sp-4) 0;
  border-top:1px solid var(--c-border);margin-top:var(--sp-4)}
.cm-footer-logo{font-size:16px;font-weight:800;color:var(--c-primary);
  margin-bottom:var(--sp-1)}
.cm-footer-links{display:flex;gap:var(--sp-2);justify-content:center;
  flex-wrap:wrap;margin-bottom:var(--sp-2)}
.cm-footer-links a{font-size:13px;color:var(--c-text-sub);text-decoration:none}
.cm-footer-links a:hover{color:var(--c-primary)}
.cm-footer-copy{font-size:12px;color:var(--c-text-light)}

/* ── 404 페이지 ── */
.cm-404{text-align:center;padding:var(--sp-5) 0 var(--sp-4)}
.cm-404-code{font-size:80px;font-weight:900;color:var(--c-primary);
  letter-spacing:-3px;line-height:1;margin-bottom:var(--sp-2);opacity:.15}
.cm-404-title{font-size:22px;font-weight:800;letter-spacing:-.4px;
  margin-bottom:var(--sp-2);line-height:1.4}
.cm-404-sub{font-size:14px;color:var(--c-text-sub);margin-bottom:var(--sp-4)}
.cm-404-actions{display:flex;gap:var(--sp-2);justify-content:center;flex-wrap:wrap}
.cm-404-btn{display:inline-flex;align-items:center;padding:13px 28px;
  border-radius:var(--r-btn);font-size:15px;font-weight:700;
  text-decoration:none;transition:background .15s,transform .1s}
.cm-404-btn--primary{background:var(--c-primary);color:#fff;box-shadow:var(--shadow-btn)}
.cm-404-btn--primary:hover{background:var(--c-primary-dark);transform:translateY(-1px);text-decoration:none}
.cm-404-btn:not(.cm-404-btn--primary){background:var(--c-card);color:var(--c-primary);
  border:1.5px solid var(--c-primary)}
.cm-404-btn:not(.cm-404-btn--primary):hover{background:var(--c-primary-bg);text-decoration:none}

/* ── 반응형 ── */
@media(max-width:700px){
  .cm-calc-grid{grid-template-columns:repeat(2,1fr)}
  .cm-hero-logo{font-size:32px}
  .cm-hero-tagline{font-size:16px}
  .cm-hero-btn{font-size:15px;padding:14px 28px}
}
@media(max-width:480px){
  .cm-calc-grid{grid-template-columns:1fr}
  .cm-nav-links a:not(:last-child){display:none}
}
"""


# ── 공통 HTML 빌더 ─────────────────────────────────────────────────

def _esc(s: str) -> str:
    return _html.escape(str(s))


def _nav(site_url: str) -> str:
    u = site_url.rstrip("/")
    return (
        '<nav class="cm-nav" aria-label="메인 네비게이션">'
        '<div class="cm-nav-inner">'
        f'<a href="{u}/" class="cm-nav-logo">CalcMate</a>'
        '<div class="cm-nav-links">'
        f'<a href="{u}/">계산기</a>'
        f'<a href="{u}/about/">소개</a>'
        f'<a href="{u}/contact/">문의</a>'
        '</div>'
        '</div>'
        '</nav>'
    )


def _footer(site_url: str) -> str:
    u = site_url.rstrip("/")
    return (
        '<footer class="cm-footer">'
        '<div class="cm-footer-logo">CalcMate</div>'
        '<nav class="cm-footer-links" aria-label="푸터 링크">'
        f'<a href="{u}/about/">소개</a>'
        f'<a href="{u}/privacy/">개인정보처리방침</a>'
        f'<a href="{u}/terms/">이용약관</a>'
        f'<a href="{u}/contact/">문의하기</a>'
        '</nav>'
        '<p class="cm-footer-copy">© 2026 CalcMate. All rights reserved.</p>'
        '</footer>'
    )


def _ga4_snippet(ga4_id: str) -> str:
    if not ga4_id:
        return ""
    gid = _esc(ga4_id)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>\n'
        f'<script>window.dataLayer=window.dataLayer||[];'
        f'function gtag(){{dataLayer.push(arguments);}}'
        f"gtag('js',new Date());gtag('config','{gid}');</script>"
    )


def _page(title: str, description: str, css_path: str,
          site_url: str, body: str, canonical: str = "",
          ga4_id: str = "") -> str:
    u = site_url.rstrip("/")
    canon_tag = f'<link rel="canonical" href="{_esc(canonical)}">' if canonical else ""
    ga4_tag   = _ga4_snippet(ga4_id)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#2563EB">
<meta name="naver-site-verification" content="de4ad3f1575284b5a8ea58baab7bc7a77b7cf07e">
<meta name="description" content="{_esc(description)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{_esc(canonical or u + '/')}">
<title>{_esc(title)}</title>
{canon_tag}
<link rel="stylesheet" href="{css_path}">
{ga4_tag}
</head>
<body>
{_nav(u)}
{body}
</body>
</html>"""


# ── 메인 홈 페이지 ────────────────────────────────────────────────

def _extra_published_blog_articles(cfg: dict) -> list[dict]:
    """GOLDEN_10에 없는, publish 상태인 blog_articles만 골라 카드/sitemap용 최소
    필드({slug, title, description})로 정규화한다(STEP186 — WP 자동등록 병합).

    GOLDEN_10 원본 리스트는 이 함수 안에서도 읽기만 하며 절대 수정하지 않는다.
    calculators 테이블은 조회하지 않는다. 실패해도(DB 미구성 등) 빈 리스트를
    반환해 메인 페이지/sitemap 생성 자체가 깨지지 않도록 한다.
    """
    try:
        from content.blog import GOLDEN_10
        from adapters.db.factory import get_db_adapter
        from repositories.blog_article_repository import BlogArticleRepository

        golden10_slugs = {gc.slug for gc in GOLDEN_10}
        rows = BlogArticleRepository(get_db_adapter(cfg)).list_all()
    except Exception:
        return []

    extras = []
    for row in rows:
        slug = row.get("slug", "")
        if not slug or slug in golden10_slugs:
            continue
        if row.get("wp_status") != "publish":
            continue
        extras.append({
            "slug": slug,
            "title": row.get("title", "") or slug,
            "description": row.get("meta_description") or "",
        })
    return sorted(extras, key=lambda a: a["slug"])


def generate_index(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")
    ga4_id = cfg.get("GA4_MEASUREMENT_ID", "") or ""

    # 계산기 목록: registry v3 display_order 기준 정렬, card_desc는 v3 단일 소스
    from modules.app_generator import _registry
    from modules.registry_loader import load_registry_v3
    reg = _registry()
    _v3 = load_registry_v3()
    # status=HOLD(App Factory 생성 후 legal 미검증)는 공개 카드 제외
    _slugs = [s for s, _ in sorted(
        [(s, e.get("display_order", 999)) for s, e in _v3.items()
         if reg.get(s) and e.get("status") != "HOLD"],
        key=lambda x: x[1],
    )]
    calc_cards = "\n".join(
        f'<a class="cm-calc-card" href="{u}/{slug}/" aria-label="{_esc(calc.get("name", slug))}">'
        f'<span class="cm-calc-emoji" aria-hidden="true">{_esc(calc.get("emoji", "🧮"))}</span>'
        f'<div class="cm-calc-name">{_esc(calc.get("name", slug))}</div>'
        f'<div class="cm-calc-desc">{_esc((_v3.get(slug) or {}).get("card_desc") or "")}</div>'
        f'</a>'
        for slug in _slugs
        if (calc := reg.get(slug))
    )

    # Golden10 블로그 카드 — 계산기 그리드와 동일한 카드 패턴 재사용(STEP 16-B)
    from content.blog import GOLDEN_10
    blog_cards = "\n".join(
        f'<a class="cm-calc-card" href="{u}/blog/{gc.slug}/" aria-label="{_esc(gc.title)}">'
        f'<span class="cm-calc-emoji" aria-hidden="true">📖</span>'
        f'<div class="cm-calc-name">{_esc(gc.title)}</div>'
        f'<div class="cm-calc-desc">{_esc(gc.description)}</div>'
        f'</a>'
        for gc in GOLDEN_10
    )

    # WP 자동등록 신규 블로그 카드(STEP186) — GOLDEN_10은 위에서 그대로 유지하고,
    # GOLDEN_10에 없는 blog_articles(publish)만 추가한다. GOLDEN_10 카드 자체의
    # 순서/개수/내용에는 어떤 영향도 주지 않는다(추가만, 대체 없음).
    extra_blog_cards = "\n".join(
        f'<a class="cm-calc-card" href="{u}/blog/{a["slug"]}/" aria-label="{_esc(a["title"])}">'
        f'<span class="cm-calc-emoji" aria-hidden="true">📖</span>'
        f'<div class="cm-calc-name">{_esc(a["title"])}</div>'
        f'<div class="cm-calc-desc">{_esc(a["description"])}</div>'
        f'</a>'
        for a in _extra_published_blog_articles(cfg)
    )
    if extra_blog_cards:
        blog_cards = blog_cards + "\n" + extra_blog_cards

    body = f"""
<main>
  <div class="cm-wrap">
    <!-- Hero -->
    <section class="cm-hero">
      <div class="cm-hero-logo">{_esc(site_name)}</div>
      <p class="cm-hero-tagline">CalcMate — 실생활 계산기 모음</p>
      <p class="cm-hero-sub">필요한 계산을 쉽고 빠르게, 한곳에서 확인하세요.</p>
      <a class="cm-hero-btn" href="#calculators">계산기 시작하기</a>
    </section>

    <!-- 계산기 그리드 -->
    <section class="cm-section" id="calculators" aria-labelledby="calc-grid-title">
      <h2 class="cm-section-title" id="calc-grid-title">많이 찾는 계산기</h2>
      <div class="cm-calc-grid">
{calc_cards}
      </div>
    </section>

    <!-- 서비스 소개 -->
    <section class="cm-about" aria-labelledby="about-title">
      <h2 class="cm-about-title" id="about-title">CalcMate를 만든 이유</h2>
      <div class="cm-about-body">
        <p>직장인이라면 누구나 한 번쯤 "내 퇴직금은 얼마일까", "이번 달 실수령액은 얼마일까" 궁금했던 적이 있을 겁니다.</p>
        <p>CalcMate는 근로기준법, 고용보험법 등 관련 법령을 기준으로 정확한 계산 로직을 만들고, 법령이 바뀔 때마다 계산 기준도 함께 업데이트합니다.</p>
        <p>복잡한 노동법·세법 지식 없이도, 숫자만 입력하면 누구나 쉽게 자신의 권리를 확인할 수 있도록 돕습니다.</p>
      </div>
    </section>

    <!-- 이용 안내 -->
    <div class="cm-notice-box" role="note" aria-label="이용 안내">
      <div class="cm-notice-title">이용 전 꼭 확인하세요</div>
      <ul class="cm-notice-list">
        <li>계산 결과는 참고용입니다. 실제 지급액은 근무 조건, 회사 사정 등에 따라 달라질 수 있습니다.</li>
        <li>최신 법령 기준을 반영하려 노력하지만, 법령 개정 직후 일시적으로 차이가 있을 수 있습니다.</li>
        <li>입력하신 정보는 저장되지 않으며, 서버로 전송되지 않습니다.</li>
        <li>중요한 결정을 앞두고 있다면 노무사, 세무사 등 전문가와 상담하시길 권장합니다.</li>
      </ul>
    </div>

    <!-- 계산 가이드(Golden10 블로그) -->
    <section class="cm-section" id="guides" aria-labelledby="guides-title">
      <h2 class="cm-section-title" id="guides-title">자주 찾는 계산 가이드</h2>
      <div class="cm-calc-grid">
{blog_cards}
      </div>
    </section>

    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"{site_name} — 퇴직금·주휴수당·실업급여·4대보험 무료 계산기",
        description="퇴직금, 주휴수당, 실업급여, 4대보험, 연차수당을 법령 기준으로 쉽고 빠르게 계산하세요. 대한민국 직장인을 위한 무료 계산기 플랫폼.",
        css_path="site.css",
        site_url=u,
        body=body,
        canonical=f"{u}/",
        ga4_id=ga4_id,
    )


# ── 소개 페이지 ────────────────────────────────────────────────────

def generate_about(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")
    ga4_id = cfg.get("GA4_MEASUREMENT_ID", "") or ""

    body = f"""
<main>
  <div class="cm-wrap--narrow">
    <div class="cm-page-hero">
      <h1 class="cm-page-title">{_esc(site_name)} 소개</h1>
      <p class="cm-page-sub">대한민국 직장인을 위한 무료 계산기 서비스</p>
    </div>
    <div class="cm-content">
      <p>{_esc(site_name)}는 대한민국 직장인을 위한 무료 계산기 서비스입니다.</p>
      <p>퇴직금, 주휴수당, 실업급여, 4대보험, 연차수당 등 근로 현장에서 자주 궁금해하는 계산을 누구나 쉽고 빠르게 할 수 있도록 만들었습니다.</p>

      <h2>계산 기준</h2>
      <p>모든 계산기는 근로기준법, 고용보험법, 국민연금법 등 관련 법령을 기준으로 만들어졌으며, 법령이 개정될 경우 계산 로직도 함께 업데이트됩니다.</p>
      <p>정기적으로 법령 변경 사항을 점검하고 있습니다.</p>

      <h2>왜 CalcMate인가요</h2>
      <ul>
        <li>회원가입 없이 바로 이용 가능</li>
        <li>입력 정보를 저장하거나 수집하지 않음</li>
        <li>모바일에서도 편하게 이용 가능</li>
        <li>계속 늘어나는 계산기 라인업</li>
      </ul>

      <h2>문의</h2>
      <p>서비스 이용 중 궁금한 점이나 오류를 발견하셨다면 <a href="{u}/contact/">문의하기 페이지</a>를 통해 알려주세요.</p>
    </div>
    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"소개 — {site_name}",
        description=f"{site_name} 서비스 소개. 근로기준법 기준 퇴직금·주휴수당·실업급여 계산기 플랫폼입니다.",
        css_path="../site.css",
        site_url=u,
        body=body,
        canonical=f"{u}/about/",
        ga4_id=ga4_id,
    )


# ── 개인정보처리방침 ────────────────────────────────────────────────

def generate_privacy(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")
    ga4_id = cfg.get("GA4_MEASUREMENT_ID", "") or ""

    body = f"""
<main>
  <div class="cm-wrap--narrow">
    <div class="cm-page-hero">
      <h1 class="cm-page-title">개인정보처리방침</h1>
      <p class="cm-page-sub">{_esc(site_name)}는 이용자의 개인정보를 소중히 여기며 관련 법령을 준수합니다.</p>
    </div>
    <div class="cm-content">
      <h2>1. 수집하는 정보</h2>
      <p>{_esc(site_name)}는 계산기 이용 시 입력하는 정보(급여, 근무기간 등)를 서버에 저장하거나 수집하지 않습니다. 모든 계산은 이용자의 브라우저에서만 처리됩니다.</p>
      <p>다만 서비스 이용 과정에서 아래 정보가 자동으로 수집될 수 있습니다.</p>
      <ul>
        <li>접속 로그, IP 주소, 쿠키</li>
        <li>이용 기기 정보, 방문 페이지 기록</li>
      </ul>

      <h2>2. 정보 이용 목적</h2>
      <ul>
        <li>서비스 이용 통계 분석 및 개선</li>
        <li>광고 게재(Google AdSense 등 제3자 광고 서비스 이용 시)</li>
      </ul>

      <h2>3. 쿠키(Cookie) 사용</h2>
      <p>{_esc(site_name)}는 이용자 맞춤 서비스 제공 및 광고 게재를 위해 쿠키를 사용할 수 있습니다. 이용자는 브라우저 설정을 통해 쿠키 저장을 거부할 수 있습니다.</p>

      <h2>4. 제3자 제공</h2>
      <p>원칙적으로 개인정보를 외부에 제공하지 않습니다. 단, Google AdSense 등 광고 서비스 이용 시 해당 서비스의 자체 정책에 따라 정보가 처리될 수 있습니다.</p>

      <h2>5. 문의</h2>
      <p>개인정보 관련 문의는 <a href="{u}/contact/">문의하기 페이지</a>를 통해 연락 주시기 바랍니다.</p>

      <p class="cm-date">시행일: {_EFFECTIVE_DATE}</p>
    </div>
    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"개인정보처리방침 — {site_name}",
        description=f"{site_name} 개인정보처리방침. 이용자 정보 수집·이용 목적 및 쿠키 사용에 관한 안내입니다.",
        css_path="../site.css",
        site_url=u,
        body=body,
        canonical=f"{u}/privacy/",
        ga4_id=ga4_id,
    )


# ── 이용약관 ────────────────────────────────────────────────────────

def generate_terms(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")
    ga4_id = cfg.get("GA4_MEASUREMENT_ID", "") or ""

    body = f"""
<main>
  <div class="cm-wrap--narrow">
    <div class="cm-page-hero">
      <h1 class="cm-page-title">이용약관</h1>
      <p class="cm-page-sub">{_esc(site_name)} 서비스 이용 조건 및 절차에 관한 사항입니다.</p>
    </div>
    <div class="cm-content">
      <h2>제1조 (목적)</h2>
      <p>본 약관은 {_esc(site_name)}(이하 "서비스")가 제공하는 계산기 서비스의 이용 조건 및 절차에 관한 사항을 규정함을 목적으로 합니다.</p>

      <h2>제2조 (서비스의 내용)</h2>
      <p>서비스는 근로기준법 등 관련 법령을 기준으로 한 계산 도구를 무료로 제공합니다.</p>

      <h2>제3조 (계산 결과의 성격)</h2>
      <ol>
        <li>서비스가 제공하는 계산 결과는 참고용 정보이며, 법적 효력이나 구속력을 갖지 않습니다.</li>
        <li>실제 지급액, 수급액 등은 개별 사안에 따라 달라질 수 있으며, 서비스는 그 정확성을 보증하지 않습니다.</li>
        <li>중요한 의사결정은 관련 전문가(노무사, 세무사 등)와 상담 후 진행하시길 권장합니다.</li>
      </ol>

      <h2>제4조 (책임의 제한)</h2>
      <p>서비스는 계산 결과를 신뢰하여 발생한 손해에 대해 법적 책임을 지지 않습니다.</p>

      <h2>제5조 (서비스의 변경 및 중단)</h2>
      <p>서비스는 운영상, 기술상 필요에 따라 서비스의 전부 또는 일부를 변경하거나 중단할 수 있습니다.</p>

      <h2>제6조 (약관의 개정)</h2>
      <p>본 약관은 관련 법령 변경 또는 서비스 정책 변경에 따라 개정될 수 있으며, 개정 시 서비스 내 공지합니다.</p>

      <p class="cm-date">시행일: {_EFFECTIVE_DATE}</p>
    </div>
    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"이용약관 — {site_name}",
        description=f"{site_name} 이용약관. 계산기 서비스 이용 조건, 계산 결과의 성격, 책임 제한 등에 관한 사항입니다.",
        css_path="../site.css",
        site_url=u,
        body=body,
        canonical=f"{u}/terms/",
        ga4_id=ga4_id,
    )


# ── 문의하기 ────────────────────────────────────────────────────────

def generate_contact(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")
    ga4_id = cfg.get("GA4_MEASUREMENT_ID", "") or ""
    email = _CONTACT_EMAIL

    body = f"""
<main>
  <div class="cm-wrap--narrow">
    <div class="cm-page-hero">
      <h1 class="cm-page-title">문의하기</h1>
      <p class="cm-page-sub">서비스 관련 문의, 오류 신고, 개선 제안을 받습니다.</p>
    </div>
    <div class="cm-content">
      <p>서비스 이용 중 궁금한 점, 계산 오류, 개선 제안이 있다면 언제든지 알려주세요.</p>

      <h2>이메일 문의</h2>
      <a class="cm-contact-email" href="mailto:{_esc(email)}">{_esc(email)}</a>

      <p class="cm-note">개별 노무·세무 상담은 제공하지 않으며, 서비스 관련 문의만 받고 있습니다.</p>
      <p class="cm-note">법령 변경으로 인한 계산 기준 수정 요청도 환영합니다.</p>
    </div>
    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"문의하기 — {site_name}",
        description=f"{site_name} 문의하기. 서비스 오류 신고, 개선 제안, 법령 변경 제보를 받습니다.",
        css_path="../site.css",
        site_url=u,
        body=body,
        canonical=f"{u}/contact/",
        ga4_id=ga4_id,
    )


# ── 404 페이지 ────────────────────────────────────────────────────────

def generate_404(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    site_name = cfg.get("SITE_NAME", "CalcMate")

    body = f"""
<main>
  <div class="cm-wrap--narrow">
    <div class="cm-404">
      <div class="cm-404-code" aria-hidden="true">404</div>
      <h1 class="cm-404-title">죄송합니다.<br>찾으시는 계산기가 없습니다.</h1>
      <p class="cm-404-sub">URL을 다시 확인하거나 아래 버튼으로 이동하세요.</p>
      <div class="cm-404-actions">
        <a class="cm-404-btn cm-404-btn--primary" href="{u}/">홈으로</a>
        <a class="cm-404-btn" href="{u}/#calculators">계산기 목록</a>
      </div>
    </div>
    {_footer(u)}
  </div>
</main>"""

    return _page(
        title=f"페이지를 찾을 수 없습니다 — {site_name}",
        description=f"요청하신 페이지를 찾을 수 없습니다. {site_name} 홈으로 이동하세요.",
        css_path="site.css",
        site_url=u,
        body=body,
    )


# ── sitemap.xml ──────────────────────────────────────────────────────

def generate_sitemap(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    from modules.registry_loader import load_registry_v3
    today = datetime.date.today().isoformat()

    _v3 = load_registry_v3()
    # status=HOLD는 사이트맵 제외
    _sitemap_slugs = [s for s, _ in sorted(
        [(s, e) for s, e in _v3.items() if e.get("status") != "HOLD"],
        key=lambda x: x[1].get("display_order", 999),
    )]
    static_pages = [
        ("", "1.0", "weekly"),
        ("/about/", "0.6", "monthly"),
        ("/privacy/", "0.4", "monthly"),
        ("/terms/", "0.4", "monthly"),
        ("/contact/", "0.5", "monthly"),
    ]
    calc_entries = [(f"/{slug}/", "0.8", "weekly") for slug in _sitemap_slugs]

    # Golden10 블로그 글 — 기존 계산기 URL은 그대로 두고 추가만 한다(STEP 2).
    from content.blog import GOLDEN_10
    blog_entries = [(f"/blog/{gc.slug}/", "0.7", "monthly") for gc in GOLDEN_10]

    # WP 자동등록 신규 블로그 글(STEP186) — GOLDEN_10 URL은 위에서 그대로 유지하고,
    # GOLDEN_10에 없는 slug만 추가한다(중복 URL 방지는 _extra_published_blog_articles가
    # GOLDEN_10 slug를 이미 제외하므로 여기서 추가 중복 제거가 필요 없다).
    extra_blog_entries = [
        (f"/blog/{a['slug']}/", "0.7", "monthly")
        for a in _extra_published_blog_articles(cfg)
    ]

    all_entries = static_pages + calc_entries + blog_entries + extra_blog_entries

    items = "\n".join(
        f"  <url>"
        f"<loc>{u}{path}</loc>"
        f"<lastmod>{today}</lastmod>"
        f"<changefreq>{freq}</changefreq>"
        f"<priority>{priority}</priority>"
        f"</url>"
        for path, priority, freq in all_entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n"
        "</urlset>"
    )


# ── robots.txt ───────────────────────────────────────────────────────

def generate_robots(cfg: dict) -> str:
    u = cfg.get("SITE_URL", "https://calcmate.kr").rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {u}/sitemap.xml\n"
    )


# ── 전체 생성 ────────────────────────────────────────────────────────

def generate_all(cfg: dict) -> dict:
    """반환: {path: content} — github_deployer._put_file 호환."""
    return {
        "index.html":           generate_index(cfg),
        "site.css":             _SITE_CSS,
        "about/index.html":     generate_about(cfg),
        "privacy/index.html":   generate_privacy(cfg),
        "terms/index.html":     generate_terms(cfg),
        "contact/index.html":   generate_contact(cfg),
        "404.html":             generate_404(cfg),
        "sitemap.xml":          generate_sitemap(cfg),
        "robots.txt":           generate_robots(cfg),
    }
