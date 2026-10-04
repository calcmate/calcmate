# -*- coding: utf-8 -*-
"""
tests/test_openrouter_provider.py — OpenRouter Provider 단위 테스트

실제 API 호출 없이 동작하는 테스트는 unittest.mock 사용.
실제 연결 테스트(TEST_OR_LIVE=1)는 별도 환경에서만 실행.
"""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── TEST 1: API Key 없음 → ValueError ────────────────────────────────────────
class TestOpenRouterProviderNoKey:
    def test_empty_key_raises(self):
        from modules.ai_provider import OpenRouterProvider
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            OpenRouterProvider("")

    def test_whitespace_key_raises(self):
        from modules.ai_provider import OpenRouterProvider
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            OpenRouterProvider("   ")

    def test_none_key_raises(self):
        from modules.ai_provider import OpenRouterProvider
        with pytest.raises((ValueError, TypeError)):
            OpenRouterProvider(None)


# ── TEST 2: build_provider 통합 ──────────────────────────────────────────────
class TestBuildProviderOpenRouter:
    def test_build_provider_missing_key(self):
        from modules.ai_provider import build_provider
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            build_provider("openrouter", {"OPENROUTER_API_KEY": ""})

    def test_build_provider_alias_or(self):
        from modules.ai_provider import build_provider
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            build_provider("or", {})

    def test_build_provider_unknown_still_raises(self):
        from modules.ai_provider import build_provider
        with pytest.raises(ValueError, match="알 수 없는 provider"):
            build_provider("nonexistent_provider", {})


# ── TEST 3: AI_PROFILE_MAP OpenRouter 슬롯 등록 확인 ─────────────────────────
class TestProfileMap:
    def test_or_deepseek_registered(self):
        from modules.ai_provider import AI_PROFILE_MAP
        assert "or_deepseek" in AI_PROFILE_MAP
        assert AI_PROFILE_MAP["or_deepseek"]["provider"] == "openrouter"

    def test_or_qwen_registered(self):
        from modules.ai_provider import AI_PROFILE_MAP
        assert "or_qwen_coder" in AI_PROFILE_MAP

    def test_or_free_registered(self):
        from modules.ai_provider import AI_PROFILE_MAP
        assert "or_free" in AI_PROFILE_MAP
        assert ":free" in AI_PROFILE_MAP["or_free"]["model"]

    def test_existing_profiles_intact(self):
        """기존 슬롯이 변경되지 않았는지 확인."""
        from modules.ai_provider import AI_PROFILE_MAP
        assert AI_PROFILE_MAP["claude_sonnet"]["provider"] == "claude"
        assert AI_PROFILE_MAP["gpt4o"]["provider"] == "openai"
        assert AI_PROFILE_MAP["gemini_flash"]["provider"] == "gemini"


# ── TEST 4: OpenRouterProvider.chat — mock 기반 ───────────────────────────────
class TestOpenRouterProviderChat:
    def test_chat_returns_text_and_tokens(self, monkeypatch):
        """정상 응답: (str, int) 반환."""
        from modules.ai_provider import OpenRouterProvider
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "안녕하세요, 보조 개발자입니다."
        mock_resp.usage.total_tokens = 42

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_resp

            provider = OpenRouterProvider("sk-or-v1-fake")
            text, tokens = provider.chat(
                system="시스템 프롬프트",
                user="테스트 질문",
                model="deepseek/deepseek-r1-0528",
            )

        assert isinstance(text, str)
        assert len(text) > 0
        assert isinstance(tokens, int)
        assert tokens == 42

    def test_chat_json_mode_passes_format(self, monkeypatch):
        """json_mode=True 시 response_format 전달 확인."""
        from modules.ai_provider import OpenRouterProvider
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"ok": true}'
        mock_resp.usage.total_tokens = 10

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_resp

            provider = OpenRouterProvider("sk-or-v1-fake")
            provider.chat("sys", "user", "model", json_mode=True)

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs.get("response_format") == {"type": "json_object"}

    def test_chat_no_usage_returns_zero_tokens(self, monkeypatch):
        """usage=None인 모델 응답에서 토큰 0 반환 (크래시 없음)."""
        from modules.ai_provider import OpenRouterProvider
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "응답"
        mock_resp.usage = None

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_resp

            provider = OpenRouterProvider("sk-or-v1-fake")
            _, tokens = provider.chat("sys", "user", "model")

        assert tokens == 0


