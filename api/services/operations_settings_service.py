"""api/services/operations_settings_service.py — 블로그 파이프라인 모델 매칭 /
운영 설정 / TELEGRAM_EVENTS 조회·저장 + Telegram 테스트 전송
(CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01).

dashboard.py "🔧 설정" 탭의 다음 부분만 그대로 이관한다(새 설정 키를 만들지 않음):
  - "🤖 최신 텍스트 AI 역할 및 모델 매칭"(3101-3133): {ORCHESTRATOR,PLANNER,WRITER,
    EDITOR}_PROVIDER / MODEL_{ORCHESTRATOR,PLANNER,WRITER,EDITOR} / MODEL_CLEANER /
    MODEL_EDITOR_FALLBACK. 블로그 파이프라인(main.py, cleaner, strategist, editor,
    ai_provider, strategy_room)이 실제로 읽는 flat 키다 — React의 AI_ROLES(modules.
    ai_roles 확장용 역할표)와는 별개 설정이며 서로 대체하지 않는다.
  - "⚙️ 운영 설정"(3216-3231): ADSENSE_MODE / DLQ_THRESHOLD / AUTO_TOPIC_EXPANSION /
    ENABLE_STRATEGY_ROOM. RUN_MODE / OPERATION_MODE(reader 없음)와 DAILY_POST_COUNT
    (원본도 표시 전용)는 다루지 않는다.
  - "이벤트별 알림 ON/OFF"(3252-3261): TELEGRAM_EVENTS(6개 bool, telegram_ops.
    EVENT_KEYS).
  - "📤 텔레그램 테스트 전송"(3241-3251): telegram_ops.notify()를 그대로 호출한다.

허용값은 원본 selectbox/number_input 옵션을 그대로 가져온다(원본보다 넓히지 않음).
저장은 ConfigService의 기존 _load_raw()/_atomic_write()와 같은 모듈 lock
(_CONFIG_WRITE_LOCK)을 재사용한다 — patch_image_google_settings()와 동일한
"전체 로드 → 대상 키만 갱신 → 원자적 교체" 방식이며 새 저장 메커니즘을 만들지 않는다.
"""
import yaml

from api.services.config_service import ConfigService, _CONFIG_WRITE_LOCK
from modules.telegram_ops import EVENT_KEYS as TELEGRAM_EVENT_KEYS

# dashboard.py:3102-3107 그대로.
PIPELINE_PROVIDERS = ("openai", "claude", "gemini")
PIPELINE_MODEL_PRESETS = {
    "openai": ("gpt-4o", "gpt-4o-mini"),
    "claude": ("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"),
    "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
}
# dashboard.py:3123-3126 — (역할, provider 키, model 키, provider 기본값, model 기본값)
PIPELINE_ROLES = (
    ("orchestrator", "ORCHESTRATOR_PROVIDER", "MODEL_ORCHESTRATOR", "openai", "gpt-4o"),
    ("planner", "PLANNER_PROVIDER", "MODEL_PLANNER", "openai", "gpt-4o"),
    ("writer", "WRITER_PROVIDER", "MODEL_WRITER", "openai", "gpt-4o"),
    ("editor", "EDITOR_PROVIDER", "MODEL_EDITOR", "claude", "claude-sonnet-4-6"),
)
# dashboard.py:3131,3133 — Cleaner/Fallback은 openai 프리셋에서만 고른다.
OPENAI_ONLY_MODEL_KEYS = ("MODEL_CLEANER", "MODEL_EDITOR_FALLBACK")
# dashboard.py:3223 — ADSENSE_MODE selectbox 옵션.
ADSENSE_MODES = ("pre", "post")

_DEFAULTS = {
    **{pk: pdef for _, pk, _, pdef, _ in PIPELINE_ROLES},
    **{mk: mdef for _, _, mk, _, mdef in PIPELINE_ROLES},
    "MODEL_CLEANER": "gpt-4o",
    "MODEL_EDITOR_FALLBACK": "gpt-4o",
    "ADSENSE_MODE": "pre",
    "DLQ_THRESHOLD": 3,
    "AUTO_TOPIC_EXPANSION": False,
    "ENABLE_STRATEGY_ROOM": True,
}
OPERATIONS_FIELDS = tuple(_DEFAULTS) + ("TELEGRAM_EVENTS",)

TELEGRAM_TEST_MESSAGE = "✅ CalcMate 텔레그램 연결 테스트 — 정상"


