import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Document, DocumentShares, Group } from '../api/types'
import Modal from './Modal'

export default function ShareDialog({ document, onClose }: { document: Document; onClose: () => void }) {
  const url = `/documents/${document.id}/permissions`
  const shares = useQuery({ queryKey: ['shares', document.id], queryFn: () => api<DocumentShares>(url) })
  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api<Group[]>('/groups') })

  if (shares.isPending || groups.isPending) {
    return (
      <Modal title={`Share “${document.title}”`} onClose={onClose}>
        <p className="muted">Loading…</p>
      </Modal>
    )
  }
  return (
    <ShareForm
      document={document}
      initial={shares.data ?? { user_emails: [], group_ids: [] }}
      groups={groups.data ?? []}
      onClose={onClose}
    />
  )
}

function ShareForm({
  document,
  initial,
  groups,
  onClose,
}: {
  document: Document
  initial: DocumentShares
  groups: Group[]
  onClose: () => void
}) {
  const [emails, setEmails] = useState(initial.user_emails.join('\n'))
  const [groupIds, setGroupIds] = useState<string[]>(initial.group_ids)
  const save = useMutation({
    mutationFn: (body: DocumentShares) =>
      api<DocumentShares>(`/documents/${document.id}/permissions`, { method: 'PUT', json: body }),
    onSuccess: onClose,
  })

  function submit() {
    const user_emails = emails
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter(Boolean)
    save.mutate({ user_emails, group_ids: groupIds })
  }

  return (
    <Modal title={`Share “${document.title}”`} onClose={onClose}>
      <p className="muted">
        People you share with can find this document in search and chat answers. Only you can change sharing or
        delete it.
      </p>
      <label className="field">
        <span>People (one email per line)</span>
        <textarea rows={4} value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="name@example.com" />
      </label>
      <fieldset className="field">
        <legend>Groups</legend>
        {groups.length === 0 && <p className="muted">No groups yet. Admins can create them.</p>}
        {groups.map((g) => (
          <label key={g.id} className="checkbox">
            <input
              type="checkbox"
              checked={groupIds.includes(g.id)}
              onChange={(e) =>
                setGroupIds((ids) => (e.target.checked ? [...ids, g.id] : ids.filter((id) => id !== g.id)))
              }
            />
            {g.name}
          </label>
        ))}
      </fieldset>
      {save.error && <p className="error-text">{save.error.message}</p>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={submit} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save sharing'}
        </button>
      </div>
    </Modal>
  )
}
