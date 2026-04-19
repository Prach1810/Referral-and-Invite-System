from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.models import User, CreditsLedger
from app.schemas.schemas import MyCreditsResponse, CreditEntryResponse

router = APIRouter(prefix="/credits", tags=["Credits"])


@router.get("/me", response_model=MyCreditsResponse)
async def get_my_credits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(CreditsLedger)
        .where(CreditsLedger.user_id == current_user.id)
        .order_by(CreditsLedger.created_at.desc())
    )
    entries = result.scalars().all()

    return MyCreditsResponse(
        credits_balance=current_user.credits_balance,
        history=[
            CreditEntryResponse(
                amount=e.amount,
                reason=e.reason,
                reference_id=e.reference_id,
                created_at=e.created_at
            )
            for e in entries
        ]
    )