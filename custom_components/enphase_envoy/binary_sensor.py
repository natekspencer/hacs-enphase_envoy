"""Support for Enphase Envoy binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import COORDINATOR, DOMAIN, NAME
from .entity import EnvoyEntity

GRID_STATUS_BINARY_SENSOR = BinarySensorEntityDescription(
    key="grid_status",
    name="Grid Status",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up envoy binary sensor platform."""
    data: dict = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: DataUpdateCoordinator = data[COORDINATOR]
    envoy_name: str = data[NAME]
    envoy_serial_num = config_entry.unique_id
    assert envoy_serial_num is not None

    entities = []
    if coordinator.data.get("grid_status") is not None:
        entities.append(
            EnvoyGridStatusEntity(
                coordinator, GRID_STATUS_BINARY_SENSOR, envoy_name, envoy_serial_num
            )
        )

    async_add_entities(entities)


class EnvoyGridStatusEntity(EnvoyEntity, BinarySensorEntity):
    """Envoy grid status entity."""

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return "mdi:transmission-tower" if self.is_on else "mdi:transmission-tower-off"

    @property
    def is_on(self) -> bool:
        """Return the status of the requested attribute."""
        return self.coordinator.data.get("grid_status") == "closed"
