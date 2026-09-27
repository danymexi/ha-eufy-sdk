"""DataUpdateCoordinator for eufy_sdk — owns the bridge connection + the device list."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EufySdkApiClientAuthenticationError, EufySdkApiClientError

if TYPE_CHECKING:
    from .data import EufySdkConfigEntry


class EufySdkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Keep the bridge connected and expose the device list as `{sn: device}`."""

    config_entry: EufySdkConfigEntry

    # Anker Solix devices (separate account/backend), kept apart from the eufy `data`
    # so the eufy platforms never iterate them: `{sn: {productCode, name, category,
    # capabilities, values, ...}}`. Empty unless the bridge has SOLIX_* configured;
    # reassigned per-update, so the class-level {} is only an initial fallback. Live
    # values arrive via `solixReading` events.
    solix_devices: ClassVar[dict[str, dict]] = {}

    # A single failed poll marks every entity `unavailable` until the NEXT poll — up to
    # `update_interval` (10 min) of blackout for one transient hiccup (a wedged WS, a slow
    # `list_devices`, a boot still "pending"). This schedules a fast retry (~45 s) after any
    # failure so entities recover in under a minute, without raising the steady-state poll rate.
    _FAST_RETRY_S = 45
    _fast_retry_cancel = None

    @callback
    def _schedule_fast_retry(self) -> None:
        if self._fast_retry_cancel is not None:
            return  # one already pending
        self._fast_retry_cancel = async_call_later(
            self.hass, self._FAST_RETRY_S, self._fast_retry_fire
        )

    @callback
    def _fast_retry_fire(self, _now) -> None:
        self._fast_retry_cancel = None
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _clear_fast_retry(self) -> None:
        if self._fast_retry_cancel is not None:
            self._fast_retry_cancel()
            self._fast_retry_cancel = None

    async def _async_update_data(self) -> dict[str, dict]:
        """Ensure the connection is up, confirm we're authed, and return the devices."""
        client = self.config_entry.runtime_data.client
        try:
            if not client.connected:
                await client.connect()
            auth = await client.auth_status()
            state = auth.get("state")
            if state in ("require_2fa", "require_captcha"):
                # Genuinely needs the user — start the reauth flow.
                msg = f"bridge needs re-authentication (state: {state})"
                raise ConfigEntryAuthFailed(msg)
            if state != "ok":
                # Transient: the bridge is still booting/logging in ("pending" after a
                # restart). Retry fast (below) instead of waiting a full interval or
                # freezing the entry in reauth.
                self._schedule_fast_retry()
                msg = f"bridge not ready yet (state: {state})"
                raise UpdateFailed(msg)
            devices = await client.list_devices()
        except EufySdkApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(err) from err
        except EufySdkApiClientError as err:
            # A wedged WS won't clear `connected` on its own; drop it so the fast retry
            # reconnects fresh rather than timing out on the same dead socket.
            self._schedule_fast_retry()
            await client.reset_connection()
            raise UpdateFailed(err) from err
        # Solix is optional + independent: a hiccup must not fail the eufy update.
        try:
            solix = await client.list_solix_devices()
            self.solix_devices = {d["sn"]: d for d in solix if d.get("sn")}
        except EufySdkApiClientError:
            self.solix_devices = getattr(self, "solix_devices", {})
        self._clear_fast_retry()
        return {d["sn"]: d for d in devices if d.get("sn")}
