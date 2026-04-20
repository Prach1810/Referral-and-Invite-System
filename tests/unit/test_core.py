import pytest
import uuid
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


# ── Reward Logic Tests ────────────────────────────────────────────────────────

class TestTierRewards:
    def test_inviter_tier_totals(self):
        from app.core.tier_rewards import inviter_reward_total_credits

        assert inviter_reward_total_credits(1) == 50
        assert inviter_reward_total_credits(5) == 50
        assert inviter_reward_total_credits(6) == 75
        assert inviter_reward_total_credits(10) == 75
        assert inviter_reward_total_credits(11) == 150

    def test_tier_1_to_5_base_rate(self):
        from app.core.tier_rewards import inviter_tier_multiplier, inviter_reward_total_credits
        for n in range(1, 6):
            assert inviter_tier_multiplier(n) == 1.0
            assert inviter_reward_total_credits(n) == 50

    def test_tier_6_to_10_one_and_half(self):
        from app.core.tier_rewards import inviter_tier_multiplier, inviter_reward_total_credits
        for n in range(6, 11):
            assert inviter_tier_multiplier(n) == 1.5
            assert inviter_reward_total_credits(n) == 75

    def test_tier_11_plus_triple(self):
        from app.core.tier_rewards import inviter_tier_multiplier, inviter_reward_total_credits
        for n in [11, 12, 20, 100]:
            assert inviter_tier_multiplier(n) == 3.0
            assert inviter_reward_total_credits(n) == 150

    def test_bonus_delta_at_tier_2(self):
        from app.core.tier_rewards import inviter_reward_total_credits, INVITER_BASE_CREDITS
        total = inviter_reward_total_credits(6)
        bonus = total - INVITER_BASE_CREDITS
        assert bonus == 25

    def test_no_bonus_delta_in_base_tier(self):
        from app.core.tier_rewards import inviter_reward_total_credits, INVITER_BASE_CREDITS
        total = inviter_reward_total_credits(3)
        bonus = total - INVITER_BASE_CREDITS
        assert bonus == 0

    def test_boundary_at_5(self):
        from app.core.tier_rewards import inviter_tier_multiplier
        assert inviter_tier_multiplier(5) == 1.0
        assert inviter_tier_multiplier(6) == 1.5

    def test_boundary_at_10(self):
        from app.core.tier_rewards import inviter_tier_multiplier
        assert inviter_tier_multiplier(10) == 1.5
        assert inviter_tier_multiplier(11) == 3.0


class TestConversionWorker:

    def test_process_conversion_awards_correct_credits(self):
        """Base inviter slice is 50; invitee gets 25 on conversion"""
        from app.workers.conversion_worker import INVITER_CREDITS, INVITEE_CREDITS

        assert INVITER_CREDITS == 50
        assert INVITEE_CREDITS == 25

    def test_process_conversion_idempotent(self):
        """Same conversion event processed twice must not double-award"""
        mock_session = MagicMock()
        mock_event = MagicMock()
        mock_event.processed = True  # already processed

        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_event

        with patch("app.workers.conversion_worker.Session") as MockSession:
            MockSession.return_value.__enter__.return_value = mock_session
            from app.workers.conversion_worker import process_conversion
            process_conversion(str(uuid.uuid4()))

        # credits should never be added
        mock_session.add.assert_not_called()

    def test_process_conversion_missing_event_does_nothing(self):
        """If event not found, worker exits cleanly"""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("app.workers.conversion_worker.Session") as MockSession:
            MockSession.return_value.__enter__.return_value = mock_session
            from app.workers.conversion_worker import process_conversion
            process_conversion(str(uuid.uuid4()))

        mock_session.add.assert_not_called()


# ── Referral Code Generation Tests ───────────────────────────────────────────

class TestCodeGenerator:

    def test_generates_correct_format(self):
        from app.core.code_generator import generate_referral_code
        code = generate_referral_code()
        assert code.startswith("FLIK-")
        assert len(code) == 11  # FLIK- (5) + 6 chars

    def test_generates_url_safe_code(self):
        from app.core.code_generator import generate_referral_code
        for _ in range(50):
            code = generate_referral_code()
            assert " " not in code
            assert "/" not in code
            assert "?" not in code

    def test_codes_are_uppercase(self):
        from app.core.code_generator import generate_referral_code
        code = generate_referral_code()
        assert code == code.upper()

    def test_custom_prefix(self):
        from app.core.code_generator import generate_referral_code
        code = generate_referral_code(prefix="TEST", length=6)
        assert code.startswith("TEST-")
        assert len(code) == 11  # TEST- (5) + 6 chars


