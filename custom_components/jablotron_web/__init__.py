"""Jablotron Web integration for Home Assistant."""
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_RETRY_DELAY,
    CONF_TIMEOUT,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PGM_STATE_OFF,
    PGM_STATE_ON,
)
from .jablotron_client import (
    JablotronAuthError,
    JablotronClient,
    JablotronSessionError,
)
from . import services
from .services import SERVICE_RELOAD

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON]


class JablotronDataCoordinator(DataUpdateCoordinator):
    """Coordinator for Jablotron data with typed state management.

    Extends DataUpdateCoordinator with:
    - config_entry: passed explicitly at construction (required pattern in
      recent HA; the ContextVar fallback is deprecated for core and its
      deprecation window closed with 2025.12)
    - last_updated: timestamp of the last successful update (used by the
      "next update" sensor)
    - set_pgm_state(): the single sanctioned way to mutate cached PGM state
      after a control command, so platforms never reach into the raw dict
    """

    last_updated: float | None

    def __init__(self, *args, **kwargs):
        """Initialize the coordinator."""
        super().__init__(*args, **kwargs)
        self.last_updated = None

    def set_pgm_state(self, pgm_id: str, stav: int, ts: int | None = None) -> bool:
        """Update the cached state of one PGM after a successful control call.

        Args:
            pgm_id: PGM identifier as used in coordinator.data["pgm"].
            stav: New state (1 = on, 0 = off).
            ts: Change timestamp from the API response, if present.

        Returns:
            True if the cached state was updated, False if the PGM is unknown
            or the state invalid (cache left untouched).
        """
        if stav not in (PGM_STATE_ON, PGM_STATE_OFF):
            _LOGGER.warning("Refusing to cache invalid PGM state %r for %s", stav, pgm_id)
            return False
        pgm_data = (self.data or {}).get("pgm", {})
        if pgm_id not in pgm_data:
            _LOGGER.warning("PGM %s not in cached data; not updating state", pgm_id)
            return False
        pgm_data[pgm_id]["stav"] = stav
        if ts is not None:
            pgm_data[pgm_id]["ts"] = ts
        return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Jablotron Web from a config entry."""

    username = entry.data["username"]
    password = entry.data["password"]
    service_id = entry.data.get("service_id", "")
    pgm_code = entry.data.get("pgm_code", "")
    timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    retry_delay = entry.options.get(CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY)

    client = JablotronClient(username, password, service_id, hass, pgm_code, timeout=timeout, retry_delay=retry_delay)

    async def async_update_data():
        """Fetch data from API."""
        # Check if we're in a retry delay period
        next_retry = client.get_next_retry_time()
        if next_retry is not None:
            current_time = time.time()
            if current_time < next_retry:
                # Still in retry delay - skip the call
                remaining = int(next_retry - current_time)
                minutes = remaining // 60
                seconds = remaining % 60
                _LOGGER.debug(
                    "Waiting for retry delay to expire: %sm %ss remaining", minutes, seconds
                )
                raise UpdateFailed(
                    f"Session error - retrying in {minutes} minutes {seconds} seconds"
                )
            # Retry delay has expired - reset session before retry so the
            # upcoming get_status() starts with a clean login
            _LOGGER.info("Retry delay expired, resetting session before retry")
            await client.reset_session_and_clear_retry()

        try:
            data = await client.get_status()
            coordinator.last_updated = time.time()
            _LOGGER.debug("Updated last_update_time for entry %s", entry.entry_id)
            return data
        except JablotronAuthError as err:
            # Wrong credentials - only this should trigger the reauth flow
            raise ConfigEntryAuthFailed from err
        except JablotronSessionError as err:
            # Recoverable session/network problem - back off and retry later,
            # the client has set its retry delay
            _LOGGER.warning("Session error, will retry later: %s", err)
            raise UpdateFailed(f"Session error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = JablotronDataCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
    )

    # Start the first refresh. THIS MUST be done before setting up platforms
    # that rely on the data to be present.
    await coordinator.async_config_entry_first_refresh()

    # Initialize hass.data safely after refresh succeeds
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as err:
        _LOGGER.error("Forward entry setups failed: %s", err)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    # Register services with race condition protection
    if not hass.services.async_has_service(DOMAIN, SERVICE_RELOAD):
        await services.async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.info("Reloading config entry for entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # setdefault: setup may have failed before hass.data was initialized
        coordinator_data = hass.data.setdefault(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator_data is None:
            # Already unloaded or setup never completed
            return True
        client = coordinator_data["client"]
        await client.async_close()

        # Unregister services if this was the last entry
        if not hass.data[DOMAIN]:
            await services.async_unload_services(hass)

    return unload_ok
