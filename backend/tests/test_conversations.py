"""Conversations: history, follow-up rewriting, saved answers and citation access."""

import pytest

from app.llm.chat import ChatError
from app.llm.prompts import history_messages
from app.retrieval.condense import EXAMPLES, clean_rewrite, condense_messages
from tests.helpers import parse_sse, upload_samples


@pytest.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


@pytest.fixture
async def library(client, alice, tmp_path, session_factory, storage, embedder):
    return await upload_samples(client, alice, tmp_path, session_factory, storage, embedder)


async def new_conversation(client, user) -> str:
    resp = await client.post("/conversations", json={}, headers=user.headers)
    assert resp.status_code == 201
    return resp.json()["id"]


async def send(client, user, conversation_id: str, question: str) -> dict[str, object]:
    """Send a message; return {event name: data} (tokens joined into one string)."""
    resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"question": question},
        headers=user.headers,
    )
    assert resp.status_code == 200, resp.text
    events: dict[str, object] = {}
    for name, data in parse_sse(resp.text):
        if name == "token":
            events["token"] = str(events.get("token", "")) + data["text"]
        else:
            events[name] = data
    return events


# --- building blocks -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "How much parental leave do contractors get?",
            "How much parental leave do contractors get?",
        ),
        (
            '"How much parental leave do contractors get?"',
            "How much parental leave do contractors get?",
        ),
        ("Rewritten question: Is it paid?\nExtra chatter.", "Is it paid?"),
        ("", "what about them?"),  # empty: fall back to the original
        ("word " * 200, "what about them?"),  # rambling (probably answered instead): fall back
    ],
)
def test_clean_rewrite(raw, expected):
    assert clean_rewrite(raw, "what about them?") == expected


def test_condense_prompt_has_examples_then_the_conversation():
    history = [
        {"role": "user", "content": "How much parental leave?"},
        {"role": "assistant", "content": "16 weeks for primary caregivers [1]."},
    ]
    messages = condense_messages(history, "what about contractors?")
    assert len(messages) == 1 + 2 * len(EXAMPLES) + 1
    last = messages[-1]["content"]
    assert "User: How much parental leave?" in last
    assert "Assistant: 16 weeks for primary caregivers." in last  # citation markers dropped
    assert "Follow-up question: what about contractors?" in last


def test_old_citation_markers_are_removed_from_history():
    history = [{"role": "assistant", "content": "It is 16 weeks [1][2]. Paid [3]."}]
    assert history_messages(history) == [{"role": "assistant", "content": "It is 16 weeks. Paid."}]


# --- managing conversations ------------------------------------------------------------


async def test_create_list_rename_delete(client, alice):
    conversation_id = await new_conversation(client, alice)
    listed = (await client.get("/conversations", headers=alice.headers)).json()
    assert [c["id"] for c in listed] == [conversation_id]

    resp = await client.patch(
        f"/conversations/{conversation_id}",
        json={"title": "Leave questions"},
        headers=alice.headers,
    )
    assert resp.json()["title"] == "Leave questions"

    assert (
        await client.delete(f"/conversations/{conversation_id}", headers=alice.headers)
    ).status_code == 204
    assert (await client.get("/conversations", headers=alice.headers)).json() == []


async def test_conversations_are_private(client, alice, bob):
    conversation_id = await new_conversation(client, alice)
    url = f"/conversations/{conversation_id}"
    assert (await client.get(url, headers=bob.headers)).status_code == 404
    assert (await client.patch(url, json={"title": "x"}, headers=bob.headers)).status_code == 404
    assert (await client.delete(url, headers=bob.headers)).status_code == 404
    resp = await client.post(f"{url}/messages", json={"question": "hi"}, headers=bob.headers)
    assert resp.status_code == 404
    assert (await client.get("/conversations", headers=bob.headers)).json() == []


# --- asking in a conversation ----------------------------------------------------------


async def test_first_message_is_answered_and_saved(client, alice, library, chat):
    conversation_id = await new_conversation(client, alice)
    events = await send(
        client, alice, conversation_id, "How much parental leave do primary caregivers get?"
    )

    assert "rewritten" not in events and chat.rewrite_prompts == []  # nothing to rewrite yet
    done = events["done"]
    assert done["answer"] == "Primary caregivers get 16 weeks [1]."
    assert done["conversation_id"] == conversation_id

    detail = (await client.get(f"/conversations/{conversation_id}", headers=alice.headers)).json()
    assert detail["title"] == "How much parental leave do primary caregivers get?"
    user_msg, assistant_msg = detail["messages"]
    assert (user_msg["position"], user_msg["role"], user_msg["id"]) == (
        0,
        "user",
        done["user_message_id"],
    )
    assert (assistant_msg["position"], assistant_msg["role"]) == (1, "assistant")
    assert assistant_msg["content"] == done["answer"] and assistant_msg["model"] == "fake-chat"
    citation = assistant_msg["citations"][0]
    assert citation["available"] and citation["heading_path"][-1] == "Parental Leave"
    assert "16 weeks" in citation["text"]


