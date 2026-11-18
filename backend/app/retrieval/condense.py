"""Query condensation: turn a follow-up question into one that stands on its own.

Search only sees the text we give it. "What about contractors?" retrieves nothing useful,
but "What is the parental leave policy for contractors?" does. Before searching, we ask
the LLM to rewrite the latest question using the conversation so far.
"""

import re

from app.llm.chat import ChatModel, complete

CONDENSE_SYSTEM_PROMPT = """\
You rewrite follow-up questions so they can be understood without the conversation. \
The rewritten question is used to search a document library.

- Replace pronouns and vague references ("it", "they", "that", "what about X", \
"and X?") with what they refer to in the conversation.
- Keep every specific name, number and term from the follow-up question.
- If the question already stands on its own, return it unchanged.
- Reply with ONLY the rewritten question. Do not answer it."""

# Worked examples ("few-shot prompting"): small models follow a demonstrated pattern far
# more reliably than a description alone. Deliberately about a different topic.
EXAMPLES = [
    (
        "User: How many vacation days do new employees get?\n"
        "Assistant: New employees get 20 vacation days per year.",
        "what about managers?",
        "How many vacation days do managers get per year?",
    ),
    (
        "User: Who approves purchase orders?\n"
        "Assistant: Purchase orders over $1,000 are approved by Finance.",
        "and under that?",
        "Who approves purchase orders under $1,000?",
    ),
    (
        "User: Who approves purchase orders?\n"
        "Assistant: Purchase orders over $1,000 are approved by Finance.",
        "How do I reset my password?",
        "How do I reset my password?",
    ),
]

# Assistant answers can be long; the gist is enough to resolve references.
MAX_TURN_CHARS = 400
_PREFIX = re.compile(r"^(rewritten|standalone)?\s*(question)?\s*:\s*", re.IGNORECASE)


def _shorten(text: str) -> str:
    text = re.sub(r"\s*\[\d+\]", "", text).strip()  # drop citation markers
    return text if len(text) <= MAX_TURN_CHARS else text[:MAX_TURN_CHARS].rsplit(" ", 1)[0] + "…"


def _request(transcript: str, question: str) -> str:
    return f"Conversation:\n{transcript}\n\nFollow-up question: {question}\n\nRewritten question:"


def condense_messages(history: list[dict[str, str]], question: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": CONDENSE_SYSTEM_PROMPT}]
    for transcript, follow_up, rewritten in EXAMPLES:
        messages.append({"role": "user", "content": _request(transcript, follow_up)})
        messages.append({"role": "assistant", "content": rewritten})
    transcript = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {_shorten(m['content'])}"
        for m in history
    )
    messages.append({"role": "user", "content": _request(transcript, question)})
    return messages


def clean_rewrite(raw: str, question: str) -> str:
    """Tidy the model's reply; fall back to the original question if it looks wrong."""
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if not lines:
        return question
    rewritten = _PREFIX.sub("", lines[0]).strip().strip("\"'“”").strip()
    # An empty or rambling reply (e.g. the model answered instead) isn't a usable query.
    if not rewritten or len(rewritten) > max(300, 4 * len(question)):
        return question
    return rewritten


async def condense_question(chat: ChatModel, history: list[dict[str, str]], question: str) -> str:
    """The question rewritten to stand alone (unchanged if there's no history)."""
    if not history:
        return question
    raw = await complete(
        chat, condense_messages(history, question), options={"temperature": 0, "num_predict": 100}
    )
    return clean_rewrite(raw, question)
