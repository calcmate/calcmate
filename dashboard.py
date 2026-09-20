"""
dashboard.py — 블로그자동화 v11.9 운영 대시보드 (오류 완치 최종본)
최신 텍스트 AI 라인업 + 🎨 이미지 생성 AI 설정 (무료/유료 완벽 분기 및 인덱스 에러 방어 탑재)
"""
import streamlit as st
import json, yaml, sys, time, os
from pathlib import Path
from datetime import datetime, date

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# ── 마법사 우선 체크 (config.yaml 없거나 미설정이면 마법사 실행) ────────
from modules.setup_wizard import config_exists, render_wizard

def _needs_setup() -> bool:
    if not config_exists():
        return True
    try:
        cfg_path = BASE / "config" / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            c = yaml.safe_load(f) or {}
    except Exception:
        return True
    has_ai_key   = any(c.get(k) for k in ("OPENAI_API_KEY", "CLAUDE_API_KEY", "GEMINI_API_KEY"))
    has_sheet_id = bool(c.get("GOOGLE_SHEET_ID"))
    return not (has_ai_key or has_sheet_id)

if _needs_setup():
    render_wizard()
    st.stop()

# ── 일반 대시보드 진입 ────────────────────────────────────────
from modules.utils import health_monitor as hc_mod
from modules.slug_generator import generate_slug

st.set_page_config(
    page_title="블로그자동화 v12 운영센터",
    page_icon="🛰️",
    layout="wide",
)

# ── SaaS 다크/글래스 테마 적용 (UI 전용, 기존 로직 무관) ──────────
def load_css(path: str = "assets/css/dashboard.css"):
    f = BASE / path
    if f.exists():
        st.markdown(f"<style>{f.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

load_css()

# ── config 로드 ────────────────────────────────────────────────
@st.cache_resource(ttl=30)
def load_cfg():
    cfg_path = BASE / "config" / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        c = yaml.safe_load(f) or {}
    # 민감정보는 config/secrets.yaml에 분리 저장 → 런타임 병합(secrets 우선)
    from modules.config_loader import merge_secrets
    c = merge_secrets(c, str(cfg_path))
    c["_root"] = str(BASE)   # scheduler/backup 경로 기준
    return c

cfg = load_cfg()

# ── Blog Schedule 스레드 (Golden 10 블로그 콘텐츠 자동 발행) ──────────
# Calculator Scheduler와 완전히 분리된 독립 스레드.
# BLOG_SCHEDULE.enabled=true일 때만 기동.
@st.cache_resource
def _start_blog_scheduler_thread():
    import threading
    for _t in threading.enumerate():
        if _t.name == "blog-scheduler-loop" and _t.is_alive():
            return _t
    from modules.scheduler import run_scheduler_loop
    import main as _PIPE

    # Blog 라인 전용 cfg 복사본 — Calculator cfg와 독립
    blog_cfg = dict(cfg)
    blog_cfg["scheduler_line"] = "blog"

    def _loop():
        try:
            run_scheduler_loop(blog_cfg, _PIPE.resolve_blog_publish_fn(blog_cfg))
        except Exception as e:
            import logging
            logging.getLogger("dashboard").error("Blog 스케줄러 스레드 종료: %s", e, exc_info=True)
            try:
                from modules import telegram_ops
                telegram_ops.notify_level(blog_cfg, "ERROR",
                    "Blog 발행 스케줄러 스레드 종료", e, event="error")
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="blog-scheduler-loop", daemon=True)
    t.start()
    return t

# Blog Scheduler: BLOG_SCHEDULE.enabled=true일 때만 기동
if cfg.get("BLOG_SCHEDULE", {}).get("enabled", False):
    _start_blog_scheduler_thread()

# ── Calculator Webapp Schedule 스레드 (Phase F-1) ─────────────────────
# 계산기 "웹앱"(AG.generate_calculator → _site/{slug}/ 스냅샷 → 자동 QA → [배포])을
# 자동 생성하는 스레드. Blog Scheduler와 완전히 분리된 독립 스레드이며,
# 기존 Calculator Scheduler(SEO 아티클용 run_calculator_once)와도 무관하다.
# CALC_WEBAPP_SCHEDULE.enabled=true일 때만 기동.
@st.cache_resource
def _start_calc_webapp_scheduler_thread():
    import threading
    for _t in threading.enumerate():
        if _t.name == "calc-webapp-scheduler-loop" and _t.is_alive():
            return _t
    from modules.scheduler import run_scheduler_loop
    from modules.calc_webapp_pipeline import run_calc_webapp_once

    # Calculator Webapp 라인 전용 cfg 복사본 — Blog cfg와 독립
    calc_webapp_cfg = dict(cfg)
    calc_webapp_cfg["scheduler_line"] = "calc_webapp"

    def _loop():
        try:
            run_scheduler_loop(calc_webapp_cfg, run_calc_webapp_once)
        except Exception as e:
            import logging
            logging.getLogger("dashboard").error("Calculator Webapp 스케줄러 스레드 종료: %s", e, exc_info=True)
            try:
                from modules import telegram_ops
                telegram_ops.notify_level(calc_webapp_cfg, "ERROR",
                    "Calculator Webapp 스케줄러 스레드 종료", e, event="error")
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="calc-webapp-scheduler-loop", daemon=True)
    t.start()
    return t

if cfg.get("CALC_WEBAPP_SCHEDULE", {}).get("enabled", False):
    _start_calc_webapp_scheduler_thread()

# ── Content Sync(WP→Sheets 동기화) 백그라운드 자동 실행 ────────────
# Publish Scheduler와 완전히 분리된 독립 서비스. 대시보드가 떠 있으면 매일
# CONTENT_SYNC.run_at(기본 03:00)에 1회 동기화가 자동 실행된다(별도 스레드/락/이력).
# run_sync.py 를 Windows 작업 스케줄러로 병행 등록해도 content_sync.lock +
# 하루 1회 실행 가드가 중복 실행을 막아준다.
@st.cache_resource
def _start_content_sync_thread():
    import threading
    # 프로세스당 1개 보장(scheduler와 동일 가드)
    for _t in threading.enumerate():
        if _t.name == "content-sync-loop" and _t.is_alive():
            return _t
    from modules.content_sync import run_sync_loop

    def _loop():
        try:
            run_sync_loop(cfg)
        except Exception as e:  # 스레드가 죽어도 대시보드는 유지
            import logging
            logging.getLogger("dashboard").error("content_sync 스레드 종료: %s", e, exc_info=True)
            # 자동화 정지 — 운영자 즉시 인지(Sprint 1 §1-2)
            try:
                from modules import telegram_ops
                telegram_ops.notify_level(cfg, "ERROR",
                    "Content Sync 스레드 종료 — 동기화 중단됨", e, event="error")
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="content-sync-loop", daemon=True)
    t.start()
    return t

# CONTENT_SYNC.enabled 가 true 일 때만 기동(기본 True)
if (cfg.get("CONTENT_SYNC") or {}).get("enabled", True):
    _start_content_sync_thread()

# ── 빠른 읽기 헬퍼 (운영센터 5초 로딩 목표 — 모두 로컬 파일) ──────
def _read_health_cache() -> dict:
    p = BASE / "data" / "logs" / "health_last.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

# ── 로그 tail 읽기 (전체 읽기 금지: 끝부분 바이트만) ──────────────
def _tail_lines(rel: str, n: int = 150, blk: int = 65536) -> list:
    p = BASE / rel
    if not p.exists():
        return []
    try:
        sz = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, sz - blk))
            data = f.read()
        return data.decode("utf-8", "replace").splitlines()[-n:]
    except Exception:
        return []

def _recent_error_lines(n: int = 5) -> list:
    lines = _tail_lines("data/logs/pipeline.log", 400)
    return [l for l in lines if "[ERROR]" in l][-n:][::-1]

# ── 캐시 레이어 (Google Sheet 조회 60초 캐시 — 메뉴 이동 가속) ──────
#   ※ 기능/출력 불변: 데이터는 최대 60초 캐시. 발행/생성 액션 후 _run_action에서 캐시 무효화.
#   2단 캐시: st.cache_data(세션 60초) + SQLite 미러(세션간/만료 후 가속, 라이브 폴백)
@st.cache_data(ttl=60, show_spinner=False)
def cached_posts() -> list:
    from modules.dashboard_cache import read
    return read(cfg, "articles", ttl=120)

@st.cache_data(ttl=60, show_spinner=False)
def cached_table(table: str) -> list:
    from modules.dashboard_cache import read
    return read(cfg, table, ttl=120)

def _run_action(label: str, fn):
    """빠른 실행 패널 공통 래퍼 — 스피너 + 결과/오류 표시. 액션 후 캐시 무효화."""
    with st.spinner(f"{label} 실행 중..."):
        try:
            res = fn()
            st.session_state["_last_action"] = (True, f"✅ {label} 완료: {res if res is not None else ''}")
        except Exception as e:
            st.session_state["_last_action"] = (False, f"❌ {label} 실패: {e}")
    try:
        st.cache_data.clear()   # 발행/생성 등으로 데이터가 바뀌었을 수 있어 갱신
        from modules.dashboard_cache import invalidate_all
        invalidate_all(cfg)     # SQLite 미러도 만료 → 다음 읽기에서 원본 재조회
    except Exception:
        pass

# ── 사이드바 ───────────────────────────────────────────────────
st.sidebar.title("🛰️ 블로그자동화 v12")
st.sidebar.markdown("**운영 방식:** `예약 발행`")
st.sidebar.markdown(f"**애드센스:** `{cfg.get('ADSENSE_MODE','pre').upper()}`")
st.sidebar.markdown(f"**일 예산:** `${cfg.get('DAILY_AI_BUDGET',5)}`")

# v12 Lite: 8개 그룹으로 통합(기존 페이지 유지, 그룹→하위 2단 네비). 계산기 생성은 App Factory 단일화.
NAV_GROUPS = {
    "🏠 Dashboard":    ["🏠 운영센터", "📊 현황"],
    "📝 Content":      ["📋 발행 목록", "🗑️ 휴지통", "📋 작업 보드", "💬 AI Workspace", "🧠 전략회의실"],
    "🧮 Calculator":   ["🏭 App Factory", "🧮 계산기 관리"],
    "📅 Scheduler":    ["📝 Blog Schedule", "📊 AI Pipeline", "🌐 사이트 관리"],
    "💰 Revenue":      ["💰 비용 모니터"],
    "📡 Logs":         ["⚠️ 오류 로그", "📡 실시간 로그", "🏥 헬스체크"],
    "🔧 Settings":     ["🔧 설정"],
    "🤖 AI Assistant": ["🤖 AI Assistant"],
}
_group = st.sidebar.radio("메뉴", list(NAV_GROUPS.keys()), key="nav_group")
_subs = NAV_GROUPS[_group]
if len(_subs) > 1:
    tab = st.sidebar.radio(_group, _subs, key=f"sub_{_group}")
else:
    tab = _subs[0]

# ══════════════════════════════════════════════════════════════
# 탭: 🏠 운영센터 (홈) — 5초 안에 전체 상태 파악 + 빠른 실행
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# SaaS Dashboard Home 컴포넌트 (UI 전용 — 로직/Repository/Adapter/Pipeline 무관)
# ══════════════════════════════════════════════════════════════
def render_header():
    st.markdown(
        '<div class="sm-card" style="margin-bottom:16px">'
        '<div style="font-size:25px;font-weight:800;letter-spacing:-.5px;'
        'background:linear-gradient(90deg,#a5b4fc,#67e8f9);-webkit-background-clip:text;'
        'background-clip:text;-webkit-text-fill-color:transparent">CalcMate OS</div>'
        '<div class="sm-dim" style="font-size:13px;margin-top:3px">AI Content Operating System</div>'
        '</div>', unsafe_allow_html=True)

def _kpi_card(col, icon, label, value, sub=""):
    col.markdown(
        f'<div class="sm-kpi"><div class="ic">{icon}</div>'
        f'<div class="lab">{label}</div><div class="val">{value}</div>'
        f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)

def _list_sites_safe():
    """site_wizard.list_sites 안전 호출(읽기 전용). 실패 시 빈 목록."""
    try:
        from modules import site_wizard as SW
        return SW.list_sites(cfg) or []
    except Exception:
        return []

def _derive_platforms(has_calc: bool):
    """현재 설정 기준 활성 Platform 파생(읽기 전용 표시용)."""
    p = []
    if cfg.get("RUN_MODE") == "wordpress" or cfg.get("WORDPRESS_URL"):
        p.append("WordPress")
    if has_calc:
        p.append("Calculator")
    return p or ["—"]

def _derive_features():
    """현재 설정 기준 활성 공통 Feature 파생(표시용)."""
    f = ["Scheduler", "AI Assistant", "Cost Manager", "Retry Queue"]
    if cfg.get("TELEGRAM_BOT_TOKEN") and cfg.get("TELEGRAM_CHAT_ID"):
        f.append("Telegram")
    if cfg.get("ENABLE_STRATEGY_ROOM"):
        f.append("Strategy")
    return f

def render_current_site_card():
    """최상단 고정 '현재 Site' 카드 + Site 변경 셀렉터(읽기/세션상태만)."""
    sites = _list_sites_safe()
    with st.container(border=True):
        left, right = st.columns([2.2, 1])
        if sites:
            labels = [(s.get("site_name") or s.get("site_id") or "(이름없음)") for s in sites]
            ids = [s.get("site_id", "") for s in sites]
            cur = st.session_state.get("current_site_id", ids[0])
            idx = ids.index(cur) if cur in ids else 0
            with right:
                pick = st.selectbox("Site 변경", labels, index=idx, key="cur_site_pick")
            sel_i = labels.index(pick)
            st.session_state["current_site_id"] = ids[sel_i]
            site = sites[sel_i]
            name = site.get("site_name") or site.get("site_id") or "CalcMate"
        else:
            st.session_state["current_site_id"] = ""
            site, name = {}, "CalcMate"
            with right:
                st.caption("등록 사이트 없음 — 기본 사이트")
        try:
            has_calc = len(cached_table("calculators")) > 0
        except Exception:
            has_calc = False
        with left:
            st.markdown(f"#### 🏢 현재 Site: **{name}**")
            st.markdown(f"**Platform:** {'  +  '.join(_derive_platforms(has_calc))}")
            st.caption("활성 Feature: " + " / ".join(_derive_features()))

def render_kpi_cards():
    # 1) 시스템 상태 (health_last.json)
    h = _read_health_cache()
    crit = [v for v in h.values() if isinstance(v, dict) and v.get("level") == "CRITICAL"]
    ok_c = sum(1 for v in crit if v.get("status") == "OK")
    sys_val = "정상" if crit and ok_c == len(crit) else ("주의" if crit else "—")
    sys_sub = f"{ok_c}/{len(crit)} OK" if crit else "헬스 미실행"
    # pipeline 상태
    try:
        from modules.pipeline_status import get_pipeline_state
        ps = get_pipeline_state(cfg)
    except Exception:
        ps = {"stages": [], "cost_today": 0}
    stages = ps.get("stages", [])
    running = next((s for s in stages if s.get("status") == "running"), None)
    done = [s for s in stages if s.get("status") == "completed"]
    # 2) 현재 Workflow 단계
    if running:        wf = running.get("name", "-")
    elif ps.get("finished"): wf = "완료"
    elif done:         wf = done[-1].get("name", "-")
    else:              wf = "대기"
    # 3) 현재 AI 작업(활성 모델)
    ai = running.get("model", "-") if running else "대기"
    # 4) 오늘 운영 현황(발행/생성)
    try:
        from modules import scheduler as SCH
        pub = SCH.summarize(SCH.load_schedule(cfg)).get("completed", 0)
    except Exception:
        pub = "—"
    try:
        gen = len(cached_posts())
    except Exception:
        gen = "—"
    # 5) 오늘 AI 비용 (Cost Manager / BudgetTracker)
    try:
        from modules import cost_manager as CM
        cs = CM.status(cfg)
        cost_val, cost_sub = f"${cs['used']:.2f}", f"/ ${cs['limit']} ({cs['pct']:.0f}%)"
    except Exception:
        cost_val, cost_sub = f"${ps.get('cost_today', 0)}", "예산 정보"
    cols = st.columns(5)
    _kpi_card(cols[0], "🩺", "시스템", sys_val, sys_sub)
    _kpi_card(cols[1], "⛓️", "Workflow", wf, "현재 단계")
    _kpi_card(cols[2], "🤖", "AI 작업", ai, "활성 모델")
    _kpi_card(cols[3], "📦", "오늘", f"{pub}건", f"발행 / 생성 {gen}")
    _kpi_card(cols[4], "💰", "AI 비용", cost_val, cost_sub)

def render_pipeline_status():
    # 라이브 단계 상태(블로그 파이프라인) — pipeline_status.py 기준
    stage_status = {}
    try:
        from modules.pipeline_status import get_pipeline_state
        for s in get_pipeline_state(cfg)["stages"]:
            stage_status[s["name"]] = s["status"]
    except Exception:
        pass
    def _stat(keys):
        for nm, stt in stage_status.items():
            if any(k in nm for k in keys):
                return stt
        return "pending"
    cls = {"completed": "done", "running": "run", "error": "run", "pending": ""}
    # main.py STEP 순서 기준(추측 아님): 수집→정제→중복→전략→SEO→작성→검수→이미지→발행→기록
    blog = [("📥", "수집", ["수집"]), ("🧹", "정제", ["정제", "표준"]),
            ("🔁", "중복검사", ["중복", "유사"]), ("🧠", "전략", ["전략", "리서치"]),
            ("🔎", "SEO기획", ["SEO", "기획", "리서치"]), ("✍", "작성", ["작성"]),
            ("🔍", "검수", ["검수"]), ("🖼", "이미지", ["이미지"]),
            ("🚀", "발행", ["발행"]), ("🗂", "기록", ["기록", "DB"])]
    calc = [("🔑", "키워드", []), ("🔎", "SEO", []), ("❓", "FAQ", []),
            ("📝", "본문", []), ("🤖", "Reviewer", []), ("🧩", "HTML", []), ("🌐", "배포", [])]
    def _row(title, steps, live):
        cards = "".join(
            f'<div class="sm-step {cls.get(_stat(keys), "") if live else ""}">'
            f'<div class="s-ic">{ic}</div><div class="s-nm">{nm}</div></div>'
            for ic, nm, keys in steps)
        return f'<h4 style="margin:8px 0 8px;font-size:13px" class="sm-dim">{title}</h4><div class="sm-pipe">{cards}</div>'
    st.markdown(
        '<div class="sm-card"><h3 style="margin:0 0 8px">⛓️ Workflow</h3>'
        + _row("📰 블로그 파이프라인 (현재 단계 강조)", blog, True)
        + _row("🧮 계산기 파이프라인", calc, False)
        + '</div>', unsafe_allow_html=True)

def _resolve_run_site():
    """선택된 Site와 활성 platforms 반환. (site|None, platforms[list])"""
    site, platforms = None, []
    try:
        _sid = st.session_state.get("current_site_id", "")
        for s in (cached_table("sites") or []):
            if s.get("site_id") == _sid:
                site = s; break
    except Exception:
        site = None
    if site:
        try:
            platforms = json.loads(site.get("platforms") or "[]")
        except Exception:
            platforms = []
    return site, platforms

def render_quick_actions():
    import main as PIPE
    def _run_blog():
        return PIPE.run_once(cfg)
    def _run_calc():
        from modules.calculator_pipeline import run_calculator_once
        return run_calculator_once(cfg, max_count=1)
    def _run_seq():
        _run_calc(); _run_blog(); return "계산기→블로그 순차 완료"

    with st.container(border=True):
        st.markdown("**⚡ 실행**")
        site, platforms = _resolve_run_site()
        has_wp, has_calc = ("WordPress" in platforms), ("Calculator" in platforms)
        sname = site.get("site_name") if site else "기본(CalcMate)"
        if not platforms:
            st.caption(f"대상: **{sname}** · Platform 미설정 → 기본 블로그 파이프라인 실행")
        else:
            st.caption(f"대상: **{sname}** · Platform: {' + '.join(platforms)}")
        # 둘 다 활성 시 실행 방식 선택
        order = None
        if has_wp and has_calc:
            order = st.radio("실행 방식", ["순차(Calculator→WordPress)", "Calculator만", "WordPress만"],
                             key="qa_order", horizontal=True)
        # ── 통합 실행 버튼: 활성 Platform 기반 Pipeline 자동 결정 ──
        if st.button("▶ 실행", type="primary", use_container_width=True, key="qa_run"):
            if has_wp and has_calc:
                if order == "Calculator만":
                    _run_action("계산기 실행", _run_calc)
                elif order == "WordPress만":
                    _run_action("블로그 파이프라인 실행", _run_blog)
                else:
                    _run_action("순차 실행(Calc→WP)", _run_seq)
            elif has_calc:
                _run_action("계산기 실행", _run_calc)
            else:
                _run_action("블로그 파이프라인 실행", _run_blog)  # WP-only 또는 미설정 fallback
            st.rerun()
        # ── 고급 실행(수동) — 기존 개별 버튼 보존 ──
        with st.expander("🔧 고급 실행(수동)"):
            if st.button("▶ 파이프라인 실행(전량)", use_container_width=True, key="qa_pipe"):
                _run_action("파이프라인 실행", lambda: PIPE.run_once(cfg)); st.rerun()
            if st.button("🧮 계산기 생성", use_container_width=True, key="qa_calc"):
                from modules.calculator_pipeline import run_calculator_once
                _run_action("계산기 글 생성", lambda: run_calculator_once(cfg, max_count=1)); st.rerun()
            if st.button("📝 글 생성(1건)", use_container_width=True, key="qa_post"):
                _run_action("글 생성(1건)", lambda: PIPE.run_once(cfg, max_count=1)); st.rerun()

def render_recent_activity():
    with st.container(border=True):
        st.markdown("**🕒 Recent Activity**")
        lines = _tail_lines("data/logs/pipeline.log", 20)[::-1]
        if lines:
            st.code("\n".join(lines), language="text")
        else:
            st.caption("No Activity")

def render_progress():
    """진행 현황: 오늘 일정 진행률 + Retry/실패/진행중/ETA (읽기 전용)."""
    try:
        from modules import scheduler as SCH
        sm = SCH.summarize(SCH.load_schedule(cfg))
    except Exception:
        sm = {}
    try:
        from modules.retry_queue import list_pending
        retry_n = len(list_pending())
    except Exception:
        retry_n = "—"
    total = sm.get("total", 0) or 0
    comp = sm.get("completed", 0) or 0
    pct = int(comp / total * 100) if total else 0
    with st.container(border=True):
        st.markdown("**📈 진행 현황**")
        st.progress((pct / 100) if total else 0.0, text=f"오늘 일정 {comp}/{total} ({pct}%)")
        m = st.columns(4)
        m[0].metric("Retry 대기", retry_n)
        m[1].metric("실패", sm.get("failed", 0))
        m[2].metric("진행중", sm.get("running", 0))
        m[3].metric("다음 발행(ETA)", sm.get("next") or "-")

def render_dashboard_home():
    a = st.session_state.pop("_last_action", None)
    if a:
        (st.success if a[0] else st.error)(a[1])
    render_header()
    render_current_site_card()        # 최상단 고정 '현재 Site' 카드 + 셀렉터
    render_kpi_cards()                # 운영 현황 5카드
    st.markdown("<br>", unsafe_allow_html=True)
    render_pipeline_status()          # 블로그 + 계산기 Workflow
    st.markdown("<br>", unsafe_allow_html=True)
    render_progress()                 # 진행 현황 패널
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1.5])
    with c1:
        render_quick_actions()
    with c2:
        render_recent_activity()

if tab == "🏠 운영센터":
    render_dashboard_home()

elif tab == "📋 작업 보드":
    st.title("📋 작업 현황 보드")
    st.caption("마스터_DB 상태값 기준 칸반. (수집중→작성중→검수중→발행대기→발행완료 / 오류)")
    try:
        posts = cached_posts()
    except Exception as e:
        posts = []
        st.error(f"데이터 로드 실패(시트 권한 확인): {e}")
    KANBAN = [
        ("🟡 수집중", ["대기", "진행중"]),
        ("🔵 작성중", ["작성중"]),
        ("🟠 검수중", ["검수대기"]),
        ("⏳ 발행대기", ["보류", "복구대기", "재처리대기"]),
        ("🟢 발행완료", ["발행완료"]),
        ("🔴 오류", ["작성오류", "이미지오류", "발행실패", "만료"]),
    ]
    cols = st.columns(len(KANBAN))
    for col, (title, states) in zip(cols, KANBAN):
        items = [p for p in posts if p.get("상태값") in states]
        col.markdown(f"**{title}**")
        col.metric("건수", len(items))
        for p in items[:15]:
            t = str(p.get("최종추천제목") or p.get("정책명") or "(제목없음)")
            col.caption("• " + (t[:22] + ("…" if len(t) > 22 else "")))

