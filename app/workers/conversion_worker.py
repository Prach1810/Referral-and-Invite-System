import uuid
from datetime import datetime
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.redis import get_redis
from app.models.models import (
    ConversionEvent, Referral, ReferralStatus,
    CreditsLedger, CreditReason, User
)

# RQ workers use sync SQLAlchemy
engine = create_engine(settings.SYNC_DATABASE_URL)
redis_client = get_redis()

INVITER_CREDITS = 50
INVITEE_CREDITS = 25


def process_conversion(conversion_event_id: str):
    """
    RQ job: processes a conversion event atomically.
    Idempotency guaranteed by processed flag.
    """
    with Session(engine) as session:
        with session.begin():
            # fetch event and lock row
            event = session.execute(
                select(ConversionEvent)
                .where(ConversionEvent.id == uuid.UUID(conversion_event_id))
                .with_for_update()
            ).scalar_one_or_none()

            if not event:
                return

            # idempotency check
            if event.processed:
                return

            referral = session.execute(
                select(Referral).where(Referral.id == event.referral_id)
            ).scalar_one_or_none()

            if not referral:
                return

            # mark event processed
            event.processed = True

            # update referral status
            referral.status = ReferralStatus.CONVERTED
            referral.updated_at = datetime.utcnow()

            # award inviter credits
            session.add(CreditsLedger(
                user_id=referral.inviter_id,
                amount=INVITER_CREDITS,
                reason=CreditReason.REFERRAL_INVITER,
                reference_id=event.id
            ))

            # award invitee credits
            session.add(CreditsLedger(
                user_id=referral.invitee_id,
                amount=INVITEE_CREDITS,
                reason=CreditReason.REFERRAL_INVITEE,
                reference_id=event.id
            ))

            # update cached balances
            session.execute(
                update(User)
                .where(User.id == referral.inviter_id)
                .values(credits_balance=User.credits_balance + INVITER_CREDITS)
            )
            session.execute(
                update(User)
                .where(User.id == referral.invitee_id)
                .values(credits_balance=User.credits_balance + INVITEE_CREDITS)
            )

        # invalidate leaderboard cache outside transaction
        current_month = datetime.utcnow().strftime("%Y-%m")
        redis_client.delete(f"leaderboard:{current_month}")


def send_invite_email(invitee_email: str, inviter_name: str, shareable_link: str):
    """
    RQ job: sends invite email.
    In production, integrate with SendGrid/SES/etc.
    """
    print(f"[EMAIL] Sending invite to {invitee_email} from {inviter_name}: {shareable_link}")
    # TODO: integrate real email provider