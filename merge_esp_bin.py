#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP Bin File Merger Tool
Merge ESP32/ESP8266 bootloader, partition table, and app bin files into a single combined firmware
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

try:
    import inquirer
except ImportError:
    inquirer = None


# Default ESP32 flash addresses (in bytes)
ESP32_DEFAULT_ADDRESSES = {
    'bootloader': 0x1000,
    'partition-table': 0x8000,
    'app': 0x10000,
    # ota_data_initial.bin (OTA data partition) typical address
    'ota': 0xD000,
    'boot_app0': 0xE000,  # Optional, for OTA
}

# Default ESP8266 flash addresses
ESP8266_DEFAULT_ADDRESSES = {
    'bootloader': 0x0,
    'ota': 0xd000,
    'partition-table': 0x8000,
    'app': 0x10000,
}

# Default ESP32-C3 flash addresses
ESP32C3_DEFAULT_ADDRESSES = {
    'bootloader': 0x0,
    'partition-table': 0x10000,
    'ota': 0x15000,
    'app': 0x20000,
}

# Default ESP8684 flash addresses
# 说明：这里暂时复用 ESP32 的典型地址布局，如有特殊布局可再调整
SP8684_DEFAULT_ADDRESSES = {
    'bootloader': 0,
    'partition-table': 0x8000,
    'app': 0x10000,
    'ota': 0xD000,
}


def clear_screen():
    """Clear screen"""
    os.system('clear' if os.name != 'nt' else 'cls')


def print_header(title, width=80):
    """Print formatted header"""
    top_border = "╔" + "═" * (width - 2) + "╗"
    bottom_border = "╚" + "═" * (width - 2) + "╝"
    title_line = "║" + title.center(width - 2) + "║"
    
    print("\n" + top_border)
    print(title_line)
    print(bottom_border + "\n")


def print_centered(text, width=80):
    """Print centered text"""
    lines = text.split('\n')
    for line in lines:
        print(line.center(width))


def find_bin_files(directory):
    """Find all .bin files in the directory and subdirectories"""
    bin_files = []
    directory_path = Path(directory)
    
    if not directory_path.exists():
        return bin_files
    
    # Search in directory and subdirectories
    for bin_file in directory_path.rglob('*.bin'):
        bin_files.append(bin_file)
    
    return sorted(bin_files)


def get_file_size(file_path):
    """Get file size in bytes"""
    return os.path.getsize(file_path)


