"""Prove that this machine can actually use our MongoDB Atlas cluster.

    python tools/check_mongo.py

WHY THIS EXISTS
---------------
A connection string that looks right and a connection string that is right are
not distinguishable by eye, and Atlas's failure modes are worded unhelpfully. The
single most common one - your IP is not on the access list - does not say that.
Atlas drops the packets rather than refusing the connection, so the client waits
thirty seconds and reports a *timeout*, which sends people off investigating
their network instead of clicking the button that fixes it.

So every check below prints what a failure actually means, in the terms of the
thing you have to go and change. That is the whole value of this file.

WHY IT CHECKS A TRANSACTION
---------------------------
Check 7 is the one that justifies putting the database in the cloud at all.

`services.transfer()` moves money between two accounts and writes two ledger
entries, and its docstring promises "Both legs happen or neither does". In memory
that is free. In MongoDB it requires a multi-document transaction, and those
require a replica set.

A standalone `mongod` does not reject transaction code. It accepts it and gives
no atomicity, silently. That failure would survive every test we have and surface
as a corrupted balance during the demo - so this asserts the guarantee against
the real cluster rather than inferring it from the tier name in the docs.

WHAT IT TOUCHES
---------------
One collection, `_connection_check`, which it deletes after itself. It never
reads or writes `users`, `accounts`, or `transactions`.
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
PROBE = "_connection_check"

# Exit codes, so this is usable from a shell script later.
OK, FAILED = 0, 1


# --------------------------------------------------------------------- output

class Out:
    """Plain-text status lines.

    Every symbol is also a word - "OK", "FAIL" - rather than a bare green or red
    tick. Colour alone is not a signal; the same accessibility rule the rest of
    this project follows for credit and debit applies to a terminal.
    """

    @staticmethod
    def step(n, text):
        print(f"\n[{n}/7] {text}")

    @staticmethod
    def ok(text):
        print(f"      OK    {text}")

    @staticmethod
    def info(text):
        print(f"            {text}")

    @staticmethod
    def fail(text, *fixes):
        print(f"      FAIL  {text}")
        if fixes:
            print()
            print("      What to do:")
            for fix in fixes:
                # A fix starting with spaces is a continuation of the one above
                # it, so it is indented rather than given a bullet of its own.
                if fix.startswith("  "):
                    print(f"          {fix.strip()}")
                else:
                    print(f"        - {fix}")
        print()
        print("      Full details: README, section 'Using MongoDB Atlas'.")


def die(*_):
    sys.exit(FAILED)


# ------------------------------------------------------------------ .env load

def load_env():
    """Read `.env` into os.environ, via the same loader the application uses.

    Deliberately not a second copy of the parser. This script exists to tell you
    why your setup does not work, so it has to read the file exactly the way
    `server.py` does - a checker with its own subtly different parser can pass
    while the server fails, which is worse than having no checker.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from bank import config
    config.load_env()


def redact(uri):
    """A connection string with the password replaced, safe to print.

    This output gets pasted into group chats when someone asks for help, so the
    credential must not be in it.
    """
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", uri)


# -------------------------------------------------------------------- checks

def check_driver():
    Out.step(1, "pymongo is installed")
    try:
        import pymongo
    except ImportError:
        Out.fail(
            "pymongo is not installed in this Python.",
            "pip install -r requirements.txt",
            f"Check you installed into the Python you are running: {sys.prefix}",
            "If you made a venv, is it activated?",
        )
        die()

    Out.ok(f"pymongo {pymongo.version} on Python {sys.version.split()[0]}")
    try:
        import dns  # noqa: F401
    except ImportError:
        Out.fail(
            "dnspython is missing, so mongodb+srv:// cannot be resolved.",
            "pip install -r requirements.txt",
            "Do NOT use `pip install pymongo[srv]` - that extra no longer exists.",
        )
        die()
    Out.ok("dnspython present, so mongodb+srv:// will resolve")
    return pymongo


