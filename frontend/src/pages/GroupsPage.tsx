import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Group, Member } from '../api/types'

/** Admin only: groups let a document be shared with a whole team at once. */
export default function GroupsPage() {
  const queryClient = useQueryClient()
  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api<Group[]>('/groups') })
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: (groupName: string) => api<Group>('/groups', { method: 'POST', json: { name: groupName } }),
    onSuccess: (group) => {
      setName('')
      setSelected(group.id)
      return queryClient.invalidateQueries({ queryKey: ['groups'] })
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (name.trim()) create.mutate(name.trim())
  }

  const current = groups.data?.find((g) => g.id === selected) ?? null

  return (
    <div className="page">
      <div className="page-header">
        <h1>Groups</h1>
        <p className="muted">Share a document with a group and every member can use it in search and chat.</p>
      </div>
      <div className="groups-layout">
        <section className="card groups-list">
          <form className="inline-form" onSubmit={submit}>
            <input placeholder="New group name" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn btn-primary" disabled={create.isPending}>
              Create
            </button>
          </form>
          {create.error && <p className="error-text">{create.error.message}</p>}
          {groups.data?.length === 0 && <p className="muted">No groups yet.</p>}
          <ul className="select-list">
            {groups.data?.map((g) => (
              <li key={g.id}>
                <button aria-current={g.id === selected} onClick={() => setSelected(g.id)}>
                  {g.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="card groups-members">
          {current ? <Members group={current} /> : <p className="muted">Select a group to manage its members.</p>}
        </section>
      </div>
    </div>
  )
}

function Members({ group }: { group: Group }) {
  const queryClient = useQueryClient()
  const key = ['members', group.id]
  const members = useQuery({ queryKey: key, queryFn: () => api<Member[]>(`/groups/${group.id}/members`) })
  const [email, setEmail] = useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const add = useMutation({
    mutationFn: (address: string) => api(`/groups/${group.id}/members`, { method: 'POST', json: { email: address } }),
    onSuccess: () => {
      setEmail('')
      return refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (userId: string) => api(`/groups/${group.id}/members/${userId}`, { method: 'DELETE' }),
    onSuccess: refresh,
  })

  return (
    <>
      <h2>{group.name}</h2>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (email.trim()) add.mutate(email.trim())
        }}
      >
        <input type="email" placeholder="member@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button className="btn" disabled={add.isPending}>
          Add member
        </button>
      </form>
      {add.error && <p className="error-text">{add.error.message}</p>}
      {members.data?.length === 0 && <p className="muted">No members yet.</p>}
      <ul className="member-list">
        {members.data?.map((m) => (
          <li key={m.id}>
            <span>{m.email}</span>
            <button className="btn btn-small btn-ghost" onClick={() => remove.mutate(m.id)}>
              Remove
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}
