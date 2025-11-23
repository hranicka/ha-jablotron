"""Jablotron API Client with session management."""
import logging
import aiohttp
from typing import Dict, Any, Optional
from urllib.parse import urlencode

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

    async def login(self) -> bool:
        """Login to Jablotron and get session ID."""
        _LOGGER.info("Attempting to login to Jablotron Cloud")

        # First, make a request to get initial PHPSESSID
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
                            _LOGGER.debug(f"Got initial PHPSESSID: {self.phpsessid}")

                # If not in headers, check cookies from response
                if not self.phpsessid and response.cookies:
                    if 'PHPSESSID' in response.cookies:
                        self.phpsessid = response.cookies['PHPSESSID'].value
        except Exception as e:
            _LOGGER.warning(f"Could not get initial PHPSESSID: {e}")

        # Now perform login
        login_data = {
            "login": self.username,
            "heslo": self.password,
            "aStatus": "200",
            "loginType": "Login"
        }

        headers = self._get_headers(referer=f"{API_BASE_URL}/")
        cookies = self._get_cookies()

        try:
            async with self.session.post(
                API_LOGIN_URL,
                data=urlencode(login_data),
                headers=headers,
                cookies=cookies,
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(f"Login response status: {response.status}")
                _LOGGER.debug(f"Login response: {response_text}")

                # Update PHPSESSID from login response
                if 'Set-Cookie' in response.headers:
                    for cookie in response.headers.getall('Set-Cookie', []):
                        if 'PHPSESSID' in cookie:
                            self.phpsessid = cookie.split('PHPSESSID=')[1].split(';')[0]
                            _LOGGER.info(f"Login successful, got new PHPSESSID")

                if not self.phpsessid and response.cookies and 'PHPSESSID' in response.cookies:
                    self.phpsessid = response.cookies['PHPSESSID'].value

                if response.status == 200:
                    _LOGGER.info("Successfully logged in to Jablotron Cloud")
                    return True
                else:
                    _LOGGER.error(f"Login failed with status {response.status}")
                    return False

        except Exception as e:
            _LOGGER.error(f"Login error: {e}")
            return False

    async def get_status(self) -> Dict[str, Any]:
        """Get status from Jablotron API."""
        # Try to get data with the current session
        data = await self._fetch_status()

        # Check if the session expired (status == 300)
        if data and data.get("status") == 300:
            _LOGGER.info("Session expired or login invalid, logging in again")
            if await self.login():
                # Retry with a new session
                data = await self._fetch_status()
                if data and data.get("status") == 300:
                    _LOGGER.error("Re-login failed, still getting status 300 from API")
                    raise Exception("Failed to re-login to Jablotron Cloud (status 300)")
            else:
                raise Exception("Failed to re-login to Jablotron Cloud (login failed)")

        return data

    async def _fetch_status(self) -> Dict[str, Any]:
        """Fetch status from API."""
        if not self.phpsessid:
            _LOGGER.info("No session, logging in first")
            if not await self.login():
                raise Exception("Failed to login to Jablotron Cloud")

        referer = f"{API_BASE_URL}/app/ja100?service={self.service_id}"
        headers = self._get_headers(referer=referer)
        cookies = self._get_cookies()

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
                    return {}
                _LOGGER.debug(f"Status data received: {data}")
                return data
        except Exception as e:
            _LOGGER.error(f"Error fetching status: {e}")
            raise
