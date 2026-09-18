"""Configuration loading. Standard library only.

Reads KEY=value lines from `.env` into the environment, so the server picks up
MONGODB_URI, MONGODB_DB and BANK_SECRET without a third-party loader. A value
already set in the real environment wins over the file, which lets a one-off
command override it.

`ensure_secret` also WRITES to `.env`, which is the one place this program
modifies its own configuration. See its docstring for why that is the right
trade and why the key is not shared between machines.
"""
import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> bool:
    """Load `.env` into os.environ. Returns whether a file was found.

    Blank lines and lines starting with # are ignored. Matching quotes around a
    value are stripped, since people copy these out of shell snippets.
    """
    env_file = Path(path) if path is not None else PROJECT_ROOT / ".env"
    if not env_file.exists():
        return False
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


def ensure_secret(path: Path | None = None) -> tuple[str, str]:
    """The JWT signing key, generating and saving one on first run.

    Returns `(secret, origin)`, where origin is one of:

        "environment"  already set, from the real environment or from .env
        "created"      generated just now and written to .env
        "unwritable"   generated just now, but .env could not be written

    WHY THIS EXISTS. Without a key, `security.new_secret` invents a random one per
    process, so every token stops working the moment the server restarts. That is
    safe but miserable: a restart signs everybody out, and during development
    there are a lot of restarts. Asking each person to remember to create a key by
    hand is the kind of setup step that is skipped, so the program does it once
    and then stops mentioning it.

    WHY EACH DEVELOPER GETS THEIR OWN, AND IT IS NOT SHARED. It is tempting to
    agree one key and pass it round the team, but nothing needs that. A token is
    only ever presented to the server that signed it, and everybody runs their own
    backend on localhost, so a key that never leaves one machine works perfectly
    and is one fewer secret in a chat log. A deployed server is the case that
    needs a fixed key, and it sets BANK_SECRET in its own environment - which this
    function then finds and leaves alone.

    WHY .env AND NOT A FILE OF ITS OWN. `.env` is already the documented place for
    configuration, already gitignored, and already the first place anybody looks.
    A second secret file would be a second thing to explain and a second thing to
    forget to ignore.
    """
    existing = os.environ.get("BANK_SECRET", "").strip()
    if existing:
        return existing, "environment"

    secret = secrets.token_urlsafe(32)
    os.environ["BANK_SECRET"] = secret

    env_file = Path(path) if path is not None else PROJECT_ROOT / ".env"
    # A file that does not end in a newline would otherwise have the new key
    # glued onto its last line, which silently corrupts whatever that line was.
    prefix = ""
    if env_file.exists():
        current = env_file.read_text(encoding="utf-8")
        if current and not current.endswith("\n"):
            prefix = "\n"

    block = (
        f"{prefix}\n"
        f"# Generated automatically on first run so that tokens survive a restart.\n"
        f"# Personal to this machine, never shared, never committed - .env is\n"
        f"# gitignored. Delete this line to be issued a new one, which signs out\n"
        f"# anybody holding a token from the old one.\n"
        f"BANK_SECRET={secret}\n"
    )
    try:
        with env_file.open("a", encoding="utf-8") as handle:
            handle.write(block)
    except OSError:
        # A read-only checkout, a permissions problem, a locked file. The server
        # still runs - the key just lasts until this process stops, which is
        # exactly the old behaviour.
        return secret, "unwritable"
    return secret, "created"
