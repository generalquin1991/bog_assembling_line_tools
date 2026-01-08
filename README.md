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
- ✅ **Bin File Merger Tool**: Merge bootloader, partition table, and app bin files into a single combined firmware

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
- **Features**: Suitable for development phase, supports repeated flashing, supports detailed post-flash self-test (RTC, pressure sensor, button, HW revision, serial number, MAC logging, etc.)

### FACTORY Mode (Production Mode)
- **Purpose**: Mass production and official release
- **Encryption**: Supports encryption, more secure
- **Config File**: `config_factory.json`
- **Features**: Suitable for production environment, protects firmware from being read, and can share a similar automated self-test workflow (RTC, pressure, button) depending on config

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
- `monitor_baud`: Baud rate used for log monitoring during self-test
- `test_after_flash`: Whether to automatically run the self-test flow after flashing
- `device_code_rule`: Rule to generate serial number / device code when not manually entered (e.g., `SN: YYMMDD+序号`)

### Self-Test Workflow (After Flashing)

When `test_after_flash` is enabled, the tool can automatically perform a post-flash self-test based on the configuration (mainly `config_develop.json` / `config.json`):

1. **Read MAC address via esptool**
   - Use esptool to query the ESP chip info and extract the MAC address.
   - The MAC is stored in the current session and later written to the local database.

2. **Reset device with esptool and start log monitoring**
   - Use esptool to perform a reset (e.g., `--after hard_reset`).
   - Immediately start a serial monitor at `monitor_baud`, treating the reset completion time as `t0`.
   - Confirm reset success by detecting log patterns like `rst:0x1`, `POWERON`, `boot:0xe`, `SPI_FAST_FLASH_BOOT`.

3. **Detect Factory Configuration Mode (optional)**
   - Listen for `Factory Configuration Mode` or `factory_config:` within a short timeout (e.g., 2 seconds).
   - This indicates the device has entered the factory configuration flow.

4. **RTC self-test**
   - Listen for RTC-related log patterns (e.g., `Time passed`, `RTC Time now:`).
   - If received within the configured timeout (e.g., 10 seconds), RTC test is marked as **PASS**; otherwise **FAIL/TIMEOUT**.

5. **Pressure sensor self-test**
   - Listen for pressure-related log patterns (e.g., `Pressure Sensor Calibration Value Ok`, `Pressure Sensor Reading:`).
   - If received within timeout, mark pressure sensor test as **PASS** and extract the measured value from the log.
   - The measured pressure is stored and later written to the local database.

6. **Button test (10s timeout)**
   - When the log first shows `Press button to continue` / `button to continue`, the TUI prompts the operator to press the physical button.
   - From the moment this prompt is detected, a 10-second timer starts.
   - If the logs show that the button has been pressed (e.g., prompt disappears and the firmware proceeds; or firmware prints a confirmation string) within the timeout, the button test is **PASS**; otherwise **FAIL/TIMEOUT**.

7. **Automatic HW revision input**
   - After the button test, the tool waits for hardware version prompts like `Enter Hardware Version:`, `Enter hardware version:`, `Hardware Version:`.
   - Once detected, the tool automatically sends the hardware version string:
     - Prefer value from the TUI (if the operator provided it), otherwise
     - Fall back to `version_string` from the configuration (`config_develop.json` / `config.json`).
   - The value sent is displayed in the terminal so the operator can verify it.

8. **Automatic serial number input**
   - Next, the tool waits for prompts like `Enter Serial Number:`, `Enter serial number:`, `Serial Number:`, `Enter Device Code:`, `Enter device code:`.
   - If `device_code_rule` is configured (for example, `SN: YYMMDD+序号`), the tool can:
     - Look up existing records in the local database for today,
     - Generate the next serial number according to the rule,
     - Automatically send it to the device.
   - If no rule is configured, the TUI prompts the operator to input/scan the serial number, and then sends it to the device.
   - The final SN/device code is also shown in the terminal for confirmation.

9. **Aggregate test results**
   - Throughout the process, the serial monitor keeps tracking:
     - RTC test status,
     - Pressure test status and measured value,
     - Button test status,
     - Success/failure of HW version and SN auto input.
   - Before finishing, the tool aggregates all these results into a single test summary (PASS/FAIL with reasons).

10. **Write key information to local database**
   - At the end of the self-test, the tool writes a structured record to a local database (e.g., SQLite or CSV in the `logs/` directory), including:
     - Timestamps (start/end),
     - Serial port, chip type, mode (develop/factory),
     - MAC address,
     - HW revision,
     - Serial number / device code,
     - RTC / pressure / button test results,
     - Pressure measurement value,
     - Path to the raw log file.

## Directory Structure

```
.
├── firmware/              # Firmware folder, place .bin firmware files
├── venv/                  # Virtual environment (when using virtual environment)
├── config.json            # Default configuration file
├── config_develop.json    # Development mode config (unencrypted)
├── config_factory.json    # Production mode config (encrypted)
├── flash_esp.py           # Main flashing program
├── merge_esp_bin.py       # Bin file merger tool
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

## Bin File Merger Tool

The `merge_esp_bin.py` tool allows you to merge multiple ESP bin files (bootloader, partition table, app) into a single combined firmware file.

### Interactive TUI Mode (Recommended)

```bash
python merge_esp_bin.py
```

The TUI will guide you through:
1. Select ESP chip type (ESP32, ESP32-C3, ESP8266)
2. Select directory containing bin files
3. Select bin files to merge
4. Specify flash addresses for each file
5. Select output file path
6. Confirm and merge

### Command Line Mode

```bash
# Basic usage - merge bootloader, partition table, and app
python merge_esp_bin.py \
    --chip ESP32 \
    --bootloader bootloader.bin \
    --partition partition-table.bin \
    --app app.bin \
    --output merged_firmware.bin

# With custom addresses
python merge_esp_bin.py \
    --chip ESP32 \
    --bootloader bootloader.bin --bootloader-addr 0x1000 \
    --partition partition-table.bin --partition-addr 0x8000 \
    --app app.bin --app-addr 0x10000 \
    --output merged_firmware.bin

# ESP8266 (no partition table)
python merge_esp_bin.py \
    --chip ESP8266 \
    --bootloader bootloader.bin \
    --app app.bin \
    --output merged_firmware.bin
```

### Default Flash Addresses

**ESP32:**
- Bootloader: `0x1000`
- Partition Table: `0x8000`
- App: `0x10000`

**ESP32-C3:**
- Bootloader: `0x0`
- Partition Table: `0x8000`
- App: `0x10000`

**ESP8266:**
- Bootloader: `0x0`
- App: `0x10000`

## ESP Flash Download Tool Comparison

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
