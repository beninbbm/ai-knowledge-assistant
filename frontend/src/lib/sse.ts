// Reading Server-Sent Events from a fetch() response.
//
// The browser's built-in EventSource can only make GET requests and can't send an
// Authorization header, so we read the stream ourselves. The format is plain text:
//
//   event: token
//   data: {"text": "Hello"}
//   <blank line>
//
// Network chunks don't line up with events, so we buffer until we see a blank line.

export type SseEvent = { event: string; data: unknown }

/** Parse complete events out of `buffer`; returns them plus the unfinished remainder. */
export function parseSseBuffer(buffer: string): { events: SseEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const blocks = normalized.split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: SseEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      // Lines starting with ":" are comments (keep-alive pings); ignore them.
    }
    if (data.length) events.push({ event, data: JSON.parse(data.join('\n')) })
  }
  return { events, rest }
}

/** Yield events from a streaming response as they arrive. */
export async function* readSse(resp: Response): AsyncGenerator<SseEvent> {
  if (!resp.body) return
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    const { events, rest } = parseSseBuffer(buffer)
    buffer = rest
    yield* events
  }
  const { events } = parseSseBuffer(buffer + '\n\n')
  yield* events
}
