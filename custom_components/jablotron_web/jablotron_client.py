"""Jablotron API Client with session management."""
import json
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import time
import aiohttp

from homeassistant.core import HomeAssistant

from .const import API_LOGIN_URL, API_STATUS_URL, API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class JablotronAuthError(Exception):
    """Jablotron authentication error."""


class JablotronClient:
    """Client for Jablotron API with automatic session management."""

    def __init__(self, username: str, password: str, service_id: str, hass: HomeAssistant):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.service_id = service_id
        self.hass = hass
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
                return response.status == 200
        except Exception as e:
            _LOGGER.error(f"Error visiting homepage: {e}", exc_info=True)
            return False

    async def login(self) -> None:
        """Clear cookies and perform a full login flow."""
        _LOGGER.info("Performing full login to Jablotron Cloud.")
        await self._ensure_session()

        # 1. Clear all cookies for a fresh start
        self.session.cookie_jar.clear()
        _LOGGER.debug("Cookie jar cleared for login.")

        # 2. Visit homepage to get PHPSESSID
        if not await self._visit_homepage():
            _LOGGER.error("Failed to visit homepage")
            return False

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

        except JablotronAuthError:
            raise  # Re-raise JablotronAuthError to be caught by the caller
        except Exception as e:
            _LOGGER.error(f"Login request error: {e}", exc_info=True)
            raise JablotronAuthError("Login request failed") from e

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
                if cloud_response.status != 200:
                    _LOGGER.error(f"/cloud page fetch failed with status: {cloud_response.status}")
                    raise JablotronAuthError(f"/cloud page fetch failed with status: {cloud_response.status}")
        except Exception as e:
            _LOGGER.error(f"Error fetching /cloud page: {e}", exc_info=True)
            raise JablotronAuthError("Error fetching /cloud page") from e

        # 5. Visit the JA100 app page (required before fetching sensors)
        _LOGGER.debug("Visiting JA100 app page...")
        ja100_url = f"{API_BASE_URL}/app/ja100"
        if self.service_id:
            ja100_url += f"?service={self.service_id}"

        try:
            async with self.session.get(ja100_url, headers=cloud_headers) as ja100_response:
                await ja100_response.text()
                _LOGGER.debug(f"JA100 app page status: {ja100_response.status}")
                if ja100_response.status == 200:
                    _LOGGER.info("Successfully logged in and obtained all cookies.")
                else:
                    _LOGGER.error(f"JA100 app page returned status {ja100_response.status}")
                    raise JablotronAuthError(f"JA100 app page returned status {ja100_response.status}")
        except Exception as e:
            _LOGGER.error(f"Error fetching JA100 app page: {e}", exc_info=True)
            raise JablotronAuthError("Error fetching JA100 app page") from e

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

        if not self.session.cookie_jar:
            _LOGGER.info("No cookies found, performing initial login")
            await self.login()

        try:
            data = await fetch_func()

            if data and data.get("status") == 300:
                _LOGGER.info("Session expired (status 300), re-logging in with cleared cookies")
                try:
                    await self.login()
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
            _LOGGER.error(f"Jablotron API error: {e}. Will retry after 30 minutes.")
            self._next_retry_time = time.time() + 1800  # 30 minutes
            raise Exception("Jablotron API unavailable, will retry after 30 minutes") from e

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
