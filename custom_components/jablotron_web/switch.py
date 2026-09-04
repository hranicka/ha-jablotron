"""Switch platform for Jablotron Web."""
import logging
import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_PGM_CODE, PGM_REACTION_PULSE, PGM_SWITCHABLE_REACTIONS

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
    pgm_code = entry.data.get(CONF_PGM_CODE, "")
    if not pgm_code or not pgm_code.strip():
        _LOGGER.info("PGM control code not configured - switches will not be created. Configure PGM code in integration options to enable PGM switching.")
        async_add_entities(switches)
        return

    # Get initial data to determine available switchable PGMs
    if coordinator.data and "pgm" in coordinator.data:
        # Check if the user has permissions to control PGMs
        permissions = coordinator.data.get("permissions", {})

        for pgm_id, pgm_data in coordinator.data["pgm"].items():
            # Only create a switch if:
            # 1. PGM code is configured (checked above)
            # 2. PGM has a switchable reaction type
            # 3. User has permission to control it
            reaction = pgm_data.get("reaction", "")
            state_name = pgm_data.get("stateName", "")
            has_permission = permissions.get(state_name, 0) == 1
            pgm_name = pgm_data.get("nazev", f"PGM {pgm_id}")

            if reaction in PGM_SWITCHABLE_REACTIONS and has_permission:
                _LOGGER.debug("Creating switch for PGM %s (%s, reaction: %s)", pgm_id, pgm_name, reaction)
                switches.append(
                    JablotronPGMSwitch(
                        coordinator,
                        client,
                        entry.entry_id,
                        pgm_id,
                        pgm_name,
                        # A pulse output must not be re-fired if the command
                        # has to be retried after a session recovery
                        is_idempotent=reaction != PGM_REACTION_PULSE,
                    )
                )
            elif reaction in PGM_SWITCHABLE_REACTIONS:
                _LOGGER.debug("Skipping PGM %s (%s) - switchable but no permission", pgm_id, pgm_name)
            else:
                _LOGGER.debug("Skipping PGM %s (%s) - not switchable (reaction: %s)", pgm_id, pgm_name, reaction)

    _LOGGER.info("Created %d switch(es) for PGMs", len(switches))
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
        is_idempotent: bool = True,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._client = client
        self._pgm_id = pgm_id
        self._attr_name = f"Jablotron {pgm_name}"
        self._attr_unique_id = f"{entry_id}_pgm_switch_{pgm_id}"
        self._entry_id = entry_id
        self._is_idempotent = is_idempotent
        self._optimistic_state: bool | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"hub_{self._entry_id}")},
            name="Jablotron Alarm",
            manufacturer="Jablotron",
        )

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
        action = "on" if turn_on else "off"
        command = 1 if turn_on else 0

        try:
            # Set optimistic state immediately to freeze the switch during the operation
            self._optimistic_state = turn_on
            self.async_write_ha_state()

            _LOGGER.debug("Turning %s PGM %s, state frozen during operation", action, self._pgm_id)
            response = await self._client.control_pgm(
                self._pgm_id, command, retry_on_relogin=self._is_idempotent
            )
            _LOGGER.info("PGM %s control response: %s", self._pgm_id, response)

            # Cache the reported result so the state is correct even before
            # the next coordinator poll
            new_state = response.get("result") if response else None
            if not isinstance(new_state, int) or new_state not in (0, 1):
                _LOGGER.warning("Invalid result in PGM %s response: %r", self._pgm_id, new_state)
            elif not self.coordinator.set_pgm_state(
                self._pgm_id, new_state, response.get("ts") or int(time.time())
            ):
                _LOGGER.warning("Could not cache PGM %s state after control", self._pgm_id)
        except Exception as err:
            _LOGGER.error("Failed to turn %s PGM %s: %s", action, self._pgm_id, err, exc_info=True)
        finally:
            # Unfreeze: the state reported by coordinator data applies again
            self._optimistic_state = None
            self.async_write_ha_state()
            # Reconcile with the actual device state
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_control_pgm(turn_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_control_pgm(turn_on=False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
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

