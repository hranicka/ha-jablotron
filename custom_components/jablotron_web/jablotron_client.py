"""Jablotron MyJABLOTRON API v2.2 client with session management.

Talks to the mobile-app API on api.jablonet.net (the same API the official
MyJABLOTRON app uses). The old www.jablonet.net web endpoints are closed to
non-browser clients since the 2026 web rework (TLS fingerprinting at nginx
plus reCAPTCHA on the jip.jablotron.cloud SSO login), so the integration
speaks the mobile API instead.

Session model: `userAuthorize.json` establishes a PHPSESSID cookie session;
the cookie alone authenticates data/control calls. Session expiry surfaces
as HTTP 401 / `USER.SESSION.EXPIRED` and is recovered by re-login.
"""
import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import aiohttp
from aiohttp import ClientTimeout

from homeassistant.core import HomeAssistant

from .const import (
    API_ACCEPT_LANGUAGE,
    API_CLIENT_VERSION,
    API_CONTROL_SEGMENT_URL,
    API_DATA_UPDATE_URL,
    API_LOGOUT_URL,
    API_SERVICE_LIST_URL,
    API_SYSTEM_NAME,
    API_THERMO_DEVICES_URL,
    API_USER_AUTHORIZE_URL,
    API_USER_AGENT,
    API_VENDOR_ID,
    DEFAULT_RETRY_DELAY,
    ERROR_INVALID_CREDENTIALS,
    ERROR_SESSION_EXPIRED,
    PGM_STATE_ON,
    SERVICE_TYPE_JA100,
)
from .v22_adapter import adapt_control_response, adapt_data_update

_LOGGER = logging.getLogger(__name__)


class JablotronError(Exception):
    """Base exception for this integration."""


class JablotronAuthError(JablotronError):
    """Exception for authentication errors."""


class JablotronNetworkError(JablotronError):
    """Exception for network errors."""


class JablotronSessionError(JablotronError):
    """Exception for session errors that can be resolved by re-login."""


