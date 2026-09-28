"""api/services/dashboard_status_service.py — Dashboard 순수 상태/진행 표시 조회.

STEP P2-02: dashboard.py의 render_pipeline_status()(dashboard.py:380-413,
"⛓️ Workflow" 블로그+계산기 파이프라인 다이어그램)와 render_progress()
(dashboard.py:489-511, "📈 진행 현황" 패널)를 그대로 재현한다. 전부 READ-ONLY이며,
기존 계산 함수를 그대로 재사용한다 — 새 계산식을 만들지 않는다.

STEP P2-10: dashboard.py의 "📊 현황" 탭(dashboard.py:562-584, elif tab ==
"📊 현황")을 GET /api/dashboard/status-summary로 이관한다. 이 탭은 "🏠 Dashboard"
네비 그룹에서 "🏠 운영센터"(P2-01/P2-02가 이미 이관)와 형제 탭이지만 완전히
다른 화면이다 — P2-02의 get_progress()(scheduler 기반 오늘 일정 진행률)와
이름은 비슷하지만 데이터 source와 계산식이 전혀 다르다(재확인, 혼동 금지):
  - 데이터 source: cached_posts()(dashboard.py:208-210) → modules.dashboard_cache.
    read(cfg, "articles", ttl=120) — articles 테이블을 읽는다(scheduler가 아님).
    dashboard_cache.read()는 미러가 오래되면 원본을 1회 조회해 별도 미러 파일
    (data/cache/dashboard_cache.db)만 갱신한다 — 이 미러 파일은 이 STEP이
    추적하는 어떤 보호 데이터(calculators/articles 실제 카운트, Registry,
    secrets.yaml 등)에도 포함되지 않으며, 원본 데이터에는 어떤 영향도 주지
    않는다(모듈 자체 docstring 재확인: "미러는 별도 파일이라 원본 데이터에
    영향 없음") — STOP 조건 아님. P2-01의 dashboard_kpi_service.py가 이미 이
    동일한 dashboard_cache.read()를 재사용 중이므로 이 패턴은 이 프로젝트의
    기존 전례다.
  - 상태별 개수(dashboard.py:566-574): articles의 "상태값" 필드 값별로 개수를
    센다. 표시 순서/아이콘도 원본 그대로: [("대기","🟡"),("작성중","🔵"),
    ("검수대기","🟠"),("발행완료","🟢"),("이미지오류","🔴"),("재처리대기","⚫")].
    이 6개 외의 상태값(있다면)은 원본처럼 화면에 표시되지 않는다(집계에서도
    제외 — 원본이 애초에 이 6개 키로만 cols[i].metric()을 렌더링하기 때문).
  - 오늘 발행(dashboard.py:577-581): daily_goal = cfg.get("DAILY_POST_COUNT", 3).
    today_published = 상태값이 ("발행완료","검수대기") 중 하나이고 "발행일시"가
    오늘 날짜(date.today().isoformat())로 시작하는 article 개수. progress =
    min(today_published / max(daily_goal, 1), 1.0) — 0.0~1.0 사이 float를
    st.progress()에 그대로 전달한다(퍼센트 텍스트로 변환해 보여주지 않음).
  - 원본에 "전체 article 수" 표시는 없다 — 6개 상태별 개수 + 오늘 발행/목표
    + 진행률 막대뿐이다. 없는 필드를 새로 추가하지 않는다.
  - 오류 처리(dashboard.py:582-583): try/except로 감싸 실패 시 "데이터 로드
    오류: {e}"만 표시한다 — 이 서비스도 동일하게 예외를 삼키지 않고 상위
    (router)에서 잡아 표준 오류 응답으로 변환한다.
  - write 없음(재확인): 이 탭 전체(dashboard.py:562-584)에 INSERT/UPDATE/
    DELETE/save()/append()/yaml.dump() 등 어떤 쓰기 호출도 없다 — 순수 GET-only
    read model이다.

STEP P2-11: dashboard.py의 "📊 AI Pipeline" 탭(dashboard.py:2875-2901, "📊 AI
Pipeline Monitor")을 GET /api/dashboard/ai-pipeline로 이관한다. 재확인된
사실(추측 없음):
  - 이 탭은 modules.pipeline_status.get_pipeline_state(cfg)를 그대로 호출한다
    — api/services/log_service.get_pipeline_status()(기존 GET /api/pipeline/
    status)와 완전히 동일한 함수이며, 이미 P2-01의 dashboard_kpi_service.
    get_kpi()도 이 함수를 그대로 재사용 중이다(새 계산 없음).
  - 표시 항목(전부 확인): 단계 카드 6개(dashboard.py:2884-2889, 각 name/model/
    status, 색상은 status에 따라 🟡pending/🔵running/🟢completed/🔴error),
    "오늘 비용"(cost_today, $X.XXXX 4자리), "오늘 토큰"(tokens_today, 천단위
    콤마), "실행 상태"(has_error면 "🔴 오류", 아니면 finished면 "✅ 완료/대기",
    아니면 "🔵 진행중" — 파생 텍스트, 원본 그대로 재현), "오늘 모델별 비용"
    (model_costs, 있을 때만 표시=원본과 동일하게 비어있으면 표 자체를 숨김),
    "최근 로그"(last_lines, 최근 실행 구간의 마지막 12줄, 없으면 "(로그
    없음)").
  - **중요 발견사항(STOP 조건 검토, 최종 보고 §8-§10 참고)**: 기존 GET
    /api/pipeline/status(api/routers/logs.py:28-30)는 require_admin이 전혀
    적용되지 않은 공개(unauthenticated) endpoint다 — cost_today/tokens_today/
    model_costs 등 AI 비용 데이터를 포함함에도 인증이 없다. 이는 STEP
    18-G(이 STEP 이전에 이미 완료된 STEP)에서 만들어진 기존 상태이며, 이
    STEP의 절대 금지 목록에 "기존 완료 STEP 수정"이 있으므로 이 endpoint
    자체를 수정하지 않는다(다른 호출자가 이 공개 endpoint의 무인증 특성에
    의존하고 있을 가능성도 배제할 수 없음). 대신 STEP 5가 명시적으로 허용한
    대안("새 endpoint가 정말 필요한 경우에만 추가한다")을 따라, 기존 함수를
    재구현 없이 그대로 호출하기만 하는 새 admin 전용 GET endpoint(/api/
    dashboard/ai-pipeline)를 추가해, React의 이 화면은 이 새 admin 경로로만
    데이터를 가져온다(공개 endpoint를 프론트에서 직접 호출하지 않는다) —
    P2-01이 AI 비용 포함 KPI를 require_admin으로 통일한 것과 동일한 원칙.
  - write 없음(재확인): get_pipeline_state()는 pipeline.log를 "rb" 모드로
    tail만 하고, BudgetTracker의 get_daily_cost()/get_today_tokens()/
    get_model_breakdown()은 전부 이미 메모리에 로드된 self.data 딕셔너리를
    읽기만 한다(record()/_save()를 호출하지 않음, 재확인) — budget.json에
    쓰지 않는다. __init__의 mkdir()은 디렉터리 생성만(존재해도 무해, 파일
    내용 무변경).

각 UI의 실제 데이터 source(재검색으로 확인, 추측 없음):
  1) Workflow(파이프라인 상태): modules.pipeline_status.get_pipeline_state(cfg)
     — P2-01의 Workflow/AI 작업 KPI 및 기존 GET /api/pipeline/status와 완전히
     동일한 함수. dashboard.py는 stages 목록을 {name: status} dict로 변환한 뒤,
     10개 블로그 단계 키워드 목록(main.py STEP 순서 기준, dashboard.py 원본
     주석에 "추측 아님"이라 명시됨)에 대해 이름에 키워드가 포함되는 첫 stage의
     status를 찾는다(없으면 "pending"). **중요**: 계산기(App Factory) 7단계는
     dashboard.py에서 항상 live=False로 렌더링되어 실제로는 어떤 계산도 하지
     않고 매번 빈 상태(정적 아이콘만 표시)다 — 이 버그/설계를 그대로 재현하며
     "고치지" 않는다(계산기 단계에 실제 상태를 부여하지 않는다).
  2) 진행 현황: modules.scheduler.summarize(modules.scheduler.load_schedule(cfg))
     — P2-01의 "오늘" KPI와 완전히 동일한 함수/동일한 cfg(scheduler_line 미지정,
     기본 라인). modules.retry_queue.list_pending()의 개수(READ ONLY — remove()/
     retry()/enqueue() 등 쓰기 함수는 호출하지 않는다. 이 값은 기존 GET /api/costs
     응답의 retry_queue.pending_count와 개념적으로 동일한 숫자이지만, 그 API는
     비용 데이터와 함께 묶여 있어 재사용하지 않고 원본과 동일하게
     retry_queue.list_pending()을 직접 호출한다).
"""
from datetime import date

