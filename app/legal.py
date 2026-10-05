"""Versions and helpers shared by the legal pages, the cookie banner and the consent checkboxes."""
POLICY_VERSION = "2026-10-04"  # bump when a policy changes in a way users should re-read
LAST_UPDATED = "4 October 2026"
CONSENT_COOKIE = "chainbid_consent"
CONSENT_CHOICES = ("all", "essential")
CONSENT_MAX_AGE = 180 * 24 * 3600


def read_cookie_choice(cookies):
    """The visitor's saved cookie choice, or None if they have not chosen (or chose under an older policy version)."""
    version, _, choice = (cookies.get(CONSENT_COOKIE) or "").partition(":")
    return choice if version == POLICY_VERSION and choice in CONSENT_CHOICES else None