def check_uri():
    Out.step(2, "MONGODB_URI is set and looks usable")
    uri = os.environ.get("MONGODB_URI", "").strip()

    if not uri:
        Out.fail(
            "MONGODB_URI is not set.",
            f"Create {ENV_FILE.name}: copy .env.example .env",
            "Set MONGODB_URI to your Atlas string (see the README).",
        )
        die()

    if "<" in uri or ">" in uri:
        Out.fail(
            "The connection string still contains a placeholder in angle brackets.",
            "Replace <db_password> - brackets included - with your real password.",
            "Atlas: Database Access -> Edit -> Edit Password -> Autogenerate.",
        )
        die()

    if not uri.startswith(("mongodb+srv://", "mongodb://")):
        Out.fail(
            f"Does not start with mongodb+srv:// or mongodb:// - got {uri[:24]!r}",
            "Repaste it as one line with no surrounding quotes.",
        )
        die()

    Out.ok(redact(uri))

    if uri.startswith("mongodb://") and "localhost" in uri:
        Out.info("NOTE: this points at a local mongod, not Atlas. Check 7 will fail:")
        Out.info("      a standalone server cannot do multi-document transactions.")

    db_name = os.environ.get("MONGODB_DB", "").strip()
    if not db_name:
        db_name = "simple_bank_test"
        Out.info(f"MONGODB_DB is not set; using {db_name!r} for this check only.")
        # The server treats a missing MONGODB_DB as a hard error rather than
        # guessing, so a passing check here would otherwise be followed by a
        # server that refuses to start and a puzzled teammate.
        Out.info("WARNING: server.py will REFUSE TO START without MONGODB_DB.")
        Out.info("         Add MONGODB_DB=simple_bank_<yourname> to .env.")
    else:
        Out.ok(f"MONGODB_DB = {db_name}")
        if db_name == "simple_bank":
            Out.info("NOTE: that is the SHARED demo database. For day-to-day work")
            Out.info("      prefer simple_bank_<yourname> - see the README.")
    return uri, db_name


def check_connection(pymongo, uri):
    """Checks 3, 4 and 5: DNS, reachability, credentials.

    They are one function because pymongo connects lazily - nothing happens until
    the first command - so a single ping is what surfaces all three, and the
    exception type is what tells them apart.
    """
    from pymongo.errors import (
        ConfigurationError, OperationFailure, ServerSelectionTimeoutError,
    )

    Out.step(3, "DNS resolves, the cluster answers, the credentials are accepted")
    Out.info("resolving and connecting - this can take up to 15 seconds...")

    # The constructor is inside the try on purpose. A `mongodb+srv://` URI is
    # resolved eagerly here rather than lazily at first command, so a wrong
    # cluster hostname raises *now* - and left uncaught it prints a thirty-line
    # dnspython traceback instead of the one sentence that identifies the typo.
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000,
                                     appName="check_mongo")
    except ConfigurationError as exc:
        detail = str(exc)
        if "DNS" in detail or "resolv" in detail.lower():
            Out.fail(
                f"The cluster hostname did not resolve: {detail}",
                "Check the hostname in MONGODB_URI against Atlas -> Connect.",
                "  It looks like cluster0.XXXXX.mongodb.net - the XXXXX part is",
                "  generated per project and is easy to mistype.",
                "Some school and corporate networks block DNS SRV lookups.",
            )
        else:
            Out.fail(f"Could not build a client from the URI: {detail}",
                     "Repaste the connection string as one line, no quotes.")
        die()
    except Exception as exc:  # InvalidURI and friends
        Out.fail(f"Could not build a client from the URI: {exc}",
                 "Repaste the connection string as one line, no quotes.")
        die()

    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        detail = str(exc).lower()
        if "dns" in detail or "resolv" in detail or "srv" in detail:
            Out.fail(
                "The cluster hostname did not resolve.",
                "Check the hostname in MONGODB_URI against Atlas -> Connect.",
                "Some school and corporate networks block DNS SRV lookups.",
            )
        else:
            Out.fail(
                "Could not reach the cluster (timed out).",
                "MOST LIKELY: your IP is not on the access list. Atlas -> Network",
                "  Access -> confirm a 0.0.0.0/0 entry exists and says Active,",
                "  not Pending. A new entry takes a minute or two to apply.",
                "Or the cluster is paused: Atlas -> Database -> Resume.",
                "  (M0 pauses itself after 60 days of no activity.)",
                "Or your network blocks outbound port 27017.",
            )
        die()
    except ConfigurationError as exc:
        Out.fail(f"Configuration error: {exc}",
                 "Usually a malformed URI, or dnspython missing.")
        die()
    except OperationFailure as exc:
        if getattr(exc, "code", None) in (18, 8000) or "auth" in str(exc).lower():
            Out.fail(
                "Reached the cluster, but the credentials were rejected.",
                "Check the username and password in MONGODB_URI.",
                "Use your DATABASE user (Atlas -> Database Access), NOT your",
                "  Atlas account login. They are different credentials.",
                "Fastest fix: Edit -> Edit Password -> Autogenerate -> repaste.",
                "A password with @ : / ? # in it must be percent-encoded.",
            )
        else:
            Out.fail(f"Server rejected the ping: {exc}")
        die()

    Out.ok("hostname resolved")

    Out.step(4, "the cluster is reachable")
    Out.ok("ping answered")

    Out.step(5, "credentials accepted")
    Out.ok("authenticated")

    info = client.server_info()
    Out.ok(f"MongoDB {info.get('version', 'unknown')}")

    topology = client.topology_description.topology_type_name
    Out.ok(f"topology: {topology}")
    return client, topology