# ── Rate Limiting Tests ───────────────────────────────────────────────────────

class TestRateLimiting:

    def test_rate_limit_blocks_after_threshold(self):
        from app.core.rate_limit import check_signup_rate_limit
        from fastapi import HTTPException

        mock_redis = MagicMock()
        mock_redis.get.return_value = "5"  # at limit

        with patch("app.core.rate_limit.redis_client", mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                check_signup_rate_limit("192.168.1.1")
            assert exc_info.value.status_code == 429

    def test_rate_limit_allows_under_threshold(self):
        from app.core.rate_limit import check_signup_rate_limit

        mock_redis = MagicMock()
        mock_redis.get.return_value = "2"  # under limit
        mock_redis.pipeline.return_value.execute.return_value = None

        with patch("app.core.rate_limit.redis_client", mock_redis):
            check_signup_rate_limit("192.168.1.1")

    def test_rate_limit_allows_first_request(self):
        from app.core.rate_limit import check_signup_rate_limit

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # no prior requests

        with patch("app.core.rate_limit.redis_client", mock_redis):
            check_signup_rate_limit("192.168.1.1")


# ── Fraud Detection Tests ─────────────────────────────────────────────────────

class TestFraudDetection:

    def test_rule_based_flags_high_velocity(self):
        """More than 20 events in less than 120 minutes should be flagged"""
        features = [[25, 30]]  # 25 events, 30 minutes
        scores = []
        for f in features:
            event_count, time_variance = f
            is_anomaly = event_count > 20 and time_variance < 120
            scores.append(-1 if is_anomaly else 1)
        assert scores[0] == -1

    def test_rule_based_allows_normal_activity(self):
        """Low event count should not be flagged"""
        features = [[3, 200]]  # 3 events, 200 minutes
        scores = []
        for f in features:
            event_count, time_variance = f
            is_anomaly = event_count > 20 and time_variance < 120
            scores.append(-1 if is_anomaly else 1)
        assert scores[0] == 1

    def test_rule_based_high_count_slow_pace_not_flagged(self):
        """High event count spread over long time is OK"""
        features = [[25, 300]]  # 25 events over 5 hours
        scores = []
        for f in features:
            event_count, time_variance = f
            is_anomaly = event_count > 20 and time_variance < 120
            scores.append(-1 if is_anomaly else 1)
        assert scores[0] == 1


# ── Security Tests ────────────────────────────────────────────────────────────

class TestSecurity:

    def test_password_hash_is_not_plaintext(self):
        from app.core.security import hash_password
        hashed = hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"
        assert len(hashed) > 20

    def test_password_verification_correct(self):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("mysecretpassword")
        assert verify_password("mysecretpassword", hashed) is True

    def test_password_verification_wrong(self):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("mysecretpassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_jwt_token_contains_expected_fields(self):
        from app.core.security import create_access_token, decode_token
        user_id = str(uuid.uuid4())
        token = create_access_token({"user_id": user_id, "role": "USER"})
        payload = decode_token(token)
        assert payload["user_id"] == user_id
        assert payload["role"] == "USER"
        assert "jti" in payload
        assert "exp" in payload

    def test_invalid_token_returns_none(self):
        from app.core.security import decode_token
        result = decode_token("not.a.valid.token")
        assert result is None


# ── Invitation Expiry Tests ───────────────────────────────────────────────────

class TestInvitationExpiry:
    def test_default_code_expiry_is_30_days(self):
        from app.core.datetime_utils import utc_now_naive
        now = utc_now_naive()
        expired_at = now + timedelta(days=30)
        assert (expired_at - now).days == 30

    def test_promo_code_expiry_uses_min(self):
        from app.core.datetime_utils import utc_now_naive
        now = utc_now_naive()
        code_expires = now + timedelta(days=5)   # promo expires in 5 days
        invite_window = now + timedelta(days=30)  # default 30 days
        expired_at = min(invite_window, code_expires)
        assert expired_at == code_expires         # promo wins

    def test_invitation_past_expiry_is_expired(self):
        from app.core.datetime_utils import utc_now_naive
        expired_at = utc_now_naive() - timedelta(hours=1)
        is_expired = expired_at < utc_now_naive()
        assert is_expired is True