"""Local Bluetooth support for Alesinx O-Air."""


async def async_setup_entry(hass, entry):
    from .const import PLATFORMS
    from .coordinator import OAirCoordinator

    coordinator = OAirCoordinator(hass, entry)
    await coordinator.async_initial_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "O-Air initial datapoint refresh"
    )
    return True


async def async_unload_entry(hass, entry):
    from .const import PLATFORMS

    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown_connection()
    return unloaded
