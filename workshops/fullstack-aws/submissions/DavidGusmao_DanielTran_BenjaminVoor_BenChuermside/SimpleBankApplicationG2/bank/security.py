"""Password hashing and JSON Web Tokens. Standard library only.

Two jobs, both of which are easy to get dangerously wrong, so both live in one
small file that can be read end to end in a minute.

    hash_password / verify_password   -> storing a password safely
    issue_token / read_token          -> proving who you are on the next request

WHY PBKDF2 AND NOT bcrypt
-------------------------
The build plan says bcrypt or argon2 through a library, and that is still the
right answer for production. Neither is in the Python standard library, and this
submission has a hard "nothing to pip install" constraint, so this file uses
`hashlib.pbkdf2_hmac`, which *is* in the standard library and *is* a real
password-based key derivation function: salted, and deliberately slow.

What matters is that the shape is identical. `hash_password` returns one opaque
string and `verify_password` takes that string back, so swapping in bcrypt later
means rewriting the bodies of two functions and nothing else. The one thing that
is never acceptable, in any of these variants, is a bare SHA-256 of the password:
a plain hash is fast, and fast is exactly the property an attacker wants.

WHAT A JWT IS, IN THREE PARTS
-----------------------------
A token is `header.payload.signature`, each part base64url text:

    header     {"alg":"HS256","typ":"JWT"}       which algorithm signed it
    payload    {"sub":7,"username":...,"role":...,"exp":...}   the claims
    signature  HMAC-SHA256(secret, "header.payload")

The first thing to be clear about is that base64url is ENCODING, NOT ENCRYPTION.
Anyone holding the token can decode the payload and read every claim, with no key
involved. A JWT keeps nothing secret, so nothing sensitive ever goes in one.

What it gives you instead is integrity. The signature is computed with a secret
only the server has, and HMAC is one-way: seeing outputs reveals nothing about
the key. That creates the asymmetry the whole scheme rests on - ANYBODY CAN READ
the claims, ONLY THE SERVER CAN WRITE them. A customer who decodes their token,
edits "role":"CUSTOMER" to "ADMIN" and re-encodes it cannot produce a matching
signature, so `read_token` rejects it.

WHY HAND-ROLLED AND NOT PyJWT
-----------------------------
Same reason as PBKDF2 above: PyJWT is a third-party package and this submission
installs nothing. The format below is a real JWT - three parts, HS256, standard
`sub`/`iat`/`exp` claim names - so a token from here pastes into jwt.io and
decodes, and swapping in PyJWT later means deleting two functions.

THREE MISTAKES THIS FILE DELIBERATELY AVOIDS
--------------------------------------------
1. Verifying the signature BEFORE parsing the payload. Reading `exp` from an
   unverified token means trusting a number the attacker chose.
2. `hmac.compare_digest`, never `==`. A normal comparison returns as soon as two
   bytes differ, so how long it takes leaks how much of a forgery was right.
3. Pinning the algorithm instead of believing the header. The classic JWT break
   is `{"alg":"none"}` - a token declaring itself unsigned, which libraries used
   to accept. `read_token` only ever computes HS256 and refuses any header that
   claims otherwise.

THE ONE THING A JWT CANNOT DO
-----------------------------
Be revoked. The server signs a token and then forgets it, so there is no record
to delete: it is valid until it expires, whatever happens to the user meanwhile.
The mitigation here is that `api._authenticate` re-reads the User from storage
and authorizes on the STORED role, never on the `role` claim - so a demoted admin
loses their powers on the very next request even though their token still says
ADMIN. The claim is there for the client's convenience; the database is the
authority. See README section 13.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time

# Cost factor. Higher is slower, and slow is the entire point: it is what makes
# guessing a stolen hash expensive. This is roughly the OWASP floor for
# PBKDF2-HMAC-SHA256. Raising it later is safe, because the round count is stored
# inside each hash, so existing hashes keep verifying with the number they were
# created with.
PBKDF2_ROUNDS = 600_000
SALT_BYTES = 16

# One week. Long for a bank, and a demo decision rather than a security one: an
# hour meant a token saved in Postman, or a tab left open over a weekend, came
# back 401 in the middle of showing something.
#
# Be clear about what it costs, because a JWT cannot be cancelled: a token that
# leaks is usable for a week, and there is no way to end it early short of
# changing BANK_SECRET, which logs out every user at once. That is acceptable for
# a graded project with a seeded roster and would not be for real money. Shorten
# this one constant to change it.
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

# The only algorithm this file will sign or accept. Pinned as a constant rather
# than read from a token's own header - see mistake 3 in the module docstring.
ALGORITHM = "HS256"
JWT_HEADER = {"alg": ALGORITHM, "typ": "JWT"}


# --------------------------------------------------------------------- helpers

def _b64encode(raw: bytes) -> str:
    """base64url with the `=` padding stripped, so the result is URL and header safe."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    """Inverse of `_b64encode`. Puts back however much padding was removed."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _json(obj: dict) -> bytes:
    """Compact JSON bytes for a JWT part.

    No spaces, because the signature covers the encoded text: two encodings of
    the same dict that differ by a space are different strings and produce
    different signatures.
    """
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------- passwords

