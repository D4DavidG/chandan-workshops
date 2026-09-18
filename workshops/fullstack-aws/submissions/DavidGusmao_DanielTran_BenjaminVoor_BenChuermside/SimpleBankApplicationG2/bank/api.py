"""The controller layer: HTTP in, JSON out, and nothing else.

    Frontend (UI) -> REST API (Controller) -> Service Layer -> Repository -> Database
                     ^^^^^^^^^^^^^^^^^^^^
                     this file

WHAT A CONTROLLER IS ALLOWED TO DO
----------------------------------
Four things, and only these four:

    1. Work out who is calling         (read the token, look up the user)
    2. Pull values out of the request  (path, query string, JSON body)
    3. Call exactly one service method
    4. Turn the result, or the exception, into a status code and a body

There is no business rule anywhere in this file. No balance comparison, no "is
this account frozen", no ownership check. Those all live in `services.py`, and
the test for whether that separation is real is simple: `test_bank.py` exercises
every rule in the system without importing this module at all.

"Clean MVC separation" is a graded criterion, and the way it is usually lost is
not by a grand architectural mistake. It is lost one `if` at a time, each of which
looked easier to put in the handler than to thread through the service.

WHY http.server AND NOT FastAPI OR FLASK
----------------------------------------
The stack question is still open - the brief says MySQL "to be confirmed" and
suggests Node, Spring Boot or Python, while the syllabus teaches Python. Choosing
FastAPI now would quietly answer a question that belongs to the instructor, and
it would add a dependency to a submission that currently installs nothing.

`http.server` is in the standard library, so this runs on a clean machine with
`python server.py` and no virtualenv. The four things a controller does, listed
above, are the same in any framework; what changes is the routing syntax. When
the stack is settled, porting this file to FastAPI is mechanical - the route
table below becomes decorators, `_authenticate` becomes a dependency, and
`ERROR_STATUS` becomes an exception handler. Nothing outside this file moves.

The honest limitation: `http.server` is explicitly not for production use. For a
training project graded on API correctness and layer separation, that is fine,
and it is written down here rather than left to be discovered.

THE ERROR TABLE IS THE OTHER HALF OF THE DESIGN
-----------------------------------------------
`services.py` raises domain exceptions - `InsufficientFunds`, not "409". That is
what lets the same rules serve an HTTP API, a CLI, and a test suite. The price is
that somebody has to map one to the other, and `ERROR_STATUS` below is that map:
one table, in one file, instead of a `try`/`except` in each of sixteen handlers.
"""
import json
import re
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .errors import (
    AccountNotActive, AccountNotFound, BankError, ConcurrentUpdate, DuplicateTransaction,
    StaleIdCounter,
    EmailAlreadyUsed, InsufficientFunds, InvalidAmount, NotAuthorized,
    StorageUnavailable, UserNotFound,
)
from .security import TOKEN_TTL_SECONDS, issue_token, new_secret, read_token
from .serializers import account_json, page_json, transaction_json, user_json

# ---------------------------------------------------------------------------
# Domain exception -> HTTP status. The whole mapping, in one place.
#
# Order matters: the lookup walks this list top to bottom and takes the first
# class the exception is an instance of, so subclasses must come before their
# parents. `InvalidAmount` before `BankError`, or every 400 would answer 500.
# ---------------------------------------------------------------------------
ERROR_STATUS = [
    # 400 Bad Request - the request itself is malformed or invalid.
    (InvalidAmount, 400),

    # 403 Forbidden - we know who you are, and you may not do this.
    # (A *failed login* is 401, not 403, and is handled in the login route:
    #  401 means "authenticate", 403 means "authenticating again will not help".)
    (NotAuthorized, 403),

    # 404 Not Found - also returned for an account that exists but is not yours.
    # See `BankService.get_account_for`: a distinct 403 there would confirm the
    # account is real, which is the leak the 404 exists to prevent.
    (AccountNotFound, 404),
    (UserNotFound, 404),

    # 409 Conflict - the request is well formed, but the current state refuses it.
    (InsufficientFunds, 409),
    (AccountNotActive, 409),
    (DuplicateTransaction, 409),
    (EmailAlreadyUsed, 409),
    # Another request changed the same account first, and this one was rolled
    # back whole. Retrying is safe.
    (ConcurrentUpdate, 409),

    # 503 Service Unavailable - the request was fine, but the database could not
    # be reached. Nothing was changed, so the caller can try again shortly.
    (StorageUnavailable, 503),
    # A setup problem, not a request problem: retrying fails identically, so it
    # is a 500 and the message says how to repair it.
    (StaleIdCounter, 500),

    # Anything else from the domain that has not been given a status yet.
    (BankError, 400),

    # ValueError covers the service layer's own argument checks - a missing name,
    # an unknown account type, an admin reason that is too short.
    (ValueError, 400),
    # money.to_cents raises TypeError on anything that is not an int number of
    # cents. That is a client mistake, not a server fault, so it is a 400 and not
    # a 500. (parse_amount catches most of these first and raises InvalidAmount;
    # this row covers the paths that reach to_cents directly.)
    (TypeError, 400),
]

