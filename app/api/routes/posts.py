from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
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

    post = Post(author_id=current_user.id, content=body.content)
    db.add(post)
    await db.flush()

    post_count = (
        await db.execute(
            select(func.count()).where(Post.author_id == current_user.id)
        )
    ).scalar()

    conversion_event_id = None

    if post_count == 1:
        referral = (
            await db.execute(
                select(Referral).where(
                    Referral.invitee_id == current_user.id,
                    Referral.status == ReferralStatus.NOT_CONVERTED,
                )
            )
        ).scalar_one_or_none()

        if referral:
            # DB-level unique constraint (uq_conversion_events_referral) is the source
            # of truth for "one conversion per referral"; this avoids a race where two
            # concurrent first-post requests both see post_count == 1.
            # Use a SAVEPOINT so a duplicate-event collision does not roll back the post.
            conversion_event = ConversionEvent(
                referral_id=referral.id,
                invitee_id=current_user.id,
                event_type="FIRST_CONTENT_GENERATED",
                processed=False,
            )
            try:
                async with db.begin_nested():
                    db.add(conversion_event)
                conversion_event_id = conversion_event.id
            except IntegrityError:
                # Another request already inserted the conversion event — safe to ignore.
                conversion_event_id = None

    await db.commit()
    await db.refresh(post)

    if conversion_event_id is not None:
        q = Queue("conversions", connection=redis)
        q.enqueue(
            "app.workers.conversion_worker.process_conversion",
            str(conversion_event_id),
            retry=Retry(max=3, interval=5),
        )

    return PostResponse(
        post_id=post.id,
        author_id=post.author_id,
        content=post.content,
        created_at=post.created_at,
    )