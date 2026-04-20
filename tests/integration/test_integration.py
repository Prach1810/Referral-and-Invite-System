"""
Integration tests for the Flik Referral System.

These tests run against a real database and Redis instance.
They require the full Docker stack to be running.

Usage:
    docker-compose exec web pytest tests/integration/ -v

Each test class is independent — setUp creates fresh users with unique emails.
"""
import pytest
import uuid
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings
from app.core.security import hash_password
from app.core.code_generator import generate_referral_code
from app.models.models import User, ReferralCode, CampaignType, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

async def _seed_user_with_referral_code(
    email: str, role: UserRole
) -> tuple:
    """
    Insert user + default referral code using a disposable async engine/session.
    Avoids sharing the app's pooled connections during ASGI tests (asyncpg safety).
    """
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    try:
        async with SessionLocal() as db:
            async with db.begin():
                for _ in range(5):
                    candidate = generate_referral_code()
                    exists = await db.execute(
                        select(ReferralCode).where(ReferralCode.code == candidate)
                    )
                    if not exists.scalar_one_or_none():
                        break

                user = User(
                    email=email,
                    first_name="Test",
                    last_name="User",
                    password_hash=hash_password("password123"),
                    role=role,
                )
                db.add(user)
                await db.flush()

                code = ReferralCode(
                    code=candidate, owner_id=user.id, campaign_type=CampaignType.DEFAULT
                )
                db.add(code)
            
            # Extract the ID outside the begin() block
            user_id = user.id
            
    finally:
        # Aggressively kill the engine and yield to the event loop
        await engine.dispose()
        await asyncio.sleep(0.1)

    return user_id, candidate


# ── helpers ───────────────────────────────────────────────────────────────────

def unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}@test.com"


async def create_user_direct(email: str, role: UserRole = UserRole.USER) -> tuple:
    """Create a user directly in DB, return (user, referral_code_str)."""
    return await _seed_user_with_referral_code(email, role)


