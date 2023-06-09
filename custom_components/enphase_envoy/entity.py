"""Enphase Envoy entity."""
from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, INVERTERS_KEY

_LOGGER = logging.getLogger(__name__)


class EnvoyEntity(CoordinatorEntity):
    """Envoy entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: EntityDescription,
        name: str,
        serial_number: str,
    ) -> None:
        """Initialize envoy entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            configuration_url=f"https://{coordinator.config_entry.data[CONF_HOST]}",
            identifiers={(DOMAIN, serial_number)},
            manufacturer="Enphase",
            model="Envoy",
            name=name,
        )


class InverterEntity(CoordinatorEntity):
    """Inverter entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: EntityDescription,
        serial_number: str,
        envoy_serial_number: str,
    ) -> None:
        """Initialize inverter entity."""
        super().__init__(coordinator)
        self.entity_description = description
        if description.key == INVERTERS_KEY:
            self._attr_unique_id = serial_number
        else:
            self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            manufacturer="Enphase",
            model="Inverter",
            name=f"Inverter {serial_number}",
            via_device=(DOMAIN, envoy_serial_number),
        )
        self.serial_number = serial_number


class BatteryEntity(CoordinatorEntity):
    """Battery entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: EntityDescription,
        serial_number: str,
        envoy_serial_number: str,
    ) -> None:
        """Initialize battery entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            manufacturer="Enphase",
            model="Battery",
            name=f"Battery {serial_number}",
            via_device=(DOMAIN, envoy_serial_number),
        )
        self.serial_number = serial_number