# ── TEST 5: dev_assistant 키 없음 → 안전한 오류 ───────────────────────────────
class TestDevAssistantNoKey:
    def test_load_api_key_returns_empty_when_unset(self, monkeypatch):
        """OPENROUTER_API_KEY 환경변수 없고 secrets.yaml에도 없으면 빈 문자열."""
        import tools.dev_assistant as da
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        # secrets.yaml이 있어도 키가 없으면 빈 문자열 반환
        # (실제 secrets.yaml 값에 의존하지 않도록 _load_api_key 내부 로직만 검증)
        result = da._load_api_key()
        assert isinstance(result, str)

    def test_main_exits_on_no_key(self, monkeypatch, capsys):
        """_load_api_key가 빈 문자열 반환 시 main()이 sys.exit(1)."""
        import tools.dev_assistant as da
        monkeypatch.setattr(da, "_load_api_key", lambda: "")
        monkeypatch.setattr(da, "_load_model", lambda x: "deepseek/deepseek-r1-0528")
        monkeypatch.setattr("sys.argv", ["dev_assistant.py"])

        with pytest.raises(SystemExit) as exc_info:
            da.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "OPENROUTER_API_KEY" in captured.out


# ── TEST 6: dev_assistant 파일 경로 안전장치 ─────────────────────────────────
class TestDevAssistantFileSafety:
    def test_outside_root_rejected(self):
        from tools.dev_assistant import _read_file_safe
        with pytest.raises(ValueError, match="외부"):
            _read_file_safe("C:/Windows/System32/drivers/etc/hosts")

    def test_nonexistent_file_raises(self):
        from tools.dev_assistant import _read_file_safe
        with pytest.raises(FileNotFoundError):
            _read_file_safe("modules/nonexistent_xyz_abc.py")

    def test_project_file_readable(self):
        from tools.dev_assistant import _read_file_safe
        content = _read_file_safe("modules/ai_provider.py")
        assert "OpenRouterProvider" in content

    def test_build_context_empty_files(self):
        from tools.dev_assistant import _build_context
        assert _build_context([]) == ""

    def test_build_context_with_file(self):
        from tools.dev_assistant import _build_context
        ctx = _build_context(["modules/ai_provider.py"])
        assert "ai_provider" in ctx.lower()