# ══════════════════════════════════════════════════════════════
# 백그라운드 탭 로직 (현황, 목록, 오류, 비용)
# ══════════════════════════════════════════════════════════════
elif tab == "📊 현황":
    st.title("📊 실시간 상태 현황")
    try:
        posts = cached_posts()
        status_counts = {}
        for p in posts:
            s = p.get("상태값", "알 수 없음")
            status_counts[s] = status_counts.get(s, 0) + 1

        cols = st.columns(6)
        state_map = [("대기", "🟡"), ("작성중", "🔵"), ("검수대기", "🟠"), ("발행완료", "🟢"), ("이미지오류", "🔴"), ("재처리대기", "⚫")]
        for i, (state, icon) in enumerate(state_map):
            cols[i].metric(f"{icon} {state}", status_counts.get(state, 0))

        st.divider()
        daily_goal = cfg.get("DAILY_POST_COUNT", 3)
        today_str = date.today().isoformat()
        today_published = sum(1 for p in posts if p.get("상태값") in ("발행완료", "검수대기") and str(p.get("발행일시", "")).startswith(today_str))
        st.subheader(f"오늘 발행: {today_published}/{daily_goal}")
        st.progress(min(today_published / max(daily_goal, 1), 1.0))
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")

elif tab == "📋 발행 목록":
    st.title("📋 최근 발행 목록")
    # WordPress REST API 직접 호출 금지 — 수정은 publisher.update_post()만 사용(계층 분리).
    from modules import publisher as PUB
    from repositories.article_repository import ArticleRepository
    from adapters.db.factory import get_db_adapter
    # TODO(본문 편집 UI): 현재 WP 본문을 불러와 미리보기→수정→저장하는 흐름 +
    # 긴 본문 가독성 개선(리치 에디터/높이 조절). 이번 범위 제외.
    try:
        posts = cached_posts()
        published = [p for p in posts if p.get("상태값") in ("발행완료", "검수대기", "수정됨")]
        published.sort(key=lambda x: x.get("발행일시", ""), reverse=True)
        for p in published[:20]:
            pid = p.get("ID", "")
            wp_id = str(p.get("wp_post_id", "") or "").strip()
            with st.expander(f"✅ {p.get('최종추천제목','(제목없음)')} — {p.get('발행일시','')}"):
                st.write(f"**URL:** {p.get('발행 URL', '')}")
                st.write(f"**상태:** {p.get('상태값')}")
                if not wp_id:
                    st.caption("✏️ 수정 기능 미지원 (wp_post_id 없음 — 1차 이전 발행 글)")
                else:
                    with st.expander("✏️ 수정"):
                        e_title = st.text_input("제목", value=p.get("최종추천제목", ""), key=f"ed_t_{pid}")
                        e_excerpt = st.text_input("요약(excerpt)", value=p.get("메타설명", ""), key=f"ed_e_{pid}")
                        e_content = st.text_area(
                            "본문 교체", value="", key=f"ed_c_{pid}",
                            help="입력하면 WordPress 본문 전체를 이 내용으로 교체. 비워두면 본문은 수정하지 않음(전송 안 함).")
                        if st.button("💾 저장 (WordPress 반영)", key=f"ed_save_{pid}"):
                            # content: 비워두면 None(미전송=본문 유지). excerpt/title은 현재값 그대로 전송.
                            content_arg = e_content if e_content.strip() else None
                            res = PUB.update_post(cfg, wp_id, title=e_title,
                                                  content=content_arg, excerpt=e_excerpt)
                            if res.get("success"):
                                # WordPress 성공 후에만 로컬 DB/history 갱신
                                art_repo = ArticleRepository(get_db_adapter(cfg))
                                try:
                                    art_repo.update_status(pid, "수정됨")
                                    art_repo.append_history(pid, "update", {
                                        "wp_post_id": res.get("wp_post_id", ""),
                                        "modified": res.get("modified", ""),
                                        "operator": "dashboard"})
                                except Exception as _e:
                                    st.warning(f"WordPress 수정은 성공했으나 로컬 기록 일부 실패: {_e}")
                                st.success(f"수정 완료 — modified={res.get('modified','')}")
                                st.rerun()
                            else:
                                # 실패 시 로컬 DB/history 절대 미변경
                                st.error(f"수정 실패 (로컬 미변경): {res.get('error','')}")

                    # 🗑️ 삭제(휴지통 이동) — 2단계 확인. publisher만 호출, WP REST 직접호출 없음.
                    st.markdown("---")
                    if not st.session_state.get(f"del_confirm_{pid}"):
                        if st.button("🗑️ 삭제 (휴지통 이동)", key=f"del_btn_{pid}"):
                            # 확인 단계 진입 전 get_post 재조회(이미 삭제/권한/제목 확인)
                            check = PUB.get_post(cfg, wp_id)
                            if check.get("success"):
                                st.session_state[f"del_confirm_{pid}"] = True
                                st.session_state[f"del_check_{pid}"] = check
                                st.rerun()
                            else:
                                err = check.get("error", "")
                                msg = {
                                    "not_found": "이미 삭제되었거나 존재하지 않는 글입니다.",
                                    "authentication_failed": "WordPress 인증 실패 — 자격증명을 확인하세요.",
                                    "permission_denied": "WordPress 권한 부족 — 삭제 권한이 없습니다.",
                                }.get(err, f"조회 실패: {err}")
                                st.error(msg)  # 확인 단계 취소, 로컬 미변경
                    else:
                        check = st.session_state.get(f"del_check_{pid}", {})
                        st.warning("⚠️ 이 글을 WordPress 휴지통으로 이동합니다.")
                        st.write(f"- **제목:** {check.get('title','')}")
                        st.write(f"- **URL:** {check.get('link','')}")
                        st.write(f"- **WP 상태:** {check.get('status','')}")
                        conf = st.text_input('삭제하려면 "DELETE" 를 입력하세요', key=f"del_txt_{pid}")
                        dc = st.columns(2)
                        if dc[0].button("실행", key=f"del_exec_{pid}", type="primary",
                                        disabled=(conf != "DELETE")):
                            res = PUB.delete_post(cfg, wp_id)  # force=False → 휴지통
                            if res.get("success"):
                                art_repo = ArticleRepository(get_db_adapter(cfg))
                                try:
                                    art_repo.update_status(pid, "휴지통")
                                    art_repo.append_history(pid, "trash", {
                                        "wp_post_id": wp_id,
                                        "title": check.get("title", ""),
                                        "operator": "dashboard",
                                        "wp_status": res.get("wp_status", ""),
                                        "force": False})
                                except Exception as _e:
                                    st.warning(f"WordPress 삭제는 성공했으나 로컬 기록 일부 실패: {_e}")
                                st.session_state.pop(f"del_confirm_{pid}", None)
                                st.session_state.pop(f"del_check_{pid}", None)
                                st.success("🗑️ 휴지통으로 이동 완료")
                                st.rerun()
                            else:
                                # 실패 시 로컬 DB/history 절대 미변경
                                st.error(f"삭제 실패 (로컬 미변경): {res.get('error','')}")
                        if dc[1].button("취소", key=f"del_cancel_{pid}"):
                            st.session_state.pop(f"del_confirm_{pid}", None)
                            st.session_state.pop(f"del_check_{pid}", None)
                            st.rerun()
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")

elif tab == "🗑️ 휴지통":
    st.title("🗑️ 휴지통")
    st.caption("WordPress 휴지통(trash)으로 이동된 글. ♻️ 복원하면 발행(publish)으로 되돌립니다.")
    # WP REST 직접호출 금지 — 복원은 publisher.restore_post()만 사용(계층 분리).
    from modules import publisher as PUB
    from repositories.article_repository import ArticleRepository
    from adapters.db.factory import get_db_adapter
    try:
        posts = cached_posts()
        trashed = [p for p in posts if p.get("상태값") == "휴지통"]
        trashed.sort(key=lambda x: x.get("발행일시", ""), reverse=True)
        if not trashed:
            st.info("휴지통이 비어 있습니다.")
        for p in trashed[:30]:
            pid = p.get("ID", "")
            wp_id = str(p.get("wp_post_id", "") or "").strip()
            with st.expander(f"🗑️ {p.get('최종추천제목','(제목없음)')} — {p.get('발행일시','')}"):
                st.write(f"**URL:** {p.get('발행 URL', '')}")
                st.write(f"**로컬 상태:** {p.get('상태값')}")
                if not wp_id:
                    st.caption("♻️ 복원 미지원 (wp_post_id 없음)")
                elif st.button("♻️ 복원", key=f"restore_btn_{pid}"):
                    result = PUB.restore_post(cfg, wp_id)   # 내부 get_post 재조회 포함
                    if result.get("success"):
                        # already_restored여도 로컬이 발행완료가 아니면 동기화(WP-로컬 불일치 해소)
                        if result.get("already_restored") and p.get("상태값") == "발행완료":
                            st.info("이미 복원되어 있습니다.")
                        else:
                            art_repo = ArticleRepository(get_db_adapter(cfg))
                            try:
                                art_repo.update_status(pid, "발행완료")
                                art_repo.append_history(pid, "restore", {
                                    "wp_post_id": wp_id,
                                    "title": result.get("title", ""),
                                    "operator": "dashboard",
                                    "wp_status": result.get("wp_status", ""),
                                    "restored_from": "휴지통",
                                    "already_restored": bool(result.get("already_restored")),
                                })
                            except Exception as _e:
                                st.warning(f"WordPress 복원은 성공했으나 로컬 기록 일부 실패: {_e}")
                            st.success("♻️ 복원되었습니다" +
                                       (" (WP는 이미 발행 상태였음 — 로컬 동기화)" if result.get("already_restored") else ""))
                        st.rerun()
                    else:
                        # 실패 시 로컬 미변경
                        error_map = {
                            "not_found": "WP에서 글을 찾을 수 없습니다.",
                            "authentication_failed": "WordPress 인증 실패입니다.",
                            "permission_denied": "WordPress 권한이 부족합니다.",
                        }
                        err = result.get("error", "")
                        st.error(error_map.get(err, f"복원 실패 (로컬 미변경): {err}"))
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")

elif tab == "⚠️ 오류 로그":
    st.title("⚠️ 최근 오류 로그")
    st.caption("운영로그(logs) 실패 + 계산기(articles) 품질보류/REWRITE를 함께 조회합니다.")
    try:
        rows = cached_table("logs")
        # 가동결과에 '오류' 포함되거나 실패모듈이 있는 행
        errors = [r for r in rows
                  if "오류" in str(r.get("가동결과", "")) or str(r.get("실패모듈", "")).strip()]
        errors = errors[-20:][::-1]  # 최근 20건, 최신 우선

        # 계산기 파이프라인 실패는 logs가 아닌 articles에 기록됨 → 함께 표시(표시 전용).
        # 활성 실패 상태는 '품질보류' 하나뿐(REWRITE/legal 미검증 홀드 모두 이 상태값). quality_status는
        # 발행완료·재처리완료·삭제됨 행에도 'REWRITE'가 잔존해 오탐하므로, 상태값으로만 판정한다.
        def _is_calc_fail(r):
            return str(r.get("상태값", "")).strip() == "품질보류"
        try:
            calc_fails = [r for r in cached_table("articles") if _is_calc_fail(r)][-20:][::-1]
        except Exception:
            calc_fails = []

        st.metric("최근 오류 건수", len(errors) + len(calc_fails))
        import pandas as pd

        st.subheader("운영로그(logs) 오류")
        if errors:
            cols = ["실행일시", "마스터ID", "대상정책명", "실패모듈", "오류내용"]
            df = pd.DataFrame(errors)
            show = [c for c in cols if c in df.columns]
            st.dataframe(df[show] if show else df, use_container_width=True)
        else:
            st.caption("운영로그 오류 없음")

        st.subheader("계산기 품질보류 / REWRITE (articles)")
        if calc_fails:
            cols = ["발행일시", "최종추천제목", "정책명", "상태값", "quality_status", "quality_failed_rules"]
            df = pd.DataFrame(calc_fails)
            show = [c for c in cols if c in df.columns]
            st.dataframe(df[show] if show else df, use_container_width=True)
        else:
            st.caption("계산기 품질보류 없음")

        if not errors and not calc_fails:
            st.success("최근 오류 없음 ✅")
    except Exception as e:
        st.error(f"로그 로드 오류: {e}")
        st.caption("Google Sheet 권한(서비스 계정 공유) 또는 네트워크를 확인하세요.")

elif tab == "💰 비용 모니터":
    st.title("💰 AI 사용 비용 모니터")
    st.caption("data/logs/budget.json 기반 — 실제 호출 시 누적 기록됩니다.")
    try:
        from modules.logger import BudgetTracker
        bt = BudgetTracker(cfg)
        bs = bt.check_budget()

        c1, c2, c3 = st.columns(3)
        c1.metric("오늘 비용", f"${bs['daily_used']:.4f}", f"한도 ${bs['daily_limit']}")
        c2.metric("이번달 비용", f"${bs['monthly_used']:.4f}", f"한도 ${bs['monthly_limit']}")
        c3.metric("누적 비용(전체월)", f"${bt.get_total_cost():.4f}")
        # 예산 진행률
        st.progress(min(bs['daily_used'] / max(bs['daily_limit'], 0.0001), 1.0),
                    text=f"일 예산 사용률 {bs['daily_used']/max(bs['daily_limit'],0.0001)*100:.1f}%")
        if bs["daily_exceeded"]:
            st.error("⛔ 일 예산 초과 — 파이프라인이 자동 중단됩니다.")
        if bs["monthly_exceeded"]:
            st.error("⛔ 월 예산 초과 — 파이프라인이 자동 중단됩니다.")

        st.divider()
        colA, colB = st.columns(2)
        with colA:
            st.subheader("Provider별 (이번달)")
            prov = bt.get_provider_breakdown("monthly")
            prov = {k: v for k, v in prov.items() if v}
            if prov:
                import pandas as pd
                st.bar_chart(pd.Series(prov, name="USD"))
                st.dataframe(pd.DataFrame(
                    [{"Provider": k, "비용($)": v} for k, v in prov.items()]),
                    use_container_width=True, hide_index=True)
            else:
                st.caption("이번달 집계 없음")
        with colB:
            st.subheader("모델별 (이번달)")
            models = bt.get_model_breakdown("monthly")
            if models:
                import pandas as pd
                st.dataframe(pd.DataFrame(
                    [{"모델": k, "비용($)": v} for k, v in sorted(models.items(), key=lambda x: -x[1])]),
                    use_container_width=True, hide_index=True)
            else:
                st.caption("이번달 집계 없음")

        st.divider()
        t1, t2 = st.columns(2)
        t1.metric("오늘 토큰", f"{int(bt.get_today_tokens()):,}")
        st.caption("※ 비용은 모델별 입력/출력 단가표 기반 추정치입니다(blended 적용 구간 존재).")
    except Exception as e:
        st.error(f"비용 데이터 로드 오류: {e}")

    st.divider()
    # ── Cost Manager (80% 경고 / 100% 자동 일시정지 / 익일 재개) ──
    st.subheader("🛡️ Cost Manager")
    try:
        from modules import cost_manager as CM
        cs = CM.status(cfg)
        paused = CM.is_paused(cfg)
        cc = st.columns(3)
        cc[0].metric("일 예산 사용률", f"{cs['pct']:.0f}%")
        cc[1].metric("상태", "⛔ 일시정지" if paused else "🟢 정상")
        cc[2].metric("정책", "80%경고 / 100%정지")
        if paused:
            st.error("일 예산 한도 도달로 자동 일시정지됨(익일 자동 재개).")
            if st.button("▶ 지금 수동 재개", key="cm_resume"):
                CM.resume(cfg); st.success("재개됨"); st.rerun()
    except Exception as e:
        st.caption(f"Cost Manager 로드 실패: {e}")

    st.divider()
    # ── Retry Queue (WordPress 발행 실패분 재발행) ──
    st.subheader("🔁 발행 재시도 큐")
    try:
        from modules import retry_queue as RQ
        pend = RQ.list_pending()
        if not pend:
            st.caption("재발행 대기 없음")
        for it in pend[:20]:
            with st.container(border=True):
                st.markdown(f"**{it['seo'].get('seo_title','(제목없음)')}** · "
                            f"<span class='sm-dim'>{it.get('created_at','')[:16]} · {it.get('error','')[:60]}</span>",
                            unsafe_allow_html=True)
                rc = st.columns(2)
                if rc[0].button("🔁 재발행", key=f"rq_{it['id']}"):
                    ok, msg = RQ.retry(cfg, it["id"])
                    (st.success if ok else st.error)(msg); st.rerun()
                if rc[1].button("🗑 제거", key=f"rqd_{it['id']}"):
                    RQ.remove(it["id"]); st.rerun()
    except Exception as e:
        st.caption(f"Retry Queue 로드 실패: {e}")

