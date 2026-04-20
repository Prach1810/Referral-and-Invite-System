import secrets
import string


# Excludes visually ambiguous characters (0/O, 1/I) for friendlier manual entry.
_CODE_ALPHABET = "".join(
    c for c in (string.ascii_uppercase + string.digits) if c not in "O0I1"
)


def generate_referral_code(prefix: str = "FLIK", length: int = 6) -> str:
    """
    Generates a referral code like ``FLIK-XK9QRT``.

    Cryptographically random (``secrets``) so codes cannot be guessed from
    previously-issued ones. 32^6 ≈ 1 billion combinations keeps the
    collision-retry loop in signup effectively free.
    """
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    return f"{prefix}-{suffix}"