"""Generate `postman_collection.json` from the live route table.

    python tools/export_postman.py

WHY GENERATE IT
---------------
A Postman collection is one of the four submission artifacts, and it is also the
API contract the frontend builds against. Hand-maintained, it drifts: a route
gets renamed, the collection keeps the old path, and the mismatch surfaces during
integration week instead of the afternoon it was introduced.

So the collection is built by importing `BankAPI` and walking `api.routes`. If a
route is added, renamed, or deleted, re-running this picks it up. The only thing
maintained by hand is the example body and description for each request, in
`EXAMPLES` below, and a route with no entry there still appears - with an empty
body and a TODO - rather than being silently dropped.

WHAT THE COLLECTION DOES WHEN YOU RUN IT
----------------------------------------
The login request has a test script that pulls the token out of the response and
stores it in a collection variable, and every other request sends
`Authorization: Bearer {{token}}`. So the flow is: run "Login (customer)", then
any other request works. No copying tokens by hand.

FAILURE CASES ARE INCLUDED ON PURPOSE
-------------------------------------
The build plan asks for overdraft, negative amount, and unauthorized access to
another user's account. A collection containing only happy paths demonstrates
that the endpoints exist; one containing the failures demonstrates that the rules
do. The second is what the grading criteria are actually asking about.
"""
import json
import pathlib
import sys

# Make `import bank` work when this is run as `python tools/export_postman.py`.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bank import BankAPI, BankService, BankStore  # noqa: E402

OUTPUT = pathlib.Path(__file__).resolve().parent.parent / "postman_collection.json"

# Values that match the seeded demo data, so every request works against a server
# started with `python server.py`.
VARIABLES = {
    "baseUrl": "http://127.0.0.1:8000",
    "token": "",                       # filled in by the login request's test script
    "customerEmail": "aaron.forrester@example.com",
    "adminEmail": "david.gusmao@example.com",
    "password": "BankDemo123!",
    "accountId": "1",                  # Aaron's checking, 2,480.00
    "savingsAccountId": "2",           # Aaron's savings, 15,750.00, no minimum held
    "otherUsersAccountId": "9",        # Daniel Tran's. Used to prove the IDOR is closed.
    "frozenAccountId": "10",           # seeded FROZEN
    "lowBalanceAccountId": "6",        # 12.50, for the overdraft case
}

# (method, path) -> (name, description, body or None)
EXAMPLES = {
    ("GET", "/api/health"): (
        "Health check",
        "No token required. Confirms the server is up, and says nothing else - a "
        "route that needs no token should not describe the bank's data.", None),

    ("POST", "/api/auth/register"): (
        "Register a new customer",
        "Creates a CUSTOMER and returns a token. Note there is no `role` field: "
        "sending one is ignored, so this endpoint cannot mint an admin.",
        {"name": "Test Person", "email": "test.person@example.com",
         "password": "ChangeMe123!"}),

    ("POST", "/api/auth/login"): (
        "Login (customer)",
        "Run this first. The test script stores the returned token in the "
        "collection variable `token`, which every other request sends as a "
        "bearer header.",
        {"email": "{{customerEmail}}", "password": "{{password}}"}),

    ("GET", "/api/auth/me"): (
        "Who am I",
        "Returns the user the current token belongs to. The frontend calls this "
        "on load to decide whether a stored token is still valid.", None),

    ("POST", "/api/accounts"): (
        "Create account",
        "The brief's POST /api/accounts. The owner is the authenticated user; "
        "`userId` is honoured only for an admin opening an account on someone "
        "else's behalf.",
        {"accountType": "SAVINGS", "openingBalance": 25000}),

    ("GET", "/api/accounts"): (
        "List my accounts",
        "Every account belonging to the caller. The dashboard's first call.", None),

    ("GET", "/api/accounts/{id}"): (
        "Get account details",
        "The brief's GET /api/accounts/{id}. Every money field comes back as an "
        "INTEGER NUMBER OF CENTS: a balance of 123456 means 1,234.56. JSON "
        "integers are exact, so nothing is lost in the browser the way a "
        "fractional number would be.", None),

    ("POST", "/api/accounts/{id}/deposit"): (
        "Deposit",
        "The brief's deposit endpoint. `clientTxnId` is optional and is the "
        "idempotency guard: send the same one twice and the second is refused.",
        {"amount": 10000, "clientTxnId": "postman-deposit-0001"}),

    ("POST", "/api/accounts/{id}/withdraw"): (
        "Withdraw",
        "The brief's withdraw endpoint.",
        {"amount": 2500}),

    ("GET", "/api/accounts/{id}/transactions"): (
        "Transaction history",
        "The brief's history endpoint, paginated. Supports ?page=, ?pageSize= "
        "and ?type=DEPOSIT.", None),

    ("POST", "/api/transfers"): (
        "Transfer between accounts",
        "Bonus feature from brief section 9. Both legs happen or neither does.",
        {"fromAccountId": 2, "toAccountId": 1, "amount": 5000}),

    ("GET", "/api/admin/users"): (
        "Admin: list users", "Requires the ADMIN role. 403 otherwise.", None),
    ("GET", "/api/admin/accounts"): (
        "Admin: list all accounts", "Requires the ADMIN role.", None),
    ("POST", "/api/admin/accounts/{id}/freeze"): (
        "Admin: freeze account",
        "A written reason of at least 10 characters is required, and the action "
        "is written to the audit log.",
        {"frozen": True, "reason": "Suspected card compromise, under review"}),
    ("POST", "/api/admin/accounts/{id}/adjust"): (
        "Admin: post a correcting adjustment",
        "The ONLY way an admin may change a balance. There is deliberately no "
        "set-balance endpoint: an adjustment posts a normal ledger entry, so "
        "balance == sum(ledger) still holds afterwards.",
        {"amount": 5000, "direction": "CREDIT",
         "reason": "Reversing a fee misposted on 2026-09-10"}),
    ("GET", "/api/admin/audit"): (
        "Admin: audit log", "Who did what, to which account, and why.", None),
    ("GET", "/api/admin/reconciliation"): (
        "Admin: reconciliation",
        "Every account where the stored balance disagrees with the sum of its "
        "ledger. Should always be empty. This is the one to open during the demo.",
        None),
}

