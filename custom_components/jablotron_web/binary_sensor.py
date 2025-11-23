"""Binary sensor platform for Jablotron Web."""
import logging
from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jablotron binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    binary_sensors = []

    # Get initial data to determine available binary sensors
    if coordinator.data and "pgm" in coordinator.data:
        for pgm_id, pgm_data in coordinator.data["pgm"].items():
            binary_sensors.append(
                JablotronPGMBinarySensor(
                    coordinator,
                    entry.entry_id,
                    pgm_id,
                    pgm_data.get("nazev", f"PGM {pgm_id}"),
                )
            )

    async_add_entities(binary_sensors)


class JablotronPGMBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jablotron PGM binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(
        self,
        coordinator,
        entry_id: str,
        pgm_id: str,
        pgm_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._pgm_id = pgm_id
        self._attr_name = f"Jablotron {pgm_name}"
        self._attr_unique_id = f"{entry_id}_pgm_{pgm_id}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.data
            and "pgm" in self.coordinator.data
            and self._pgm_id in self.coordinator.data["pgm"]
        ):
            try:
                # PGM is "on" when stav == 0 (based on YAML config)
                return self.coordinator.data["pgm"][self._pgm_id]["stav"] == 0
            except (KeyError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        if (
            self.coordinator.data
            and "pgm" in self.coordinator.data
            and self._pgm_id in self.coordinator.data["pgm"]
        ):
            pgm_data = self.coordinator.data["pgm"][self._pgm_id]
            attrs = {
                "pgm_id": self._pgm_id,
                "nazev": pgm_data.get("nazev", ""),
                "stav": pgm_data.get("stav", None),
                "state_name": pgm_data.get("stateName", ""),
                "reaction": pgm_data.get("reaction", ""),
            }
            if "ts" in pgm_data:
                attrs["timestamp"] = pgm_data["ts"]
            if "time" in pgm_data:
                attrs["time"] = pgm_data["time"]
            return attrs
        return {}

