import { describe, expect, it } from 'vitest'
import { parseSseBuffer } from './sse'

describe('parseSseBuffer', () => {
  it('parses complete events and keeps the unfinished remainder', () => {
    const buffer = 'event: token\ndata: {"text":"Hi"}\n\nevent: token\ndata: {"te'
    const { events, rest } = parseSseBuffer(buffer)
    expect(events).toEqual([{ event: 'token', data: { text: 'Hi' } }])
    expect(rest).toBe('event: token\ndata: {"te')
  })

  it('handles CRLF line endings, comments and default event names', () => {
    const { events } = parseSseBuffer(': ping\r\n\r\ndata: 1\r\n\r\n')
    expect(events).toEqual([{ event: 'message', data: 1 }])
  })
})
