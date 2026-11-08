import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Citation, Conversation, ConversationDetail, Document, Message, StoredCitation } from '../api/types'
import AnswerText from '../components/AnswerText'
import ConversationSidebar from '../components/ConversationSidebar'
import SourcePanel from '../components/SourcePanel'
import SourcesList from '../components/SourcesList'
import type { PendingTurn } from '../lib/useAnswerStream'
import { useAnswerStream } from '../lib/useAnswerStream'

type ActiveSource = { key: string; citation: StoredCitation; conversationId?: string }

const toStored = (c: Citation): StoredCitation => ({ ...c, available: true })

export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [selected, setActive] = useState<ActiveSource | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api<ConversationDetail>(`/conversations/${conversationId}`),
    enabled: Boolean(conversationId),
  })
  const documents = useQuery({ queryKey: ['documents'], queryFn: () => api<Document[]>('/documents') })

  const onFinished = useCallback(
    async (id: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['conversation', id] }),
        queryClient.invalidateQueries({ queryKey: ['conversations'] }),
      ])
    },
    [queryClient],
  )
  const { turn, send, stop, dismiss } = useAnswerStream(onFinished)
  const streaming = turn !== null && turn.phase !== 'error'
  const visibleTurn = turn && turn.conversationId === conversationId ? turn : null

  // An open source belongs to one conversation; switching conversation hides it.
  const active = selected?.conversationId === conversationId ? selected : null

  // Keep the newest content in view.
  const messages = conversationId ? (detail.data?.messages ?? []) : []
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, visibleTurn?.text, visibleTurn?.phase])

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    const question = draft.trim()
    if (!question || streaming) return
    setDraft('')
    let id = conversationId
    if (!id) {
      const created = await api<Conversation>('/conversations', { method: 'POST', json: {} })
      id = created.id
      queryClient.setQueryData(['conversation', id], { ...created, messages: [] })
      void queryClient.invalidateQueries({ queryKey: ['conversations'] }) // show it in the sidebar now
      navigate(`/chat/${id}`)
    }
    void send(id, question, messages.length > 0)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  const select = (key: string) => (citation: StoredCitation) =>
    setActive((current) =>
      current?.key === `${key}:${citation.number}` && current.conversationId === conversationId
        ? null
        : { key: `${key}:${citation.number}`, citation, conversationId },
    )

  const readyDocs = documents.data?.filter((d) => d.status === 'ready').length ?? 0

  return (
    <div className={`chat-layout ${active ? 'with-panel' : ''}`}>
      <ConversationSidebar activeId={conversationId} />

      <section className="chat-main">
        <div className="messages">
          {!conversationId && !visibleTurn && (
            <div className="empty-chat">
              <h1>Ask about your documents</h1>
              {documents.isPending ? null : readyDocs > 0 ? (
                <p className="muted">
                  Answers come only from the {readyDocs} document{readyDocs === 1 ? '' : 's'} you can access, with
                  numbered citations you can click to check the source.
                </p>
              ) : (
                <p className="muted">
                  You don't have any searchable documents yet. <Link to="/documents">Upload some</Link> to get started.
                </p>
              )}
            </div>
          )}
          {conversationId && detail.isPending && <p className="muted">Loading conversation…</p>}
          {detail.error && <p className="error-text">{detail.error.message}</p>}

          {messages.map((m) => (
            <MessageView key={m.id} message={m} activeKey={active?.key ?? null} onCite={select(m.id)} />
          ))}
          {visibleTurn && (
            <PendingView
              turn={visibleTurn}
              activeKey={active?.key ?? null}
              onCite={select('pending')}
              onDismiss={dismiss}
            />
          )}
          <div ref={bottom} />
        </div>

        <form className="composer" onSubmit={(e) => void submit(e)}>
          <textarea
            rows={2}
            placeholder="Ask a question… (Enter to send, Shift+Enter for a new line)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Your question"
          />
          {streaming ? (
            <button type="button" className="btn" onClick={() => setDraft(stop())}>
              Stop
            </button>
          ) : (
            <button className="btn btn-primary" disabled={!draft.trim()}>
              Send
            </button>
          )}
        </form>
      </section>

      {active && <SourcePanel citation={active.citation} onClose={() => setActive(null)} />}
    </div>
  )
}

function MessageView({
  message,
  activeKey,
  onCite,
}: {
  message: Message
  activeKey: string | null
  onCite: (c: StoredCitation) => void
}) {
  if (message.role === 'user') {
    const rewritten =
      message.standalone_query && message.standalone_query.toLowerCase() !== message.content.toLowerCase()
        ? message.standalone_query
        : null
    return <UserBubble text={message.content} rewritten={rewritten} />
  }
  return (
    <div className="assistant-message">
      <AnswerText text={message.content} citations={message.citations} onCite={onCite} />
      <SourcesList citations={message.citations} activeKey={activeKey} onSelect={onCite} keyPrefix={message.id} />
    </div>
  )
}

function UserBubble({ text, rewritten }: { text: string; rewritten?: string | null }) {
  return (
    <div className="user-message">
      <div className="user-bubble">{text}</div>
      {rewritten && <div className="rewritten muted small">Searched for: “{rewritten}”</div>}
    </div>
  )
}

const PHASE_LABEL: Record<PendingTurn['phase'], string> = {
  rewriting: 'Understanding your follow-up question…',
  searching: 'Searching your documents…',
  reading: 'Reading the passages…',
  writing: '',
  done: '',
  error: '',
}

function PendingView({
  turn,
  activeKey,
  onCite,
  onDismiss,
}: {
  turn: PendingTurn
  activeKey: string | null
  onCite: (c: StoredCitation) => void
  onDismiss: () => void
}) {
  // While streaming, chips link to everything retrieved; once done, to what was cited.
  const citations = (turn.done?.citations ?? turn.sources ?? []).map(toStored)
  const status =
    turn.phase === 'reading' && turn.sources
      ? `Reading ${turn.sources.length} passage${turn.sources.length === 1 ? '' : 's'}…`
      : PHASE_LABEL[turn.phase]

  return (
    <>
      <UserBubble text={turn.question} rewritten={turn.rewritten} />
      <div className="assistant-message">
        {status && (
          <div className="status-line muted" role="status">
            <span className="spinner" aria-hidden /> {status}
          </div>
        )}
        {(turn.done?.answer ?? turn.text) && (
          <AnswerText text={turn.done?.answer ?? turn.text} citations={citations} onCite={onCite} />
        )}
        {turn.phase === 'writing' && <span className="cursor" aria-hidden />}
        {turn.done && (
          <SourcesList citations={citations} activeKey={activeKey} onSelect={onCite} keyPrefix="pending" />
        )}
        {turn.error && (
          <div className="error-box">
            <strong>Couldn't answer:</strong> {turn.error}
            <button className="btn btn-small" onClick={onDismiss}>
              Dismiss
            </button>
          </div>
        )}
      </div>
    </>
  )
}
