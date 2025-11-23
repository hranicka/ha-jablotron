"""Sensor platform for Jablotron Web."""
import logging
from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SENSOR_NAMES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jablotron sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Get custom sensor names from config
    sensor_names = entry.data.get(CONF_SENSOR_NAMES, {})

    sensors = []

    # Get initial data to determine available sensors
    if coordinator.data and "teplomery" in coordinator.data:
        for sensor_id, sensor_data in coordinator.data["teplomery"].items():
            # Use custom name if provided, otherwise use generic name
            sensor_name = sensor_names.get(sensor_id, f"Teploměr {sensor_id}")
            sensors.append(
                JablotronTemperatureSensor(
                    coordinator,
                    entry.entry_id,
                    sensor_id,
                    sensor_name,
                )
            )

    async_add_entities(sensors)


class JablotronTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Jablotron temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator,
        entry_id: str,
        sensor_id: str,
        sensor_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        self._attr_name = f"Jablotron {sensor_name}"
        self._attr_unique_id = f"{entry_id}_teplomer_{sensor_id}"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if (
            self.coordinator.data
            and "teplomery" in self.coordinator.data
            and self._sensor_id in self.coordinator.data["teplomery"]
        ):
            try:
                return float(self.coordinator.data["teplomery"][self._sensor_id]["value"])
            except (KeyError, ValueError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        if (
            self.coordinator.data
            and "teplomery" in self.coordinator.data
            and self._sensor_id in self.coordinator.data["teplomery"]
        ):
            sensor_data = self.coordinator.data["teplomery"][self._sensor_id]
            attrs = {
                "sensor_id": self._sensor_id,
                "state_name": sensor_data.get("stateName", ""),
            }
            if "ts" in sensor_data:
                attrs["timestamp"] = sensor_data["ts"]
            return attrs
        return {}

