from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.models import User, UserBadge, Badge, BadgeType

router = APIRouter(prefix="/badges", tags=["Badges"])


class BadgeResponse(BaseModel):
    badge_id: UUID
    badge_type: BadgeType
    badge_name: str
    description: str
    threshold: int
    earned_at: datetime


class MyBadgesResponse(BaseModel):
    total: int
    badges: List[BadgeResponse]


@router.get("/me", response_model=MyBadgesResponse)
async def get_my_badges(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(UserBadge, Badge)
        .join(Badge, Badge.id == UserBadge.badge_id)
        .where(UserBadge.user_id == current_user.id)
        .order_by(UserBadge.earned_at.desc())
    )
    rows = result.all()

    badges = [
        BadgeResponse(
            badge_id=badge.id,
            badge_type=badge.badge_type,
            badge_name=badge.badge_name,
            description=badge.description,
            threshold=badge.threshold,
            earned_at=user_badge.earned_at
        )
        for user_badge, badge in rows
    ]

    return MyBadgesResponse(total=len(badges), badges=badges)