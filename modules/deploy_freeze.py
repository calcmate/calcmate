# -*- coding: utf-8 -*-
"""modules/deploy_freeze.py — 계산기 배포 동결 플래그(CALCMATE-PUBLIC-SAFETY-DEPLOY-FREEZE, 안 B2).

계산기 산출물을 바꾸거나 공개할 수 있는 서버 경로(P1 계산기별 Deploy, P2 전체 사이트
재빌드, P7 calc_webapp 스케줄러)는 진입 직후 is_frozen()을 확인해 동결 중이면 아무 작업도
하지 않고 차단한다. 사이트 공통 페이지(P3)·블로그 경로는 대상이 아니다.

동결 상태는 저장소 루트의 표식 파일 data/workspace/DEPLOY_FREEZE 존재 여부로 정한다
(data/workspace/* 는 .gitignore 대상 — 로컬 운영 상태이며 커밋되지 않는다).
표식 파일 존재를 확인할 수 없으면(권한·I/O 오류) 동결로 간주한다(fail-closed).

CALCMATE_DEPLOY_FREEZE_MARKER 환경변수로 표식 파일 경로를 바꿀 수 있다(격리 테스트용).
"""
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKER = _REPO_ROOT / "data" / "workspace" / "DEPLOY_FREEZE"
MARKER_ENV = "CALCMATE_DEPLOY_FREEZE_MARKER"

FROZEN_MESSAGE = ("🔒 배포 동결 중 — 계산기 Deploy/전체 재빌드/자동 생성이 일시 중지되었습니다"
                  "(data/workspace/DEPLOY_FREEZE). 해제는 별도 승인 후 표식 파일을 제거하세요.")


def marker_path() -> Path:
    override = os.environ.get(MARKER_ENV)
    return Path(override) if override else DEFAULT_MARKER


def is_frozen() -> bool:
    """동결이면 True. 표식 파일 확인 자체가 실패하면 True(fail-closed)."""
    try:
        return marker_path().exists()
    except Exception:
        return True
