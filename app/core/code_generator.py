import random
import string


def generate_referral_code(prefix: str = "FLIK", length: int = 4) -> str:
    """
    Generates a referral code like FLIK-XK92
    URL-safe, alphanumeric, uppercase
    """
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=length))
    return f"{prefix}-{suffix}"