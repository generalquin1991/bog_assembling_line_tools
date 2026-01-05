# ESP Auto Flashing Tool

A tool for automatically flashing firmware to ESP32/ESP8266/ESP32-C2 devices, supporting both development and production modes.

## Features

- ✅ Supports ESP32, ESP8266, ESP32-C2 chips
- ✅ **Interactive TUI**: Select each step via keyboard
- ✅ Auto-detect serial ports
- ✅ Support development mode (unencrypted) and production mode (encrypted)
- ✅ Support firmware verification and Flash erasure
- ✅ Support complete firmware flashing (combined bin)
- ✅ Manage parameters via JSON configuration files

## Quick Start

### One-Click Launch (Recommended)

```bash
# 1. Load aliases (temporary, current terminal session only)
source setup_aliases.sh

# 2. One-click launch (auto-create virtual environment, install dependencies, and start TUI)
start_bog
```

### Permanent Alias Installation

```bash
# Install aliases to ~/.zshrc or ~/.bashrc
./install_aliases.sh

# Reload configuration
source ~/.zshrc  # or source ~/.bashrc
```

After installation, you can use anywhere:
- `start_bog` - One-click launch (auto-complete all setup)
- `flash_develop` - Development mode flashing (unencrypted)
- `flash_factory` - Production mode flashing (encrypted)
- `help_bog` - Show help information

## Environment Setup

### Using Virtual Environment (Recommended)

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Or use scripts:
```bash
# Linux/Mac
./setup_venv.sh
source venv/bin/activate
pip install -r requirements.txt

# Windows
setup_venv.bat
venv\Scripts\activate
pip install -r requirements.txt
```

⚠️ **Important Notes**: 
- Strongly recommend using virtual environment to avoid conflicts with system Python packages
- Only run `pip install` after activating the virtual environment (when you see `(venv)` in the prompt)

## Usage

### Interactive TUI (Recommended)

```bash
# Run directly (no arguments) will auto-start TUI
python flash_esp.py

# Or use alias
start_bog
```

The TUI interface will guide you through:
1. Select flashing mode (development/production)
2. Select serial port device
3. Select firmware file
4. Select other options (skip verification, no reset, erase Flash, etc.)
5. Confirm configuration and start flashing

### Command Line Mode

```bash
# Development mode (unencrypted)
python flash_esp.py --mode develop
# Or use alias
flash_develop

# Production mode (encrypted)
python flash_esp.py --mode factory
# Or use alias
flash_factory

# List available serial ports
python flash_esp.py --list

# Specify serial port
python flash_esp.py --mode develop -p /dev/ttyUSB0

# Specify firmware file
python flash_esp.py -f firmware/my_firmware.bin

# Skip verification
python flash_esp.py --no-verify

# Don't reset after flashing
python flash_esp.py --no-reset
```

## Mode Description

### DEVELOP Mode (Development Mode)
- **Purpose**: Development and debugging
- **Encryption**: Unencrypted, easy to debug and read
- **Config File**: `config_develop.json`
- **Features**: Suitable for development phase, supports repeated flashing

### FACTORY Mode (Production Mode)
- **Purpose**: Mass production and official release
- **Encryption**: Supports encryption, more secure
- **Config File**: `config_factory.json`
- **Features**: Suitable for production environment, protects firmware from being read

## Configuration Files

Configuration files contain the following main items:

- `serial_port`: Serial port device path (e.g., `/dev/ttyUSB0` or `COM3`)
- `baud_rate`: Baud rate (default: 921600)
- `chip_type`: Chip type (`esp32`, `esp8266`, `esp32c2`)
- `firmware_path`: Firmware file path
- `flash_mode`: Flash mode (`dio`, `qio`, `dout`, `qout`)
- `flash_freq`: Flash frequency (`80m`, `60m`, `40m`)
- `flash_size`: Flash size (`2MB`, `4MB`, `8MB`, etc.)
- `erase_flash`: Whether to erase entire Flash (`true`/`false`)
- `verify`: Whether to verify flashing result (`true`/`false`)
- `encrypt`: Whether to enable encryption (`true`/`false`)
- `secure_boot`: Whether to enable secure boot (`true`/`false`)

## Directory Structure

```
.
├── firmware/              # Firmware folder, place .bin firmware files
├── venv/                  # Virtual environment (when using virtual environment)
├── config.json            # Default configuration file
├── config_develop.json    # Development mode config (unencrypted)
├── config_factory.json    # Production mode config (encrypted)
├── flash_esp.py           # Main program
├── requirements.txt       # Python dependencies
├── setup_venv.sh          # Virtual environment setup script (Linux/Mac)
├── setup_venv.bat         # Virtual environment setup script (Windows)
├── setup_aliases.sh       # Alias setup script
├── install_aliases.sh     # Permanent alias installation script
└── README.md              # Documentation
```

## Troubleshooting

### Serial Port Permission Issues (Linux/Mac)

```bash
sudo chmod 666 /dev/ttyUSB0
```

Or add user to dialout group:
```bash
sudo usermod -a -G dialout $USER
```

### Device Not Found

- Check USB connection
- Check if drivers are installed
- Use `--list` parameter to view available devices

### Flashing Failed

- Lower baud rate (modify `baud_rate` in config file)
- Check if firmware file is correct
- Ensure device enters download mode (some devices require holding BOOT button)

## ESP Flash Download Tool (Official Tool)

### Overview

The official ESP Flash Download Tool is suitable for mass production environments, supporting Flash encryption and secure boot.

### Comparison with esptool

| Feature | ESP Flash Download Tool | esptool (This Tool) |
|---------|-------------------------|---------------------|
| Use Case | Mass production | Development/Debugging |
| Flash Encryption | Supported (auto-encrypt on first boot) | Manual configuration required |
| Secure Boot | Supported | Manual configuration required |
| Repeatable Flashing | ❌ Not supported (cannot re-flash after encryption) | ✅ Supported |
| Interface | GUI | Command line/TUI |
| Multi-device Flashing | ✅ Supported | ❌ Single device |

### Usage Recommendations

- **Mass Production**: Use ESP Flash Download Tool to ensure Flash encryption and secure boot
- **Development/Debugging**: Use this tool (esptool), supports repeated flashing and debugging

### Official Tool Usage Flow

1. **Download Tool**
   - Download URL: https://docs.espressif.com/projects/esp-test-tools/en/latest/esp32/production_stage/tools/flash_download_tool.html

2. **Configure Flashing Parameters**
   - Select chip type: **ESP-C2**
   - Select mode: **Factory Mode**
   - Uncheck "Lock Settings" to modify settings
   - Select firmware file, set start address: **0x00** (combined firmware)
   - Re-check "Lock Settings"

3. **Start Flashing**
   - Select correct COM port (UART COM port)
   - Click **Start** to begin flashing

4. **First Boot**
   - Device will automatically verify firmware signature and encrypt Flash on first boot
   - Factory configuration will start automatically after completion
   - ⚠️ **Important**: Device can only be flashed once, cannot re-flash after encryption

## Notes

1. Ensure ESP device is properly connected to computer
2. Some devices require holding BOOT button to enter download mode
3. If flashing fails, try lowering baud rate (e.g., 115200)
4. Ensure sufficient permissions to access serial port device (Linux/Mac may require sudo)
