"""Jablotron API client with simple session management."""
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
    ACTIVE_TAB_HEAT,
    API_BASE_URL,
    API_CONTROL_URL,
    API_LOGIN_URL,
    API_STATUS_URL,
    DEFAULT_FIREFOX_UA,
    DEFAULT_RETRY_DELAY,
    JA_STATUS_VALUE,
    LOGIN_TYPE_VALUE,
    UID_SUFFIX,
)

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
    """Client for Jablotron API with automatic session management."""

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
    ) -> tuple[int, str]:
        """
        Thin HTTP wrapper for all requests.

        Returns: (status_code, response_text)
        Raises:
            JablotronNetworkError: On network errors or 5xx server errors.
            JablotronSessionError: On 4xx client errors.
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

            if status != 200:
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

    async def _http_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: str | None = None,
        expected_status: int = 200,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        HTTP request expecting JSON response.

        Returns: Parsed JSON dict
        Raises: JablotronSessionError if response is not valid JSON or status doesn't match
        """
        status, text = await self._http_request(method, url, headers, data, timeout=timeout)

        try:
            json_data = json.loads(text)
        except json.JSONDecodeError as e:
            _LOGGER.error("Invalid JSON from %s: %s", url, text[:200])
            raise JablotronSessionError("Invalid JSON response") from e

        # Check if JSON contains error status (like status: 300 for session expired)
        if isinstance(json_data, dict) and "status" in json_data:
            if json_data["status"] != expected_status:
                _LOGGER.warning(
                    f"API returned status {json_data['status']}, expected {expected_status}"
                )
                raise JablotronSessionError(
                    f"API status {json_data['status']} (expected {expected_status})"
                )

        return json_data

    # ===== Session Management =====

    def _get_common_headers(self) -> dict[str, str]:
        """Get common browser headers that all requests share."""
        return {
            "User-Agent": DEFAULT_FIREFOX_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Upgrade-Insecure-Requests": "1",
        }

    async def _reset_session(self):
        """Completely reset the session - close and clear everything."""
        _LOGGER.info("Resetting session (clearing cookies and closing connection)")
        if self.session and not self.session.closed:
            self.session.cookie_jar.clear()
            await self.session.close()
        self.session = None

    async def _visit_homepage(self):
        """Step 1: Visit homepage to get initial PHPSESSID cookie."""
        _LOGGER.debug("Step 1: Visiting homepage for PHPSESSID")

        # Regular browser visit - use common headers as-is
        headers = self._get_common_headers()

        await self._http_request("GET", API_BASE_URL, headers=headers)
        _LOGGER.debug("Homepage visit successful")

    async def _login_post(self):
        """Step 2: POST credentials to login.php."""
        _LOGGER.debug("Step 2: POSTing credentials to login.php")

        login_data = {
            "login": self.username,
            "heslo": self.password,
            "aStatus": JA_STATUS_VALUE,
            "loginType": LOGIN_TYPE_VALUE,
        }

        # Start with common browser headers, then override for API request
        headers = self._get_common_headers()
        headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": f"{API_BASE_URL}/",
        })
        # Remove Upgrade-Insecure-Requests for API calls
        headers.pop("Upgrade-Insecure-Requests", None)

        # Login typically returns empty JSON {} or similar on success
        status, text = await self._http_request("POST", API_LOGIN_URL, headers=headers, data=urlencode(login_data))

        if status != 200:
            _LOGGER.error("Login failed with HTTP status %s", status)
            raise JablotronAuthError(f"Login failed: HTTP {status}")

        try:
            json_response = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            _LOGGER.error("Login returned non-JSON response, assuming success (HTTP 200)")
            json_response = {}

        if isinstance(json_response, dict) and json_response.get("errorMessage"):
            error_message = json_response["errorMessage"]
            _LOGGER.error("Login failed with error message: %s", error_message)
            raise JablotronAuthError(f"Login failed: {error_message}")

        _LOGGER.debug("Login POST successful")

    async def _get_cloud_page(self):
        """Step 3: GET /cloud to obtain the lastMode cookie."""
        _LOGGER.debug("Step 3: Getting /cloud page for lastMode cookie")

        # Regular browser request - use common headers and add Referer
        headers = self._get_common_headers()
        headers["Referer"] = f"{API_BASE_URL}/"

        await self._http_request("GET", f"{API_BASE_URL}/cloud", headers=headers)
        _LOGGER.debug("/cloud page retrieved successfully")

    async def _get_ja100_app(self):
        """Step 4: GET /app/ja100 to initialize JA100 app session."""
        _LOGGER.debug("Step 4: Getting JA100 app page")

        url = f"{API_BASE_URL}/app/ja100"
        if self.service_id:
            url += f"?service={self.service_id}"

        # Regular browser request - use common headers and add Referer
        headers = self._get_common_headers()
        headers["Referer"] = f"{API_BASE_URL}/cloud"

        await self._http_request("GET", url, headers=headers)
        _LOGGER.debug("JA100 app page retrieved successfully")

    async def login(self):
        """
        Perform a 4-step login sequence.

        Raises:
            JablotronAuthError: On authentication failure (wrong credentials)
            JablotronSessionError: On other failures (network, server errors, etc.)
        """
        _LOGGER.info("Performing full login to Jablotron Cloud")

        try:
            await self._visit_homepage()
            await self._login_post()
            await self._get_cloud_page()
            await self._get_ja100_app()
            _LOGGER.info("Login successful - all cookies obtained")

        except JablotronAuthError:
            # Authentication failed, re-raise it to be handled by the coordinator
            _LOGGER.error("Authentication failed: Invalid credentials")
            raise
        except (JablotronNetworkError, JablotronSessionError) as e:
            # Any other error during login is treated as a session/network problem
            _LOGGER.error("Login failed due to network/session error: %s", e)
            raise JablotronSessionError(f"Login failed: {e}") from e

    # ===== API Methods =====

    async def get_status(self) -> dict[str, Any]:
        """
        Get the current status from stav.php.

        Handles session expiry automatically by catching JablotronSessionError
        and letting the coordinator retry via the delay mechanism.
        """
        return await self._with_session_handling(self._fetch_status)

    async def control_pgm(
        self, pgm_id: str, status: int, *, retry_on_relogin: bool = True
    ) -> dict[str, Any]:
        """Control a PGM output (turn on/off).

        Args:
            pgm_id: PGM identifier from the status payload.
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
            return await api_func()

        except JablotronError as e:
            # Catch-all for other Jablotron errors (e.g., JablotronAuthError from api_func)
            _LOGGER.warning("API call failed: %s", e)
            raise

    async def _fetch_status(self) -> dict[str, Any]:
        """Internal method to fetch status from stav.php."""
        referer = f"{API_BASE_URL}/app/ja100"
        if self.service_id:
            referer += f"?service={self.service_id}"

        # Start with common browser headers, then override for API request
        headers = self._get_common_headers()
        headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": referer,
        })
        # Remove Upgrade-Insecure-Requests for API calls
        headers.pop("Upgrade-Insecure-Requests", None)

        # Use 'heat' to get temperature sensors and PGM data
        payload = ACTIVE_TAB_HEAT
        if self.service_id:
            payload += f"&service_id={self.service_id}"

        _LOGGER.debug("Fetching status from %s", API_STATUS_URL)

        # This will raise JablotronSessionError if status != 200 in JSON
        data = await self._http_json("POST", API_STATUS_URL, headers=headers, data=payload)

        _LOGGER.debug("Status fetched successfully: %s bytes", len(str(data)))
        return data

    async def _control_pgm_internal(self, pgm_id: str, status: int) -> dict[str, Any]:
        """Internal method to control a PGM output."""
        referer = f"{API_BASE_URL}/app/ja100"
        if self.service_id:
            referer += f"?service={self.service_id}"

        # Start with common browser headers, then override for API request
        headers = self._get_common_headers()
        headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": referer,
        })
        # Remove Upgrade-Insecure-Requests for API calls
        headers.pop("Upgrade-Insecure-Requests", None)

        # Build the state_name (e.g., PGM_7 for pgm_id "6")
        try:
            pgm_id_int = int(str(pgm_id))
        except (ValueError, TypeError):
            raise JablotronError(f"Invalid PGM ID: {pgm_id}") from None
        pgm_index = pgm_id_int + 1
        state_name = f"PGM_{pgm_index}"
        uid = f"{state_name}{UID_SUFFIX}"

        payload_data = {
            "section": state_name,
            "status": str(status),
            "code": self.pgm_code,
            "uid": uid,
        }

        _LOGGER.debug("Controlling %s: status=%s", state_name, status)


        # Control endpoint doesn't use the "status" field in JSON, so we don't validate it
        # Just check for HTTP 200
        status_code, text = await self._http_request(
            "POST", API_CONTROL_URL, headers=headers, data=urlencode(payload_data)
        )

        try:
            data = json.loads(text)
            _LOGGER.debug("Control response: %s", data)

            # Check for PGM-specific errors in response
            if "authorization" in data and data["authorization"] != 200:
                _LOGGER.error("PGM control authorization failed: %s", data)
                raise JablotronSessionError(f"Authorization failed: {data['authorization']}")

            if "responseCode" in data and data["responseCode"] != 200:
                _LOGGER.error("PGM control failed with response code: %s", data)
                raise JablotronSessionError(f"Response code: {data['responseCode']}")

            return data

        except json.JSONDecodeError as e:
            _LOGGER.error("Invalid JSON from control API: %s", text[:200])
            raise JablotronSessionError("Invalid control response") from e

    async def async_close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