def format_size(size_bytes):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def merge_bin_files(bin_files_info, output_path, flash_size=0x400000, compact=False):
    """
    Merge multiple bin files into a single combined firmware
    
    Args:
        bin_files_info: List of tuples (file_path, address)
        output_path: Output file path
        flash_size: Total flash size (default 4MB)
        compact: If True, only output up to the end of the last file (no padding)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create a byte array for the entire flash
        flash_data = bytearray(flash_size)
        
        # Fill with 0xFF (erased flash state)
        for i in range(flash_size):
            flash_data[i] = 0xFF
        
        # Track the maximum address used
        max_address = 0
        
        # Write each bin file at its specified address
        for file_path, address in bin_files_info:
            if not os.path.exists(file_path):
                print(f"✗ Error: File not found: {file_path}")
                return False
            
            file_size = get_file_size(file_path)
            
            # Check if file fits in flash
            if address + file_size > flash_size:
                print(f"✗ Error: File {file_path} (size: {format_size(file_size)}) at address 0x{address:X} exceeds flash size")
                return False
            
            # Read and write file data
            with open(file_path, 'rb') as f:
                file_data = f.read()
                flash_data[address:address + file_size] = file_data
            
            # Update max_address
            max_address = max(max_address, address + file_size)
            
            print(f"  ✓ Merged {os.path.basename(file_path)} at 0x{address:X} ({format_size(file_size)})")
        
        # Write merged file
        with open(output_path, 'wb') as f:
            if compact:
                # Only write up to the end of the last file
                f.write(flash_data[:max_address])
                print(f"  (Compact mode: output size = {format_size(max_address)})")
            else:
                # Write full flash image
                f.write(flash_data)
        
        output_size = get_file_size(output_path)
        print(f"\n✓ Merged firmware saved: {output_path}")
        print(f"  Total size: {format_size(output_size)}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error merging files: {e}")
        import traceback
        traceback.print_exc()
        return False


def validate_and_resolve_directory(directory_str):
    """
    Validate and resolve directory path
    
    Returns:
        tuple: (success: bool, resolved_path: str, error_message: str)
    """
    if not directory_str or not directory_str.strip():
        return False, None, "Directory path cannot be empty"
    
    directory = directory_str.strip()
    
    # Expand user path and resolve
    try:
        directory = os.path.expanduser(directory)
        directory = os.path.abspath(directory)
    except Exception as e:
        return False, None, f"Invalid path format: {e}"
    
    # Validate directory
    if not os.path.exists(directory):
        # Try to suggest similar paths
        parent_dir = os.path.dirname(directory)
        suggestion = ""
        if os.path.exists(parent_dir):
            suggestion = f"\n  Hint: Parent directory exists: {parent_dir}"
        return False, directory, f"Directory does not exist: {directory}{suggestion}"
    
    if not os.path.isdir(directory):
        return False, directory, f"Not a directory: {directory}"
    
    return True, directory, None


def browse_directories(start_dir):
    """
    Simple TUI directory browser using inquirer.List
    Allows navigating into subdirectories / parent and finally choosing one.
    """
    current_dir = os.path.abspath(start_dir)
    while True:
        print(f"\nCurrent directory: {current_dir}")

        choices = []
        # Use this directory
        choices.append(("[Use this directory]", "__USE__"))

        # Go to parent
        parent_dir = os.path.dirname(current_dir)
        if parent_dir != current_dir:
            choices.append(("[Parent directory] ..", "__PARENT__"))

        # List subdirectories
        try:
            entries = sorted(os.listdir(current_dir))
        except OSError as e:
            print(f"✗ Cannot list directory: {e}")
            return current_dir

        for name in entries:
            full_path = os.path.join(current_dir, name)
            if os.path.isdir(full_path):
                choices.append((f"[Dir] {name}", full_path))

        # Extra actions
        choices.append(("[Enter path manually]", "__MANUAL__"))
        choices.append(("[Cancel]", "__CANCEL__"))

        question = [
            inquirer.List(
                "choice",
                message="Navigate to target directory",
                choices=choices,
            )
        ]

        answer = inquirer.prompt(question)
        if not answer:
            return None

        choice = answer.get("choice")
        if choice == "__USE__":
            return current_dir
        elif choice == "__PARENT__":
            current_dir = parent_dir
        elif choice == "__MANUAL__":
            # Let caller fall back to manual input
            return None
        elif choice == "__CANCEL__":
            return None
        else:
            # choice is a subdirectory path
            current_dir = choice


def _manual_directory_input(current_dir):
    """Manual text input mode for selecting directory"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        # Ask for directory path
        try:
            # 为了避免终端里显示很长的默认路径和被截断的 [def... 提示，这里不再给 inquirer 传默认值，
            # 而是手动把“空输入”解释为“使用当前目录”。
            if retry_count == 0:
                message = "Enter directory path (press Enter to use current directory)"
            else:
                message = "Enter directory path (or leave empty to use current directory)"

            question = [
                inquirer.Text(
                    'directory',
                    message=message,
                )
            ]
            
            answer = inquirer.prompt(question)
            if not answer:
                return None
            
            directory = answer.get('directory', '').strip()

            # 空输入表示使用当前目录
            if not directory:
                directory = current_dir
            
            # Validate directory
            success, resolved_path, error_msg = validate_and_resolve_directory(directory)
            
            if success:
                return resolved_path
            else:
                print(f"✗ {error_msg}")
                retry_count += 1
                if retry_count < max_retries:
                    print(f"  Attempt {retry_count + 1} of {max_retries}")
                    input("\nPress Enter to try again...")
                    continue
                else:
                    print("\nMaximum retry attempts reached.")
                    return None
                    
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user")
            return None
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            retry_count += 1
            if retry_count < max_retries:
                input("\nPress Enter to try again...")
                continue
            return None
    
    return None