# Requests that are not a plain call to one route: the failure cases, and the
# admin login. Each is (folder, name, method, path, body, description).
EXTRA_REQUESTS = [
    ("Auth", "Login (admin)", "POST", "/api/auth/login",
     {"email": "{{adminEmail}}", "password": "{{password}}"},
     "Same endpoint, admin credentials. Run this before the Admin folder."),

    ("Auth", "Login (wrong password)", "POST", "/api/auth/login",
     {"email": "{{customerEmail}}", "password": "not-the-password"},
     "Expect 401. The message is identical to an unknown email, so the form "
     "cannot be used to discover which addresses are registered."),

    ("Failure cases", "Overdraft is refused", "POST",
     "/api/accounts/{{lowBalanceAccountId}}/withdraw", {"amount": 1251},
     "Account 6 holds 12.50. Expect 409 and an unchanged balance."),

    ("Failure cases", "Negative amount is refused", "POST",
     "/api/accounts/{{accountId}}/deposit", {"amount": -5000},
     "Expect 400, rejected by validation before anything is written."),

    ("Failure cases", "A dollars-and-cents string is refused", "POST",
     "/api/accounts/{{accountId}}/deposit", {"amount": "10.50"},
     "Expect 400. This API takes a whole number of cents, so 10.50 dollars is "
     "sent as 1050. A quoted \"10.50\" is what the previous version of this API "
     "accepted, and it is refused rather than guessed at."),

    ("Failure cases", "A fractional JSON number is refused", "POST",
     "/api/accounts/{{accountId}}/deposit", {"amount": 10.50},
     "Expect 400. `10.50` parses to a float, which has already lost precision "
     "by the time the server sees it, and is ambiguous besides: in an API that "
     "speaks cents it could mean ten and a half cents. Send 1050."),

    ("Failure cases", "Frozen account refuses a deposit", "POST",
     "/api/accounts/{{frozenAccountId}}/deposit", {"amount": 10000},
     "Account 10 is seeded FROZEN. Expect 409."),

    ("Failure cases", "Duplicate clientTxnId is refused", "POST",
     "/api/accounts/{{accountId}}/deposit",
     {"amount": 10000, "clientTxnId": "postman-deposit-0001"},
     "Run the Deposit request first, then this. Expect 409: the double-clicked "
     "submit button does not deposit twice."),

    ("Failure cases", "IDOR: reading another user's account", "GET",
     "/api/accounts/{{otherUsersAccountId}}", None,
     "THE IMPORTANT ONE. Logged in as Aaron, ask for Daniel Tran's account. "
     "Expect 404 - and note it is the same 404 as an account that does not "
     "exist, because a 403 here would confirm the account is real."),

    ("Failure cases", "A customer cannot reach an admin route", "GET",
     "/api/admin/users", None,
     "Logged in as a customer. Expect 403."),

    ("Failure cases", "No token at all", "GET", "/api/accounts", None,
     "Delete the Authorization header in Postman before sending. Expect 401."),
]

