"""Tests for the GlobalHotkeyListener (XDG Desktop Portal GlobalShortcuts)."""

import pytest
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gio, GLib

from speak2type.global_hotkey import (
    GlobalHotkeyListener,
    _APP_ID,
    _HOST_REGISTRY_IFACE,
    _PORTAL_BUS_NAME,
    _PORTAL_IFACE,
    _PORTAL_OBJECT_PATH,
    _REQUEST_IFACE,
    _SESSION_IFACE,
    _SHORTCUT_ID,
)


@pytest.fixture
def callbacks():
    """Return a pair of mock press/release callbacks."""
    return MagicMock(name="on_press"), MagicMock(name="on_release")


@pytest.fixture
def mock_bus():
    """Return a mock D-Bus connection with standard behaviors."""
    bus = MagicMock(spec=Gio.DBusConnection)
    bus.get_unique_name.return_value = ":1.42"
    bus.signal_subscribe.side_effect = lambda *a, **kw: (
        len(bus.signal_subscribe.call_args_list)
    )
    return bus


def _make_create_session_response(
    code: int = 0, session_handle: str = "/session/test"
) -> GLib.Variant:
    """Build a CreateSession Response signal payload."""
    data = {}
    if code == 0:
        data["session_handle"] = GLib.Variant("s", session_handle)
    return GLib.Variant("(ua{sv})", (code, data))


def _make_bind_response(code: int = 0) -> GLib.Variant:
    """Build a BindShortcuts Response signal payload."""
    return GLib.Variant("(ua{sv})", (code, {}))


def _make_activated_variant(session_handle: str, shortcut_id: str) -> GLib.Variant:
    """Build an Activated signal payload."""
    return GLib.Variant("(osta{sv})", (session_handle, shortcut_id, 0, {}))


def _make_deactivated_variant(session_handle: str, shortcut_id: str) -> GLib.Variant:
    """Build a Deactivated signal payload."""
    return GLib.Variant("(osta{sv})", (session_handle, shortcut_id, 0, {}))


