# -*- coding: utf-8 -*-
"""publisher_base.py — Publisher 인터페이스 및 안전한 기본 구현(NullPublisher)"""
from abc import ABC, abstractmethod
from modules.logger import get_logger

LOG = get_logger()


class BasePublisher(ABC):
    """WordPress Draft 생성 Publisher 공통 인터페이스."""

    @abstractmethod
    def create_draft(self, metadata: dict) -> str:
        """성공 시 post_id(str), 실패 시 "FAILED"를 반환한다."""
        raise NotImplementedError


class NullPublisher(BasePublisher):
    """실제 네트워크를 전혀 사용하지 않는 안전한 기본 Publisher.

    DI 미지정 시 기본값으로 쓰인다. 실제 WordPress post ID로 오해될 수 있는
    값을 반환하지 않으며, credentials/URL을 갖지 않으므로 로그에 노출할 것도 없다.
    """

    def create_draft(self, metadata: dict) -> str:
        LOG.info("[NULL PUBLISHER] create_draft 호출됨 — 실제 네트워크 요청 없음")
        return "NULL_PUBLISHER_NO_OP"


class NullMediaUploader:
    """실제 네트워크를 전혀 사용하지 않는 안전한 기본 MediaUploader.

    EngineAdapter DI 미지정 시 기본값으로 쓰인다. 기존
    WordPressMediaUploader(완전 Mock 구현)의 반환값("999")과 동일하게 맞춰
    호출부(EngineAdapter.run_content_generation)의 기존 동작을 그대로 보존한다.
    credentials/URL을 갖지 않는다.
    """

    def upload_image(self, *args, **kwargs) -> str:
        LOG.info("[NULL MEDIA UPLOADER] upload_image 호출됨 — 실제 네트워크 요청 없음")
        return "999"
