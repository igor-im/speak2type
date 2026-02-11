#!/bin/bash
# speak2type development installation script
#
# This script sets up speak2type for development on Ubuntu 25.10+
# It installs system dependencies and configures IBus to load the engine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_PREFIX="${HOME}/.local"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_ubuntu() {
    if ! command -v lsb_release &> /dev/null; then
        log_warn "Cannot detect distribution (lsb_release not found)"
        return
    fi

    local distro=$(lsb_release -is)
    local version=$(lsb_release -rs)

    log_info "Detected: $distro $version"

    if [[ "$distro" != "Ubuntu" ]]; then
        log_warn "This script is designed for Ubuntu. Some commands may need adjustment."
    fi
}

install_system_deps() {
    log_info "Installing system dependencies..."

    # Core dependencies
    sudo apt-get update
    sudo apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-gi \
        python3-gi-cairo \
        gir1.2-ibus-1.0 \
        gir1.2-gtk-4.0 \
        gir1.2-adw-1 \
        gir1.2-gstreamer-1.0 \
        gir1.2-gst-plugins-base-1.0 \
        ibus \
        libibus-1.0-dev \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-pipewire \
        gstreamer1.0-pulseaudio \
        gstreamer1.0-tools

    log_info "System dependencies installed"
}

install_optional_deps() {
    log_info "Installing optional dependencies..."

    # webrtcdsp for noise suppression (optional)
    if apt-cache show gstreamer1.0-plugins-bad &> /dev/null; then
        sudo apt-get install -y gstreamer1.0-plugins-bad
        log_info "Installed GStreamer bad plugins (includes webrtcdsp)"
    else
        log_warn "gstreamer1.0-plugins-bad not available"
    fi
}

install_gst_vosk() {
    log_info "Checking for gst-vosk..."

    # Check if gst-vosk is available as a package
    if apt-cache show gstreamer1.0-vosk &> /dev/null; then
        sudo apt-get install -y gstreamer1.0-vosk
        log_info "Installed gst-vosk from package"
    else
        log_warn "gst-vosk not available as package"
        log_warn "Vosk backend will not work without gst-vosk"
        log_warn "See: https://github.com/PhilippeRo/gst-vosk"
    fi
}

setup_python_env() {
    log_info "Setting up Python environment..."

    cd "$PROJECT_DIR"

    # Create virtual environment if it doesn't exist
    if [[ ! -d ".venv" ]]; then
        python3 -m venv .venv --system-site-packages
        log_info "Created virtual environment"
    fi

    # Activate and install
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -e ".[dev,all]"

    log_info "Python environment ready"
}

install_ibus_component() {
    log_info "Installing IBus component..."

    local component_dir="${INSTALL_PREFIX}/share/ibus/component"
    local libexec_dir="${INSTALL_PREFIX}/libexec"

    mkdir -p "$component_dir"
    mkdir -p "$libexec_dir"

    # Create the component XML from template
    local component_xml="${component_dir}/speak2type.xml"

    cat > "$component_xml" << EOF
<?xml version="1.0" encoding="utf-8"?>
<component>
    <name>org.freedesktop.IBus.speak2type</name>
    <description>Speech To Text Engine</description>
    <exec>${PROJECT_DIR}/scripts/ibus-engine-speak2type --ibus</exec>
    <version>0.1.0</version>
    <author>speak2type contributors</author>
    <license>GPL-3.0</license>
    <homepage>https://github.com/speak2type/speak2type</homepage>
    <textdomain>speak2type</textdomain>
    <engines>
        <engine>
            <name>speak2type</name>
            <language>en</language>
            <license>GPL-3.0</license>
            <author>speak2type contributors</author>
            <icon>audio-input-microphone</icon>
            <layout>us</layout>
            <longname>Speech To Text</longname>
            <description>Speech To Text input method</description>
            <rank>0</rank>
            <setup>${libexec_dir}/ibus-setup-speak2type</setup>
        </engine>
    </engines>
</component>
EOF

    log_info "Created IBus component: $component_xml"

    # Create the engine launcher script
    local engine_script="${PROJECT_DIR}/scripts/ibus-engine-speak2type"

    cat > "$engine_script" << EOF
#!/bin/bash
# speak2type IBus engine launcher
cd "${PROJECT_DIR}"
source .venv/bin/activate
exec python -m speak2type.engine "\$@"
EOF

    chmod +x "$engine_script"
    log_info "Created engine script: $engine_script"

    # Create the setup launcher script
    local setup_script="${libexec_dir}/ibus-setup-speak2type"

    cat > "$setup_script" << EOF
#!/bin/bash
# speak2type setup launcher
cd "${PROJECT_DIR}"
source .venv/bin/activate
exec python -m speak2type.preferences "\$@"
EOF

    chmod +x "$setup_script"
    log_info "Created setup script: $setup_script"
}

