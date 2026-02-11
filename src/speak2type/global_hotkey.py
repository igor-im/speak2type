"""Global hotkey listener using XDG Desktop Portal GlobalShortcuts.

Provides push-to-talk activation for non-IBus apps (e.g. VSCode, Electron)
where IBus key events are not forwarded to the engine.

The GlobalShortcuts portal (available on GNOME 48+, KDE Plasma 6.1+) grabs
keys at the compositor level and delivers Activated/Deactivated signals over
D-Bus — exactly the press/release semantics needed for push-to-talk.

If the portal is unavailable the listener degrades gracefully: setup()
returns False and the engine continues with IBus-only key handling.
See .aisteering/policy-exceptions.md — GLOBAL_HOTKEY_GRACEFUL_DEGRADATION.
"""

import logging
import os
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gio, GLib

LOG = logging.getLogger(__name__)

_PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"
_HOST_REGISTRY_IFACE = "org.freedesktop.host.portal.Registry"

_SHORTCUT_ID = "speak2type-ptt"
_APP_ID = "ibus-setup-speak2type"

_PROVIDER_BUS_NAME = "org.gnome.Settings.GlobalShortcutsProvider"
_PROVIDER_OBJECT_PATH = "/org/gnome/Settings/GlobalShortcutsProvider"
_PROVIDER_IFACE = "org.gnome.Settings.GlobalShortcutsProvider"

_PROVIDER_IFACE_XML = """
<node>
  <interface name="org.gnome.Settings.GlobalShortcutsProvider">
    <method name="BindShortcuts">
      <arg name="app_id" type="s" direction="in"/>
      <arg name="parent_window" type="s" direction="in"/>
      <arg name="shortcuts" type="a(sa{sv})" direction="in"/>
      <arg name="results" type="a(sa{sv})" direction="out"/>
    </method>
  </interface>
</node>
"""