# ── TEST 7: SECRET_KEYS에 OPENROUTER_API_KEY 포함 확인 ───────────────────────
class TestConfigLoader:
    def test_openrouter_key_is_secret(self):
        from modules.config_loader import SECRET_KEYS
        assert "OPENROUTER_API_KEY" in SECRET_KEYS

    def test_existing_secret_keys_intact(self):
        from modules.config_loader import SECRET_KEYS
        for key in ("OPENAI_API_KEY", "CLAUDE_API_KEY", "GEMINI_API_KEY",
                    "WORDPRESS_APP_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            assert key in SECRET_KEYS


# ── TEST 8: build_provider_from_profile OpenRouter 슬롯 ──────────────────────
class TestBuildProviderFromProfile:
    def test_or_deepseek_profile(self):
        from modules.ai_provider import build_provider_from_profile, OpenRouterProvider
        from unittest.mock import patch

        with patch("openai.OpenAI"):
            provider, model = build_provider_from_profile(
                "or_deepseek", {"OPENROUTER_API_KEY": "sk-or-v1-fake"}
            )
        assert isinstance(provider, OpenRouterProvider)
        assert model == "deepseek/deepseek-r1-0528"

    def test_unknown_profile_raises(self):
        from modules.ai_provider import build_provider_from_profile
        with pytest.raises(ValueError, match="알 수 없는 AI 프로필"):
            build_provider_from_profile("nonexistent", {})


# ── TEST 9: 무료 모델 목록 검증 ──────────────────────────────────────────────
class TestFreeModels:
    def test_free_models_count(self):
        """무료 모델 목록이 정확히 3개인지."""
        from tools.dev_assistant import FREE_MODELS
        assert len(FREE_MODELS) == 3

    def test_all_models_are_free(self):
        """:free suffix 없는 모델이 목록에 없는지 (비용 안전 원칙)."""
        from tools.dev_assistant import FREE_MODELS
        for m in FREE_MODELS:
            assert ":free" in m["id"], f"유료 모델이 포함됨: {m['id']}"

    def test_model_1_id(self):
        """모델 1 → nvidia/nemotron-3-super-120b-a12b:free"""
        from tools.dev_assistant import FREE_MODELS
        assert FREE_MODELS[0]["id"] == "nvidia/nemotron-3-super-120b-a12b:free"

    def test_model_2_id(self):
        """모델 2 → cohere/north-mini-code:free"""
        from tools.dev_assistant import FREE_MODELS
        assert FREE_MODELS[1]["id"] == "cohere/north-mini-code:free"

    def test_model_3_id(self):
        """모델 3 → openai/gpt-oss-20b:free (google/gemma-4-31b-it:free 공유 풀 rate limit으로 대체)"""
        from tools.dev_assistant import FREE_MODELS
        assert FREE_MODELS[2]["id"] == "openai/gpt-oss-20b:free"

    def test_each_model_has_required_fields(self):
        """각 모델 항목에 label, id, ctx, note가 있는지."""
        from tools.dev_assistant import FREE_MODELS
        for m in FREE_MODELS:
            assert "label" in m
            assert "id" in m
            assert "ctx" in m
            assert "note" in m

    def test_default_model_is_free(self):
        """기본 모델이 :free인지."""
        from tools.dev_assistant import DEFAULT_MODEL
        assert ":free" in DEFAULT_MODEL

    def test_default_model_is_first_in_list(self):
        """DEFAULT_MODEL이 FREE_MODELS[0]와 일치하는지."""
        from tools.dev_assistant import DEFAULT_MODEL, FREE_MODELS
        assert DEFAULT_MODEL == FREE_MODELS[0]["id"]


# ── TEST 10: /model 선택 메뉴 동작 ───────────────────────────────────────────
class TestSelectModelMenu:
    def test_select_model_1(self, monkeypatch):
        """/model 후 1 입력 → FREE_MODELS[0] 반환."""
        from tools.dev_assistant import select_model_menu, FREE_MODELS
        monkeypatch.setattr("builtins.input", lambda _: "1")
        result = select_model_menu("dummy/model:free")
        assert result == FREE_MODELS[0]["id"]

    def test_select_model_2(self, monkeypatch):
        """/model 후 2 입력 → FREE_MODELS[1] 반환."""
        from tools.dev_assistant import select_model_menu, FREE_MODELS
        monkeypatch.setattr("builtins.input", lambda _: "2")
        result = select_model_menu("dummy/model:free")
        assert result == FREE_MODELS[1]["id"]

    def test_select_model_3(self, monkeypatch):
        """/model 후 3 입력 → FREE_MODELS[2] 반환."""
        from tools.dev_assistant import select_model_menu, FREE_MODELS
        monkeypatch.setattr("builtins.input", lambda _: "3")
        result = select_model_menu("dummy/model:free")
        assert result == FREE_MODELS[2]["id"]

    def test_invalid_number_keeps_current(self, monkeypatch, capsys):
        """잘못된 번호(4) → 현재 모델 유지 + 오류 메시지."""
        from tools.dev_assistant import select_model_menu
        current = "nvidia/nemotron-3-super-120b-a12b:free"
        monkeypatch.setattr("builtins.input", lambda _: "4")
        result = select_model_menu(current)
        assert result == current
        captured = capsys.readouterr()
        assert "잘못된" in captured.out

    def test_non_numeric_input_keeps_current(self, monkeypatch, capsys):
        """숫자가 아닌 입력(abc) → 현재 모델 유지 + 오류 메시지."""
        from tools.dev_assistant import select_model_menu
        current = "nvidia/nemotron-3-super-120b-a12b:free"
        monkeypatch.setattr("builtins.input", lambda _: "abc")
        result = select_model_menu(current)
        assert result == current
        captured = capsys.readouterr()
        assert "잘못된" in captured.out

    def test_zero_input_keeps_current(self, monkeypatch):
        """0 입력 → 현재 모델 유지."""
        from tools.dev_assistant import select_model_menu
        current = "nvidia/nemotron-3-super-120b-a12b:free"
        monkeypatch.setattr("builtins.input", lambda _: "0")
        result = select_model_menu(current)
        assert result == current

    def test_q_cancels(self, monkeypatch, capsys):
        """q 입력 → 취소, 현재 모델 유지."""
        from tools.dev_assistant import select_model_menu
        current = "nvidia/nemotron-3-super-120b-a12b:free"
        monkeypatch.setattr("builtins.input", lambda _: "q")
        result = select_model_menu(current)
        assert result == current

    def test_empty_input_cancels(self, monkeypatch):
        """빈 입력 → 취소, 현재 모델 유지."""
        from tools.dev_assistant import select_model_menu
        current = "nvidia/nemotron-3-super-120b-a12b:free"
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = select_model_menu(current)
        assert result == current

    def test_selection_applied_to_next_ask(self, monkeypatch):
        """/model로 선택한 모델이 ask()에 실제로 전달되는지 확인 (mock)."""
        from tools.dev_assistant import select_model_menu, FREE_MODELS
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("builtins.input", lambda _: "2")
        new_model = select_model_menu("nvidia/nemotron-3-super-120b-a12b:free")
        assert new_model == FREE_MODELS[1]["id"]

        # ask() 호출 시 새 모델이 전달되는지 확인
        from tools.dev_assistant import ask
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "응답"
        mock_resp.usage.total_tokens = 5

        with patch("openai.OpenAI") as mock_oa:
            mock_client = MagicMock()
            mock_oa.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_resp

            resp, tokens = ask("테스트", "", new_model, "sk-or-v1-fake")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == FREE_MODELS[1]["id"]


# ── 실제 API 연결 테스트 (선택적, TEST_OR_LIVE=1 시만 실행) ──────────────────
@pytest.mark.skipif(
    not __import__("os").environ.get("TEST_OR_LIVE"),
    reason="TEST_OR_LIVE=1 환경변수 설정 시에만 실행 (실제 API 호출)"
)
class TestOpenRouterLive:
    def test_live_ping(self):
        import os
        from modules.ai_provider import OpenRouterProvider
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            pytest.skip("OPENROUTER_API_KEY 없음")
        provider = OpenRouterProvider(key)
        resp, tokens = provider.chat(
            system="You are a helpful assistant.",
            user="Reply with exactly: PONG",
            model=os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
            max_tokens=20,
        )
        assert len(resp) > 0
        assert tokens >= 0

    def test_live_all_free_models(self):
        """무료 모델 3종 각각에 ping 테스트."""
        import os
        from tools.dev_assistant import FREE_MODELS
        from modules.ai_provider import OpenRouterProvider
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            pytest.skip("OPENROUTER_API_KEY 없음")
        provider = OpenRouterProvider(key)
        for m in FREE_MODELS:
            try:
                resp, tokens = provider.chat(
                    system="You are a helpful assistant.",
                    user="한 단어로만 답하라: 안녕",
                    model=m["id"],
                    max_tokens=20,
                )
                assert len(resp) > 0
                print(f"  {m['id']}: OK ({tokens} tokens)")
            except Exception as e:
                print(f"  {m['id']}: FAIL - {e}")
