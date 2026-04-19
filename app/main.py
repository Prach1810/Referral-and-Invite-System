from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.session import engine, Base
from app.api.routes import auth, users, referral_codes, invitations, referrals, posts, credits, dashboard, leaderboard, admin, badges


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create tables on startup (migrations handle this in prod, this is a fallback)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Flik Referral System",
    description="""
    ## Flik Referral & Invite System

    A production-scale referral system supporting:
    - **Referral codes** (permanent default + time-limited promo campaigns)
    - **Explicit email invites** with expiry tracking
    - **Passive link-based referrals** via shareable URLs
    - **Conversion tracking** triggered by first content creation
    - **Credits ledger** with idempotent reward processing via async RQ workers
    - **Leaderboard** with Redis caching
    - **Anomaly detection** using Isolation Forest on referral patterns
        """,
    version="1.0.0",
    lifespan=lifespan
)

# register routes
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(referral_codes.router)
app.include_router(invitations.router)
app.include_router(referrals.router)
app.include_router(posts.router)
app.include_router(credits.router)
app.include_router(dashboard.router)
app.include_router(leaderboard.router)
app.include_router(admin.router)
app.include_router(badges.router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}