# Postman test script attached to the login requests.
CAPTURE_TOKEN = """// Store the token so every other request in this collection can use it.
const body = pm.response.json();
if (body.token) {
    pm.collectionVariables.set("token", body.token);
    console.log("token stored for " + body.user.email + " (" + body.user.role + ")");
}
pm.test("login succeeded", function () {
    pm.response.to.have.status(200);
});
"""


def url_object(path: str) -> dict:
    """Postman wants a URL split into host and path segments as well as raw."""
    raw = "{{baseUrl}}" + path
    return {
        "raw": raw,
        "host": ["{{baseUrl}}"],
        "path": [segment for segment in path.strip("/").split("/") if segment],
    }


def request_item(name, method, path, body, description, script=None) -> dict:
    item = {
        "name": name,
        "request": {
            "method": method,
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": url_object(path),
            "description": description,
        },
    }
    if body is not None:
        item["request"]["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    if script:
        item["event"] = [{"listen": "test",
                          "script": {"type": "text/javascript",
                                     "exec": script.splitlines()}}]
    return item


def folder_for(path: str) -> str:
    """Group requests the way somebody reading the collection would expect."""
    if path.startswith("/api/auth"):
        return "Auth"
    if path.startswith("/api/admin"):
        return "Admin"
    if path.startswith("/api/transfers"):
        return "Transfers"
    if path.startswith("/api/accounts"):
        return "Accounts"
    return "Other"


def build() -> dict:
    # Import the real route table rather than restating it. This is the line that
    # makes the collection unable to drift from the code.
    api = BankAPI(BankService(BankStore()), secret="export-only")

    folders: dict[str, list] = {}
    for route in api.routes:
        # Recover the readable path from the compiled pattern.
        path = route.pattern.pattern.strip("^$").replace(r"(?P<id>\d+)", "{id}")
        name, description, body = EXAMPLES.get(
            (route.method, path),
            (f"TODO: {route.method} {path}",
             "This route has no example yet. Add one to EXAMPLES in "
             "tools/export_postman.py.", None))

        # Substitute the collection variable for the path parameter so the
        # requests are runnable as shipped.
        runnable = path.replace("{id}", "{{accountId}}")
        if path == "/api/accounts/{id}/transactions":
            runnable += "?page=1&pageSize=20"

        script = CAPTURE_TOKEN if path == "/api/auth/login" else None
        folders.setdefault(folder_for(path), []).append(
            request_item(name, route.method, runnable, body, description, script))

    for folder, name, method, path, body, description in EXTRA_REQUESTS:
        script = CAPTURE_TOKEN if path == "/api/auth/login" else None
        folders.setdefault(folder, []).append(
            request_item(name, method, path, body, description, script))

    order = ["Auth", "Accounts", "Transfers", "Admin", "Failure cases", "Other"]
    return {
        "info": {
            "name": "Simple Bank Application API",
            "description": (
                "Generated from the route table by tools/export_postman.py - do "
                "not edit by hand, edit that file and re-run it.\n\n"
                "USAGE\n"
                "1. Start the server:  python server.py\n"
                "2. Run 'Auth > Login (customer)'. The token is captured "
                "automatically into the `token` collection variable.\n"
                "3. Run anything else.\n"
                "4. For the Admin folder, run 'Auth > Login (admin)' first.\n\n"
                "All seeded users share the password BankDemo123!. Every email "
                "is on example.com, which RFC 2606 reserves and which can never "
                "receive mail.\n\n"
                "The 'Failure cases' folder is the interesting one: it covers "
                "overdraft, negative and malformed amounts, a frozen account, a "
                "replayed submission, and reading another user's account."),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        # Collection-level auth, so no individual request repeats the header.
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}",
                                               "type": "string"}]},
        "variable": [{"key": k, "value": v} for k, v in VARIABLES.items()],
        "item": [{"name": folder, "item": folders[folder]}
                 for folder in order if folder in folders],
    }


def main() -> int:
    collection = build()
    OUTPUT.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    count = sum(len(folder["item"]) for folder in collection["item"])
    print(f"wrote {OUTPUT.name}: {count} requests in "
          f"{len(collection['item'])} folders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