class JablotronClient:
    """Client for the Jablotron MyJABLOTRON API v2.2 with session management."""

    def __init__(
        self,
        username: str,
        password: str,
        service_id: str,
        hass: HomeAssistant,
        pgm_code: str = "",
        timeout: int = 10,
        retry_delay: int = DEFAULT_RETRY_DELAY,
    ):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.service_id = service_id
        self.hass = hass
        self.pgm_code = pgm_code
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.session: aiohttp.ClientSession | None = None
        self._next_retry_time: float | None = None
        self._lock = asyncio.Lock()
        self._discovered_service_id: str | None = None

    def get_next_retry_time(self) -> float | None:
        """Get timestamp when next retry is allowed.

        Returns:
            Timestamp (seconds since epoch) when retry is allowed, or None if no delay is active.
        """
        return self._next_retry_time

    async def reset_session_and_clear_retry(self):
        """Reset the session and clear the retry timer. Called when retry delay expires."""
        _LOGGER.info("Clearing retry timer and resetting session for fresh retry")
        async with self._lock:
            self._next_retry_time = None
            await self._reset_session()

    # ===== HTTP Client Wrapper =====

    async def _http_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: str | None = None,
        timeout: int | None = None,
        *,
        raise_http_errors: bool = True,
    ) -> tuple[int, str]:
        """
        Thin HTTP wrapper for all requests.

        Returns: (status_code, response_text)
        Raises:
            JablotronNetworkError: On network errors or 5xx server errors.
            JablotronSessionError: On 4xx client errors (unless
                raise_http_errors=False — callers that need to inspect the
                error body use that, e.g. to tell bad credentials from a
                dead session).
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())

        request_timeout_seconds = timeout if timeout is not None else self.timeout

        try:
            request_timeout = ClientTimeout(total=request_timeout_seconds)
            if method.upper() == "GET":
                async with self.session.get(
                    url, headers=headers, timeout=request_timeout
                ) as response:
                    text = await response.text()
                    status = response.status
            else:  # POST
                async with self.session.post(
                    url, headers=headers, data=data, timeout=request_timeout
                ) as response:
                    text = await response.text()
                    status = response.status

            if raise_http_errors and status != 200:
                _LOGGER.error("HTTP %s %s returned status %s", method, url, status)
                if 400 <= status < 500:
                    raise JablotronSessionError(f"Request failed: HTTP {status}")
                if 500 <= status < 600:
                    raise JablotronNetworkError(f"Server error: HTTP {status}")
                raise JablotronNetworkError(f"Unexpected HTTP status: {status}")

            return status, text

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Network error during %s %s: %s", method, url, e)
            raise JablotronNetworkError(f"Network error: {e}") from e
        except JablotronError:
            raise
        except Exception as e:
            _LOGGER.error("Unexpected error during %s %s: %s", method, url, e)
            raise JablotronError(f"Request failed: {e}") from e

    # ===== v2.2 helpers =====

    @staticmethod
    def _parse_json_object(text: str | None) -> dict[str, Any]:
        """Parse a response body as a JSON object (empty dict on failure)."""
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON response: %s", text[:200])
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _first_error_code(payload: dict[str, Any]) -> str | None:
        """Extract the first errors[].code from a v2.2 error payload."""
        errors = payload.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict) and error.get("code"):
                    return str(error["code"])
        return None

    def _check_api_errors(self, http_status: int, payload: dict[str, Any], context: str) -> None:
        """Raise JablotronSessionError when an api/2.2 call reports a dead session.

        Session expiry arrives as HTTP 401 (optionally with the
        USER.SESSION.EXPIRED error code) and is recovered by re-login.
        """
        error_code = self._first_error_code(payload)
        if error_code == ERROR_SESSION_EXPIRED or http_status == 401:
            raise JablotronSessionError(
                f"{context}: session expired (HTTP {http_status}, {error_code or 'no error code'})"
            )

    def _get_common_headers(self) -> dict[str, str]:
        """Headers imitating the official MyJABLOTRON mobile client."""
        return {
            "User-Agent": API_USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": API_ACCEPT_LANGUAGE,
            "Accept-Encoding": "*",
            "x-vendor-id": API_VENDOR_ID,
            "x-client-version": API_CLIENT_VERSION,
        }

    def _json_headers(self) -> dict[str, str]:
        """Common headers plus a JSON content type."""
        headers = self._get_common_headers()
        headers["Content-Type"] = "application/json"
        return headers

    def _form_headers(self) -> dict[str, str]:
        """Common headers plus a form content type."""
        headers = self._get_common_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return headers

    async def _reset_session(self):
        """Completely reset the session - close and clear everything."""
        _LOGGER.info("Resetting session (clearing cookies and closing connection)")
        if self.session and not self.session.closed:
            self.session.cookie_jar.clear()
            await self.session.close()
        self.session = None

    # ===== Session Management =====

    async def login(self):
        """
        Authenticate against api.jablonet.net and establish the API session.

        Raises:
            JablotronAuthError: On authentication failure (wrong credentials)
            JablotronSessionError: On other failures (network, server errors, etc.)
        """
        _LOGGER.info("Performing login to the MyJABLOTRON API (api.jablonet.net)")

        body = json.dumps({"login": self.username, "password": self.password})
        try:
            status, text = await self._http_request(
                "POST",
                API_USER_AUTHORIZE_URL,
                headers=self._json_headers(),
                data=body,
                raise_http_errors=False,
            )
        except JablotronError as err:
            # Network/unexpected errors during login must surface as session
            # errors: the coordinator's initial-login path arms its retry
            # delay only for JablotronSessionError.
            _LOGGER.error("Login failed due to network/session error: %s", err)
            raise JablotronSessionError(f"Login failed: {err}") from err
        payload = self._parse_json_object(text)
        error_code = self._first_error_code(payload)

        if status == 200 and payload.get("http-code", 200) == 200:
            _LOGGER.info("Login successful - API session established")
            return

        if status == 401 or error_code == ERROR_INVALID_CREDENTIALS or payload.get("http-code") == 401:
            _LOGGER.error("Authentication failed: invalid credentials")
            raise JablotronAuthError(f"Login failed: {error_code or f'HTTP {status}'}")

        _LOGGER.error("Login failed due to network/session error: HTTP %s %s", status, error_code or text[:120])
        raise JablotronSessionError(f"Login failed: HTTP {status} {error_code or ''}".rstrip())

    # ===== API Methods =====

    async def get_status(self) -> dict[str, Any]:
        """
        Get the current status of all service data.

        Handles session expiry automatically by catching JablotronSessionError
        and letting the coordinator retry via the delay mechanism.
        """
        return await self._with_session_handling(self._fetch_status)

    async def control_pgm(
        self, pgm_id: str, status: int, *, retry_on_relogin: bool = True
    ) -> dict[str, Any]:
        """Control a PGM output (turn on/off).

        Args:
            pgm_id: PGM identifier as used in the status payload.
            status: 1 to switch on, 0 to switch off.
            retry_on_relogin: Retry the command after a session recovery.
                Disable for non-idempotent commands (pulse PGMs) where a
                retry could execute the command twice.
        """
        return await self._with_session_handling(
            lambda: self._control_pgm_internal(pgm_id, status),
            retry_on_relogin=retry_on_relogin,
        )

    async def _with_session_handling(
        self,
        api_func: Callable[[], Awaitable[dict[str, Any]]],
        *,
        retry_on_relogin: bool = True,
    ) -> dict[str, Any]:
        """
        Wrapper for API calls with automatic session handling.

        Flow:
        1. Ensure the session exists (login if needed)
        2. Try API call
        3. On JablotronSessionError -> reset session, try immediate re-login
        4. If re-login succeeds -> retry API call (unless retry_on_relogin=False)
        5. If re-login fails (any reason) -> set a configurable retry delay
        """
        async with self._lock:
            # Ensure we have a session — only needed on first call or after expiry
            if self.session is None or self.session.closed or len(self.session.cookie_jar) == 0:
                _LOGGER.info("No session found, performing initial login")
                try:
                    await self.login()
                except JablotronSessionError as e:
                    # Initial login failed - set retry delay
                    self._next_retry_time = time.time() + self.retry_delay
                    minutes = self.retry_delay // 60
                    _LOGGER.error("Initial login failed. Will retry in %s minutes.", minutes)
                    raise

        # API call outside lock — cookies are valid and stable across concurrent calls
        try:
            result = await api_func()
            self._next_retry_time = None
            return result

        except JablotronNetworkError:
            # Network error during API call - re-raise as-is (transient, no re-login needed)
            raise

        except JablotronSessionError as e:
            # Session error during API call - reset and try immediate re-login
            _LOGGER.error("Session error detected during API call: %s", e)

            async with self._lock:
                await self._reset_session()
                _LOGGER.info("Attempting immediate re-login after session error")
                try:
                    await self.login()
                    _LOGGER.info("Re-login successful")
                except JablotronAuthError as err:
                    _LOGGER.error("Re-login failed: %s", err)
                    self._next_retry_time = time.time() + self.retry_delay
                    raise
                except Exception as err:
                    # Any other re-login failure (network, server) — back off too,
                    # otherwise the coordinator would retry the full login every poll
                    _LOGGER.warning("Re-login failed after session error: %s", err)
                    self._next_retry_time = time.time() + self.retry_delay
                    raise

            # Retry API call outside lock — cookies are now valid
            if not retry_on_relogin:
                # The command may or may not have executed before the session
                # error; retrying could fire it twice. The session itself is
                # healthy again, so let the caller decide whether to repeat.
                raise JablotronSessionError(
                    f"Command not retried after session recovery (non-idempotent): {e}"
                ) from e
            try:
                return await api_func()
            except JablotronSessionError as retry_err:
                # Even after a successful re-login the API can keep failing
                # (sticky expiry) — arm the backoff instead of hammering
                # re-login on every poll.
                _LOGGER.error("API call failed again after re-login: %s", retry_err)
                self._next_retry_time = time.time() + self.retry_delay
                raise

        except JablotronError as e:
            # Catch-all for other Jablotron errors (e.g., JablotronAuthError from api_func)
            _LOGGER.warning("API call failed: %s", e)
            raise

    # ===== Service resolution =====

    async def _resolve_service_id(self) -> str:
        """Return the configured service id, or discover the first JA-100 service."""
        if self.service_id:
            service_id = str(self.service_id).strip()
            if not service_id.isdigit():
                raise JablotronError(
                    f"Invalid service ID {self.service_id!r}: must be numeric "
                    "(see the service list in test_jablonet.py output)"
                )
            return service_id
        if self._discovered_service_id:
            return self._discovered_service_id

        services = await self._fetch_service_list()
        for service in services:
            service_type = str(service.get("service-type", "")).lower()
            service_status = str(service.get("status", "")).upper()
            if service_type == SERVICE_TYPE_JA100 and service_status == "ENABLED":
                self._discovered_service_id = str(service.get("service-id"))
                _LOGGER.info(
                    "Discovered JA-100 service %s (%s)",
                    self._discovered_service_id,
                    service.get("name", ""),
                )
                return self._discovered_service_id

        raise JablotronError(
            "No enabled JA-100 service found on this account. "
            "Set the service ID manually in the integration options if you have multiple services."
        )

    async def _fetch_service_list(self) -> list[dict[str, Any]]:
        """Fetch the account's services (id, name, type, status)."""
        status, text = await self._http_request(
            "POST",
            API_SERVICE_LIST_URL,
            headers=self._json_headers(),
            data=json.dumps({"list-type": "EXTENDED", "visibility": "VISIBLE"}),
            raise_http_errors=False,
        )
        payload = self._parse_json_object(text)
        self._check_api_errors(status, payload, "Service list fetch")
        if status != 200:
            raise JablotronNetworkError(f"Service list fetch failed: HTTP {status}")

        services = (payload.get("data") or {}).get("services")
        return services if isinstance(services, list) else []

    # ===== Internal methods =====

    async def _fetch_status(self) -> dict[str, Any]:
        """Fetch all service data and translate it into the legacy stav.php shape."""
        service_id = await self._resolve_service_id()

        request = [
            {
                "filter_data": [
                    {"data_type": "section"},
                    {"data_type": "pgm"},
                    {"data_type": "thermometer"},
                    {"data_type": "thermostat"},
                ],
                "service_type": SERVICE_TYPE_JA100,
                "service_id": int(service_id),
                "data_group": "serviceData",
            }
        ]
        body = urlencode({"data": json.dumps(request), "system": API_SYSTEM_NAME})

        _LOGGER.debug("Fetching status from %s (service %s)", API_DATA_UPDATE_URL, service_id)

        status, text = await self._http_request(
            "POST",
            API_DATA_UPDATE_URL,
            headers=self._form_headers(),
            data=body,
            raise_http_errors=False,
        )
        payload = self._parse_json_object(text)
        self._check_api_errors(status, payload, "Status fetch")

        if payload.get("status") is False:
            message = payload.get("error_message") or "unknown error"
            # Dead sessions don't always arrive as HTTP 401 — long-lived
            # sessions have been observed getting HTTP 200 + status:false
            # with no error code. Route it through session recovery: re-login
            # fixes the session case, and any other cause just fails the
            # retry and arms the retry-delay backoff.
            _LOGGER.error("Status fetch failed: %s (response: %s)", message, text[:200])
            raise JablotronSessionError(f"Status fetch failed: {message}")
        if status != 200:
            raise JablotronNetworkError(f"Status fetch failed: HTTP {status}")

        # Live thermometer readings — dataUpdate's thermometer block is only
        # a stale cache ("unknown" for online peripheries).
        thermo_payload = None
        try:
            thermo_payload = await self._fetch_thermo_states(service_id)
        except JablotronSessionError:
            raise
        except JablotronError as err:
            # Sections/PGMs are still fresh — degrade to cached temperatures
            # rather than failing the whole update.
            _LOGGER.warning("Thermometer fetch failed (continuing without live values): %s", err)

        return adapt_data_update(
            payload,
            service_id=service_id,
            has_pgm_code=bool(self.pgm_code),
            thermo_payload=thermo_payload,
        )

    async def _fetch_thermo_states(self, service_id: str) -> dict[str, Any]:
        """Fetch live thermo device states (readings + timestamps)."""
        body = json.dumps(
            {
                "connect-device": False,
                "list-type": "FULL",
                "service-id": int(service_id),
                "service-states": True,
            }
        )
        status, text = await self._http_request(
            "POST",
            API_THERMO_DEVICES_URL,
            headers=self._json_headers(),
            data=body,
            raise_http_errors=False,
        )
        payload = self._parse_json_object(text)
        self._check_api_errors(status, payload, "Thermometer fetch")
        if status != 200:
            raise JablotronNetworkError(f"Thermometer fetch failed: HTTP {status}")
        return payload

    async def _control_pgm_internal(self, pgm_id: str, status: int) -> dict[str, Any]:
        """Switch a PGM output via controlSegment.json."""
        if not self.pgm_code:
            raise JablotronError("PGM control code is not configured")

        try:
            pgm_index = int(str(pgm_id)) + 1
        except (ValueError, TypeError):
            raise JablotronError(f"Invalid PGM ID: {pgm_id}") from None
        segment_id = f"PGM_{pgm_index}"

        service_id = await self._resolve_service_id()
        body = urlencode(
            {
                "service": SERVICE_TYPE_JA100,
                "serviceId": service_id,
                "segmentId": segment_id,
                "segmentKey": segment_id.lower(),
                "expected_status": "set" if status == PGM_STATE_ON else "unset",
                "control_time": "0",
                "control_code": self.pgm_code,
                "system": API_SYSTEM_NAME,
            }
        )

        _LOGGER.debug(
            "Controlling %s: expected_status=%s",
            segment_id,
            "set" if status == PGM_STATE_ON else "unset",
        )

        http_status, text = await self._http_request(
            "POST",
            API_CONTROL_SEGMENT_URL,
            headers=self._form_headers(),
            data=body,
            raise_http_errors=False,
        )
        payload = self._parse_json_object(text)

        # A dead session is recoverable via re-login. Other rejections (wrong
        # code, no permission) also surface as session errors so the existing
        # backoff and the non-idempotent pulse guard apply.
        self._check_api_errors(http_status, payload, "PGM control")

        if payload.get("status") is False:
            message = payload.get("error_message") or payload.get("error_status") or "control rejected"
            _LOGGER.error("PGM control failed for %s: %s", segment_id, message)
            raise JablotronSessionError(f"PGM control failed: {message}")
        if http_status != 200:
            raise JablotronNetworkError(f"PGM control failed: HTTP {http_status}")

        return adapt_control_response(status)

    async def async_close(self):
        """Log out (best effort) and close the aiohttp session."""
        if self.session and not self.session.closed and len(self.session.cookie_jar) > 0:
            try:
                await self._http_request(
                    "POST",
                    API_LOGOUT_URL,
                    headers=self._form_headers(),
                    data=urlencode({"system": API_SYSTEM_NAME}),
                    raise_http_errors=False,
                    timeout=5,
                )
            except JablotronError as err:
                _LOGGER.debug("Logout failed (ignored): %s", err)
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