install_gsettings_schema() {
    log_info "Installing GSettings schema..."

    local schema_dir="${INSTALL_PREFIX}/share/glib-2.0/schemas"
    mkdir -p "$schema_dir"

    # Copy the schema file (remove .in suffix and process template)
    local schema_src="${PROJECT_DIR}/data/org.freedesktop.ibus.engine.stt.gschema.xml.in"
    local schema_dst="${schema_dir}/org.freedesktop.ibus.engine.speak2type.gschema.xml"

    # For now, just copy (template processing would be done by meson normally)
    cp "$schema_src" "$schema_dst"

    # Compile schemas
    glib-compile-schemas "$schema_dir"

    log_info "GSettings schema installed"
}

setup_ibus_env() {
    log_info "Setting up IBus environment..."

    local component_dir="${INSTALL_PREFIX}/share/ibus/component"

    # Check if IBUS_COMPONENT_PATH is already set
    if [[ -z "${IBUS_COMPONENT_PATH:-}" ]]; then
        log_info "Add the following to your shell profile (~/.bashrc or ~/.zshrc):"
        echo ""
        echo "  export IBUS_COMPONENT_PATH=\"${component_dir}:\${IBUS_COMPONENT_PATH:-/usr/share/ibus/component}\""
        echo ""
    else
        log_info "IBUS_COMPONENT_PATH already set: $IBUS_COMPONENT_PATH"
    fi
}

restart_ibus() {
    log_info "Restarting IBus daemon..."

    if pgrep -x "ibus-daemon" > /dev/null; then
        ibus restart
        log_info "IBus restarted"
    else
        log_warn "IBus daemon not running. Start it with: ibus-daemon -drxR"
    fi
}

print_usage() {
    echo "speak2type development installation script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --deps-only     Install system dependencies only"
    echo "  --python-only   Setup Python environment only"
    echo "  --ibus-only     Install IBus component only"
    echo "  --no-restart    Don't restart IBus after installation"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0              Full installation"
    echo "  $0 --deps-only  Install system dependencies only"
}

main() {
    local deps_only=false
    local python_only=false
    local ibus_only=false
    local no_restart=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --deps-only)
                deps_only=true
                shift
                ;;
            --python-only)
                python_only=true
                shift
                ;;
            --ibus-only)
                ibus_only=true
                shift
                ;;
            --no-restart)
                no_restart=true
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done

    log_info "speak2type development installation"
    log_info "Project directory: $PROJECT_DIR"
    echo ""

    check_ubuntu

    if $deps_only; then
        install_system_deps
        install_optional_deps
        install_gst_vosk
        exit 0
    fi

    if $python_only; then
        setup_python_env
        exit 0
    fi

    if $ibus_only; then
        install_ibus_component
        install_gsettings_schema
        setup_ibus_env
        if ! $no_restart; then
            restart_ibus
        fi
        exit 0
    fi

    # Full installation
    install_system_deps
    install_optional_deps
    install_gst_vosk
    setup_python_env
    install_ibus_component
    install_gsettings_schema
    setup_ibus_env

    if ! $no_restart; then
        restart_ibus
    fi

    echo ""
    log_info "Installation complete!"
    log_info ""
    log_info "Next steps:"
    log_info "1. Add IBUS_COMPONENT_PATH to your shell profile (see above)"
    log_info "2. Log out and log back in (or run: source ~/.bashrc)"
    log_info "3. Open GNOME Settings > Keyboard > Input Sources"
    log_info "4. Add 'Speech To Text' input source"
    log_info "5. Select the input source and start dictating!"
}

main "$@"
