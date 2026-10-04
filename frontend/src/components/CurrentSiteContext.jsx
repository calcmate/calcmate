import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getSites } from '../api/client.js'

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-CURRENT-SITE-02: dashboard.py
// st.session_state["current_site_id"]의 React 이관.
//   - 저장하지 않는다(localStorage/sessionStorage/서버 저장 없음) — 앱이 떠 있는 동안의
//     메모리 상태일 뿐이며, 새로고침/새 브라우저 세션에서는 다시 첫 번째 Site가 기본값이다.
//   - 화면 이동(라우트 변경)으로는 사라지지 않도록 App 수준 Provider에 둔다
//     (Streamlit도 같은 세션 안에서는 탭을 옮겨도 선택이 유지됐다).
//   - 기본값 = GET /api/sites 순서 그대로의 첫 번째 Site(상태 무관, 정렬하지 않음).
//   - 목록이 바뀌어 선택한 Site가 사라지면 현재 목록의 첫 번째 Site로 교정한다.

const CurrentSiteContext = createContext(null)

export function CurrentSiteProvider({ children }) {
  const [currentSiteId, setCurrentSiteId] = useState(null)
  return (
    <CurrentSiteContext.Provider value={{ currentSiteId, setCurrentSiteId }}>
      {children}
    </CurrentSiteContext.Provider>
  )
}

// 선택 id가 목록에 없으면(최초 진입, 삭제 등) 첫 번째 Site, 목록이 비면 null.
export function resolveCurrentSiteId(sites, currentSiteId) {
  if (!Array.isArray(sites) || sites.length === 0) return null
  return sites.some((s) => s.site_id === currentSiteId) ? currentSiteId : sites[0].site_id
}

export function useCurrentSiteSelection() {
  const ctx = useContext(CurrentSiteContext)
  const [localId, setLocalId] = useState(null)   // Provider 밖(단독 렌더)에서도 동작
  const currentSiteId = ctx ? ctx.currentSiteId : localId
  const setCurrentSiteId = ctx ? ctx.setCurrentSiteId : setLocalId

  const [sites, setSites] = useState(null)       // null = 로딩 중
  const [error, setError] = useState(null)

  const reload = useCallback(() => {
    getSites().then((res) => {
      if (res?.success) {
        setSites(Array.isArray(res.data?.sites) ? res.data.sites : (Array.isArray(res.data) ? res.data : []))
        setError(null)
      } else {
        setSites([])
        setError(res?.error?.message || 'Site 목록을 불러오지 못했습니다.')
      }
    })
  }, [])

  useEffect(() => { reload() }, [reload])

  useEffect(() => {
    if (sites === null) return
    const resolved = resolveCurrentSiteId(sites, currentSiteId)
    if (resolved !== currentSiteId) setCurrentSiteId(resolved)
  }, [sites, currentSiteId, setCurrentSiteId])

  const effectiveId = sites === null ? null : resolveCurrentSiteId(sites, currentSiteId)
  const currentSite = (sites || []).find((s) => s.site_id === effectiveId) || null
  return { sites, error, currentSiteId: effectiveId, currentSite, setCurrentSiteId, reload }
}