def select_directory():
    """Select directory using TUI (supports browsing and manual input)"""
    if inquirer is None:
        print("Error: inquirer library not installed")
        print("Please run: pip install inquirer")
        return None
    
    current_dir = os.getcwd()

    # First choose input mode
    mode_question = [
        inquirer.List(
            "mode",
            message="How do you want to select the firmware directory?",
            choices=[
                ("Browse directories (recommended)", "browse"),
                ("Type path manually", "manual"),
                ("Use current directory", "current"),
                ("Cancel", "cancel"),
            ],
            default="browse",
        )
    ]

    mode_answer = inquirer.prompt(mode_question)
    if not mode_answer:
        return None

    mode = mode_answer.get("mode")
    if mode == "cancel":
        return None
    if mode == "current":
        return current_dir

    if mode == "browse":
        # Try directory browser first
        selected = browse_directories(current_dir)
        if selected:
            return selected
        # If user chose "enter manually" or cancelled, fall through to manual if needed
        # (selected == None means user probably hit cancel or chose manual)
        # Only go to manual if they didn't explicitly cancel via top-level menu

    # Manual mode
    return _manual_directory_input(current_dir)


def select_bin_files(bin_files, chip_type='ESP32'):
    """Select bin files and their addresses using TUI"""
    if inquirer is None:
        return None
    
    if not bin_files:
        print("✗ No .bin files found in the directory")
        return None
    
    # Get default addresses based on chip type
    if chip_type == 'ESP8266':
        default_addresses = ESP8266_DEFAULT_ADDRESSES
    elif chip_type == 'ESP32-C3':
        default_addresses = ESP32C3_DEFAULT_ADDRESSES
    elif chip_type == 'ESP8684':
        default_addresses = SP8684_DEFAULT_ADDRESSES
    else:
        default_addresses = ESP32_DEFAULT_ADDRESSES
    
    # Display found bin files
    print(f"\nFound {len(bin_files)} .bin file(s):")
    for idx, bin_file in enumerate(bin_files, 1):
        size = get_file_size(bin_file)
        print(f"  {idx}. {bin_file.name} ({format_size(size)})")
    
    # Select files to merge
    file_choices = [(f"{f.name} ({format_size(get_file_size(f))})", str(f)) for f in bin_files]
    
    checkbox_question = [
        inquirer.Checkbox('selected_files',
                         message="Select bin files to merge (space to select, Enter to confirm)",
                         choices=file_choices)
    ]
    
    answer = inquirer.prompt(checkbox_question)
    if not answer or not answer.get('selected_files'):
        print("✗ No files selected")
        return None
    
    selected_files = answer['selected_files']
    
    # For each selected file, ask for address
    bin_files_info = []
    
    for file_path in selected_files:
        file_name = os.path.basename(file_path)
        file_name_lower = file_name.lower()
        
        # Try to auto-detect file type and suggest address
        suggested_address = None
        if 'bootloader' in file_name_lower:
            suggested_address = default_addresses.get('bootloader', 0x1000)
        elif 'partition' in file_name_lower or 'ptable' in file_name_lower:
            suggested_address = default_addresses.get('partition-table', 0x8000)
        elif 'ota' in file_name_lower:
            # OTA data partition (e.g. ota_data_initial.bin)
            suggested_address = default_addresses.get('ota', 0xD000)
        elif 'app' in file_name_lower or 'application' in file_name_lower:
            suggested_address = default_addresses.get('app', 0x10000)
        elif 'boot_app0' in file_name_lower:
            suggested_address = default_addresses.get('boot_app0', 0xE000)
        else:
            suggested_address = 0x10000  # Default to app address
        
        # Ask for address
        address_question = [
            inquirer.Text('address',
                         message=f"Enter flash address (hex) for {file_name}",
                         default=f"0x{suggested_address:X}")
        ]
        
        addr_answer = inquirer.prompt(address_question)
        if not addr_answer:
            continue
        
        try:
            # Parse hex address
            addr_str = addr_answer['address'].strip()
            if addr_str.startswith('0x') or addr_str.startswith('0X'):
                address = int(addr_str, 16)
            else:
                address = int(addr_str, 16)  # Try hex anyway
        except ValueError:
            print(f"✗ Invalid address format: {addr_str}, skipping {file_name}")
            continue
        
        bin_files_info.append((file_path, address))
    
    return bin_files_info


def select_chip_type():
    """Select ESP chip type (now fixed to ESP8684 only)"""
    # Tool is currently specialized for ESP8684; keep API but always return ESP8684.
    # TUI simply skips selection step when inquirer is unavailable.
    return 'ESP8684'


