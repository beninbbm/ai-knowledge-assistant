"""Authorization: what you are allowed to see.

These are the most important tests in the project. Every later feature (search, chat,
source passages) relies on `app.permissions`, so these must never regress.
"""

import pytest


@pytest.fixture
async def alice(make_user):
    return await make_user("alice@example.com")


@pytest.fixture
async def bob(make_user):
    return await make_user("bob@example.com")


@pytest.fixture
async def carol(make_user):
    return await make_user("carol@example.com")


@pytest.fixture
async def admin(make_user):
    return await make_user("admin@example.com", admin=True)


def ids(resp) -> set[str]:
    return {d["id"] for d in resp.json()}


async def test_owner_sees_own_documents(client, alice, make_document):
    doc_id = await make_document(alice)
    resp = await client.get("/documents", headers=alice.headers)
    assert ids(resp) == {str(doc_id)}
    assert resp.json()[0]["is_owner"] is True
    assert (await client.get(f"/documents/{doc_id}", headers=alice.headers)).status_code == 200


async def test_private_document_is_invisible_to_others(client, alice, bob, make_document):
    doc_id = await make_document(alice)
    assert ids(await client.get("/documents", headers=bob.headers)) == set()
    # 404 (not 403) on every route, so Bob can't even tell the document exists.
    assert (await client.get(f"/documents/{doc_id}", headers=bob.headers)).status_code == 404
    assert (await client.delete(f"/documents/{doc_id}", headers=bob.headers)).status_code == 404
    perms_url = f"/documents/{doc_id}/permissions"
    assert (await client.get(perms_url, headers=bob.headers)).status_code == 404
    put = await client.put(perms_url, json={"user_emails": [bob.email]}, headers=bob.headers)
    assert put.status_code == 404


async def test_share_with_user_then_revoke(client, alice, bob, carol, make_document):
    doc_id = await make_document(alice)
    perms_url = f"/documents/{doc_id}/permissions"

    resp = await client.put(perms_url, json={"user_emails": [bob.email]}, headers=alice.headers)
    assert resp.status_code == 200
    assert resp.json()["user_emails"] == [bob.email]

    bob_view = await client.get("/documents", headers=bob.headers)
    assert ids(bob_view) == {str(doc_id)}
    assert bob_view.json()[0]["is_owner"] is False
    assert ids(await client.get("/documents", headers=carol.headers)) == set()

    # Reading is allowed, but only the owner may delete or re-share.
    assert (await client.delete(f"/documents/{doc_id}", headers=bob.headers)).status_code == 403
    reshare = await client.put(perms_url, json={"user_emails": [carol.email]}, headers=bob.headers)
    assert reshare.status_code == 403

    # Revoke by sending an empty list.
    await client.put(perms_url, json={"user_emails": []}, headers=alice.headers)
    assert ids(await client.get("/documents", headers=bob.headers)) == set()
    assert (await client.get(f"/documents/{doc_id}", headers=bob.headers)).status_code == 404


async def test_share_with_group_and_membership_changes(
    client, admin, alice, bob, carol, make_document
):
    group = (await client.post("/groups", json={"name": "HR"}, headers=admin.headers)).json()
    await client.post(
        f"/groups/{group['id']}/members", json={"email": bob.email}, headers=admin.headers
    )

    doc_id = await make_document(alice)
    resp = await client.put(
        f"/documents/{doc_id}/permissions", json={"group_ids": [group["id"]]}, headers=alice.headers
    )
    assert resp.status_code == 200

    assert ids(await client.get("/documents", headers=bob.headers)) == {str(doc_id)}  # member
    assert ids(await client.get("/documents", headers=carol.headers)) == set()  # not a member

    # Leaving the group removes access immediately.
    await client.delete(f"/groups/{group['id']}/members/{bob.id}", headers=admin.headers)
    assert ids(await client.get("/documents", headers=bob.headers)) == set()


async def test_each_user_sees_exactly_their_set(client, alice, bob, carol, make_document):
    a_private = await make_document(alice, "a-private")
    a_shared = await make_document(alice, "a-shared")
    b_private = await make_document(bob, "b-private")
    await client.put(
        f"/documents/{a_shared}/permissions",
        json={"user_emails": [bob.email]},
        headers=alice.headers,
    )
    assert ids(await client.get("/documents", headers=alice.headers)) == {
        str(a_private),
        str(a_shared),
    }
    assert ids(await client.get("/documents", headers=bob.headers)) == {
        str(a_shared),
        str(b_private),
    }
    assert ids(await client.get("/documents", headers=carol.headers)) == set()


async def test_unknown_share_targets_are_rejected_without_changes(
    client, alice, bob, make_document
):
    doc_id = await make_document(alice)
    perms_url = f"/documents/{doc_id}/permissions"
    await client.put(perms_url, json={"user_emails": [bob.email]}, headers=alice.headers)

    resp = await client.put(
        perms_url,
        json={
            "user_emails": ["nobody@example.com"],
            "group_ids": ["00000000-0000-0000-0000-000000000000"],
        },
        headers=alice.headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["unknown_user_emails"] == ["nobody@example.com"]
    # The earlier share with Bob is untouched.
    assert (await client.get(perms_url, headers=alice.headers)).json()["user_emails"] == [bob.email]


async def test_sharing_with_yourself_is_ignored(client, alice, make_document):
    doc_id = await make_document(alice)
    resp = await client.put(
        f"/documents/{doc_id}/permissions",
        json={"user_emails": [alice.email]},
        headers=alice.headers,
    )
    assert resp.status_code == 200
    assert resp.json()["user_emails"] == []


async def test_deleting_removes_access_for_everyone(client, alice, bob, make_document):
    doc_id = await make_document(alice)
    await client.put(
        f"/documents/{doc_id}/permissions", json={"user_emails": [bob.email]}, headers=alice.headers
    )
    assert (await client.delete(f"/documents/{doc_id}", headers=alice.headers)).status_code == 204
    assert ids(await client.get("/documents", headers=alice.headers)) == set()
    assert ids(await client.get("/documents", headers=bob.headers)) == set()


async def test_only_admins_manage_groups(client, admin, alice):
    assert (
        await client.post("/groups", json={"name": "X"}, headers=alice.headers)
    ).status_code == 403
    created = await client.post("/groups", json={"name": "X"}, headers=admin.headers)
    assert created.status_code == 201
    group_id = created.json()["id"]
    # Everyone can list groups (so they can pick one when sharing)...
    assert [g["name"] for g in (await client.get("/groups", headers=alice.headers)).json()] == ["X"]
    # ...but only admins can see or change membership.
    members_url = f"/groups/{group_id}/members"
    assert (await client.get(members_url, headers=alice.headers)).status_code == 403
    add = await client.post(members_url, json={"email": alice.email}, headers=alice.headers)
    assert add.status_code == 403


async def test_duplicate_group_name_conflicts(client, admin):
    await client.post("/groups", json={"name": "HR"}, headers=admin.headers)
    resp = await client.post("/groups", json={"name": "HR"}, headers=admin.headers)
    assert resp.status_code == 409
