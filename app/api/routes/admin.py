import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
from app.db.session import get_db
from app.core.dependencies import get_admin_user
from app.models.models import User, RateLimitEvent, RateLimitAction
from app.schemas.schemas import AnomaliesResponse, AnomalyEntry

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/anomalies", response_model=AnomaliesResponse)
async def get_anomalies(
    current_user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    window_start = datetime.utcnow() - timedelta(hours=24)

    # aggregate rate limit events per user+ip in last 24hrs
    result = await db.execute(
        select(
            RateLimitEvent.user_id,
            RateLimitEvent.ip_address,
            func.count(RateLimitEvent.id).label("event_count"),
            func.min(RateLimitEvent.created_at).label("first_event"),
            func.max(RateLimitEvent.created_at).label("last_event")
        )
        .where(RateLimitEvent.created_at >= window_start)
        .group_by(RateLimitEvent.user_id, RateLimitEvent.ip_address)
    )
    rows = result.all()

    if not rows:
        return AnomaliesResponse(
            generated_at=datetime.utcnow(),
            window="last_24_hours",
            flagged_accounts=[]
        )

    # build feature vectors: [event_count, time_variance_minutes]
    features = []
    for row in rows:
        time_diff = (row.last_event - row.first_event).total_seconds() / 60
        features.append([row.event_count, time_diff])

    features_array = np.array(features)

    # use Isolation Forest when enough data, fallback to rules
    if len(rows) >= 10:
        model = IsolationForest(contamination=0.05, random_state=42)
        scores = model.fit_predict(features_array)
    else:
        # rule-based fallback: >20 events in <120 minutes
        scores = []
        for f in features:
            event_count, time_variance = f
            is_anomaly = event_count > 20 and time_variance < 120
            scores.append(-1 if is_anomaly else 1)

    # collect unique IPs per user for the response
    unique_ips_result = await db.execute(
        select(
            RateLimitEvent.user_id,
            func.count(func.distinct(RateLimitEvent.ip_address)).label("unique_ips")
        )
        .where(RateLimitEvent.created_at >= window_start)
        .group_by(RateLimitEvent.user_id)
    )
    unique_ips_map = {row.user_id: row.unique_ips for row in unique_ips_result.all()}

    # fetch emails for flagged users
    flagged_user_ids = [
        rows[i].user_id for i, score in enumerate(scores)
        if score == -1 and rows[i].user_id is not None
    ]

    email_map = {}
    if flagged_user_ids:
        users_result = await db.execute(
            select(User.id, User.email).where(User.id.in_(flagged_user_ids))
        )
        email_map = {row.id: row.email for row in users_result.all()}

    flagged = []
    for i, score in enumerate(scores):
        if score == -1:
            row = rows[i]
            time_variance = features[i][1]
            flagged.append(AnomalyEntry(
                user_id=row.user_id,
                email=email_map.get(row.user_id),
                event_count=row.event_count,
                unique_ips=unique_ips_map.get(row.user_id, 1),
                time_variance_minutes=round(time_variance, 2),
                anomaly_score=-1,
                first_event=row.first_event,
                last_event=row.last_event
            ))

    return AnomaliesResponse(
        generated_at=datetime.utcnow(),
        window="last_24_hours",
        flagged_accounts=flagged
    )