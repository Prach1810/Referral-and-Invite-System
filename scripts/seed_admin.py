"""
Run this once after docker-compose up to create the first admin user.
Usage: docker-compose exec web python scripts/seed_admin.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.core.config import settings
from app.core.security import hash_password
from app.core.code_generator import generate_referral_code
from app.models.models import User, ReferralCode, UserRole, CampaignType

engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

ADMIN_EMAIL = "admin@flik.com"
ADMIN_PASSWORD = "admin123"
ADMIN_FIRST = "Flik"
ADMIN_LAST = "Admin"


async def seed():
    async with AsyncSessionLocal() as db:
        # check if admin already exists
        existing = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if existing.scalar_one_or_none():
            print(f"Admin already exists: {ADMIN_EMAIL}")
            return

        # create admin user
        admin = User(
            email=ADMIN_EMAIL,
            first_name=ADMIN_FIRST,
            last_name=ADMIN_LAST,
            password_hash=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
        )
        db.add(admin)
        await db.flush()

        # generate default referral code for admin
        for _ in range(5):
            candidate = generate_referral_code()
            exists = await db.execute(
                select(ReferralCode).where(ReferralCode.code == candidate)
            )
            if not exists.scalar_one_or_none():
                break

        code = ReferralCode(
            code=candidate,
            owner_id=admin.id,
            campaign_type=CampaignType.DEFAULT,
        )
        db.add(code)
        await db.commit()

        print(f"Admin created successfully!")
        print(f"  Email:    {ADMIN_EMAIL}")
        print(f"  Password: {ADMIN_PASSWORD}")
        print(f"  Code:     {candidate}")


asyncio.run(seed())