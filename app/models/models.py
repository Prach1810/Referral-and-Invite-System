import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey,
    Enum as SAEnum, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.session import Base
import enum


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class CampaignType(str, enum.Enum):
    DEFAULT = "DEFAULT"
    PROMO = "PROMO"


class InvitationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SIGNED_UP = "SIGNED_UP"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, enum.Enum):
    CONVERTED = "CONVERTED"
    NOT_CONVERTED = "NOT_CONVERTED"


class ReferralSource(str, enum.Enum):
    INVITE = "INVITE"
    LINK = "LINK"


class SignupSource(str, enum.Enum):
    WEB = "WEB"
    MOBILE = "MOBILE"
    API = "API"


class CreditReason(str, enum.Enum):
    REFERRAL_INVITER = "REFERRAL_INVITER"
    REFERRAL_INVITEE = "REFERRAL_INVITEE"
    BONUS_TIER = "BONUS_TIER"
    ADJUSTMENT = "ADJUSTMENT"


class RateLimitAction(str, enum.Enum):
    SIGNUP = "SIGNUP"
    CODE_REDEMPTION = "CODE_REDEMPTION"


class BadgeType(str, enum.Enum):
    REFERRAL = "REFERRAL"
    STREAK = "STREAK"
    ENGAGEMENT = "ENGAGEMENT"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    referred_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    credits_balance = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    referral_codes = relationship("ReferralCode", back_populates="owner", foreign_keys="ReferralCode.owner_id")
    sent_invitations = relationship("Invitation", back_populates="inviter", foreign_keys="Invitation.inviter_id")
    posts = relationship("Post", back_populates="author")
    earned_badges = relationship("UserBadge", back_populates="user", foreign_keys="UserBadge.user_id")


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, unique=True, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=True)
    uses_count = Column(Integer, default=0, nullable=False)
    campaign_type = Column(SAEnum(CampaignType), default=CampaignType.DEFAULT, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="referral_codes", foreign_keys=[owner_id])
    invitations = relationship("Invitation", back_populates="referral_code")
    referrals = relationship("Referral", back_populates="referral_code")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_code_id = Column(UUID(as_uuid=True), ForeignKey("referral_codes.id"), nullable=False)
    inviter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    invitee_email = Column(String, nullable=False)
    invitee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(SAEnum(InvitationStatus), default=InvitationStatus.PENDING, nullable=False)
    signup_source = Column(SAEnum(SignupSource), nullable=True)
    expired_at = Column(DateTime, nullable=False)
    invited_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    signed_up_at = Column(DateTime, nullable=True)

    inviter = relationship("User", back_populates="sent_invitations", foreign_keys=[inviter_id])
    invitee = relationship("User", foreign_keys=[invitee_id])
    referral_code = relationship("ReferralCode", back_populates="invitations")
    referral = relationship("Referral", back_populates="invitation", uselist=False)


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_code_id = Column(UUID(as_uuid=True), ForeignKey("referral_codes.id"), nullable=False)
    inviter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    invitee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    invitation_id = Column(UUID(as_uuid=True), ForeignKey("invitations.id"), nullable=True)
    source = Column(SAEnum(ReferralSource), nullable=False)
    status = Column(SAEnum(ReferralStatus), default=ReferralStatus.NOT_CONVERTED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    referral_code = relationship("ReferralCode", back_populates="referrals")
    inviter = relationship("User", foreign_keys=[inviter_id])
    invitee = relationship("User", foreign_keys=[invitee_id])
    invitation = relationship("Invitation", back_populates="referral")
    conversion_events = relationship("ConversionEvent", back_populates="referral")


class ConversionEvent(Base):
    __tablename__ = "conversion_events"
    __table_args__ = (
        UniqueConstraint("referral_id", name="uq_conversion_events_referral"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_id = Column(UUID(as_uuid=True), ForeignKey("referrals.id"), nullable=False)
    invitee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    event_type = Column(String, nullable=False, default="FIRST_CONTENT_GENERATED")
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    referral = relationship("Referral", back_populates="conversion_events")
    invitee = relationship("User", foreign_keys=[invitee_id])


class CreditsLedger(Base):
    __tablename__ = "credits_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(SAEnum(CreditReason), nullable=False)
    reference_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    ip_address = Column(String, nullable=False)
    action = Column(SAEnum(RateLimitAction), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Post(Base):
    __tablename__ = "posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    author = relationship("User", back_populates="posts")


class Badge(Base):
    __tablename__ = "badges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    badge_type = Column(SAEnum(BadgeType), nullable=False)
    badge_name = Column(String(128), nullable=False)
    description = Column(String(512), nullable=False)
    threshold = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user_badges = relationship("UserBadge", back_populates="badge")


class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badges_user_badge"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    badge_id = Column(UUID(as_uuid=True), ForeignKey("badges.id", ondelete="CASCADE"), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="earned_badges", foreign_keys=[user_id])
    badge = relationship("Badge", back_populates="user_badges")