async def login(client: AsyncClient, email: str, password: str = "password123") -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAuth:

    async def test_register_success(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("reg")
            resp = await client.post("/auth/register", json={
                "email": email,
                "first_name": "Test",
                "last_name": "User",
                "password": "password123",
                "signup_source": "WEB"
            })
            assert resp.status_code == 201
            data = resp.json()
            assert "user_id" in data
            assert data["referral_code"].startswith("FLIK-")
            assert data["referred_by"] is None
            assert "access_token" in data

    async def test_register_duplicate_email(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("dup")
            payload = {"email": email, "first_name": "T", "last_name": "U", "password": "pw123", "signup_source": "WEB"}
            await client.post("/auth/register", json=payload)
            resp = await client.post("/auth/register", json=payload)
            assert resp.status_code == 400
            assert "already registered" in resp.json()["detail"]

    async def test_register_with_referral_code(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inviter_email = unique_email("inviter")
            inviter_id, code = await create_user_direct(inviter_email)

            invitee_email = unique_email("invitee")
            resp = await client.post("/auth/register", json={
                "email": invitee_email,
                "first_name": "Invitee",
                "last_name": "User",
                "password": "password123",
                "referral_code": code,
                "signup_source": "WEB"
            })
            assert resp.status_code == 201
            assert resp.json()["referred_by"] == str(inviter_id)

    async def test_login_success(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("login")
            await create_user_direct(email)
            resp = await client.post("/auth/login", json={"email": email, "password": "password123"})
            assert resp.status_code == 200
            assert "access_token" in resp.json()

    async def test_login_wrong_password(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("wrongpw")
            await create_user_direct(email)
            resp = await client.post("/auth/login", json={"email": email, "password": "wrongpassword"})
            assert resp.status_code == 401

    async def test_logout_blacklists_token(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("logout")
            await create_user_direct(email)
            token = await login(client, email)

            # logout
            resp = await client.post("/auth/logout", headers=auth_headers(token))
            assert resp.status_code == 200

            # token should now be invalid
            resp = await client.get("/users/me", headers=auth_headers(token))
            assert resp.status_code == 401

    async def test_self_referral_blocked(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("selfref")
            _, code = await create_user_direct(email)
            resp = await client.post("/auth/register", json={
                "email": email,
                "first_name": "T", "last_name": "U",
                "password": "password123",
                "referral_code": code,
                "signup_source": "WEB"
            })
            assert resp.status_code in [400, 409]


# ── Users Tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestUsers:

    async def test_get_profile(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("profile")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.get("/users/me", headers=auth_headers(token))
            assert resp.status_code == 200
            data = resp.json()
            assert data["email"] == email
            assert data["referral_code"].startswith("FLIK-")

    async def test_update_profile(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("update")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.put("/users/me", headers=auth_headers(token), json={"first_name": "Updated"})
            assert resp.status_code == 200
            assert resp.json()["first_name"] == "Updated"

    async def test_unauthenticated_access_denied(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/users/me")
            assert resp.status_code == 403


# ── Referral Flow Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestReferralFlow:

    async def test_referral_created_on_signup_with_code(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inviter_email = unique_email("inv")
            _, code = await create_user_direct(inviter_email)

            invitee_email = unique_email("invitee")
            await client.post("/auth/register", json={
                "email": invitee_email,
                "first_name": "T", "last_name": "U",
                "password": "password123",
                "referral_code": code,
                "signup_source": "WEB"
            })

            token = await login(client, inviter_email)
            resp = await client.get("/referrals/me", headers=auth_headers(token))
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["by_source"]["link"] == 1
            assert data["not_converted"] == 1

    async def test_conversion_on_first_post(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inviter_email = unique_email("cinviter")
            _, code = await create_user_direct(inviter_email)

            invitee_email = unique_email("cinvitee")
            await client.post("/auth/register", json={
                "email": invitee_email,
                "first_name": "T", "last_name": "U",
                "password": "password123",
                "referral_code": code,
                "signup_source": "WEB"
            })

            invitee_token = await login(client, invitee_email)
            resp = await client.post("/posts", headers=auth_headers(invitee_token), json={"content": "first post"})
            assert resp.status_code == 201

            # give worker a moment
            await asyncio.sleep(2)

            # invitee should have 25 credits
            resp = await client.get("/credits/me", headers=auth_headers(invitee_token))
            assert resp.status_code == 200
            assert resp.json()["credits_balance"] == 25

    async def test_second_post_does_not_reconvert(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            inviter_email = unique_email("reinviter")
            _, code = await create_user_direct(inviter_email)

            invitee_email = unique_email("reinvitee")
            await client.post("/auth/register", json={
                "email": invitee_email, "first_name": "T", "last_name": "U",
                "password": "password123", "referral_code": code, "signup_source": "WEB"
            })

            invitee_token = await login(client, invitee_email)
            await client.post("/posts", headers=auth_headers(invitee_token), json={"content": "first"})
            await asyncio.sleep(2)
            await client.post("/posts", headers=auth_headers(invitee_token), json={"content": "second"})
            await asyncio.sleep(1)

            # still only 25 credits — not 50
            resp = await client.get("/credits/me", headers=auth_headers(invitee_token))
            assert resp.json()["credits_balance"] == 25


# ── Invitations Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestInvitations:

    async def test_send_invitation(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("sender")
            await create_user_direct(email)
            token = await login(client, email)

            invitee = unique_email("recipient")
            resp = await client.post("/invitations", headers=auth_headers(token),
                                     json={"invitee_email": invitee})
            assert resp.status_code == 201
            assert resp.json()["status"] == "PENDING"

    async def test_duplicate_invitation_rejected(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("dupinviter")
            await create_user_direct(email)
            token = await login(client, email)

            invitee = unique_email("duprecipient")
            await client.post("/invitations", headers=auth_headers(token), json={"invitee_email": invitee})
            resp = await client.post("/invitations", headers=auth_headers(token), json={"invitee_email": invitee})
            assert resp.status_code == 409

    async def test_self_invitation_blocked(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("selfinvite")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.post("/invitations", headers=auth_headers(token), json={"invitee_email": email})
            assert resp.status_code == 400


# ── Dashboard Tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDashboard:

    async def test_dashboard_returns_correct_shape(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("dash")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.get("/dashboard/me", headers=auth_headers(token))
            assert resp.status_code == 200
            data = resp.json()
            assert "total_invites_sent" in data
            assert "pending_referrals" in data
            assert "total_converted" in data
            assert "current_multiplier" in data
            assert "credits_balance" in data
            assert "earned_badges" in data

    async def test_fresh_user_zero_stats(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("fresh")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.get("/dashboard/me", headers=auth_headers(token))
            data = resp.json()
            assert data["total_invites_sent"] == 0
            assert data["total_converted"] == 0
            assert data["credits_balance"] == 0
            assert data["current_multiplier"] == 1.0


# ── Leaderboard Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestLeaderboard:

    async def test_leaderboard_public(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/leaderboard")
            assert resp.status_code == 200
            data = resp.json()
            assert "month" in data
            assert "leaderboard" in data

    async def test_leaderboard_invalid_month(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/leaderboard?month=not-a-month")
            assert resp.status_code == 400

    async def test_leaderboard_future_month_rejected(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/leaderboard?month=2099-01")
            assert resp.status_code == 400


# ── Admin Tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAdmin:

    async def test_non_admin_cannot_create_promo_code(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("nonadmin")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.post("/admin/referral-codes", headers=auth_headers(token), json={
                "code": "TESTPROMO",
                "expires_at": "2026-12-31T00:00:00Z",
                "max_uses": 100
            })
            assert resp.status_code == 403

    async def test_non_admin_cannot_view_anomalies(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = unique_email("nonadmin2")
            await create_user_direct(email)
            token = await login(client, email)
            resp = await client.get("/admin/anomalies", headers=auth_headers(token))
            assert resp.status_code == 403

    async def test_admin_can_create_promo_code(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_email = unique_email("admintest")
            await create_user_direct(admin_email, role=UserRole.ADMIN)
            token = await login(client, admin_email)

            code = f"TESTPROMO{uuid.uuid4().hex[:4].upper()}"
            resp = await client.post("/admin/referral-codes", headers=auth_headers(token), json={
                "code": code,
                "expires_at": "2026-12-31T00:00:00Z",
                "max_uses": 100
            })
            assert resp.status_code == 201
            assert resp.json()["campaign_type"] == "PROMO"