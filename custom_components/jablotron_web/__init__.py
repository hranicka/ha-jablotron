"""Jablotron Web integration for Home Assistant."""
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .jablotron_client import JablotronAuthError, JablotronClient
from . import services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Jablotron Web from a config entry."""

    username = entry.data["username"]
    password = entry.data["password"]
    service_id = entry.data.get("service_id", "")
    pgm_code = entry.data.get("pgm_code", "")

    client = JablotronClient(username, password, service_id, hass, pgm_code)

    async def async_update_data():
        """Fetch data from API."""
        # Check if we're in a retry delay period
        next_retry = client.get_next_retry_time()
        if next_retry and time.time() < next_retry:
            # Skip the call entirely, raise UpdateFailed with a clear message
            remaining = int(next_retry - time.time())
            minutes = remaining // 60
            seconds = remaining % 60
            _LOGGER.debug(
                f"Waiting for retry delay to expire: {minutes}m {seconds}s remaining"
            )
            raise UpdateFailed(
                f"Session error - retrying in {minutes} minutes {seconds} seconds"
            )

        try:
            return await client.get_status()
        except JablotronAuthError as err:
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=entry.options.get("scan_interval", 300)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    # Register services on the first entry
    if len(hass.data[DOMAIN]) == 1:
        await services.async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Close the client session
        client = hass.data[DOMAIN][entry.entry_id]["client"]
        await client.async_close()
        hass.data[DOMAIN].pop(entry.entry_id)

        # Unregister services if this was the last entry
        if not hass.data[DOMAIN]:
            await services.async_unload_services(hass)

    return unload_ok
