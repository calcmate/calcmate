"""api/services/config_service.py — Config 접근 계층 (STEP 18-C 읽기 골격 + STEP 18-E 쓰기).

secrets.yaml / score_weights.yaml 에 대한 write는 여전히 이 클래스에 없다.
config.yaml 쓰기는 BLOG_SCHEDULE 섹션 전용 patch_blog_schedule()만 제공하며,
STEP 17-N에서 검증된 "섹션 블록만 정규식 치환" 방식을 그대로 재사용한다
(yaml.safe_load()→dict 변경→yaml.dump() 전체 재작성 방식은 사용하지 않는다 — 주석/
다른 섹션이 소실되는 부작용이 있었음).

allowlist에 없는 section은 거부하며, secrets로 보이는 키는 원문을 절대 반환하지 않는다.

STEP P2-14: dashboard.py "🎨 블로그 이미지 생성 AI 설정"(3150-3183)과 "📊 Google
연동"(3186-3189)만 추가로 이관한다. 재확인된 사실(추측 없음):
  - 7개 필드(IMAGE_PROVIDER/MODEL_IMAGE/IMAGE_SIZE/IMAGE_QUALITY/GOOGLE_SHEET_ID/
    GOOGLE_DRIVE_ROOT_ID/GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID) 전부 config.yaml의
    평범한 top-level 값이며 _SECRET_KEY_SUFFIXES(_KEY/_TOKEN/_PASSWORD/_SECRET)
    어디에도 해당하지 않는다 — secrets.yaml로 분리 저장되지 않는다(원본
    dashboard.py:3429-3435의 split_secrets() 호출도 이 7개 키를 secret_cfg로
    분류하지 않음, 재확인).
  - 기본값(원본 cfg.get() 재확인): IMAGE_PROVIDER="free_pollinations",
    MODEL_IMAGE="", IMAGE_SIZE="auto", IMAGE_QUALITY="standard",
    GOOGLE_SHEET_ID/GOOGLE_DRIVE_ROOT_ID/GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID="".
  - 허용값(원본 selectbox 옵션 그대로): IMAGE_PROVIDER ∈ {free_pollinations,
    gemini, openai}, IMAGE_SIZE ∈ {auto, 1024x1024, 1792x1024}, IMAGE_QUALITY
    ∈ {standard, hd}. MODEL_IMAGE는 원본이 provider별 프리셋 1개짜리 selectbox
    (예: free_pollinations→"무료 이미지 엔진 (API키/결제 없음)"라는 플레이스홀더
    텍스트 자체가 저장값)로만 제약할 뿐 서버측 강제 검증은 없다 — 이 STEP도
    자유 문자열로 받아 원본보다 더 엄격한 검증을 새로 만들지 않는다.
    GOOGLE_* 3개는 원본에 형식 검증이 전혀 없다 — 그대로 자유 문자열.
  - patch_general_settings()(STEP 4-F, 완료)는 수정하지 않는다 — 이 7개 필드는
    GENERAL_PUBLIC_FIELDS/GENERAL_SECRET_FIELDS 어디에도 없어 겹치지 않는다.
    같은 클래스(ConfigService)에 새 메서드만 추가하고, 기존 _load_raw()/
    _atomic_write()(원자적 임시파일→rename 교체, 이미 검증된 방식)를 그대로
    재사용한다 — 새 저장 메커니즘을 만들지 않는다.
  - PATCH 의미론은 api/routers/publish.py의 PublishEditRequest와 동일한
    관례를 따른다: 필드를 아예 보내지 않으면(None) 변경 안 함, 명시적으로
    빈 문자열을 보내면 그 값으로 비움 — GeneralSettingsUpdate(시크릿 필드라
    빈 문자열을 "재전송 안 함"으로 취급)와는 다른 의미론이지만, 이 7개는
    시크릿이 아니고 원본 Streamlit도 텍스트 입력을 비우면 그대로 빈 문자열을
    저장하므로 이 쪽이 원본 동작에 더 가깝다.
"""
import re
import threading
from pathlib import Path

import yaml

ALLOWED_SECTIONS = frozenset({
    "BLOG_SCHEDULE",
    "PUBLISH_SCHEDULE",
    "CALC_WEBAPP_SCHEDULE",
    "CONTENT_SYNC",
    "PUBLISHING_POLICY",
    "AUTO_PUBLISHING",
    "WP_BLOG_SYNC",
})

_SECRET_KEY_SUFFIXES = ("_KEY", "_TOKEN", "_PASSWORD", "_SECRET")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_BLOG_MODES = ("draft", "publish")

_CONFIG_WRITE_LOCK = threading.Lock()

