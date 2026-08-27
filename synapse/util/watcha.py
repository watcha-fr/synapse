import secrets
import string
import unicodedata
from enum import Enum
from inspect import stack
from math import ceil, log2
from typing import Dict, Iterable, Optional


class Secrets:
    # https://fr.wikipedia.org/wiki/Ascii85#Version_ZeroMQ_(Z85)
    alphabet = string.ascii_letters + string.digits + ".-:+=^!/*?&<>()[]{}@%$#"
    min_entropy = 128

    def __init__(self, alphabet: str = None, min_entropy: int = None):
        if alphabet is not None:
            self.alphabet = unicodedata.normalize("NFKC", alphabet)

        if min_entropy is not None:
            self.min_entropy = min_entropy

    def gen_password(self) -> str:
        alphabet_length = len(self.alphabet)
        password_length = ceil(self.min_entropy / log2(alphabet_length))
        return "".join(secrets.choice(self.alphabet) for i in range(password_length))


# watcha+
def email_domain_matches(email_address: Optional[str], domains: Iterable[str]) -> bool:
    """Whether an email address belongs to one of `domains`, or to a subdomain.

    Used to decide whether a user invited as a partner actually belongs to the
    organisation and must therefore be registered as a full member. The check is
    deliberately anchored on the domain part: a plain substring test would let
    `someone@evil-universite-lyon.fr.example` through, and that grants
    membership.

    Args:
        email_address: the address to test. A missing or malformed address never
            matches.
        domains: the whitelisted domains. Comparison is case-insensitive.

    Returns:
        True if the address belongs to a whitelisted domain.
    """
    if not email_address or "@" not in email_address:
        return False

    domain = email_address.rpartition("@")[2].strip().lower().rstrip(".")
    if not domain:
        return False

    for whitelisted in domains or ():
        whitelisted = (whitelisted or "").strip().lower().lstrip("@").rstrip(".")
        if not whitelisted:
            continue
        if domain == whitelisted or domain.endswith("." + whitelisted):
            return True
    return False


# +watcha


class ActionStatus(Enum):
    """Enum to define the status of a logged action"""

    FAILED = "failed"
    SUCCESS = "success"


def build_log_message(
    action: str = None,
    status: ActionStatus = ActionStatus.FAILED,
    log_vars: Dict = None,
):
    """Build log message to correspond with Watcha format : "[prefix] <action to log> - <status of action> - <collection of variables to logs>"

    Args:
        action: action to log, if it not specified, correspond to caller function name
        status: status of the logged action
        log_vars:  collection of variables to log
    """

    def _get_action_from_caller_function():
        """Get human readable action name from caller function"""
        FUNCTION_NAME_INDEX = 3
        CALLER_FUNCTION_INDEX = 2  # correspond to grand mother function

        function_name = stack()[CALLER_FUNCTION_INDEX][FUNCTION_NAME_INDEX]
        action = " ".join(function_name.split("_")).strip()
        return action

    if action is None:
        action = _get_action_from_caller_function()

    message = f"[watcha] {action} - {status.value}"
    return message if log_vars is None else f"{message} {log_vars}"
