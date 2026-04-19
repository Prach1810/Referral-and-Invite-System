"""Inviter tier multipliers for referral conversion rewards (invitees unchanged)."""

INVITER_BASE_CREDITS = 50


def inviter_tier_multiplier(lifetime_converted_count: int) -> float:
    """
    lifetime_converted_count: inviter's total CONVERTED referrals after this event (1..N).

    1–5: base (1.0×), 6–10: 1.5×, 11+: 3×.
    """
    if lifetime_converted_count <= 5:
        return 1.0
    if lifetime_converted_count <= 10:
        return 1.5
    return 3.0


def inviter_reward_total_credits(lifetime_converted_count: int) -> int:
    """Total inviter credits for this conversion (base × tier), integer-rounded."""
    return int(round(INVITER_BASE_CREDITS * inviter_tier_multiplier(lifetime_converted_count)))
