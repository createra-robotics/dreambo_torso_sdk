"""Scan a serial bus to find which motor IDs respond at common baudrates."""

import argparse
import os
import time
from typing import List

import serial.tools.list_ports
from servocom import Sm40BlPyController

SERIAL_TIMEOUT = 0.01
COMMANDS_BITS_LENGTH = {
    "Ping": (10 + 14) * 10,
    "Read": (14 + 15) * 10,
    "Write": (16 + 11) * 10,
}
# FeeTech STS/SM control-table baudrate enum (SM40BL arms + STS3025BL nose).
BAUDRATE_CONV_TABLE = {
    1000000: 0,
    500000: 1,
    250000: 2,
    128000: 3,
    115200: 4,
    76800: 5,
    57600: 6,
    38400: 7,
}

# VID: 1a86 | PID: 55d3 is CH343 USB to Serial
def find_serial_port(
    wireless_version: bool = False,
    vid: str = "1a86",
    pid: str = "55d3",
    pi_uart: str = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034031-if00",
) -> list[str]:
    """Replicate from the daemon.utils.find_serial_port function."""
    # If it's a wireless version, we should use the Raspberry Pi UART
    if wireless_version:
        return [pi_uart] if os.path.exists(pi_uart) else []

    # If it's a lite version, we should find it using the VID and PID
    ports = serial.tools.list_ports.comports()
    vid = vid.upper()
    pid = pid.upper()
    return [p.device for p in ports if f"USB VID:PID={vid}:{pid}" in p.hwid]


def scan(port: str, baudrate: int) -> List[int]:
    """Scan the bus at the given baudrate and return detected IDs."""
    found_motors: list[int] = []
    controller = None
    try:
        controller = Sm40BlPyController(
            port,
            baudrate,
            float(SERIAL_TIMEOUT) + float(COMMANDS_BITS_LENGTH["Ping"]) / baudrate,
        )
        for motor_id in range(255):
            try:
                if controller.ping(motor_id):
                    found_motors.append(motor_id)
            except Exception:
                pass
    except Exception as e:
        print(f"Error while scanning port {port} at baudrate {baudrate}: {e}")
    finally:
        # CRITICAL: Close the controller to release the serial port
        if controller is not None:
            try:
                del controller
            except Exception:
                pass
        # Small delay to ensure port is fully released
        time.sleep(SERIAL_TIMEOUT)
    return found_motors


def main() -> None:
    """Iterate through baudrates and print the IDs found at each."""
    parser = argparse.ArgumentParser(
        description="Scan a serial bus to find which motor IDs respond at common baudrates.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=str,
        default=None,
        help="Serial port (e.g. /dev/ttyUSB0 or COM3). Auto-detected if not specified.",
    )
    parser.add_argument(
        "--wireless",
        action="store_true",
        help="Use the wireless version of the Dreambo torso (Raspberry Pi UART).",
    )
    args = parser.parse_args()

    if args.port:
        port = args.port
    else:
        ports = find_serial_port(wireless_version=args.wireless)
        if not ports:
            print(
                "No serial port found. Please check your USB connection and permissions."
            )
            return
        port = ports[0]

    for baudrate in BAUDRATE_CONV_TABLE.keys():
        print(f"Trying baudrate: {baudrate}")
        found_motors = scan(port, baudrate)
        if found_motors:
            print(f"Found motors at baudrate {baudrate}: {found_motors}")
        else:
            print(f"No motors found at baudrate {baudrate}")


if __name__ == "__main__":
    main()
