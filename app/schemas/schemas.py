from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from app.models.models import (
    UserRole, CampaignType, InvitationStatus,
    ReferralStatus, ReferralSource, SignupSource, CreditReason, BadgeType,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    password: str
    phone: Optional[str] = None
    referral_code: Optional[str] = None
    # String (not enum) so we can return 400 for invalid values; enum-only body yields 422 from FastAPI.
    signup_source: str = Field(default="WEB", description="One of: WEB, MOBILE, API")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    user_id: UUID
    role: UserRole


class RegisterResponse(BaseModel):
    user_id: UUID
    first_name: str
    last_name: str
    referral_code: str
    referred_by: Optional[UUID]
    access_token: str


# ── Users ─────────────────────────────────────────────────────────────────────

class UserProfileResponse(BaseModel):
    user_id: UUID
    email: str
    first_name: str
    last_name: str
    phone: Optional[str]
    referral_code: str
    credits_balance: int
    referred_by: Optional[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateUserRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None


class UpdateUserResponse(BaseModel):
    user_id: UUID
    first_name: str
    last_name: str
    phone: Optional[str]
    updated_at: datetime


# ── Referral Codes ────────────────────────────────────────────────────────────

class ReferralCodeResponse(BaseModel):
    id: UUID
    code: str
    campaign_type: CampaignType
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    uses_count: int
    created_at: datetime
    shareable_link: str

    class Config:
        from_attributes = True


class MyReferralCodesResponse(BaseModel):
    codes: List[ReferralCodeResponse]


class CreatePromoCodeRequest(BaseModel):
    code: str
    expires_at: datetime
    max_uses: Optional[int] = None

    @field_validator("code")
    @classmethod
    def code_alphanumeric(cls, v):
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Code must be alphanumeric")
        return v.upper()


# ── Invitations ───────────────────────────────────────────────────────────────

class CreateInvitationRequest(BaseModel):
    invitee_email: EmailStr


class InvitationResponse(BaseModel):
    invitation_id: UUID
    invitee_email: str
    status: InvitationStatus
    expired_at: datetime
    shareable_link: str

    class Config:
        from_attributes = True


class InvitationDetailResponse(BaseModel):
    invitation_id: UUID
    invitee_email: str
    status: InvitationStatus
    invited_at: datetime
    expired_at: datetime
    signed_up_at: Optional[datetime]

    class Config:
        from_attributes = True


class MyInvitationsResponse(BaseModel):
    total: int
    invitations: List[InvitationDetailResponse]


# ── Referrals ─────────────────────────────────────────────────────────────────

class ReferralsBySourceResponse(BaseModel):
    invite: int
    link: int


class MyReferralsResponse(BaseModel):
    total: int
    by_source: ReferralsBySourceResponse
    converted: int
    not_converted: int


# ── Posts ─────────────────────────────────────────────────────────────────────

class CreatePostRequest(BaseModel):
    content: str


class PostResponse(BaseModel):
    post_id: UUID
    author_id: UUID
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Credits ───────────────────────────────────────────────────────────────────

class CreditEntryResponse(BaseModel):
    amount: int
    reason: CreditReason
    reference_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class MyCreditsResponse(BaseModel):
    credits_balance: int
    history: List[CreditEntryResponse]


# ── Dashboard ─────────────────────────────────────────────────────────────────

class EarnedBadgeEntry(BaseModel):
    badge_id: UUID
    badge_type: BadgeType
    badge_name: str
    description: str
    earned_at: datetime


class DashboardResponse(BaseModel):
    total_invites_sent: int
    pending_referrals: int
    total_converted: int
    current_multiplier: float
    credits_balance: int
    earned_badges: List[EarnedBadgeEntry]


# ── Leaderboard ───────────────────────────────────────────────────────────────

class LeaderboardEntry(BaseModel):
    rank: int
    user_id: UUID
    first_name: str
    last_name: str
    conversions: int


class LeaderboardResponse(BaseModel):
    month: str
    leaderboard: List[LeaderboardEntry]


# ── Admin ─────────────────────────────────────────────────────────────────────

class AnomalyEntry(BaseModel):
    user_id: Optional[UUID]
    email: Optional[str]
    event_count: int
    unique_ips: int
    time_variance_minutes: float
    anomaly_score: int
    risk_score: int
    first_event: datetime
    last_event: datetime


class AnomaliesResponse(BaseModel):
    generated_at: datetime
    window: str
    flagged_accounts: List[AnomalyEntry]