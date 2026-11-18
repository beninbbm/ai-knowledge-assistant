import { NavLink, useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Conversation } from '../api/types'
import { timeAgo } from '../lib/format'

export default function ConversationSidebar({ activeId }: { activeId?: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: () => api<Conversation[]>('/conversations') })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      if (id === activeId) navigate('/chat')
      return queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })

  return (
    <aside className="sidebar">
      <button className="btn btn-primary btn-block" onClick={() => navigate('/chat')}>
        + New chat
      </button>
      <div className="sidebar-label">Recent</div>
      {conversations.data?.length === 0 && <p className="muted small">No conversations yet.</p>}
      <ul className="conversation-list">
        {conversations.data?.map((c) => (
          <li key={c.id}>
            <NavLink to={`/chat/${c.id}`} className="conversation-link">
              <span className="truncate">{c.title ?? 'New conversation'}</span>
              <span className="muted small">{timeAgo(c.updated_at)}</span>
            </NavLink>
            <button
              className="conversation-delete"
              aria-label={`Delete “${c.title ?? 'conversation'}”`}
              onClick={() => {
                if (confirm('Delete this conversation?')) remove.mutate(c.id)
              }}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
