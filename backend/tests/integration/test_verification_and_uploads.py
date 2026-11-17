"""Uploads (validation, EXIF stripping, authorization), verification workflow and portfolio (PostgreSQL)."""

from __future__ import annotations

import io
import uuid

import httpx
import pytest
from PIL import Image

from app.core.clock import FrozenClock
from app.core.container import Services
from app.modules.professionals import service as professionals_service
from tests.support import (
    API,
    PDF_BYTES,
    create_admin_account,
    image_bytes,
    register,
    register_professional,
    upload,
)


async def test_image_upload_is_reencoded_and_exif_gps_stripped(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account = await register(client)
    original = image_bytes("JPEG", exif_make="SecretPhoneCam")
    assert Image.open(io.BytesIO(original)).getexif().get(0x010F) == "SecretPhoneCam"
    response = await upload(client, account, "AVATAR", original, filename="me.jpg", content_type="image/jpeg")
    assert response.status_code == 201, response.text
    ref = response.json()
    assert ref["content_type"] == "image/jpeg"
    assert (ref["width"], ref["height"]) == (64, 48)
    assert ref["signed_url"] is None  # avatars are public
    stored = await client.get(ref["url"])
    assert stored.status_code == 200
    exif = Image.open(io.BytesIO(stored.content)).getexif()
    assert len(exif) == 0
    assert b"SecretPhoneCam" not in stored.content


async def test_type_is_detected_from_bytes_not_name_or_header(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    account = await register(client)
    fake = await upload(client, account, "AVATAR", b"<script>alert(1)</script>", filename="x.png")
    assert fake.status_code == 415
    pdf_as_avatar = await upload(client, account, "AVATAR", PDF_BYTES, filename="doc.png")
    assert pdf_as_avatar.status_code == 415
    corrupt = await upload(client, account, "AVATAR", b"\x89PNG\r\n\x1a\n" + b"garbage" * 20)
    assert corrupt.status_code == 415
    renamed_png = await upload(
        client, account, "AVATAR", image_bytes("PNG"), filename="x.gif", content_type="image/gif"
    )
    assert renamed_png.status_code == 201
    assert renamed_png.json()["content_type"] == "image/png"


async def test_size_limits_and_empty_files(client: httpx.AsyncClient, seeded: Services) -> None:
    account = await register(client)
    oversized = image_bytes("PNG") + b"\0" * (5 * 1024 * 1024)
    assert (await upload(client, account, "AVATAR", oversized)).status_code == 413
    assert (await upload(client, account, "AVATAR", b"")).status_code == 400


async def test_purpose_role_restrictions_and_auth(client: httpx.AsyncClient, seeded: Services) -> None:
    customer = await register(client)
    assert (await upload(client, customer, "PORTFOLIO")).status_code == 403
    assert (await upload(client, customer, "VERIFICATION_DOCUMENT", PDF_BYTES)).status_code == 403
    anonymous = await client.post(
        f"{API}/uploads", files={"file": ("a.png", image_bytes(), "image/png")}, data={"purpose": "AVATAR"}
    )
    assert anonymous.status_code == 401


async def test_private_files_are_only_readable_by_owner_admin_or_signed_url(
    client: httpx.AsyncClient, seeded: Services, clock: FrozenClock
) -> None:
    pro, _ = await register_professional(client)
    stranger = await register(client)
    admin = await create_admin_account(client, seeded)
    ref = (await upload(client, pro, "VERIFICATION_DOCUMENT", PDF_BYTES, filename="id.pdf")).json()
    assert ref["signed_url"] is not None
    assert (await client.get(ref["url"])).status_code == 404
    assert (await client.get(ref["url"], headers=stranger.headers)).status_code == 404
    owner = await client.get(ref["url"], headers=pro.headers)
    assert owner.status_code == 200
    assert owner.headers["content-disposition"].startswith("attachment")
    assert owner.headers["cache-control"] == "private, no-store"
    assert (await client.get(ref["url"], headers=admin.headers)).status_code == 200
    assert (await client.get(ref["signed_url"])).status_code == 200
    tampered = ref["signed_url"][:-3] + "abc"
    assert (await client.get(tampered)).status_code == 404
    clock.advance(301)
    assert (await client.get(ref["signed_url"])).status_code == 404
    assert (await client.get(f"{API}/files/{uuid.uuid4()}")).status_code == 404


async def test_verification_workflow(client: httpx.AsyncClient, seeded: Services) -> None:
    pro, professional_id = await register_professional(client)
    admin = await create_admin_account(client, seeded)
    document = (await upload(client, pro, "VERIFICATION_DOCUMENT", PDF_BYTES, filename="nin.pdf")).json()

    submitted = await client.post(
        f"{API}/professionals/me/verifications",
        json={"type": "IDENTITY", "file_ids": [document["id"]], "note": "NIN slip"},
        headers=pro.headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["verification_status"] == "PENDING"

    queue = await client.get(f"{API}/admin/verifications", headers=admin.headers)
    assert queue.status_code == 200
    item = next(entry for entry in queue.json() if entry["professional_id"] == professional_id)
    assert item["files"][0]["id"] == document["id"]
    assert (await client.get(item["files"][0]["url"], headers=admin.headers)).status_code == 200

    reject_without_reason = await client.post(
        f"{API}/admin/verifications/{item['id']}/decision",
        json={"decision": "REJECTED"},
        headers=admin.headers,
    )
    assert reject_without_reason.status_code == 422
    approved = await client.post(
        f"{API}/admin/verifications/{item['id']}/decision",
        json={"decision": "VERIFIED"},
        headers=admin.headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "VERIFIED"
    again = await client.post(
        f"{API}/admin/verifications/{item['id']}/decision",
        json={"decision": "VERIFIED"},
        headers=admin.headers,
    )
    assert again.status_code == 409

    public = (await client.get(f"{API}/professionals/{professional_id}")).json()
    assert public["verification_status"] == "VERIFIED"
    assert public["verification"]["identity"] is True
    assert "verifications" not in public
    listed = (await client.get(f"{API}/professionals", params={"verified_only": "true"})).json()
    assert [entry["id"] for entry in listed] == [professional_id]


async def test_only_admins_decide_and_documents_must_be_own(
    client: httpx.AsyncClient, seeded: Services
) -> None:
    pro, _ = await register_professional(client)
    other, _ = await register_professional(client, name="Other Pro")
    foreign_doc = (await upload(client, other, "VERIFICATION_DOCUMENT", PDF_BYTES)).json()
    stolen = await client.post(
        f"{API}/professionals/me/verifications",
        json={"type": "IDENTITY", "file_ids": [foreign_doc["id"]]},
        headers=pro.headers,
    )
    assert stolen.status_code == 400
    assert stolen.json()["code"] == "INVALID_FILE"
    avatar = (await upload(client, pro, "AVATAR")).json()
    wrong_purpose = await client.post(
        f"{API}/professionals/me/verifications",
        json={"type": "TRADE", "file_ids": [avatar["id"]]},
        headers=pro.headers,
    )
    assert wrong_purpose.status_code == 400
    phone = await client.post(
        f"{API}/professionals/me/verifications", json={"type": "PHONE"}, headers=pro.headers
    )
    assert phone.status_code == 200
    assert (await client.post(
        f"{API}/professionals/me/verifications", json={"type": "IDENTITY"}, headers=pro.headers
    )).status_code == 422  # fmt: skip
    for actor in (pro, await register(client)):
        assert (await client.get(f"{API}/admin/verifications", headers=actor.headers)).status_code == 403
        decision = await client.post(
            f"{API}/admin/verifications/{uuid.uuid4()}/decision",
            json={"decision": "VERIFIED"},
            headers=actor.headers,
        )
        assert decision.status_code == 403


async def test_portfolio_crud_and_ownership(
    client: httpx.AsyncClient, seeded: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    pro, professional_id = await register_professional(client)
    other, _ = await register_professional(client, name="Other Pro")
    image = (await upload(client, pro, "PORTFOLIO")).json()
    created = await client.post(
        f"{API}/professionals/me/portfolio",
        json={"title": "iPhone 13 screen", "caption": "Before and after", "image_file_id": image["id"]},
        headers=pro.headers,
    )
    assert created.status_code == 201
    item = created.json()
    public = (await client.get(f"{API}/professionals/{professional_id}")).json()
    assert public["portfolio"][0]["title"] == "iPhone 13 screen"
    assert (await client.get(public["portfolio"][0]["image_url"])).status_code == 200

    stolen = await client.post(
        f"{API}/professionals/me/portfolio", json={"title": "Not mine", "image_file_id": image["id"]},
        headers=other.headers,
    )  # fmt: skip
    assert stolen.status_code == 400
    assert (
        await client.patch(
            f"{API}/professionals/me/portfolio/{item['id']}", json={"title": "x"}, headers=other.headers
        )
    ).status_code == 404
    edited = await client.patch(
        f"{API}/professionals/me/portfolio/{item['id']}", json={"caption": "Updated"}, headers=pro.headers
    )
    assert edited.json()["caption"] == "Updated"

    monkeypatch.setattr(professionals_service, "MAX_PORTFOLIO_ITEMS", 1)
    full = await client.post(
        f"{API}/professionals/me/portfolio",
        json={"title": "Second", "image_file_id": image["id"]},
        headers=pro.headers,
    )
    assert full.status_code == 409
    deleted = await client.delete(f"{API}/professionals/me/portfolio/{item['id']}", headers=pro.headers)
    assert deleted.status_code == 204


async def test_avatar_on_profile(client: httpx.AsyncClient, seeded: Services) -> None:
    pro, professional_id = await register_professional(client)
    avatar = (await upload(client, pro, "AVATAR")).json()
    me = await client.patch(f"{API}/auth/me", json={"avatar_file_id": avatar["id"]}, headers=pro.headers)
    assert me.json()["avatar_url"] == avatar["url"]
    assert (await client.get(f"{API}/professionals/{professional_id}")).json()["avatar_url"] == avatar["url"]
    other = await register(client)
    stolen = await client.patch(
        f"{API}/auth/me", json={"avatar_file_id": avatar["id"]}, headers=other.headers
    )
    assert stolen.status_code == 400
