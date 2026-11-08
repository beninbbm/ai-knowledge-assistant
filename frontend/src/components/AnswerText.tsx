import ReactMarkdown from 'react-markdown'
import type { StoredCitation } from '../api/types'
import { citationNumber, describeLocation, linkCitations } from '../lib/citations'

/** Renders an answer's Markdown, turning [n] markers into clickable citation chips. */
export default function AnswerText({
  text,
  citations,
  onCite,
}: {
  text: string
  citations: StoredCitation[]
  onCite: (citation: StoredCitation) => void
}) {
  return (
    <div className="answer-text">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => {
            const n = citationNumber(href)
            if (n === null) {
              return (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              )
            }
            const citation = citations.find((c) => c.number === n)
            if (!citation) return <span className="cite-chip cite-chip-missing">{n}</span>
            const label = citation.available
              ? `${citation.document_title} — ${describeLocation(citation.heading_path, citation.page_start, citation.page_end)}`
              : 'Source no longer available'
            return (
              <button
                type="button"
                className={`cite-chip ${citation.available ? '' : 'cite-chip-missing'}`}
                title={label}
                aria-label={`Source ${n}: ${label}`}
                onClick={() => onCite(citation)}
              >
                {n}
              </button>
            )
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  )
}
