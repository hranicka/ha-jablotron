"""Services for Jablotron Web integration."""
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_RELOAD = "reload"
SERVICE_UPDATE = "update"

SERVICE_RELOAD_SCHEMA = vol.Schema({})
SERVICE_UPDATE_SCHEMA = vol.Schema({})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Jablotron Web integration."""

    async def async_reload_integration(call: ServiceCall) -> None:
        """Reload all Jablotron Web config entries."""
        _LOGGER.info("Reloading Jablotron Web integration")

        # Get all config entries for this integration
        entries = hass.config_entries.async_entries(DOMAIN)

        if not entries:
            _LOGGER.warning("No Jablotron Web integrations found to reload")
            return

        # Reload each entry
        for entry in entries:
            _LOGGER.info(f"Reloading Jablotron Web entry: {entry.title}")
            await hass.config_entries.async_reload(entry.entry_id)

        _LOGGER.info(f"Reloaded {len(entries)} Jablotron Web integration(s)")

    async def async_trigger_update(call: ServiceCall) -> None:
        """Trigger an immediate update of all Jablotron coordinators."""
        _LOGGER.info("Triggering manual update of Jablotron data")

        # Get all entries
        if DOMAIN not in hass.data:
            _LOGGER.warning("No Jablotron Web integrations found")
            return

        # Trigger refresh for all coordinators
        update_count = 0
        for entry_id, entry_data in hass.data[DOMAIN].items():
            if "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                _LOGGER.info(f"Triggering update for entry: {entry_id}")
                await coordinator.async_request_refresh()
                update_count += 1

        _LOGGER.info(f"Triggered update for {update_count} Jablotron integration(s)")

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD,
        async_reload_integration,
        schema=SERVICE_RELOAD_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE,
        async_trigger_update,
        schema=SERVICE_UPDATE_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for Jablotron Web integration."""
    hass.services.async_remove(DOMAIN, SERVICE_RELOAD)
    hass.services.async_remove(DOMAIN, SERVICE_UPDATE)

