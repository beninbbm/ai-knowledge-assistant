// Sends a question in a conversation and follows the streamed answer.
//
// Phases shown to the user while waiting:
//   rewriting  -> turning a follow-up into a standalone search question
//   searching  -> finding relevant passages
//   reading    -> the model is reading the passages (the slow part on a laptop)
//   writing    -> answer text is arriving

import { useCallback, useRef, useState } from 'react'
import { rawRequest } from '../api/client'
import type { AnswerDone, Citation } from '../api/types'
import { readSse } from './sse'

export type Phase = 'rewriting' | 'searching' | 'reading' | 'writing' | 'done' | 'error'

export type PendingTurn = {
  conversationId: string
  question: string
  phase: Phase
  rewritten?: string
  sources?: Citation[]
  text: string
  done?: AnswerDone
  error?: string
}

export function useAnswerStream(onFinished: (conversationId: string) => Promise<void>) {
  const [turn, setTurn] = useState<PendingTurn | null>(null)
  const controller = useRef<AbortController | null>(null)

  const send = useCallback(
    async (conversationId: string, question: string, hasHistory: boolean) => {
      controller.current?.abort()
      const abort = new AbortController()
      controller.current = abort
      const update = (patch: Partial<PendingTurn>) => setTurn((t) => (t ? { ...t, ...patch } : t))
      setTurn({ conversationId, question, phase: hasHistory ? 'rewriting' : 'searching', text: '' })

      try {
        const resp = await rawRequest(`/conversations/${conversationId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question }),
          signal: abort.signal,
        })
        for await (const { event, data } of readSse(resp)) {
          if (event === 'rewritten') {
            update({ phase: 'searching', rewritten: (data as { question: string }).question })
          } else if (event === 'sources') {
            const sources = data as Citation[]
            update({ phase: sources.length ? 'reading' : 'writing', sources })
          } else if (event === 'token') {
            const piece = (data as { text: string }).text
            setTurn((t) => (t ? { ...t, phase: 'writing', text: t.text + piece } : t))
          } else if (event === 'done') {
            update({ phase: 'done', done: data as AnswerDone })
            await onFinished(conversationId) // reload the saved conversation...
            setTurn(null) // ...which now contains this turn
          } else if (event === 'error') {
            update({ phase: 'error', error: (data as { message: string }).message })
          }
        }
      } catch (err) {
        if (abort.signal.aborted) return
        update({ phase: 'error', error: err instanceof Error ? err.message : String(err) })
      }
    },
    [onFinished],
  )

  /** Stop generating. Nothing is saved for an unfinished answer. */
  const stop = useCallback(() => {
    controller.current?.abort()
    const question = turn?.question ?? ''
    setTurn(null)
    return question
  }, [turn])

  const dismiss = useCallback(() => setTurn(null), [])

  return { turn, send, stop, dismiss }
}
