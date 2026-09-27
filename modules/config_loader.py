"""
config_loader.py — config.yaml 로드 및 검증 + secrets.yaml 병합

설정 로딩 일원화:
  - config.yaml  : 일반 설정(모델/예산/Google/WP URL 등)
  - secrets.yaml : 민감정보(API 키/앱 비밀번호/봇 토큰) — .gitignore 대상, 추적 안 함
  런타임에서 두 파일을 Merge(secrets 우선)하여 기존 flat 키(cfg["OPENAI_API_KEY"] 등)를
  그대로 사용. 호출부 코드 무변경(하위 호환).
"""
import yaml
import os
import sys

REQUIRED_MODELS = [
    "MODEL_ORCHESTRATOR", "MODEL_PLANNER", "MODEL_WRITER",
    "MODEL_EDITOR", "MODEL_CLEANER"
]

# config.yaml이 아닌 config/secrets.yaml에 보관하는 민감정보 키(flat).
# 저장(쓰기) 시 이 키들은 config.yaml에서 제거되고 secrets.yaml로 이동한다.
SECRET_KEYS = (
    "OPENAI_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "WORDPRESS_APP_PASSWORD",
    "WORDPRESS_PASSWORD",     # 구 키(하위호환). _normalize가 APP_PASSWORD로 승격.
    "TELEGRAM_BOT_TOKEN",
)


def _secrets_path_for(config_path: str) -> str:
    """config.yaml 경로 기준 같은 폴더의 secrets.yaml 경로."""
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "secrets.yaml")


