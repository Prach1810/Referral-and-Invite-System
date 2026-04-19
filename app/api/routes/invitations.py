from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import timedelta
from app.core.datetime_utils import utc_now_naive
from rq import Queue
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.core.config import settings
from app.models.models import (
    User, ReferralCode, Invitation, InvitationStatus, CampaignType
)
from app.schemas.schemas import (
    CreateInvitationRequest, InvitationResponse,
    MyInvitationsResponse, InvitationDetailResponse
)

router = APIRouter(prefix="/invitations", tags=["Invitations"])


@router.post("", response_model=InvitationResponse, status_code=201)
async def send_invitation(
    body: CreateInvitationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis)
):
    # self-invite check
    if body.invitee_email == current_user.email:
        raise HTTPException(status_code=400, detail="You cannot invite yourself")

    # already registered check
    existing_user = await db.execute(
        select(User).where(User.email == body.invitee_email)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This email is already registered")

    # duplicate pending invite check
    existing_invite = await db.execute(
        select(Invitation).where(
            Invitation.inviter_id == current_user.id,
            Invitation.invitee_email == body.invitee_email,
            Invitation.status == InvitationStatus.PENDING
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You already have a pending invite for this email")

    # get inviter's default referral code
    code_result = await db.execute(
        select(ReferralCode).where(
            ReferralCode.owner_id == current_user.id,
            ReferralCode.campaign_type == CampaignType.DEFAULT
        )
    )
    referral_code = code_result.scalar_one_or_none()
    if not referral_code:
        raise HTTPException(status_code=500, detail="No referral code found for user")

    expired_at = utc_now_naive() + timedelta(days=30)

    invitation = Invitation(
        referral_code_id=referral_code.id,
        inviter_id=current_user.id,
        invitee_email=body.invitee_email,
        expired_at=expired_at
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # enqueue email sending async via RQ
    q = Queue("emails", connection=redis)
    shareable_link = f"{settings.BASE_URL}/signup?ref={referral_code.code}"
    q.enqueue(
        "app.workers.conversion_worker.send_invite_email",
        body.invitee_email,
        f"{current_user.first_name} {current_user.last_name}",
        shareable_link
    )

    return InvitationResponse(
        invitation_id=invitation.id,
        invitee_email=invitation.invitee_email,
        status=invitation.status,
        expired_at=invitation.expired_at,
        shareable_link=shareable_link
    )


@router.get("/me", response_model=MyInvitationsResponse)
async def get_my_invitations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # lazy expiry — bulk update stale pending invitations before fetching
    await db.execute(
        update(Invitation)
        .where(
            Invitation.inviter_id == current_user.id,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.expired_at < utc_now_naive()
        )
        .values(status=InvitationStatus.EXPIRED)
    )
    await db.commit()

    result = await db.execute(
        select(Invitation)
        .where(Invitation.inviter_id == current_user.id)
        .order_by(Invitation.invited_at.desc())
    )
    invitations = result.scalars().all()

    return MyInvitationsResponse(
        total=len(invitations),
        invitations=[
            InvitationDetailResponse(
                invitation_id=inv.id,
                invitee_email=inv.invitee_email,
                status=inv.status,
                invited_at=inv.invited_at,
                expired_at=inv.expired_at,
                signed_up_at=inv.signed_up_at
            )
            for inv in invitations
        ]
    )