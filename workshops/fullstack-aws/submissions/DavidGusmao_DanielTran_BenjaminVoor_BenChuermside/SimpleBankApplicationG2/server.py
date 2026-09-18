"""Start the REST API. Run with: python server.py

    python server.py              # MongoDB if .env has MONGODB_URI, otherwise in memory
    python server.py --reset      # MongoDB: wipe your database and reload the demo data
    python server.py --memory     # ignore .env and run in memory
    python server.py --empty      # start with no demo data
    python server.py --port 9000  # somewhere else

With MONGODB_URI and MONGODB_DB set in .env, data lives in Atlas and survives a
restart. The demo data is loaded the first time the database is empty, and only
then: loading it on every start would try to recreate records that already exist.
To start over, use --reset.

Without them, everything is in memory, and each run starts from the demo data.
"""
import argparse
import os
import sys

from bank import BankService, BankStore, serve
from bank import seed as seed_module
from bank.config import ensure_secret, load_env
from bank.errors import StorageUnavailable

# The team's shared demo database. --reset refuses to wipe it without --force.
SHARED_DB = "simple_bank"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple Bank Application API")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (default: 127.0.0.1, localhost only)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    parser.add_argument("--empty", action="store_true",
                        help="do not load the demo data")
    parser.add_argument("--memory", action="store_true",
                        help="run in memory even if .env has a MongoDB connection string")
    parser.add_argument("--reset", action="store_true",
                        help="MongoDB only: delete everything in your database first")
    parser.add_argument("--force", action="store_true",
                        help=f"allow --reset on the shared {SHARED_DB!r} database")
    return parser


def open_mongo_store(uri: str, args):
    """Connect to MongoDB, or print what to fix and return None."""
    try:
        from bank.mongo_store import MongoStore
    except ImportError:
        print("  MONGODB_URI is set, but pymongo is not installed.")
        print("  Run: python -m pip install -r requirements.txt")
        return None

    db_name = os.environ.get("MONGODB_DB", "").strip()
    if not db_name:
        print("  MONGODB_URI is set, but MONGODB_DB is not.")
        print("  Add MONGODB_DB=simple_bank_yourname to .env (see the README).")
        return None
    if args.reset and db_name == SHARED_DB and not args.force:
        print(f"  refusing to --reset the shared {SHARED_DB!r} database.")
        print("  Point MONGODB_DB at your own database, or add --force if you mean it.")
        return None

    print(f"  connecting to MongoDB database {db_name!r}...")
    try:
        store = MongoStore(uri, db_name)
    except StorageUnavailable:
        print("  could not reach the cluster. Run: python tools/check_mongo.py")
        return None
    print(f"  storage: MongoDB Atlas, database {db_name!r} (data survives restarts)")
    return store


def load_demo_data(service) -> None:
    # Loading the seed replays ~73 transactions through the real service methods
    # and asserts the result reconciles, so a failure here is a genuine bug report
    # and not a data problem.
    summary = seed_module.load(service)
    print(f"  seeded {summary['users']} users, {summary['accounts']} accounts, "
          f"{summary['transactions']} transactions")
    print("  all accounts reconcile: balance == sum(ledger)")
    print()
    print(f"  every seeded user's password is: {summary['password']}")
    print("  customer login: aaron.forrester@example.com")
    # Two admins, so admin-to-admin visibility and the audit trail can both be
    # demonstrated. Either works; the Postman collection uses David.
    print(f"  admin logins:   {', '.join(summary['admins'])}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    found_env = load_env()

    print("=" * 70)
    print("  Simple Bank Application: backend")
    print("=" * 70)
    if not found_env:
        print("  no .env file found; using the environment only")

    uri = os.environ.get("MONGODB_URI", "").strip()
    use_mongo = bool(uri) and not args.memory

    # Compose the layers. This is the only place the whole stack is assembled,
    # and it reads as the architecture diagram: store -> service -> api.
    if use_mongo:
        store = open_mongo_store(uri, args)
        if store is None:
            return 1
    else:
        if args.reset:
            print("  --reset needs MONGODB_URI in .env; in memory there is nothing to reset.")
            return 2
        store = BankStore()
        print("  storage: in memory (nothing is saved when the server stops)")
    service = BankService(store)
    print()

    if use_mongo and args.reset:
        store.reset()
        print("  --reset: deleted everything in this database")

    if args.empty:
        print("  --empty: not loading demo data. POST /api/auth/register to create a user.")
    elif use_mongo and not store.is_empty():
        print("  database already has data, so the demo data was not reloaded")
        print("  (use --reset to start over)")
    else:
        if use_mongo:
            print("  loading demo data into the database; over the network this "
                  "takes a little while...")
        load_demo_data(service)

    print()
    # Tokens are signed, not stored, so what decides whether one survives a
    # restart is the signing key rather than the database. ensure_secret creates
    # one on first run and saves it to .env, so this is a setup step nobody has
    # to be told about - and a saved Postman token answering 401 after a restart
    # stops being a thing that happens.
    secret, origin = ensure_secret()
    if origin == "environment":
        print("  signing key:    from BANK_SECRET (tokens survive a restart)")
    elif origin == "created":
        print("  signing key:    generated and saved to .env - yours, not shared")
        print("                  (tokens will now survive a restart)")
    else:
        print("  signing key:    random for this process; .env could not be written")
        print("                  (every token stops working when you restart)")
    admin_code = os.environ.get("BANK_ADMIN_CODE", "").strip()
    if admin_code:
        print("  admin code:     set, so POST /api/auth/register accepts adminCode")
    else:
        print("  admin code:     not set, so nobody can register as an admin")
        print("  tip: set BANK_ADMIN_CODE in .env to open admin registration")
    print()

    serve(service, host=args.host, port=args.port, secret=secret,
          admin_code=admin_code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