def browse_directory_for_output_file(start_dir, default_filename=None):
    """
    Browse directory to select where to save the output file, then ask for filename
    """
    if default_filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_filename = f"merged_firmware_{timestamp}.bin"
    
    # First, browse to select directory
    selected_dir = browse_directories(start_dir)
    if not selected_dir:
        return None
    
    # Show selected directory in a separate line to avoid long path in prompt
    print(f"\nSelected directory: {selected_dir}\n")
    
    # Then ask for filename - use simple message without long path
    question = [
        inquirer.Text('filename',
                     message="Enter output filename",
                     default=default_filename)
    ]
    
    try:
        answer = inquirer.prompt(question)
        if not answer:
            return None
        
        filename = answer.get('filename', '').strip()
        if not filename:
            filename = default_filename
        
        # Ensure .bin extension
        if not filename.endswith('.bin'):
            filename += '.bin'
        
        output_path = os.path.join(selected_dir, filename)
        output_path = os.path.abspath(output_path)
        
        # Create directory if it doesn't exist (should already exist, but just in case)
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        return output_path
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return None
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return None


def select_output_path(default_name=None, start_dir=None):
    """Select output file path with option to browse directory"""
    if inquirer is None:
        return None
    
    if start_dir is None:
        start_dir = os.getcwd()
    
    if default_name is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"merged_firmware_{timestamp}.bin"
    
    # Ask user how they want to specify the output path
    method_question = [
        inquirer.List('method',
                     message="How do you want to specify the output file path?",
                     choices=[
                         ('Browse directory and enter filename', 'browse'),
                         ('Type full path manually', 'manual'),
                         ('Use default path', 'default'),
                         ('Cancel', 'cancel'),
                     ],
                     default='browse')
    ]
    
    method_answer = inquirer.prompt(method_question)
    if not method_answer:
        return None
    
    method = method_answer.get('method')
    
    if method == 'cancel':
        return None
    elif method == 'browse':
        return browse_directory_for_output_file(start_dir, os.path.basename(default_name))
    elif method == 'default':
        # Use default path in start_dir
        output_path = os.path.join(start_dir, os.path.basename(default_name))
        output_path = os.path.abspath(output_path)
        # Create directory if it doesn't exist
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        return output_path
    else:  # manual
        # Show default path separately to avoid long path in prompt
        print(f"\nDefault path: {default_name}\n")
        question = [
            inquirer.Text('output_path',
                         message="Enter output file path (or press Enter for default)",
                         default="")
        ]
        
        try:
            answer = inquirer.prompt(question)
            if not answer:
                return None
            
            output_path = answer.get('output_path', '').strip()
            
            # If empty, use default
            if not output_path:
                output_path = default_name
            else:
                output_path = os.path.expanduser(output_path)
                output_path = os.path.abspath(output_path)
            
            # Ensure .bin extension if not present
            if not output_path.endswith('.bin'):
                output_path += '.bin'
            
            # Create directory if it doesn't exist
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            return output_path
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user")
            return None
        except Exception as e:
            print(f"\n✗ Error: {e}")
            return None


def select_flash_size_for_esp8684(default_size=0x200000):
    """Interactively select flash size for ESP8684 in TUI mode.
    
    Only used in TUI; CLI already has --flash-size.
    """
    if inquirer is None:
        # Fallback to default if TUI dependency is missing
        return default_size
    
    options = [
        ('2MB (0x200000) [module default]', 0x200000),
        ('4MB (0x400000)', 0x400000),
        ('Custom...', 'custom'),
    ]
    
    question = [
        inquirer.List(
            'flash_size',
            message="Select flash size for ESP8684 (total flash capacity)",
            choices=options,
            default=default_size,
        )
    ]
    
    try:
        answer = inquirer.prompt(question)
        if not answer:
            return None
        
        value = answer.get('flash_size')
        if value != 'custom':
            return int(value)
        
        # Custom value: ask user to input hex or decimal
        print("\nYou can enter flash size in hex (e.g., 0x200000) or decimal (e.g., 2097152).")
        custom_q = [
            inquirer.Text(
                'custom_size',
                message="Enter flash size",
                default=f"0x{default_size:X}",
            )
        ]
        custom_answer = inquirer.prompt(custom_q)
        if not custom_answer:
            return None
        
        raw = custom_answer.get('custom_size', '').strip()
        if not raw:
            return None
        
        try:
            size = int(raw, 0)  # auto-detect base
            if size <= 0:
                print("\n✗ Flash size must be positive.")
                return None
            return size
        except ValueError:
            print("\n✗ Invalid flash size format.")
            return None
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return None
    except Exception as e:
        print(f"\n✗ Error while selecting flash size: {e}")
        return None


