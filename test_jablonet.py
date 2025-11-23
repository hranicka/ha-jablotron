#!/usr/bin/env python3
"""Simple test script to debug Jablotron login and sensor data fetching."""
import asyncio
import logging
import sys
import aiohttp
from urllib.parse import urlencode
import json
from yarl import URL

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://www.jablonet.net"
API_BASE_URL_YARL = URL(API_BASE_URL)  # For cookie filtering
API_LOGIN_URL = f"{API_BASE_URL}/ajax/login.php"
API_STATUS_URL = f"{API_BASE_URL}/app/ja100/ajax/stav.php"


async def test_jablonet(username: str, password: str, service_id: str = ""):
    """Test login to Jablotron."""
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    
    try:
        # Step 1: Visit homepage
        _LOGGER.info("Step 1: Visiting homepage to get initial cookies...")
        async with session.get(
            API_BASE_URL,
            headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"}
        ) as response:
            _LOGGER.info(f"Homepage status: {response.status}")
            cookies = session.cookie_jar.filter_cookies(API_BASE_URL_YARL)
            _LOGGER.info(f"Cookies after homepage: {dict(cookies)}")
        
        # Step 2: Login
        _LOGGER.info("Step 2: Attempting login...")
        login_data = {
            "login": username,
            "heslo": password,
            "aStatus": "200",
            "loginType": "Login"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": f"{API_BASE_URL}/"
        }
        
        async with session.post(
            API_LOGIN_URL,
            data=urlencode(login_data),
            headers=headers
        ) as response:
            response_text = await response.text()
            _LOGGER.info(f"Login response status: {response.status}")
            _LOGGER.info(f"Login response body: {response_text}")
            _LOGGER.info(f"Login response headers: {dict(response.headers)}")
            
            cookies = session.cookie_jar.filter_cookies(API_BASE_URL_YARL)
            _LOGGER.info(f"Cookies after login: {dict(cookies)}")
            
            # Try to parse as JSON
            if response_text:
                try:
                    response_json = json.loads(response_text)
                    _LOGGER.info(f"Parsed JSON response: {response_json}")
                except Exception as e:
                    _LOGGER.warning(f"Response is not JSON: {e}")
        
        # Step 3: Visit /cloud page
        _LOGGER.info("Step 3: Visiting /cloud page...")
        cloud_headers = headers.copy()
        cloud_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })
        
        async with session.get(f"{API_BASE_URL}/cloud", headers=cloud_headers) as response:
            _LOGGER.info(f"/cloud response status: {response.status}")
            cookies = session.cookie_jar.filter_cookies(API_BASE_URL_YARL)
            _LOGGER.info(f"Cookies after /cloud: {dict(cookies)}")
            
            if response.status == 200:
                _LOGGER.info("✓ Login appears successful!")
            else:
                _LOGGER.error("✗ Login failed - /cloud page returned non-200 status")
                return

        # Step 4: Visit JA100 app page (might be required before fetching sensors)
        _LOGGER.info("Step 4: Visiting JA100 app page...")
        ja100_url = f"{API_BASE_URL}/app/ja100"
        if service_id:
            ja100_url += f"?service={service_id}"

        async with session.get(ja100_url, headers=cloud_headers) as response:
            _LOGGER.info(f"JA100 app page status: {response.status}")
            if response.status != 200:
                _LOGGER.warning(f"JA100 app page returned status {response.status}")

        # Step 5: Fetch sensor data
        _LOGGER.info("Step 5: Fetching sensor data...")

        referer = f"{API_BASE_URL}/app/ja100?service={service_id}"
        status_headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": API_BASE_URL,
            "Referer": referer
        }

        if service_id:
            payload = f"activeTab=heat&service_id={service_id}"
        else:
            payload = "activeTab=heat"

        async with session.post(
            API_STATUS_URL,
            data=payload,
            headers=status_headers
        ) as response:
            _LOGGER.info(f"Status response status: {response.status}")

            if response.status == 200:
                response_text = await response.text()
                _LOGGER.info(f"Status response body (first 500 chars): {response_text[:500]}")

                try:
                    status_data = json.loads(response_text)
                    _LOGGER.info(f"Status data parsed successfully")

                    # Display sensor information
                    if "teplomery" in status_data:
                        temps = status_data["teplomery"]
                        _LOGGER.info(f"\n{'='*60}")
                        _LOGGER.info(f"Found {len(temps)} temperature sensor(s):")
                        _LOGGER.info(f"{'='*60}")
                        for sensor_id, sensor_data in temps.items():
                            temp = sensor_data.get("value", "N/A")
                            state = sensor_data.get("state_name", "N/A")
                            _LOGGER.info(f"  Sensor {sensor_id}: {temp}°C ({state})")
                    else:
                        _LOGGER.warning("No 'teplomery' (temperature sensors) found in response")

                    if "pgm" in status_data:
                        pgm_outputs = status_data["pgm"]
                        _LOGGER.info(f"\n{'='*60}")
                        _LOGGER.info(f"Found {len(pgm_outputs)} PGM output(s):")
                        _LOGGER.info(f"{'='*60}")
                        for pgm_id, pgm_data in pgm_outputs.items():
                            name = pgm_data.get("nazev", "Unknown")
                            state = "ON" if pgm_data.get("stav") == 0 else "OFF"
                            _LOGGER.info(f"  PGM {pgm_id}: {name} - {state}")
                    else:
                        _LOGGER.info("No PGM outputs found in response")

                    _LOGGER.info(f"{'='*60}")
                    _LOGGER.info("✓ Sensor data fetched successfully!")
                    _LOGGER.info(f"{'='*60}\n")

                except json.JSONDecodeError as e:
                    _LOGGER.error(f"Failed to parse status JSON: {e}")
                except Exception as e:
                    _LOGGER.error(f"Error processing status data: {e}")
            else:
                _LOGGER.error(f"✗ Failed to fetch sensors - status code: {response.status}")

    finally:
        await session.close()


if __name__ == "__main__":
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python test_jablonet.py <username> <password> [service_id]")
        print("\nExamples:")
        print("  python test_jablonet.py user@example.com mypassword")
        print("  python test_jablonet.py user@example.com mypassword 12345")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    service_id = sys.argv[3] if len(sys.argv) == 4 else ""

    asyncio.run(test_jablonet(username, password, service_id))

