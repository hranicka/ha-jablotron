"""Button to trigger a manual update of Jablotron data."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jablotron update button."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([JablotronUpdateButton(coordinator, entry.entry_id)])


class JablotronUpdateButton(CoordinatorEntity, ButtonEntity):
    """A button to manually trigger a Jablotron data update."""

    def __init__(self, coordinator: DataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_name = "Jablotron Force Update"
        self._attr_unique_id = f"{entry_id}_force_update"
        self._attr_icon = "mdi:sync"
        self._entry_id = entry_id

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        # Button is always available so users can trigger updates even when the coordinator has errors
        return True

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Force updating Jablotron data via button press")
        await self.coordinator.async_request_refresh()

