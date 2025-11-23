"""Jablotron API Client with session management."""
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import time
import aiohttp

from homeassistant.core import HomeAssistant

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
        # Create custom session with cookie jar to handle cookies properly
        self.session: Optional[aiohttp.ClientSession] = None
        self.phpsessid: Optional[str] = None
        self._cookies: Dict[str, str] = {}
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
        await self._ensure_session()
        self.phpsessid = None
        try:
            _LOGGER.debug(f"Fetching new PHPSESSID from {API_BASE_URL}")
            async with self.session.get(
                API_BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"}
            ) as response:
                _LOGGER.debug(f"Base URL response status: {response.status}")
                _LOGGER.debug(f"Response headers: {dict(response.headers)}")
                _LOGGER.debug(f"Response cookies: {dict(response.cookies)}")

                # Read response body for debugging
                response_body = await response.text()
                _LOGGER.debug(f"Response body length: {len(response_body)} bytes")
                if len(response_body) < 1000:
                    _LOGGER.debug(f"Response body: {response_body}")

                # Try to extract PHPSESSID from response.cookies first
                if response.cookies and 'PHPSESSID' in response.cookies:
                    self.phpsessid = response.cookies['PHPSESSID'].value
                    _LOGGER.debug(f"Got new PHPSESSID from response.cookies: {self.phpsessid}")

                # If not found, try Set-Cookie headers
                if not self.phpsessid and 'Set-Cookie' in response.headers:
                    set_cookies = response.headers.getall('Set-Cookie', [])
                    _LOGGER.debug(f"Set-Cookie headers: {set_cookies}")
                    for cookie in set_cookies:
                        if 'PHPSESSID' in cookie:
                            # Parse: PHPSESSID=xyz; path=/; ...
                            self.phpsessid = cookie.split('PHPSESSID=')[1].split(';')[0]
                            _LOGGER.debug(f"Got new PHPSESSID from Set-Cookie header: {self.phpsessid}")
                            break

                if self.phpsessid:
                    _LOGGER.info(f"Successfully refreshed PHPSESSID")
                else:
                    _LOGGER.error("Could not extract PHPSESSID from response")

            return self.phpsessid is not None
        except Exception as e:
            _LOGGER.error(f"Could not refresh PHPSESSID: {e}", exc_info=True)
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

        _LOGGER.debug(f"Login request URL: {API_LOGIN_URL}")
        _LOGGER.debug(f"Login request headers: {headers}")
        _LOGGER.debug(f"Login request cookies: {cookies}")
        _LOGGER.debug(f"Login request data: login={self.username}, heslo=*****, aStatus=200, loginType=Login")

        try:
            async with self.session.post(
                API_LOGIN_URL,
                data=urlencode(login_data),
                headers=headers,
                cookies=cookies,
            ) as response:
                _LOGGER.debug(f"Login response status: {response.status}")
                _LOGGER.debug(f"Login response headers: {dict(response.headers)}")
                _LOGGER.debug(f"Login response cookies: {dict(response.cookies)}")

                response_text = await response.text()
                _LOGGER.debug(f"Login response body length: {len(response_text)} bytes")
                if response_text:
                    _LOGGER.debug(f"Login response body: {response_text}")
                else:
                    _LOGGER.debug("Login response body is empty (expected)")

                # Login response has an empty body, just check status
                if response.status == 200:
                    _LOGGER.info("Successfully logged in to Jablotron Cloud")
                    return True
                else:
                    _LOGGER.error(f"Login failed with status {response.status}: {response_text}")
                    return False
        except Exception as e:
            _LOGGER.error(f"Login error: {e}", exc_info=True)
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

        _LOGGER.debug(f"Status request URL: {API_STATUS_URL}")
        _LOGGER.debug(f"Status request headers: {headers}")
        _LOGGER.debug(f"Status request cookies: {cookies}")
        _LOGGER.debug(f"Status request payload: {payload}")

        try:
            async with self.session.post(
                API_STATUS_URL,
                data=payload,
                headers=headers,
                cookies=cookies,
            ) as response:
                _LOGGER.debug(f"Status response status: {response.status}")
                _LOGGER.debug(f"Status response headers: {dict(response.headers)}")
                _LOGGER.debug(f"Status response cookies: {dict(response.cookies)}")

                response_text = await response.text()
                _LOGGER.debug(f"Status response body length: {len(response_text)} bytes")
                _LOGGER.debug(f"Status response body: {response_text}")

                try:
                    data = await response.json()
                    _LOGGER.debug(f"Status data parsed successfully: {data}")
                except Exception as parse_error:
                    _LOGGER.error(f"Failed to parse JSON from status response: {parse_error}")
                    _LOGGER.error(f"Response text was: {response_text}")
                    raise Exception("Failed to parse JSON from status response")

                return data
        except Exception as e:
            _LOGGER.error(f"Error fetching status: {e}", exc_info=True)
            raise Exception("Jablotron API request failed")
