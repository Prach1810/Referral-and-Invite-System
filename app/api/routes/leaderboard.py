import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
from app.core.datetime_utils import utc_now_naive
from app.db.session import get_db
from app.core.redis import get_redis
from app.models.models import Referral, User, ReferralStatus
from app.schemas.schemas import LeaderboardResponse, LeaderboardEntry

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])

CURRENT_MONTH_TTL = 3600          # 1 hour
PAST_MONTH_TTL = 60 * 60 * 24 * 30  # 30 days


@router.get("", response_model=LeaderboardResponse)
async def get_leaderboard(
    month: str = None,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis)
):
    if month is None:
        month = utc_now_naive().strftime("%Y-%m")
    else:
        try:
            parsed = datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")

        now = utc_now_naive()
        if parsed.year > now.year or (parsed.year == now.year and parsed.month > now.month):
            raise HTTPException(status_code=400, detail="Cannot request leaderboard for a future month")

    # check Redis cache
    cache_key = f"leaderboard:{month}"
    cached = redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        return LeaderboardResponse(**data)

    # parse month for query
    month_start = datetime.strptime(month, "%Y-%m")

    result = await db.execute(
        select(
            User.id,
            User.first_name,
            User.last_name,
            func.count(Referral.id).label("conversions")
        )
        .join(Referral, Referral.inviter_id == User.id)
        .where(
            Referral.status == ReferralStatus.CONVERTED,
            func.date_trunc("month", Referral.updated_at) == func.date_trunc("month", month_start)
        )
        .group_by(User.id, User.first_name, User.last_name)
        .order_by(func.count(Referral.id).desc())
        .limit(10)
    )
    rows = result.all()

    entries = [
        LeaderboardEntry(
            rank=idx + 1,
            user_id=row.id,
            first_name=row.first_name,
            last_name=row.last_name,
            conversions=row.conversions
        )
        for idx, row in enumerate(rows)
    ]

    response = LeaderboardResponse(month=month, leaderboard=entries)

    # cache — longer TTL for past months
    now = utc_now_naive()
    is_current_month = (
        month_start.year == now.year and month_start.month == now.month
    )
    ttl = CURRENT_MONTH_TTL if is_current_month else PAST_MONTH_TTL
    redis.setex(cache_key, ttl, response.model_dump_json())

    return response