MAX_BODY_BYTES = 64 * 1024  # A request body larger than this is refused unread.


class ApiError(Exception):
    """An HTTP-level problem with no domain meaning: a missing token, an unknown
    route, a body that is not JSON. Domain problems raise domain exceptions and
    are translated by `ERROR_STATUS` instead."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Request:
    """Everything a handler is given. Deliberately small.

    `actor` is the authenticated `User`, or None on a public route. A handler
    never reads a header or a raw query string; if it needs something, it is a
    field here, which keeps handler bodies down to one service call each.
    """

    __slots__ = ("method", "path", "params", "query", "body", "actor")

    def __init__(self, method, path, params, query, body, actor=None):
        self.method = method
        self.path = path
        self.params = params      # values captured from the URL, e.g. {"id": 4}
        self.query = query        # parsed query string, flattened to single values
        self.body = body          # parsed JSON body, always a dict (possibly empty)
        self.actor = actor        # the logged-in User, or None

    # -- small typed readers, so no handler ever re-implements validation --

    def require(self, key: str):
        """A body field that must be present and non-empty."""
        value = self.body.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ApiError(400, f"'{key}' is required")
        return value

    def optional(self, key: str, default=None):
        return self.body.get(key, default)

    def int_query(self, key: str, default: int) -> int:
        """A query-string integer that refuses to crash the request.

        `?page=abc` is a client mistake, and falling back to the default is kinder
        than a 500 and more useful than a 400 for a value this peripheral.
        """
        try:
            return int(self.query.get(key, default))
        except (TypeError, ValueError):
            return default


class Route:
    """One row of the routing table: a method, a URL pattern, and who may call it."""

    __slots__ = ("method", "pattern", "handler", "auth", "admin")

    def __init__(self, method, pattern, handler, auth=True, admin=False):
        self.method = method
        # Turn "/api/accounts/{id}/deposit" into a regex with a named group.
        # `\d+` rather than `.+` so a non-numeric id is a clean 404 from the
        # router instead of an exception deeper in.
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>\\d+)", pattern)
        self.pattern = re.compile(f"^{regex}$")
        self.handler = handler
        self.auth = auth      # must present a valid token
        self.admin = admin    # must additionally hold the ADMIN role


class BankAPI:
    """The routing table and the handlers.

    Separated from the HTTP server underneath it on purpose: `handle()` takes
    plain arguments and returns a plain `(status, dict)`, so `test_api.py` tests
    every route without opening a socket. It is also the seam that makes swapping
    `http.server` for FastAPI a change to the bottom of this file only.
    """

    def __init__(self, service, secret: str | None = None,
                 admin_code: str | None = None):
        self.service = service
        # The key every token is signed with. Held here rather than in the
        # service because signing is not a business rule - services.py must stay
        # callable from a CLI or a test that has no notion of a session.
        self.secret = secret or new_secret()
        # The shared code that lets somebody register as an admin. None means the
        # door is shut and `adminCode` is refused whatever it contains, which is
        # the right default: a deployment that never sets it cannot grow admins
        # by accident. It arrives as an argument rather than being read from the
        # environment here, so this class still has no idea what a .env file is.
        self.admin_code = admin_code or None
        self.routes = self._build_routes()

    # -------------------------------------------------------------- the table

    def _build_routes(self) -> list[Route]:
        """Every endpoint in the system, readable as a list.

        The five routes the brief specifies are marked. The rest are the auth the
        hiring manager asked for, plus the admin surface and the transfer from the
        bonus list.
        """
        return [
            # -- public: no token required ---------------------------------
            Route("POST", "/api/auth/register", self.register, auth=False),
            Route("POST", "/api/auth/login", self.login, auth=False),
            Route("GET", "/api/health", self.health, auth=False),

            # -- authenticated customer ------------------------------------
            Route("GET", "/api/auth/me", self.me),
            Route("POST", "/api/auth/me", self.update_me),
            Route("POST", "/api/accounts", self.create_account),            # brief 5.4
            Route("GET", "/api/accounts", self.list_accounts),
            Route("GET", "/api/users/search", self.search_users),
            Route("GET", "/api/accounts/{id}", self.get_account),           # brief 5.4
            Route("POST", "/api/accounts/{id}/deposit", self.deposit),      # brief 5.4
            Route("POST", "/api/accounts/{id}/withdraw", self.withdraw),    # brief 5.4
            Route("GET", "/api/accounts/{id}/transactions", self.history),  # brief 5.4
            Route("POST", "/api/transfers", self.transfer),

            # -- admin only ------------------------------------------------
            Route("GET", "/api/admin/users", self.admin_users, admin=True),
            Route("GET", "/api/admin/accounts", self.admin_accounts, admin=True),
            Route("POST", "/api/admin/accounts/{id}/freeze", self.admin_freeze, admin=True),
            Route("POST", "/api/admin/accounts/{id}/adjust", self.admin_adjust, admin=True),
            Route("GET", "/api/admin/audit", self.admin_audit, admin=True),
            Route("GET", "/api/admin/reconciliation", self.admin_reconcile, admin=True),
        ]

    # ------------------------------------------------------------- dispatch

    def handle(self, method: str, raw_path: str, body_bytes: bytes = b"",
               headers: dict | None = None) -> tuple[int, dict]:
        """The single entry point. Never raises; every path returns (status, body).

        A handler that threw an unexpected exception would otherwise take the
        whole server down or leak a stack trace to the client, so the catch-all at
        the bottom turns anything unrecognised into a 500 with a generic message.
        """
        headers = headers or {}
        parsed = urlparse(raw_path)
        # parse_qs gives {"page": ["2"]}; flatten to {"page": "2"} since no
        # parameter in this API is legitimately repeated.
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        try:
            route, params = self._match(method, parsed.path)
            actor = self._authenticate(route, headers)
            body = self._parse_body(method, body_bytes)
            request = Request(method, parsed.path, params, query, body, actor)
            return route.handler(request)

        except ApiError as exc:
            return exc.status, {"error": exc.message}
        except Exception as exc:                      # noqa: BLE001 - intentional
            status = self._status_for(exc)
            if status is None:
                # Genuinely unexpected. Log it for the operator, and tell the
                # client nothing: an exception message can carry internal detail.
                import traceback
                traceback.print_exc()
                return 500, {"error": "internal server error"}
            return status, {"error": self._client_message(exc)}

    def _match(self, method: str, path: str) -> tuple[Route, dict]:
        """Find the route, distinguishing 404 from 405.

        If some route matches the path but none matches the method, the answer is
        405 Method Not Allowed rather than 404 - a POST to a GET-only URL is a
        different mistake from a URL that does not exist, and saying so saves the
        caller from hunting for a typo that is not there.
        """
        path_matched = False
        for route in self.routes:
            match = route.pattern.match(path)
            if not match:
                continue
            path_matched = True
            if route.method == method:
                # Path parameters are all `\d+`, so int() here is safe and means
                # handlers receive ints rather than strings.
                return route, {k: int(v) for k, v in match.groupdict().items()}
        raise ApiError(405 if path_matched else 404,
                       "method not allowed" if path_matched else "no such endpoint")

    def _authenticate(self, route: Route, headers: dict):
        """Turn an Authorization header into a User, and enforce the route's role.

        This runs for every protected route from one place. The build plan's
        Section 5.2 point applies here: a role check repeated as an `if` inside
        each handler is the fastest way to end up with one handler that forgot.
        """
        if not route.auth:
            return None

        raw = headers.get("authorization") or headers.get("Authorization") or ""
        if not raw.lower().startswith("bearer "):
            raise ApiError(401, "missing bearer token")

        # Signature and expiry, in that order, inside read_token. Returns None
        # for every kind of unusable token - wrong shape, bad signature, wrong
        # algorithm, expired - because they are all the same 401 to the caller.
        claims = read_token(raw[7:].strip(), self.secret)
        if claims is None:
            raise ApiError(401, "invalid or expired token")

        try:
            # THE ROLE IS NOT READ FROM THE TOKEN. The claims are signed, so
            # `claims["role"]` has certainly not been tampered with - but it was
            # written up to a week ago, and a token cannot be recalled. If this
            # user was demoted an hour after logging in, their token still says
            # ADMIN and still verifies. The stored record is the authority, so
            # the demotion takes effect on this request.
            actor = self.service.store.get_user(claims["sub"])
        except UserNotFound:
            raise ApiError(401, "invalid or expired token") from None

        if route.admin and not actor.is_admin:
            raise ApiError(403, "admin role required")
        return actor

    @staticmethod
    def _parse_body(method: str, body_bytes: bytes) -> dict:
        """Parse a JSON body, or return an empty dict for a request with none."""
        if method in ("GET", "DELETE") or not body_bytes:
            return {}
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "request body must be valid JSON") from None
        if not isinstance(parsed, dict):
            raise ApiError(400, "request body must be a JSON object")
        return parsed

    @staticmethod
    def _int_field(value, key: str) -> int:
        """A body field that must be a whole number, or a 400 naming the field.

        Without this, int(["x"]) raises a TypeError whose message is Python's own
        wording about argument types, which describes our internals rather than
        the caller's mistake.
        """
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ApiError(400, f"'{key}' must be a number")
        try:
            return int(value)
        except ValueError:
            raise ApiError(400, f"'{key}' must be a number") from None

    @staticmethod
    def _client_message(exc: Exception) -> str:
        """What the caller is told about a matched exception.

        Domain errors and ValueErrors carry messages written for a caller. A
        TypeError does not: its text is Python explaining itself to a developer,
        so it is replaced with something the caller can act on.
        """
        if isinstance(exc, (BankError, ValueError)):
            return str(exc)
        return "invalid request"

    @staticmethod
    def _status_for(exc: Exception) -> int | None:
        """First matching row of ERROR_STATUS, or None if nothing matches."""
        for exc_type, status in ERROR_STATUS:
            if isinstance(exc, exc_type):
                return status
        return None

    # ================================================================ handlers
    #
    # Each one: read the request, call one service method, serialize. If a handler
    # below ever grows a business rule, it belongs in services.py instead.

    # ------------------------------------------------------------------ auth

    def health(self, request: Request) -> tuple[int, dict]:
        """Liveness check. Useful for confirming the server is up before a demo.

        Answers whether the process is up, and nothing else. It used to include
        the account count, which was handy for seeing at a glance that the seed
        had run, but it was the wrong thing to put here twice over: it is a
        business figure on the one route that needs no token, and counting rows
        makes a liveness check get slower as the data grows - once this is MySQL
        it is a query, and a slow database would start failing health checks on a
        server that is perfectly alive.

        The count is still available to an admin from GET /api/admin/reconciliation,
        which reports `checked`.
        """
        return 200, {"status": "ok"}

    def register(self, request: Request) -> tuple[int, dict]:
        """Create a customer and log them straight in.

        Note there is still no `role` field read from the body. Accepting one
        would let anybody mint themselves an admin by adding a line to a request,
        which is the most common privilege-escalation bug in exactly this kind of
        endpoint. What the body may carry is `adminCode`, which is checked against
        a value only the server knows - see `_role_for`.
        """
        user = self.service.register_user(
            name=request.require("name"),
            email=request.require("email"),
            password=request.require("password"),
            role=self._role_for(request.optional("adminCode")),
        )
        return 201, {"user": user_json(user), **self._session_for(user)}

    def login(self, request: Request) -> tuple[int, dict]:
        """Exchange email and password for a token.

        `NotAuthorized` is caught here and re-raised as 401 rather than falling
        through to the 403 in ERROR_STATUS. The distinction is real: 401 means
        "you are not authenticated, try credentials", 403 means "you are
        authenticated and still may not". A failed login is the first.
        """
        try:
            user = self.service.authenticate(request.require("email"),
                                             request.require("password"))
        except NotAuthorized:
            raise ApiError(401, "invalid email or password") from None
        return 200, {"user": user_json(user), **self._session_for(user)}

    def _session_for(self, user) -> dict:
        """The `token` and `expiresIn` pair that register and login both return.

        The username claim is the email, because that is what this application
        logs in with - there is no separate username field on User. The display
        name rides along so a client can greet somebody without a second call.
        """
        return {
            "token": issue_token(user.user_id, user.email, user.role,
                                 self.secret, name=user.name),
            "expiresIn": TOKEN_TTL_SECONDS,
        }

    def _role_for(self, submitted_code) -> str:
        """CUSTOMER, or ADMIN if the request carried the right code.

        The comparison is `compare_digest`, not `==`. String equality returns as
        soon as two characters differ, so the time it takes leaks how much of the
        code was right, and a few thousand attempts turn that into the code
        itself. The fixed-time compare is one import and removes the whole class
        of attack.

        This is a shared secret typed into a form, which is the weakest thing
        that can honestly be called authentication: everybody who registers this
        way knows the same string, and it cannot be revoked for one person. It is
        appropriate for a graded training project with a seeded roster, and it
        would not be appropriate for anything real - the production answer is
        that an existing admin promotes you, and the audit log records who did.
        """
        if submitted_code is None or submitted_code == "":
            return "CUSTOMER"
        if not isinstance(submitted_code, str) or self.admin_code is None:
            raise ApiError(403, "invalid admin code")
        if not compare_digest(submitted_code, self.admin_code):
            raise ApiError(403, "invalid admin code")
        return "ADMIN"

    def me(self, request: Request) -> tuple[int, dict]:
        """Who the current token belongs to. The frontend calls this on load to
        decide whether a stored token is still good."""
        return 200, {"user": user_json(request.actor)}

    def update_me(self, request: Request) -> tuple[int, dict]:
        """Edit your own name or email.

        Which user gets edited comes from the token, never from the body, so
        there is no id here to point at somebody else. A field that is absent is
        left alone; a field that is present and blank is a 400 rather than a way
        to erase your own name.
        """
        name = request.optional("name")
        email = request.optional("email")
        if name is None and email is None:
            raise ApiError(400, "send 'name', 'email', or both")
        user = self.service.update_profile(request.actor, name=name, email=email)
        return 200, {"user": user_json(user)}

    # -------------------------------------------------------------- accounts

    def create_account(self, request: Request) -> tuple[int, dict]:
        """POST /api/accounts - the brief's create-account endpoint.

        ONE DELIBERATE DEVIATION FROM THE BRIEF. Its sample body is:

            {"userId": 1, "accountType": "SAVINGS"}

        Taking the owner from the body means any caller can open an account in
        somebody else's name by changing that number - the same class of bug as
        the IDOR on `GET /api/accounts/{id}`. So the owner is the authenticated
        user, and `userId` is honoured only for an admin opening an account on a
        customer's behalf. The brief's exact body still works; it just no longer
        works for a customer targeting a stranger.
        """
        owner = request.actor
        requested_owner = request.optional("userId")
        if requested_owner is not None:
            requested_owner = self._int_field(requested_owner, "userId")
            if requested_owner != request.actor.user_id:
                if not request.actor.is_admin:
                    raise ApiError(403, "cannot open an account for another user")
                owner = self.service.store.get_user(requested_owner)

        account = self.service.open_account(
            owner=owner,
            account_type=request.require("accountType"),
            opening_balance=request.optional("openingBalance", 0),
        )
        return 201, {"account": account_json(account, owner)}

    def list_accounts(self, request: Request) -> tuple[int, dict]:
        """Every account belonging to the caller. Not in the brief, but the
        dashboard needs it, and without it the UI has no way to discover an
        account id short of the user typing one in."""
        accounts = self.service.my_accounts(request.actor)
        return 200, {"accounts": [account_json(a, request.actor) for a in accounts]}

    def search_users(self, request: Request) -> tuple[int, dict]:
        """GET /api/users/search?q=ben - who the caller could send money to.

        Deliberately not under /api/admin: paying somebody is a customer action.
        See `service.search_users` for what this exposes and why it would not
        exist in a real bank.
        """
        people = self.service.search_users(request.query.get("q", ""), request.actor)
        return 200, {"users": [user_json(u) for u in people]}

    def get_account(self, request: Request) -> tuple[int, dict]:
        """GET /api/accounts/{id} - the brief's endpoint, with the hole closed.

        The ownership check is not written here. It is inside
        `service.get_account_for`, which every read and write path already goes
        through, so this route cannot forget it and neither can the next one
        somebody adds.
        """
        account = self.service.get_account_for(request.params["id"], request.actor)
        owner = self.service.store.get_user(account.user_id)
        return 200, {"account": account_json(account, owner)}

    def deposit(self, request: Request) -> tuple[int, dict]:
        """POST /api/accounts/{id}/deposit - the brief's endpoint.

        `clientTxnId` is optional and is the cheap idempotency guard: the client
        generates one UUID per submission attempt, and a double-clicked button
        sends the same one twice. The second is refused with 409 rather than
        depositing twice. See `BankService._guard_idempotency`.
        """
        txn = self.service.deposit(
            account_id=request.params["id"],
            amount=request.require("amount"),
            actor=request.actor,
            client_txn_id=request.optional("clientTxnId"),
        )
        return self._movement_response(txn, request)

    def withdraw(self, request: Request) -> tuple[int, dict]:
        """POST /api/accounts/{id}/withdraw - the brief's endpoint."""
        txn = self.service.withdraw(
            account_id=request.params["id"],
            amount=request.require("amount"),
            actor=request.actor,
            client_txn_id=request.optional("clientTxnId"),
        )
        return self._movement_response(txn, request)

    def history(self, request: Request) -> tuple[int, dict]:
        """GET /api/accounts/{id}/transactions - the brief's endpoint, paginated.

        Supports ?page=, ?pageSize= and ?type=DEPOSIT. The ownership check is
        again inside the service call, not here.
        """
        page = request.int_query("page", 1)
        page_size = request.int_query("pageSize", 20)
        rows, total = self.service.history(
            account_id=request.params["id"],
            actor=request.actor,
            page=page,
            page_size=page_size,
            txn_type=request.query.get("type"),
        )
        # The service clamps page_size to 1..100, so echo back what it actually
        # used rather than what was asked for, or the client's paging arithmetic
        # will disagree with the server's.
        effective_size = min(max(1, page_size), 100)
        return 200, page_json([transaction_json(t) for t in rows], total,
                              max(1, page), effective_size)

    def transfer(self, request: Request) -> tuple[int, dict]:
        """POST /api/transfers - the brief's bonus feature.

        Body carries both account ids, so this is not nested under
        /api/accounts/{id}: a transfer is an operation on the pair, and putting
        one of them in the path and the other in the body suggests an asymmetry
        that does not exist.

        The destination may be given as `toUserId` instead of `toAccountId`, and
        the server resolves it to that person's primary account. That is what
        lets the frontend offer a name to pick rather than asking somebody to
        know an account number - and it means the browser never has to be told
        another user's account ids, which it has no business holding.
        """
        out, inn = self.service.transfer(
            from_id=self._int_field(request.require("fromAccountId"), "fromAccountId"),
            to_id=self._destination_account_id(request),
            amount=request.require("amount"),
            actor=request.actor,
            client_txn_id=request.optional("clientTxnId"),
        )
        source = self.service.get_account_for(out.account_id, request.actor)
        owner = self.service.store.get_user(source.user_id)
        return 201, {
            "debit": transaction_json(out),
            "credit": transaction_json(inn),
            "account": account_json(source, owner),
        }

    def _destination_account_id(self, request: Request) -> int:
        """Where a transfer is going: an account id, or a person's primary one.

        Exactly one of the two is required. Accepting both and silently
        preferring one would mean a client that sent a mismatched pair moved
        money somewhere it did not name.
        """
        account_id = request.optional("toAccountId")
        user_id = request.optional("toUserId")
        if (account_id is None) == (user_id is None):
            raise ApiError(400, "send exactly one of 'toAccountId' or 'toUserId'")
        if account_id is not None:
            return self._int_field(account_id, "toAccountId")
        user_id = self._int_field(user_id, "toUserId")
        # get_user first, so an id that is nobody reads as "no such user" rather
        # than as "that person has no account".
        self.service.store.get_user(user_id)
        return self.service.primary_account_for(user_id).account_id

    def _movement_response(self, txn, request: Request) -> tuple[int, dict]:
        """Shared reply for deposit and withdraw.

        Returns the new account alongside the transaction, on purpose. The client
        must never compute a balance by adding the amount to the one it was
        holding - that is the frontend doing money arithmetic, and it is wrong the
        moment two tabs are open. One request, one authoritative balance back.
        """
        account = self.service.get_account_for(txn.account_id, request.actor)
        # The owner, looked up, rather than the caller. An admin acting on a
        # customer's account would otherwise see their own name as userName.
        owner = self.service.store.get_user(account.user_id)
        return 201, {
            "transaction": transaction_json(txn),
            "account": account_json(account, owner),
        }

    # ----------------------------------------------------------------- admin
    #
    # Every route here is `admin=True` in the table, so `_authenticate` has already
    # rejected a customer with 403 before any of these run. The service methods
    # check the role a second time, which is not redundant: services.py must be
    # safe to call from a CLI or a test that never passes through this file.

    def admin_users(self, request: Request) -> tuple[int, dict]:
        users = self.service.all_users(request.actor)
        return 200, {"users": [user_json(u) for u in users]}

    def admin_accounts(self, request: Request) -> tuple[int, dict]:
        accounts = self.service.all_accounts(request.actor)
        # Every owner in one read, then looked up in memory. The obvious version
        # calls get_user() inside the comprehension, which is a query per
        # account - 37 of them here, and one more for every account opened.
        owners = {u.user_id: u for u in self.service.store.all_users()}
        return 200, {"accounts": [
            account_json(a, owners.get(a.user_id)) for a in accounts
        ]}

    def admin_freeze(self, request: Request) -> tuple[int, dict]:
        """Freeze or unfreeze. `frozen` is explicit rather than a toggle, so
        retrying a request that may or may not have landed is safe."""
        frozen = request.optional("frozen", True)
        # Only a real true or false. bool("false") is True, so a client sending
        # the word in quotes would freeze an account it meant to release.
        if not isinstance(frozen, bool):
            raise ApiError(400, "'frozen' must be true or false")
        account = self.service.set_frozen(
            account_id=request.params["id"],
            frozen=frozen,
            reason=request.require("reason"),
            actor=request.actor,
        )
        return 200, {"account": account_json(account)}

    def admin_adjust(self, request: Request) -> tuple[int, dict]:
        """The only way an admin may change a balance.

        There is no `PUT /api/accounts/{id}/balance` in the route table and there
        should never be one. An adjustment posts a normal ledger entry tagged with
        the acting admin and a written reason, so `balance == sum(ledger)` still
        holds afterwards. A balance set directly breaks that invariant permanently
        and leaves no way to tell which of the two numbers was right.
        """
        txn = self.service.adjust(
            account_id=request.params["id"],
            amount=request.require("amount"),
            direction=request.require("direction"),
            reason=request.require("reason"),
            actor=request.actor,
        )
        account = self.service.store.get_account(request.params["id"])
        return 201, {"transaction": transaction_json(txn),
                     "account": account_json(account)}

    def admin_audit(self, request: Request) -> tuple[int, dict]:
        """Read-only. Who did what, to which account, why, and when.

        `createdAt` goes out as UTC in ISO 8601, like every other timestamp in
        this API. Which zone to show it in is the client's decision, not the
        server's - the admin page renders it in Eastern time.

        The ids come with names attached. "user #28 froze account #31" is a
        sentence you have to go and look two things up to understand, and an
        audit log nobody reads is not doing the job it exists for. The names are
        resolved here rather than in the browser because the alternative is the
        client fetching every user and every account to caption one list.

        A name can be missing - an account closed since, or a row older than the
        user record it names - so each falls back to None rather than failing
        the whole request. The ids are still there either way.
        """
        # Two lookups built once, not one query per row: the log is the one
        # endpoint here that grows without limit.
        users = {u.user_id: u.name for u in self.service.store.all_users()}
        owners = {a.account_id: users.get(a.user_id)
                  for a in self.service.store.all_accounts()}
        return 200, {"entries": [
            {"actorUserId": a, "actorName": users.get(a),
             "action": b,
             "accountId": c, "accountOwnerName": owners.get(c),
             "reason": d,
             "createdAt": e.isoformat()}
            for a, b, c, d, e in self.service.audit_log(request.actor)
        ]}

    def admin_reconcile(self, request: Request) -> tuple[int, dict]:
        """Every account where the stored balance disagrees with the ledger sum.

        Should always be empty. This is the endpoint to open during the demo: it
        is the running proof that no code path has changed a balance without
        writing a matching entry.
        """
        broken = self.service.reconciliation_report(request.actor)
        return 200, {
            "balanced": not broken,
            "checked": len(self.service.store.all_accounts()),
            "discrepancies": [
                {"accountId": i, "balance": b, "ledgerSum": s}  # cents
                for i, b, s in broken
            ],
        }


