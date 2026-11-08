import { useQuery } from '@tanstack/react-query'
import { api, rawRequest } from '../api/client'
import type { ChunkContext, Document, StoredCitation } from '../api/types'
import { describeLocation } from '../lib/citations'

/** Shows a cited passage with the text around it, so you can check the answer. */
export default function SourcePanel({ citation, onClose }: { citation: StoredCitation; onClose: () => void }) {
  const context = useQuery({
    queryKey: ['chunk', citation.chunk_id],
    queryFn: () => api<ChunkContext>(`/chunks/${citation.chunk_id}?context=1`),
    enabled: citation.available && citation.chunk_id !== null,
    retry: false,
  })
  const document = useQuery({
    queryKey: ['document', citation.document_id],
    queryFn: () => api<Document>(`/documents/${citation.document_id}`),
    enabled: citation.available && citation.document_id !== null,
    retry: false,
  })

  async function openPdf() {
    // The file needs our login token, so fetch it ourselves and open the downloaded copy.
    // Open the tab first (synchronously, so pop-up blockers allow it), then fill it.
    const tab = window.open('', '_blank')
    const resp = await rawRequest(`/documents/${citation.document_id}/file`)
    const url = URL.createObjectURL(await resp.blob())
    const target = citation.page_start ? `${url}#page=${citation.page_start}` : url
    if (tab) tab.location.href = target
    else window.location.href = target
  }

  const isPdf = document.data?.mime_type === 'application/pdf'

  return (
    <aside className="source-panel" aria-label="Source passage">
      <div className="source-panel-header">
        <div>
          <div className="eyebrow">Source {citation.number}</div>
          <h2>{citation.available ? citation.document_title : 'Unavailable'}</h2>
          {citation.available && (
            <div className="muted">{describeLocation(citation.heading_path, citation.page_start, citation.page_end)}</div>
          )}
        </div>
        <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close source">
          ✕
        </button>
      </div>

      {!citation.available ? (
        <p className="muted">
          You no longer have access to this document (it may have been deleted or un-shared), so the passage can't be
          shown.
        </p>
      ) : (
        <div className="source-panel-body">
          {context.data?.before.map((c) => (
            <p key={c.id} className="passage passage-context">
              {c.text}
            </p>
          ))}
          <p className="passage passage-cited">{context.data?.chunk.text ?? citation.text}</p>
          {context.data?.after.map((c) => (
            <p key={c.id} className="passage passage-context">
              {c.text}
            </p>
          ))}
          {citation.chunk_id === null && (
            <p className="muted small">
              The document has been reprocessed since this answer, so this is the passage as it was when cited.
            </p>
          )}
          {isPdf && (
            <button className="btn" onClick={() => void openPdf()}>
              Open PDF{citation.page_start ? ` at page ${citation.page_start}` : ''} ↗
            </button>
          )}
        </div>
      )}
    </aside>
  )
}
