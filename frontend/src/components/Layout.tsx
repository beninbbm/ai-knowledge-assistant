import { NavLink, Outlet } from 'react-router'
import { useAuth } from '../authContext'

export default function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          Knowledge Assistant
        </div>
        <nav className="nav">
          <NavLink to="/chat">Chat</NavLink>
          <NavLink to="/documents">Documents</NavLink>
          {user?.is_superuser && <NavLink to="/groups">Groups</NavLink>}
        </nav>
        <div className="topbar-user">
          <span className="muted" title={user?.email}>
            {user?.email}
          </span>
          <button className="btn btn-ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
