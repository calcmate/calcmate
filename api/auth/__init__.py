"""api/auth — Dashboard 인증/권한 최소 구조 (STEP 18-Q).

실제 로그인/회원가입 시스템이 아니다. 향후 실제 인증 방식(세션, JWT, SSO 등)으로
교체 가능하도록 CurrentUser / 의존성(get_current_user, require_authenticated,
require_admin) 형태의 얇은 추상화만 제공한다. 이번 STEP에서는 어떤 기존 GET
endpoint에도 인증을 강제하지 않으며(§7), 새 write endpoint도 만들지 않는다.
"""
