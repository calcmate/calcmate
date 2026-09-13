"""
adapters/db/factory.py — config 기반 DB Adapter 선택
"""
from .base import AbstractDBAdapter


def get_db_adapter(cfg: dict) -> AbstractDBAdapter:
    adapter_type = cfg.get("DB_ADAPTER", "sheets").lower()
    if adapter_type == "sheets":
        from .sheets_adapter import SheetsAdapter
        return SheetsAdapter(cfg)
    elif adapter_type == "sqlite":
        from .sqlite_adapter import SQLiteAdapter
        return SQLiteAdapter(cfg)
    elif adapter_type == "postgres":
        from .postgres_adapter import PostgresAdapter
        return PostgresAdapter(cfg)
    elif adapter_type == "dual":
        from .dual_adapter import DualAdapter
        return DualAdapter(cfg)
    else:
        raise ValueError(f"알 수 없는 DB_ADAPTER: {adapter_type}")


def get_template_storage_adapter(cfg: dict) -> AbstractDBAdapter:
    """app_templates 전용 adapter(IRP-22/23).

    전역 DB_ADAPTER가 Sheets를 실제로 사용하는 설정(sheets/dual)일 때만
    SQLiteFirstAdapter(SQLite=운영 원본, Sheets=백업, 50K 초과 자동 분할)로
    바꿔치기한다. 그 외(sqlite/postgres 단독 등, Sheets 백업이 애초에 의미
    없는 설정)에서는 get_db_adapter(cfg)와 완전히 동일하게 동작해 기존
    테스트/개발 환경(DB_ADAPTER=sqlite)을 그대로 통과시킨다.

    "calculators"/"sites"/"articles" 등 다른 Repository는 절대 이 함수를
    쓰지 않는다 — get_db_adapter(cfg)를 그대로 계속 사용한다."""
    adapter_type = cfg.get("DB_ADAPTER", "sheets").lower()
    if adapter_type in ("sheets", "dual"):
        from .sqlite_first_adapter import SQLiteFirstAdapter
        return SQLiteFirstAdapter(cfg)
    return get_db_adapter(cfg)


def get_calculator_storage_adapter(cfg: dict) -> AbstractDBAdapter:
    """calculators 전용 adapter(STEP90~93: SQLite MAIN / Sheets BACKUP 전환).

    STEP90에서 확인된 대로 get_db_adapter(cfg)가 반환하는 DualAdapter는
    Sheets가 primary다 — calculators는 그 정책을 원치 않으므로, 이미
    app_templates에서 검증된 SQLiteFirstAdapter(SQLite=운영 원본, Sheets=백업)를
    그대로 재사용하는 별도 진입점을 둔다(STEP92에서 재사용 가능성 PASS 판정).

    get_template_storage_adapter()와 완전히 동일한 조건부 구조를 따른다 —
    전역 DB_ADAPTER가 Sheets를 실제로 쓰는 설정(sheets/dual)일 때만
    SQLiteFirstAdapter로 바꿔치고, 그 외(sqlite/postgres 단독)에서는
    get_db_adapter(cfg)와 동일하게 동작해 기존 테스트/개발 환경을 그대로
    통과시킨다.

    "sites"/"articles"는 절대 이 함수를 쓰지 않는다 — 계속 get_db_adapter(cfg)
    (DualAdapter, Sheets-primary)를 그대로 사용한다. DualAdapter 자체는
    이 함수 신설로 단 한 줄도 바뀌지 않는다."""
    adapter_type = cfg.get("DB_ADAPTER", "sheets").lower()
    if adapter_type in ("sheets", "dual"):
        from .sqlite_first_adapter import SQLiteFirstAdapter
        return SQLiteFirstAdapter(cfg)
    return get_db_adapter(cfg)


def get_blog_article_storage_adapter(cfg: dict) -> AbstractDBAdapter:
    """blog_articles 전용 adapter(STEP96~97: SQLite MAIN / Sheets BACKUP 전환).

    STEP96에서 확인된 대로 blog_articles(Golden10 SSOT)는 SQLite/Sheets/WP
    10/10 완전 일치하고, WordPress로 향하는 write 경로가 애초에 존재하지
    않아(blog_articles_sync.py는 READ-ONLY 비교만 수행) SQLite MAIN 전환이
    WP 운영에 영향을 줄 수 없다고 판단됐다(STEP96 GO 판정).

    get_calculator_storage_adapter()/get_template_storage_adapter()와 완전히
    동일한 조건부 구조를 따른다 — 전역 DB_ADAPTER가 Sheets를 실제로 쓰는
    설정(sheets/dual)일 때만 SQLiteFirstAdapter로 바꿔치고, 그 외(sqlite/
    postgres 단독)에서는 get_db_adapter(cfg)와 동일하게 동작해 기존 테스트/
    개발 환경을 그대로 통과시킨다.

    "sites"/"articles"(레거시)/"calculators"는 절대 이 함수를 쓰지 않는다 —
    각자 기존 경로(get_db_adapter 또는 get_calculator_storage_adapter)를
    그대로 사용한다. DualAdapter/get_calculator_storage_adapter 자체는
    이 함수 신설로 단 한 줄도 바뀌지 않는다."""
    adapter_type = cfg.get("DB_ADAPTER", "sheets").lower()
    if adapter_type in ("sheets", "dual"):
        from .sqlite_first_adapter import SQLiteFirstAdapter
        return SQLiteFirstAdapter(cfg)
    return get_db_adapter(cfg)
