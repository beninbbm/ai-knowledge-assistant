// Who is signed in. The login token lives in localStorage so a page reload keeps you
// signed in; it is sent with every API request (see api/client.ts).

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, getToken, setToken, setUnauthorizedHandler } from './api/client'
import type { User } from './api/types'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => getToken() !== null)
  const queryClient = useQueryClient()

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    queryClient.clear() // forget the previous user's documents and chats
  }, [queryClient])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!getToken()) return
    api<User>('/users/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    // fastapi-users expects an HTML-form style body with "username" and "password".
    const form = new URLSearchParams({ username: email, password })
    const { access_token } = await api<{ access_token: string }>('/auth/jwt/login', {
      method: 'POST',
      body: form,
    })
    setToken(access_token)
    setUser(await api<User>('/users/me'))
  }, [])

  const register = useCallback(
    async (email: string, password: string) => {
      await api('/auth/register', { method: 'POST', json: { email, password } })
      await login(email, password)
    },
    [login],
  )

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
