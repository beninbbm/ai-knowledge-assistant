import type { StoredCitation } from '../api/types'
import { describeLocation } from '../lib/citations'

/** The sources an answer cited, listed under it. */
export default function SourcesList({
  citations,
  activeKey,
  onSelect,
  keyPrefix,
}: {
  citations: StoredCitation[]
  activeKey: string | null
  onSelect: (c: StoredCitation) => void
  keyPrefix: string
}) {
  if (!citations.length) return null
  return (
    <div className="sources">
      <div className="sources-label">Sources</div>
      <ul>
        {citations.map((c) => (
          <li key={c.number}>
            <button
              type="button"
              className="source-item"
              aria-pressed={activeKey === `${keyPrefix}:${c.number}`}
              onClick={() => onSelect(c)}
            >
              <span className="cite-chip" aria-hidden>
                {c.number}
              </span>
              {c.available ? (
                <span className="source-text">
                  <span className="source-title">{c.document_title}</span>
                  <span className="muted">{describeLocation(c.heading_path, c.page_start, c.page_end)}</span>
                </span>
              ) : (
                <span className="muted">Source no longer available to you</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
