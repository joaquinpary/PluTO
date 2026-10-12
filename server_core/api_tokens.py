"""The per-instance token a plugin container uses against /api/.

One token per launch: the orchestrator hands the plain value to the container
and the row keeps only its sha256, so the token decides which instance a
request speaks for, the way the topic did over MQTT.

sha256 rather than Django's password hashers on purpose. Those are slow by
design, to resist guessing a human password; a token is 256 random bits, so
there is nothing to guess, and a fast unsalted hash lets every plugin request
find its row through an index instead of paying a key derivation each time.
"""
import hashlib
import secrets

# Makes a leaked token recognizable in a log, a paste or a secret scanner.
TOKEN_PREFIX = 'pluto_'


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def issue_token():
    """A fresh token and the hash to store for it."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)
