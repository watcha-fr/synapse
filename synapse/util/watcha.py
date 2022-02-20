import os
import sys
import unicodedata
import secrets as crypto

import pkg_resources


class Secrets:
    def __init__(self, word_list_filename):
        self.word_list_filename = word_list_filename

    def _get_words(self):
        word_list_dir = pkg_resources.resource_filename(
            "synapse", "res/watcha_word_lists"
        )
        word_list_path = os.path.join(word_list_dir, self.word_list_filename)
        with open(word_list_path) as f:
            return [word.strip() for word in f]

    def passphrase(self, nwords=4):
        words = self._get_words()
        passphrase = " ".join(crypto.choice(words) for i in range(nwords))
        return unicodedata.normalize("NFKC", passphrase)