from modules.config_loader import load_config

# dashboard.py:572 STATE_MAP 순서/아이콘 그대로(추측 아님).
_STATUS_MAP = [
    ("대기", "🟡"), ("작성중", "🔵"), ("검수대기", "🟠"),
    ("발행완료", "🟢"), ("이미지오류", "🔴"), ("재처리대기", "⚫"),
]

# main.py STEP 순서 기준(dashboard.py 원본 주석 그대로, 추측 아님):
# 수집→정제→중복→전략→SEO→작성→검수→이미지→발행→기록
_BLOG_STEPS = [
    ("📥", "수집", ["수집"]), ("🧹", "정제", ["정제", "표준"]),
    ("🔁", "중복검사", ["중복", "유사"]), ("🧠", "전략", ["전략", "리서치"]),
    ("🔎", "SEO기획", ["SEO", "기획", "리서치"]), ("✍", "작성", ["작성"]),
    ("🔍", "검수", ["검수"]), ("🖼", "이미지", ["이미지"]),
    ("🚀", "발행", ["발행"]), ("🗂", "기록", ["기록", "DB"]),
]
# 계산기(App Factory) 7단계 — dashboard.py에서 항상 live=False로 렌더링되어
# 실제 상태를 반영하지 않는 정적 다이어그램이다(재현 대상, 개선 대상 아님).
_CALC_STEPS = [
    ("🔑", "키워드"), ("🔎", "SEO"), ("❓", "FAQ"),
    ("📝", "본문"), ("🤖", "Reviewer"), ("🧩", "HTML"), ("🌐", "배포"),
]