# STEP 4-F: General Settings(API 키/WordPress URL·계정/Telegram/Budget/AI Roles) 전용.
# secrets.yaml 저장 대상(top-level flat 키) — modules.config_loader.SECRET_KEYS의
# 부분집합만 이 화면에서 다룬다. nested secrets.yaml의 `wordpress.*`(blog.genon.app
# 운영용 자격증명)는 이 API가 절대 읽거나 쓰지 않는다 — 완전히 별개 대상이다.
GENERAL_SECRET_FIELDS = (
    "OPENAI_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",   # ab9ac26 보안 결정 — secrets.yaml 소유, 원문 미반환
    "WORDPRESS_APP_PASSWORD",
)
# config.yaml에 남는 비-secret 필드(모두 top-level flat 키).
GENERAL_PUBLIC_FIELDS = (
    "WORDPRESS_URL",
    "WORDPRESS_USERNAME",
    "DAILY_AI_BUDGET",
    "MONTHLY_AI_BUDGET",
    "AI_ROLES",
)

# STEP P2-14: Image-gen AI/Google 연동 전용(GENERAL_PUBLIC_FIELDS와 겹치지 않는
# 별도 7개 필드) — 전부 secrets.yaml 대상이 아니다(모듈 docstring 재확인).
IMAGE_GOOGLE_FIELDS = (
    "IMAGE_PROVIDER",
    "MODEL_IMAGE",
    "IMAGE_SIZE",
    "IMAGE_QUALITY",
    "GOOGLE_SHEET_ID",
    "GOOGLE_DRIVE_ROOT_ID",
    "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID",
)
_IMAGE_GOOGLE_DEFAULTS = {
    "IMAGE_PROVIDER": "free_pollinations",
    "MODEL_IMAGE": "",
    "IMAGE_SIZE": "auto",
    "IMAGE_QUALITY": "standard",
    "GOOGLE_SHEET_ID": "",
    "GOOGLE_DRIVE_ROOT_ID": "",
    "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID": "",
}




# STEP 18-C: Calculator Display Settings 전용 (STEP 18-C)
# dashboard.py "🎨 계산기 노출 설정 (v2)"(3586-3634)의 14개 필드 전용.
# 전부 config.yaml top-level 평범한 값이며 secret이 아니다.
CALCULATOR_DISPLAY_FIELDS = (
    "SITE_MODE",
    "SHOW_SHARE",
    "SHOW_PWA",
    "SHOW_RESULT_SAVE",
    "SHOW_FAQ",
    "SHOW_NOTICE",
    "SHOW_RELATED",
    "SHOW_DETAIL",
    "SHOW_ADSENSE",
    "SHOW_CPA",
    "RESULT_EXPORT_TYPE",
    "KAKAO_JS_KEY",
    "CALCULATOR_VERSION",
    "LAW_VERSION",
)

_SITE_MODE_CHOICES = ("pre_adsense", "adsense", "cpa", "full")
_RESULT_EXPORT_TYPE_CHOICES = ("png", "pdf", "both", "none")

# Calculator WebApp Scheduler 전용 (CALCMATE-CALCULATOR-SCHEDULER-FASTAPI-WORKER-IMPLEMENT-01)
# CALC_WEBAPP_SCHEDULE 섹션: enabled, mode, targets, poll_seconds
_CALC_WEBAPP_MODES = ("qa_only", "qa_deploy")


class ConfigSectionNotAllowed(Exception):
    """allowlist에 없는 section을 요청한 경우."""


