// Shapes of the JSON returned by the backend (see backend/app/schemas.py).

export type User = {
  id: string
  email: string
  is_active: boolean
  is_superuser: boolean
}

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'

export type Document = {
  id: string
  owner_id: string
  title: string
  filename: string
  mime_type: string
  size_bytes: number
  page_count: number | null
  status: DocumentStatus
  error: string | null
  created_at: string
  is_owner: boolean
}

export type DocumentShares = {
  user_emails: string[]
  group_ids: string[]
}

export type Group = { id: string; name: string; created_at: string }
export type Member = { id: string; email: string }

export type Chunk = {
  id: string
  document_id: string
  chunk_index: number
  text: string
  heading_path: string[]
  page_start: number | null
  page_end: number | null
  token_count: number
}

export type ChunkContext = {
  document: Document
  chunk: Chunk
  before: Chunk[]
  after: Chunk[]
}

/** A citation as it arrives while streaming (always available). */
export type Citation = {
  number: number
  chunk_id: string
  document_id: string
  document_title: string
  heading_path: string[]
  page_start: number | null
  page_end: number | null
  text: string
}

/** A citation saved with a message. Unavailable if access to the document was lost. */
export type StoredCitation = {
  number: number
  available: boolean
  chunk_id: string | null
  document_id: string | null
  document_title: string | null
  heading_path: string[]
  page_start: number | null
  page_end: number | null
  text: string | null
}

export type Conversation = {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

export type Message = {
  id: string
  position: number
  role: 'user' | 'assistant'
  content: string
  standalone_query: string | null
  model: string | null
  created_at: string
  citations: StoredCitation[]
}

export type ConversationDetail = Conversation & { messages: Message[] }

export type AnswerDone = {
  answer: string
  citations: Citation[]
  sources_considered: number
  model: string | null
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  standalone_question: string
}