def _stat(stage_status: dict, keys: list) -> str:
    for nm, stt in stage_status.items():
        if any(k in nm for k in keys):
            return stt
    return "pending"


def get_pipeline_status_diagram() -> dict:
    """반환: {"blog": [{"icon","label","status"}...10개], "calculator":
    [{"icon","label"}...7개, status 없음 — 원본이 항상 정적이므로]}."""
    cfg = load_config()
    stage_status = {}
    try:
        from modules.pipeline_status import get_pipeline_state
        for s in get_pipeline_state(cfg)["stages"]:
            stage_status[s["name"]] = s["status"]
    except Exception:
        pass

    blog = [
        {"icon": ic, "label": nm, "status": _stat(stage_status, keys)}
        for ic, nm, keys in _BLOG_STEPS
    ]
    calculator = [{"icon": ic, "label": nm} for ic, nm in _CALC_STEPS]
    return {"blog": blog, "calculator": calculator}


def get_progress() -> dict:
    """반환: {"total","completed","pct","failed","running","next","retry_pending"}."""
    try:
        import modules.scheduler as SCH
        cfg = load_config()
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
    return {
        "total": total,
        "completed": comp,
        "pct": pct,
        "failed": sm.get("failed", 0),
        "running": sm.get("running", 0),
        "next": sm.get("next"),
        "retry_pending": retry_n,
    }


def get_status_summary() -> dict:
    """dashboard.py "📊 현황" 탭(dashboard.py:562-584)과 동일한 실행 의미 —
    READ-ONLY. cached_posts()가 하던 대로 dashboard_cache.read(cfg, "articles")
    를 그대로 재사용해 상태별 개수/오늘 발행/목표/진행률을 계산한다(재구현
    없음, 원본에 없는 값을 추가하지 않는다). 반환: {"statuses":[{"status",
    "icon","count"}×6], "today_published", "daily_goal", "progress_percent"}.
    progress_percent는 원본의 0.0~1.0 float(min(today_published/max(daily_goal,1),
    1.0))를 DashboardProgressPanel의 기존 "pct" 관례에 맞춰 0~100 정수로
    표현만 바꾼 것이다(값 자체는 동일, 새 계산식 아님)."""
    cfg = load_config()
    try:
        from modules.dashboard_cache import read as cache_read
        posts = cache_read(cfg, "articles", ttl=120)
    except Exception:
        posts = []

    status_counts = {}
    for p in posts:
        s = p.get("상태값", "알 수 없음")
        status_counts[s] = status_counts.get(s, 0) + 1

    statuses = [
        {"status": name, "icon": icon, "count": status_counts.get(name, 0)}
        for name, icon in _STATUS_MAP
    ]

    daily_goal = cfg.get("DAILY_POST_COUNT", 3)
    today_str = date.today().isoformat()
    today_published = sum(
        1 for p in posts
        if p.get("상태값") in ("발행완료", "검수대기") and str(p.get("발행일시", "")).startswith(today_str)
    )
    progress_ratio = min(today_published / max(daily_goal, 1), 1.0)

    return {
        "statuses": statuses,
        "today_published": today_published,
        "daily_goal": daily_goal,
        "progress_percent": round(progress_ratio * 100),
    }


def get_ai_pipeline_status() -> dict:
    """dashboard.py "📊 AI Pipeline Monitor" 탭(dashboard.py:2875-2901)과 동일한
    데이터 — api/services/log_service.get_pipeline_status()(기존 공개 GET
    /api/pipeline/status가 호출하는 바로 그 함수)를 재구현 없이 그대로
    호출한다. 이 함수는 값을 그대로 전달하는 것 외에 아무것도 하지 않는다 —
    cost_today/tokens_today/model_costs 등 AI 비용 데이터를 admin 전용 경로
    로도 제공하기 위한 thin wrapper다(기존 공개 endpoint 자체는 변경하지
    않는다 — 모듈 docstring의 P2-11 발견사항 참고)."""
    from api.services.log_service import get_pipeline_status
    return get_pipeline_status()