class ConfigService:
    """config/config.yaml 접근 계층. BLOG_SCHEDULE 외 섹션은 읽기 전용이다."""

    def __init__(self, config_path: Path = None):
        project_root = Path(__file__).resolve().parent.parent.parent
        self._config_path = config_path or (project_root / "config" / "config.yaml")

    def _load_raw(self) -> dict:
        with open(self._config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_section(self, section: str) -> dict:
        if section not in ALLOWED_SECTIONS:
            raise ConfigSectionNotAllowed(f"section not allowed: {section}")
        raw = self._load_raw()
        return self._mask_secrets(raw.get(section, {}))

    def patch_blog_schedule(self, enabled: bool, mode: str, publish_slots: list, weekday_only: bool) -> dict:
        """BLOG_SCHEDULE 블록만 정규식으로 치환한다. 파일의 다른 부분(주석 포함)은
        건드리지 않는다. 저장 전 값 검증을 통과하지 못하면 파일을 쓰지 않는다."""
        with _CONFIG_WRITE_LOCK:
            self._validate_blog_schedule(enabled, mode, publish_slots, weekday_only)

            block_lines = [
                "BLOG_SCHEDULE:",
                f"  enabled: {'true' if enabled else 'false'}",
                f"  mode: {mode}",
                "  publish_slots:",
            ]
            for slot in publish_slots:
                block_lines.append(f'  - start: "{slot["start"]}"')
                block_lines.append(f'    end: "{slot["end"]}"')
            block_lines.append(f"  weekday_only: {'true' if weekday_only else 'false'}")
            new_block = "\n".join(block_lines) + "\n"

            text = self._config_path.read_text(encoding="utf-8")
            pattern = re.compile(r"^BLOG_SCHEDULE:\n(?:[ \t].*\n?)*", re.MULTILINE)
            if pattern.search(text):
                new_text = pattern.sub(lambda _m: new_block, text, count=1)
            else:
                new_text = text.rstrip("\n") + "\n\n" + new_block

            self._atomic_write(new_text)
            return self.get_section("BLOG_SCHEDULE")

    def patch_publishing_policy(self, policy: dict) -> dict:
        """PUBLISHING_POLICY 블록만 정규식으로 치환한다(patch_blog_schedule()과
        동일한 안전 방식 — 다른 섹션/주석은 건드리지 않음, 원자적 교체).

        검증은 이 클래스에서 새로 만들지 않고 modules.publishing_policy.
        validate_policy()를 그대로 재사용한다(CALCMATE-BLOG-PUBLISHING-POLICY-
        FASTAPI-REACT-CONNECTION-IMPLEMENT-01) — 두 개의 validation SSOT가
        생기지 않도록 한다. 검증 실패 시 파일을 쓰지 않고 ValueError를 raise."""
        with _CONFIG_WRITE_LOCK:
            from modules import publishing_policy as PP

            errors = PP.validate_policy(policy)
            if errors:
                raise ValueError(f"PUBLISHING_POLICY 검증 실패: {errors}")

            block_lines = ["PUBLISHING_POLICY:", f'  timezone: "{policy["timezone"]}"', "  weekdays:"]
            for day in PP.WEEKDAYS:
                entry = policy["weekdays"][day]
                block_lines.append(f"    {day}:")
                block_lines.append(f"      count: {entry['count']}")
                if entry["time_ranges"]:
                    block_lines.append("      time_ranges:")
                    for r in entry["time_ranges"]:
                        block_lines.append(f'        - start: "{r["start"]}"')
                        block_lines.append(f'          end: "{r["end"]}"')
                else:
                    block_lines.append("      time_ranges: []")
            block_lines.append(f"  max_pending_reservations: {policy['max_pending_reservations']}")
            new_block = "\n".join(block_lines) + "\n"

            text = self._config_path.read_text(encoding="utf-8")
            pattern = re.compile(r"^PUBLISHING_POLICY:\n(?:[ \t].*\n?)*", re.MULTILINE)
            if pattern.search(text):
                new_text = pattern.sub(lambda _m: new_block, text, count=1)
            else:
                new_text = text.rstrip("\n") + "\n\n" + new_block

            self._atomic_write(new_text)
            return self.get_section("PUBLISHING_POLICY")

    def patch_auto_publishing(self, enabled: bool) -> dict:
        """AUTO_PUBLISHING.enabled만 저장한다(patch_blog_schedule()과 동일한
        섹션 블록 치환 방식). Weekly Planner의 실행 여부 자체는 이 메서드가
        결정하지 않는다 — 값을 저장할 뿐이며, 실제 실행 루프
        (modules.publishing_planner.run_planner_loop())는 이 STEP의 범위가
        아니다(감사 결론과 동일, 새로 연결하지 않음)."""
        with _CONFIG_WRITE_LOCK:
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")

            new_block = "AUTO_PUBLISHING:\n" + f"  enabled: {'true' if enabled else 'false'}\n"
            text = self._config_path.read_text(encoding="utf-8")
            pattern = re.compile(r"^AUTO_PUBLISHING:\n(?:[ \t].*\n?)*", re.MULTILINE)
            if pattern.search(text):
                new_text = pattern.sub(lambda _m: new_block, text, count=1)
            else:
                new_text = text.rstrip("\n") + "\n\n" + new_block

            self._atomic_write(new_text)
            return self.get_section("AUTO_PUBLISHING")

    def get_general_settings(self) -> dict:
        """API 키/WordPress URL·계정/Telegram/Budget/AI Roles 조회.
        secret 필드는 절대 원문을 반환하지 않고 {"configured": bool}만 반환한다.

        modules.config_loader.load_config()는 파이프라인 실행 전제(MODEL_* 필수 등)
        전체 검증을 수행하므로 여기서는 쓰지 않는다 — get_section()과 동일하게
        raw config.yaml만 읽고(_load_raw), secret 존재 여부만 load_secrets()로
        별도 확인한다(원문은 절대 조회 결과에 담지 않음)."""
        from modules.config_loader import load_secrets
        raw = self._load_raw()
        secrets = load_secrets(str(self._config_path))
        out = {}
        for key in GENERAL_PUBLIC_FIELDS:
            out[key] = raw.get(key)
        for key in GENERAL_SECRET_FIELDS:
            out[key] = {"configured": bool(secrets.get(key))}
        return out

    def patch_general_settings(self, updates: dict) -> dict:
        """updates에 있는 키만 부분 업데이트한다. 빈 문자열/None/빈 dict는
        "변경 안 함"으로 취급해 기존 값을 보존한다(§6). secret은
        modules.config_loader.save_secrets_flat(기존 함수, 새 저장소 생성 없음)을
        그대로 재사용해 secrets.yaml에, 나머지는 config.yaml에 저장한다.
        AI_ROLES는 role 단위로 병합한다(요청에 없는 role은 기존 값 유지)."""
        with _CONFIG_WRITE_LOCK:
            from modules.config_loader import save_secrets_flat

            secret_updates = {k: v for k, v in updates.items() if k in GENERAL_SECRET_FIELDS and v}
            public_updates = {k: v for k, v in updates.items() if k in GENERAL_PUBLIC_FIELDS and v}

            if secret_updates:
                save_secrets_flat(secret_updates, str(self._config_path))

            if public_updates:
                raw = self._load_raw()
                if "AI_ROLES" in public_updates:
                    merged_roles = dict(raw.get("AI_ROLES") or {})
                    merged_roles.update(public_updates["AI_ROLES"])
                    public_updates["AI_ROLES"] = merged_roles
                raw.update(public_updates)
                text = yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False)
                self._atomic_write(text)

            return self.get_general_settings()

    def get_image_google_settings(self) -> dict:
        """dashboard.py "🎨 블로그 이미지 생성 AI 설정"(3150-3183)/"📊 Google
        연동"(3186-3189) 조회(READ-ONLY). 7개 전부 secret이 아니므로 원문
        그대로 반환한다(마스킹 대상 아님, 모듈 docstring 재확인)."""
        raw = self._load_raw()
        return {key: raw.get(key, _IMAGE_GOOGLE_DEFAULTS[key]) for key in IMAGE_GOOGLE_FIELDS}

    def patch_image_google_settings(self, updates: dict) -> dict:
        """updates에 있는 키(None이 아닌 값)만 부분 업데이트한다 — 빈 문자열도
        명시적 변경으로 저장한다(원본이 텍스트 입력을 비우면 그대로 빈 문자열을
        저장하는 것과 동일한 의미론, GeneralSettingsUpdate의 falsy-필터링과는
        다름 — 모듈 docstring 참고). patch_general_settings()와 동일하게
        _load_raw()로 기존 config.yaml 전체를 읽고 대상 7개 키만 덮어써
        나머지 키는 완전히 보존한 뒤, 이미 검증된 _atomic_write()(임시파일→
        rename 원자적 교체)로 저장한다 — 새 저장 메커니즘을 만들지 않는다."""
        with _CONFIG_WRITE_LOCK:
            public_updates = {k: v for k, v in updates.items() if k in IMAGE_GOOGLE_FIELDS and v is not None}
            if public_updates:
                raw = self._load_raw()
                raw.update(public_updates)
                text = yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False)
                self._atomic_write(text)
            return self.get_image_google_settings()

    def get_calculator_display_settings(self) -> dict:
        """dashboard.py "🎨 계산기 노출 설정 (v2)"(3586-3634) 조회.
        14개 필드 전부 config.yaml top-level 평범한 값이며 secret이 아니므로
        원문 그대로 반환한다(마스킹 대상 아님)."""
        raw = self._load_raw()
        return {key: raw.get(key) for key in CALCULATOR_DISPLAY_FIELDS}

    def patch_calculator_display_settings(self, updates: dict) -> dict:
        """updates에 있는 키(None이 아닌 값)만 부분 업데이트한다 — 빈 문자열도
        명시적 변경으로 저장한다(원본이 텍스트 입력을 비우면 그대로 빈 문자열을
        저장하는 것과 동일한 의미론). _load_raw()로 기존 config.yaml 전체를 읽고
        대상 14개 키만 덮어써 나머지 키는 완전히 보존한 뒤,
        이미 검증된 _atomic_write()(임시파일→rename 원자적 교체)로 저장한다."""
        with _CONFIG_WRITE_LOCK:
            public_updates = {k: v for k, v in updates.items() if k in CALCULATOR_DISPLAY_FIELDS and v is not None}
            if public_updates:
                raw = self._load_raw()
                raw.update(public_updates)
                text = yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False)
                self._atomic_write(text)
            return self.get_calculator_display_settings()

    def patch_calc_webapp_schedule(self, enabled: bool = None, mode: str = None, targets: list = None, poll_seconds: int = None) -> dict:
        """CALC_WEBAPP_SCHEDULE 블록만 정규식으로 치환한다. 파일의 다른 부분(주석 포함)은
        건드리지 않는다. 저장 전 값 검증을 통과하지 못하면 파일을 쓰지 않는다.

        중요: mode가 "qa_deploy"라도 FastAPI 자동 Worker는 GitHub Deploy/Registry Publish를
        실행하지 않는다. 자동 Worker는 Build/QA/_site만 담당한다. Deploy/Registry는
        별도 명시적 endpoint(/calculator/{id}/deploy, /calculator/{id}/publish)로 분리한다."""
        with _CONFIG_WRITE_LOCK:
            # Validate only provided fields
            if enabled is not None and not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            if mode is not None and mode not in _CALC_WEBAPP_MODES:
                raise ValueError(f"mode must be one of {_CALC_WEBAPP_MODES}")
            if targets is not None:
                if not isinstance(targets, list):
                    raise ValueError("targets must be a list")
                for t in targets:
                    if not isinstance(t, str) or not t.strip():
                        raise ValueError("each target must be a non-empty string")
            if poll_seconds is not None:
                if not isinstance(poll_seconds, int) or poll_seconds < 1:
                    raise ValueError("poll_seconds must be a positive integer")

            # Load current section to preserve unspecified fields
            current = self.get_section("CALC_WEBAPP_SCHEDULE")
            enabled = current.get("enabled", False) if enabled is None else enabled
            mode = current.get("mode", "qa_only") if mode is None else mode
            targets = current.get("targets", []) if targets is None else targets
            poll_seconds = current.get("poll_seconds", 30) if poll_seconds is None else poll_seconds

            block_lines = [
                "CALC_WEBAPP_SCHEDULE:",
                f"  enabled: {'true' if enabled else 'false'}",
                f"  mode: {mode}",
                "  targets:",
            ]
            for target in targets:
                block_lines.append(f'  - "{target}"')
            block_lines.append(f"  poll_seconds: {poll_seconds}")
            new_block = "\n".join(block_lines) + "\n"

            text = self._config_path.read_text(encoding="utf-8")
            pattern = re.compile(r"^CALC_WEBAPP_SCHEDULE:\n(?:[ \t].*\n?)*", re.MULTILINE)
            if pattern.search(text):
                new_text = pattern.sub(lambda _m: new_block, text, count=1)
            else:
                new_text = text.rstrip("\n") + "\n\n" + new_block

            self._atomic_write(new_text)
            return self.get_section("CALC_WEBAPP_SCHEDULE")

    def _atomic_write(self, text: str):
        tmp_path = self._config_path.with_name(self._config_path.name + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self._config_path)  # 같은 파일시스템 내 원자적 교체

    @staticmethod
    def _validate_blog_schedule(enabled, mode, publish_slots, weekday_only):
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if mode not in _BLOG_MODES:
            raise ValueError(f"mode must be one of {_BLOG_MODES}")
        if not isinstance(publish_slots, list) or not publish_slots:
            raise ValueError("publish_slots must be a non-empty list")
        for slot in publish_slots:
            if not isinstance(slot, dict) or "start" not in slot or "end" not in slot:
                raise ValueError("each slot needs start/end")
            if not _TIME_RE.match(str(slot["start"])) or not _TIME_RE.match(str(slot["end"])):
                raise ValueError("start/end must be HH:MM (00:00-23:59)")
            if str(slot["start"]) >= str(slot["end"]):
                raise ValueError("slot start must be before end")
        if not isinstance(weekday_only, bool):
            raise ValueError("weekday_only must be a boolean")

    @staticmethod
    def _mask_secrets(value):
        if isinstance(value, dict):
            masked = {}
            for k, v in value.items():
                if isinstance(k, str) and any(k.upper().endswith(suf) for suf in _SECRET_KEY_SUFFIXES):
                    masked[k] = "****"
                else:
                    masked[k] = ConfigService._mask_secrets(v)
            return masked
        if isinstance(value, list):
            return [ConfigService._mask_secrets(v) for v in value]
        return value
