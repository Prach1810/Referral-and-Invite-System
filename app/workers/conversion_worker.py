import uuid
from sqlalchemy import create_engine, select, update, func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.redis import get_redis
from app.core.datetime_utils import utc_now_naive
from app.core.tier_rewards import INVITER_BASE_CREDITS, inviter_reward_total_credits
from app.core.outbound_mail import send_invite_email_sync
from app.models.models import (
    ConversionEvent,
    Referral,
    ReferralStatus,
    ReferralCode,
    CampaignType,
    CreditsLedger,
    CreditReason,
    User,
    Badge,
    UserBadge,
    BadgeType,
)

# RQ workers use sync SQLAlchemy
engine = create_engine(settings.SYNC_DATABASE_URL)
redis_client = get_redis()

INVITER_CREDITS = INVITER_BASE_CREDITS
INVITEE_CREDITS = 25


def _grant_referral_badges(session: Session, inviter_id: uuid.UUID, lifetime_count: int) -> None:
    """Insert earned REFERRAL badges where threshold <= lifetime_count (skip if already earned)."""
    badges = session.execute(
        select(Badge).where(
            Badge.badge_type == BadgeType.REFERRAL,
            Badge.threshold <= lifetime_count,
        )
    ).scalars().all()

    for badge in badges:
        already = session.execute(
            select(func.count())
            .select_from(UserBadge)
            .where(UserBadge.user_id == inviter_id, UserBadge.badge_id == badge.id)
        ).scalar_one()
        if int(already) == 0:
            session.add(UserBadge(user_id=inviter_id, badge_id=badge.id))


def process_conversion(conversion_event_id: str):
    """
    RQ job: processes a conversion event atomically.

    Idempotency guaranteed by the ``processed`` flag on ``ConversionEvent``.

    Reward rules:
    - Invitee always receives ``INVITEE_CREDITS`` (promo or personal code).
    - Inviter credits / badges only apply for **personal** (``DEFAULT``) codes.
      PROMO codes are owned by the admin who created them, so crediting the
      inviter there would pay the admin for every campaign signup.
    - Inviter credits use tier multipliers; the ledger records
      base ``REFERRAL_INVITER`` + ``BONUS_TIER`` delta for auditability.
    """
    with Session(engine) as session:
        with session.begin():
            event = session.execute(
                select(ConversionEvent)
                .where(ConversionEvent.id == uuid.UUID(conversion_event_id))
                .with_for_update()
            ).scalar_one_or_none()

            if not event:
                return

            if event.processed:
                return

            referral = session.execute(
                select(Referral).where(Referral.id == event.referral_id)
            ).scalar_one_or_none()

            if not referral:
                return

            campaign_type = session.execute(
                select(ReferralCode.campaign_type).where(
                    ReferralCode.id == referral.referral_code_id
                )
            ).scalar_one_or_none()
            is_promo = campaign_type == CampaignType.PROMO

            event.processed = True
            referral.status = ReferralStatus.CONVERTED
            referral.updated_at = utc_now_naive()
            session.flush()

            # Invitee always earns credits.
            session.add(
                CreditsLedger(
                    user_id=referral.invitee_id,
                    amount=INVITEE_CREDITS,
                    reason=CreditReason.REFERRAL_INVITEE,
                    reference_id=event.id,
                )
            )
            session.execute(
                update(User)
                .where(User.id == referral.invitee_id)
                .values(credits_balance=User.credits_balance + INVITEE_CREDITS)
            )

            # Skip inviter-side rewards for promo signups (see docstring).
            if is_promo:
                current_month = utc_now_naive().strftime("%Y-%m")
                redis_client.delete(f"leaderboard:{current_month}")
                return

            lifetime_count = session.execute(
                select(func.count())
                .select_from(Referral)
                .join(ReferralCode, ReferralCode.id == Referral.referral_code_id)
                .where(
                    Referral.inviter_id == referral.inviter_id,
                    Referral.status == ReferralStatus.CONVERTED,
                    ReferralCode.campaign_type == CampaignType.DEFAULT,
                )
            ).scalar_one()

            inviter_total = inviter_reward_total_credits(int(lifetime_count))
            bonus = inviter_total - INVITER_BASE_CREDITS

            session.add(
                CreditsLedger(
                    user_id=referral.inviter_id,
                    amount=INVITER_BASE_CREDITS,
                    reason=CreditReason.REFERRAL_INVITER,
                    reference_id=event.id,
                )
            )
            if bonus > 0:
                session.add(
                    CreditsLedger(
                        user_id=referral.inviter_id,
                        amount=bonus,
                        reason=CreditReason.BONUS_TIER,
                        reference_id=event.id,
                    )
                )

            session.execute(
                update(User)
                .where(User.id == referral.inviter_id)
                .values(
                    credits_balance=User.credits_balance + inviter_total,
                )
            )

            _grant_referral_badges(session, referral.inviter_id, int(lifetime_count))

        current_month = utc_now_naive().strftime("%Y-%m")
        redis_client.delete(f"leaderboard:{current_month}")


def send_invite_email(invitee_email: str, inviter_name: str, shareable_link: str):
    """
    RQ job: sends the invitation email (SendGrid, SMTP, or log-only if unconfigured).

    Configure either ``SENDGRID_API_KEY`` or ``SMTP_HOST`` plus ``MAIL_FROM_EMAIL``.
    Raises on delivery failure so the queue can retry.
    """
    send_invite_email_sync(invitee_email, inviter_name, shareable_link)
