# -*- coding: utf-8 -*-
"""tests/_route_utils.py — FastAPI 실제 등록 route 재귀 수집 helper (STEP 18-N).

배경: 이 프로젝트가 사용하는 FastAPI 0.141.1 / Starlette 1.3.1에서는
`app.include_router()`로 등록한 라우트가 `app.routes`에 바로 펼쳐지지 않고,
`_IncludedRouter` 래퍼 객체(`.original_router.routes`에 실제 라우트를 담고 있음)로만
노출된다. STEP 18-C/18-G/18-I-A에서 작성된 기존 "쓰기 endpoint가 없는지" 검사
테스트들은 `app.routes`를 얕게(non-recursive) 순회했기 때문에, 이 래퍼 계층을
뚫고 들어가지 못해 실제로는 어떤 개별 endpoint도 검사하지 못한 채
공허하게(vacuously) 통과해왔다(STEP 18-M에서 발견).

collect_routes(app)는 `original_router.routes`가 있는 모든 노드를 재귀적으로
내려가 실제 (path, methods) 조합을 전부 모은다. 향후 FastAPI/Starlette가 다시
구조를 바꾸더라도 이 helper 하나만 고치면 되도록, 라우트 순회 로직을 이 파일에만
둔다(각 테스트 파일에 중복 구현하지 않는다).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RouteInfo:
    path: str
    methods: frozenset
    name: str | None = None
    endpoint: object = field(default=None, compare=False, hash=False)


def collect_routes(app) -> list[RouteInfo]:
    """app에 실제 등록된 모든 route를 재귀적으로 수집한다(중복 제거).

    `original_router`(또는 동등하게 `.routes`를 가진 하위 라우터) 속성을 가진
    노드는 얼마든지 깊이 내려가며 펼친다 — include_router가 여러 단계로
    중첩되어도 안전하다.
    """
    seen: set[tuple[str, frozenset]] = set()
    out: list[RouteInfo] = []

    def _walk(routes):
        for r in routes or []:
            path = getattr(r, "path", None)
            methods = getattr(r, "methods", None)
            if path is not None and methods:
                key = (path, frozenset(methods))
                if key not in seen:
                    seen.add(key)
                    out.append(RouteInfo(
                        path=path,
                        methods=frozenset(methods),
                        name=getattr(r, "name", None),
                        endpoint=getattr(r, "endpoint", None),
                    ))
            # 중첩 라우터(_IncludedRouter 등) — original_router.routes로 재귀
            inner_router = getattr(r, "original_router", None)
            if inner_router is not None:
                _walk(getattr(inner_router, "routes", None))
            # 혹시 다른 버전에서 라우트 자체가 .routes를 갖는 Mount류일 경우도 대비
            elif hasattr(r, "routes") and getattr(r, "routes", None) is not routes:
                _walk(getattr(r, "routes", None))

    _walk(app.routes)
    return out


def write_routes(app, prefix: str = "") -> list[tuple[str, str]]:
    """(path, method) 쌍으로 된 쓰기(POST/PATCH/PUT/DELETE) route 목록.
    prefix가 주어지면 그 경로로 시작하는 route만 대상으로 한다."""
    WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
    out = []
    for r in collect_routes(app):
        if prefix and not r.path.startswith(prefix):
            continue
        for m in r.methods & WRITE_METHODS:
            out.append((r.path, m))
    return sorted(out)
