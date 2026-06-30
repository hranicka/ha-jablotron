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
1. `login()` calls `_visit_homepage()` → `_login_post()` → `_get_cloud_page()` → `_get_ja100_app()` sequentially
2. On `JablotronAuthError`: re-raised as-is (from config flow shows error to user, from coordinator raises `ConfigEntryAuthFailed` → triggers HA reauth flow)
3. On `JablotronSessionError` or `JablotronNetworkError`: wrapped in session error with context

**Config flow result**: Error displayed in UI ("Cannot connect" or "Invalid authentication credentials").

## Normal Session Recovery (No Delay)

The most common failure — session expires (HTTP status 300 from API) while the coordinator is polling.

**Detection**: `stav.php` returns `{"status": 300}` → `_http_json()` raises `JablotronSessionError`.

**Recovery flow** (inside `__with_session_handling()`):
1. Catch `JablotronSessionError` from API call
2. Call `_reset_session()` — clears cookies, closes session, sets to None
3. Attempt re-login immediately (no delay)
4. If re-login succeeds → retry the original API call
5. Return data on success

**Recovery time**: 2–5 seconds (two requests: re-login + retry).

## Delayed Recovery (Retry Backoff)

When **re-login itself fails** (e.g., credentials are invalid, network is down, or API is unreachable).

**Flow**:
1. Catch `JablotronSessionError` from original API call → attempt re-login
2. Re-login also fails with `JablotronAuthError` or `JablotronNetworkError`
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

## Network Error During Initial Login

If the very first login fails (coordinator's first refresh):

1. `_with_session_handling()` catches the error during initial login
2. Sets retry delay immediately: `_next_retry_time = now + retry_delay`
3. Raises `JablotronAuthError` → coordinator raises `ConfigEntryAuthFailed`
4. Home Assistant shows authentication error for the entity but does not trigger reauth flow (initial login is part of setup, not a runtime update)
5. Subsequent coordinator polls hit the delay check and skip

## Error Scenarios Summary

| Scenario | Trigger | Recovery mechanism | Delay | UI state |
|----------|---------|-------------------|-------|----------|
| Session expired mid-poll | API returns `status: 300` | Re-login + immediate retry | None (2-5s) | Entities stay available |
| Re-login fails | Credentials invalid, network down | Set retry delay | Configurable (default 5 min) | "Unavailable" |
| Network error on status fetch | Timeout, DNS failure | Wrapped as session error → re-login trigger | If re-login succeeds: none; if fails: delay | Depends |
| Initial login fails | Wrong credentials at setup | Retry delay set for recovery attempts | Configurable | Error in UI |

## Reset Session

Called in two places:

1. **On every `JablotronSessionError`** from an API call (automatic recovery)
2. **When retry delay expires** (`reset_session_and_clear_retry()`), called by coordinator to clear cached state before retrying

Implementation clears the cookie jar, closes the aiohttp session, and sets `self.session = None`. Next request creates a fresh session.

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

1. `"Performing full login to Jablotron Cloud"` — login started
2. `"[Step N]: ..." ` — each of the four login steps
3. `"Login successful - all cookies obtained"` — 4-step login complete
4. `"No session found, performing initial login"` — on first API call or after reset
5. `"Attempting immediate re-login after session error"` — recovery attempted
6. `"Re-login successful, retrying API call"` — recovery succeeded
7. `"Re-login failed after session error. Will retry in X minutes."` — recovery failed, delay set
8. `"Waiting for retry delay to expire: Xm Ys remaining"` — skipping update during delay

## Test Script

A standalone script at `test_jablonet.py` replicates the full 4-step login flow and sensor data fetching for debugging:

```bash
python test_jablonet.py <username> <password> [service_id]
```

Outputs HTTP status codes, cookie states per step, and parsed JSON for temperature sensors and PGM outputs. Uses its own `aiohttp.ClientSession` with `yarl.URL` for cookie filtering — no Home Assistant dependency.
