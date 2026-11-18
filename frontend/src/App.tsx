import { Navigate, Route, Routes } from 'react-router'
import { useAuth } from './authContext'
import Layout from './components/Layout'
import ChatPage from './pages/ChatPage'
import GroupsPage from './pages/GroupsPage'
import LibraryPage from './pages/LibraryPage'
import LoginPage from './pages/LoginPage'

export default function App() {
  const { user, loading } = useAuth()

  if (loading) return <div className="center-screen muted">Loading…</div>
  if (!user) return <LoginPage />

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/chat/:conversationId?" element={<ChatPage />} />
        <Route path="/documents" element={<LibraryPage />} />
        {user.is_superuser && <Route path="/groups" element={<GroupsPage />} />}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
