import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Document } from '../api/types'
import ChunksDialog from '../components/ChunksDialog'
import ShareDialog from '../components/ShareDialog'
import StatusBadge from '../components/StatusBadge'
import UploadDropzone from '../components/UploadDropzone'
import { fileKind, formatBytes, timeAgo } from '../lib/format'

export default function LibraryPage() {
  const queryClient = useQueryClient()
  const [sharing, setSharing] = useState<Document | null>(null)
  const [inspecting, setInspecting] = useState<Document | null>(null)

  const documents = useQuery({
    queryKey: ['documents'],
    queryFn: () => api<Document[]>('/documents'),
    // While anything is still being processed, check again every 2 seconds.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === 'pending' || d.status === 'processing') ? 2000 : false,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['documents'] })

  const remove = useMutation({
    mutationFn: (doc: Document) => api(`/documents/${doc.id}`, { method: 'DELETE' }),
    onSuccess: refresh,
  })
  const reprocess = useMutation({
    mutationFn: (doc: Document) => api(`/documents/${doc.id}/reprocess`, { method: 'POST' }),
    onSuccess: refresh,
  })

  const mine = documents.data?.filter((d) => d.is_owner) ?? []
  const shared = documents.data?.filter((d) => !d.is_owner) ?? []

  return (
    <div className="page">
      <div className="page-header">
        <h1>Documents</h1>
        <p className="muted">Upload files to make them searchable. The assistant only uses documents you can see here.</p>
      </div>

      <UploadDropzone onUploaded={refresh} />

      {documents.isPending && <p className="muted">Loading…</p>}
      {documents.error && <p className="error-text">{documents.error.message}</p>}
      {(remove.error || reprocess.error) && (
        <p className="error-text">{(remove.error ?? reprocess.error)?.message}</p>
      )}

      {documents.data && (
        <>
          <DocumentTable
            title="Your documents"
            empty="You haven't uploaded anything yet."
            documents={mine}
            onShare={setSharing}
            onInspect={setInspecting}
            onReprocess={(d) => reprocess.mutate(d)}
            onDelete={(d) => {
              if (confirm(`Delete “${d.title}”? This can't be undone.`)) remove.mutate(d)
            }}
          />
          <DocumentTable
            title="Shared with you"
            empty="Nobody has shared a document with you yet."
            documents={shared}
            onInspect={setInspecting}
          />
        </>
      )}

      {sharing && (
        <ShareDialog
          document={sharing}
          onClose={() => {
            setSharing(null)
          }}
        />
      )}
      {inspecting && <ChunksDialog document={inspecting} onClose={() => setInspecting(null)} />}
    </div>
  )
}

function DocumentTable({
  title,
  empty,
  documents,
  onShare,
  onInspect,
  onReprocess,
  onDelete,
}: {
  title: string
  empty: string
  documents: Document[]
  onShare?: (d: Document) => void
  onInspect: (d: Document) => void
  onReprocess?: (d: Document) => void
  onDelete?: (d: Document) => void
}) {
  return (
    <section className="section">
      <h2>
        {title} <span className="muted">({documents.length})</span>
      </h2>
      {documents.length === 0 ? (
        <p className="muted empty">{empty}</p>
      ) : (
        <ul className="doc-list">
          {documents.map((d) => (
            <li key={d.id} className="doc-row card">
              <div className="doc-main">
                <div className="doc-title truncate" title={d.title}>
                  {d.title}
                </div>
                <div className="doc-meta muted">
                  <span className="kind">{fileKind(d.mime_type)}</span>
                  <span className="truncate">{d.filename}</span>
                  <span>{formatBytes(d.size_bytes)}</span>
                  {d.page_count && <span>{d.page_count} pages</span>}
                  <span>{timeAgo(d.created_at)}</span>
                </div>
                {d.status === 'failed' && d.error && <div className="error-text small">{d.error}</div>}
              </div>
              <StatusBadge status={d.status} error={d.error} />
              <div className="doc-actions">
                {d.status === 'ready' && (
                  <button className="btn btn-small" onClick={() => onInspect(d)}>
                    View chunks
                  </button>
                )}
                {onShare && (
                  <button className="btn btn-small" onClick={() => onShare(d)}>
                    Share
                  </button>
                )}
                {onReprocess && (d.status === 'ready' || d.status === 'failed') && (
                  <button className="btn btn-small" onClick={() => onReprocess(d)} title="Extract, chunk and embed again">
                    Reprocess
                  </button>
                )}
                {onDelete && (
                  <button className="btn btn-small btn-danger" onClick={() => onDelete(d)}>
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