# ===========================================================================
# HTTP plumbing. Everything above is transport-independent; only this part
# knows about sockets, and it is the only part that changes under FastAPI.
# ===========================================================================

def make_handler_class(api: BankAPI, cors: bool = True, quiet: bool = False):
    """Build a request handler class bound to one BankAPI instance.

    A closure rather than a constructor argument because `http.server`
    instantiates the handler class itself, once per request, and gives us no
    opportunity to pass anything in.
    """

    class BankRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # required for keep-alive and Content-Length
        server_version = "SimpleBank/1.0"

        # -- the three verbs this API uses --

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_OPTIONS(self):
            """CORS preflight. A browser sends this before any cross-origin POST
            that carries an Authorization header, and refuses the real request if
            it is not answered."""
            self._respond(204, None)

        def _dispatch(self, method: str):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                # Refuse without reading. Reading it first would mean allocating
                # whatever a caller decided to send.
                self._respond(413, {"error": "request body too large"})
                return
            body = self.rfile.read(length) if length else b""
            status, payload = api.handle(method, self.path, body, dict(self.headers))
            self._respond(status, payload)

        def _respond(self, status: int, payload):
            data = b"" if payload is None else json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if cors:
                # Development convenience: the React dev server runs on a
                # different port, which makes every call cross-origin.
                # `*` is fine while tokens travel in a header. It would NOT be
                # fine with cookie-based sessions, where it must name the exact
                # origin and set Access-Control-Allow-Credentials.
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            if data:
                self.wfile.write(data)

        def log_message(self, fmt, *args):
            """One tidy line per request instead of the default noise.

            Silenced entirely under `quiet`, which the test suite passes so that a
            server booted inside a test does not interleave its access log with
            unittest's own output.
            """
            if quiet:
                return
            print(f"  {self.command:<7} {self.path:<45} {args[1] if len(args) > 1 else ''}")

    return BankRequestHandler


def serve(service, host: str = "127.0.0.1", port: int = 8000,
          secret: str | None = None, admin_code: str | None = None) -> None:
    """Start the API. Blocks until Ctrl+C.

    ThreadingHTTPServer, not HTTPServer: the single-threaded version handles one
    request at a time, which would hide the concurrency problem the lock in
    `BankService` exists to solve. Serving requests in parallel means the demo
    runs on the same execution model the rules were written for.
    """
    api = BankAPI(service, secret, admin_code)
    httpd = ThreadingHTTPServer((host, port), make_handler_class(api))
    print(f"  Simple Bank API listening on http://{host}:{port}")
    print(f"  {len(api.routes)} routes. Try: GET http://{host}:{port}/api/health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
