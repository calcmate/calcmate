# -*- coding: utf-8 -*-
"""
tools/dev_assistant.py — OpenRouter 보조 개발자 CLI

Claude Code 사용량이 많을 때 OpenRouter 무료 모델로
CalcMate 코드 분석·리뷰·간단한 수정 제안을 수행한다.

이 스크립트는 직접 파일을 수정하지 않는다.
모든 응답은 사용자가 검토 후 적용한다.

사용법:
  python tools/dev_assistant.py                              # 대화형 모드
  python tools/dev_assistant.py --ping                      # 연결 테스트
  python tools/dev_assistant.py --file modules/app_factory.py
  python tools/dev_assistant.py --file modules/ai_provider.py \\
      --question "이 파일의 구조를 설명해줘"               # 1회 질의
  python tools/dev_assistant.py --model nvidia/nemotron-3-super-120b-a12b:free

대화형 모드 명령:
  /model      무료 모델 선택 메뉴
  :file PATH  파일 컨텍스트 추가
  q / exit    종료

환경변수 / config/secrets.yaml:
  OPENROUTER_API_KEY  필수 (openrouter.ai/keys)
  OPENROUTER_MODEL    선택 (기본값: FREE_MODELS[0])
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows cp949 터미널에서 한국어/특수문자 출력 안전하게 처리
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 무료 모델 고정 목록 (비용 안전 원칙: :free 모델만 포함) ──────────────────
# OpenRouter 실제 가용 확인일: 2026-08-12
FREE_MODELS = [
    {
        "label":   "NVIDIA Nemotron Super 120B",
        "id":      "nvidia/nemotron-3-super-120b-a12b:free",
        "ctx":     262144,
        "note":    "120B MoE(12B 활성), 추론·코드 균형, 262K ctx",
    },
    {
        "label":   "Cohere North Mini Code",
        "id":      "cohere/north-mini-code:free",
        "ctx":     256000,
        "note":    "코드 특화 MoE(3B 활성), 256K ctx",
    },
    {
        "label":   "OpenAI OSS 20B",
        "id":      "openai/gpt-oss-20b:free",
        "ctx":     131072,
        "note":    "OpenAI 오픈소스 20B, 한국어 지원, 131K ctx",
    },
]
# 참고: google/gemma-4-31b-it:free는 Google AI Studio 공유 풀 rate limit으로 대체됨 (2026-08-12)

# 기본 모델 — FREE_MODELS[0] 고정 (유료 모델이 기본으로 사용되지 않도록)
DEFAULT_MODEL = FREE_MODELS[0]["id"]

LOG_PATH = ROOT / "data" / "logs" / "dev_assistant.jsonl"

# 보조 개발자 시스템 프롬프트
_SYSTEM = """너는 CalcMate(SalaryMate v12) 프로젝트의 보조 개발자다.

[프로젝트 개요]
- SalaryMate v12: React/FastAPI + Python 기반 한국 급여·노동법 계산기 플랫폼
- 핵심 모듈: formula_engine.py, app_factory.py, ai_provider.py, api/(FastAPI), frontend/(React)
- 계약 구조: Formula Lifecycle (not_generated → ai_suggested → pending_validation → operator_confirmed)
- 주요 계층: Registry(YAML) / Contract Instance(YAML) / App Factory / Formula Engine

[역할]
- 코드 분석, 리뷰, 설명
- 버그 원인 분석 및 수정 방향 제안
- 테스트 실패 원인 분석
- 소규모 수정 코드 제안 (적용은 사용자가 직접)

