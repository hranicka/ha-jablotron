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

from .const import DOMAIN, PGM_SWITCHABLE_REACTIONS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jablotron binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    binary_sensors = []

    # Check if PGM code is configured - affects which PGMs become binary sensors vs switches
    pgm_code = entry.data.get("pgm_code", "")
    has_pgm_code = bool(pgm_code and pgm_code.strip())

    if has_pgm_code:
        _LOGGER.debug("PGM code is configured - switchable PGMs will be created as switches, not binary sensors")
    else:
        _LOGGER.debug("PGM code not configured - all PGMs will be created as binary sensors")

    # Get initial data to determine available binary sensors
    if coordinator.data:
        # Add alarm section sensors
        if "sekce" in coordinator.data:
            for section_id, section_data in coordinator.data["sekce"].items():
                binary_sensors.append(
                    JablotronSectionBinarySensor(
                        coordinator,
                        entry.entry_id,
                        section_id,
                        section_data.get("nazev", f"Section {section_id}"),
                    )
                )

        # Add PGM sensors
        if "pgm" in coordinator.data:
            permissions = coordinator.data.get("permissions", {})

            _LOGGER.info(f"Evaluating {len(coordinator.data['pgm'])} PGMs for binary sensor creation (PGM code {'configured' if has_pgm_code else 'NOT configured'})")

            for pgm_id, pgm_data in coordinator.data["pgm"].items():
                reaction = pgm_data.get("reaction", "")
                state_name = pgm_data.get("stateName", "")
                has_permission = permissions.get(state_name, 0) == 1

                # Skip creating binary sensor if:
                # 1. PGM code is configured AND
                # 2. PGM is a switchable type AND
                # 3. User has permission
                # (These will be created as switches instead)
                is_switchable = reaction in PGM_SWITCHABLE_REACTIONS
                will_be_switch = has_pgm_code and is_switchable and has_permission

                if will_be_switch:
                    _LOGGER.debug(f"Skipping binary sensor for PGM {pgm_id} ({pgm_data.get('nazev')}) - will be created as switch instead (reaction: {reaction}, permission: {has_permission})")
                    continue

                _LOGGER.debug(f"Creating binary sensor for PGM {pgm_id} ({pgm_data.get('nazev')}) - reaction: {reaction}, switchable: {is_switchable}, permission: {has_permission}, has_code: {has_pgm_code}")
                binary_sensors.append(
                    JablotronPGMBinarySensor(
                        coordinator,
                        entry.entry_id,
                        pgm_id,
                        pgm_data.get("nazev", f"PGM {pgm_id}"),
                    )
                )

        # Add PIR motion sensors
        if "pir" in coordinator.data:
            for pir_id, pir_data in coordinator.data["pir"].items():
                binary_sensors.append(
                    JablotronPIRBinarySensor(
                        coordinator,
                        entry.entry_id,
                        pir_id,
                        pir_data.get("nazev", f"PIR {pir_id}"),
                    )
                )

    # Count PGM binary sensors
    pgm_binary_count = sum(1 for sensor in binary_sensors if isinstance(sensor, JablotronPGMBinarySensor))
    _LOGGER.info(f"Created {pgm_binary_count} PGM binary sensor(s), {len(binary_sensors)} total binary sensors")
    async_add_entities(binary_sensors)


class JablotronSectionBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jablotron alarm section."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self,
        coordinator,
        entry_id: str,
        section_id: str,
        section_name: str,
    ) -> None:
        """Initialize the section sensor."""
        super().__init__(coordinator)
        self._section_id = section_id
        self._attr_name = f"Jablotron {section_name}"
        self._attr_unique_id = f"{entry_id}_section_{section_id}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the section is armed."""
        if (
            self.coordinator.data
            and "sekce" in self.coordinator.data
            and self._section_id in self.coordinator.data["sekce"]
        ):
            try:
                # Section is "armed" when stav == 1, "disarmed" when stav == 0
                return self.coordinator.data["sekce"][self._section_id]["stav"] == 1
            except (KeyError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        if (
            self.coordinator.data
            and "sekce" in self.coordinator.data
            and self._section_id in self.coordinator.data["sekce"]
        ):
            section_data = self.coordinator.data["sekce"][self._section_id]
            attrs = {
                "section_id": self._section_id,
                "nazev": section_data.get("nazev", ""),
                "stav": section_data.get("stav", None),
                "state_name": section_data.get("stateName", ""),
                "active": section_data.get("active", None),
            }
            if "time" in section_data:
                attrs["time"] = section_data["time"]
            return attrs
        return {}


class JablotronPGMBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jablotron PGM binary sensor."""

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

        # Determine device class based on name keywords
        name_lower = pgm_name.lower()
        if any(word in name_lower for word in ["dveře", "dvere", "door"]):
            self._attr_device_class = BinarySensorDeviceClass.DOOR
        elif any(word in name_lower for word in ["vrata", "gate", "garáž", "garage"]):
            self._attr_device_class = BinarySensorDeviceClass.GARAGE_DOOR
        elif any(word in name_lower for word in ["okno", "window"]):
            self._attr_device_class = BinarySensorDeviceClass.WINDOW
        elif any(word in name_lower for word in ["pohyb", "pir", "motion"]):
            self._attr_device_class = BinarySensorDeviceClass.MOTION
        elif any(word in name_lower for word in ["zvon", "doorbell", "bell"]):
            self._attr_device_class = BinarySensorDeviceClass.SOUND
        else:
            self._attr_device_class = BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.data
            and "pgm" in self.coordinator.data
            and self._pgm_id in self.coordinator.data["pgm"]
        ):
            try:
                # PGM is "on" when stav == 1, "off" when stav == 0
                return self.coordinator.data["pgm"][self._pgm_id]["stav"] == 1
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


class JablotronPIRBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jablotron PIR motion sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(
        self,
        coordinator,
        entry_id: str,
        pir_id: str,
        pir_name: str,
    ) -> None:
        """Initialize the PIR sensor."""
        super().__init__(coordinator)
        self._pir_id = pir_id
        self._attr_name = f"Jablotron {pir_name}"
        self._attr_unique_id = f"{entry_id}_pir_{pir_id}"

    @property
    def is_on(self) -> bool | None:
        """Return true if motion is detected."""
        if (
            self.coordinator.data
            and "pir" in self.coordinator.data
            and self._pir_id in self.coordinator.data["pir"]
        ):
            try:
                # PIR is "active" when active == 1
                return self.coordinator.data["pir"][self._pir_id]["active"] == 1
            except (KeyError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        if (
            self.coordinator.data
            and "pir" in self.coordinator.data
            and self._pir_id in self.coordinator.data["pir"]
        ):
            pir_data = self.coordinator.data["pir"][self._pir_id]
            attrs = {
                "pir_id": self._pir_id,
                "nazev": pir_data.get("nazev", ""),
                "state_name": pir_data.get("stateName", ""),
                "active": pir_data.get("active", None),
                "type": pir_data.get("type", ""),
            }
            if "last_pic" in pir_data and pir_data["last_pic"] != -1:
                attrs["last_picture"] = pir_data["last_pic"]
            return attrs
        return {}

