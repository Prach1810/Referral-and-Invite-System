from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import time

from app.core.datetime_utils import utc_now_naive, to_utc_naive
from uuid import UUID

from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from app.core.redis import get_redis
from app.core.rate_limit import check_signup_rate_limit, check_code_redemption_rate_limit
from app.core.dependencies import logout_bearer, get_client_ip
from app.core.code_generator import generate_referral_code
from app.models.models import (
    User,
    ReferralCode,
    Referral,
    Invitation,
    CampaignType,
    ReferralSource,
    InvitationStatus,
    RateLimitEvent,
    RateLimitAction,
    SignupSource,
)
from app.schemas.schemas import RegisterRequest, LoginRequest, TokenResponse, RegisterResponse
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/auth", tags=["Auth"])


def _parse_signup_source(raw: str) -> SignupSource:
    try:
        return SignupSource(raw.strip().upper())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signup_source value")


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    ip = get_client_ip(request)
    check_signup_rate_limit(ip)

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    signup_source = _parse_signup_source(body.signup_source)

    inviter: Optional[User] = None
    referral_code_obj: Optional[ReferralCode] = None
    pending_invitation: Optional[Invitation] = None

    if body.referral_code:
        check_code_redemption_rate_limit(ip, body.referral_code)

        result = await db.execute(
            select(ReferralCode).where(ReferralCode.code == body.referral_code)
        )
        referral_code_obj = result.scalar_one_or_none()

        if not referral_code_obj:
            raise HTTPException(status_code=404, detail="Referral code not found")

        # Enforce max_uses for any campaign when the limit is set (not only PROMO).
        if (
            referral_code_obj.max_uses is not None
            and referral_code_obj.uses_count >= referral_code_obj.max_uses
        ):
            raise HTTPException(
                status_code=410,
                detail="Referral code has reached maximum uses",
            )

        if referral_code_obj.campaign_type == CampaignType.PROMO:
            if (
                referral_code_obj.expires_at is not None
                and to_utc_naive(referral_code_obj.expires_at) <= utc_now_naive()
            ):
                raise HTTPException(
                    status_code=410,
                    detail="Referral code has expired",
                )

        inviter_result = await db.execute(
            select(User).where(User.id == referral_code_obj.owner_id)
        )
        inviter = inviter_result.scalar_one_or_none()
        if inviter is None:
            raise HTTPException(status_code=404, detail="Referral code not found")

        # Self-referral: same email as the code owner (cannot refer yourself).
        if inviter.email.lower() == body.email.lower():
            raise HTTPException(
                status_code=409,
                detail="Self-referral is not allowed",
            )

        invitation_result = await db.execute(
            select(Invitation).where(
                Invitation.invitee_email == body.email,
                Invitation.referral_code_id == referral_code_obj.id,
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        pending_invitation = invitation_result.scalar_one_or_none()

        if pending_invitation is not None:
            if to_utc_naive(pending_invitation.expired_at) <= utc_now_naive():
                # Wrong order previously: user row was created first, then we raised — leaving orphan users.
                raise HTTPException(
                    status_code=410,
                    detail="Invitation has expired",
                )

    new_user = User(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        password_hash=hash_password(body.password),
        referred_by=inviter.id if inviter else None,
    )
    db.add(new_user)
    await db.flush()

    # Previous check `inviter.id == new_user.id` after flush was ineffective: new_user always
    # had a fresh UUID, so it could never equal the code owner. Use email match above instead.

    for _ in range(5):
        candidate = generate_referral_code()
        exists = await db.execute(
            select(ReferralCode).where(ReferralCode.code == candidate)
        )
        if not exists.scalar_one_or_none():
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique referral code")

    new_code = ReferralCode(
        code=candidate,
        owner_id=new_user.id,
        campaign_type=CampaignType.DEFAULT,
    )
    db.add(new_code)

    if referral_code_obj is not None and inviter is not None:
        referral_code_obj.uses_count += 1

        if pending_invitation is not None:
            pending_invitation.status = InvitationStatus.SIGNED_UP
            pending_invitation.invitee_id = new_user.id
            pending_invitation.signed_up_at = utc_now_naive()
            pending_invitation.signup_source = signup_source

            referral = Referral(
                referral_code_id=referral_code_obj.id,
                inviter_id=inviter.id,
                invitee_id=new_user.id,
                invitation_id=pending_invitation.id,
                source=ReferralSource.INVITE,
            )
        else:
            referral = Referral(
                referral_code_id=referral_code_obj.id,
                inviter_id=inviter.id,
                invitee_id=new_user.id,
                invitation_id=None,
                source=ReferralSource.LINK,
            )

        db.add(referral)

    db.add(
        RateLimitEvent(
            user_id=new_user.id,
            ip_address=ip,
            action=RateLimitAction.SIGNUP,
        )
    )

    if referral_code_obj is not None:
        db.add(
            RateLimitEvent(
                user_id=new_user.id,
                ip_address=ip,
                action=RateLimitAction.CODE_REDEMPTION,
            )
        )

    await db.commit()
    await db.refresh(new_user)

    token = create_access_token(
        {
            "user_id": str(new_user.id),
            "email": new_user.email,
            "role": new_user.role.value,
        }
    )

    referred_by: Optional[UUID] = new_user.referred_by

    return RegisterResponse(
        user_id=new_user.id,
        referral_code=candidate,
        referred_by=referred_by,
        access_token=token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    if not (body.email and str(body.email).strip()):
        raise HTTPException(status_code=400, detail="Email and password are required")
    if body.password is None or body.password == "":
        raise HTTPException(status_code=400, detail="Email and password are required")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="Email not found")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong password")

    token = create_access_token(
        {
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
    )

    return TokenResponse(access_token=token, user_id=user.id, role=user.role)


@router.post("/logout", status_code=200)
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(logout_bearer),
    redis=Depends(get_redis),
):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="No token provided")

    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    jti = payload.get("jti")
    exp = payload.get("exp")

    if not jti:
        raise HTTPException(status_code=401, detail="Invalid token")

    if redis.get(f"blacklist:{jti}"):
        raise HTTPException(status_code=401, detail="Token already blacklisted")

    if exp is not None:
        ttl = int(float(exp) - time.time())
        if ttl > 0:
            redis.setex(f"blacklist:{jti}", ttl, "1")

    return {"message": "logged out successfully"}
