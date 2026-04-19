from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.models import Referral, ReferralStatus, ReferralSource, User
from app.schemas.schemas import MyReferralsResponse, ReferralsBySourceResponse

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.get("/me", response_model=MyReferralsResponse)
async def get_my_referrals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Referral).where(Referral.inviter_id == current_user.id)
    )
    referrals = result.scalars().all()

    total = len(referrals)
    invite_count = sum(1 for r in referrals if r.source == ReferralSource.INVITE)
    link_count = sum(1 for r in referrals if r.source == ReferralSource.LINK)
    converted = sum(1 for r in referrals if r.status == ReferralStatus.CONVERTED)
    not_converted = sum(1 for r in referrals if r.status == ReferralStatus.NOT_CONVERTED)

    return MyReferralsResponse(
        total=total,
        by_source=ReferralsBySourceResponse(invite=invite_count, link=link_count),
        converted=converted,
        not_converted=not_converted
    )