def check_readwrite(client, db_name):
    Out.step(6, "this user can insert, read and delete")
    from pymongo.errors import OperationFailure

    coll = client[db_name][PROBE]
    try:
        result = coll.insert_one({"check": "readwrite", "cents": 12345})
        found = coll.find_one({"_id": result.inserted_id})
        coll.delete_one({"_id": result.inserted_id})
    except OperationFailure as exc:
        Out.fail(
            f"Write refused: {exc}",
            "Your database user is probably read-only.",
            "Atlas -> Database Access -> Edit -> Read and write to any database.",
        )
        die()

    if not found or found.get("cents") != 12345:
        Out.fail("Wrote a document but read back something unexpected.")
        die()

    # Money is integer cents everywhere in this project (see money.py). BSON has
    # a 64-bit integer type and Python's int maps to it, so confirm the round
    # trip did not quietly produce a float - that is the same bug money.py
    # exists to prevent, arriving through the database instead of through Python.
    if not isinstance(found["cents"], int) or isinstance(found["cents"], bool):
        Out.fail(f"Integer cents came back as {type(found['cents']).__name__}, "
                 "not int. Money must never round-trip through a float.")
        die()

    Out.ok(f"insert / read / delete round-tripped in {db_name!r}")
    Out.ok("integer cents survived the round trip as an int")


def check_transaction(client, db_name, topology):
    Out.step(7, "multi-document transactions work (transfer() depends on this)")
    from pymongo.errors import OperationFailure

    if topology == "Single":
        Out.fail(
            "Connected to a standalone server, which cannot do transactions.",
            "A standalone mongod accepts transaction code and gives NO atomicity,",
            "  silently - so transfer() would corrupt balances without erroring.",
            "Point MONGODB_URI at the Atlas cluster (mongodb+srv://...mongodb.net).",
        )
        die()

    db = client[db_name]
    coll = db[PROBE]
    try:
        with client.start_session() as session:
            with session.start_transaction():
                # Two documents, one transaction. This is the shape of transfer():
                # debit one account, credit another, both or neither.
                coll.insert_one({"_id": "txn_probe_out", "cents": -500}, session=session)
                coll.insert_one({"_id": "txn_probe_in", "cents": 500}, session=session)
                # Abort rather than commit: the guarantee being tested is that the
                # two writes are one unit, and aborting proves it while leaving
                # nothing behind.
                session.abort_transaction()
    except OperationFailure as exc:
        Out.fail(
            f"Transaction failed: {exc}",
            "If this mentions replica sets, the server is not a replica set.",
            "Atlas M0 is a 3-node replica set, so this should pass on Atlas.",
        )
        die()

    leftover = coll.count_documents({"_id": {"$in": ["txn_probe_out", "txn_probe_in"]}})
    if leftover:
        coll.delete_many({"_id": {"$in": ["txn_probe_out", "txn_probe_in"]}})
        Out.fail(
            "The aborted transaction left documents behind - it was not atomic.",
            "Do not build transfer() on this connection until it is understood.",
        )
        die()

    Out.ok("a two-document transaction ran and rolled back cleanly")
    Out.ok("transfer() can be made atomic against this cluster")

    try:
        db.drop_collection(PROBE)
    except OperationFailure:
        pass  # Not worth failing the run over; the documents are already gone.


# ----------------------------------------------------------------------- main

def main():
    print("=" * 70)
    print("  MongoDB Atlas connection check")
    print("=" * 70)
    load_env()
    Out.info(f"reading {ENV_FILE}" if ENV_FILE.exists()
             else f"no {ENV_FILE.name} found - using the environment only")

    pymongo = check_driver()
    uri, db_name = check_uri()
    client, topology = check_connection(pymongo, uri)
    try:
        check_readwrite(client, db_name)
        check_transaction(client, db_name, topology)
    finally:
        client.close()

    print()
    print("=" * 70)
    print("  All checks passed. Atlas is ready.")
    print("=" * 70)
    print(f"  cluster:  {redact(uri)}")
    print(f"  database: {db_name}")
    print()
    print("  Next:  python server.py                 serve the API from Atlas")
    print("         python server.py --reset         wipe and reload the demo data")
    print("         MONGO_TESTS=1 python test_mongo.py    tests against this cluster")
    return OK


if __name__ == "__main__":
    sys.exit(main())
