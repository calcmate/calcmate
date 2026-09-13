# -*- coding: utf-8 -*-
"""
adapters/db/content_splitter.py — Google Sheets 50,000자 셀 제한 대응 분할/재조립

IRP-22에서 설계하고 IRP-23에서 구현한, app_templates.html_template처럼
50,000자를 넘을 수 있는 콘텐츠를 Sheets 백업용으로 분할/재조립/무결성
검증하기 위한 순수 함수 모음. DB/Sheets 접근 없음(부작용 없음).

문자(코드포인트) 단위로 분할한다(바이트 단위 아님) — content[i:i+max_chars].
"""
import hashlib

MAX_CHARS = 50000


class IntegrityError(Exception):
    """parts 무결성 검증 실패."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_content(content: str, max_chars: int = MAX_CHARS) -> list[dict]:
    """content를 max_chars 단위(문자 수 기준)로 분할해 part dict 리스트로 반환한다.
    빈 문자열도 최소 1개의(빈) part를 생성한다 — total_parts=0인 상태를 만들지 않기 위함."""
    content = content or ""
    chunks = [content[i:i + max_chars] for i in range(0, len(content), max_chars)] or [""]
    total_parts = len(chunks)
    full_hash = _sha256(content)
    return [
        {
            "part_no": i,
            "content": chunk,
            "content_hash": _sha256(chunk),
            "full_content_hash": full_hash,
            "total_parts": total_parts,
        }
        for i, chunk in enumerate(chunks)
    ]


def reassemble(parts: list[dict]) -> str:
    """parts를 part_no 오름차순으로 정렬해 원문으로 재조립한다.
    입력 순서(행 순서)에 의존하지 않는다."""
    ordered = sorted(parts, key=lambda p: int(p["part_no"]))
    return "".join(p["content"] for p in ordered)


def verify_integrity(parts: list[dict]) -> bool:
    """parts 무결성을 검증한다. 실패 시 IntegrityError를 발생시킨다.

    검증 항목:
      1. part_no 중복 없음
      2. part_no가 0부터 연속(0..N-1)
      3. total_parts가 parts 개수 및 각 part의 선언값과 일치
      4. 각 part의 content_hash가 실제 content와 일치
      5. 재조립 결과의 SHA-256이 모든 part가 선언한 full_content_hash와 일치
    """
    if not parts:
        raise IntegrityError("parts가 비어 있음")

    part_nos = [int(p["part_no"]) for p in parts]
    if len(part_nos) != len(set(part_nos)):
        raise IntegrityError(f"part_no 중복: {part_nos}")

    expected = list(range(len(parts)))
    if sorted(part_nos) != expected:
        raise IntegrityError(f"part_no가 0부터 연속하지 않음: {sorted(part_nos)} != {expected}")

    total_parts_values = {int(p["total_parts"]) for p in parts}
    if len(total_parts_values) != 1 or total_parts_values.pop() != len(parts):
        raise IntegrityError(f"total_parts 불일치: parts 개수={len(parts)}")

    for p in parts:
        actual = _sha256(p["content"])
        if actual != p["content_hash"]:
            raise IntegrityError(f"part_no={p['part_no']} content_hash 불일치")

    full_hash_values = {p["full_content_hash"] for p in parts}
    if len(full_hash_values) != 1:
        raise IntegrityError("full_content_hash가 part마다 다름")

    reassembled = reassemble(parts)
    if _sha256(reassembled) != full_hash_values.pop():
        raise IntegrityError("재조립 결과의 SHA-256이 full_content_hash와 불일치")

    return True
