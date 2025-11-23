"""Jablotron API Client with session management."""
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_LOGIN_URL, API_STATUS_URL, API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class JablotronClient:
    """Client for Jablotron API with automatic session management."""

    def __init__(self, username: str, password: str, service_id: str, hass: HomeAssistant):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.service_id = service_id
        self.hass = hass
        self.session = async_get_clientsession(hass)
        self.phpsessid: Optional[str] = None
        self._cookies: Dict[str, str] = {}
        self._next_retry_time: Optional[float] = None  # Timestamp for next allowed API attempt

    def _get_headers(self, referer: str = None) -> Dict[str, str]:
        """Get common headers for requests."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
        }

        if referer:
            headers["Referer"] = referer

        return headers

    def _get_cookies(self) -> Dict[str, str]:
        """Get cookies including PHPSESSID."""
        cookies = {f"lastMode-{self.username.replace('@', '_').replace('.', '_')}": "jablonet"}

        if self.phpsessid:
            cookies["PHPSESSID"] = self.phpsessid

        return cookies

    async def refresh_session(self) -> bool:
        """Always fetch a new PHPSESSID by visiting the base domain."""
        self.phpsessid = None
        try:
            async with self.session.get(
                API_BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"}
            ) as response:
                # Extract PHPSESSID from cookies
                if 'Set-Cookie' in response.headers:
                    for cookie in response.headers.getall('Set-Cookie', []):
                        if 'PHPSESSID' in cookie:
                            self.phpsessid = cookie.split('PHPSESSID=')[1].split(';')[0]
                            _LOGGER.debug(f"Got new PHPSESSID: {self.phpsessid}")
                if not self.phpsessid and response.cookies:
                    if 'PHPSESSID' in response.cookies:
                        self.phpsessid = response.cookies['PHPSESSID'].value
            return self.phpsessid is not None
        except Exception as e:
            _LOGGER.warning(f"Could not refresh PHPSESSID: {e}")
            return False

    async def login(self) -> bool:
        """Login to Jablotron and get session ID, always using a fresh PHPSESSID."""
        _LOGGER.info("Refreshing session and logging in to Jablotron Cloud")
        if not await self.refresh_session():
            _LOGGER.error("Failed to refresh PHPSESSID before login")
            return False

        login_data = {
            "login": self.username,
            "heslo": self.password,
            "aStatus": "200",
            "loginType": "Login"
        }

        headers = self._get_headers(referer=f"{API_BASE_URL}/")
        # Only send PHPSESSID cookie for login
        cookies = {"PHPSESSID": self.phpsessid} if self.phpsessid else {}

        try:
            async with self.session.post(
                API_LOGIN_URL,
                data=urlencode(login_data),
                headers=headers,
                cookies=cookies,
            ) as response:
                _LOGGER.debug(f"Login response status: {response.status}")
                # Login response has an empty body, just check status
                if response.status == 200:
                    _LOGGER.info("Successfully logged in to Jablotron Cloud")
                    return True
                else:
                    response_text = await response.text()
                    _LOGGER.error(f"Login failed with status {response.status}: {response_text}")
                    return False
        except Exception as e:
            _LOGGER.error(f"Login error: {e}")
            return False

    async def get_status(self) -> Dict[str, Any]:
        """Get status from Jablotron API, with retry on API unavailability and robust session handling."""
        now = time.time()
        if self._next_retry_time and now < self._next_retry_time:
            retry_in = int(self._next_retry_time - now)
            _LOGGER.warning(f"Jablotron API unavailable, next retry in {retry_in} seconds")
            raise Exception(f"Jablotron API unavailable, retry after {retry_in} seconds")
        try:
            data = await self._fetch_status()
        except Exception as e:
            _LOGGER.error(f"Jablotron API error: {e}. Will retry after 30 minutes.")
            self._next_retry_time = now + 1800  # 30 minutes
            raise Exception("Jablotron API unavailable, will retry after 30 minutes")
        # Check if the session expired (status == 300)
        if data and data.get("status") == 300:
            _LOGGER.info("Session expired or login invalid, refreshing session and logging in again")
            if await self.login():
                try:
                    data = await self._fetch_status()
                except Exception as e:
                    _LOGGER.error(f"Jablotron API error after re-login: {e}. Will retry after 30 minutes.")
                    self._next_retry_time = time.time() + 1800
                    raise Exception("Jablotron API unavailable, will retry after 30 minutes")
                if data and data.get("status") == 300:
                    _LOGGER.error("Re-login failed, still getting status 300 from API")
                    raise Exception("Failed to re-login to Jablotron Cloud (status 300)")
            else:
                raise Exception("Failed to re-login to Jablotron Cloud (login failed)")
        self._next_retry_time = None
        return data

    async def _fetch_status(self) -> Dict[str, Any]:
        """Fetch status from API, ensure the session is valid."""
        if not self.phpsessid:
            _LOGGER.info("No session, logging in first")
            if not await self.login():
                raise Exception("Failed to login to Jablotron Cloud")

        referer = f"{API_BASE_URL}/app/ja100?service={self.service_id}"
        headers = self._get_headers(referer=referer)
        cookies = self._get_cookies()

        # Use 'heat' to get temperature sensors (teplomery) and binary sensors (pgm)
        payload = "activeTab=heat"

        try:
            async with self.session.post(
                API_STATUS_URL,
                data=payload,
                headers=headers,
                cookies=cookies,
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(f"Status response: {response_text}")
                try:
                    data = await response.json()
                except Exception:
                    _LOGGER.error("Failed to parse JSON from status response")
                    raise Exception("Failed to parse JSON from status response")
                _LOGGER.debug(f"Status data received: {data}")
                return data
        except Exception as e:
            _LOGGER.error(f"Error fetching status: {e}")
            raise Exception("Jablotron API request failed")
