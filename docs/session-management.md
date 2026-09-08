# Session Management & Error Handling

This document covers how the integration handles authentication, session recovery, retry delays, and various failure modes.

## Exception Hierarchy

```
JablotronError                       # Base exception for all Jablotron errors
├── JablotronAuthError               # Authentication failed (wrong credentials)
├── JablotronNetworkError            # Network / server errors (5xx, connection failures)
└── JablotronSessionError            # Session-level issues resolvable by re-login
```

## Login Failure Flow

Occurs during initial setup (config flow validation) or during automatic login.

**Causes**: Wrong username/password, network unreachable, API down.

**Flow**:
1. `login()` POSTs the credentials to `userAuthorize.json` on `api.jablonet.net`
2. On `JablotronAuthError` (HTTP 401 / `USER.LOGIN.INVALID-CREDENTIALS`): re-raised as-is (from config flow shows error to user, from coordinator raises `ConfigEntryAuthFailed` → triggers HA reauth flow)
3. On `JablotronSessionError` or `JablotronNetworkError`: wrapped in session error with context

**Config flow result**: Error displayed in UI ("Cannot connect" or "Invalid authentication credentials").

## Normal Session Recovery (No Delay)

The most common failure — the API session expires while the coordinator is polling.

**Detection**: `dataUpdate.json` (or any data/control call) returns HTTP 401 with `USER.SESSION.EXPIRED` → the client raises `JablotronSessionError`.

**Recovery flow** (inside `_with_session_handling()`):
1. Catch `JablotronSessionError` from API call
2. Call `_reset_session()` — clears cookies, closes session, sets to None
3. Attempt re-login immediately (no delay)
4. If re-login succeeds → retry the original API call (skipped for non-idempotent PGM commands, see below)
5. If the retried API call fails again with a session error (sticky expiry) → arm the retry delay
6. Return data on success

**Recovery time**: 2–5 seconds (two requests: re-login + retry).

**Non-idempotent commands**: `control_pgm()` accepts `retry_on_relogin=False`. Switches for `pgorPulse` PGMs pass it — if the session expired while a pulse command was in flight, the command is *not* re-sent after recovery (it may already have executed), and a `JablotronSessionError` is raised instead so the switch can reconcile via the next status poll.

## Delayed Recovery (Retry Backoff)

When **re-login itself fails** (e.g., credentials are invalid, network is down, or API is unreachable), or when the API keeps failing after a successful re-login.

**Flow**:
1. Catch `JablotronSessionError` from original API call → attempt re-login
2. Re-login fails (wrong credentials, network down, API unreachable — any error), *or* the retried API call fails again
3. Set `_next_retry_time = now + retry_delay` (default 300 seconds / 5 minutes)
4. Raise error up to coordinator

**Coordinator behavior during retry delay**:
1. Before every update, coordinator calls `client.get_next_retry_time()`
2. If returned value exists AND is in the future → skip API call entirely
3. Raise `UpdateFailed` with human-readable message: "Session error - retrying in X minutes Y seconds"
4. All entities show as "Unavailable" (Home Assistant marks them unavailable)

**When delay expires**:
1. Next coordinated update checks `get_next_retry_time()` — value is now in the past
2. Clears the timer call `client.reset_session_and_clear_retry()` → full session reset
3. Proceeds with normal API call and recovery flow

## Initial Login Failure

If the very first login fails (coordinator's first refresh or config flow validation):

1. `_with_session_handling()` catches the error during initial login
2. Sets retry delay immediately: `_next_retry_time = now + retry_delay`
3. Raises `JablotronSessionError` → coordinator raises `UpdateFailed`
4. Home Assistant shows the entities as unavailable; no reauth flow is triggered
5. Subsequent coordinator polls hit the delay check and skip

If the initial login fails with `JablotronAuthError` (invalid credentials), the
coordinator raises `ConfigEntryAuthFailed` instead, which triggers the reauth flow.

## Error Scenarios Summary

| Scenario | Trigger | Recovery mechanism | Delay | UI state |
|----------|---------|-------------------|-------|----------|
| Session expired mid-poll | API returns HTTP 401 / `USER.SESSION.EXPIRED` | Re-login + immediate retry | None (2-5s) | Entities stay available |
| Re-login fails | Credentials invalid, network down | Set retry delay | Configurable (default 5 min) | "Unavailable" |
| API fails again after re-login | Sticky server-side expiry | Set retry delay | Configurable | "Unavailable" |
| Network error on status fetch | Timeout, DNS failure | Wrapped as session error → re-login trigger | If re-login succeeds: none; if fails: delay | Depends |
| Initial login fails (network) | Network/API down at setup | Retry delay set for recovery attempts | Configurable | "Unavailable" |
| Initial login fails (credentials) | Wrong username/password at setup | None — auth error propagates | — | Reauth flow |

## Reset Session

Called in two places:

1. **On every `JablotronSessionError`** from an API call (automatic recovery)
2. **When retry delay expires** (`reset_session_and_clear_retry()`), called by coordinator to clear cached state before retrying

Implementation clears the cookie jar, closes the aiohttp session, and sets `self.session = None`. Next request creates a fresh session. On integration unload the client logs out (`logout.json`) before closing the session.

## Configuration Constants (from `const.py`)

| Constant | Default | Description | Configurable via options flow? |
|----------|---------|-------------|-------------------------------|
| `DEFAULT_SCAN_INTERVAL` | 300 | Coordinator poll interval in seconds | Yes — "Update interval" |
| `DEFAULT_TIMEOUT` | 10 | HTTP request timeout per call in seconds | Yes — "Request timeout" |
| `DEFAULT_RETRY_DELAY` | 300 | Backoff period when recovery fails, in seconds | Yes — "Retry delay after errors" |

## Debug Logging

Enable with:

```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```

**Key log messages** (chronological order during normal operation):

1. `"Performing login to the MyJABLOTRON API (api.jablonet.net)"` — login started
2. `"Login successful - API session established"` — session cookie obtained
3. `"No session found, performing initial login"` — on first API call or after reset
4. `"Discovered JA-100 service ..."` — service auto-discovery (only when no service ID is configured)
5. `"Attempting immediate re-login after session error"` — recovery attempted
6. `"Re-login successful"` — recovery succeeded
7. `"Re-login failed after session error: ..."` / `"API call failed again after re-login: ..."` — recovery failed, delay set
8. `"Waiting for retry delay to expire: Xm Ys remaining"` — skipping update during delay

## Test Script

A standalone script at `test_jablonet.py` probes the v2.2 API with real credentials for debugging:

```bash
python test_jablonet.py <username> <password> [service_id]
```

Performs login, lists account services, dumps the raw `dataUpdate.json` response, probes for extra data types (e.g. PIR), and prints the legacy-shaped dict the integration builds from it. It never triggers control calls.
