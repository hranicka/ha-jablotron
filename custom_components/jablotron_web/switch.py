"""Switch platform for Jablotron Web."""
import logging
import time
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
        self._optimistic_state: bool | None = None

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Don't update if we have an optimistic state pending
        # This prevents coordinator updates from overwriting our optimistic UI
        if self._optimistic_state is None:
            super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        # Use optimistic state if set (during pending operation)
        if self._optimistic_state is not None:
            return self._optimistic_state

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

    async def _async_control_pgm(self, turn_on: bool) -> None:
        """Control the PGM switch (shared logic for on/off).

        Args:
            turn_on: True to turn on, False to turn off
        """
        previous_state = self.is_on
        action = "on" if turn_on else "off"
        command = 1 if turn_on else 0

        try:
            # Set optimistic state immediately to freeze the switch during the operation
            # This prevents coordinator updates from changing the state while we're switching
            self._optimistic_state = turn_on
            self.async_write_ha_state()

            _LOGGER.debug(f"Turning {action} PGM {self._pgm_id}, state frozen during operation")
            response = await self._client.control_pgm(self._pgm_id, command)
            _LOGGER.info(f"PGM {self._pgm_id} control response: {response}")

            # Process the response and update coordinator data immediately
            # Response format: {"ts": 123, "id": "PGM_7", "authorization": 200, "result": 0/1, "responseCode": 200}
            if response and "result" in response and self.coordinator.data:
                new_state = response.get("result")
                if isinstance(new_state, int) and new_state in (0, 1):
                    # Update the coordinator's data with the fresh state from the response
                    _LOGGER.debug(f"Updating coordinator data with response state: {new_state} for PGM {self._pgm_id}")
                    if "pgm" not in self.coordinator.data:
                        self.coordinator.data["pgm"] = {}
                    if self._pgm_id not in self.coordinator.data["pgm"]:
                        self.coordinator.data["pgm"][self._pgm_id] = {}

                    # Update the state in coordinator data
                    self.coordinator.data["pgm"][self._pgm_id]["stav"] = new_state
                    self.coordinator.data["pgm"][self._pgm_id]["ts"] = response.get("ts", int(time.time()))

                    # Clear optimistic state BEFORE triggering update so this switch can process it
                    self._optimistic_state = None

                    # Trigger coordinator update to notify all listeners (including this switch)
                    self.coordinator.async_set_updated_data(self.coordinator.data)
                    _LOGGER.debug(f"Coordinator data updated, state unfrozen for PGM {self._pgm_id}")
                else:
                    # Invalid response, clear optimistic state
                    _LOGGER.warning(f"Invalid result in response: {new_state}")
                    self._optimistic_state = None
            else:
                # No valid response, clear optimistic state
                _LOGGER.warning(f"No valid response data for PGM {self._pgm_id}")
                self._optimistic_state = None

            # Request a full refresh to get all updated data (for other sensors, etc.)
            # This also ensures we have the latest state from the server
            await self.coordinator.async_request_refresh()

            # State should already be cleared above, but ensure it's None
            self._optimistic_state = None
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error(f"Failed to turn {action} PGM {self._pgm_id}: {err}")
            # Revert to previous state on failure
            self._optimistic_state = previous_state
            self.async_write_ha_state()
            # Clear optimistic state after a moment
            self._optimistic_state = None
            raise

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_control_pgm(turn_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_control_pgm(turn_on=False)

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

