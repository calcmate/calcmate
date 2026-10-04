"""api — FastAPI 관리 API 계층 (STEP 18-C 최소 골격).

기존 Calculator / Blog / Scheduler / DB / Registry 엔진은 이 패키지 안에 재작성하지 않는다.
이 패키지는 router → service → 기존 엔진 순서의 얇은 어댑터 계층만 담당한다.
"""