def hash_password(password: str, rounds: int = PBKDF2_ROUNDS) -> str:
    """Derive a storable representation of a password.

    Returns a single self-describing string:

        pbkdf2_sha256$600000$<salt-b64>$<derived-key-b64>

    Everything needed to verify a later guess is in that string, including the
    round count and the salt. That is why no other column is needed, and why the
    cost factor can be raised without invalidating existing users.

    The salt is fresh random bytes per user. Two people who choose the same
    password get different stored values, which is what stops one cracked hash
    from unlocking every account that shares that password.
    """
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be a string of at least 8 characters")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Check a guess against a stored hash. Never raises; returns True or False.

    `encoded` is allowed to be None, which is the case for a user created without
    a password. That user simply cannot log in, and this returns False rather
    than crashing the login route.
    """
    if not encoded or not isinstance(password, str):
        return False
    try:
        algorithm, rounds, salt_b64, expected_b64 = encoded.split("$")
    except ValueError:
        return False  # malformed stored value; treat as "does not verify"
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(salt_b64), int(rounds)
        )
        expected = _b64decode(expected_b64)
    except (ValueError, binascii.Error):
        return False
    # Constant-time comparison. See the module docstring.
    return hmac.compare_digest(derived, expected)


# ---------------------------------------------------------------------- tokens

def new_secret() -> str:
    """The server's signing key. Everything above rests on this staying secret.

    Read from BANK_SECRET when it is set, otherwise a fresh random value per
    process. The random default is the safe one for a demo - no secret is ever
    committed - but it means restarting the server invalidates every token that
    was ever issued, which is worth knowing before you wonder why a saved Postman
    token started answering 401. Set BANK_SECRET in .env to keep logins working
    across restarts.

    If this value ever leaks, an attacker can mint a token for any user with any
    role, and nothing in the logs would show it. Changing it is the only way to
    revoke anything, and it revokes everything at once.
    """
    return os.environ.get("BANK_SECRET") or secrets.token_urlsafe(32)


def _sign(signing_input: str, secret: str) -> bytes:
    """HMAC-SHA256 over the exact bytes that travel as `header.payload`.

    One function, used by both `issue_token` and `read_token`, so the thing that
    is signed and the thing that is verified cannot drift apart. If these were
    two expressions, a change to one would silently invalidate every token.
    """
    return hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"),
                    hashlib.sha256).digest()


def issue_token(user_id: int, username: str, role: str, secret: str,
                name: str | None = None, ttl: int = TOKEN_TTL_SECONDS) -> str:
    """Mint a signed JWT for a user who has just proved who they are.

    The claims, and why each one is here:

        sub       the user id. The subject - who this token is about, and the
                  only claim anything is actually looked up by.
        username  the email, because that is what this app logs in with.
        name      the display name, so a client can greet somebody without a
                  second request. Omitted if not supplied.
        role      CUSTOMER or ADMIN. Carried for the client's convenience and
                  NEVER used for authorization - see the module docstring.
        iat       issued at. Not checked by anything; it makes a token
                  self-describing when you are staring at one in a debugger.
        exp       absolute expiry, as a Unix timestamp. The one claim that can
                  make an otherwise valid token useless.

    All of it is readable by anyone holding the token. That is fine - a user id,
    an email and a role are not secrets to the person they belong to - but it is
    the reason nothing else may be added here without asking whether the holder
    is entitled to read it.
    """
    now = int(time.time())
    payload = {"sub": user_id, "username": username, "role": role,
               "iat": now, "exp": now + ttl}
    if name is not None:
        payload["name"] = name
    signing_input = f"{_b64encode(_json(JWT_HEADER))}.{_b64encode(_json(payload))}"
    return f"{signing_input}.{_b64encode(_sign(signing_input, secret))}"


def read_token(token: str, secret: str) -> dict | None:
    """Validate a token's signature and expiry, and return its claims.

    Returns None for anything unusable, which deliberately collapses several
    causes into one answer - wrong shape, wrong algorithm, bad signature,
    expired, no subject. The caller's response is the same 401 in every case, and
    naming which check failed tells somebody forging tokens which part to fix.

    NEVER RAISES. Every caller treats None as "401" and has no except branch, so
    an exception escaping here would surface as a 500 or, via ERROR_STATUS, as a
    400 - both of which are the wrong answer to a bad token. Anything malformed,
    of the wrong type, or undecodable returns None.

    The order below is the security-critical part and is not interchangeable:

        1. split into exactly three parts
        2. recompute the signature over the FIRST TWO PARTS AS RECEIVED and
           compare in constant time
        3. only now decode the header, and refuse any algorithm but HS256
        4. only now decode the payload and check `exp`

    Steps 3 and 4 read attacker-supplied bytes, so they come after step 2 has
    established that the attacker did not supply them.
    """
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, signature_b64 = parts

    # -- 2. signature, before anything inside the token is believed ----------
    expected = _sign(f"{header_b64}.{payload_b64}", secret)
    try:
        provided = _b64decode(signature_b64)
    except (ValueError, binascii.Error):
        return None
    if not hmac.compare_digest(expected, provided):
        return None  # forged, tampered with, or signed with a different secret

    # -- 3. the algorithm we pinned, not the one the token asks for ----------
    try:
        header = json.loads(_b64decode(header_b64))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(header, dict) or header.get("alg") != ALGORITHM:
        # Unreachable in practice - a header we did not write would not have
        # verified above - but the check is the documentation of the `alg: none`
        # attack, and it survives somebody later making the signing configurable.
        return None

    # -- 4. the claims ------------------------------------------------------
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(payload, dict) or "sub" not in payload:
        return None

    # `exp` is checked for TYPE before it is compared. A missing exp, or one that
    # is a string or a bool rather than a number, is an unusable token and not a
    # crash: `"9999999999" < time.time()` raises TypeError, which escapes this
    # function, and the caller then answers 400 "invalid request" instead of 401.
    # Only something holding the signing key could produce such a token, so this
    # is defence in depth rather than a live hole - but a validator that raises
    # is a validator whose contract cannot be relied on.
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    if exp < time.time():
        return None  # expired; the client must log in again
    return payload