# ══════════════════════════════════════════════════════════════
# 탭: 📝 Blog Schedule (Golden 10 블로그 자동 발행 + Content Sync)
# ══════════════════════════════════════════════════════════════
elif tab == "📝 Blog Schedule":
    st.title("📝 Blog Schedule")
    from modules import scheduler as SCH
    from datetime import datetime as _dt
    import threading as _th

    def _parse_t(s, fallback="09:00"):
        try:
            return _dt.strptime(s, "%H:%M").time()
        except Exception:
            return _dt.strptime(fallback, "%H:%M").time()

    # ── Content Sync 수동 트리거 (WordPress ↔ Sheets 상태 동기화) ──
    # run_sync_once 100% 재사용. content_sync.lock으로 자동 03:00 실행과 상호배제.
    with st.expander("🔄 Content Sync (WordPress ↔ Sheets 상태 동기화 · 자동 03:00 + 수동)"):
        st.caption("발행글의 WP 상태를 조회해 시트 sync_flag 갱신(WP_DELETED/URL_CHANGED/ORPHAN). "
                   "매일 03:00 자동 실행 + 여기서 즉시 수동 실행.")
        _scm = st.radio("범위", ["recent", "full"], horizontal=True, key="sync_mode",
                        help="recent=최근 30일 발행분 / full=전체 스캔")
        if st.button("🔄 Sync Now", key="sync_now", type="primary"):
            from modules import content_sync as CS
            import time as _time
            if not CS._acquire_lock(cfg):
                st.warning("다른 동기화가 진행 중입니다(자동 03:00 또는 다른 창). 잠시 후 재시도하세요.")
            else:
                res = None
                try:
                    _t0 = _time.time()
                    with st.spinner("WordPress ↔ Sheets 동기화 중..."):
                        res = CS.run_sync_once(cfg, mode=_scm)
                    _el = round(_time.time() - _t0, 1)
                finally:
                    CS._release_lock(cfg)
                if not res or not res.get("ok"):
                    st.warning(f"동기화 미실행: {(res or {}).get('reason','?')} (WordPress 미구성 등)")
                else:
                    from collections import Counter as _Ctr
                    _fc = _Ctr(a.get("flag") for a in res.get("anomalies", []))
                    st.success(f"✅ 동기화 완료 · 검사 {res['checked']}건 / 변경 {res['changed']}건 / {_el}초")
                    st.write("이상: WP_DELETED %d · URL_CHANGED %d · ORPHAN_WP %d · ORPHAN_SHEET %d" % (
                        _fc.get("WP_DELETED",0), _fc.get("URL_CHANGED",0),
                        _fc.get("ORPHAN_WP",0), _fc.get("ORPHAN_SHEET",0)))
                    for a in res.get("anomalies", [])[:10]:
                        st.write(f"- {a.get('flag')} · {a.get('name','')} (post_id={a.get('post_id','-')})")

    # ── Blog Schedule 설정 (Golden 10 블로그 자동 발행) ──
    st.divider()
    st.subheader("📝 Blog Schedule (Golden 10 블로그 자동 발행)")

    bs = dict(cfg.get("BLOG_SCHEDULE", {}) or {})
    _blog_enabled = bool(bs.get("enabled", False))
    _blog_alive = any(t.name == "blog-scheduler-loop" and t.is_alive() for t in _th.enumerate())
    _blog_running = _blog_alive and _blog_enabled

    with st.container(border=True):
        b1, b2, b3 = st.columns(3)
        b1.markdown("**Blog 상태**: " + ("🟢 Running" if _blog_running else "🔴 정지"))
        b2.markdown(f"**enabled**: {'on' if _blog_enabled else 'off'} · 스레드 {'live' if _blog_alive else 'dead'}")
        b3.markdown(f"**mode**: `{bs.get('mode', 'draft')}`")

    blog_enabled = st.toggle("Blog 스케줄러 사용(enabled)", value=_blog_enabled, key="blog_enabled")
    blog_mode = st.selectbox(
        "Blog 발행 모드", ["draft", "publish"],
        index=0 if bs.get("mode", "draft") == "draft" else 1,
        format_func=lambda m: {"draft": "Dry-Run (WP 미호출)", "publish": "Publish (WP 즉시 발행)"}.get(m, m),
        key="blog_mode")
    blog_weekday_only = st.checkbox("평일만 발행 (weekday_only)", value=bs.get("weekday_only", False), key="blog_wd_only")

    # publish_slots 편집
    existing_slots = bs.get("publish_slots") or []
    if not existing_slots:
        existing_slots = [{"start": "10:00", "end": "10:30"}]
    blog_slot_count = st.number_input(
        "Blog 하루 발행 슬롯 수", 1, 10, len(existing_slots), key="blog_slot_count")

    blog_slots = []
    for i in range(int(blog_slot_count)):
        cur = existing_slots[i] if i < len(existing_slots) else {"start": "10:00", "end": "10:30"}
        c1, c2 = st.columns(2)
        bs_s = c1.time_input(
            f"Blog 슬롯 {i+1} 시작", value=_parse_t(cur.get("start", "10:00")),
            key=f"blog_slot_s_{i}", step=300)
        bs_e = c2.time_input(
            f"Blog 슬롯 {i+1} 종료", value=_parse_t(cur.get("end", "10:30")),
            key=f"blog_slot_e_{i}", step=300)
        blog_slots.append({"start": bs_s.strftime("%H:%M"), "end": bs_e.strftime("%H:%M")})

    if st.button("💾 Blog 설정 저장", type="primary", key="blog_save"):
        cfg_path = BASE / "config" / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw["BLOG_SCHEDULE"] = {
            "enabled": bool(blog_enabled),
            "mode": blog_mode,
            "publish_slots": blog_slots,
            "weekday_only": bool(blog_weekday_only),
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        load_cfg.clear()
        cfg = load_cfg()
        st.success(f"✅ Blog 설정 저장 완료 · enabled={blog_enabled} · slots={len(blog_slots)}개")
        st.rerun()

    st.caption("⚠️ Blog 스케줄러 ON/OFF 변경은 Dashboard 재시작 후 적용됩니다.")

# ══════════════════════════════════════════════════════════════
# 탭: 🌐 사이트 관리 (사이트/계산기 생성 마법사 + 관리)
# ══════════════════════════════════════════════════════════════
elif tab == "🌐 사이트 관리":
    st.title("🌐 사이트 관리")
    from modules import site_wizard as SW
    import json as _json
    AI_PROFILES = ["gemini_flash", "gemini_pro", "gpt4o", "gpt4o_mini",
                   "claude_sonnet", "claude_haiku", "claude_opus"]

    # ── 현재 Site 헤더 + 셀렉터 (작업4 세션 공유) ──
    try:
        _sm_sites = SW.list_sites(cfg) or []
    except Exception:
        _sm_sites = []
    if _sm_sites:
        _ids = [s.get("site_id", "") for s in _sm_sites]
        _labels = [(s.get("site_name") or s.get("site_id") or "(이름없음)") for s in _sm_sites]
        _cur = st.session_state.get("current_site_id", _ids[0])
        _idx = _ids.index(_cur) if _cur in _ids else 0
        hc1, hc2 = st.columns([2, 1])
        with hc2:
            _pick = st.selectbox("현재 Site", _labels, index=_idx, key="sm_cur_pick")
        st.session_state["current_site_id"] = _ids[_labels.index(_pick)]
        hc1.info(f"현재 선택: **{_pick}**")
    else:
        st.caption("등록된 사이트 없음 — 기본 사이트(CalcMate). 아래에서 새 사이트를 추가하세요.")

    # ── ⬇️⬆️ Export / Import (메타데이터만 · 자격증명 제외) ──
    with st.expander("⬇️⬆️ Export / Import"):
        ec1, ec2 = st.columns(2)
        with ec1:
            st.download_button(
                "⬇️ 사이트 Export(JSON)",
                data=_json.dumps(_sm_sites, ensure_ascii=False, indent=2),
                file_name="sites_export.json", mime="application/json", key="sm_export")
            st.caption("WP 자격증명/시크릿은 포함되지 않습니다.")
        with ec2:
            up = st.file_uploader("⬆️ Import(JSON) — 검증 경유 신규 등록만", type=["json"], key="sm_import")
            if up is not None and st.button("Import 실행", key="sm_import_run"):
                try:
                    rows = _json.loads(up.read()); assert isinstance(rows, list)
                except Exception as e:
                    rows = None; st.error(f"JSON 파싱 실패: {e}")
                if rows:
                    okc, errs = 0, []
                    for r in rows:
                        stype = r.get("site_type", "custom")
                        label = next((k for k, v in SW.TYPE_DEFS.items() if v["site_type"] == stype), "사용자정의")
                        ok, msg = SW.create_site(cfg, label, {
                            "site_name": r.get("site_name", ""), "domain": r.get("domain", ""),
                            "category": r.get("site_tags", ""),
                            "wp_url": r.get("wordpress_url", ""), "wp_user": "", "wp_app_password": "",
                            "rss_sources": "",
                        })
                        okc += 1 if ok else 0
                        if not ok: errs.append(msg)
                    st.success(f"Import: {okc}건 등록 (WP 유형은 자격증명 필요 시 실패할 수 있음)")
                    for e in errs[:8]:
                        st.warning(e)
                    if okc:
                        st.cache_resource.clear(); st.rerun()

    # ── ⚙️ Site Settings (Global → Override) · 현재 선택 Site 대상 ──
    with st.expander("⚙️ Site Settings (Override)"):
        _cur_id = st.session_state.get("current_site_id", "")
        _site = next((s for s in _sm_sites if s.get("site_id") == _cur_id),
                     (_sm_sites[0] if _sm_sites else None))
        if not _site:
            st.caption("선택된 Site가 없습니다. 먼저 사이트를 추가하세요.")
        else:
            GLOB = "(Global 기본값)"
            st.caption(f"대상: **{_site.get('site_name','-')}** ({_site.get('site_id','')}) · "
                       "빈 값=Global 상속, 값 있으면 🔵 Override")
            def _ai_box(col, label, gdef, colobj):
                cur = _site.get(col, "")
                opts = [GLOB] + AI_PROFILES
                idx = opts.index(cur) if cur in AI_PROFILES else 0
                v = colobj.selectbox(label + (" 🔵" if cur in AI_PROFILES else ""),
                                     opts, index=idx, key=f"ss_{col}")
                colobj.caption(f"Global: {gdef}")
                return "" if v == GLOB else v
            st.markdown("**AI**")
            a1, a2, a3 = st.columns(3)
            o_res = _ai_box("research_ai", "Research AI", SW.DEFAULT_AI["research_ai"], a1)
            o_wri = _ai_box("writing_ai", "Writing AI", SW.DEFAULT_AI["writing_ai"], a2)
            o_rev = _ai_box("review_ai", "Review AI", SW.DEFAULT_AI["review_ai"], a3)

            st.markdown("**WordPress / SEO**")
            w1, w2 = st.columns(2)
            o_wpurl = w1.text_input("WordPress URL" + (" 🔵" if _site.get("wordpress_url") else ""),
                                    value=_site.get("wordpress_url", ""), key="ss_wpurl",
                                    placeholder=cfg.get("WORDPRESS_URL", ""))
            o_cat = w2.text_input("카테고리(site_tags)" + (" 🔵" if _site.get("site_tags") else ""),
                                  value=_site.get("site_tags", ""), key="ss_cat")
            s1, s2 = st.columns(2)
            o_kwc = s1.text_input("SEO 키워드 수" + (" 🔵" if _site.get("seo_keyword_count") else ""),
                                  value=str(_site.get("seo_keyword_count", "")), key="ss_kwc", placeholder="Global 5")
            o_len = s2.text_input("SEO 글 길이" + (" 🔵" if _site.get("seo_length") else ""),
                                  value=str(_site.get("seo_length", "")), key="ss_len", placeholder="Global 1500")

            st.markdown("**Scheduler / Image**")
            sc1, sc2 = st.columns(2)
            o_daily = sc1.text_input("일 발행수" + (" 🔵" if _site.get("daily_override") else ""),
                                     value=str(_site.get("daily_override", "")), key="ss_daily",
                                     placeholder=f"Global {cfg.get('DAILY_POST_COUNT',3)}")
            _img_opts = [GLOB, "free_pollinations", "openai", "none"]
            _imgcur = _site.get("image_mode", "")
            o_img = sc2.selectbox("이미지 생성 방식" + (" 🔵" if _imgcur else ""), _img_opts,
                                  index=_img_opts.index(_imgcur) if _imgcur in _img_opts else 0, key="ss_img")
            sc2.caption(f"Global 이미지: {cfg.get('IMAGE_PROVIDER','free_pollinations')}")

            st.markdown("**Telegram / Analytics**")
            t1, t2 = st.columns(2)
            _onoff = [GLOB, "ON", "OFF"]
            _tgcur = _site.get("telegram_enabled", "")
            o_tg = t1.selectbox("Telegram 알림" + (" 🔵" if _tgcur else ""), _onoff,
                                index=_onoff.index(_tgcur) if _tgcur in _onoff else 0, key="ss_tg")
            _ancur = _site.get("analytics_enabled", "")
            o_an = t2.selectbox("Analytics" + (" 🔵" if _ancur else ""), _onoff,
                                index=_onoff.index(_ancur) if _ancur in _onoff else 0, key="ss_an")

            st.markdown("**Calculator (활성 계산기)**")
            try:
                _allcalc = [c.get("name", "") for c in SW.list_calculators(cfg) if c.get("name")]
            except Exception:
                _allcalc = []
            try:
                _cursel = _json.loads(_site.get("calc_active") or "[]")
            except Exception:
                _cursel = []
            o_calc = st.multiselect("활성 계산기 목록", _allcalc,
                                    default=[c for c in _cursel if c in _allcalc], key="ss_calc")

            st.markdown("**Feature Flags (작업6 설정 — 표시)**")
            st.code(_site.get("features", "{}"), language="json")

            bc1, bc2 = st.columns(2)
            if bc1.button("💾 Override 저장", type="primary", key="ss_save"):
                ok, msg = SW.update_site(cfg, _site.get("site_id", ""), {
                    "research_ai": o_res, "writing_ai": o_wri, "review_ai": o_rev,
                    "wordpress_url": o_wpurl.strip(), "site_tags": o_cat.strip(),
                    "seo_keyword_count": o_kwc.strip(), "seo_length": o_len.strip(),
                    "daily_override": o_daily.strip(),
                    "image_mode": "" if o_img == GLOB else o_img,
                    "telegram_enabled": "" if o_tg == GLOB else o_tg,
                    "analytics_enabled": "" if o_an == GLOB else o_an,
                    "calc_active": _json.dumps(o_calc, ensure_ascii=False),
                })
                (st.success if ok else st.error)("Override 저장됨" if ok else msg)
                if ok: st.cache_resource.clear(); st.rerun()
            if bc2.button("↩️ Override 초기화(Global 복귀)", key="ss_reset"):
                # 코어 필드(wordpress_url/site_tags)는 보존, Override 전용 필드만 비움
                ok, msg = SW.update_site(cfg, _site.get("site_id", ""), {k: "" for k in [
                    "research_ai", "writing_ai", "review_ai", "seo_keyword_count", "seo_length",
                    "daily_override", "image_mode", "telegram_enabled", "analytics_enabled", "calc_active"]})
                (st.success if ok else st.error)("Global 기본값으로 초기화" if ok else msg)
                if ok: st.cache_resource.clear(); st.rerun()

    # ── 🧙 새 사이트 마법사 (5단계: Profile→Platform→Feature→Settings→Pipeline) ──
    with st.expander("🧙 새 사이트 마법사 (5단계)"):
        WP_FEATS = ["글 작성", "자동 발행", "SEO", "이미지 업로드", "카테고리"]
        CALC_FEATS = ["계산기 생성", "계산기 SEO 글", "FAQ 생성", "AI Reviewer", "HTML 생성"]
        COMMON_FEATS = ["Scheduler", "Telegram", "AI Assistant", "Analytics", "Cost Manager", "Retry Queue"]
        w = st.session_state.setdefault("wiz6", {"step": 1, "data": {}})
        step, d = w["step"], w["data"]
        st.caption(f"진행: {step}/5")

        if step == 1:
            st.markdown("**Step 1 · Site Profile**")
            d["site_name"] = st.text_input("사이트명 *", value=d.get("site_name", ""), key="w6_name")
            d["domain"]    = st.text_input("도메인 *", value=d.get("domain", ""), key="w6_dom")
            d["wp_url"]    = st.text_input("WordPress URL (선택)", value=d.get("wp_url", ""), key="w6_wpurl")
            if st.button("다음 →", key="w6_n1"):
                if d.get("site_name") and d.get("domain"):
                    w["step"] = 2; st.rerun()
                else:
                    st.error("사이트명과 도메인은 필수입니다.")

        elif step == 2:
            st.markdown("**Step 2 · Platform 선택 (독립 복수)**")
            pf = d.get("platforms", [])
            use_wp   = st.checkbox("WordPress", value=("WordPress" in pf), key="w6_pwp")
            use_calc = st.checkbox("Calculator", value=("Calculator" in pf), key="w6_pcalc")
            if use_wp:
                st.caption("WordPress 자격증명 (필수)")
                d["wp_user"] = st.text_input("WordPress ID *", value=d.get("wp_user", ""), key="w6_wpuser")
                d["wp_pw"]   = st.text_input("App Password *", type="password", value=d.get("wp_pw", ""), key="w6_wppw")
            c1, c2 = st.columns(2)
            if c1.button("← 이전", key="w6_b2"): w["step"] = 1; st.rerun()
            if c2.button("다음 →", key="w6_n2"):
                pf = (["WordPress"] if use_wp else []) + (["Calculator"] if use_calc else [])
                d["platforms"] = pf
                if use_wp and not (d.get("wp_url") and d.get("wp_user") and d.get("wp_pw")):
                    st.error("WordPress 선택 시 URL(Step1)/ID/App Password가 필요합니다.")
                else:
                    w["step"] = 3; st.rerun()

        elif step == 3:
            st.markdown("**Step 3 · Feature 선택 (Platform별 + 공통)**")
            pf, sel = d.get("platforms", []), {}
            if "WordPress" in pf:
                st.markdown("*WordPress*")
                sel["wordpress"] = [f for f in WP_FEATS if st.checkbox(f, value=True, key=f"w6_fw_{f}")]
            if "Calculator" in pf:
                st.markdown("*Calculator*")
                sel["calculator"] = [f for f in CALC_FEATS if st.checkbox(f, value=True, key=f"w6_fc_{f}")]
            st.markdown("*공통*")
            sel["common"] = [f for f in COMMON_FEATS if st.checkbox(f, value=True, key=f"w6_fco_{f}")]
            c1, c2 = st.columns(2)
            if c1.button("← 이전", key="w6_b3"): w["step"] = 2; st.rerun()
            if c2.button("다음 →", key="w6_n3"):
                d["features"] = sel; w["step"] = 4; st.rerun()

        elif step == 4:
            st.markdown("**Step 4 · Settings (Global 기본값 → Override)**")
            st.caption("미변경 시 Global 기본값 적용. 상세 항목은 작업7(Site Settings)에서 편집.")
            a1, a2, a3 = st.columns(3)
            d["research_ai"] = a1.selectbox("Research AI", AI_PROFILES,
                index=AI_PROFILES.index(d.get("research_ai", SW.DEFAULT_AI["research_ai"])), key="w6_rai")
            d["writing_ai"] = a2.selectbox("Writing AI", AI_PROFILES,
                index=AI_PROFILES.index(d.get("writing_ai", SW.DEFAULT_AI["writing_ai"])), key="w6_wai")
            d["review_ai"] = a3.selectbox("Review AI", AI_PROFILES,
                index=AI_PROFILES.index(d.get("review_ai", SW.DEFAULT_AI["review_ai"])), key="w6_vai")
            d["daily_override"] = st.number_input("일 발행수 (Override)", 1, 20,
                int(d.get("daily_override", cfg.get("DAILY_POST_COUNT", 3))), key="w6_daily")
            c1, c2 = st.columns(2)
            if c1.button("← 이전", key="w6_b4"): w["step"] = 3; st.rerun()
            if c2.button("다음 →", key="w6_n4"): w["step"] = 5; st.rerun()

        elif step == 5:
            st.markdown("**Step 5 · Pipeline 연결 확인**")
            pf = d.get("platforms", [])
            if "Calculator" in pf and "WordPress" in pf:
                pipe_msg = "이 Site는 **Calculator Pipeline → WordPress 발행** 순서로 실행됩니다."
            elif "Calculator" in pf:
                pipe_msg = "이 Site는 **Calculator Pipeline**으로 실행됩니다."
            elif "WordPress" in pf:
                pipe_msg = "이 Site는 **RSS/정책 Pipeline → WordPress 발행**으로 실행됩니다."
            else:
                pipe_msg = "Platform 미선택 — 나중에 Platform을 추가하면 Pipeline이 결정됩니다."
            st.info(pipe_msg)
            st.json({"profile": {"name": d.get("site_name"), "domain": d.get("domain")},
                     "platforms": pf, "features": d.get("features", {}),
                     "override": {"research_ai": d.get("research_ai"), "writing_ai": d.get("writing_ai"),
                                  "review_ai": d.get("review_ai"), "daily": d.get("daily_override")}})
            c1, c2 = st.columns(2)
            if c1.button("← 이전", key="w6_b5"): w["step"] = 4; st.rerun()
            if c2.button("✅ 사이트 생성", type="primary", key="w6_create"):
                needs_wp = "WordPress" in pf
                label = "사용자정의" if needs_wp else "계산기"
                ok, msg = SW.create_site(cfg, label, {
                    "site_name": d.get("site_name", ""), "domain": d.get("domain", ""), "category": "",
                    "wp_url": d.get("wp_url", ""), "wp_user": d.get("wp_user", ""),
                    "wp_app_password": d.get("wp_pw", ""), "rss_sources": "",
                    "research_ai": d.get("research_ai", ""), "writing_ai": d.get("writing_ai", ""),
                    "review_ai": d.get("review_ai", ""),
                })
                if ok:
                    try:  # platforms/features를 신규 컬럼으로 기록(create_site 무변경)
                        rows = SW.list_sites(cfg)
                        nm = d.get("site_name", "").strip()
                        nr = next((x for x in rows if str(x.get("site_name", "")).strip() == nm), None)
                        if nr:
                            SW.update_site(cfg, nr.get("site_id", ""), {
                                "platforms": _json.dumps(pf, ensure_ascii=False),
                                "features": _json.dumps(d.get("features", {}), ensure_ascii=False),
                                "daily_override": str(d.get("daily_override", "")),
                            })
                    except Exception as e:
                        st.warning(f"platforms/features 기록 경고: {e}")
                    st.success(msg + " · Platform/Feature 저장됨")
                    st.session_state.pop("wiz6", None)
                    st.cache_resource.clear(); st.rerun()
                else:
                    st.error(msg)

    # ── ➕ 사이트 추가 ──
    with st.expander("➕ 사이트 추가", expanded=True):
        type_label = st.selectbox("유형 선택", SW.SITE_TYPES, key="sw_type")
        spec = SW.TYPE_DEFS[type_label]
        st.caption(f"site_type=`{spec['site_type']}` · 수익화=`{spec['monetization']}` · "
                   f"content_mode=`{spec['content_mode']}`"
                   + (" · ⚠️ 수집기 미구현(stub)" if spec['site_type'] in SW.STUB_TYPES else ""))

        if type_label == "계산기":
            c1, c2 = st.columns(2)
            calc_name = c1.text_input("계산기명 *", placeholder="주휴수당 계산기", key="sw_calc_name")
            calc_cat  = c2.text_input("카테고리", placeholder="노무/급여", key="sw_calc_cat")
            calc_desc = st.text_area("설명", placeholder="예: 주휴수당 자동 계산", key="sw_calc_desc")
            st.caption("예시: 주휴수당 계산기 · 퇴직금 계산기 · 대출이자 계산기")
            if st.button("💾 계산기 등록", type="primary", key="sw_calc_save"):
                ok, msg = SW.create_calculator(cfg, {
                    "name": calc_name, "description": calc_desc, "category": calc_cat})
                (st.success if ok else st.error)(msg)
                if ok:
                    st.cache_resource.clear(); st.rerun()
        else:
            c1, c2 = st.columns(2)
            site_name = c1.text_input("사이트명 *", key="sw_name")
            domain    = c2.text_input("도메인 *", placeholder="example.com", key="sw_domain")
            category  = st.text_input("카테고리", placeholder="복지/정책", key="sw_cat")

            wp_url = wp_user = wp_pw = ""
            if spec["needs_wp"]:
                st.markdown("**WordPress 연동**")
                w1, w2 = st.columns(2)
                wp_url  = w1.text_input("WordPress URL *", placeholder="https://yourblog.com", key="sw_wpurl")
                wp_user = w2.text_input("WordPress ID *", placeholder="admin", key="sw_wpuser")
                wp_pw   = st.text_input("App Password *", type="password",
                                        placeholder="xxxx xxxx xxxx xxxx", key="sw_wppw")
            rss = ""
            if spec["uses_rss"]:
                rss = st.text_input("RSS 수집원(콤마 구분, 선택)",
                                    placeholder="https://www.korea.kr/rss/policy.xml", key="sw_rss")

            with st.expander("AI 프로필(선택) — 미선택 시 기본값"):
                a1, a2, a3 = st.columns(3)
                research = a1.selectbox("Research AI", AI_PROFILES,
                                        index=AI_PROFILES.index(SW.DEFAULT_AI["research_ai"]), key="sw_research")
                writing  = a2.selectbox("Writing AI", AI_PROFILES,
                                        index=AI_PROFILES.index(SW.DEFAULT_AI["writing_ai"]), key="sw_writing")
                review   = a3.selectbox("Review AI", AI_PROFILES,
                                        index=AI_PROFILES.index(SW.DEFAULT_AI["review_ai"]), key="sw_review")

            if st.button("💾 사이트 등록", type="primary", key="sw_site_save"):
                ok, msg = SW.create_site(cfg, type_label, {
                    "site_name": site_name, "domain": domain, "category": category,
                    "wp_url": wp_url, "wp_user": wp_user, "wp_app_password": wp_pw,
                    "rss_sources": rss,
                    "research_ai": research, "writing_ai": writing, "review_ai": review,
                })
                (st.success if ok else st.error)(msg)
                if ok:
                    st.cache_resource.clear(); st.rerun()

    st.divider()
    # ── 사이트 목록 / 관리 ──
    st.subheader("📋 등록된 사이트")
    try:
        sites = SW.list_sites(cfg)
    except Exception as e:
        sites = []
        st.error(f"사이트 목록 조회 실패(시트 권한 확인): {e}")
    if not sites:
        st.caption("등록된 사이트 없음")
    for s in sites:
        sid = s.get("site_id", "")
        active = str(s.get("status", "")).lower() == "active"
        icon = "🟢" if active else "⚪"
        with st.expander(f"{icon} {s.get('site_name','(이름없음)')} — {s.get('domain','')} "
                         f"[{s.get('site_type','')}] ({s.get('status','')})"):
            e1, e2 = st.columns(2)
            new_name = e1.text_input("사이트명", value=s.get("site_name", ""), key=f"ed_name_{sid}")
            new_dom  = e2.text_input("도메인", value=s.get("domain", ""), key=f"ed_dom_{sid}")
            new_cat  = st.text_input("카테고리", value=s.get("site_tags", ""), key=f"ed_cat_{sid}")
            from datetime import datetime as _dt, timedelta as _td
            status_l = str(s.get("status", "")).lower()
            archived = status_l == "archived"
            b1, b2, b3 = st.columns(3)
            if b1.button("💾 수정 저장", key=f"ed_save_{sid}"):
                ok, msg = SW.update_site(cfg, sid, {
                    "site_name": new_name, "domain": new_dom, "site_tags": new_cat})
                (st.success if ok else st.error)(msg)
                if ok: st.rerun()
            if not archived:
                toggle_label = "⏸ 비활성화" if active else "▶ 활성화"
                if b2.button(toggle_label, key=f"ed_tog_{sid}"):
                    ok, msg = SW.set_site_status(cfg, sid, "inactive" if active else "active")
                    (st.success if ok else st.error)(msg)
                    if ok: st.rerun()
                if b3.button("🗑️ 삭제(보관 이동)", key=f"ed_arch_{sid}"):
                    ok, msg = SW.update_site(cfg, sid, {
                        "status": "archived", "deleted_at": _dt.now().isoformat()})
                    (st.success if ok else st.error)(
                        "보관함으로 이동됨 — 보관기간 내 복구 가능" if ok else msg)
                    if ok: st.rerun()
            else:
                ret_days = int(cfg.get("SITE_RETENTION_DAYS", 30) or 30)
                da = s.get("deleted_at", "")
                expired, exp_txt = False, "-"
                try:
                    exp = _dt.fromisoformat(da) + _td(days=ret_days)
                    expired = _dt.now() > exp
                    exp_txt = exp.strftime("%Y-%m-%d")
                except Exception:
                    pass
                st.warning(f"📦 보관됨 (삭제예정 {exp_txt}, 보관 {ret_days}일)"
                           + (" · ⚠️ 보관기간 만료 — 영구삭제 가능" if expired else ""))
                if b2.button("♻️ 복구", key=f"ed_restore_{sid}"):
                    ok, msg = SW.update_site(cfg, sid, {"status": "inactive", "deleted_at": ""})
                    (st.success if ok else st.error)("복구됨(비활성 상태)" if ok else msg)
                    if ok: st.rerun()
                with b3:
                    conf = st.text_input('영구삭제: "DELETE" 입력', key=f"ed_delconf_{sid}")
                    if st.button("⛔ 영구 삭제", key=f"ed_perm_{sid}"):
                        if conf.strip() == "DELETE":
                            ok, msg = SW.delete_site(cfg, sid)
                            (st.success if ok else st.error)(msg)
                            if ok: st.rerun()
                        else:
                            st.error('"DELETE"를 정확히 입력해야 합니다.')
            # ── 📑 복제(Clone) — 인라인 프리필 폼 ──
            with st.expander("📑 복제(Clone)"):
                cl_name = st.text_input("새 사이트명 *", value=f"{s.get('site_name','')} (복사본)",
                                        key=f"cl_name_{sid}")
                cl_dom = st.text_input("새 도메인 *", value="", key=f"cl_dom_{sid}")
                spec_lbl = next((k for k, v in SW.TYPE_DEFS.items()
                                 if v["site_type"] == s.get("site_type", "custom")), "사용자정의")
                cwu = cwz = cwp = ""
                if SW.TYPE_DEFS[spec_lbl]["needs_wp"]:
                    st.caption("이 유형은 WordPress 자격증명이 필요합니다(복제 시 재입력).")
                    cwu = st.text_input("WordPress URL *", key=f"cl_wpurl_{sid}")
                    cwz = st.text_input("WordPress ID *", key=f"cl_wpuser_{sid}")
                    cwp = st.text_input("App Password *", type="password", key=f"cl_wppw_{sid}")
                if st.button("📑 복제 실행", key=f"cl_run_{sid}"):
                    ok, msg = SW.create_site(cfg, spec_lbl, {
                        "site_name": cl_name, "domain": cl_dom, "category": s.get("site_tags", ""),
                        "wp_url": cwu, "wp_user": cwz, "wp_app_password": cwp, "rss_sources": "",
                        "research_ai": s.get("research_ai", ""), "writing_ai": s.get("writing_ai", ""),
                        "review_ai": s.get("review_ai", ""),
                    })
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.cache_resource.clear(); st.rerun()

    st.divider()
    # ── 계산기 목록 / 관리 ──
    st.subheader("🧮 등록된 계산기")
    try:
        calcs = SW.list_calculators(cfg)
    except Exception as e:
        calcs = []
        st.error(f"계산기 목록 조회 실패: {e}")
    if not calcs:
        st.caption("등록된 계산기 없음")
    for c in calcs:
        cid = c.get("id", "")
        with st.expander(f"🧮 {c.get('name','(이름없음)')} — {c.get('category','')} ({c.get('status','')})"):
            st.write(c.get("seo_desc", ""))
            if st.button("🗑️ 삭제", key=f"cdel_{cid}"):
                ok, msg = SW.delete_calculator(cfg, cid)
                (st.success if ok else st.error)(msg)
                if ok: st.rerun()

# ══════════════════════════════════════════════════════════════
# 탭: 🧮 Calculator Builder (계산기 CRUD — CalculatorRepository 경유)
# ══════════════════════════════════════════════════════════════
elif tab == "🧮 Calculator Builder":
    st.title("🧮 Calculator Builder")
    st.caption("계산기를 코드 수정 없이 생성/수정/상태변경 (CalculatorRepository 경유)")
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    repo = CalculatorRepository(get_db_adapter(cfg))

    ab1, ab2 = st.columns(2)
    if ab1.button("🌱 CalcMate 초기 5종 시드"):
        try:
            from modules.calculator_seed import seed_all
            r = seed_all(cfg)
            st.success(f"시드 완료 — 템플릿 {r['templates']}, 계산기 {r['calculators']}"); st.rerun()
        except Exception as e:
            st.error(f"시드 실패(시트 권한 확인): {e}")
    if ab2.button("▶ 계산기 글 1건 생성(SEO+CTA)"):
        try:
            from modules.calculator_pipeline import run_calculator_once
            with st.spinner("키워드→SEO→본문→계산기 위젯 생성 중..."):
                s = run_calculator_once(cfg, max_count=1)
            st.success(f"생산 {s.get('produced',0)}건 (발행대기 포함). 상세는 작업보드/오류로그 참고.")
        except Exception as e:
            st.error(f"생성 실패: {e}")

    # ── 품질보류 재평가(HOLD Re-evaluate) ──────────────────────────
    # 자동 재평가(품질 서명 변경 시 다음 스케줄에서 자동 재도전)와 별개로, 지금 즉시
    # "무엇이 재도전 대상인지" 확인/실행하는 운영 도구.
    with st.expander("♻️ 품질보류 재평가 (legal/게이트/프롬프트 변경 반영)"):
        st.caption("품질 서명이 바뀐 품질보류 글을 재도전 대상으로 집계합니다. "
                   "'재평가 확인'은 리포트만(비용 0), '재도전 즉시 실행'은 재생성(API 비용)까지 수행.")
        rc1, rc2 = st.columns(2)
        if rc1.button("🔍 재평가 확인 (리포트)", key="reeval_report"):
            try:
                from modules.calculator_pipeline import reevaluate_holds
                res = reevaluate_holds(cfg, apply=False)
                st.success(f"품질보류 {res['holds']}건 · 재도전 {len(res['released'])}건 · "
                           f"유지 {len(res['blocked'])}건 · 이미발행(정리대상) {len(res.get('already_published',[]))}건 · "
                           f"legal 입력필요 {len(res['legal_pending'])}건")
                if res["released"]:
                    st.write("**재도전 대상(released):**")
                    for it in res["released"]:
                        st.write(f"- {it['name']} (`{it['old']}`→`{it['new']}`)")
                if res.get("already_published"):
                    st.write("**이미 발행됨(옛 HOLD 정리 대상 — '재도전 즉시 실행' 시 재처리완료):**")
                    for it in res["already_published"]:
                        st.write(f"- {it['name']}")
                if res["legal_pending"]:
                    st.write("**legal_basis 입력 필요:**")
                    for it in res["legal_pending"]:
                        st.write(f"- {it['name']} (slug=`{it['slug']}`)")
            except Exception as e:
                st.error(f"재평가 실패: {e}")
        if rc2.button("▶ 재도전 즉시 실행 (재생성)", key="reeval_apply"):
            try:
                from modules.calculator_pipeline import reevaluate_holds
                with st.spinner("재도전 대상 재생성 중(키워드→SEO→본문→품질검수)..."):
                    res = reevaluate_holds(cfg, apply=True)
                st.success(f"재도전 {len(res['released'])}건 → 생산 {res.get('produced',0)}건 · "
                           f"옛 HOLD 정리(재처리완료) {res.get('resolved',0)}건. 상세는 작업보드/오류로그 참고.")
            except Exception as e:
                st.error(f"재생성 실패: {e}")
    st.divider()
    try:
        calcs = repo.get_all()
    except Exception as e:
        calcs = []
        st.error(f"계산기 목록 조회 실패(시트 권한 확인): {e}")

    options = ["+ 신규 생성"] + [f"{c.get('name','?')} ({c.get('id','')})" for c in calcs]
    sel = st.selectbox("대상 선택", options, key="cb_sel")
    editing = calcs[options.index(sel) - 1] if sel != "+ 신규 생성" else None

    def _v(k, d=""):
        return (editing or {}).get(k, d)

    c1, c2 = st.columns(2)
    name = c1.text_input("계산기명 *", value=_v("name"), key="cb_name")

    # Slug 자동생성: 편집 대상 전환 시 리셋, 신규 생성 + 공백이면 이름에서 자동생성
    _cb_editing_id = (editing or {}).get("id") or "__new__"
    if st.session_state.get("_cb_prev_editing_id") != _cb_editing_id:
        st.session_state["_cb_prev_editing_id"] = _cb_editing_id
        st.session_state["cb_slug"] = _v("slug")
    if not editing and not st.session_state.get("cb_slug") and name:
        _auto = generate_slug(name)
        if _auto:
            st.session_state["cb_slug"] = _auto

    slug = c2.text_input("slug (자동생성 — 수정 가능)", key="cb_slug")
    c3, c4 = st.columns(2)
    category = c3.text_input("category", value=_v("category"), key="cb_cat")
    ctype = c4.text_input("calculator_type", value=_v("calculator_type", "general"), key="cb_type")
    seo_title = st.text_input("seo_title", value=_v("seo_title"), key="cb_st")
    seo_desc = st.text_area("seo_desc", value=_v("seo_desc"), key="cb_sd")
    formula = st.text_area("formula", value=_v("formula"), key="cb_f")
    faq = st.text_area("faq", value=_v("faq"), key="cb_faq")
    insch = st.text_area("input_schema (JSON)",
                         value=_v("input_schema", '{"hourly_wage":"number","weekly_hours":"number"}'), key="cb_in")
    outsch = st.text_area("output_schema (JSON)",
                          value=_v("output_schema", '{"weekly_allowance":"number"}'), key="cb_out")
    stt = _v("status", "draft")
    status = st.selectbox("status", ["draft", "active", "inactive"],
                          index=["draft", "active", "inactive"].index(stt) if stt in ["draft", "active", "inactive"] else 0,
                          key="cb_status")
    if st.button("💾 저장", type="primary", key="cb_save"):
        if not name.strip():
            st.error("계산기명은 필수입니다.")
        else:
            row = {"name": name, "slug": slug, "category": category, "calculator_type": ctype,
                   "seo_title": seo_title, "seo_desc": seo_desc, "formula": formula, "faq": faq,
                   "input_schema": insch, "output_schema": outsch, "status": status}
            try:
                if editing:
                    repo.update(editing.get("id"), row); st.success("✅ 수정 완료")
                else:
                    repo.save(row); st.success("✅ 생성 완료")
                st.rerun()
            except Exception as e:
                st.error(f"저장 실패(시트 권한 확인): {e}")
    if editing:
        st.divider(); st.caption(f"상태 변경 (현재: {editing.get('status')})")
        sc = st.columns(3)
        for i, s in enumerate(["draft", "active", "inactive"]):
            if sc[i].button(f"→ {s}", key=f"cb_s_{s}"):
                try:
                    repo.update(editing.get("id"), {"status": s}); st.success(f"상태 → {s}"); st.rerun()
                except Exception as e:
                    st.error(f"실패: {e}")

# ══════════════════════════════════════════════════════════════
# 탭: 🧮 계산기 관리 (앱 생성 + GitHub Pages 배포)
# ══════════════════════════════════════════════════════════════
elif tab == "🧮 계산기 관리":
    st.title("🧮 계산기 관리")
    st.caption("계산기 메타데이터로 정적 앱(HTML/CSS/JS) 생성 → GitHub Pages 배포 → URL/상태 관리. (모든 접근 Repository 경유)")
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules import app_generator as AG, github_deployer as GH, formula_engine as FE
    from modules import app_factory as AF_CM
    from modules.registry_loader import load_registry_v3 as _load_v3
    repo = CalculatorRepository(get_db_adapter(cfg))
    _v3_reg = _load_v3(force=True)

    if st.button("🌱 기본 계산기 5종 시드"):
        from modules.calculator_seeder import seed_default_calculators
        r = seed_default_calculators(cfg)
        if "error" in r:
            st.error(f"시드 실패(시트 권한 확인): {r['error']}")
        else:
            st.success(f"생성 {r.get('created',0)} / 스킵 {r.get('skipped',0)}"); st.rerun()

    st.caption("배포 설정: " + ("✅ GITHUB_TOKEN 있음" if GH.is_configured(cfg)
               else "⚠️ GITHUB_TOKEN 미설정 — 배포 비활성(로컬 미리보기만 가능)"))
    try:
        calcs = repo.get_all()
    except Exception as e:
        calcs = []
        st.error(f"계산기 조회 실패(시트 권한 확인): {e}")
    if not calcs:
        st.info("등록된 계산기 없음 — 위 시드 버튼 또는 🧮 Calculator Builder / 🏭 App Factory로 등록")

    def _inline(files):
        # 공통 렌더 함수 1개 공유(대시보드 미리보기 = WordPress 삽입 동일 산출물)
        from modules.app_generator import render_inline_calculator
        return render_inline_calculator(files)

    # Phase F-1: _site/{slug}/ 스냅샷 읽기/쓰기는 modules/site_snapshot.py로 이관
    # (자동 스케줄러 wrapper와 공유하기 위함 — 동작 자체는 무변경).
    from modules.site_snapshot import (
        write_site_snapshot as _write_site_snapshot_impl,
        read_site_snapshot as _read_site_snapshot_impl,
    )

    def _write_site_snapshot(calc: dict, files: dict) -> str:
        return _write_site_snapshot_impl(cfg, calc, files)

    def _read_site_snapshot(calc: dict) -> dict:
        return _read_site_snapshot_impl(cfg, calc)

    _just_saved = st.session_state.get("af_just_saved_name")
    for c in calcs:
        cid = c.get("id", "")
        url = c.get("published_url", "")
        status_icon = "🟢" if str(c.get("status")).lower() == "active" else "⚪"
        _auto_expand = bool(_just_saved) and c.get("name") == _just_saved
        _v3e = _v3_reg.get(c.get("slug", "")) or {}
        _is_hold = _v3e.get("source") == "app_factory" and _v3e.get("status") == "HOLD"
        _hold_badge = " 🔴 LEGAL HOLD" if _is_hold else ""
        with st.expander(f"{status_icon} {c.get('name','(이름없음)')} — {c.get('status','')}{_hold_badge}"
                         + (f" · 배포됨" if url else ""), expanded=_auto_expand):
            if url:
                st.markdown(f"**배포 URL:** [{url}]({url})")
            # App Factory HOLD 계산기 — Phase3-3 검토센터 UI
            if _is_hold:
                from modules import review_center as _RC
                from datetime import datetime as _dt, timezone as _tz

                _slug = c.get("slug", "")
                st.warning(
                    f"⚠️ **LEGAL HOLD** — Tier{_v3e.get('tier','?')} 계산기. "
                    "아래 검토 항목을 확인 완료 후 READY 전환하세요."
                )

                # 체크리스트 로드 (yaml에서)
                _checklist = AF_CM.get_af_checklist(_slug)
                if not _checklist:
                    st.info("검토 항목 생성 중... (계산기를 다시 저장하면 자동 생성됩니다)")
                else:
                    _critical = [i for i in _checklist if i.get("severity") == "critical"]
                    _advisory = [i for i in _checklist if i.get("severity") == "advisory"]
                    _critical_done = sum(1 for i in _critical if i.get("checked"))

                    # 🔴 필수 검토
                    st.markdown(f"**🔴 필수 검토** ({_critical_done}/{len(_critical)} 완료 — 전체 완료해야 READY 가능)")
                    _checklist_changed = False
                    for _item in _critical:
                        _iid = _item["id"]
                        _key = f"chk_{_slug}_{_iid}"
                        _cur = bool(_item.get("checked"))
                        _col_chk, _col_lbl = st.columns([1, 12])
                        _new_val = _col_chk.checkbox("", value=_cur, key=_key)
                        _display = _item.get("display_value") or ""
                        _col_lbl.markdown(
                            f"{'~~' if _new_val else ''}**{_item['label']}**{'~~' if _new_val else ''}"
                            + (f"  \n`{_display[:120]}`" if _display else "")
                        )
                        if _new_val != _cur:
                            if _cur and not _new_val:
                                # D-3: 취소 → 재확인 없이 unchecked (st.warning으로 알림)
                                st.toast(f"'{_item['label']}' 확인 취소됨")
                            _item["checked"] = _new_val
                            _item["checked_by"] = "operator" if _new_val else None
                            _item["checked_at"] = (_dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                                   if _new_val else None)
                            _checklist_changed = True

                    # 🟡 권장 검토
                    if _advisory:
                        st.markdown("**🟡 권장 검토** (선택사항)")
                        for _item in _advisory:
                            _iid = _item["id"]
                            _key = f"chk_{_slug}_{_iid}"
                            _cur = bool(_item.get("checked"))
                            _col_chk, _col_lbl = st.columns([1, 12])
                            _new_val = _col_chk.checkbox("", value=_cur, key=_key)
                            _display = _item.get("display_value") or ""
                            _col_lbl.markdown(
                                f"{'~~' if _new_val else ''}**{_item['label']}**{'~~' if _new_val else ''}"
                                + (f"  \n`{_display[:120]}`" if _display else "")
                            )
                            if _new_val != _cur:
                                _item["checked"] = _new_val
                                _item["checked_by"] = "operator" if _new_val else None
                                _item["checked_at"] = (_dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                                       if _new_val else None)
                                _checklist_changed = True

                    # 체크 상태 변경 시 yaml 저장 + 페이지 갱신
                    if _checklist_changed:
                        try:
                            AF_CM.save_af_checklist(_slug, _checklist)
                        except Exception as _ce:
                            st.error(f"체크리스트 저장 실패: {_ce}")
                        st.rerun()

                    # READY 전환 버튼 (🔴 전체 완료 시에만 활성화)
                    _all_critical_done = all(i.get("checked") for i in _critical)
                    st.markdown("---")
                    if _all_critical_done:
                        st.caption("위 🔴 필수 항목 전체를 직접 확인하였습니다.")
                    if st.button("✅ READY 전환 (legal 검증 완료)", key=f"cm_ready_{cid}",
                                 type="primary", disabled=not _all_critical_done,
                                 help="🔴 필수 항목 전체 완료 시에만 활성화됩니다." if not _all_critical_done else ""):
                        _ok_r, _msg_r = AF_CM.promote_to_ready(_slug)
                        (st.success if _ok_r else st.error)(_msg_r)
                        if _ok_r:
                            st.rerun()
            # 수식 편집(검증 후 저장)
            cur_formula = c.get("formula", "")
            new_formula = st.text_input("수식(formula)", value=str(cur_formula), key=f"cm_f_{cid}")
            _raw_ins = c.get("input_schema")
            try:
                import json as _json
                ins = _raw_ins if isinstance(_raw_ins, dict) else (_json.loads(_raw_ins) if _raw_ins else {})
            except Exception:
                ins = {}
            if st.button("💾 수식 저장(검증)", key=f"cm_fs_{cid}"):
                ok, msg = FE.validate_formula(new_formula, ins, slug=c.get("slug"))
                if ok:
                    FE.save_formula(cfg, cid, new_formula); st.success("수식 저장 완료"); st.rerun()
                else:
                    st.error(f"수식 검증 실패: {msg}")

            # ── AI 자동 생성 ──
            st.markdown("**🤖 AI 자동 생성**")
            g = st.columns(5)
            if g[0].button("SEO 생성", key=f"ag_seo_{cid}"):
                from modules import calculator_seo_generator as SEO
                with st.spinner("SEO 생성 중..."):
                    repo.update_generated(cid, {"seo_title": SEO.generate_seo_title(cfg, c),
                                                "seo_description": SEO.generate_meta_description(cfg, c)})
                st.success("SEO 생성·저장"); st.rerun()
            if g[1].button("FAQ 생성", key=f"ag_faq_{cid}"):
                from modules.calculator_faq_generator import generate_faq
                import json as _j
                with st.spinner("FAQ 생성 중..."):
                    repo.update_generated(cid, {"faq": _j.dumps(generate_faq(cfg, c), ensure_ascii=False)})
                st.success("FAQ 생성·저장"); st.rerun()
            if g[2].button("본문 생성", key=f"ag_art_{cid}"):
                from modules.calculator_content_generator import generate_article
                # STEP 28-37: DB 저장 직전 SSOT 법정수치 검증(논블로킹 warning — 저장은 계속 진행).
                # STEP 28-26에서 만든 기존 헬퍼를 그대로 재사용(신규 파서 없음).
                from modules.calculator_pipeline import _check_legal_current_before_save
                # STEP 28-52: 콘텐츠 SSOT 추적 필드 — 기존 게이트를 내부에서 재사용하는 공통 helper.
                from modules.content_integrity import build_content_tracking_fields
                with st.spinner("본문 생성 중..."):
                    article = generate_article(cfg, c)
                    _check_legal_current_before_save(article, c.get("slug", ""), cid)
                    try:
                        _tracking_fields = build_content_tracking_fields(
                            article, c.get("slug", ""), "dashboard_manual")
                    except Exception:
                        _tracking_fields = {}
                    repo.update_generated(cid, {"article_content": article, **_tracking_fields})
                st.success("본문 생성·저장"); st.rerun()
            if g[3].button("이미지 프롬프트", key=f"ag_img_{cid}"):
                from modules import calculator_image_prompt_generator as IMG
                with st.spinner("이미지 프롬프트 생성 중..."):
                    repo.update_generated(cid, {"image_prompt_thumbnail": IMG.generate_thumbnail_prompt(cfg, c),
                                                "image_prompt_body": IMG.generate_body_prompt(cfg, c)})
                st.success("이미지 프롬프트 생성·저장"); st.rerun()
            if g[4].button("⚡ 전체 자동생성", key=f"ag_all_{cid}", type="primary"):
                from modules.calculator_content_generator import auto_generate_all
                with st.spinner("SEO→FAQ→본문→이미지→저장 진행 중... (수십 초)"):
                    r = auto_generate_all(cfg, c, save=True)
                (st.success if r.get("_saved") else st.warning)(
                    f"전체 자동생성 완료 (저장 {'성공' if r.get('_saved') else '실패: '+r.get('_save_error','')})")
                st.rerun()

            # 생성 결과 미리보기
            if c.get("seo_title") or c.get("article_content"):
                with st.expander("👁 생성 결과 미리보기"):
                    st.write(f"**SEO 제목:** {c.get('seo_title','-')}")
                    st.write(f"**메타설명:** {c.get('seo_description', c.get('seo_desc','-'))}")
                    if c.get("faq"):
                        import json as _j
                        try:
                            fq = _j.loads(c["faq"]) if isinstance(c["faq"], str) else c["faq"]
                            st.write(f"**FAQ {len(fq)}개:**")
                            for f in fq[:10]:
                                st.markdown(f"- **{f.get('question', f.get('q',''))}** — {f.get('answer', f.get('a',''))}")
                        except Exception:
                            pass
                    if c.get("image_prompt_thumbnail"):
                        st.caption(f"썸네일 프롬프트: {c.get('image_prompt_thumbnail')}")
                        st.caption(f"본문 프롬프트: {c.get('image_prompt_body','')}")
                    if c.get("article_content"):
                        st.markdown("**본문 미리보기:**")
                        st.markdown(c["article_content"][:1500] + (" …" if len(c["article_content"]) > 1500 else ""),
                                    unsafe_allow_html=True)
                    if c.get("generated_at"):
                        st.caption(f"생성 시각: {c.get('generated_at')}")

            # ── 🧮 계산기 생성 (Phase A: 명시적 버튼 클릭 시에만 실행) ──────────
            # AG.generate_calculator()는 더 이상 렌더링 시 자동 호출되지 않음.
            # 결과는 session_state에 유지되어 다른 버튼/rerun에도 재생성되지 않는다.
            _files_key = f"cm_files_{cid}"
            _qa_key = f"cm_qa_{cid}"
            _qa_pass_key = f"cm_qa_pass_{cid}"
            _reviewed_key = f"cm_reviewed_{cid}"
            if st.button("🧮 생성", key=f"cm_gen_{cid}"):
                with st.spinner("계산기 생성 중..."):
                    _prev_files = _read_site_snapshot(c)   # Phase E: 덮어쓰기 전 직전 스냅샷 확보
                    _gen_files = AG.generate_calculator(c, cfg)
                    st.session_state[_files_key] = _gen_files
                    _snapshot_dir = _write_site_snapshot(c, _gen_files)
                    try:
                        from modules.review_center import pre_build_qa
                        _qa_results = pre_build_qa(c, cfg, prev_files=_prev_files)
                    except Exception as _qe:
                        _qa_results = [{"step": 0, "label": "QA 실행", "passed": False,
                                        "skipped": False, "detail": f"QA 실행 오류: {_qe}"}]
                    st.session_state[_qa_key] = _qa_results
                    st.session_state[_qa_pass_key] = all(r["passed"] or r["skipped"] for r in _qa_results)
                    st.session_state[_reviewed_key] = False   # Phase E: 새로 생성될 때마다 승인 상태 초기화
                st.success(f"생성 완료 — 스냅샷 저장: {_snapshot_dir}"); st.rerun()

            files = st.session_state.get(_files_key)
            qa_pass = st.session_state.get(_qa_pass_key, False)
            reviewed = st.session_state.get(_reviewed_key, False)
            if files is None:
                st.info("아직 생성되지 않음 — 🧮 생성 버튼을 눌러주세요.")
            else:
                if not files["_formula_valid"]:
                    st.warning(f"수식 경고: {files['_formula_msg']}")
                _qa_results = st.session_state.get(_qa_key)
                if _qa_results:
                    with st.expander(f"{'✅' if qa_pass else '❌'} QA 결과 (pre_build_qa) — {'PASS' if qa_pass else 'FAIL'}"):
                        for r in _qa_results:
                            _icon = "✅" if r["passed"] else ("⏭️" if r["skipped"] else "❌")
                            st.markdown(f"{_icon} Step {r['step']}: {r['label']} — {r['detail']}")
                with st.expander("🔎 앱 미리보기"):
                    import streamlit.components.v1 as components
                    components.html(_inline(files), height=440, scrolling=True)

                # ── 👤 사람 검수 (Phase E: QA PASS 후에만 노출) ──────────────
                if qa_pass:
                    with st.container(border=True):
                        st.markdown(f"**👤 사람 검수** — {'✅ 승인됨' if reviewed else '⏳ 대기 중'}")
                        from modules.review_center import _extract_rate_constants
                        _rates = _extract_rate_constants((files.get("script.js") or "") + (files.get("index.html") or ""))
                        if _rates:
                            st.caption("감지된 요율/기준값: " + ", ".join(f"{k}={v}" for k, v in sorted(_rates.items())))
                        _step7 = next((r for r in _qa_results if r["step"] == 7), None)
                        if _step7 and not _step7["skipped"]:
                            st.caption(f"계산 스모크 테스트 결과: {_step7['detail']}")
                        if not reviewed:
                            if st.button("✅ 검수 승인", key=f"cm_approve_{cid}", type="primary"):
                                st.session_state[_reviewed_key] = True
                                st.rerun()
                        else:
                            if st.button("↩️ 승인 취소", key=f"cm_unapprove_{cid}"):
                                st.session_state[_reviewed_key] = False
                                st.rerun()
                elif files is not None:
                    st.caption("⚠️ QA 실패 — 사람 검수 단계로 진행할 수 없습니다. 위 QA 결과를 확인하세요.")

            b = st.columns(4)
            deploy_label = "🚀 재배포" if url else "🚀 배포"
            _deploy_blocked_reason = (
                "GITHUB_TOKEN 미설정" if not GH.is_configured(cfg) else
                "먼저 🧮 생성을 실행하세요" if files is None else
                "QA 실패로 배포 불가" if not qa_pass else
                "사람 검수 대기 중" if not reviewed else
                None
            )
            if b[0].button(deploy_label, key=f"cm_dep_{cid}",
                           disabled=_deploy_blocked_reason is not None):
                # Phase E: 배포는 _site/{slug}/에 저장된 확정 스냅샷을 그대로 사용 — 재생성하지 않음.
                _deploy_files = _read_site_snapshot(c)
                ok, res = GH.deploy_app(cfg, _deploy_files,
                                        repo=cfg.get("GITHUB_REPO", "salarymate-calculators"),
                                        subdir=c.get("slug", cid))
                if ok:
                    repo.publish(cid, res); st.success(f"배포 완료: {res}"); st.rerun()
                else:
                    st.error(res)
            if _deploy_blocked_reason:
                b[0].caption(f"🔒 {_deploy_blocked_reason}")
            if b[1].button("⏸ 상태토글", key=f"cm_tg_{cid}"):
                repo.update(cid, {"status": "inactive" if str(c.get("status")).lower() == "active" else "active"})
                st.rerun()
            if b[2].button("📥 파일 저장", key=f"cm_dl_{cid}", disabled=files is None):
                import os
                # 계산기별 폴더 생성 후 3파일 저장(옵션 A). 상대경로(style.css/script.js) 유지 →
                # 로컬 더블클릭·GitHub Pages 구조 동일. app_generator/템플릿/CSS는 무변경.
                # (Phase B에서 이 경로를 data/workspace/_site/{slug}/로 연결 예정 — 이번 턴은 무변경)
                slug = str(c.get("slug", cid)).strip().replace("/", "_").replace("\\", "_").replace("..", "_") or cid
                outdir = BASE / "data" / "workspace" / slug
                os.makedirs(outdir, exist_ok=True)
                for fn in ("index.html", "style.css", "script.js"):
                    (outdir / fn).write_text(files[fn], encoding="utf-8")
                st.success(f"✅ 저장: data/workspace/{slug}/ (index.html · style.css · script.js). "
                           f"index.html 더블클릭 시 CSS/JS 상대경로 연결 정상 — GitHub Pages와 동일 구조.")
            if b[3].button("🗑 삭제", key=f"cm_del_{cid}"):
                # DB row만 지우면 registry_auto.yaml/v3 Registry에 orphan 엔트리가 남는다
                # (STEP 28-157에서 실제 재현 확인) — delete_app()으로 DB+registry 일괄 정리.
                _del_slug = str(c.get("slug", cid)).strip()
                _del_ok, _del_msg = AF_CM.delete_app(cfg, _del_slug)
                (st.success if _del_ok else st.error)(_del_msg)
                if _del_ok:
                    st.rerun()

            # ── Build 버튼 (READY 상태 app_factory 계산기만) ─────────────
            _is_ready_af = (_v3e.get("source") == "app_factory" and
                            _v3e.get("status") == "READY")
            if _is_ready_af:
                st.divider()
                st.markdown("**⚙️ Build (정적 사이트 전체 재빌드)**")
                if st.button(f"⚙️ Build — {c.get('name','')}", key=f"cm_build_{cid}", type="primary"):
                    from modules import review_center as _RC_build
                    # Step 1~6 사전 QA 실행
                    with st.spinner("Build 사전 QA 실행 중..."):
                        _qa_results = _RC_build.pre_build_qa(c, cfg)
                    _qa_failed = [r for r in _qa_results if not r["passed"] and not r["skipped"]]
                    # QA 결과 표시
                    for _r in _qa_results:
                        _icon = "✅" if _r["passed"] else ("⏭️" if _r["skipped"] else "❌")
                        st.markdown(f"{_icon} **Step {_r['step']}: {_r['label']}** — {_r['detail']}")
                    if _qa_failed:
                        st.error(f"❌ Build 차단 — QA {len(_qa_failed)}개 항목 실패. 위 내용을 확인 후 재시도하세요.")
                    else:
                        st.success("✅ 사전 QA 전체 통과 → _rebuild_site.py 실행 중...")
                        import subprocess, sys as _sys
                        _rb = subprocess.run(
                            [_sys.executable, "scripts/_rebuild_site.py"],
                            capture_output=True, text=True, timeout=180, cwd=str(BASE)
                        )
                        if _rb.returncode == 0:
                            st.success("✅ Build 완료 — _site/ 갱신됨")
                            st.code(_rb.stdout[-2000:] or "(출력 없음)")
                            # index/sitemap 반영 확인
                            _site_dir = BASE / "data" / "workspace" / "_site"
                            _slug_built = c.get("slug", "")
                            _has_slug_dir = (_site_dir / _slug_built / "index.html").exists()
                            _sitemap = _site_dir / "sitemap.xml"
                            _in_sitemap = (_slug_built in _sitemap.read_text(encoding="utf-8")
                                           if _sitemap.exists() else False)
                            st.markdown(
                                f"**반영 확인:**  \n"
                                f"{'✅' if _has_slug_dir else '⚠️'} `_site/{_slug_built}/index.html` {'존재' if _has_slug_dir else '없음'}  \n"
                                f"{'✅' if _in_sitemap else '⚠️'} `sitemap.xml`에 slug {'포함' if _in_sitemap else '미포함'}"
                            )
                            # Deploy 준비 안내 화면
                            st.divider()
                            st.markdown("### 📋 배포 전 확인 체크리스트 (수동 진행)")
                            st.info(
                                "Build 완료. 아래 4단계를 직접 진행하세요. "
                                "Step 3·4가 확인될 때까지 '배포 완료'로 간주하지 마세요."
                            )
                            _deploy_slug = c.get("slug", "YOUR-SLUG")
                            st.markdown(f"""
**Step 1** — git commit
```
git add data/workspace/_site/ docs/registry/
git commit -m "feat(phase3-N): add {_deploy_slug} calculator"
```
**Step 2** — git push
```
git push origin master
```
**Step 3** — GitHub Actions 확인
→ Actions 페이지에서 최신 워크플로가 ✅ 완료 상태인지 확인

**Step 4** — 실제 사이트 확인
- `https://calcmate.kr/` (메인 카드 노출)
- `https://calcmate.kr/{_deploy_slug}/` (HTTP 200 + 출력 요소)
- `https://calcmate.kr/sitemap.xml` (URL 포함)
""")
                        else:
                            st.error("❌ Build 실패")
                            st.code(_rb.stderr[-2000:] or "(출력 없음)")

    # 자동펼침 플래그는 한 번 사용 후 제거(다음 렌더부터는 평소처럼 접힌 채)
    if _just_saved:
        st.session_state["af_just_saved_name"] = None

    # ── 사이트 페이지 배포 ─────────────────────────────────────────
    st.divider()
    st.subheader("🌐 사이트 페이지 배포")
    st.caption("메인 홈 + 소개 / 개인정보처리방침 / 이용약관 / 문의하기 페이지를 GitHub Pages에 배포합니다.")

    from modules import site_generator as SG
    site_pages = SG.generate_all(cfg)
    page_list = [p for p in site_pages if not p.endswith(".css")]

    with st.expander("📄 생성 페이지 미리보기"):
        preview_page = st.selectbox("페이지 선택", page_list,
                                    key="site_preview_page")
        if preview_page:
            import streamlit.components.v1 as _comp
            _comp.html(site_pages[preview_page], height=500, scrolling=True)

    col_a, col_b = st.columns(2)
    if col_a.button("🚀 사이트 페이지 배포",
                    disabled=not GH.is_configured(cfg),
                    key="cm_site_deploy"):
        with st.spinner("사이트 페이지 업로드 중..."):
            _repo_name = cfg.get("GITHUB_REPO", "calcmate-calculators")
            ok_r, full_name = GH.create_repo(cfg, _repo_name)
            if not ok_r:
                st.error(f"저장소 생성 실패: {full_name}")
            else:
                _ok, _fail = 0, []
                for _path, _content in site_pages.items():
                    try:
                        # STEP 16-W: Pages는 data/workspace/_site/**만 아티팩트로 배포(.github/workflows/deploy.yml)하므로
                        # 사이트 페이지도 저장소 루트가 아니라 이 경로 하위에 커밋해야 실제로 반영된다.
                        GH._put_file(cfg, full_name, f"data/workspace/_site/{_path}", _content)
                        _ok += 1
                    except Exception as _e:
                        _fail.append(f"{_path}: {_e}")
                GH._enable_pages(cfg, full_name)
                if _fail:
                    st.warning(f"배포 완료({_ok}개) — 실패: {'; '.join(_fail)}")
                else:
                    _site_url = cfg.get("SITE_URL", "https://calcmate.kr")
                    st.success(f"✅ {_ok}개 페이지 배포 완료 → {_site_url}/")

    if col_b.button("💾 로컬 저장", key="cm_site_local"):
        import os
        _out = BASE / "data" / "workspace" / "_site"
        for _path, _content in site_pages.items():
            _fp = _out / _path
            os.makedirs(_fp.parent, exist_ok=True)
            _fp.write_text(_content, encoding="utf-8")
        st.success(f"✅ data/workspace/_site/ 에 {len(site_pages)}개 파일 저장")

# ══════════════════════════════════════════════════════════════
# 탭: 🏭 App Factory (계산기 자동 생성)
# ══════════════════════════════════════════════════════════════
elif tab == "🏭 App Factory":
    st.title("🏭 App Factory")
    st.caption("자동 생성 흐름: GPT 스펙 → Claude 코드(HTML) → GPT SEO/FAQ/초안 → Gemini 이미지 프롬프트 → 저장")
    from modules import app_factory as AF

    # 🔍 키워드 기반 아이디어 제안 — 키워드를 중심으로 이름/카테고리/설명 자동채움.
    k1, k2 = st.columns([3, 1])
    af_keyword = k1.text_input("키워드로 아이디어 생성",
                               placeholder="예: 육아휴직, 4대보험, 연차",
                               key="af_keyword")
    if k2.button("🔍 키워드로 제안", key="af_suggest_kw"):
        with st.spinner("키워드 기반 아이디어 생성 중..."):
            try:
                idea = AF.suggest_idea(cfg, keyword=af_keyword)
                st.session_state["af_name"] = idea.get("name", "")
                st.session_state["af_cat"] = idea.get("category", "")
                st.session_state["af_desc"] = idea.get("desc", "")
            except Exception as e:
                st.warning(f"AI 제안 실패(직접 입력해주세요): {e}")

    # 💡 AI 아이디어 제안(수동 버튼)
    if st.button("💡 AI 아이디어 제안", key="af_suggest"):
        with st.spinner("AI가 새 계산기 아이디어를 찾는 중..."):
            try:
                idea = AF.suggest_idea(cfg)
                st.session_state["af_name"] = idea.get("name", "")
                st.session_state["af_cat"] = idea.get("category", "")
                st.session_state["af_desc"] = idea.get("desc", "")
            except Exception as e:
                st.warning(f"AI 제안 실패(직접 입력해주세요): {e}")

    from modules import review_center as RC

    c1, c2 = st.columns(2)
    af_name = c1.text_input("계산기명 *", placeholder="퇴직금 계산기", key="af_name")
    af_cat = c2.text_input("카테고리", placeholder="노무/급여", key="af_cat")
    af_desc = st.text_area("설명", placeholder="예: 근속연수와 평균임금으로 퇴직금 계산", key="af_desc")

    # ── Mode(A/B) AI 추천 (STEP 25-2) ───────────────────────────
    # 추천 표시 전용 UX 기능. generate_app()/generate_app_with_contract()/save_app()를
    # 직접 호출하지 않으며, legal_refs·test_cases 자동 선택/생성에도 관여하지 않는다.
    # Mode 선택 자체는 기존과 동일하게 아래 [🏭 자동 생성](A) / [📋 Contract 기반 생성](B)
    # 버튼 중 사용자가 직접 클릭하는 방식으로 최종 결정된다(이 STEP에서 변경하지 않음).
    _mode_col1, _mode_col2 = st.columns([4, 1])
    with _mode_col1:
        _mode_suggest = st.session_state.get("af_mode_suggest", {})
        if _mode_suggest:
            _m_conf = _mode_suggest.get("confidence", "medium")
            _m_val = _mode_suggest.get("mode", "A")
            _m_label = "Mode B — 📋 Contract 기반 생성" if _m_val == "B" else "Mode A — 🏭 자동 생성"
            _m_reason = _mode_suggest.get("reason", "")
            if _m_conf == "high":
                st.success(f"✅ AI 추천: **{_m_label}** (확신도: HIGH)  \n이유: {_m_reason}")
            else:
                _m_conf_icon = {"medium": "⚠️ 확신도 보통 —", "low": "🚨 판단 불확실 —"}.get(_m_conf, "")
                st.info(f"💡 AI 추천: **{_m_label}** {_m_conf_icon}  \n이유: {_m_reason}")
            st.caption(
                "참고용 추천입니다. 아래 버튼 중 직접 선택해 진행하세요 — "
                "legal_refs·test_cases는 이 추천과 무관하게 항상 사람이 직접 확정합니다."
            )
    with _mode_col2:
        if st.button("💡 Mode AI 추천", key="af_mode_suggest_btn",
                      help="이름·카테고리·설명 기반으로 AI가 Mode(A/B)를 추천합니다(표시만, 자동 생성 없음)"):
            if not af_name.strip():
                st.warning("계산기명을 먼저 입력하세요.")
            else:
                with st.spinner("Mode 분석 중..."):
                    try:
                        _m_result = RC.suggest_mode(cfg, af_name, af_cat or "", af_desc or "")
                        st.session_state["af_mode_suggest"] = _m_result
                        st.rerun()
                    except Exception as _me:
                        st.warning(f"Mode 추천 실패(직접 선택): {_me}")

    # ── Tier2-B 키워드 사전 감지 (rule-based) ──────────────────
    if af_name and RC.detect_tier2b_keywords(af_name, af_desc or ""):
        st.warning("⚠️ 이름/설명에 날짜·기간 관련 키워드가 감지됩니다. Tier2-B(날짜형) 가능성을 직접 확인하세요.")

    # ── Tier AI 추천 (D-1) ─────────────────────────────────────
    _tier_map_str_to_int = {"Tier2-A": 2, "Tier2-B": 2, "Tier1": 1}
    _tier_map_int_to_str = {2: "Tier2-A", 1: "Tier1"}

    _tier_col1, _tier_col2 = st.columns([4, 1])
    with _tier_col1:
        _tier_suggest = st.session_state.get("af_tier_suggest", {})
        if _tier_suggest:
            _conf = _tier_suggest.get("confidence", "medium")
            _tier_val = _tier_suggest.get('tier', 'Tier2-A')
            _reason = _tier_suggest.get('reason', '')
            # STEP 23-3: confidence=high는 "자동 선택됨"을 명확히 표시(자동 생성 아님 —
            # 라디오/체크박스는 여전히 사용자가 언제든 변경 가능, 생성 버튼은 항상 수동 클릭)
            if _conf == "high":
                st.success(f"✅ AI 추천: **{_tier_val}** (신뢰도: HIGH) — "
                           f"높은 확신도로 자동 선택되었습니다. 필요하면 직접 변경할 수 있습니다.  \n"
                           f"이유: {_reason}")
            else:
                _conf_icon = {"medium": "⚠️ 확신도 보통 —", "low": "🚨 분류 불확실 —"}.get(_conf, "")
                st.info(f"💡 AI 추천: **{_tier_val}** {_conf_icon}  \n"
                        f"이유: {_reason}")
    with _tier_col2:
        if st.button("💡 Tier AI 추천", key="af_tier_suggest_btn", help="이름·설명 기반으로 AI가 Tier를 추천합니다"):
            if not af_name.strip():
                st.warning("계산기명을 먼저 입력하세요.")
            else:
                with st.spinner("Tier 분석 중..."):
                    try:
                        _result = RC.suggest_tier(cfg, af_name, af_desc or "")
                        st.session_state["af_tier_suggest"] = _result
                        # D-1: 추천값으로 라디오 기본값 세팅
                        _t_int = _tier_map_str_to_int.get(_result["tier"], 2)
                        st.session_state["af_tier"] = _t_int
                        # STEP 23-2: Tier2-B 추천 신호를 Mode B 체크박스까지 배선
                        # (confidence와 무관하게 "Tier2-B라는 추천 결과 자체"만 보존 —
                        #  자동확정 여부는 이 STEP의 범위 밖. Mode A는 subtype 개념이 없어 영향 없음)
                        _tier2b_suggested = (_result.get("tier") == "Tier2-B")
                        st.session_state["af_tier2b_suggested"] = _tier2b_suggested
                        st.session_state["af_contract_is_tier2b"] = _tier2b_suggested
                        st.rerun()
                    except Exception as _te:
                        st.warning(f"Tier 추천 실패(직접 선택): {_te}")

    # Tier 선택 (필수) — D-1: AI 추천이 기본값, 운영자 최종 확인/변경
    af_tier = st.radio(
        "Tier * (최종 선택 — AI 추천을 참고하되 직접 확인하세요)",
        options=[2, 1],
        format_func=lambda t: (
            "Tier2 — 단순 산술/일반 공식 (수식으로 표현 가능한 계산)"
            if t == 2 else
            "Tier1 — 법령/조건분기/복잡 계산 (날짜 기반, 다단계 조건, 법령 요율 적용)"
        ),
        horizontal=True,
        key="af_tier",
    )
    if af_tier == 1:
        st.info("ℹ️ Tier1은 생성 후 계산 로직 + legal 근거 모두 사람이 검증해야 합니다. READY 전환 전까지 index/sitemap 비노출.")
    else:
        st.info("ℹ️ Tier2는 생성 후 계산 정확성 검증 + legal 검증 완료 시 READY 전환 가능.")
    # ── Mode A: 자동 생성 ──────────────────────────────────────────────
    if st.button("🏭 자동 생성", type="primary", key="af_gen"):
        if not af_name.strip():
            st.error("계산기명은 필수입니다.")
        else:
            with st.spinner("AI가 계산기를 생성 중입니다... (수십 초)"):
                try:
                    st.session_state["af_result"] = AF.generate_app(
                        cfg, af_name, af_cat, af_desc, tier=af_tier)
                    st.session_state.pop("af_contract", None)
                except Exception as e:
                    st.session_state["af_result"] = None
                    st.error(f"생성 실패: {e}")

    st.divider()

    # ── Mode B: Contract 기반 생성 ─────────────────────────────────────
    with st.expander("📋 Contract 확정 스펙 입력 (법령 기반 계산기 — 선택)"):
        st.caption(
            "법령·취업규칙 등으로 필드명·수식이 이미 확정된 계산기에만 사용하세요. "
            "Contract는 AI 호출 전에 확정되어야 합니다. "
            "AI 결과를 보고 나서 Contract를 채우는 것은 검증 의미가 없습니다."
        )
        _af_is_tier2b = st.checkbox(
            "🗓️ Tier2-B (날짜형 계산기) — AI 없이 결정적 HTML 생성",
            key="af_contract_is_tier2b",
            help="입영일·전역일 등 날짜 연산 계산기. 체크 시 AI 호출 없이 날짜 계산 HTML을 직접 생성합니다.",
        )
        # ── STEP 26-1: 확정 slug 자동 제안 — 기존 generate_slug() 재사용 ──
        # (Mode A의 af_slug 자동 프리필과 동일 함수. 신규 slug 규칙 없음.)
        # 위젯(key=af_contract_slug_pre)이 아직 instantiate되기 전이므로 여기서
        # session_state를 직접 세팅해도 안전하다(StreamlitAPIException 없음).
        # 슬러그 입력란이 비어있을 때만 채우고, 한 번이라도 값이 들어가면
        # (자동 제안이든 사용자 직접 입력이든) 이후 rerun에서 다시 덮어쓰지 않는다.
        if af_name.strip() and not (st.session_state.get("af_contract_slug_pre") or "").strip():
            _cs_auto = generate_slug(af_name.strip())
            if _cs_auto:
                st.session_state["af_contract_slug_pre"] = _cs_auto

        _bc1, _bc2 = st.columns(2)
        _af_slug_pre = _bc1.text_input(
            "확정 slug *", placeholder="annual-leave-remaining",
            key="af_contract_slug_pre",
            help="생성 전 확정 URL 식별자. 영문 소문자·숫자·하이픈만. "
                 "계산기명을 입력하면 자동 제안되며, 직접 수정할 수 있습니다.")
        # ── STEP 26-1: 확정 slug 중복 확인 — 기존 check_slug_conflict() 재사용 ──
        _cs_check = (_af_slug_pre or "").strip().lower()
        if _cs_check:
            import re as _re_cs_chk
            if _re_cs_chk.match(r"^[a-z0-9][a-z0-9-]*$", _cs_check):
                _, _cs_conflict, _cs_msg = RC.check_slug_conflict(_cs_check, cfg)
                if _cs_conflict:
                    _bc1.error(f"⛔ 슬러그 중복: {_cs_msg}")
                else:
                    _bc1.caption(f"✅ 슬러그 사용 가능: '{_cs_check}'")
            else:
                _bc1.warning("영문 소문자·숫자·하이픈만 사용 가능합니다.")
        _af_input_fields = _bc2.text_input(
            "입력 필드 (쉼표 구분) *", placeholder="years_of_service, used_days",
            key="af_contract_input_fields",
            help="법령에서 확정한 입력 필드명(영문). 예: years_of_service, used_days")
        _af_output_fields = st.text_input(
            "출력 필드 (쉼표 구분) *", placeholder="total_days, remaining_days",
            key="af_contract_output_fields",
            help="법령에서 확정한 출력 필드명(영문). 예: total_days, remaining_days")

        # ── CA-1B-3-A: Registry에서 input/output 필드 자동 프리필 ───────────
        # CA-1B-3-A-FIX: Streamlit lifecycle 상 위젯(key=af_contract_input_fields 등)이
        # 이미 instantiation된 뒤 같은 run에서 해당 session_state를 직접 수정하면
        # StreamlitAPIException이 발생하므로, on_click callback에서 세팅한다.
        # (callback은 다음 rerun에서 위젯이 생성되기 전에 실행됨 → 프리필 값이 반영됨)
        def _af_prefill_from_registry() -> None:
            _slug = (st.session_state.get("af_contract_slug_pre") or "").strip()
            if not _slug:
                st.session_state["af_prefill_msg"] = (
                    "warning", "⚠️ Registry에서 불러오려면 먼저 [확정 slug]를 입력하세요.")
                return
            _pf = AF.prefill_contract_from_registry(_slug)
            if not _pf.get("found"):
                st.session_state["af_prefill_msg"] = (
                    "warning",
                    f"⚠️ Registry v3에 '{_slug}' 엔트리가 없습니다. "
                    "자동 프리필하지 않고 기존 입력을 유지합니다.")
            elif not _pf.get("input_fields") and not _pf.get("output_fields"):
                st.session_state["af_prefill_msg"] = (
                    "warning",
                    f"⚠️ Registry 엔트리에 input_labels/output_labels가 없습니다. "
                    "자동 프리필하지 않고 기존 입력을 유지합니다.")
            else:
                st.session_state["af_contract_input_fields"] = ", ".join(_pf["input_fields"])
                st.session_state["af_contract_output_fields"] = ", ".join(_pf["output_fields"])
                # CA-1B-3-B P1: legal_refs → legal_master → scope_exclusions 자동 매핑
                _se = _pf.get("scope_exclusions") or []
                st.session_state["af_contract_scope_exclusions"] = list(_se)
                # CA-1B-4 P1-D: Registry legal_refs 보존 (HOLD-3/Type D/분류용)
                st.session_state["af_contract_legal_refs"] = list(_pf.get("legal_refs") or [])
                _se_note = f" / 제외조건 {len(_se)}개" if _se else ""
                st.session_state["af_prefill_msg"] = (
                    "success",
                    f"✅ Registry에서 불러옴: {_pf.get('name') or _slug} — "
                    f"input {len(_pf['input_fields'])}개 / output {len(_pf['output_fields'])}개"
                    f"{_se_note}. 확인 후 [📋 Contract 기반 생성]을 실행하세요.")

        # ── CA-1B-4 P0: 저장된 Contract instance에서 기존 Contract 복원 ──────
        # CA-1B-3-A/B에서 저장(instance 파일 + registry 인덱스)과 로더
        # (load_contract_instance)는 구현됐지만 읽는 경로가 없어, App Factory 재진입 시
        # 기존 Contract를 위젯에 복원해 재검증/재사용할 수 있게 연결한다.
        # 위젯 key는 on_click callback에서 세팅 (Streamlit lifecycle 안전 패턴 유지)
        def _af_load_contract_instance() -> None:
            _slug = (st.session_state.get("af_contract_slug_pre") or "").strip()
            if not _slug:
                st.session_state["af_prefill_msg"] = (
                    "warning", "⚠️ Contract를 불러오려면 먼저 [확정 slug]를 입력하세요.")
                return
            _rest = AF.contract_instance_restore(_slug)
            if not _rest.get("found"):
                st.session_state["af_prefill_msg"] = (
                    "warning", f"⚠️ {_rest.get('message')} 기존 입력을 유지합니다.")
                return
            st.session_state["af_contract_input_fields"] = ", ".join(_rest["input_fields"])
            st.session_state["af_contract_output_fields"] = ", ".join(_rest["output_fields"])
            st.session_state["af_contract_scope_exclusions"] = list(
                _rest["scope_exclusions"])
            _f = _rest.get("formula")
            _f_str = ""
            if _f is not None:
                _f_str = (json.dumps(_f, ensure_ascii=False)
                          if isinstance(_f, dict) else str(_f))
            st.session_state["af_contract_formula"] = _f_str
            _tc = _rest.get("test_cases") or []
            st.session_state["af_contract_test_cases"] = json.dumps(
                _tc, ensure_ascii=False)
            # operator_confirmed로 저장된 Contract는 재생성 시에도 상태 보존
            if _rest.get("formula_status") == "operator_confirmed" and _f_str:
                st.session_state["af_formula_confirmed_text"] = _f_str
            else:
                st.session_state.pop("af_formula_confirmed_text", None)
            st.session_state["af_prefill_msg"] = (
                "success",
                f"✅ Contract instance 복원: {_rest.get('name') or _rest['slug']} — "
                f"input {len(_rest['input_fields'])}개 / output {len(_rest['output_fields'])}개 "
                f"/ formula_status: {_rest.get('formula_status')}. "
                "확인 후 [📋 Contract 기반 생성]으로 재검증하세요.")

        # ── STEP 24-2: AI 필드 자동 제안 — STEP 24-1의 _suggest_spec() 재사용 ──
        # (신규 프롬프트/생성 로직 없음. generate_app()의 [0]/[1] 단계와 동일한
        #  existing 로드 + _suggest_spec() 호출만 수행 — Mode A 로직 무변경.)
        def _af_suggest_fields_with_ai() -> None:
            _name = (st.session_state.get("af_name") or "").strip()
            if not _name:
                st.session_state["af_prefill_msg"] = (
                    "warning", "⚠️ 필드 자동 제안을 사용하려면 먼저 [계산기명]을 입력하세요.")
                return
            _cat = st.session_state.get("af_cat") or ""
            _desc = st.session_state.get("af_desc") or ""
            _tier = st.session_state.get("af_tier", 2)
            try:
                from repositories.calculator_repository import CalculatorRepository as _CR
                from adapters.db.factory import get_db_adapter as _gda
                _existing = _CR(_gda(cfg)).get_all()
            except Exception:
                _existing = []
            try:
                _spec, _ = AF._suggest_spec(cfg, _name, _cat, _desc, _tier, _existing, _contract=None)
            except Exception as _e:
                st.session_state["af_prefill_msg"] = (
                    "warning", f"⚠️ 필드 자동 제안에 실패했습니다. 기존 입력값은 유지됩니다. ({_e})")
                return
            _in_keys = list((_spec.get("input_schema") or {}).keys())
            _out_keys = list((_spec.get("output_schema") or {}).keys())
            if not _in_keys and not _out_keys:
                st.session_state["af_prefill_msg"] = (
                    "warning", "⚠️ AI가 유효한 필드를 제안하지 못했습니다. 기존 입력값은 유지됩니다.")
                return
            if _in_keys:
                st.session_state["af_contract_input_fields"] = ", ".join(_in_keys)
            if _out_keys:
                st.session_state["af_contract_output_fields"] = ", ".join(_out_keys)
            _formula = _spec.get("formula")
            _has_formula = _formula not in (None, "", {})
            if _has_formula:
                _f_str = (json.dumps(_formula, ensure_ascii=False)
                          if isinstance(_formula, dict) else str(_formula))
                st.session_state["af_contract_formula"] = _f_str
            _labels = _spec.get("labels") or {}
            _label_note = (" (" + ", ".join(f"{k}={v}" for k, v in list(_labels.items())[:5]) + ")"
                           if _labels else "")
            st.session_state["af_prefill_msg"] = (
                "success",
                f"✅ AI 필드 제안이 적용되었습니다 — input {len(_in_keys)}개 / output {len(_out_keys)}개"
                f"{' / formula 포함' if _has_formula else ''}. 필요하면 직접 수정하세요.{_label_note}")

        st.button(
            "💡 필드 자동 제안",
            key="af_suggest_fields_btn",
            on_click=_af_suggest_fields_with_ai,
            help=(
                "계산기명/카테고리/설명을 바탕으로 AI가 input/output 필드명과 formula 후보를 "
                "제안해 아래 입력란에 채웁니다(STEP 24-1의 _suggest_spec() 재사용, 신규 AI 로직 없음). "
                "AI 제안으로 현재 필드 입력값을 채웁니다. 필요하면 이후 직접 수정할 수 있습니다."
            ),
        )

        _btn_col1, _btn_col2 = st.columns(2)
        _btn_col1.button(
            "📥 Registry에서 불러오기 (input/output 필드)",
            key="af_registry_prefill",
            on_click=_af_prefill_from_registry,
            help=(
                "확정 slug에 해당하는 Registry v3 엔트리의 input_labels/output_labels를 "
                "입력·출력 필드에 채웁니다. 프리필 후 운영자가 확인·수정할 수 있습니다."
            ),
        )
        _btn_col2.button(
            "📂 Contract Instance 불러오기 (저장된 Contract 복원)",
            key="af_contract_load",
            on_click=_af_load_contract_instance,
            help=(
                "확정 slug의 저장된 Contract instance(docs/contract_schema/instances/)를 "
                "입력·출력·formula·test_cases·제외조건에 복원합니다. "
                "복원 후 [📋 Contract 기반 생성]으로 재검증/재사용할 수 있습니다."
            ),
        )
        _af_prefill_msg = st.session_state.pop("af_prefill_msg", None)
        if _af_prefill_msg:
            _af_prefill_kind, _af_prefill_text = _af_prefill_msg
            if _af_prefill_kind == "warning":
                st.warning(_af_prefill_text)
            else:
                st.success(_af_prefill_text)

        # CA-1B-3-B P1: 프리필로 매핑된 scope_exclusions를 운영자가 확인할 수 있게 표시 (read-only)
        # CA-1B-4 P1-B: AI 생성 prompt(enforcement + writer)에 전달되므로 문구 갱신
        _af_scope_exclusions = st.session_state.get("af_contract_scope_exclusions") or []
        if _af_scope_exclusions:
            st.caption(
                "🚫 제외 대상 (scope_exclusions — legal_master 자동 매핑, AI 생성 prompt에 전달됨): "
                + ", ".join(str(s) for s in _af_scope_exclusions))

        _af_formula = st.text_area(
            "확정 Formula (선택 — str 또는 JSON dict)",
            placeholder='{"total_days": "15 + min(max(0, (years_of_service-1)//2), 10)", ...}',
            height=90,
            key="af_contract_formula",
            help="수식이 법령으로 확정된 경우만 입력. 입력 시 AI 결과 수식과 비교합니다.")

        # ── CA-3-4: AI Formula 제안 버튼 ─────────────────────────────
        _sf_input_ok = (
            bool((_af_input_fields or "").strip())
            and bool((_af_output_fields or "").strip())
        )
        if st.button(
            "🤖 AI Formula 제안",
            key="af_formula_ai_suggest",
            disabled=not _sf_input_ok,
            help=(
                "입력 필드와 출력 필드를 먼저 입력하세요." if not _sf_input_ok
                else "AI가 Formula를 제안합니다. 반드시 [🔍 Formula 검증] 후 [✅ Formula 확정]을 실행하세요."
            ),
        ):
            _existing_formula = (_af_formula or "").strip()
            _override_set = st.session_state.pop("_af_ai_suggest_override", False)
            if _existing_formula and not _override_set:
                # R-6: 1차 클릭 — 기존 formula 존재 시 경고 후 대기
                st.warning("⚠️ 기존 Formula가 있습니다. 다시 클릭하면 AI 제안으로 교체됩니다.")
                st.session_state["_af_ai_suggest_override"] = True
            else:
                # 2차 클릭 또는 기존 formula 없음 — AI 호출
                _sf_input_list  = [f.strip() for f in (_af_input_fields or "").split(",") if f.strip()]
                _sf_output_list = [f.strip() for f in (_af_output_fields or "").split(",") if f.strip()]
                with st.spinner("🤖 AI가 Formula를 제안하는 중..."):
                    _sf_result = AF.suggest_formula(
                        cfg=cfg,
                        name=af_name or "",
                        category=af_cat or "",
                        desc=af_desc or "",
                        input_fields=_sf_input_list,
                        output_fields=_sf_output_list,
                        legal_refs=list(
                            st.session_state.get("af_contract_legal_refs") or []),
                        slug=(_af_slug_pre or "").strip() or None,
                    )
                if _sf_result["success"]:
                    _sf_formula = _sf_result["formula"]
                    # dict → compact JSON 문자열로 직렬화 (whitespace 비교 일관성 유지)
                    _sf_formula_str = (
                        json.dumps(_sf_formula, ensure_ascii=False)
                        if isinstance(_sf_formula, dict)
                        else str(_sf_formula)
                    )
                    st.session_state["af_contract_formula"] = _sf_formula_str
                    st.session_state["af_formula_ai_suggested_text"] = _sf_formula_str
                    # 이전 확정/검증 상태 초기화
                    st.session_state.pop("af_formula_confirmed_text", None)
                    st.session_state.pop("af_formula_validation", None)
                    if st.session_state.get("af_contract"):
                        st.session_state["af_contract"]["formula_status"] = "ai_suggested"
                    for _sw in (_sf_result.get("warnings") or []):
                        st.warning(f"⚠️ {_sw}")
                    st.info("AI Formula 제안 완료. 반드시 검토 후 [🔍 Formula 검증]을 실행하세요.")
                    st.rerun()
                else:
                    st.error(f"❌ AI Formula 제안 실패: {_sf_result['reason']}")
                    for _sw in (_sf_result.get("warnings") or []):
                        st.warning(f"⚠️ {_sw}")

        # ── CA-2-6-2: formula_status 배지 (항상 표시) ─────────────────
        _fv_badge_status = (st.session_state.get("af_contract") or {}).get("formula_status")
        if _fv_badge_status is None:
            _fv_prior_raw_badge = st.session_state.get("af_formula_confirmed_text", "")
            _fv_ai_badge_raw    = st.session_state.get("af_formula_ai_suggested_text", "")
            _fv_cur_raw_badge   = (_af_formula or "").strip()
            if _fv_prior_raw_badge and _fv_cur_raw_badge == _fv_prior_raw_badge:
                _fv_badge_status = "operator_confirmed"
            elif _fv_ai_badge_raw and _fv_cur_raw_badge == _fv_ai_badge_raw:
                _fv_badge_status = "ai_suggested"   # CA-3-4: af_contract 없을 때 fallback
            elif _fv_cur_raw_badge:
                _fv_badge_status = "pending_validation"
            else:
                _fv_badge_status = "not_generated"
        _fv_badge_map = {
            "not_generated":      "⚪ Formula 미생성",
            "ai_suggested":        "🔵 AI 제안",
            "pending_validation":  "🟡 검증 대기",
            "operator_confirmed":  "🟢 운영자 확정",
        }
        st.caption(f"Formula 상태: {_fv_badge_map.get(_fv_badge_status, '⚠️ 확인 필요')}")
        _af_test_cases = st.text_area(
            "테스트 케이스 (선택 — JSON 배열)",
            placeholder='[{"input": {"years_of_service": 1, "used_days": 0}, "expected": {"total_days": 15.0}}]',
            height=90,
            key="af_contract_test_cases",
            help="예상 입출력 쌍. 있으면 Contract 기반 생성 후 수식 샘플 검증도 수행합니다.")

        # ── CA-2-6-2: Formula 수정 감지 → operator_confirmed 무효화 ───
        _fv_confirmed_raw = st.session_state.get("af_formula_confirmed_text", "")
        _fv_current_raw   = (_af_formula or "").strip()
        if _fv_confirmed_raw and _fv_current_raw != _fv_confirmed_raw:
            st.session_state.pop("af_formula_confirmed_text", None)
            st.session_state.pop("af_formula_validation", None)
            if st.session_state.get("af_contract"):
                st.session_state["af_contract"]["formula_status"] = "pending_validation"

        # ── CA-3-1: ai_suggested 수정 감지 → pending_validation 복귀 ───
        _fv_ai_suggested_raw = st.session_state.get("af_formula_ai_suggested_text", "")
        if _fv_ai_suggested_raw and _fv_current_raw != _fv_ai_suggested_raw:
            st.session_state.pop("af_formula_ai_suggested_text", None)
            st.session_state.pop("af_formula_validation", None)
            if st.session_state.get("af_contract"):
                st.session_state["af_contract"]["formula_status"] = "pending_validation"

        # ── CA-2-6-2: Formula 검증 / 확정 버튼 ─────────────────────────
        _fv_stored = st.session_state.get("af_formula_validation")
        _fv_passed = (
            _fv_stored is not None
            and _fv_stored.get("valid", False)
            and not any(s.get("match") is False for s in _fv_stored.get("sample_results", []))
        )
        _fv_col1, _fv_col2 = st.columns([1, 1])
        if _fv_col1.button("🔍 Formula 검증", key="af_formula_validate"):
            _fv_raw = (_af_formula or "").strip()
            if not _fv_raw:
                st.warning("Formula를 입력한 후 검증하세요.")
                st.session_state.pop("af_formula_validation", None)
                _fv_passed = False
            else:
                try:
                    _fv_formula_parsed = json.loads(_fv_raw)
                except Exception:
                    _fv_formula_parsed = _fv_raw
                _fv_in_list = [f.strip() for f in (_af_input_fields or "").split(",") if f.strip()]
                _fv_schema  = {f: "number" for f in _fv_in_list}
                _fv_tc = []
                _fv_tc_raw = (_af_test_cases or "").strip()
                if _fv_tc_raw:
                    try:
                        _fv_tc_parsed = json.loads(_fv_tc_raw)
                        if isinstance(_fv_tc_parsed, list):
                            _fv_tc = _fv_tc_parsed
                    except Exception:
                        pass
                from modules.formula_engine import validate_formula_with_samples as _vfws
                _fv_result = _vfws(_fv_formula_parsed, _fv_schema, _fv_tc or None)
                st.session_state["af_formula_validation"] = _fv_result
                _fv_stored = _fv_result
                _fv_passed = (
                    _fv_result.get("valid", False)
                    and not any(s.get("match") is False
                                for s in _fv_result.get("sample_results", []))
                )
                if st.session_state.get("af_contract"):
                    st.session_state["af_contract"]["formula_status"] = "pending_validation"
                st.session_state.pop("af_formula_confirmed_text", None)

        if _fv_col2.button(
            "✅ Formula 확정",
            key="af_formula_confirm",
            disabled=not _fv_passed,
            help="Formula 검증을 먼저 실행하고 통과해야 확정할 수 있습니다." if not _fv_passed else None,
        ):
            st.session_state["af_formula_confirmed_text"] = (_af_formula or "").strip()
            if st.session_state.get("af_contract"):
                st.session_state["af_contract"]["formula_status"] = "operator_confirmed"
            st.success("✅ Formula 운영자 확정 완료 — operator_confirmed")
            st.rerun()

        if _fv_stored is not None:
            _fv_valid   = _fv_stored.get("valid", False)
            _fv_msg     = _fv_stored.get("message", "")
            _fv_samples = _fv_stored.get("sample_results", [])
            _fv_failed  = [s for s in _fv_samples if s.get("match") is False]
            if _fv_passed:
                _fv_tc_info = f" | 테스트 케이스 {len(_fv_samples)}개 통과" if _fv_samples else ""
                st.success(f"✅ Formula 검증 통과 (Level 1/2/3){_fv_tc_info}")
            elif not _fv_valid:
                st.error(f"❌ Formula 검증 실패 (Level 1/2): {_fv_msg}")
            else:
                st.error(f"❌ Formula 검증 실패 (Level 3 — 기대값 불일치): {len(_fv_failed)}개")
                for _s in _fv_failed[:3]:
                    if _s.get("error"):
                        st.markdown(f"  - 입력 `{_s.get('input')}` → 오류: `{_s.get('error')}`")
                    else:
                        st.markdown(
                            f"  - 입력 `{_s.get('input')}` → "
                            f"예상 `{_s.get('expected')}` / 실제 `{_s.get('output')}`"
                        )

        if st.button("📋 Contract 기반 생성", key="af_gen_contract"):
            if not af_name.strip():
                st.error("계산기명은 필수입니다.")
            elif not _af_slug_pre.strip():
                st.error("Contract 모드에서는 확정 slug가 필수입니다.")
            elif not _af_input_fields.strip() or not _af_output_fields.strip():
                st.error("Contract 모드에서는 입력 필드와 출력 필드가 필수입니다.")
            else:
                import re as _re_contract
                _slug_clean = _af_slug_pre.strip().lower()
                if not _re_contract.match(r"^[a-z0-9][a-z0-9-]*$", _slug_clean):
                    st.error("slug는 영문 소문자·숫자·하이픈만 허용됩니다.")
                else:
                    _input_list = [f.strip() for f in _af_input_fields.split(",") if f.strip()]
                    _output_list = [f.strip() for f in _af_output_fields.split(",") if f.strip()]

                    _formula_val = None
                    _formula_raw = (_af_formula or "").strip()
                    if _formula_raw:
                        try:
                            _formula_val = json.loads(_formula_raw)
                        except Exception:
                            _formula_val = _formula_raw

                    _test_cases_val = []
                    _test_raw = (_af_test_cases or "").strip()
                    if _test_raw:
                        try:
                            _test_cases_val = json.loads(_test_raw)
                            if not isinstance(_test_cases_val, list):
                                st.error("테스트 케이스는 JSON 배열이어야 합니다.")
                                _test_cases_val = []
                        except Exception as _te:
                            st.error(f"테스트 케이스 파싱 실패: {_te}")
                            _test_cases_val = []

                    # CA-2-6-2: 이전 확정 상태 전달 — formula 미변경 시 operator_confirmed 보존
                    # Tier2-B는 날짜 계산 방법이 확정됐으므로 formula_status=operator_confirmed
                    _fv_prior_raw = st.session_state.get("af_formula_confirmed_text", "")
                    _fv_prior_status = (
                        "operator_confirmed"
                        if _af_is_tier2b or (_fv_prior_raw and _formula_raw == _fv_prior_raw)
                        else None
                    )
                    _contract = AF.build_contract(
                        slug=_slug_clean,
                        name=af_name.strip(),
                        category=af_cat or "",
                        tier="Tier2-B" if _af_is_tier2b else _tier_map_int_to_str.get(af_tier, "Tier2-A"),
                        input_fields=_input_list,
                        output_fields=_output_list,
                        # CA-1B-3-B P1: Registry prefill로 매핑된 scope_exclusions 전달 (없으면 빈 리스트)
                        scope_exclusions=list(
                            st.session_state.get("af_contract_scope_exclusions") or []),
                        # CA-1B-4 P1-D: Registry legal_refs 전달 (HOLD-3/Type D/P1-B 분류용)
                        legal_refs=list(
                            st.session_state.get("af_contract_legal_refs") or []),
                        formula=_formula_val,
                        formula_status=_fv_prior_status,
                        test_cases=_test_cases_val,
                        desc=af_desc or "",
                    )
                    st.session_state["af_contract"] = _contract

                    # ── Pre-generation Soft Gate (HOLD-1/2/3) ────────────────
                    _hold = AF.check_hold_rules(_contract)
                    for _hm in _hold["messages"]:
                        st.warning(f"⚠️ {_hm}")

                    with st.spinner("Contract 기반으로 AI가 계산기를 생성 중입니다... (수십 초)"):
                        try:
                            st.session_state["af_result"] = AF.generate_app_with_contract(cfg, _contract)
                        except Exception as e:
                            st.session_state["af_result"] = None
                            st.session_state.pop("af_contract", None)
                            st.error(f"생성 실패: {e}")

    app = st.session_state.get("af_result")
    if app:
        _tier_label = "Tier2 (단순)" if app.get("tier", 2) == 2 else "Tier1 (복잡)"
        st.success(f"생성 완료 — 토큰 {app['_tokens']} | {_tier_label}")
        if not app.get("_formula_valid", True):
            st.error(f"⚠️ 수식 검증 실패: {app.get('_formula_msg', '')}\n\n(저장은 가능하나 생성물 계산이 정상 동작하지 않을 수 있습니다. 운영자 확인 필요.)")
        st.write("**단계:** " + " → ".join(f"{s[0]}({s[1]})" for s in app["_steps"]))
        m = st.columns(4)
        m[0].metric("HTML 길이", len(app["html"]))
        m[1].metric("FAQ 수", len(app["faq"]) if isinstance(app["faq"], list) else 0)
        m[2].metric("계산기 유형", app["calculator_type"])
        m[3].metric("formula 타입", "dict(복수출력)" if isinstance(app.get("formula"), dict) else "str(단일)")
        st.text_input("SEO 제목", app["seo_title"], disabled=True, key="af_seo")
        with st.expander("입력/출력 스키마"):
            st.json({"input": app["input_schema"], "output": app["output_schema"]})
        with st.expander("HTML 코드"):
            st.code(app["html"][:4000], language="html")
        with st.expander("FAQ / 블로그 초안"):
            st.write(app["faq"]); st.write(app.get("blog_draft", ""))
        if app["html"]:
            with st.expander("🔎 실제 렌더 미리보기"):
                import streamlit.components.v1 as components
                components.html(app["html"], height=420, scrolling=True)

        # ── Contract 검증 결과 패널 (Mode B에서만 표시) ─────────────────
        _cv = app.get("_contract_validation")
        if _cv is not None:
            _contract_obj = app.get("_contract", {})
            st.markdown("---")
            st.subheader("📋 Contract 검증 결과")
            if _cv.get("valid"):
                st.success("✅ Contract 검증 통과 — slug / schema / formula 모두 일치합니다.")
            else:
                st.error(
                    "⛔ Contract 불일치 — 저장이 차단됩니다.\n\n"
                    "아래 내용을 확인하고 Contract를 수정하거나 재생성하세요."
                )

            _cv_col1, _cv_col2 = st.columns(2)
            with _cv_col1:
                # Slug 비교
                _slug_icon = "✅" if not _cv.get("slug_mismatch") else "❌"
                st.markdown(f"**{_slug_icon} Slug**")
                st.markdown(
                    f"- Contract: `{_cv.get('slug_contract', '')}`  \n"
                    f"- AI 결과: `{_cv.get('slug_ai') or '(AI가 slug 미반환)'}`"
                )

                # Formula 비교
                _form_icon = "✅" if not _cv.get("formula_changed") else "❌"
                st.markdown(f"**{_form_icon} Formula**")
                if _cv.get("formula_changed"):
                    st.markdown("- AI가 Contract 확정 formula를 변경했습니다.")
                elif _contract_obj.get("formula") is None:
                    st.markdown("- _(Formula Contract 미지정 — 비교 생략)_")
                else:
                    st.markdown("- AI가 Contract formula를 그대로 유지했습니다.")

            with _cv_col2:
                # Schema 비교
                _drift = _cv.get("schema_drift", {})
                _schema_icon = "✅" if not _drift.get("drifted") else "❌"
                st.markdown(f"**{_schema_icon} Schema (입력/출력 필드)**")
                if _drift.get("drifted"):
                    for _ch in (_drift.get("changes") or []):
                        _t = _ch.get("type", "")
                        if "missing" in _t:
                            st.markdown(f"- ❌ 누락: `{_ch.get('contract')}`")
                        elif "extra" in _t:
                            st.markdown(f"- ⚠️ 추가: `{_ch.get('ai')}`")
                else:
                    _in_cnt = len(_contract_obj.get("input_fields") or [])
                    _out_cnt = len(_contract_obj.get("output_fields") or [])
                    st.markdown(f"- 입력 {_in_cnt}개 / 출력 {_out_cnt}개 모두 일치")

            # 테스트 케이스 샘플 검증 (test_cases 있을 때)
            # validate_formula_with_samples() → {"valid": bool, "message": str, "sample_results": [...]}
            _test_cases = _contract_obj.get("test_cases") or []
            if _test_cases and app.get("formula"):
                from modules.formula_engine import validate_formula_with_samples
                _tc_result = validate_formula_with_samples(
                    app.get("formula", ""),
                    app.get("input_schema", {}),
                    _test_cases,
                )
                _tc_valid = _tc_result.get("valid", False)
                _tc_samples = _tc_result.get("sample_results", [])
                _tc_failed = [s for s in _tc_samples if s.get("match") is False]
                _tc_passed_all = _tc_valid and len(_tc_failed) == 0
                _tc_icon = "✅" if _tc_passed_all else "❌"
                st.markdown(f"**{_tc_icon} 테스트 케이스 ({len(_test_cases)}개)**")
                if _tc_passed_all:
                    st.markdown(f"- {len(_test_cases)}개 모두 통과")
                elif not _tc_valid:
                    st.markdown(f"- formula 검증 실패: {_tc_result.get('message', '')}")
                else:
                    st.markdown(f"- {len(_tc_failed)}개 불일치")
                    for _s in _tc_failed:
                        st.markdown(
                            f"  - 입력 `{_s.get('input')}` → "
                            f"예상 `{_s.get('expected')}` / 실제 `{_s.get('output')}`"
                        )

            if _cv.get("messages"):
                with st.expander("상세 불일치 내용"):
                    for _m in _cv["messages"]:
                        st.markdown(f"- {_m}")

        # Slug 자동생성: 새 앱 생성 시 또는 af_slug 공백이면 자동완성
        # Mode B에서는 Contract 확정 slug를 우선 사용
        _contract_slug_pre = (st.session_state.get("af_contract") or {}).get("slug", "")
        _af_auto_slug = _contract_slug_pre or generate_slug(app.get("name", ""))
        if app.get("name") != st.session_state.get("_af_last_slug_for"):
            st.session_state["af_slug"] = _af_auto_slug
            st.session_state["_af_last_slug_for"] = app.get("name", "")
        elif not st.session_state.get("af_slug") and _af_auto_slug:
            st.session_state["af_slug"] = _af_auto_slug
        af_slug = st.text_input(
            "영문 slug * (폴더·URL·내부 식별자 — 저장 후 변경 불가)",
            key="af_slug",
            help="영문 소문자·숫자·하이픈만. 한글/공백 불가. 대시보드 표시는 계속 한글 이름(name)을 사용합니다.")
        # slug 중복 확인 (D: 생성 단계에서 실시간 차단)
        _slug_to_check = (af_slug or "").strip().lower()
        if _slug_to_check:
            import re as _re_slug_chk
            if _re_slug_chk.match(r"^[a-z0-9][a-z0-9-]*$", _slug_to_check):
                _, _slug_conflict, _slug_msg = RC.check_slug_conflict(_slug_to_check, cfg)
                if _slug_conflict:
                    st.error(f"⛔ 슬러그 중복: {_slug_msg}")
                else:
                    st.success(f"✅ 슬러그 사용 가능: '{_slug_to_check}'")
            else:
                st.warning("영문 소문자·숫자·하이픈만 사용 가능합니다.")

        # ── Contract 저장 차단 상태 사전 판정 ────────────────────────
        _cv_for_save = app.get("_contract_validation")
        _contract_validation_failed = (
            _cv_for_save is not None and not _cv_for_save.get("valid", True)
        )
        # CA-1B-4 P1-C: Mode B(Contract 기반)는 operator_confirmed 상태에서만 저장 허용
        _contract_for_save = app.get("_contract") or {}
        _fs_for_save = _contract_for_save.get("formula_status")
        _fs_not_confirmed = bool(_contract_for_save) and _fs_for_save != "operator_confirmed"
        _contract_save_blocked = _contract_validation_failed or _fs_not_confirmed

        # ── 액션 버튼: 저장 / 폐기 ──────────────────────────────────
        _btn_save_col, _btn_discard_col = st.columns([3, 2])
        if _btn_save_col.button(
            "💾 calculators + app_templates 저장",
            type="primary",
            key="af_save",
            disabled=_contract_save_blocked,
            help=(
                "Contract 불일치로 저장이 차단됩니다. "
                "Contract를 수정하거나 재생성하세요."
            ) if _contract_validation_failed else (
                f"🔒 저장하려면 Formula 검증 통과 후 Operator Confirm이 필요합니다. "
                f"현재 상태: {_fs_for_save}"
            ) if _fs_not_confirmed else None,
        ):
            import re as _re_slug
            slug_in = (af_slug or "").strip().lower()
            if not _re_slug.match(r"^[a-z0-9][a-z0-9-]*$", slug_in):
                st.error("영문 slug를 입력하세요 — 소문자·숫자·하이픈만 (예: annual-tax-settlement). "
                         "한글/공백/대문자 불가.")
            else:
                ok, msg = AF.save_app(cfg, app, slug=slug_in)
                if ok:
                    st.session_state["af_result"] = None
                    st.session_state.pop("af_contract", None)
                    st.session_state["af_just_saved_name"] = app.get("name", "")
                    st.success(f"{msg} — 사이드바에서 '🧮 계산기 관리'로 이동해 확인하세요.")
                    st.rerun()
                else:
                    st.error(msg)

        if _contract_save_blocked:
            if _fs_not_confirmed and not _contract_validation_failed:
                st.error(
                    f"🔒 저장하려면 Formula 검증 통과 후 Operator Confirm이 필요합니다. "
                    f"현재 Formula 상태: {_fs_for_save}."
                )
            else:
                st.error(
                    "⛔ Contract 불일치로 저장이 차단됩니다. "
                    "Contract 폼을 수정하고 [📋 Contract 기반 생성]을 다시 실행하세요."
                )

        if _btn_discard_col.button("🗑️ 생성 결과 폐기 & 초기화", key="af_discard"):
            st.session_state["af_discard_confirm"] = True
            st.rerun()

        # ── 폐기 확인 대화창 ─────────────────────────────────────────
        if st.session_state.get("af_discard_confirm"):
            st.warning(
                "⚠️ 현재 생성된 계산기 결과를 폐기하고 입력 화면을 초기화합니다.\n\n"
                "저장하지 않은 AI 생성 결과, Formula, Schema, Contract 확정 스펙 및 "
                "검증 결과가 초기화됩니다.\n\n"
                "계속하시겠습니까?"
            )
            _dc1, _dc2, _dc_rest = st.columns([2, 1, 4])
            if _dc1.button("⚠️ 폐기하고 초기화", type="primary", key="af_discard_ok"):
                for _dk in AF.AF_SESSION_DISCARD_KEYS:
                    st.session_state.pop(_dk, None)
                st.rerun()
            if _dc2.button("취소", key="af_discard_cancel"):
                st.session_state.pop("af_discard_confirm", None)
                st.rerun()

# ══════════════════════════════════════════════════════════════
# 탭: 💬 AI Workspace (대시보드 내 AI 대화 + 파일/데이터 도구)
# ══════════════════════════════════════════════════════════════
elif tab == "💬 AI Workspace":
    st.title("💬 AI Workspace")
    from modules import ai_workspace as WS
    role_map = {"총괄 (GPT)": "orchestrator", "코드 (Claude)": "code", "리서치 (Gemini)": "research"}
    role_label = st.selectbox("역할 / 모델", list(role_map.keys()), key="ws_role")
    role = role_map[role_label]

    with st.expander("📎 컨텍스트 첨부 (선택)"):
        try:
            files = WS.list_project_files()
        except Exception:
            files = []
        attach_file = st.selectbox("프로젝트 파일(읽기)", ["(없음)"] + files, key="ws_file")
        attach_repo = st.selectbox("Repository/시트 데이터", ["(없음)", "sites", "calculators", "articles", "templates"], key="ws_repo")
        attach_struct = st.checkbox("프로젝트 구조 요약", key="ws_struct")

    if "ws_msgs" not in st.session_state:
        st.session_state["ws_msgs"] = []
    for msg in st.session_state["ws_msgs"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("메시지 입력 (예: 퇴직금 계산기 HTML 만들어줘 / main.py 구조 분석해줘)")
    if prompt:
        ctx = ""
        try:
            if attach_file != "(없음)":
                ctx += f"# 파일: {attach_file}\n{WS.read_project_file(attach_file)}\n\n"
            if attach_repo != "(없음)":
                ctx += f"# {attach_repo} 데이터(최대 20행)\n{str(WS.query_repo(cfg, attach_repo)[:20])}\n\n"
            if attach_struct:
                ctx += f"# 프로젝트 구조\n{WS.analyze_structure()['by_dir']}\n\n"
        except Exception as e:
            ctx += f"(컨텍스트 첨부 실패: {e})"
        st.session_state["ws_msgs"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("생각 중..."):
                try:
                    reply, model, tok = WS.chat(cfg, role, st.session_state["ws_msgs"], ctx)
                except Exception as e:
                    reply, model, tok = f"오류: {e}", "", 0
            st.markdown(reply)
            st.caption(f"{model} · {tok} tokens")
        st.session_state["ws_msgs"].append({"role": "assistant", "content": reply})

    st.divider()
    with st.expander("💾 코드/파일 저장 도구"):
        st.caption("기본은 샌드박스(data/workspace/)에 저장. 프로젝트 파일 덮어쓰기는 원본 백업 후 확인 시에만.")
        fname = st.text_input("파일명", "generated.html", key="ws_save_name")
        fcontent = st.text_area("내용", height=200, key="ws_save_content")
        if st.button("샌드박스 저장", key="ws_sb_save"):
            if fcontent.strip():
                st.success(f"저장: {WS.write_workspace_file(fname, fcontent)}")
            else:
                st.error("내용이 비어 있습니다.")
        st.markdown("---")
        st.caption("⚠️ 고급: 프로젝트 파일 덮어쓰기 (원본 자동 백업)")
        tgt = st.text_input("대상 경로 (예: data/workspace/x.py)", key="ws_tgt")
        confirm = st.checkbox("이 경로 덮어쓰기를 확인합니다", key="ws_confirm")
        if st.button("프로젝트 파일 저장", key="ws_proj_save"):
            if confirm and tgt.strip() and fcontent.strip():
                try:
                    st.success(f"저장(백업됨): {WS.write_project_file(tgt, fcontent)}")
                except Exception as e:
                    st.error(f"실패: {e}")
            else:
                st.error("대상 경로/내용/확인 체크가 필요합니다.")
    if st.button("🗑 대화 초기화", key="ws_clear"):
        st.session_state["ws_msgs"] = []; st.rerun()

# ══════════════════════════════════════════════════════════════
# 탭: 📊 AI Pipeline Monitor
# ══════════════════════════════════════════════════════════════
elif tab == "📊 AI Pipeline":
    st.title("📊 AI Pipeline Monitor")
    st.caption("pipeline.log 기반 단계 상태(비침습적). 파이프라인 실행 중 자동 반영.")
    from modules.pipeline_status import get_pipeline_state
    ps = get_pipeline_state(cfg)
    COLOR = {"pending": "🟡", "running": "🔵", "completed": "🟢", "error": "🔴"}
    cols = st.columns(len(ps["stages"]))
    for col, s in zip(cols, ps["stages"]):
        with col.container(border=True):
            st.markdown(f"### {COLOR.get(s['status'], '⬜')}")
            st.markdown(f"**{s['name']}**")
            st.caption(f"모델: {s['model']}")
            st.caption(f"상태: {s['status']}")
    st.divider()
    m = st.columns(3)
    m[0].metric("오늘 비용", f"${ps['cost_today']:.4f}")
    m[1].metric("오늘 토큰", f"{ps['tokens_today']:,}")
    m[2].metric("실행 상태", "🔴 오류" if ps["has_error"] else ("✅ 완료/대기" if ps["finished"] else "🔵 진행중"))
    if ps["model_costs"]:
        st.subheader("오늘 모델별 비용")
        import pandas as pd
        st.dataframe(pd.DataFrame([{"모델": k, "비용($)": v} for k, v in ps["model_costs"].items()]),
                     hide_index=True, use_container_width=True)
    st.subheader("최근 로그")
    st.code("\n".join(ps["last_lines"]) or "(로그 없음)", language="text")

# ══════════════════════════════════════════════════════════════
# 탭: 🤖 AI Assistant (운영비서 — 채팅/파일도구/메모리/태스크/분석)
# ══════════════════════════════════════════════════════════════
elif tab == "🤖 AI Assistant":
    st.title("🤖 AI Assistant — 운영비서")
    st.caption("채팅으로 프로젝트 분석·개선·수정. 파일 쓰기는 승인 후에만, 워크스페이스 내부 한정(삭제/시스템명령 불가).")
    from modules import ai_assistant as AS

    model_label = st.selectbox("모델", list(AS.CHAT_MODELS.keys()), key="asst_model")
    qc = st.columns(4)
    preset_labels = ["현재 프로젝트 분석해", "App Factory 분석해", "문제점 찾아", "개선안 제안해"]
    quick = None
    for i, lab in enumerate(preset_labels):
        if qc[i].button(lab, key=f"asst_qc_{i}"):
            quick = lab

    if "asst_msgs" not in st.session_state:
        st.session_state["asst_msgs"] = []
    for m in st.session_state["asst_msgs"]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    prompt = st.chat_input("명령/질문 (예: config 수정해, 새 계산기 추가해, 최근 오류 분석해)") or quick
    if prompt:
        st.session_state["asst_msgs"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("분석 중..."):
                try:
                    reply, model, tok = AS.chat(cfg, model_label, st.session_state["asst_msgs"])
                except Exception as e:
                    reply, model, tok = f"오류: {e}", "", 0
            st.markdown(reply)
            st.caption(f"{model} · {tok} tokens")
        st.session_state["asst_msgs"].append({"role": "assistant", "content": reply})

    st.divider()
    # ── 파일 수정/생성 (승인 게이트) ──
    with st.expander("📝 파일 수정/생성 (변경 미리보기 → 승인 후 저장)"):
        st.caption("워크스페이스 내부만. write 시 원본 자동 백업(data/assistant/backups/).")
        fpath = st.text_input("대상 경로", "data/workspace/example.txt", key="asst_path")
        fcontent = st.text_area("새 내용 (AI 답변에서 복사 가능)", height=200, key="asst_content")
        if st.button("🔍 변경 미리보기", key="asst_preview"):
            try:
                st.session_state["asst_diff"] = AS.propose_diff(fpath, fcontent)
            except Exception as e:
                st.error(str(e))
        diff = st.session_state.get("asst_diff")
        if diff and diff["path"] == fpath:
            st.write(f"{'✏️ 덮어쓰기' if diff['exists'] else '🆕 신규 생성'} — "
                     f"기존 {diff['old_len']}자 → 새 {diff['new_len']}자")
            if diff["exists"]:
                with st.expander("기존 내용 보기"):
                    st.code(diff["old"][:3000])
            c1, c2 = st.columns(2)
            if c1.button("✅ 승인 후 저장", type="primary", key="asst_apply"):
                try:
                    path = AS.write_file(fpath, fcontent) if diff["exists"] else AS.create_file(fpath, fcontent)
                    st.success(f"저장 완료: {path}")
                    st.session_state.pop("asst_diff", None)
                except Exception as e:
                    st.error(f"저장 실패: {e}")
            if c2.button("취소", key="asst_cancel"):
                st.session_state.pop("asst_diff", None); st.rerun()

    # ── 워크스페이스 탐색/읽기 ──
    with st.expander("📂 워크스페이스 탐색/읽기"):
        d = st.text_input("디렉터리", ".", key="asst_ls")
        try:
            for it in AS.list_directory(d):
                st.caption(("📁 " if it["type"] == "dir" else "📄 ") + it["path"])
        except Exception as e:
            st.error(str(e))
        rf = st.text_input("파일 읽기 경로", "modules/app_factory.py", key="asst_rf")
        if st.button("읽기", key="asst_rfb"):
            try:
                st.code(AS.read_file(rf, 8000))
            except Exception as e:
                st.error(str(e))

    # ── Memory ──
    with st.expander("🧠 Memory (운영규칙 / TODO / 개발기록)"):
        mem = AS.load_memory()
        k = st.selectbox("종류", ["rules", "todo", "dev_log"], key="asst_mk")
        nt = st.text_input("추가 내용", key="asst_mt")
        if st.button("메모리 추가", key="asst_ma") and nt.strip():
            AS.add_memory(k, nt); st.rerun()
        for kk in ["rules", "todo", "dev_log"]:
            items = mem.get(kk, [])
            if items:
                st.markdown(f"**{kk}** ({len(items)})")
                for it in items[-10:]:
                    st.caption("• " + it["text"])

    # ── Task (Lite) ──
    with st.expander("✅ Task (Lite: 상태만)"):
        nt2 = st.text_input("새 태스크", key="asst_tt")
        if st.button("태스크 추가", key="asst_ta") and nt2.strip():
            AS.add_task(nt2); st.rerun()
        for t in AS.load_tasks()[-15:]:
            cols = st.columns([3, 2])
            cols[0].caption(t["title"])
            ns = cols[1].selectbox("상태", AS.TASK_STATUS,
                                   index=AS.TASK_STATUS.index(t["status"]) if t["status"] in AS.TASK_STATUS else 0,
                                   key="asst_ts_" + t["id"], label_visibility="collapsed")
            if ns != t["status"]:
                AS.set_task_status(t["id"], ns); st.rerun()

    if st.button("🗑 대화 초기화", key="asst_clear"):
        st.session_state["asst_msgs"] = []; st.rerun()

# ══════════════════════════════════════════════════════════════
# 탭: 🧠 전략회의실 (AI 운영 분석)
# ══════════════════════════════════════════════════════════════
elif tab == "🧠 전략회의실":
    st.title("🧠 전략회의실")
    st.caption(
        f"분석 모델: `{cfg.get('ORCHESTRATOR_PROVIDER','openai')} / "
        f"{cfg.get('MODEL_ORCHESTRATOR','gpt-4o')}` · "
        f"AI가 최근 운영 데이터를 분석해 카테고리·RSS·발행시간·수익화 전략을 추천합니다 (실행만, 직접 적용 안 함)."
    )

    enabled = cfg.get("ENABLE_STRATEGY_ROOM", True)
    if not enabled:
        st.warning("⚠️ `ENABLE_STRATEGY_ROOM` 설정이 꺼져 있습니다. '🔧 설정 → 운영 설정'에서 켜주세요.")

    if st.button("▶ 전략회의실 실행", type="primary", disabled=not enabled):
        with st.spinner("AI가 최근 운영 데이터를 분석 중입니다..."):
            # ── 운영 데이터 수집 (가능한 범위, 실패해도 빈 값으로 진행) ──
            analytics = {}
            try:
                posts = cached_posts()
                published = [p for p in posts if p.get("상태값") in ("발행완료", "검수대기")]
                published.sort(key=lambda x: x.get("발행일시", ""), reverse=True)
                analytics["total_published"] = len(published)
                analytics["recent_posts"] = [
                    {"title": p.get("최종추천제목", ""), "url": p.get("발행 URL", ""),
                     "date": p.get("발행일시", "")}
                    for p in published[:7]
                ]
            except Exception as e:
                st.info(f"운영 데이터 일부 수집 실패 — 빈 값으로 진행합니다: {e}")

            try:
                from modules.strategy_room import run_strategy_room
                st.session_state["strategy_result"] = run_strategy_room(analytics, cfg)
            except Exception as e:
                st.session_state["strategy_result"] = {}
                st.error(f"전략회의실 실행 중 오류: {e}")

    result = st.session_state.get("strategy_result")
    if result is not None:
        if not result:
            st.error(
                "전략회의실이 빈 결과를 반환했습니다. "
                "LLM이 올바른 JSON을 반환하지 못했거나 설정이 꺼져 있을 수 있습니다. "
                "잠시 후 다시 실행해 보세요. ('📡 실시간 로그'에서 상세 확인 가능)"
            )
        else:
            st.divider()
            st.subheader("📝 요약")
            st.write(result.get("summary", "(요약 없음)"))

            ate = result.get("auto_topic_expansion_eligible", {}) or {}
            if ate:
                st.subheader("🚦 AUTO_TOPIC_EXPANSION 전환 조건")
                cols = st.columns(5)
                labels = [
                    ("애드센스 발행", "condition_1_adsense_post"),
                    ("게시물 수",     "condition_2_post_count"),
                    ("CTR",          "condition_3_ctr"),
                    ("긍정 추천",     "condition_4_positive_recommendation"),
                    ("전체 충족",     "all_met"),
                ]
                for col, (lab, key) in zip(cols, labels):
                    col.metric(lab, "✅" if ate.get(key) else "❌")

            def _show_list(title, items):
                st.subheader(title)
                if items:
                    st.write(items)
                else:
                    st.caption("추천 없음")

            _show_list("🆕 신규 카테고리 후보",   result.get("new_category_candidates", []))
            _show_list("📡 RSS 수집원 추천",      result.get("rss_recommendations", []))
            _show_list("♻️ 리라이팅 후보",        result.get("rewrite_candidates", []))
            _show_list("⏰ 최적 발행 시간대",      result.get("best_publish_time", []))

            st.subheader("💰 수익화 제안")
            mon = result.get("monetization_suggestions")
            st.write(mon if mon else "추천 없음 (ADSENSE_MODE=pre이면 비활성)")

            st.caption(f"사용 토큰: {result.get('_tokens', '-')}")
            with st.expander("🔧 원본 JSON 보기"):
                st.json(result)

# ══════════════════════════════════════════════════════════════
# 탭 5: 설정 ★ [팅김 버그 완치 검수 완료]
# ══════════════════════════════════════════════════════════════
elif tab == "🔧 설정":
    st.title("🔧 설정 관리")
    st.info("모든 모델 세팅을 마우스 클릭으로 제어하세요.")

    cfg_path = BASE / "config" / "config.yaml"

    with st.expander("🔑 AI API Keys", expanded=False):
        openai_key = st.text_input("OpenAI API Key", value=cfg.get("OPENAI_API_KEY",""), type="password", key="s_openai")
        claude_key = st.text_input("Claude API Key", value=cfg.get("CLAUDE_API_KEY",""), type="password", key="s_claude")
        gemini_key = st.text_input("Gemini API Key", value=cfg.get("GEMINI_API_KEY",""), type="password", key="s_gemini")

    # ── 1. 텍스트 AI 모델 설정 ──────────────────────────────
    with st.expander("🤖 최신 텍스트 AI 역할 및 모델 매칭", expanded=True):
        providers_list = ["openai", "claude", "gemini"]
        model_presets = {
            "openai": ["gpt-4o", "gpt-4o-mini"],
            "claude": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
            "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"]
        }

        def render_model_selector(label, provider_val, current_model, key_prefix):
            st.markdown(f"**{label}**")
            col_p, col_m = st.columns(2)
            with col_p:
                p_idx = providers_list.index(provider_val) if provider_val in providers_list else 0
                chosen_provider = st.selectbox(f"{label} 제공사", providers_list, index=p_idx, key=f"{key_prefix}_prov", label_visibility="collapsed")
            with col_m:
                presets = model_presets.get(chosen_provider, ["gpt-4o"])
                # 현재 모델이 프리셋에 있으면 그 항목을, 없으면 첫 항목을 기본 선택
                m_idx = presets.index(current_model) if current_model in presets else 0
                    
                chosen_model = st.selectbox(f"{label} 모델명", presets, index=m_idx, key=f"{key_prefix}_model", label_visibility="collapsed")
            return chosen_provider, chosen_model

        orch_prov, orch_mod = render_model_selector("1. 전체 총괄 (Orchestrator)", cfg.get("ORCHESTRATOR_PROVIDER", "openai"), cfg.get("MODEL_ORCHESTRATOR", "gpt-4o"), "s_orch")
        plan_prov, plan_mod = render_model_selector("2. 키워드 기획 (Planner)", cfg.get("PLANNER_PROVIDER", "openai"), cfg.get("MODEL_PLANNER", "gpt-4o"), "s_plan")
        writ_prov, writ_mod = render_model_selector("3. 본문 초고 작성 (Writer)", cfg.get("WRITER_PROVIDER", "openai"), cfg.get("MODEL_WRITER", "gpt-4o"), "s_write")
        edit_prov, edit_mod = render_model_selector("4. SEO 교정 및 검수 (Editor)", cfg.get("EDITOR_PROVIDER", "claude"), cfg.get("MODEL_EDITOR", "claude-sonnet-4-6"), "s_edit")

        st.markdown("---")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            clean_mod = st.selectbox("뉴스 정리기 (Cleaner) 모델", model_presets["openai"], index=0, key="s_clean_mod")
        with col_s2:
            fb_mod = st.selectbox("교정 실패시 백업 (Fallback) 모델", model_presets["openai"], index=0, key="s_fb_mod")

    # ── 2. 🎨 이미지 생성 AI 설정 섹션 [팅김 방지 완벽 방어형 인덱싱 코드] ──────────────────────────────
    with st.expander("🎨 블로그 이미지 생성 AI 설정", expanded=True):
        st.markdown("### 썸네일 및 본문 삽입용 이미지 옵션")
        
        img_providers = ["free_pollinations", "gemini", "openai"]
        img_presets = {
            "free_pollinations": ["무료 이미지 엔진 (API키/결제 없음)"],
            "gemini": ["imagen-3.0-generate-002"],
            "openai": ["dall-e-3"]
        }
        
        col_img1, col_img2 = st.columns(2)
        with col_img1:
            curr_img_prov = str(cfg.get("IMAGE_PROVIDER", "free_pollinations")).lower()
            # 팅김 원천 방지: 리스트에 존재하지 않는 값이 들어올 경우 무조건 0번(무료엔진)으로 매핑
            img_prov_idx = img_providers.index(curr_img_prov) if curr_img_prov in img_providers else 0
            image_provider = st.selectbox("이미지 AI 제공사 (구글 무료 계정은 'free_pollinations' 필수)", img_providers, index=img_prov_idx, key="s_img_prov")
        with col_img2:
            curr_img_mod = cfg.get("MODEL_IMAGE", "")
            img_models = img_presets.get(image_provider, ["무료 이미지 엔진 (API키/결제 없음)"])
            img_mod_idx = img_models.index(curr_img_mod) if curr_img_mod in img_models else 0
            image_model = st.selectbox("이미지 생성 모델명", img_models, index=img_mod_idx, key="s_img_mod")
            
        st.markdown("---")
        col_size, col_quality = st.columns(2)
        with col_size:
            size_options = ["auto (🤖 AI 자동 판단)", "1024x1024", "1792x1024 (가로형)"]
            curr_size = cfg.get("IMAGE_SIZE", "auto")
            if curr_size == "auto": size_idx = 0
            elif curr_size == "1024x1024": size_idx = 1
            else: size_idx = 2
            image_size_raw = st.selectbox("이미지 비율/사이즈", size_options, index=size_idx, key="s_img_size")
            image_size = "auto" if "auto" in image_size_raw else "1024x1024" if "1024x1024" in image_size_raw else "1792x1024"
        with col_quality:
            image_quality = st.selectbox("품질 등급 (DALL-E 전용)", ["standard", "hd"], index=0 if cfg.get("IMAGE_QUALITY", "standard") == "standard" else 1)

    # ── Google 및 운영 세팅 연동 ──────────────────────────────────
    with st.expander("📊 Google 연동", expanded=False):
        g_sheet = st.text_input("GOOGLE_SHEET_ID", value=cfg.get("GOOGLE_SHEET_ID",""), key="s_sheet")
        g_drive = st.text_input("GOOGLE_DRIVE_ROOT_ID", value=cfg.get("GOOGLE_DRIVE_ROOT_ID",""), key="s_drive")
        g_placeholder = st.text_input("GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID", value=cfg.get("GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID",""), key="s_ph")

    with st.expander("🌐 WordPress 연동", expanded=False):
        from modules import config_loader as _CL
        _ready = _CL.is_wordpress_ready(cfg)
        st.caption(("🟢 WordPress 연동됨" if _ready else "⚪ 미설정 — 발행은 '검수대기'로 대기(크래시 없음)"))
        wp_url = st.text_input("WORDPRESS_URL", value=cfg.get("WORDPRESS_URL",""),
                               placeholder="https://your-site.com", key="s_wpurl")
        wcol1, wcol2 = st.columns(2)
        wp_user = wcol1.text_input("WORDPRESS_USERNAME", value=cfg.get("WORDPRESS_USERNAME",""),
                                   placeholder="admin", key="s_wpuser")
        wp_pw = wcol2.text_input("WORDPRESS_APP_PASSWORD", type="password",
                                 value=cfg.get("WORDPRESS_APP_PASSWORD", cfg.get("WORDPRESS_PASSWORD","")),
                                 placeholder="xxxx xxxx xxxx xxxx", key="s_wppw")
        st.caption("앱 비밀번호=WordPress 관리자 → 사용자 → 프로필 → '애플리케이션 비밀번호' 생성. 일반 로그인 비번 아님.")
        if st.button("🔌 WordPress 연결 테스트", key="s_wptest"):
            _u = (wp_url or "").strip().rstrip("/")
            if not _u or not wp_user.strip() or not wp_pw.strip():
                st.warning("URL/사용자/앱 비밀번호를 모두 입력하세요.")
            else:
                try:
                    import requests
                    r = requests.get(f"{_u}/wp-json/wp/v2/users/me",
                                     auth=(wp_user.strip(), wp_pw.strip().replace(" ", "")), timeout=10)
                    if r.status_code == 200:
                        st.success(f"연결 성공 — 사용자: {r.json().get('name','?')}")
                    elif r.status_code in (401, 403):
                        st.error("인증 실패(401/403) — 사용자/앱 비밀번호 확인")
                    else:
                        st.error(f"응답 코드 {r.status_code} — URL/REST API 활성화 확인")
                except Exception as _e:
                    st.error(f"연결 실패: {_e}")

    with st.expander("⚙️ 운영 설정", expanded=False):
        st.markdown("**발행 방식** — Calculator는 수동 생성(App Factory/계산기 관리), Blog는 예약 발행(Blog Schedule)")
        operation_mode = "scheduled"
        st.caption("실행: 단발 → `scripts/run_pipeline.bat` · Blog 예약 발행 → '📝 Blog Schedule' 탭")
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            adsense_mode = st.selectbox("ADSENSE_MODE", ["pre","post"], index=["pre","post"].index(cfg.get("ADSENSE_MODE","pre")), key="s_adsense")
            st.metric("하루 발행 개수 (DAILY_POST_COUNT)", cfg.get("DAILY_POST_COUNT", 3))
            daily_count = cfg.get("DAILY_POST_COUNT", 3)
        with col2:
            daily_budget = st.number_input("DAILY_AI_BUDGET (USD)", 1, 100, cfg.get("DAILY_AI_BUDGET",5), key="s_db")
            monthly_budget = st.number_input("MONTHLY_AI_BUDGET (USD)", 10, 1000, cfg.get("MONTHLY_AI_BUDGET",100), key="s_mb")
            dlq_threshold = st.number_input("DLQ_THRESHOLD", 1, 10, cfg.get("DLQ_THRESHOLD",3), key="s_dlq")
        auto_topic = st.toggle("AUTO_TOPIC_EXPANSION", value=cfg.get("AUTO_TOPIC_EXPANSION",False), key="s_ate")
        enable_strategy = st.toggle("ENABLE_STRATEGY_ROOM", value=cfg.get("ENABLE_STRATEGY_ROOM",True), key="s_esr")

        st.divider()
        st.markdown("**📨 텔레그램 알림** (오류/예산경고/일일요약/발행승인)")
        tcol1, tcol2 = st.columns(2)
        tg_token = tcol1.text_input("TELEGRAM_BOT_TOKEN", value=cfg.get("TELEGRAM_BOT_TOKEN",""),
                                    type="password", placeholder="1234567890:ABC...", key="s_tgtoken")
        tg_chat = tcol2.text_input("TELEGRAM_CHAT_ID", value=cfg.get("TELEGRAM_CHAT_ID",""),
                                   placeholder="-1001234567890", key="s_tgchat")
        st.caption("봇 토큰=@BotFather로 생성 · Chat ID=@userinfobot 또는 그룹에 봇 초대 후 확인. 저장 후 아래 '테스트 전송'으로 확인.")
        if st.button("📤 텔레그램 테스트 전송", key="s_tgtest"):
            from modules import telegram_ops as _TG
            _tcfg = dict(cfg); _tcfg["TELEGRAM_BOT_TOKEN"] = tg_token.strip(); _tcfg["TELEGRAM_CHAT_ID"] = tg_chat.strip()
            if not tg_token.strip() or not tg_chat.strip():
                st.warning("토큰과 Chat ID를 먼저 입력하세요.")
            else:
                try:
                    _TG.notify(_tcfg, "✅ CalcMate 텔레그램 연결 테스트 — 정상")
                    st.success("전송 시도 완료. 텔레그램 메시지를 확인하세요(미수신 시 토큰/Chat ID 재확인).")
                except Exception as _e:
                    st.error(f"전송 실패: {_e}")
        st.markdown("**이벤트별 알림 ON/OFF**")
        _ev_def = cfg.get("TELEGRAM_EVENTS") or {}
        _EVENTS = [("error", "오류 발생"), ("budget", "비용 경고"),
                   ("daily_summary", "일일 요약"), ("publish_request", "발행 승인 요청"),
                   ("quality_critical_hold", "품질 HOLD(Critical)"), ("publish_success", "발행 완료")]
        _ecols = st.columns(len(_EVENTS))
        tg_events = {}
        for _i, (_k, _lbl) in enumerate(_EVENTS):
            tg_events[_k] = bool(_ecols[_i].toggle(_lbl, value=bool(_ev_def.get(_k, True)), key=f"s_tgev_{_k}"))
        st.caption("telegram_ops 경유 이벤트에 적용. 파이프라인 크리티컬 알림(오류/예산/헬스)은 항상 발송.")

    # ── 🎨 계산기 노출 설정 (Design v2) — SM_CONFIG 연동 ──
    with st.expander("🎨 계산기 노출 설정 (v2)"):
        st.caption("생성되는 계산기 앱의 노출/정책. 저장 시 config.yaml에 반영되어 재생성물에 적용됩니다. (UI/계산식 무변경)")
        _SITE_MODES = ["pre_adsense", "adsense", "cpa", "full"]
        _cur_sm = cfg.get("SITE_MODE", "pre_adsense")
        v2_site = st.selectbox("SITE_MODE", _SITE_MODES,
                               index=_SITE_MODES.index(_cur_sm) if _cur_sm in _SITE_MODES else 0,
                               help="pre_adsense=광고/CPA off · adsense=광고 · cpa=CPA · full=둘 다")
        _c = st.columns(3)
        v2_share = _c[0].toggle("SHOW_SHARE", value=bool(cfg.get("SHOW_SHARE", True)), key="v2_share")
        v2_pwa = _c[1].toggle("SHOW_PWA", value=bool(cfg.get("SHOW_PWA", True)), key="v2_pwa")
        v2_save = _c[2].toggle("SHOW_RESULT_SAVE", value=bool(cfg.get("SHOW_RESULT_SAVE", True)), key="v2_save")
        _c2 = st.columns(3)
        v2_faq = _c2[0].toggle("SHOW_FAQ", value=bool(cfg.get("SHOW_FAQ", True)), key="v2_faq")
        v2_notice = _c2[1].toggle("SHOW_NOTICE", value=bool(cfg.get("SHOW_NOTICE", True)), key="v2_notice")
        v2_related = _c2[2].toggle("SHOW_RELATED", value=bool(cfg.get("SHOW_RELATED", True)), key="v2_related")
        _c3 = st.columns(3)
        v2_detail = _c3[0].toggle("SHOW_DETAIL", value=bool(cfg.get("SHOW_DETAIL", True)), key="v2_detail")
        v2_ads = _c3[1].toggle("SHOW_ADSENSE(오버라이드)", value=bool(cfg.get("SHOW_ADSENSE", False)), key="v2_ads")
        v2_cpa = _c3[2].toggle("SHOW_CPA(오버라이드)", value=bool(cfg.get("SHOW_CPA", False)), key="v2_cpa")
        _c4 = st.columns(2)
        _EXP = ["png", "pdf", "both", "none"]
        _cur_exp = cfg.get("RESULT_EXPORT_TYPE", "png")
        v2_exp = _c4[0].selectbox("RESULT_EXPORT_TYPE", _EXP,
                                  index=_EXP.index(_cur_exp) if _cur_exp in _EXP else 0,
                                  help="현재 png만 구현. pdf/both/none은 구조만 준비.")
        v2_kakao = _c4[1].text_input("KAKAO_JS_KEY", value=cfg.get("KAKAO_JS_KEY", ""),
                                     help="카카오 JS 키(클라이언트용). 입력 시 카카오 공유 SDK 연동 준비.")
        _c5 = st.columns(2)
        v2_calcver = _c5[0].text_input("CALCULATOR_VERSION", value=cfg.get("CALCULATOR_VERSION", "2.0.0"))
        v2_lawver = _c5[1].text_input("LAW_VERSION", value=cfg.get("LAW_VERSION", "2026-07"))
        if st.button("💾 계산기 노출 설정 저장", key="v2_save_btn"):
            _p = BASE / "config" / "config.yaml"
            with open(_p, encoding="utf-8") as f:
                _raw = yaml.safe_load(f) or {}
            _raw.update({
                "SITE_MODE": v2_site,
                "SHOW_ADSENSE": bool(v2_ads), "SHOW_CPA": bool(v2_cpa),
                "SHOW_SHARE": bool(v2_share), "SHOW_PWA": bool(v2_pwa),
                "SHOW_RESULT_SAVE": bool(v2_save), "SHOW_FAQ": bool(v2_faq),
                "SHOW_NOTICE": bool(v2_notice), "SHOW_RELATED": bool(v2_related),
                "SHOW_DETAIL": bool(v2_detail),
                "RESULT_EXPORT_TYPE": v2_exp, "KAKAO_JS_KEY": v2_kakao.strip(),
                "CALCULATOR_VERSION": v2_calcver.strip(), "LAW_VERSION": v2_lawver.strip(),
            })
            with open(_p, "w", encoding="utf-8") as f:
                yaml.dump(_raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.success("✅ 저장 완료. 계산기 재생성 시 SM_CONFIG에 반영됩니다.")
            st.cache_resource.clear()

    # ── AI 역할 체계 (확장 기능 전용 — 기존 파이프라인 모델과 별개) ──
    with st.expander("🧠 AI 역할 체계 (AI Workspace / App Factory 용)", expanded=False):
        st.caption("총괄/리서치/코드/작성/검수/이미지 역할별 모델. 기존 ORCHESTRATOR/PLANNER/WRITER/EDITOR 설정과 별개로 동작합니다.")
        from modules.ai_roles import ROLE_DEFS, get_role
        providers_list2 = ["openai", "claude", "gemini"]
        role_inputs = {}
        for rk, base in ROLE_DEFS.items():
            cur_p, cur_m = get_role(cfg, rk)
            st.markdown(f"**{base['label']}** — {base['desc']}")
            rc1, rc2 = st.columns(2)
            pv = rc1.selectbox(f"{rk} provider", providers_list2,
                               index=providers_list2.index(cur_p) if cur_p in providers_list2 else 0,
                               key=f"role_p_{rk}", label_visibility="collapsed")
            mv = rc2.text_input(f"{rk} model", value=cur_m, key=f"role_m_{rk}", label_visibility="collapsed")
            role_inputs[rk] = {"provider": pv, "model": mv}
        if st.button("💾 AI 역할 저장", key="save_roles"):
            with open(cfg_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            raw["AI_ROLES"] = role_inputs
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.success("✅ AI 역할 저장 완료")
            st.cache_resource.clear()

    # ── AI 점수 가중치 슬라이더 편집기 (score_weights.yaml) ──
    with st.expander("⚖️ AI 점수 가중치 (score_weights.yaml)", expanded=False):
        st.caption("M2 Strategist가 글 우선순위를 매기는 기준. 슬라이더 조정 후 저장하면 yaml에 반영(합계 1.0 자동 정규화).")
        sw_path = BASE / "config" / "score_weights.yaml"
        try:
            with open(sw_path, encoding="utf-8") as f:
                sw_raw = yaml.safe_load(f) or {}
        except Exception:
            sw_raw = {}
        sw = sw_raw.get("score_weights", {}) or {}
        SW_LABELS = {
            "traffic": "검색량(트래픽)", "cpc": "클릭단가(CPC)",
            "competition": "경쟁도(낮을수록 유리)", "cluster": "클러스터 연관성",
            "calculator": "계산기 연동", "revenue": "수익모델 적합도",
        }
        defaults = {"traffic": 0.30, "cpc": 0.20, "competition": 0.20,
                    "cluster": 0.10, "calculator": 0.10, "revenue": 0.10}
        sw_vals = {}
        for k, label in SW_LABELS.items():
            sw_vals[k] = st.slider(label, 0.0, 1.0,
                                   float(sw.get(k, defaults[k])), 0.05, key=f"sw_{k}")
        total = sum(sw_vals.values())
        st.caption(f"현재 합계: {total:.2f} (저장 시 1.0으로 자동 정규화)")
        if st.button("💾 가중치 저장", key="save_weights"):
            if total <= 0:
                st.error("가중치 합계가 0보다 커야 합니다.")
            else:
                norm = {k: round(v / total, 4) for k, v in sw_vals.items()}
                sw_raw["score_weights"] = norm
                with open(sw_path, "w", encoding="utf-8") as f:
                    yaml.dump(sw_raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.success(f"✅ 가중치 저장(정규화) 완료: {norm}")

    # ── 저장 로직 ──────────────────────────────────────────
    st.divider()
    if st.button("💾 설정 저장", type="primary"):
        new_cfg = dict(cfg)
        
        safe_orch = orch_mod.replace("-latest", "") if orch_prov == "gemini" else orch_mod
        safe_plan = plan_mod.replace("-latest", "") if plan_prov == "gemini" else plan_mod
        safe_writ = writ_mod.replace("-latest", "") if writ_prov == "gemini" else writ_mod
        safe_edit = edit_mod.replace("-latest", "") if edit_prov == "gemini" else edit_mod

        updates = {
            "OPENAI_API_KEY": st.session_state.get("s_openai", cfg.get("OPENAI_API_KEY","")),
            "CLAUDE_API_KEY": st.session_state.get("s_claude", cfg.get("CLAUDE_API_KEY","")),
            "GEMINI_API_KEY": st.session_state.get("s_gemini", cfg.get("GEMINI_API_KEY","")),
            
            "ORCHESTRATOR_PROVIDER": orch_prov,
            "PLANNER_PROVIDER":      plan_prov,
            "WRITER_PROVIDER":       writ_prov,
            "EDITOR_PROVIDER":       edit_prov,
            
            "MODEL_ORCHESTRATOR":    safe_orch,
            "MODEL_PLANNER":         safe_plan,
            "MODEL_WRITER":          safe_writ,
            "MODEL_EDITOR":          safe_edit,
            "MODEL_CLEANER":         clean_mod,
            "MODEL_EDITOR_FALLBACK": fb_mod,
            
            "IMAGE_PROVIDER":        image_provider,
            "MODEL_IMAGE":           image_model,
            "IMAGE_SIZE":            image_size,
            "IMAGE_QUALITY":         image_quality,
            
            "GOOGLE_SHEET_ID":   st.session_state.get("s_sheet", cfg.get("GOOGLE_SHEET_ID","")),
            "GOOGLE_DRIVE_ROOT_ID": st.session_state.get("s_drive", cfg.get("GOOGLE_DRIVE_ROOT_ID","")),
            "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID": st.session_state.get("s_ph", cfg.get("GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID","")),
            "WORDPRESS_URL":          wp_url.strip(),
            "WORDPRESS_USERNAME":     wp_user.strip(),
            "WORDPRESS_APP_PASSWORD": wp_pw.strip(),
            "RUN_MODE":           "wordpress",
            "ADSENSE_MODE":       adsense_mode,
            "DAILY_POST_COUNT":   int(daily_count),
            "DAILY_AI_BUDGET":    int(daily_budget),
            "MONTHLY_AI_BUDGET":  int(monthly_budget),
            "DLQ_THRESHOLD":      int(dlq_threshold),
            "TELEGRAM_BOT_TOKEN": tg_token.strip(),
            "TELEGRAM_CHAT_ID":   tg_chat.strip(),
            "TELEGRAM_EVENTS":    tg_events,
            "AUTO_TOPIC_EXPANSION": auto_topic,
            "ENABLE_STRATEGY_ROOM": enable_strategy,
            "OPERATION_MODE": operation_mode,
        }
        new_cfg.update(updates)

        # 민감정보는 config.yaml이 아닌 secrets.yaml에 저장(분리 유지)
        from modules.config_loader import split_secrets, save_secrets_flat
        public_cfg, secret_cfg = split_secrets(new_cfg)
        if secret_cfg:
            save_secrets_flat(secret_cfg, str(cfg_path))
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(public_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.success("✅ 제미나이 안전 규격 및 무료 이미지 옵션이 반영되어 저장되었습니다!")
        st.cache_resource.clear()

        st.subheader("🏥 저장 후 자동 헬스체크")
        with st.spinner("연결 상태 확인 중..."):
            try:
                hc_results = hc_mod.run(new_cfg)
                for k, v in hc_results.items():
                    if k == "timestamp": continue
                    if isinstance(v, dict):
                        if v.get("status") == "OK": st.success(f"✅ {k}: 연결 정상")
                        else: st.error(f"❌ {k}: 실패 — {v.get('error','')}")
            except Exception as e:
                st.error(f"헬스체크 모듈 가동 실패: {e}")

elif tab == "🏥 헬스체크":
    st.title("🏥 헬스체크 센터")
    run_live = st.button("▶ 헬스체크 실행(실시간)", type="primary")
    results = None
    if run_live:
        with st.spinner("검사 중... (API 연결 확인, 최대 30초)"):
            results = hc_mod.run(cfg)
    else:
        results = _read_health_cache()
        if results:
            st.caption(f"마지막 검사: {results.get('timestamp','-')} (실시간 재검사하려면 위 버튼)")
        else:
            st.info("검사 기록이 없습니다. 위 버튼으로 실행하세요.")

    if results:
        labels = {"openai": "OpenAI", "claude": "Claude", "gemini": "Gemini",
                  "google_sheet": "Sheets", "google_drive": "Drive",
                  "wordpress": "WordPress", "service_account": "Service Account"}
        items = [(labels.get(k, k), v) for k, v in results.items()
                 if isinstance(v, dict) and "status" in v]
        cols = st.columns(3)
        for i, (name, v) in enumerate(items):
            ok = v.get("status") == "OK"
            with cols[i % 3].container(border=True):
                st.markdown(f"### {'🟢' if ok else '🔴'} {name}")
                st.write(f"상태: **{v.get('status')}** ({v.get('level','')})")
                if not ok and v.get("error"):
                    st.error(str(v.get("error"))[:200])

elif tab == "📡 실시간 로그":
    st.title("📡 실시간 로그 센터")
    log_path = BASE / "data" / "logs" / "pipeline.log"
    fc1, fc2 = st.columns([1, 2])
    auto = fc1.toggle("🔄 자동 갱신(5초)", value=True, key="log_auto")
    level_filter = fc2.radio("필터", ["전체", "ERROR만", "WARN+ERROR", "INFO만"],
                             horizontal=True, key="log_filter")

    def _classify(line: str) -> str:
        if "[ERROR]" in line:
            return "error"
        if "[WARN" in line:   # [WARNING]/[WARN]
            return "warn"
        if "[INFO]" in line:
            return "info"
        return "other"

    def _render_log():
        st.caption(f"마지막 갱신: {datetime.now().strftime('%H:%M:%S')}")
        if not log_path.exists():
            st.info("아직 로그 파일이 없습니다 (data/logs/pipeline.log).")
            return
        lines = _tail_lines("data/logs/pipeline.log", 300)
        want = {"전체": {"error", "warn", "info", "other"},
                "ERROR만": {"error"},
                "WARN+ERROR": {"error", "warn"},
                "INFO만": {"info"}}[level_filter]
        rows = [(l, _classify(l)) for l in lines if _classify(l) in want]
        cnt = {"error": 0, "warn": 0, "info": 0}
        for _, lv in [(l, _classify(l)) for l in lines]:
            if lv in cnt:
                cnt[lv] += 1
        m = st.columns(3)
        m[0].metric("🔴 ERROR", cnt["error"]); m[1].metric("🟡 WARN", cnt["warn"]); m[2].metric("🟢 INFO", cnt["info"])
        if not rows:
            st.caption("표시할 로그가 없습니다.")
            return
        color = {"error": "#ef4444", "warn": "#f59e0b", "info": "#16a34a", "other": "#9ca3af"}
        html = ['<div style="font-family:monospace;font-size:12px;line-height:1.5;'
                'max-height:460px;overflow:auto;background:#0f172a;padding:10px;border-radius:8px">']
        import html as _h
        import re as _re
        def _body(s):   # 타임스탬프 접두사 제외 본문(연속 반복 판정용)
            return _re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s*', '', s)
        def _hms(s):
            m = _re.match(r'^\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})', s)
            return m.group(1) if m else ''

        def _emit(_line, _lv):
            html.append(f'<div style="color:{color[_lv]};white-space:pre-wrap">{_h.escape(_line)}</div>')

        disp = rows[-200:]
        i = 0
        while i < len(disp):
            line, lv = disp[i]
            key = _body(line)
            j = i + 1
            while j < len(disp) and _body(disp[j][0]) == key:
                j += 1
            run = j - i
            _emit(line, lv)                      # 첫 줄은 항상 표시
            if run >= 3:                         # 3회 이상 연속 → 나머지 압축(표시만)
                note = f'⋯ 동일 메시지 {run - 1}회 생략(마지막: {_hms(disp[j - 1][0])})'
                html.append(f'<div style="color:#64748b;font-style:italic;white-space:pre-wrap">{_h.escape(note)}</div>')
            else:                                # 1~2회는 그대로 전부 표시
                for k in range(i + 1, j):
                    _emit(disp[k][0], disp[k][1])
            i = j
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)

    if auto:
        try:
            log_fragment = st.fragment(run_every=5)(_render_log)
            log_fragment()
        except Exception:
            # 구버전 Streamlit 폴백
            if st.button("🔄 새로고침"):
                st.rerun()
            _render_log()
    else:
        if st.button("🔄 새로고침"):
            st.rerun()
        _render_log()