from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.core.datetime_utils import utc_now_naive
from app.core.dependencies import get_current_user
from app.models.models import User, ReferralCode, CampaignType
from app.schemas.schemas import UserProfileResponse, UpdateUserRequest, UpdateUserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ReferralCode).where(
            ReferralCode.owner_id == current_user.id,
            ReferralCode.campaign_type == CampaignType.DEFAULT
        )
    )
    default_code = result.scalar_one_or_none()

    return UserProfileResponse(
        user_id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        phone=current_user.phone,
        referral_code=default_code.code if default_code else "",
        credits_balance=current_user.credits_balance,
        referred_by=current_user.referred_by,
        created_at=current_user.created_at
    )


@router.put("/me", response_model=UpdateUserResponse)
async def update_my_profile(
    body: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if body.model_fields_set.isdisjoint({"first_name", "last_name", "phone"}):
        raise HTTPException(status_code=400, detail="At least one field must be provided")

    if body.first_name is not None:
        current_user.first_name = body.first_name
    if body.last_name is not None:
        current_user.last_name = body.last_name
    if body.phone is not None:
        current_user.phone = body.phone

    current_user.updated_at = utc_now_naive()
    await db.commit()
    await db.refresh(current_user)

    return UpdateUserResponse(
        user_id=current_user.id,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        phone=current_user.phone,
        updated_at=current_user.updated_at
    )