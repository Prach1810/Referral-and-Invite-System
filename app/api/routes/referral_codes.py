from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.core.datetime_utils import utc_now_naive, to_utc_naive
from app.core.dependencies import get_current_user, get_admin_user
from app.core.config import settings
from app.models.models import User, ReferralCode, CampaignType
from app.schemas.schemas import (
    MyReferralCodesResponse, ReferralCodeResponse, CreatePromoCodeRequest
)

router = APIRouter(tags=["Referral Codes"])


def build_code_response(code: ReferralCode, base_url: str) -> ReferralCodeResponse:
    return ReferralCodeResponse(
        id=code.id,
        code=code.code,
        campaign_type=code.campaign_type,
        expires_at=code.expires_at,
        max_uses=code.max_uses,
        uses_count=code.uses_count,
        created_at=code.created_at,
        shareable_link=f"{base_url}/signup?ref={code.code}"
    )


@router.get("/referral-codes/me", response_model=MyReferralCodesResponse)
async def get_my_referral_codes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ReferralCode).where(ReferralCode.owner_id == current_user.id)
    )
    codes = result.scalars().all()

    return MyReferralCodesResponse(
        codes=[build_code_response(c, settings.BASE_URL) for c in codes]
    )


@router.post("/admin/referral-codes", response_model=ReferralCodeResponse, status_code=201)
async def create_promo_code(
    body: CreatePromoCodeRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    expires_at_utc = to_utc_naive(body.expires_at)
    if expires_at_utc <= utc_now_naive():
        raise HTTPException(status_code=400, detail="expires_at must be in the future")

    existing = await db.execute(
        select(ReferralCode).where(ReferralCode.code == body.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists")

    promo = ReferralCode(
        code=body.code,
        owner_id=current_user.id,
        expires_at=expires_at_utc,
        max_uses=body.max_uses,
        campaign_type=CampaignType.PROMO
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)

    return build_code_response(promo, settings.BASE_URL)