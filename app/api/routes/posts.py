from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from rq import Queue, Retry
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.models.models import (
    User, Post, Referral, ConversionEvent,
    ReferralStatus
)
from app.schemas.schemas import CreatePostRequest, PostResponse

router = APIRouter(prefix="/posts", tags=["Posts"])


@router.post("", response_model=PostResponse, status_code=201)
async def create_post(
    body: CreatePostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis)
):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    # create post
    post = Post(author_id=current_user.id, content=body.content)
    db.add(post)
    await db.flush()  # get post.id

    # check if this is the user's first post
    post_count_result = await db.execute(
        select(func.count()).where(Post.author_id == current_user.id)
    )
    post_count = post_count_result.scalar()

    if post_count == 1:
        # first post — check for unconverted referral
        referral_result = await db.execute(
            select(Referral).where(
                Referral.invitee_id == current_user.id,
                Referral.status == ReferralStatus.NOT_CONVERTED
            )
        )
        referral = referral_result.scalar_one_or_none()

        if referral:
            # idempotency check — ensure no processed event exists
            existing_event = await db.execute(
                select(ConversionEvent).where(
                    ConversionEvent.referral_id == referral.id,
                    ConversionEvent.processed == True
                )
            )
            if not existing_event.scalar_one_or_none():
                # create conversion event
                conversion_event = ConversionEvent(
                    referral_id=referral.id,
                    invitee_id=current_user.id,
                    event_type="FIRST_CONTENT_GENERATED",
                    processed=False
                )
                db.add(conversion_event)
                await db.flush()

                # enqueue reward processing via RQ
                q = Queue("conversions", connection=redis)
                q.enqueue(
                    "app.workers.conversion_worker.process_conversion",
                    str(conversion_event.id),
                    retry=Retry(max=3, interval=5)
                )

    await db.commit()
    await db.refresh(post)

    return PostResponse(
        post_id=post.id,
        author_id=post.author_id,
        content=post.content,
        created_at=post.created_at
    )