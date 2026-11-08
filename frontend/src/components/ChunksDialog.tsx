import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Chunk, Document } from '../api/types'
import { describeLocation } from '../lib/citations'
import Modal from './Modal'

/** How the document was split for search: a learning/debugging view. */
export default function ChunksDialog({ document, onClose }: { document: Document; onClose: () => void }) {
  const chunks = useQuery({
    queryKey: ['chunks', document.id],
    queryFn: () => api<Chunk[]>(`/documents/${document.id}/chunks`),
  })
  return (
    <Modal title={`Chunks of “${document.title}”`} onClose={onClose} wide>
      {chunks.isPending && <p className="muted">Loading…</p>}
      {chunks.error && <p className="error-text">{chunks.error.message}</p>}
      {chunks.data && (
        <>
          <p className="muted">
            {chunks.data.length} chunks. Each one is embedded and searched separately; answers cite them individually.
          </p>
          <ol className="chunk-list">
            {chunks.data.map((c) => (
              <li key={c.id} className="chunk">
                <div className="chunk-meta">
                  <span>#{c.chunk_index}</span>
                  <span>{describeLocation(c.heading_path, c.page_start, c.page_end) || 'No heading'}</span>
                  <span>~{c.token_count} tokens</span>
                </div>
                <p className="passage">{c.text}</p>
              </li>
            ))}
          </ol>
        </>
      )}
    </Modal>
  )
}
