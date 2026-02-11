"""GTK4/Adwaita preferences window for speak2type.

Provides a settings UI for managing speech recognition backends,
installing dependencies, and downloading models.
"""

import logging
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .backend_manager import BACKEND_SPECS, BackendManager

LOG = logging.getLogger(__name__)


class BackendRow(Adw.ActionRow):
    """A row representing a single backend with install/remove controls."""

    def __init__(self, backend_id: str, manager: BackendManager, window: "PreferencesWindow"):
        spec = BACKEND_SPECS[backend_id]
        super().__init__(
            title=spec.name,
            subtitle=spec.description,
        )
        self._backend_id = backend_id
        self._manager = manager
        self._window = window
        self._installing = False

        # Action button (Install / Remove)
        self._action_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self._action_button.connect("clicked", self._on_action_clicked)
        self.add_suffix(self._action_button)

        # Spinner (shown during install)
        self._spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.add_suffix(self._spinner)
        self._spinner.set_visible(False)

        # Status icon
        self._status_icon = Gtk.Image(valign=Gtk.Align.CENTER)
        self.add_prefix(self._status_icon)

        self.refresh_status()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def refresh_status(self) -> None:
        """Update the row UI based on current install status."""
        if self._installing:
            return

        deps_installed = self._manager.is_deps_installed(self._backend_id)

        if deps_installed:
            self._action_button.set_label("Remove")
            self._action_button.remove_css_class("suggested-action")
            self._action_button.add_css_class("destructive-action")
            self._status_icon.set_from_icon_name("emblem-ok-symbolic")
        else:
            self._action_button.set_label("Install")
            self._action_button.add_css_class("suggested-action")
            self._action_button.remove_css_class("destructive-action")
            self._status_icon.set_from_icon_name("software-install-symbolic")

    def _on_action_clicked(self, _button: Gtk.Button) -> None:
        if self._installing:
            return

        deps_installed = self._manager.is_deps_installed(self._backend_id)
        if deps_installed:
            self._start_uninstall()
        else:
            self._start_install()

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._installing = busy
        self._spinner.set_visible(busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._action_button.set_sensitive(not busy)
        if label:
            self._action_button.set_label(label)

    def _start_install(self) -> None:
        self._set_busy(True, "Installing...")
        thread = threading.Thread(target=self._install_thread, daemon=True)
        thread.start()

    def _install_thread(self) -> None:
        try:
            self._manager.install_deps(self._backend_id)
            # If backend has models, try to download the default model
            spec = BACKEND_SPECS[self._backend_id]
            model_error = None
            if spec.has_models:
                GLib.idle_add(self._set_busy, True, "Downloading model...")
                try:
                    manager = self._manager.get_model_manager(self._backend_id)
                    if manager is not None:
                        model_id = manager.get_default_model_for_locale("en_US")
                        result = manager.download_model(model_id)
                        if result is None:
                            model_error = "Download returned no model path"
                except Exception as e:
                    model_error = str(e)
                    LOG.error("Model download failed for %s: %s", self._backend_id, e)

            GLib.idle_add(self._on_install_done, model_error)
        except subprocess.CalledProcessError as e:
            GLib.idle_add(self._on_install_error, e.stderr or str(e))
        except Exception as e:
            GLib.idle_add(self._on_install_error, str(e))

    def _on_install_done(self, model_error: str | None) -> None:
        self._set_busy(False)
        self.refresh_status()
        self._window.refresh_model_page()
        spec = BACKEND_SPECS[self._backend_id]
        if model_error:
            self._window.show_toast(
                f"{spec.name} installed, but model download failed: {model_error}"
            )
        else:
            self._window.show_toast(f"{spec.name} installed successfully")

    def _on_install_error(self, error_msg: str) -> None:
        self._set_busy(False)
        self.refresh_status()
        spec = BACKEND_SPECS[self._backend_id]
        self._window.show_toast(f"Failed to install {spec.name}: {error_msg}")

    def _start_uninstall(self) -> None:
        self._set_busy(True, "Removing...")
        thread = threading.Thread(target=self._uninstall_thread, daemon=True)
        thread.start()

    def _uninstall_thread(self) -> None:
        try:
            self._manager.uninstall_deps(self._backend_id)
            GLib.idle_add(self._on_uninstall_done)
        except Exception as e:
            GLib.idle_add(self._on_uninstall_error, str(e))

    def _on_uninstall_done(self) -> None:
        self._set_busy(False)
        self.refresh_status()
        self._window.refresh_model_page()
        spec = BACKEND_SPECS[self._backend_id]
        self._window.show_toast(f"{spec.name} removed")

    def _on_uninstall_error(self, error_msg: str) -> None:
        self._set_busy(False)
        self.refresh_status()
        spec = BACKEND_SPECS[self._backend_id]
        self._window.show_toast(f"Failed to remove {spec.name}: {error_msg}")


class ModelRow(Adw.ActionRow):
    """A row representing a downloadable model."""

    def __init__(
        self,
        model_spec: object,
        is_installed: bool,
        manager: "BackendManager",
        model_manager: object,
        window: "PreferencesWindow",
    ):
        super().__init__(
            title=model_spec.name,
            subtitle=f"{model_spec.description} ({model_spec.size_mb} MB)",
        )
        self._model_id = model_spec.id
        self._manager = manager
        self._model_manager = model_manager
        self._window = window
        self._busy = False

        self._action_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self._action_button.connect("clicked", self._on_action_clicked)
        self.add_suffix(self._action_button)

        self._spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self.add_suffix(self._spinner)
        self._spinner.set_visible(False)

        self._update_ui(is_installed)

    def _update_ui(self, is_installed: bool) -> None:
        if is_installed:
            self._action_button.set_label("Remove")
            self._action_button.remove_css_class("suggested-action")
            self._action_button.add_css_class("destructive-action")
        else:
            self._action_button.set_label("Download")
            self._action_button.add_css_class("suggested-action")
            self._action_button.remove_css_class("destructive-action")

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        self._spinner.set_visible(busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._action_button.set_sensitive(not busy)
        if label:
            self._action_button.set_label(label)

    def _on_action_clicked(self, _button: Gtk.Button) -> None:
        if self._busy:
            return
        if self._model_manager.is_installed(self._model_id):
            self._start_remove()
        else:
            self._start_download()

    def _start_download(self) -> None:
        self._set_busy(True, "Downloading...")
        thread = threading.Thread(target=self._download_thread, daemon=True)
        thread.start()

    def _download_thread(self) -> None:
        try:
            result = self._model_manager.download_model(self._model_id)
            if result is None:
                GLib.idle_add(self._on_download_error, "Download failed")
            else:
                GLib.idle_add(self._on_download_done)
        except Exception as e:
            GLib.idle_add(self._on_download_error, str(e))

    def _on_download_done(self) -> None:
        self._set_busy(False)
        self._update_ui(True)
        self._window.show_toast("Model downloaded successfully")

    def _on_download_error(self, error_msg: str) -> None:
        self._set_busy(False)
        self._update_ui(False)
        self._window.show_toast(f"Download failed: {error_msg}")

    def _start_remove(self) -> None:
        self._set_busy(True, "Removing...")
        thread = threading.Thread(target=self._remove_thread, daemon=True)
        thread.start()

    def _remove_thread(self) -> None:
        try:
            self._model_manager.remove_model(self._model_id)
            GLib.idle_add(self._on_remove_done)
        except Exception as e:
            GLib.idle_add(self._on_remove_error, str(e))

    def _on_remove_done(self) -> None:
        self._set_busy(False)
        self._update_ui(False)
        self._window.show_toast("Model removed")

    def _on_remove_error(self, error_msg: str) -> None:
        self._set_busy(False)
        self._update_ui(True)
        self._window.show_toast(f"Remove failed: {error_msg}")


class ShortcutRow(Adw.ActionRow):
    """A row that captures a keyboard shortcut when activated.

    Displays the current PTT hotkey and lets the user press a new key
    combination to change it.
    """

    # Map Gdk modifier bits to GTK accelerator tokens
    _GDK_MOD_TO_ACCEL = [
        (Gdk.ModifierType.CONTROL_MASK, "<Ctrl>"),
        (Gdk.ModifierType.ALT_MASK, "<Alt>"),
        (Gdk.ModifierType.SHIFT_MASK, "<Shift>"),
        (Gdk.ModifierType.SUPER_MASK, "<Super>"),
    ]

    def __init__(self, settings: Gio.Settings, window: "PreferencesWindow"):
        super().__init__(title="Push-to-Talk Hotkey")
        self._settings = settings
        self._window = window
        self._capturing = False

        # Label showing current shortcut
        self._shortcut_label = Gtk.ShortcutLabel(
            accelerator=settings.get_string("ptt-hotkey") or "<Alt>space",
            valign=Gtk.Align.CENTER,
        )
        self.add_suffix(self._shortcut_label)

        # Change button
        self._change_button = Gtk.Button(label="Change", valign=Gtk.Align.CENTER)
        self._change_button.connect("clicked", self._on_change_clicked)
        self.add_suffix(self._change_button)

        # Key event controller (added to the window during capture)
        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._key_controller.connect("key-pressed", self._on_key_pressed)

    def _on_change_clicked(self, _button: Gtk.Button) -> None:
        if self._capturing:
            self._stop_capture()
            return
        self._start_capture()

    def _start_capture(self) -> None:
        self._capturing = True
        self._change_button.set_label("Cancel")
        self._shortcut_label.set_accelerator("")
        self.set_subtitle("Press a key combination...")
        # Attach key controller to the toplevel window to capture all keys
        toplevel = self.get_root()
        if toplevel:
            toplevel.add_controller(self._key_controller)

    def _stop_capture(self) -> None:
        self._capturing = False
        self._change_button.set_label("Change")
        self.set_subtitle("")
        toplevel = self.get_root()
        if toplevel:
            toplevel.remove_controller(self._key_controller)

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if not self._capturing:
            return False

        # Ignore lone modifier presses (wait for the actual key)
        if keyval in (
            Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
            Gdk.KEY_Control_L, Gdk.KEY_Control_R,
            Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
            Gdk.KEY_Super_L, Gdk.KEY_Super_R,
            Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
            Gdk.KEY_ISO_Level3_Shift,
        ):
            return True  # consume but keep waiting

        # Require at least one modifier to avoid hijacking normal typing
        has_modifier = any(state & mask for mask, _ in self._GDK_MOD_TO_ACCEL)
        if not has_modifier:
            self._window.show_toast(
                "Hotkey requires at least one modifier (Ctrl, Alt, Shift, or Super)"
            )
            self._stop_capture()
            return True

        # Build accelerator string from modifiers + key
        accel = self._build_accelerator(keyval, state)
        if accel:
            self._shortcut_label.set_accelerator(accel)
            self._settings.set_string("ptt-hotkey", accel)
            LOG.info("PTT hotkey changed to: %s", accel)
            self._window.show_toast(f"Hotkey set to {accel} — restart IBus to apply")

        self._stop_capture()
        return True  # consume the key event

    @classmethod
    def _build_accelerator(cls, keyval: int, state: Gdk.ModifierType) -> str:
        """Convert a keyval + GDK modifier state to a GTK accelerator string."""
        parts: list[str] = []
        for mask, token in cls._GDK_MOD_TO_ACCEL:
            if state & mask:
                parts.append(token)

        key_name = Gdk.keyval_name(keyval)
        if not key_name:
            return ""

        parts.append(key_name)
        return "".join(parts)


class PreferencesWindow(Adw.PreferencesWindow):
    """Main preferences window for speak2type."""

    def __init__(self, **kwargs: object):
        super().__init__(title="speak2type Settings", **kwargs)
        self._manager = BackendManager()
        self._backend_rows: dict[str, BackendRow] = {}
        self._model_group: Adw.PreferencesGroup | None = None
        self._model_page: Adw.PreferencesPage | None = None

        self._settings = None
        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source and schema_source.lookup("org.freedesktop.ibus.engine.stt", True):
            self._settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")

        self._build_backends_page()
        self._build_models_page()
        self._build_general_page()

    def _build_backends_page(self) -> None:
        page = Adw.PreferencesPage(title="Backends", icon_name="application-x-addon-symbolic")
        self.add(page)

        # Active backend selector
        if self._settings:
            selector_group = Adw.PreferencesGroup(title="Active Backend")
            page.add(selector_group)

            self._backend_combo = Adw.ComboRow(title="Use for transcription")
            # Build string list from installed backends
            self._backend_string_list = Gtk.StringList()
            self._backend_combo_ids: list[str] = []
            self._refresh_backend_combo()
            self._backend_combo.set_model(self._backend_string_list)
            self._backend_combo.connect("notify::selected", self._on_backend_selected)
            selector_group.add(self._backend_combo)

        # Available backends
        group = Adw.PreferencesGroup(
            title="Available Backends",
            description="Install or remove speech recognition backends.",
        )
        page.add(group)

        for backend_id in BACKEND_SPECS:
            row = BackendRow(backend_id, self._manager, self)
            self._backend_rows[backend_id] = row
            group.add(row)

    def _refresh_backend_combo(self) -> None:
        """Rebuild the combo box items based on currently installed backends."""
        if not self._settings:
            return

        # Clear existing items
        while self._backend_string_list.get_n_items() > 0:
            self._backend_string_list.remove(0)
        self._backend_combo_ids.clear()

        current = self._settings.get_string("backend") if self._settings else "parakeet"
        selected_idx = 0

        for backend_id, spec in BACKEND_SPECS.items():
            if self._manager.is_deps_installed(backend_id):
                self._backend_string_list.append(spec.name)
                self._backend_combo_ids.append(backend_id)
                if backend_id == current:
                    selected_idx = len(self._backend_combo_ids) - 1

        if not self._backend_combo_ids:
            self._backend_string_list.append("(none installed)")
            self._backend_combo_ids.append("")

        self._backend_combo.set_selected(selected_idx)

    def _on_backend_selected(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if idx < len(self._backend_combo_ids):
            backend_id = self._backend_combo_ids[idx]
            if backend_id and self._settings:
                self._settings.set_string("backend", backend_id)
                LOG.info("Active backend set to: %s", backend_id)

    def _build_models_page(self) -> None:
        self._model_page = Adw.PreferencesPage(
            title="Models", icon_name="folder-download-symbolic"
        )
        self.add(self._model_page)

        self._model_group = Adw.PreferencesGroup(
            title="Speech Recognition Models",
            description="Download or remove models for the active backend.",
        )
        self._model_page.add(self._model_group)

        self._populate_models()

    def _populate_models(self) -> None:
        """Populate the models list for backends that have models."""
        if not self._model_group:
            return

        # Remove existing model rows
        child = self._model_group.get_first_child()
        rows_to_remove = []
        while child:
            if isinstance(child, ModelRow):
                rows_to_remove.append(child)
            child = child.get_next_sibling()
        for row in rows_to_remove:
            self._model_group.remove(row)

        # Add models for installed backends that have models
        found_any = False
        for backend_id, spec in BACKEND_SPECS.items():
            if not spec.has_models:
                continue
            if not self._manager.is_deps_installed(backend_id):
                continue

            model_manager = self._manager.get_model_manager(backend_id)
            if model_manager is None:
                continue

            for model_spec in model_manager.list_available_models():
                is_installed = model_manager.is_installed(model_spec.id)
                row = ModelRow(model_spec, is_installed, self._manager, model_manager, self)
                self._model_group.add(row)
                found_any = True

        if not found_any:
            self._model_group.set_description(
                "Install a backend first to see available models."
            )
        else:
            self._model_group.set_description(
                "Download or remove models for the active backend."
            )

    def refresh_model_page(self) -> None:
        """Refresh the models page and backend combo after an install/uninstall."""
        self._populate_models()
        self._refresh_backend_combo()

    def _build_general_page(self) -> None:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-other-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Input Settings")
        page.add(group)

        if self._settings:
            # Record mode
            mode_row = Adw.ComboRow(title="Record Mode")
            mode_list = Gtk.StringList.new(["Push to Talk", "Toggle"])
            mode_row.set_model(mode_list)
            current_mode = self._settings.get_string("record-mode")
            mode_row.set_selected(0 if current_mode == "push_to_talk" else 1)
            mode_row.connect("notify::selected", self._on_mode_selected)
            group.add(mode_row)

            # PTT hotkey
            shortcut_row = ShortcutRow(self._settings, self)
            group.add(shortcut_row)

            # Audio source
            audio_row = Adw.ComboRow(title="Audio Source")
            audio_list = Gtk.StringList.new(["Auto", "PipeWire", "PulseAudio"])
            audio_row.set_model(audio_list)
            current_source = self._settings.get_string("audio-source")
            source_map = {"auto": 0, "pipewire": 1, "pulseaudio": 2}
            audio_row.set_selected(source_map.get(current_source, 0))
            audio_row.connect("notify::selected", self._on_audio_selected)
            group.add(audio_row)

            # Log level
            log_row = Adw.ComboRow(
                title="Log Level",
                subtitle="Lower levels log more detail including transcribed text",
            )
            log_list = Gtk.StringList.new(["WARNING", "ERROR", "INFO", "DEBUG"])
            log_row.set_model(log_list)
            current_level = self._settings.get_string("log-level").upper()
            level_map = {"WARNING": 0, "ERROR": 1, "INFO": 2, "DEBUG": 3}
            log_row.set_selected(level_map.get(current_level, 0))
            log_row.connect("notify::selected", self._on_log_level_selected)
            group.add(log_row)
        else:
            no_schema_row = Adw.ActionRow(
                title="GSettings schema not installed",
                subtitle="Settings will use defaults. Reinstall the package to fix this.",
            )
            group.add(no_schema_row)

    def _on_mode_selected(self, combo: Adw.ComboRow, _pspec: object) -> None:
        if self._settings:
            modes = ["push_to_talk", "toggle"]
            self._settings.set_string("record-mode", modes[combo.get_selected()])

    def _on_audio_selected(self, combo: Adw.ComboRow, _pspec: object) -> None:
        if self._settings:
            sources = ["auto", "pipewire", "pulseaudio"]
            self._settings.set_string("audio-source", sources[combo.get_selected()])

    def _on_log_level_selected(self, combo: Adw.ComboRow, _pspec: object) -> None:
        if self._settings:
            levels = ["WARNING", "ERROR", "INFO", "DEBUG"]
            self._settings.set_string("log-level", levels[combo.get_selected()])
            self.show_toast("Log level changed — restart IBus engine to apply")

    def show_toast(self, message: str) -> None:
        """Show a toast notification."""
        toast = Adw.Toast(title=message, timeout=5)
        self.add_toast(toast)


class PreferencesApp(Adw.Application):
    """Standalone application wrapper for the preferences window."""

    def __init__(self) -> None:
        super().__init__(
            application_id="org.freedesktop.ibus.engine.stt.preferences",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )

    def do_activate(self) -> None:
        # Reuse existing window if re-activated
        win = self.get_active_window()
        if not win:
            win = PreferencesWindow(application=self)
        # present() requests focus from the compositor;
        # set_urgency_hint via the Gtk layer may help on Wayland
        win.set_visible(True)
        win.present()


def main() -> int:
    """Entry point for the preferences UI."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = PreferencesApp()
    return app.run()


if __name__ == "__main__":
    import sys

    sys.exit(main())