def run_tui():
    """Run TUI interface"""
    if inquirer is None:
        print("Error: inquirer library not installed")
        print("Please run: pip install inquirer")
        return
    
    while True:
        try:
            clear_screen()
            print_header("ESP Bin File Merger", 80)
            
            # Step 1: Select chip type
            print_centered("Step 1: Select Chip Type", 80)
            chip_type = select_chip_type()
            if not chip_type:
                break
            
            # Step 2: Select directory
            clear_screen()
            print_header("ESP Bin File Merger", 80)
            print_centered("Step 2: Select Directory", 80)
            print(f"\nCurrent directory: {os.getcwd()}\n")
            directory = select_directory()
            if not directory:
                print("\nDirectory selection cancelled or failed.")
                continue_question = [
                    inquirer.Confirm('retry',
                                   message="Would you like to try again?",
                                   default=True)
                ]
                retry_answer = inquirer.prompt(continue_question)
                if not retry_answer or not retry_answer.get('retry', False):
                    break
                continue
            
            # Step 3: Find bin files
            clear_screen()
            print_header("ESP Bin File Merger", 80)
            print_centered("Step 3: Select Bin Files", 80)
            print(f"Searching in: {directory}\n")
            
            bin_files = find_bin_files(directory)
            if not bin_files:
                print("✗ No .bin files found in the directory")
                input("\nPress Enter to continue...")
                continue
            
            # Step 4: Select files and addresses
            bin_files_info = select_bin_files(bin_files, chip_type)
            if not bin_files_info:
                break
            
            # Step 5: Select output path
            clear_screen()
            print_header("ESP Bin File Merger", 80)
            print_centered("Step 4: Select Output Path", 80)
            
            # Generate default output name
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            default_output = os.path.join(directory, f"merged_firmware_{chip_type}_{timestamp}.bin")
            
            output_path = select_output_path(default_output, start_dir=directory)
            if not output_path:
                break
            
            # Determine flash size
            # Default behavior (non-ESP8684) keeps original fixed sizes
            flash_size = 0x400000  # 4MB default for ESP32 / ESP32-C3
            if chip_type == 'ESP8266':
                flash_size = 0x100000  # 1MB for ESP8266
            elif chip_type == 'ESP8684':
                # For ESP8684, allow user to choose flash size interactively
                clear_screen()
                print_header("ESP Bin File Merger", 80)
                print_centered("Step 5: Select Flash Size", 80)
                
                selected_size = select_flash_size_for_esp8684(default_size=0x200000)
                if selected_size is None:
                    break
                flash_size = selected_size
            
            # Confirm and merge (step number depends on whether we had a flash-size step)
            clear_screen()
            print_header("ESP Bin File Merger", 80)
            if chip_type == 'ESP8684':
                print_centered("Step 6: Confirm and Merge", 80)
            else:
                print_centered("Step 5: Confirm and Merge", 80)
            
            print("\nConfiguration Summary:")
            print(f"  Chip Type: {chip_type}")
            print(f"  Source Directory: {directory}")
            print(f"  Output File: {output_path}")
            print(f"  Flash Size: 0x{flash_size:X} ({format_size(flash_size)})")
            print(f"\nFiles to merge:")
            for file_path, address in bin_files_info:
                size = get_file_size(file_path)
                print(f"  - {os.path.basename(file_path)} at 0x{address:X} ({format_size(size)})")
            
            confirm_question = [
                inquirer.Confirm('confirm',
                               message="\nConfirm to merge files?",
                               default=True)
            ]
            
            confirm_answer = inquirer.prompt(confirm_question)
            if not confirm_answer or not confirm_answer.get('confirm', False):
                print("\nMerge cancelled")
                break
            
            # Merge files
            print("\nMerging files...")
            # Use compact mode for ESP8684 to match flash_download_tool CombineBin behavior
            # flash_download_tool generates compact files (only actual data, not full flash image)
            compact_mode = (chip_type == 'ESP8684')
            
            success = merge_bin_files(bin_files_info, output_path, flash_size, compact=compact_mode)
            
            if success:
                print("\n" + "=" * 80)
                print("✓ Merge completed successfully!")
                print("=" * 80)
            else:
                print("\n" + "=" * 80)
                print("✗ Merge failed!")
                print("=" * 80)
            
            # Ask if continue
            continue_question = [
                inquirer.Confirm('continue',
                               message="Continue merging another set of files?",
                               default=False)
            ]
            
            continue_answer = inquirer.prompt(continue_question)
            if not continue_answer or not continue_answer.get('continue', False):
                break
                
        except KeyboardInterrupt:
            print("\n\nUser interrupted operation")
            break
        except Exception as e:
            print(f"\nError occurred: {e}")
            import traceback
            traceback.print_exc()
            input("\nPress Enter to continue...")
            break


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='ESP Bin File Merger Tool')
    parser.add_argument('-d', '--directory', help='Directory containing bin files')
    parser.add_argument('-o', '--output', help='Output file path')
    parser.add_argument('-c', '--chip', choices=['ESP8684'],
                       default='ESP8684', help='ESP chip type (currently only ESP8684 is supported)')
    parser.add_argument('--bootloader', help='Bootloader bin file path')
    parser.add_argument('--bootloader-addr', type=lambda x: int(x, 16),
                       help='Bootloader address (hex)')
    parser.add_argument('--partition', help='Partition table bin file path')
    parser.add_argument('--partition-addr', type=lambda x: int(x, 16),
                       help='Partition table address (hex)')
    parser.add_argument('--app', help='Application bin file path')
    parser.add_argument('--app-addr', type=lambda x: int(x, 16),
                       help='Application address (hex)')
    parser.add_argument('--flash-size', type=lambda x: int(x, 16),
                       default=0x400000, help='Flash size (hex, default: 0x400000 for 4MB)')
    parser.add_argument('--compact', action='store_true',
                       help='Compact mode: only output up to the end of the last file (no padding)')
    
    args = parser.parse_args()
    
    # If no arguments, run TUI
    if len(sys.argv) == 1:
        run_tui()
        return
    
    # Command line mode
    bin_files_info = []
    
    # Get default addresses
    if args.chip == 'ESP8266':
        default_addresses = ESP8266_DEFAULT_ADDRESSES
    elif args.chip == 'ESP32-C3':
        default_addresses = ESP32C3_DEFAULT_ADDRESSES
    elif args.chip == 'ESP8684':
        default_addresses = SP8684_DEFAULT_ADDRESSES
    else:
        default_addresses = ESP32_DEFAULT_ADDRESSES
    
    # Add bootloader
    if args.bootloader:
        addr = args.bootloader_addr if args.bootloader_addr else default_addresses.get('bootloader', 0x1000)
        bin_files_info.append((args.bootloader, addr))
    
    # Add partition table
    if args.partition:
        addr = args.partition_addr if args.partition_addr else default_addresses.get('partition-table', 0x8000)
        bin_files_info.append((args.partition, addr))
    
    # Add app
    if args.app:
        addr = args.app_addr if args.app_addr else default_addresses.get('app', 0x10000)
        bin_files_info.append((args.app, addr))
    
    if not bin_files_info:
        print("Error: No files specified. Use --bootloader, --partition, or --app")
        parser.print_help()
        return
    
    # Determine output path
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"merged_firmware_{args.chip}_{timestamp}.bin"
    
    # Auto-adjust flash_size for ESP8684 if not explicitly set
    flash_size = args.flash_size
    if args.chip == 'ESP8684' and args.flash_size == 0x400000:  # Only if using default
        flash_size = 0x200000  # 2MB for ESP8684-WROOM-02C-H2X
    
    # Use compact mode for ESP8684 to match flash_download_tool CombineBin behavior
    # flash_download_tool generates compact files (only actual data, not full flash image)
    compact_mode = args.compact
    if args.chip == 'ESP8684' and not args.compact:
        compact_mode = True  # Default to compact mode for ESP8684
    
    # Merge files
    print(f"Merging files for {args.chip}...")
    success = merge_bin_files(bin_files_info, output_path, flash_size, compact=compact_mode)
    
    if success:
        print(f"\n✓ Merge completed: {output_path}")
    else:
        print("\n✗ Merge failed!")
        sys.exit(1)


if __name__ == '__main__':
    main()

