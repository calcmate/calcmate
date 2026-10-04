import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { getAuthToken, authHeaders } from '../api/auth.js'

const KEY = 'calcmate_dashboard_token'

describe('api/auth.js — STEP 18-Q client abstraction', () => {
  afterEach(() => {
    sessionStorage.removeItem(KEY)
  })

  it('returns null and an empty headers object when no token is stored', () => {
    expect(getAuthToken()).toBeNull()
    expect(authHeaders()).toEqual({})
  })

  it('reads a token from sessionStorage if one is already present (never writes it itself)', () => {
    sessionStorage.setItem(KEY, 'abc123')
    expect(getAuthToken()).toBe('abc123')
    expect(authHeaders()).toEqual({ Authorization: 'Bearer abc123' })
  })

  it('does not write to sessionStorage as a side effect of reading', () => {
    getAuthToken()
    authHeaders()
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })
})
