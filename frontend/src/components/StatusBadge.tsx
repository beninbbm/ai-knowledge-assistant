import type { DocumentStatus } from '../api/types'

const LABELS: Record<DocumentStatus, string> = {
  pending: 'Queued',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
}

export default function StatusBadge({ status, error }: { status: DocumentStatus; error?: string | null }) {
  return (
    <span className={`badge badge-${status}`} title={error ?? undefined}>
      {(status === 'pending' || status === 'processing') && <span className="spinner" aria-hidden />}
      {LABELS[status]}
    </span>
  )
}