def _telegram_events(raw: dict) -> dict:
    current = raw.get("TELEGRAM_EVENTS") or {}
    return {k: bool(current.get(k, True)) for k in TELEGRAM_EVENT_KEYS}


def get_operations_settings(svc: ConfigService = None) -> dict:
    """원문 그대로 반환한다(secret 아님). 값이 없으면 원본 cfg.get() 기본값."""
    raw = (svc or ConfigService())._load_raw()
    out = {key: raw.get(key, default) for key, default in _DEFAULTS.items()}
    out["TELEGRAM_EVENTS"] = _telegram_events(raw)
    return out


def _validate(merged: dict, updates: dict) -> None:
    for _, pk, mk, _, _ in PIPELINE_ROLES:
        if pk not in updates and mk not in updates:
            continue
        provider = merged.get(pk)
        if provider not in PIPELINE_PROVIDERS:
            raise ValueError(f"{pk} must be one of {PIPELINE_PROVIDERS}")
        if merged.get(mk) not in PIPELINE_MODEL_PRESETS[provider]:
            raise ValueError(f"{mk} must be one of {PIPELINE_MODEL_PRESETS[provider]} for {provider}")
    for key in OPENAI_ONLY_MODEL_KEYS:
        if key in updates and updates[key] not in PIPELINE_MODEL_PRESETS["openai"]:
            raise ValueError(f"{key} must be one of {PIPELINE_MODEL_PRESETS['openai']}")
    if "ADSENSE_MODE" in updates and updates["ADSENSE_MODE"] not in ADSENSE_MODES:
        raise ValueError(f"ADSENSE_MODE must be one of {ADSENSE_MODES}")
    if "DLQ_THRESHOLD" in updates:
        v = updates["DLQ_THRESHOLD"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 10:
            raise ValueError("DLQ_THRESHOLD must be an integer between 1 and 10")
    for key in ("AUTO_TOPIC_EXPANSION", "ENABLE_STRATEGY_ROOM"):
        if key in updates and not isinstance(updates[key], bool):
            raise ValueError(f"{key} must be a boolean")
    if "TELEGRAM_EVENTS" in updates:
        events = updates["TELEGRAM_EVENTS"]
        if not isinstance(events, dict):
            raise ValueError("TELEGRAM_EVENTS must be an object")
        for k, v in events.items():
            if k not in TELEGRAM_EVENT_KEYS:
                raise ValueError(f"unknown TELEGRAM_EVENTS key: {k} (must be one of {TELEGRAM_EVENT_KEYS})")
            if not isinstance(v, bool):
                raise ValueError(f"TELEGRAM_EVENTS.{k} must be a boolean")


def patch_operations_settings(updates: dict, svc: ConfigService = None) -> dict:
    """updates(None이 아닌 값)만 부분 업데이트한다. provider/model은 역할 단위로
    (갱신 후 값 기준) 원본 프리셋 조합만 허용한다. TELEGRAM_EVENTS는 이벤트 단위로
    병합한다(요청에 없는 이벤트는 기존 값 유지). 검증 실패 시 파일을 쓰지 않고
    ValueError를 raise한다."""
    svc = svc or ConfigService()
    updates = {k: v for k, v in updates.items() if k in OPERATIONS_FIELDS and v is not None}
    with _CONFIG_WRITE_LOCK:
        if updates:
            raw = svc._load_raw()
            merged = {key: raw.get(key, default) for key, default in _DEFAULTS.items()}
            merged.update({k: v for k, v in updates.items() if k != "TELEGRAM_EVENTS"})
            _validate(merged, updates)
            if "TELEGRAM_EVENTS" in updates:
                events = _telegram_events(raw)
                events.update(updates["TELEGRAM_EVENTS"])
                updates = {**updates, "TELEGRAM_EVENTS": events}
            raw.update(updates)
            text = yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False)
            svc._atomic_write(text)
    return get_operations_settings(svc)


