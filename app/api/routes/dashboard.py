import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.db.session import get_db
from app.core.datetime_utils import utc_now_naive
from app.core.dependencies import get_current_user
from app.models.models import (
    User, Invitation, Referral,
    InvitationStatus, ReferralStatus
)
from app.schemas.schemas import DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/me", response_model=DashboardResponse)
async def get_my_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # lazy expiry before fetching
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

    # run all queries in parallel
    async def get_total_invites():
        result = await db.execute(
            select(func.count()).where(Invitation.inviter_id == current_user.id)
        )
        return result.scalar()

    async def get_pending():
        result = await db.execute(
            select(func.count()).where(
                Invitation.inviter_id == current_user.id,
                Invitation.status == InvitationStatus.PENDING
            )
        )
        return result.scalar()

    async def get_converted():
        result = await db.execute(
            select(func.count()).where(
                Referral.inviter_id == current_user.id,
                Referral.status == ReferralStatus.CONVERTED
            )
        )
        return result.scalar()

    async def get_balance():
        result = await db.execute(
            select(User.credits_balance).where(User.id == current_user.id)
        )
        return result.scalar()

    total_invites, pending, converted, balance = await asyncio.gather(
        get_total_invites(),
        get_pending(),
        get_converted(),
        get_balance()
    )

    return DashboardResponse(
        total_invites_sent=total_invites,
        pending_referrals=pending,
        total_converted=converted,
        credits_balance=balance
    )