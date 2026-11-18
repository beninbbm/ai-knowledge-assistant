import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { api } from '../api/client'
import type { Document } from '../api/types'

type Upload = { name: string; state: 'uploading' | 'done' | 'error'; message?: string }

const ACCEPT = '.pdf,.docx,.md,.markdown'

export default function UploadDropzone({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploads, setUploads] = useState<Upload[]>([])

  async function uploadFiles(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      setUploads((u) => [{ name: file.name, state: 'uploading' }, ...u])
      const update = (patch: Partial<Upload>) =>
        setUploads((u) => u.map((x) => (x.name === file.name && x.state === 'uploading' ? { ...x, ...patch } : x)))
      try {
        const form = new FormData()
        form.append('file', file)
        await api<Document>('/documents', { method: 'POST', body: form })
        update({ state: 'done' })
        onUploaded()
        // The document list shows progress from here on; drop the upload line shortly.
        setTimeout(() => setUploads((u) => u.filter((x) => !(x.name === file.name && x.state === 'done'))), 3000)
      } catch (err) {
        update({ state: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files)
  }

  return (
    <div>
      <div
        className={`dropzone ${dragging ? 'dropzone-active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
      >
        <strong>Drop files here or click to upload</strong>
        <span className="muted">PDF, Word (.docx) or Markdown (.md), up to 25 MB each</span>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) void uploadFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
      {uploads.length > 0 && (
        <ul className="upload-list">
          {uploads.slice(0, 5).map((u, i) => (
            <li key={`${u.name}-${i}`} className={`upload-${u.state}`}>
              <span className="truncate">{u.name}</span>
              <span>
                {u.state === 'uploading' && 'Uploading…'}
                {u.state === 'done' && 'Uploaded'}
                {u.state === 'error' && u.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