def load_secrets(config_path: str = None) -> dict:
    """secrets.yaml 전체를 dict로 반환(없으면 {}). 중첩 섹션 포함."""
    if config_path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base, "config", "config.yaml")
    sp = _secrets_path_for(config_path)
    if os.path.exists(sp):
        with open(sp, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def merge_secrets(cfg: dict, config_path: str = None) -> dict:
    """secrets.yaml의 내용을 cfg에 재귀적으로 병합(secrets 우선)."""
    if cfg is None:
        cfg = {}
    secrets = load_secrets(config_path)

    def deep_merge(source, destination):
        for key, value in source.items():
            if isinstance(value, dict):
                node = destination.setdefault(key, {})
                if isinstance(node, dict):
                    deep_merge(value, node)
                else:
                    destination[key] = value
            else:
                destination[key] = value
        return destination

    return deep_merge(secrets, cfg)


def save_secrets_flat(updates: dict, config_path: str = None):
    """민감정보 flat 키를 secrets.yaml에 병합 저장(기존 중첩 섹션/타 키 보존)."""
    if config_path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base, "config", "config.yaml")
    sp = _secrets_path_for(config_path)
    data = {}
    if os.path.exists(sp):
        with open(sp, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    for k, v in updates.items():
        data[k] = v
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def split_secrets(cfg: dict) -> tuple[dict, dict]:
    """cfg를 (일반설정, 민감정보)로 분리. config.yaml 저장 직전 사용.
    반환된 일반설정에는 SECRET_KEYS가 제거되어 있음."""
    public, secret = {}, {}
    for k, v in cfg.items():
        if k in SECRET_KEYS:
            secret[k] = v
        else:
            public[k] = v
    return public, secret


def load_config(path: str = None, *, wp_target: str = None) -> dict:
    """wp_target(CALCMATE-WP-ENDPOINT-FIX-IMPLEMENT-01): None/"local"이면 기존 동작
    그대로. "production"이면 _apply_wp_target()이 nested wordpress.* 세트로 flat
    WORDPRESS_* 3개를 동시에 교체한다. 이 함수는 환경변수를 읽지 않는다 — target
    해석은 호출부(api/services/worker_manager.py)의 책임이다."""
    if path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "config", "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = merge_secrets(cfg, path)   # secrets.yaml 병합(secrets 우선)
    cfg = _normalize(cfg)
    cfg = _apply_wp_target(cfg, wp_target)
    _validate(cfg)
    return cfg


def _normalize(cfg: dict) -> dict:
    """키명 정규화. WordPress 앱 비밀번호 키를 WORDPRESS_APP_PASSWORD로 단일화.
    구 키(WORDPRESS_PASSWORD)는 하위호환으로 자동 승격."""
    if cfg is None:
        cfg = {}
    legacy = cfg.get("WORDPRESS_PASSWORD")
    if legacy and not cfg.get("WORDPRESS_APP_PASSWORD"):
        cfg["WORDPRESS_APP_PASSWORD"] = legacy
    return cfg


WP_TARGETS = ("local", "production")
_WP_PRODUCTION_FIELDS = (
    ("url", "WORDPRESS_URL"),
    ("username", "WORDPRESS_USERNAME"),
    ("app_password", "WORDPRESS_APP_PASSWORD"),
)


def _apply_wp_target(cfg: dict, wp_target: str = None) -> dict:
    """WordPress 대상 선택(CALCMATE-WP-ENDPOINT-FIX-IMPLEMENT-01).

    - None / "local": 아무것도 바꾸지 않는다(flat WORDPRESS_* = 로컬/테스트 세트).
    - "production": secrets.yaml의 nested wordpress.{url,username,app_password}를
      하나의 credential set으로 검증한 뒤 flat 3개 키를 동시에 교체한다. 하나라도
      비어 있으면 ConfigError(fail-closed) — "production URL + local password"
      조합은 만들어지지 않는다. 구 키 WORDPRESS_PASSWORD도 제거해 잔재를 없앤다.
    - 그 외 값: ConfigError. 문자열 추론/fallback은 하지 않는다.

    예외 메시지에는 누락 필드 이름만 담고, 값(URL/username/password)은 담지 않는다."""
    if wp_target is None or wp_target == "local":
        return cfg
    if wp_target != "production":
        raise ConfigError(
            f"허용되지 않는 WordPress target입니다(허용값: {', '.join(WP_TARGETS)})")

    wp = cfg.get("wordpress")
    if not isinstance(wp, dict):
        raise ConfigError("Missing production WordPress configuration: wordpress section")
    values = {}
    missing = []
    for src, _dst in _WP_PRODUCTION_FIELDS:
        v = wp.get(src)
        v = v.strip() if isinstance(v, str) else ""
        if not v:
            missing.append(src)
        values[src] = v
    if missing:
        raise ConfigError(
            f"Missing production WordPress configuration: {', '.join(missing)}")

    for src, dst in _WP_PRODUCTION_FIELDS:
        cfg[dst] = values[src]
    cfg.pop("WORDPRESS_PASSWORD", None)
    cfg["_wp_target"] = "production"
    return cfg


def is_wordpress_ready(cfg: dict) -> bool:
    """WordPress 발행에 필요한 설정이 모두 갖춰졌는지 판정.
    미구축(빈 값/placeholder) 시 False → 파이프라인은 발행을 건너뛰고 대기."""
    url = (cfg.get("WORDPRESS_URL") or "").strip()
    user = (cfg.get("WORDPRESS_USERNAME") or "").strip()
    pw = (cfg.get("WORDPRESS_APP_PASSWORD")
          or cfg.get("WORDPRESS_PASSWORD")
          or (cfg.get("wordpress") or {}).get("app_password")
          or "").strip()
    if not url or not user or not pw:
        return False
    # placeholder/예시 값은 미구성으로 취급
    if "example.com" in url or user in ("temp", "admin") and pw in ("temp", "REDACTED_WP_PASSWORD"):
        return False
    return True


def _validate(cfg: dict):
    missing = [k for k in REQUIRED_MODELS if not (cfg.get(k) or "").strip()]
    if missing:
        raise ConfigError(f"config.yaml에 아래 MODEL 항목이 공란입니다: {missing}\n"
                          f"공급사 공식 문서 기준 최신 모델명을 입력하세요.")
    # WORDPRESS_URL은 더 이상 필수가 아님 — WordPress 미구축 상태에서도 대기 동작.
    # (발행 단계에서 is_wordpress_ready로 판정 후 건너뜀)


class ConfigError(Exception):
    pass
