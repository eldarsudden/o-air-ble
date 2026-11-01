"""Local Bluetooth support for Alesinx O-Air."""


async def async_setup_entry(hass, entry):
    from .const import PLATFORMS
    from .coordinator import OAirCoordinator

    coordinator = OAirCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    from .const import PLATFORMS

    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown_connection()
    return unloaded
