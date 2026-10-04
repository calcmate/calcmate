// src/api/auth.js — STEP 18-Q: 향후 인증 연결을 위한 최소 client 추상화.
//
// 이번 STEP에서는 로그인 UI/OAuth/비밀번호 저장을 구현하지 않는다. 이 파일은
// "토큰이 이미 어딘가(sessionStorage)에 있다면 요청 헤더에 실어 보낸다"는
// 읽기 전용 헬퍼만 제공한다 — 여기서 토큰을 직접 발급/저장하지 않는다.
// sessionStorage는 탭을 닫으면 사라지므로, "토큰을 localStorage에 무조건
// 저장"하는 방식은 의도적으로 사용하지 않는다.

const TOKEN_KEY = 'calcmate_dashboard_token'

export function getAuthToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || null
  } catch {
    return null
  }
}

export function authHeaders() {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
