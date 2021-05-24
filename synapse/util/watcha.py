from math import ceil, log2
import secrets
import string
import unicodedata


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
