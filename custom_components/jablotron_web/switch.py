"""Switch platform for Jablotron Web."""
import logging
from typing import Any, Dict

from homeassistant.components.switch import SwitchEntity
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
    """Set up Jablotron switches from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]

    switches = []

    # Check if PGM code is configured - switches require it for control
    pgm_code = entry.data.get("pgm_code", "")
    if not pgm_code or not pgm_code.strip():
        _LOGGER.info("PGM control code not configured - switches will not be created. Configure PGM code in integration options to enable PGM switching.")
        async_add_entities(switches)
        return

    # Get initial data to determine available switchable PGMs
    if coordinator.data and "pgm" in coordinator.data:
        # Check if the user has permissions to control PGMs
        permissions = coordinator.data.get("permissions", {})
        
        _LOGGER.info(f"Evaluating {len(coordinator.data['pgm'])} PGMs for switch creation (PGM code configured)")

        for pgm_id, pgm_data in coordinator.data["pgm"].items():
            # Only create a switch if:
            # 1. PGM code is configured (checked above)
            # 2. PGM has a switchable reaction type
            # 3. User has permission to control it
            reaction = pgm_data.get("reaction", "")
            state_name = pgm_data.get("stateName", "")
            has_permission = permissions.get(state_name, 0) == 1
            pgm_name = pgm_data.get("nazev", f"PGM {pgm_id}")

            _LOGGER.debug(f"PGM {pgm_id} ({pgm_name}): reaction={reaction}, permission={has_permission}, switchable={reaction in PGM_SWITCHABLE_REACTIONS}")

            if reaction in PGM_SWITCHABLE_REACTIONS and has_permission:
                switches.append(
                    JablotronPGMSwitch(
                        coordinator,
                        client,
                        entry.entry_id,
                        pgm_id,
                        pgm_name,
                    )
                )
                _LOGGER.info(f"✅ CREATING SWITCH for PGM {pgm_id}: {pgm_name} (reaction: {reaction})")
            elif reaction in PGM_SWITCHABLE_REACTIONS and not has_permission:
                _LOGGER.info(f"⏭ SKIPPING PGM {pgm_id} ({pgm_name}) - switchable but no permission")
            else:
                _LOGGER.debug(f"⏭ SKIPPING PGM {pgm_id} ({pgm_name}) - not switchable (reaction: {reaction})")

    _LOGGER.info(f"Created {len(switches)} switch(es) for PGMs")
    async_add_entities(switches)


class JablotronPGMSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Jablotron PGM switch."""

    def __init__(
        self,
        coordinator,
        client,
        entry_id: str,
        pgm_id: str,
        pgm_name: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._client = client
        self._pgm_id = pgm_id
        self._attr_name = f"Jablotron {pgm_name}"
        self._attr_unique_id = f"{entry_id}_pgm_switch_{pgm_id}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            _LOGGER.debug(f"Turning on PGM {self._pgm_id}")
            result = await self._client.control_pgm(self._pgm_id, 1)
            _LOGGER.info(f"PGM {self._pgm_id} turned on: {result}")
            
            # Update coordinator data immediately
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to turn on PGM {self._pgm_id}: {err}")
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            _LOGGER.debug(f"Turning off PGM {self._pgm_id}")
            result = await self._client.control_pgm(self._pgm_id, 0)
            _LOGGER.info(f"PGM {self._pgm_id} turned off: {result}")
            
            # Update coordinator data immediately
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to turn off PGM {self._pgm_id}: {err}")
            raise

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

