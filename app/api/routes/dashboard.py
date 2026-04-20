import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.db.session import get_db, AsyncSessionLocal
from app.core.datetime_utils import utc_now_naive
from app.core.dependencies import get_current_user
from app.core.tier_rewards import inviter_tier_multiplier
from app.models.models import (
    User,
    Invitation,
    InvitationStatus,
    Referral,
    ReferralStatus,
    Badge,
    UserBadge,
)
from app.schemas.schemas import DashboardResponse, EarnedBadgeEntry

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

    # Parallel reads: each task uses its own session (asyncpg does not allow concurrent
    # operations on a single connection / session).
    async def get_total_invites():
        async with AsyncSessionLocal() as s:
            r = await s.execute(
                select(func.count()).where(Invitation.inviter_id == current_user.id)
            )
            return int(r.scalar() or 0)

    async def get_pending():
        async with AsyncSessionLocal() as s:
            r = await s.execute(
                select(func.count()).where(
                    Invitation.inviter_id == current_user.id,
                    Invitation.status == InvitationStatus.PENDING,
                )
            )
            return int(r.scalar() or 0)

    async def get_converted_and_balance():
        async with AsyncSessionLocal() as s:
            converted_r = await s.execute(
                select(func.count()).where(
                    Referral.inviter_id == current_user.id,
                    Referral.status == ReferralStatus.CONVERTED,
                )
            )
            balance_r = await s.execute(
                select(User.credits_balance).where(User.id == current_user.id)
            )
            return int(converted_r.scalar() or 0), int(balance_r.scalar() or 0)

    async def get_earned_badges():
        async with AsyncSessionLocal() as s:
            r = await s.execute(
                select(Badge, UserBadge.earned_at)
                .join(UserBadge, UserBadge.badge_id == Badge.id)
                .where(UserBadge.user_id == current_user.id)
                .order_by(UserBadge.earned_at.desc())
            )
            rows = r.all()
            return [
                EarnedBadgeEntry(
                    badge_id=badge.id,
                    badge_type=badge.badge_type,
                    badge_name=badge.badge_name,
                    description=badge.description,
                    earned_at=earned_at,
                )
                for badge, earned_at in rows
            ]

    total_invites, pending, (converted, balance), earned = await asyncio.gather(
        get_total_invites(),
        get_pending(),
        get_converted_and_balance(),
        get_earned_badges(),
    )

    return DashboardResponse(
        total_invites_sent=total_invites,
        pending_referrals=pending,
        total_converted=converted,
        current_multiplier=inviter_tier_multiplier(converted),
        credits_balance=balance,
        earned_badges=earned,
    )