def send_telegram_test(bot_token: str = None, chat_id: str = None, svc: ConfigService = None) -> dict:
    """dashboard.py "📤 텔레그램 테스트 전송"과 동일하게 telegram_ops.notify()로
    고정 메시지 1건을 보낸다. 원본은 화면에 입력된 토큰/Chat ID를 썼다 — React는
    저장된 토큰 원문을 받지 못하므로, 요청에 값이 없으면 저장된 값을 사용한다.
    둘 중 하나라도 비어 있으면 전송하지 않는다(원본의 "먼저 입력하세요" 경고와 동일).
    저장된 값은 load_config()와 같은 merge_secrets()(secrets.yaml 우선, config.yaml
    fallback)로 고른다 — 파이프라인이 실제로 쓰는 값과 같아야 하기 때문이다.
    telegram_notifier.send()는 실패를 로그로만 남기고 예외를 올리지 않으므로 결과는
    원본과 같은 "전송 시도" 의미다."""
    from modules import telegram_ops
    from modules.config_loader import merge_secrets

    svc = svc or ConfigService()
    saved = merge_secrets(svc._load_raw(), str(svc._config_path))
    token = (bot_token or "").strip() or str(saved.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (chat_id or "").strip() or str(saved.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        raise ValueError("토큰과 Chat ID를 먼저 입력하세요.")
    telegram_ops.notify({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat}, TELEGRAM_TEST_MESSAGE)
    return {"attempted": True}


class WordPressTestNotConfigured(ValueError):
    """URL/사용자/앱 비밀번호 중 하나라도 비어 있음(원본의 "모두 입력하세요" 경고)."""


class WordPressTestInvalidUrl(ValueError):
    """URL이 http/https + host 형식이 아님."""


WORDPRESS_TEST_TIMEOUT = 10  # dashboard.py 원본과 동일(초)


def check_wordpress_connection(url: str = None, username: str = None, app_password: str = None,
                              svc: ConfigService = None) -> dict:
    """CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02: dashboard.py "🔌 WordPress 연결
    테스트" 이관. 원본과 동일하게 GET {url}/wp-json/wp/v2/users/me 를 Basic auth
    (앱 비밀번호 공백 제거), timeout 10초로 1회 호출한다.

    원본은 화면 입력값(저장값으로 prefill)을 썼다 — React는 저장된 앱 비밀번호 원문을
    받지 못하므로 send_telegram_test()와 같이 요청에 값이 없으면 저장값을 쓴다.
    저장값은 merge_secrets()의 최상위 키(= dashboard.py load_cfg()·Settings 화면이
    편집하는 값)이며, 운영 대상 nested wordpress.* 세트는 사용하지 않는다.

    응답에는 사용자 이름/상태 코드/분류만 담는다 — 앱 비밀번호, Authorization 헤더,
    예외 원문(credential 포함 가능)은 반환하지도 로깅하지도 않는다."""
    from urllib.parse import urlparse
    import requests
    from modules.config_loader import merge_secrets

    svc = svc or ConfigService()
    saved = merge_secrets(svc._load_raw(), str(svc._config_path))
    u = (url or "").strip() or str(saved.get("WORDPRESS_URL") or "").strip()
    user = (username or "").strip() or str(saved.get("WORDPRESS_USERNAME") or "").strip()
    pw = (app_password or "").strip() or str(
        saved.get("WORDPRESS_APP_PASSWORD") or saved.get("WORDPRESS_PASSWORD") or "").strip()
    u = u.rstrip("/")
    if not u or not user or not pw:
        raise WordPressTestNotConfigured("URL/사용자/앱 비밀번호를 모두 입력하세요.")
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise WordPressTestInvalidUrl("URL은 http:// 또는 https:// 로 시작하는 올바른 주소여야 합니다.")

    try:
        r = requests.get(f"{u}/wp-json/wp/v2/users/me",
                         auth=(user, pw.replace(" ", "")), timeout=WORDPRESS_TEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return {"ok": False, "result": "timeout", "status_code": None, "user_name": None,
                "message": f"연결 시간 초과({WORDPRESS_TEST_TIMEOUT}초)"}
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema):
        return {"ok": False, "result": "invalid_url", "status_code": None, "user_name": None,
                "message": "URL 형식 오류 — 주소를 확인하세요."}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "result": "connection_error", "status_code": None, "user_name": None,
                "message": "연결 실패 — 주소/네트워크를 확인하세요."}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "result": "request_error", "status_code": None, "user_name": None,
                "message": f"연결 실패({type(e).__name__})"}

    if r.status_code == 200:
        try:
            name = (r.json() or {}).get("name") or "?"
        except ValueError:
            name = "?"
        return {"ok": True, "result": "success", "status_code": 200, "user_name": str(name),
                "message": f"연결 성공 — 사용자: {name}"}
    if r.status_code in (401, 403):
        return {"ok": False, "result": "auth_failed", "status_code": r.status_code, "user_name": None,
                "message": f"인증 실패({r.status_code}) — 사용자/앱 비밀번호 확인"}
    return {"ok": False, "result": "http_error", "status_code": r.status_code, "user_name": None,
            "message": f"응답 코드 {r.status_code} — URL/REST API 활성화 확인"}
