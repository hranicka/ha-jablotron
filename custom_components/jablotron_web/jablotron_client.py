"""Jablotron API Client with session management."""
import json
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import time
import aiohttp

from homeassistant.core import HomeAssistant

from .const import API_LOGIN_URL, API_STATUS_URL, API_BASE_URL, API_CONTROL_URL, RETRY_DELAY

_LOGGER = logging.getLogger(__name__)


class JablotronAuthError(Exception):
    """Jablotron authentication error."""


class JablotronTransientError(Exception):
    """Jablotron transient error (server errors, network issues) that should trigger retry."""


class JablotronClient:
    """Client for Jablotron API with automatic session management."""

    def __init__(self, username: str, password: str, service_id: str, hass: HomeAssistant, pgm_code: str = ""):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.service_id = service_id
        self.hass = hass
        self.pgm_code = pgm_code
        self.session: Optional[aiohttp.ClientSession] = None
        self._next_retry_time: Optional[float] = None  # Timestamp for next allowed API attempt

    async def _ensure_session(self):
        """Ensure aiohttp session is created with a cookie jar."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar()
            )

    async def async_close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, referer: str) -> Dict[str, str]:
        """Get common headers for requests."""
        return {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": referer,
        }

    async def _visit_homepage(self) -> bool:
        """Visit the homepage to get initial cookies (like PHPSESSID)."""
        try:
            _LOGGER.debug(f"Visiting homepage: {API_BASE_URL}")
            async with self.session.get(
                API_BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"}
            ) as response:
                _LOGGER.debug(f"Homepage response status: {response.status}")
                await response.text()  # Read response body

                # Check for server errors (5xx)
                if response.status >= 500:
                    _LOGGER.error(f"Homepage returned server error: {response.status}")
                    raise JablotronTransientError(f"Homepage returned server error: {response.status}")

                return response.status == 200
        except JablotronTransientError:
            raise  # Re-raise transient errors
        except Exception as e:
            _LOGGER.error(f"Error visiting homepage: {e}", exc_info=True)
            raise JablotronTransientError(f"Network error visiting homepage: {e}") from e

    async def login(self) -> None:
        """Clear cookies and perform a full login flow."""
        _LOGGER.info("Performing full login to Jablotron Cloud.")
        await self._ensure_session()

        # 1. Clear all cookies for a fresh start
        self.session.cookie_jar.clear()
        _LOGGER.debug("Cookie jar cleared for login.")

        # 2. Visit homepage to get PHPSESSID
        try:
            homepage_ok = await self._visit_homepage()
            if not homepage_ok:
                _LOGGER.error("Failed to visit homepage")
                raise JablotronAuthError("Failed to visit homepage")
        except JablotronTransientError:
            raise  # Re-raise transient errors to trigger retry mechanism

        # 3. Perform login
        login_data = {
            "login": self.username,
            "heslo": self.password,
            "aStatus": "200",
            "loginType": "Login"
        }
        headers = self._get_headers(referer=f"{API_BASE_URL}/")
        _LOGGER.debug(f"Login request to {API_LOGIN_URL}")

        try:
            async with self.session.post(
                API_LOGIN_URL, data=urlencode(login_data), headers=headers
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(f"Login response status: {response.status}")
                _LOGGER.debug(f"Login response body: {response_text}")

                # Check for server errors (5xx) - these are transient
                if response.status >= 500:
                    _LOGGER.error(f"Login failed with server error: {response.status}")
                    raise JablotronTransientError(f"Login server error: {response.status}")

                if response.status != 200:
                    _LOGGER.error(f"Login failed. HTTP Status: {response.status}, Body: {response_text}")
                    raise JablotronAuthError(f"Login failed with status {response.status}")

                # Check if the response is JSON with error status
                if response_text:
                    try:
                        response_json = json.loads(response_text)
                        # Check for error status in JSON response (e.g., status != 200)
                        if isinstance(response_json, dict):
                            status = response_json.get("status")
                            if status and status != 200:
                                _LOGGER.error(f"Login failed. API returned status: {status}, Response: {response_json}")
                                raise JablotronAuthError(f"Login failed with API status {status}")
                            _LOGGER.debug(f"Login response JSON: {response_json}")
                    except json.JSONDecodeError:
                        # Response is not JSON, that's okay - might be empty or plain text
                        pass

                _LOGGER.debug("Login POST successful.")

        except (JablotronAuthError, JablotronTransientError):
            raise  # Re-raise to be caught by the caller
        except (aiohttp.ClientError, TimeoutError) as e:
            # Network errors, connection issues, timeouts - these are transient
            _LOGGER.error(f"Login request network error: {e}", exc_info=True)
            raise JablotronTransientError(f"Login network error: {e}") from e

        # 4. Visit /cloud page to get the lastMode cookie
        _LOGGER.debug("Fetching /cloud page to set lastMode cookie.")
        cloud_url = f"{API_BASE_URL}/cloud"
        cloud_headers = self._get_headers(referer=f"{API_BASE_URL}/")
        cloud_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })
        try:
            async with self.session.get(cloud_url, headers=cloud_headers) as cloud_response:
                await cloud_response.text()
                _LOGGER.debug(f"/cloud response status: {cloud_response.status}")

                # Check for server errors (5xx) - these are transient
                if cloud_response.status >= 500:
                    _LOGGER.error(f"/cloud page returned server error: {cloud_response.status}")
                    raise JablotronTransientError(f"/cloud page server error: {cloud_response.status}")

                if cloud_response.status != 200:
                    _LOGGER.error(f"/cloud page fetch failed with status: {cloud_response.status}")
                    raise JablotronAuthError(f"/cloud page fetch failed with status: {cloud_response.status}")
        except (JablotronAuthError, JablotronTransientError):
            raise  # Re-raise to be caught by the caller
        except (aiohttp.ClientError, TimeoutError) as e:
            # Network errors, connection issues, timeouts - these are transient
            _LOGGER.error(f"Error fetching /cloud page: {e}", exc_info=True)
            raise JablotronTransientError(f"/cloud page network error: {e}") from e

        # 5. Visit the JA100 app page (required before fetching sensors)
        _LOGGER.debug("Visiting JA100 app page...")
        ja100_url = f"{API_BASE_URL}/app/ja100"
        if self.service_id:
            ja100_url += f"?service={self.service_id}"

        try:
            async with self.session.get(ja100_url, headers=cloud_headers) as ja100_response:
                await ja100_response.text()
                _LOGGER.debug(f"JA100 app page status: {ja100_response.status}")

                # Check for server errors (5xx) - these are transient
                if ja100_response.status >= 500:
                    _LOGGER.error(f"JA100 app page returned server error: {ja100_response.status}")
                    raise JablotronTransientError(f"JA100 app page server error: {ja100_response.status}")

                if ja100_response.status == 200:
                    _LOGGER.info("Successfully logged in and obtained all cookies.")
                else:
                    _LOGGER.error(f"JA100 app page returned status {ja100_response.status}")
                    raise JablotronAuthError(f"JA100 app page returned status {ja100_response.status}")
        except (JablotronAuthError, JablotronTransientError):
            raise  # Re-raise to be caught by the caller
        except (aiohttp.ClientError, TimeoutError) as e:
            # Network errors, connection issues, timeouts - these are transient
            _LOGGER.error(f"Error fetching JA100 app page: {e}", exc_info=True)
            raise JablotronTransientError(f"JA100 app page network error: {e}") from e

    async def get_status(self) -> Dict[str, Any]:
        """Get status from Jablotron API with automatic re-login on session expiry."""
        return await self._api_request_handler(self._fetch_status)

    async def _api_request_handler(self, fetch_func) -> Dict[str, Any]:
        """Handle API requests, including session expiry and retries."""
        now = time.time()
        if self._next_retry_time and now < self._next_retry_time:
            retry_in = int(self._next_retry_time - now)
            _LOGGER.warning(f"Jablotron API unavailable, next retry in {retry_in} seconds")
            raise Exception(f"Jablotron API unavailable, retry after {retry_in} seconds")

        await self._ensure_session()

        # Check if we have any cookies, if not, perform initial login
        if len(self.session.cookie_jar) == 0:
            _LOGGER.info("No cookies found, performing initial login")
            try:
                await self.login()
            except JablotronTransientError as e:
                retry_minutes = RETRY_DELAY // 60
                _LOGGER.error(f"Jablotron login failed with transient error: {e}. Will retry after {retry_minutes} minutes.")
                self._next_retry_time = time.time() + RETRY_DELAY
                raise Exception(f"Jablotron API unavailable, will retry after {retry_minutes} minutes") from e
            except JablotronAuthError as e:
                raise JablotronAuthError("Failed to login to Jablotron Cloud") from e

        try:
            data = await fetch_func()

            if data and data.get("status") == 300:
                _LOGGER.info("Session expired (status 300), re-logging in with cleared cookies")
                try:
                    await self.login()
                except JablotronTransientError as e:
                    retry_minutes = RETRY_DELAY // 60
                    _LOGGER.error(f"Jablotron re-login failed with transient error: {e}. Will retry after {retry_minutes} minutes.")
                    self._next_retry_time = time.time() + RETRY_DELAY
                    raise Exception(f"Jablotron API unavailable, will retry after {retry_minutes} minutes") from e
                except JablotronAuthError as e:
                    raise JablotronAuthError("Failed to re-login to Jablotron Cloud") from e

                data = await fetch_func()

                if data and data.get("status") == 300:
                    _LOGGER.error("Re-login failed, still getting status 300 from API")
                    raise JablotronAuthError("Failed to re-login to Jablotron Cloud (status 300)")

            self._next_retry_time = None
            return data

        except JablotronAuthError:
            # Re-raise auth errors so Home Assistant can trigger reauth flow
            raise
        except Exception as e:
            retry_minutes = RETRY_DELAY // 60
            _LOGGER.error(f"Jablotron API error: {e}. Will retry after {retry_minutes} minutes.")
            self._next_retry_time = time.time() + RETRY_DELAY
            raise Exception(f"Jablotron API unavailable, will retry after {retry_minutes} minutes") from e

    async def _fetch_status(self) -> Dict[str, Any]:
        """Fetch status from API (stav.php)."""
        await self._ensure_session()

        referer = f"{API_BASE_URL}/app/ja100?service={self.service_id}"
        headers = self._get_headers(referer=referer)

        # Use 'heat' to get temperature sensors (teplomery) and binary sensors (pgm)
        if self.service_id:
            payload = f"activeTab=heat&service_id={self.service_id}"
        else:
            payload = "activeTab=heat"

        _LOGGER.debug(f"Fetching status from {API_STATUS_URL}")

        async with self.session.post(
            API_STATUS_URL,
            data=payload,
            headers=headers,
        ) as response:
            _LOGGER.debug(f"Status response status: {response.status}")

            if response.status != 200:
                raise Exception(f"Status request returned status {response.status}")

            response_text = await response.text()
            _LOGGER.debug(f"Status response body: {response_text}")

            try:
                data = json.loads(response_text)
                _LOGGER.debug(f"Status data parsed: {data}")
                return data
            except Exception as parse_error:
                _LOGGER.error(f"Failed to parse JSON from status response: {parse_error}")
                raise Exception("Failed to parse JSON from status response") from parse_error

    async def control_pgm(self, pgm_id: str, status: int) -> Dict[str, Any]:
        """Control a PGM output (turn on/off).

        Args:
            pgm_id: The PGM ID (e.g., "6" for PGM_7)
            status: 1 for on, 0 for off

        Returns:
            API response dict with keys: ts, id, authorization, result, responseCode
        """
        return await self._api_request_handler(lambda: self._control_pgm(pgm_id, status))

    async def _control_pgm(self, pgm_id: str, status: int) -> Dict[str, Any]:
        """Internal method to send PGM control request."""
        await self._ensure_session()

        referer = f"{API_BASE_URL}/app/ja100?service={self.service_id}"
        headers = self._get_headers(referer=referer)

        # Build the state_name (e.g., PGM_7 for pgm_id "6")
        pgm_index = int(pgm_id) + 1
        state_name = f"PGM_{pgm_index}"
        uid = f"{state_name}_prehled"

        # Build payload
        payload = {
            "section": state_name,
            "status": str(status),
            "code": self.pgm_code,
            "uid": uid,
        }

        _LOGGER.debug(f"Controlling PGM {state_name}: status={status}, payload={payload}")

        async with self.session.post(
            API_CONTROL_URL,
            data=urlencode(payload),
            headers=headers,
        ) as response:
            _LOGGER.debug(f"Control response status: {response.status}")

            if response.status != 200:
                raise Exception(f"Control request returned status {response.status}")

            response_text = await response.text()
            _LOGGER.debug(f"Control response body: {response_text}")

            try:
                data = json.loads(response_text)
                _LOGGER.debug(f"Control response parsed: {data}")

                # Check for PGM-specific error responses (authorization, responseCode)
                # Note: session expiry (status 300) is handled by _api_request_handler
                authorization = data.get("authorization")
                response_code = data.get("responseCode")

                if authorization is not None and authorization != 200:
                    _LOGGER.error(f"PGM control authorization failed: {authorization}")
                    raise Exception(f"PGM control authorization failed: {authorization}")

                if response_code is not None and response_code != 200:
                    _LOGGER.error(f"PGM control failed with response code: {response_code}")
                    raise Exception(f"PGM control failed with response code: {response_code}")

                return data
            except json.JSONDecodeError as parse_error:
                _LOGGER.error(f"Failed to parse JSON from control response: {parse_error}")
                raise Exception("Failed to parse JSON from control response") from parse_error