async def test_follow_up_is_rewritten_for_search(client, alice, library, chat):
    conversation_id = await new_conversation(client, alice)
    await send(client, alice, conversation_id, "How much parental leave do primary caregivers get?")

    chat.rewrite = "Can contractors take paid parental leave?"
    chat.reply = "No, contractors are not eligible for paid parental leave [1]."
    events = await send(client, alice, conversation_id, "what about contractors?")

    # The rewrite saw the earlier turn...
    assert (
        "User: How much parental leave do primary caregivers get?"
        in chat.rewrite_prompts[-1][-1]["content"]
    )
    # ...was reported to the client, used for search, and stored on the user message.
    assert events["rewritten"] == {"question": "Can contractors take paid parental leave?"}
    assert events["sources"][0]["heading_path"][-1] == "Parental Leave"
    detail = (await client.get(f"/conversations/{conversation_id}", headers=alice.headers)).json()
    assert detail["messages"][2]["standalone_query"] == "Can contractors take paid parental leave?"

    # The answer prompt has the earlier turn (without old [n] markers) and both phrasings.
    prompt = chat.prompts[-1]
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert prompt[2]["content"] == "Primary caregivers get 16 weeks."
    assert "Question: what about contractors?" in prompt[3]["content"]
    assert "this means: Can contractors take paid parental leave?" in prompt[3]["content"]


async def test_only_recent_turns_are_sent_as_history(client, alice, library, chat):
    conversation_id = await new_conversation(client, alice)
    for i in range(5):
        await send(client, alice, conversation_id, f"Question number {i} about leave?")
    history = [m["content"] for m in chat.prompts[-1][1:-1]]
    assert len(history) == 6  # the last 3 of the 4 earlier turns
    assert "Question number 0 about leave?" not in history
    assert (
        "Question number 1 about leave?" in history and "Question number 3 about leave?" in history
    )


async def test_error_saves_nothing(client, alice, library, chat):
    conversation_id = await new_conversation(client, alice)
    chat.error = ChatError("Ollama is not running")
    events = await send(client, alice, conversation_id, "parental leave?")
    assert events["error"] == {"message": "Ollama is not running"}
    assert "done" not in events
    detail = (await client.get(f"/conversations/{conversation_id}", headers=alice.headers)).json()
    assert detail["messages"] == []


# --- saved citations and permissions ---------------------------------------------------


async def test_saved_citations_respect_current_permissions(client, alice, bob, library, chat):
    handbook = library["employee-handbook.md"]
    perms = f"/documents/{handbook}/permissions"
    await client.put(perms, json={"user_emails": [bob.email]}, headers=alice.headers)

    conversation_id = await new_conversation(client, bob)
    await send(client, bob, conversation_id, "How much parental leave do primary caregivers get?")
    url = f"/conversations/{conversation_id}"
    citation = (await client.get(url, headers=bob.headers)).json()["messages"][1]["citations"][0]
    assert citation["available"] and "16 weeks" in citation["text"]

    # Alice stops sharing: Bob's old conversation no longer shows the passage.
    await client.put(perms, json={}, headers=alice.headers)
    citation = (await client.get(url, headers=bob.headers)).json()["messages"][1]["citations"][0]
    assert citation == {
        "number": 1, "available": False, "chunk_id": None, "document_id": None,
        "document_title": None, "heading_path": [], "page_start": None, "page_end": None,
        "text": None,
    }  # fmt: skip


async def test_citations_survive_reprocessing(
    client, alice, library, chat, session_factory, storage, embedder
):
    from tests.helpers import run_worker

    conversation_id = await new_conversation(client, alice)
    await send(client, alice, conversation_id, "How much parental leave do primary caregivers get?")
    handbook = library["employee-handbook.md"]
    await client.post(f"/documents/{handbook}/reprocess", headers=alice.headers)
    await run_worker(session_factory, storage, embedder)  # old chunks replaced by new ones

    url = f"/conversations/{conversation_id}"
    citation = (await client.get(url, headers=alice.headers)).json()["messages"][1]["citations"][0]
    assert citation["available"] and "16 weeks" in citation["text"]  # saved copy still shown
    assert citation["chunk_id"] is None  # but the original chunk is gone


# --- real model ------------------------------------------------------------------------


@pytest.mark.integration
async def test_real_follow_up_conversation(client, alice, tmp_path, session_factory, storage):
    from app.llm.chat import OllamaChat, get_chat_model
    from app.llm.embeddings import OllamaEmbedder, get_embedder
    from app.main import app

    real = OllamaEmbedder()
    app.dependency_overrides[get_chat_model] = lambda: OllamaChat(seed=42)
    app.dependency_overrides[get_embedder] = lambda: real
    await upload_samples(client, alice, tmp_path, session_factory, storage, real)

    conversation_id = await new_conversation(client, alice)
    first = await send(
        client, alice, conversation_id, "How much parental leave do primary caregivers get?"
    )
    assert "16" in first["done"]["answer"]

    follow_up = await send(client, alice, conversation_id, "what about contractors?")
    rewritten = follow_up["rewritten"]["question"].lower()
    assert "contractor" in rewritten and "parental" in rewritten
    answer = follow_up["done"]["answer"].lower()
    assert "not eligible" in answer or "unpaid" in answer
