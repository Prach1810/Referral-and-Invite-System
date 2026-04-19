from fastapi import HTTPException, status
from app.core.redis import get_redis

redis_client = get_redis()

RATE_LIMITS = {
    "signup": {"limit": 5, "window": 3600},
    "code_redemption": {"limit": 10, "window": 3600},
}


def _check_and_increment(redis_key: str, limit: int, window_seconds: int) -> None:
    current = redis_client.get(redis_key)
    if current and int(current) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )
    pipe = redis_client.pipeline()
    pipe.incr(redis_key)
    pipe.expire(redis_key, window_seconds)
    pipe.execute()


def check_signup_rate_limit(ip: str) -> None:
    """Keys: rate_limit:{ip}:signup — max 5 signups per IP per hour."""
    cfg = RATE_LIMITS["signup"]
    _check_and_increment(f"rate_limit:{ip}:signup", cfg["limit"], cfg["window"])


def check_code_redemption_rate_limit(ip: str, referral_code: str) -> None:
    """Keys: rate_limit:{ip}:code:{referral_code} — max 10 per code per IP per hour."""
    cfg = RATE_LIMITS["code_redemption"]
    _check_and_increment(
        f"rate_limit:{ip}:code:{referral_code}",
        cfg["limit"],
        cfg["window"],
    )
