"""
Anomaly Detection Demo
======================
Seeds realistic rate limit event patterns to demonstrate the Isolation Forest
and rule-based anomaly detection at GET /admin/anomalies.

Usage:
    docker-compose exec web python scripts/demo_anomalies.py

What it creates:
    - 1 suspicious account: 25 SIGNUP events from the same IP in under 60 minutes
    - 1 normal account: 3 SIGNUP events spread over 5 hours
    - Prints what GET /admin/anomalies should return after seeding

After running:
    1. Login as admin@flik.com at http://localhost:8000/docs
    2. Hit GET /admin/anomalies
    3. The suspicious account should appear in flagged_accounts
"""
import asyncio
import sys
import os
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text
from app.core.config import settings
from app.models.models import User, RateLimitEvent, RateLimitAction

engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

SUSPICIOUS_IP = "10.0.1.99"
NORMAL_IP = "10.0.2.55"
EVENT_COUNT_SUSPICIOUS = 25   # triggers rule: > 20 events in < 120 minutes
EVENT_COUNT_NORMAL = 3


async def seed():
    async with AsyncSessionLocal() as db:

        # get alice as the suspicious user (already exists from main test flow)
        result = await db.execute(select(User).where(User.email == "alice@test.com"))
        alice = result.scalar_one_or_none()

        result2 = await db.execute(select(User).where(User.email == "bob@test.com"))
        bob = result2.scalar_one_or_none()

        if not alice or not bob:
            print("ERROR: Run the main test flow first (register alice + bob)")
            return

        now = datetime.utcnow()

        # ── suspicious pattern: 25 signups from same IP in 60 minutes ─────────
        print(f"Seeding {EVENT_COUNT_SUSPICIOUS} suspicious SIGNUP events from {SUSPICIOUS_IP}...")
        for i in range(EVENT_COUNT_SUSPICIOUS):
            offset_minutes = random.uniform(0, 60)
            db.add(RateLimitEvent(
                user_id=alice.id,
                ip_address=SUSPICIOUS_IP,
                action=RateLimitAction.SIGNUP,
                created_at=now - timedelta(minutes=offset_minutes)
            ))

        # ── normal pattern: 3 signups from different IP spread over 5 hours ───
        print(f"Seeding {EVENT_COUNT_NORMAL} normal SIGNUP events from {NORMAL_IP}...")
        for i in range(EVENT_COUNT_NORMAL):
            offset_hours = i * 2.5
            db.add(RateLimitEvent(
                user_id=bob.id,
                ip_address=NORMAL_IP,
                action=RateLimitAction.SIGNUP,
                created_at=now - timedelta(hours=offset_hours)
            ))

        await db.commit()

        print("\nDone! Summary:")
        print(f"  Suspicious: user=alice@test.com, ip={SUSPICIOUS_IP}, events={EVENT_COUNT_SUSPICIOUS}, window=~60min")
        print(f"  Normal:     user=bob@test.com,   ip={NORMAL_IP}, events={EVENT_COUNT_NORMAL}, window=~5hrs")
        print("\nExpected anomaly detection:")
        print(f"  alice@test.com ({SUSPICIOUS_IP}) → FLAGGED  (event_count={EVENT_COUNT_SUSPICIOUS}, time_variance<120min)")
        print(f"  bob@test.com   ({NORMAL_IP}) → CLEAN   (event_count={EVENT_COUNT_NORMAL}, spread over hours)")
        print("\nNow hit GET /admin/anomalies in Swagger to see the result.")


asyncio.run(seed())