[제한]
- Registry / Contract 핵심 구조는 임의로 변경하지 않는다
- 대규모 리팩터링, 배포 구조 변경은 제안만 하고 결정은 사용자에게 맡긴다
- 한국어로 답변한다. 코드 블록은 언어 태그를 붙인다.
- 민감 정보(API Key, 비밀번호)는 절대 요청하지 않고 출력하지 않는다."""


# ── 키/모델 로드 ──────────────────────────────────────────────────────────────
def _load_api_key() -> str:
    """
    OPENROUTER_API_KEY를 다음 순서로 탐색:
    1. 환경변수 OPENROUTER_API_KEY
    2. config/secrets.yaml OPENROUTER_API_KEY
    """
    env_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env_key:
        return env_key

    secrets_path = ROOT / "config" / "secrets.yaml"
    if secrets_path.exists():
        try:
            import yaml
            data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
            key = (data.get("OPENROUTER_API_KEY") or "").strip()
            if key:
                return key
        except Exception:
            pass

    return ""


def _load_model(cli_model: str | None) -> str:
    """모델명을 CLI arg → env → secrets.yaml → DEFAULT_MODEL 순으로 결정.
    secrets.yaml에 유료 모델이 설정되어 있어도 /model 기본 목록은 영향 없음."""
    if cli_model:
        return cli_model.strip()
    env_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if env_model:
        return env_model
    secrets_path = ROOT / "config" / "secrets.yaml"
    if secrets_path.exists():
        try:
            import yaml
            data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
            m = (data.get("OPENROUTER_MODEL") or "").strip()
            if m:
                return m
        except Exception:
            pass
    return DEFAULT_MODEL


# ── 파일 컨텍스트 ─────────────────────────────────────────────────────────────
_READ_LIMIT = 40_000


def _read_file_safe(rel_or_abs: str) -> str:
    """CalcMate 프로젝트 내 파일을 안전하게 읽는다 (ROOT escape 금지)."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = (ROOT / rel_or_abs).resolve()
    else:
        p = p.resolve()

    if ROOT not in p.parents and p != ROOT:
        raise ValueError(f"프로젝트 외부 파일 접근 금지: {rel_or_abs}")
    if not p.exists():
        raise FileNotFoundError(f"파일 없음: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"디렉터리는 직접 읽을 수 없음: {p}")

    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > _READ_LIMIT:
        text = text[:_READ_LIMIT] + f"\n\n... (이하 {len(text) - _READ_LIMIT}자 생략)"
    return text


def _build_context(files: list[str]) -> str:
    if not files:
        return ""
    parts = []
    for f in files:
        try:
            content = _read_file_safe(f)
            rel = str(Path(f))
            parts.append(f"[파일: {rel}]\n```\n{content}\n```")
        except (ValueError, FileNotFoundError, IsADirectoryError) as e:
            parts.append(f"[파일 로드 실패: {f}] {e}")
    return "\n\n".join(parts)


# ── 로깅 ──────────────────────────────────────────────────────────────────────
def _log(entry: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── OpenRouter 호출 ───────────────────────────────────────────────────────────
def ask(question: str, context: str, model: str, api_key: str) -> tuple[str, int]:
    """OpenRouterProvider를 통해 (응답, 토큰) 반환."""
    from modules.ai_provider import OpenRouterProvider
    provider = OpenRouterProvider(api_key)

    user_msg = question
    if context:
        user_msg = f"[참고 코드]\n{context}\n\n[질문]\n{question}"

    return provider.chat(
        system=_SYSTEM,
        user=user_msg,
        model=model,
        max_tokens=4096,
    )


# ── /model 선택 메뉴 ──────────────────────────────────────────────────────────
def select_model_menu(current_model: str) -> str:
    """
    /model 명령 처리 — 무료 모델 목록 표시 후 번호 입력으로 선택.
    취소(q / 빈 입력): 현재 모델 유지.
    잘못된 번호: 안내 메시지 출력 후 현재 모델 유지.
    반환: 선택된 모델 ID (변경 없으면 current_model 그대로)
    """
    print()
    print("  OpenRouter 무료 모델 선택")
    print(f"  현재 모델: {current_model}")
    print()
    for i, m in enumerate(FREE_MODELS, start=1):
        marker = " ◀" if m["id"] == current_model else ""
        print(f"  {i}. {m['label']}{marker}")
        print(f"     {m['id']}")
        print(f"     {m['note']}")
        print()
    print(f"  번호를 선택하세요 (1-{len(FREE_MODELS)}) / q=취소:")

    try:
        choice = input("  선택> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("  취소됨.")
        return current_model

    if not choice or choice.lower() in ("q", "exit", "취소"):
        print("  취소됨. 기존 모델 유지.")
        return current_model

    try:
        idx = int(choice)
        if 1 <= idx <= len(FREE_MODELS):
            selected = FREE_MODELS[idx - 1]
            print(f"  선택됨: {selected['label']}")
            print(f"  모델: {selected['id']}")
            return selected["id"]
        else:
            print(f"  잘못된 선택입니다. 1~{len(FREE_MODELS)} 중에서 선택하세요.")
            return current_model
    except ValueError:
        print(f"  잘못된 입력입니다. 1~{len(FREE_MODELS)} 중 숫자를 입력하세요.")
        return current_model


# ── 연결 테스트 ───────────────────────────────────────────────────────────────
def ping(api_key: str, model: str) -> bool:
    """OpenRouter API 연결 및 모델 가용성을 최소 토큰으로 확인."""
    print(f"[ping] 모델: {model}")
    print("[ping] 엔드포인트: https://openrouter.ai/api/v1")
    try:
        resp, tokens = ask("Ping. 한 문장으로만 응답하라.", "", model, api_key)
        print(f"[ping] 응답: {resp[:120]}")
        print(f"[ping] 토큰: {tokens}")
        _log({"ts": datetime.now().isoformat(), "type": "ping",
              "model": model, "tokens": tokens, "ok": True})
        print("[ping] OK")
        return True
    except Exception as e:
        print(f"[ping] FAIL -- {e}")
        _log({"ts": datetime.now().isoformat(), "type": "ping",
              "model": model, "ok": False, "error": str(e)})
        return False


# ── 1회 질의 ──────────────────────────────────────────────────────────────────
def one_shot(question: str, files: list[str], model: str, api_key: str):
    context = _build_context(files)
    print(f"\n[모델] {model}")
    if files:
        print(f"[컨텍스트] {', '.join(files)}")
    print("-" * 60)
    try:
        resp, tokens = ask(question, context, model, api_key)
        print(resp)
        print(f"\n-- 토큰: {tokens} --")
        _log({"ts": datetime.now().isoformat(), "type": "one_shot",
              "model": model, "files": files, "tokens": tokens,
              "question_len": len(question), "ok": True})
    except Exception as e:
        print(f"[오류] {e}")
        _log({"ts": datetime.now().isoformat(), "type": "one_shot",
              "model": model, "files": files, "ok": False, "error": str(e)})


# ── 대화형 모드 ───────────────────────────────────────────────────────────────
def interactive(files: list[str], model: str, api_key: str):
    context = _build_context(files)
    print("=" * 60)
    print("  CalcMate 보조 개발자 (OpenRouter 무료 모드)")
    print(f"  모델 : {model}")
    if files:
        print(f"  파일 : {', '.join(files)}")
    print("  종료 : q / exit / quit")
    print("  모델 변경 : /model")
    print("  파일 추가 : :file <경로>")
    print("=" * 60)

    session_files = list(files)
    current_model = model

    while True:
        try:
            line = input(f"\n[{current_model.split('/')[1] if '/' in current_model else current_model}] 질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not line:
            continue
        if line.lower() in ("q", "exit", "quit"):
            print("종료합니다.")
            break

        # /model 명령
        if line.lower() == "/model":
            current_model = select_model_menu(current_model)
            continue

        # 파일 추가 명령
        if line.startswith(":file "):
            new_file = line[6:].strip()
            try:
                _ = _read_file_safe(new_file)
                session_files.append(new_file)
                context = _build_context(session_files)
                print(f"[파일 추가] {new_file}")
            except Exception as e:
                print(f"[파일 오류] {e}")
            continue

        try:
            resp, tokens = ask(line, context, current_model, api_key)
            print(f"\n{resp}")
            print(f"\n-- 토큰: {tokens} --")
            _log({"ts": datetime.now().isoformat(), "type": "interactive",
                  "model": current_model, "files": session_files,
                  "tokens": tokens, "question_len": len(line), "ok": True})
        except Exception as e:
            print(f"[오류] {e}")
            _log({"ts": datetime.now().isoformat(), "type": "interactive",
                  "model": current_model, "files": session_files,
                  "ok": False, "error": str(e)})


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="CalcMate OpenRouter 보조 개발자 (무료 모델 전용)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            [f"  {i+1}. {m['label']}  ({m['id']})" for i, m in enumerate(FREE_MODELS)]
        ),
    )
    parser.add_argument("--ping",     action="store_true", help="API 연결 테스트")
    parser.add_argument("--file",     action="append", default=[], metavar="PATH",
                        help="컨텍스트로 포함할 CalcMate 파일 (반복 가능)")
    parser.add_argument("--question", "-q", default="", metavar="Q",
                        help="1회 질문 (생략 시 대화형 모드)")
    parser.add_argument("--model",    default="", metavar="MODEL",
                        help=f"OpenRouter 모델명 직접 지정 (기본: {DEFAULT_MODEL})")
    args = parser.parse_args()

    api_key = _load_api_key()
    model   = _load_model(args.model or None)

    if not api_key:
        print("[오류] OPENROUTER_API_KEY가 설정되지 않았습니다.")
        print()
        print("  설정 방법:")
        print("  1. config/secrets.yaml 열기")
        print("     OPENROUTER_API_KEY: 'sk-or-v1-여기에입력'")
        print("  2. 또는 환경변수:")
        print("     set OPENROUTER_API_KEY=sk-or-v1-여기에입력")
        print()
        print("  키 발급: https://openrouter.ai/keys")
        sys.exit(1)

    if args.ping:
        ok = ping(api_key, model)
        sys.exit(0 if ok else 1)

    if args.question:
        one_shot(args.question, args.file, model, api_key)
    else:
        interactive(args.file, model, api_key)


if __name__ == "__main__":
    main()
