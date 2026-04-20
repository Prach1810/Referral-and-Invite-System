import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import timedelta
from sklearn.ensemble import IsolationForest
from app.core.datetime_utils import utc_now_naive
from app.db.session import get_db
from app.core.dependencies import get_admin_user
from app.models.models import User, RateLimitEvent, RateLimitAction
from app.schemas.schemas import AnomaliesResponse, AnomalyEntry

router = APIRouter(prefix="/admin", tags=["Admin"])


def _normalize_risk_scores(raw_values: list[float]) -> list[int]:
    """
    Convert raw anomaly severity values to a 0-100 risk scale.
    Higher means more suspicious.
    """
    if not raw_values:
        return []
    min_v = min(raw_values)
    max_v = max(raw_values)
    if max_v == min_v:
        return [50 for _ in raw_values]
    return [int(round(((v - min_v) / (max_v - min_v)) * 100)) for v in raw_values]


@router.get("/anomalies", response_model=AnomaliesResponse)
async def get_anomalies(
    current_user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    window_start = utc_now_naive() - timedelta(hours=24)

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
            generated_at=utc_now_naive(),
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
        # decision_function: higher is more normal; negate for anomaly severity.
        raw_risk = (-model.decision_function(features_array)).tolist()
        risk_scores = _normalize_risk_scores(raw_risk)
    else:
        # rule-based fallback: >20 events in <120 minutes
        scores = []
        raw_risk = []
        for f in features:
            event_count, time_variance = f
            is_anomaly = event_count > 20 and time_variance < 120
            scores.append(-1 if is_anomaly else 1)
            # Rule severity:
            # - event_count overflow above 20 contributes up to 70 points
            # - faster time window (<120m) contributes up to 30 points
            count_component = min(max((event_count - 20) * 7, 0), 70)
            time_component = min(max((120 - time_variance) / 120 * 30, 0), 30)
            raw_risk.append(float(count_component + time_component))
        risk_scores = _normalize_risk_scores(raw_risk)

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
                risk_score=risk_scores[i],
                first_event=row.first_event,
                last_event=row.last_event
            ))

    return AnomaliesResponse(
        generated_at=utc_now_naive(),
        window="last_24_hours",
        flagged_accounts=flagged
    )