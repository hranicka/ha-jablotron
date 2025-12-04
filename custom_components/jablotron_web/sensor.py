import logging
from typing import Any, Dict
from datetime import datetime
from homeassistant.util import dt as dt_util

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

    sensors = [JablotronNextUpdateSensor(coordinator, entry.entry_id)]

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


class JablotronNextUpdateSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Jablotron next update sensor with update tracking."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Jablotron Next Update"
        self._attr_unique_id = f"{entry_id}_next_update"
        self._attr_icon = "mdi:update"
        self._entry_id = entry_id

    def _get_last_update_timestamp(self) -> float | None:
        """Get the last update timestamp from hass.data."""
        if (
            DOMAIN in self.hass.data
            and self._entry_id in self.hass.data[DOMAIN]
            and "last_update_time" in self.hass.data[DOMAIN][self._entry_id]
        ):
            return self.hass.data[DOMAIN][self._entry_id]["last_update_time"]
        return None

    def _calculate_update_times(self) -> tuple[datetime, datetime] | None:
        """Calculate the last and next update times.

        Returns:
            Tuple of (last_update_dt, next_update_dt) or None if data is unavailable.
        """
        timestamp = self._get_last_update_timestamp()
        if timestamp is None:
            return None

        last_update_dt = datetime.fromtimestamp(timestamp, tz=dt_util.DEFAULT_TIME_ZONE)
        next_update_dt = last_update_dt + self.coordinator.update_interval
        return last_update_dt, next_update_dt

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self._get_last_update_timestamp() is not None

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor (next update time)."""
        try:
            update_times = self._calculate_update_times()
            if update_times is None:
                return None

            last_update_dt, next_update_dt = update_times
            _LOGGER.debug(
                f"Next update sensor: last_update={last_update_dt}, "
                f"interval={self.coordinator.update_interval}, next={next_update_dt}"
            )
            return next_update_dt.isoformat()
        except Exception as e:
            _LOGGER.error(f"Error calculating next update time: {e}")
            return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        try:
            update_times = self._calculate_update_times()
            if update_times is None:
                return {}

            last_update_dt, next_update_dt = update_times

            # Calculate time until the next update
            now = dt_util.now()
            time_until_next = next_update_dt - now
            seconds_until_next = int(time_until_next.total_seconds())

            return {
                "last_update": last_update_dt.isoformat(),
                "next_update": next_update_dt.isoformat(),
                "update_interval_seconds": int(self.coordinator.update_interval.total_seconds()),
                "update_interval_minutes": int(self.coordinator.update_interval.total_seconds() / 60),
                "seconds_until_next_update": max(0, seconds_until_next),
                "minutes_until_next_update": max(0, seconds_until_next // 60),
                "last_update_success": self.coordinator.last_update_success,
            }
        except Exception as e:
            _LOGGER.error(f"Error calculating attributes: {e}")
            return {}