class TestSetupPortalUnavailable:
    """setup() returns False when the portal is unreachable."""

    def test_no_session_bus(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")

        with patch(
            "speak2type.global_hotkey.Gio.bus_get_sync",
            side_effect=GLib.Error.new_literal(
                Gio.DBusError.quark(), "no bus", Gio.DBusError.FAILED
            ),
        ):
            assert listener.setup() is False

        on_press.assert_not_called()
        on_release.assert_not_called()

    def test_create_session_dbus_error(self, callbacks, mock_bus):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")

        mock_bus.call_sync.side_effect = GLib.Error.new_literal(
            Gio.DBusError.quark(),
            "org.freedesktop.DBus.Error.ServiceUnknown",
            Gio.DBusError.SERVICE_UNKNOWN,
        )

        with patch(
            "speak2type.global_hotkey.Gio.bus_get_sync", return_value=mock_bus
        ):
            assert listener.setup() is False


class TestAsyncCallbackChain:
    """Test the async CreateSession -> BindShortcuts callback chain."""

    def test_create_session_response_triggers_bind(self, callbacks, mock_bus):
        """Successful CreateSession response chains to BindShortcuts."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._sender_token = "1_42"

        mock_bus.call_sync.return_value = GLib.Variant("(o)", ("/dummy/request",))

        params = _make_create_session_response(
            code=0,
            session_handle="/org/freedesktop/portal/desktop/session/1_42/test",
        )
        listener._on_create_session_response(
            mock_bus, _PORTAL_BUS_NAME, "/dummy/request",
            _REQUEST_IFACE, "Response", params,
        )

        assert listener._session_handle == (
            "/org/freedesktop/portal/desktop/session/1_42/test"
        )
        # BindShortcuts should have been called
        assert mock_bus.call_sync.called
        bind_call = mock_bus.call_sync.call_args
        assert bind_call[0][3] == "BindShortcuts"

    def test_create_session_failure_does_not_bind(self, callbacks, mock_bus):
        """Failed CreateSession does not chain to BindShortcuts."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._sender_token = "1_42"

        params = _make_create_session_response(code=1)
        listener._on_create_session_response(
            mock_bus, _PORTAL_BUS_NAME, "/dummy/request",
            _REQUEST_IFACE, "Response", params,
        )

        assert listener._session_handle is None
        mock_bus.call_sync.assert_not_called()

    def test_bind_response_success_sets_active(self, callbacks, mock_bus):
        """Successful BindShortcuts response keeps session alive."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._session_handle = "/session/test"

        params = _make_bind_response(code=0)
        listener._on_bind_shortcuts_response(
            mock_bus, _PORTAL_BUS_NAME, "/dummy/request",
            _REQUEST_IFACE, "Response", params,
        )

        # Session should still be set (not torn down)
        assert listener._session_handle == "/session/test"

    def test_bind_response_denied_tears_down(self, callbacks, mock_bus):
        """Denied BindShortcuts response tears down the session."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._session_handle = "/session/test"
        listener._signal_ids = []

        params = _make_bind_response(code=1)
        listener._on_bind_shortcuts_response(
            mock_bus, _PORTAL_BUS_NAME, "/dummy/request",
            _REQUEST_IFACE, "Response", params,
        )

        assert listener._session_handle is None

    def test_setup_dispatches_create_session(self, callbacks, mock_bus):
        """setup() dispatches CreateSession and returns True."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")

        mock_bus.call_sync.return_value = GLib.Variant("(o)", ("/dummy/request",))

        with patch(
            "speak2type.global_hotkey.Gio.bus_get_sync", return_value=mock_bus
        ):
            result = listener.setup()

        assert result is True
        # CreateSession should have been called
        create_call = mock_bus.call_sync.call_args
        assert create_call[0][3] == "CreateSession"


class TestSignalHandlers:
    """Test Activated/Deactivated signal dispatch."""

    def test_activated_calls_on_press(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._session_handle = "/session/test"

        params = _make_activated_variant("/session/test", _SHORTCUT_ID)
        listener._on_activated(
            None, _PORTAL_BUS_NAME, _PORTAL_OBJECT_PATH,
            _PORTAL_IFACE, "Activated", params,
        )

        on_press.assert_called_once()
        on_release.assert_not_called()

    def test_deactivated_calls_on_release(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._session_handle = "/session/test"

        params = _make_deactivated_variant("/session/test", _SHORTCUT_ID)
        listener._on_deactivated(
            None, _PORTAL_BUS_NAME, _PORTAL_OBJECT_PATH,
            _PORTAL_IFACE, "Deactivated", params,
        )

        on_release.assert_called_once()
        on_press.assert_not_called()

    def test_wrong_session_ignored(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._session_handle = "/session/test"

        params = _make_activated_variant("/session/other", _SHORTCUT_ID)
        listener._on_activated(
            None, _PORTAL_BUS_NAME, _PORTAL_OBJECT_PATH,
            _PORTAL_IFACE, "Activated", params,
        )

        on_press.assert_not_called()

    def test_wrong_shortcut_id_ignored(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._session_handle = "/session/test"

        params = _make_activated_variant("/session/test", "some-other-shortcut")
        listener._on_activated(
            None, _PORTAL_BUS_NAME, _PORTAL_OBJECT_PATH,
            _PORTAL_IFACE, "Activated", params,
        )

        on_press.assert_not_called()


class TestTeardown:
    """Test session cleanup."""

    def test_teardown_closes_session(self, callbacks, mock_bus):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._session_handle = "/session/test"
        listener._signal_ids = [1, 2]

        listener.teardown()

        assert mock_bus.signal_unsubscribe.call_count == 2

        mock_bus.call_sync.assert_called_once()
        close_call = mock_bus.call_sync.call_args
        assert close_call[0][2] == _SESSION_IFACE
        assert close_call[0][3] == "Close"

        assert listener._session_handle is None

    def test_teardown_without_session_is_safe(self, callbacks):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener.teardown()


class TestUpdateShortcut:
    """Test rebinding with a new accelerator."""

    def test_update_calls_bind_shortcuts(self, callbacks, mock_bus):
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        listener._session_handle = "/session/test"
        listener._sender_token = "1_42"

        mock_bus.call_sync.return_value = GLib.Variant("(o)", ("/dummy/request",))

        listener.update_shortcut("<Ctrl>r")

        assert listener._accelerator == "<Ctrl>r"
        assert mock_bus.call_sync.called


class TestProviderShim:
    """Test the GlobalShortcutsProvider shim (LP#2107533 workaround)."""

    def test_bind_shortcuts_returns_approved_shortcuts(self):
        """BindShortcuts auto-approves the requested shortcuts."""
        invocation = MagicMock(spec=Gio.DBusMethodInvocation)

        shortcuts = GLib.Variant(
            "(ssa(sa{sv}))",
            (
                "ibus-setup-speak2type",
                "",
                [
                    (
                        "speak2type-ptt",
                        {
                            "description": GLib.Variant("s", "Push-to-talk"),
                            "preferred_trigger": GLib.Variant("s", "<Ctrl>space"),
                        },
                    )
                ],
            ),
        )

        GlobalHotkeyListener._on_provider_method_call(
            None, "sender", "/path", "iface", "BindShortcuts", shortcuts, invocation,
        )

        invocation.return_value.assert_called_once()
        result = invocation.return_value.call_args[0][0]
        # Result should be a tuple with an array of (s, a{sv})
        inner = result.get_child_value(0)
        assert inner.n_children() == 1
        entry = inner.get_child_value(0)
        sid = entry.get_child_value(0).get_string()
        assert sid == "speak2type-ptt"
        props = entry.get_child_value(1)
        desc = props.lookup_value("description", GLib.VariantType("s"))
        assert desc.get_string() == "Push-to-talk"
        trigger_desc = props.lookup_value("trigger_description", GLib.VariantType("s"))
        assert trigger_desc.get_string() == "Press <Ctrl>space"
        shortcuts_val = props.lookup_value("shortcuts", GLib.VariantType("as"))
        assert shortcuts_val.unpack() == ["<Ctrl>space"]

    def test_bind_shortcuts_without_trigger(self):
        """BindShortcuts handles missing preferred_trigger gracefully."""
        invocation = MagicMock(spec=Gio.DBusMethodInvocation)

        shortcuts = GLib.Variant(
            "(ssa(sa{sv}))",
            (
                "test-app",
                "",
                [
                    (
                        "test-shortcut",
                        {
                            "description": GLib.Variant("s", "Test"),
                        },
                    )
                ],
            ),
        )

        GlobalHotkeyListener._on_provider_method_call(
            None, "sender", "/path", "iface", "BindShortcuts", shortcuts, invocation,
        )

        invocation.return_value.assert_called_once()
        result = invocation.return_value.call_args[0][0]
        inner = result.get_child_value(0)
        entry = inner.get_child_value(0)
        props = entry.get_child_value(1)
        # No "shortcuts" key when trigger is empty
        shortcuts_val = props.lookup_value("shortcuts", GLib.VariantType("as"))
        assert shortcuts_val is None

    def test_unknown_method_returns_error(self):
        """Non-BindShortcuts methods return a D-Bus error."""
        invocation = MagicMock(spec=Gio.DBusMethodInvocation)

        GlobalHotkeyListener._on_provider_method_call(
            None, "sender", "/path", "iface", "UnknownMethod",
            GLib.Variant("(s)", ("arg",)), invocation,
        )

        invocation.return_dbus_error.assert_called_once()
        error_name = invocation.return_dbus_error.call_args[0][0]
        assert error_name == "org.freedesktop.DBus.Error.UnknownMethod"


class TestHostRegistration:
    """Test host app registration and provider shim lifecycle."""

    def test_register_host_app_calls_registry(self, callbacks, mock_bus):
        """_register_host_app calls the host portal Registry."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus

        listener._register_host_app()

        mock_bus.call_sync.assert_called_once()
        call_args = mock_bus.call_sync.call_args[0]
        assert call_args[0] == _PORTAL_BUS_NAME
        assert call_args[2] == _HOST_REGISTRY_IFACE
        assert call_args[3] == "Register"
        # Verify app_id is passed
        variant_args = call_args[4]
        app_id = variant_args.get_child_value(0).get_string()
        assert app_id == _APP_ID

    def test_register_host_app_tolerates_error(self, callbacks, mock_bus):
        """_register_host_app logs but does not raise on error."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus
        mock_bus.call_sync.side_effect = GLib.Error.new_literal(
            Gio.DBusError.quark(), "no registry", Gio.DBusError.UNKNOWN_METHOD,
        )

        # Should not raise
        listener._register_host_app()

    def test_provider_shim_tolerates_mock_bus(self, callbacks, mock_bus):
        """_start_provider_shim does not crash with a mock bus."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")
        listener._bus = mock_bus

        # MagicMock bus triggers TypeError in Gio.bus_own_name_on_connection
        # which should be caught gracefully
        listener._start_provider_shim()

    def test_stop_provider_shim_without_start(self, callbacks):
        """_stop_provider_shim is safe when shim was never started."""
        on_press, on_release = callbacks
        listener = GlobalHotkeyListener(on_press, on_release, "<Alt>space")

        # Should not raise
        listener._stop_provider_shim()