class GlobalHotkeyListener:
    """Listens for a global PTT hotkey via the XDG Desktop Portal.

    Uses async D-Bus calls that integrate with the caller's GLib main loop
    instead of blocking nested loops (which don't dispatch signals when
    another main loop is already running, e.g. the IBus engine).
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        accelerator: str,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._accelerator = accelerator

        self._bus: Gio.DBusConnection | None = None
        self._session_handle: str | None = None
        self._signal_ids: list[int] = []
        self._sender_token: str | None = None
        self._provider_reg_id: int = 0
        self._provider_name_id: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup(self) -> bool:
        """Begin the async portal session setup.

        Returns True if the CreateSession D-Bus call was dispatched
        successfully. The actual session and shortcut binding happen
        asynchronously via callbacks on the GLib main loop. Returns
        False if the portal is clearly unavailable (no session bus,
        D-Bus call error).
        """
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as exc:
            LOG.warning("Cannot connect to session bus: %s", exc.message)
            return False

        unique = self._bus.get_unique_name()
        self._sender_token = unique.lstrip(":").replace(".", "_")

        self._register_host_app()
        self._start_provider_shim()

        return self._create_session_async()

    def teardown(self) -> None:
        """Close the session and clean up D-Bus subscriptions."""
        for sid in self._signal_ids:
            if self._bus:
                self._bus.signal_unsubscribe(sid)
        self._signal_ids.clear()

        if self._bus and self._session_handle:
            try:
                self._bus.call_sync(
                    _PORTAL_BUS_NAME,
                    self._session_handle,
                    _SESSION_IFACE,
                    "Close",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    500,
                    None,
                )
            except GLib.Error:
                pass  # session may already be closed
            LOG.info("Global hotkey session closed")

        self._session_handle = None
        self._stop_provider_shim()

    def update_shortcut(self, accelerator: str) -> None:
        """Re-bind the shortcut with a new accelerator."""
        self._accelerator = accelerator
        if self._session_handle and self._bus:
            self._bind_shortcuts_async(accelerator)
            LOG.info("Global hotkey re-bind requested: %s", accelerator)

    # ------------------------------------------------------------------
    # Host app registration & provider shim
    # ------------------------------------------------------------------

    def _register_host_app(self) -> None:
        """Register with the host portal registry for app identity.

        Non-sandboxed (host) processes have no automatic app_id. The
        portal's host.portal.Registry.Register associates our D-Bus
        connection with a .desktop file so the portal can identify us.
        """
        try:
            self._bus.call_sync(
                _PORTAL_BUS_NAME,
                _PORTAL_OBJECT_PATH,
                _HOST_REGISTRY_IFACE,
                "Register",
                GLib.Variant("(sa{sv})", (_APP_ID, {})),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            LOG.debug("Registered host app_id: %s", _APP_ID)
        except GLib.Error as exc:
            LOG.debug("Host registry unavailable (ok for snap/flatpak): %s",
                      exc.message)

    def _start_provider_shim(self) -> None:
        """Start a minimal GlobalShortcutsProvider on D-Bus.

        Workaround for gnome-control-center LP#2107533: the system
        provider's BindShortcuts handler crashes for non-snap apps.
        We claim the bus name first so the portal uses our shim instead.
        The shim auto-approves shortcuts (the user already configured the
        hotkey in speak2type preferences).
        """
        try:
            node = Gio.DBusNodeInfo.new_for_xml(_PROVIDER_IFACE_XML)
            self._provider_reg_id = self._bus.register_object(
                _PROVIDER_OBJECT_PATH,
                node.interfaces[0],
                self._on_provider_method_call,
                None,
                None,
            )
            self._provider_name_id = Gio.bus_own_name_on_connection(
                self._bus,
                _PROVIDER_BUS_NAME,
                Gio.BusNameOwnerFlags.NONE,
                None,
                None,
            )
            LOG.debug("GlobalShortcutsProvider shim active")
        except (GLib.Error, TypeError) as exc:
            LOG.debug("Provider shim not started: %s", exc)

    def _stop_provider_shim(self) -> None:
        """Release the provider shim from D-Bus."""
        if self._provider_name_id:
            Gio.bus_unown_name(self._provider_name_id)
            self._provider_name_id = 0
        if self._provider_reg_id and self._bus:
            self._bus.unregister_object(self._provider_reg_id)
            self._provider_reg_id = 0

    @staticmethod
    def _on_provider_method_call(
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        """Handle BindShortcuts calls from the portal backend."""
        if method_name != "BindShortcuts":
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Method {method_name} not implemented",
            )
            return

        shortcuts = parameters.get_child_value(2)
        results = []
        for i in range(shortcuts.n_children()):
            entry = shortcuts.get_child_value(i)
            sid = entry.get_child_value(0).get_string()
            props = entry.get_child_value(1)

            desc_v = props.lookup_value("description", GLib.VariantType("s"))
            trigger_v = props.lookup_value(
                "preferred_trigger", GLib.VariantType("s")
            )
            desc = desc_v.get_string() if desc_v else "Shortcut"
            trigger = trigger_v.get_string() if trigger_v else ""

            result_props: dict[str, GLib.Variant] = {
                "description": GLib.Variant("s", desc),
                "trigger_description": GLib.Variant(
                    "s", f"Press {trigger}" if trigger else ""
                ),
            }
            if trigger:
                result_props["shortcuts"] = GLib.Variant("as", [trigger])
            results.append((sid, result_props))

        LOG.debug("Provider shim: approved %d shortcut(s)", len(results))
        invocation.return_value(
            GLib.Variant.new_tuple(GLib.Variant("a(sa{sv})", results))
        )

    # ------------------------------------------------------------------
    # Async portal D-Bus flow
    # ------------------------------------------------------------------

    def _create_session_async(self) -> bool:
        """Dispatch CreateSession and subscribe to its Response."""
        token_cs = f"speak2type_cs_{os.getpid()}"
        token_session = f"speak2type_session_{os.getpid()}"
        self._pending_session_token = token_session

        request_path = (
            f"/org/freedesktop/portal/desktop/request/"
            f"{self._sender_token}/{token_cs}"
        )

        # Subscribe to Response BEFORE calling (avoid race)
        sid = self._bus.signal_subscribe(
            _PORTAL_BUS_NAME,
            _REQUEST_IFACE,
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_create_session_response,
        )
        self._signal_ids.append(sid)

        try:
            options = GLib.Variant(
                "a{sv}",
                {
                    "handle_token": GLib.Variant("s", token_cs),
                    "session_handle_token": GLib.Variant("s", token_session),
                },
            )
            self._bus.call_sync(
                _PORTAL_BUS_NAME,
                _PORTAL_OBJECT_PATH,
                _PORTAL_IFACE,
                "CreateSession",
                GLib.Variant.new_tuple(options),
                GLib.VariantType.new("(o)"),
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
        except GLib.Error as exc:
            LOG.warning("GlobalShortcuts portal unavailable: %s", exc.message)
            return False

        LOG.debug("CreateSession dispatched, waiting for Response...")
        return True

    def _on_create_session_response(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface: str,
        signal: str,
        params: GLib.Variant,
    ) -> None:
        """Handle the Response signal for CreateSession."""
        response_code = params.get_child_value(0).get_uint32()
        response_data = params.get_child_value(1)

        if response_code != 0:
            LOG.warning("CreateSession failed (code=%d)", response_code)
            return

        # Extract session handle from response data
        sh_variant = response_data.lookup_value(
            "session_handle", GLib.VariantType.new("s")
        )
        if sh_variant:
            self._session_handle = sh_variant.get_string()
        else:
            # Fallback: construct from token
            self._session_handle = (
                f"/org/freedesktop/portal/desktop/session/"
                f"{self._sender_token}/{self._pending_session_token}"
            )

        LOG.info("Portal session created: %s", self._session_handle)

        # Subscribe to Activated/Deactivated
        self._subscribe_shortcut_signals()

        # Chain: now bind shortcuts
        self._bind_shortcuts_async(self._accelerator)

    def _bind_shortcuts_async(self, accelerator: str) -> None:
        """Dispatch BindShortcuts and subscribe to its Response."""
        token_bs = f"speak2type_bs_{os.getpid()}"
        request_path = (
            f"/org/freedesktop/portal/desktop/request/"
            f"{self._sender_token}/{token_bs}"
        )

        sid = self._bus.signal_subscribe(
            _PORTAL_BUS_NAME,
            _REQUEST_IFACE,
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_bind_shortcuts_response,
        )
        self._signal_ids.append(sid)

        try:
            shortcut_props = {
                "description": GLib.Variant(
                    "s", "Push-to-talk for speech recognition"
                ),
                "preferred_trigger": GLib.Variant("s", accelerator),
            }

            options = {
                "handle_token": GLib.Variant("s", token_bs),
            }

            args = GLib.Variant(
                "(oa(sa{sv})sa{sv})",
                (
                    self._session_handle,
                    [(_SHORTCUT_ID, shortcut_props)],
                    "",
                    options,
                ),
            )
            self._bus.call_sync(
                _PORTAL_BUS_NAME,
                _PORTAL_OBJECT_PATH,
                _PORTAL_IFACE,
                "BindShortcuts",
                args,
                GLib.VariantType.new("(o)"),
                Gio.DBusCallFlags.NONE,
                30000,
                None,
            )
        except GLib.Error as exc:
            LOG.error("BindShortcuts call failed: %s", exc.message)
            return

        LOG.debug("BindShortcuts dispatched, waiting for Response...")

    def _on_bind_shortcuts_response(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface: str,
        signal: str,
        params: GLib.Variant,
    ) -> None:
        """Handle the Response signal for BindShortcuts."""
        response_code = params.get_child_value(0).get_uint32()

        if response_code != 0:
            LOG.warning(
                "BindShortcuts denied or cancelled (code=%d)", response_code
            )
            self.teardown()
            return

        LOG.info(
            "Global hotkey active: %s (session %s)",
            self._accelerator,
            self._session_handle,
        )

    # ------------------------------------------------------------------
    # Shortcut signal handlers
    # ------------------------------------------------------------------

    def _subscribe_shortcut_signals(self) -> None:
        """Subscribe to Activated and Deactivated signals."""
        sid_activated = self._bus.signal_subscribe(
            _PORTAL_BUS_NAME,
            _PORTAL_IFACE,
            "Activated",
            _PORTAL_OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_activated,
        )
        sid_deactivated = self._bus.signal_subscribe(
            _PORTAL_BUS_NAME,
            _PORTAL_IFACE,
            "Deactivated",
            _PORTAL_OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_deactivated,
        )
        self._signal_ids.extend([sid_activated, sid_deactivated])

    def _on_activated(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface: str,
        signal: str,
        params: GLib.Variant,
    ) -> None:
        """Handle Activated signal from the portal."""
        session = params.get_child_value(0).get_string()
        shortcut_id = params.get_child_value(1).get_string()

        if session != self._session_handle or shortcut_id != _SHORTCUT_ID:
            return

        LOG.debug("Portal shortcut activated: %s", shortcut_id)
        self._on_press()

    def _on_deactivated(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface: str,
        signal: str,
        params: GLib.Variant,
    ) -> None:
        """Handle Deactivated signal from the portal."""
        session = params.get_child_value(0).get_string()
        shortcut_id = params.get_child_value(1).get_string()

        if session != self._session_handle or shortcut_id != _SHORTCUT_ID:
            return

        LOG.debug("Portal shortcut deactivated: %s", shortcut_id)
        self._on_release()
