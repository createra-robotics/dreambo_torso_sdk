"""Interactive servo calibration tool for the Dreambo torso.

Serial Permission:

sudo usermod -aG dialout $USER
newgrp dialout

For each motor listed in ``hardware_config.yaml`` the tool guides the user
through three manual steps:

    1. Move the joint to its mechanical ZERO position  -> recorded as ``offset``
    2. Move the joint to its LOWER limit               -> recorded as ``lower_limit``
    3. Move the joint to its UPPER limit               -> recorded as ``upper_limit``

The torque is disabled while the user moves the joint by hand, the raw
absolute-encoder position is read back, and after the user confirms the
three values they are written back into ``hardware_config.yaml`` (in place,
preserving comments and formatting).

The tool does NOT touch the servo's EEPROM. After calibration, run
``setup_motor.py`` to push the new values from the YAML into each servo.

Usage:

    # Calibrate a single motor (only one motor on the bus at a time)
    python -m dreambo_torso.tools.calibrate_motor left_arm_pitch

    # Walk through every motor in the config, prompting to swap between them
    python -m dreambo_torso.tools.calibrate_motor all

    # Override the config path or run without writing
    python -m dreambo_torso.tools.calibrate_motor nose_top --config /path/to/cfg.yaml --dry-run

The serial port is auto-detected by USB VID/PID (CH343: 1a86:55d3); pass
``--wireless`` to use the Raspberry Pi UART path instead.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

from servocom import Sm40BlPyController, Sts3025BlPyController

from dreambo_torso import __file__ as _dt_init
from dreambo_torso.tools.scan_motors import find_serial_port
from dreambo_torso.utils.hardware_config.parser import MotorConfig, parse_yaml_config

SERIAL_TIMEOUT = 0.01
# (TX + RX) * (1 start + 8 data + 1 stop) — matches setup_motor.py.
PING_BITS = (10 + 14) * 10
READ_BITS = (14 + 15) * 10

# Dreambo torso bus layout: arms are SM40BL (IDs 1-4), nose is STS3025BL (IDs 5-7).
ARM_IDS = {1, 2, 3, 4}
NOSE_IDS = {5, 6, 7}

DEFAULT_CONFIG = (
    Path(_dt_init).parent / "assets" / "config" / "hardware_config.yaml"
)

MOTOR_NAMES = [
    "left_arm_pitch",
    "left_arm_yaw",
    "right_arm_pitch",
    "right_arm_yaw",
    "nose_top",
    "nose_left",
    "nose_right",
]


def _make_controller(port: str, motor_id: int, baudrate: int, bits: int):
    """Pick the right FeeTech controller for the motor's family."""
    timeout = SERIAL_TIMEOUT + float(bits) / baudrate
    if motor_id in ARM_IDS:
        return Sm40BlPyController(port, baudrate=baudrate, timeout=timeout)
    if motor_id in NOSE_IDS:
        return Sts3025BlPyController(port, baudrate=baudrate, timeout=timeout)
    raise ValueError(
        f"Unknown motor id {motor_id}; expected one of {sorted(ARM_IDS | NOSE_IDS)}."
    )


def _unwrap(value) -> int:
    """Unwrap a servocom read_* return value.

    Older versions returned ``int`` or ``(value, status)`` tuples; servocom
    1.1+ returns a list like ``[value, status]``. Handle all three shapes.
    """
    if isinstance(value, (tuple, list)):
        return int(value[0])
    return int(value)


def _read_position(controller, motor_id: int) -> int:
    return _unwrap(controller.read_raw_present_position(motor_id))


def _prompt(msg: str, default: str = "y") -> str:
    raw = input(msg).strip().lower()
    return raw or default


def _capture_position(controller, motor_id: int, label: str) -> Optional[int]:
    """Loop: prompt -> read -> confirm. Returns the confirmed raw value or None to skip."""
    while True:
        input(
            f"  -> Move the joint to its {label} position, then press Enter to record. "
        )
        try:
            pos = _read_position(controller, motor_id)
        except Exception as e:
            print(f"    [ERROR] Failed to read position: {e}")
            if _prompt("    Retry? [Y/n]: ") in ("n", "no"):
                return None
            continue
        print(f"    Recorded raw position: {pos}")
        ans = _prompt(
            f"    Accept {pos} as '{label}'? [Y]es / [r]etry / [s]kip: ",
            default="y",
        )
        if ans in ("y", "yes"):
            return pos
        if ans in ("s", "skip"):
            return None
        # otherwise: retry


def calibrate_motor(
    port: str,
    motor_name: str,
    motor_config: MotorConfig,
    baudrate: int,
) -> Optional[dict[str, int]]:
    """Walk the user through calibrating one motor. Returns dict of values, or None to skip."""
    print()
    print("=" * 60)
    print(f"Motor: {motor_name}  (ID={motor_config.id}, baudrate={baudrate})")
    print("=" * 60)

    # One controller for the whole motor — the underlying serial port is
    # opened in __init__ and has no close(); creating a second controller
    # for the same port would fail with EBUSY.
    try:
        c = _make_controller(port, motor_config.id, baudrate, READ_BITS)
        if not c.ping(motor_config.id):
            print(f"[FAIL] Motor with ID {motor_config.id} did not respond on {port}.")
            return None
        print(f"[OK] Motor with ID {motor_config.id} is online.")
    except Exception as e:
        print(f"[FAIL] Could not reach motor: {e}")
        return None

    # Disable torque so the user can move the joint by hand.
    try:
        c.write_torque_enable(motor_config.id, False)
        print("[OK] Torque disabled — joint is now free to move by hand.")
    except Exception as e:
        print(f"[WARN] Could not disable torque: {e}. The joint may resist movement.")

    zero = _capture_position(c, motor_config.id, "ZERO (mechanical center)")
    if zero is None:
        print("Skipping motor.")
        return None

    low = _capture_position(c, motor_config.id, "LOWER limit")
    if low is None:
        print("Skipping motor.")
        return None

    high = _capture_position(c, motor_config.id, "UPPER limit")
    if high is None:
        print("Skipping motor.")
        return None

    if not (low <= zero <= high):
        print(
            f"[WARN] Unusual ordering: lower={low}, zero={zero}, upper={high}. "
            "This is OK if the encoder wraps around, but double-check before saving."
        )

    print()
    print(f"Summary: offset={zero}, lower_limit={low}, upper_limit={high}")
    if _prompt("Write these values to hardware_config.yaml? [Y/n]: ") in ("n", "no"):
        print("Discarded.")
        return None

    return {"offset": zero, "lower_limit": low, "upper_limit": high}


_MOTOR_HEADER_RE = re.compile(r"^\s*-\s+(\w+)\s*:\s*$")


def update_yaml_file(
    yaml_path: Path, motor_name: str, values: dict[str, int]
) -> None:
    """Update the offset / lower_limit / upper_limit lines for ``motor_name`` in place.

    Text-based edit so YAML comments and formatting are preserved.
    """
    lines = yaml_path.read_text().splitlines(keepends=True)
    in_target = False
    fields_left = set(values.keys())

    for i, line in enumerate(lines):
        header = _MOTOR_HEADER_RE.match(line)
        if header:
            in_target = header.group(1) == motor_name
            continue
        if not in_target:
            continue
        for field in list(fields_left):
            field_re = re.compile(rf"^(\s+){field}\s*:\s*\S+(.*?)(\r?\n?)$")
            fm = field_re.match(line)
            if fm:
                indent, trailing, newline = fm.group(1), fm.group(2), fm.group(3)
                lines[i] = f"{indent}{field}: {values[field]}{trailing}{newline}"
                fields_left.remove(field)
                break

    if fields_left:
        raise RuntimeError(
            f"Could not locate fields {sorted(fields_left)} for motor "
            f"'{motor_name}' in {yaml_path}"
        )

    yaml_path.write_text("".join(lines))
    print(f"[OK] Updated {yaml_path} for motor '{motor_name}'.")


def main() -> None:
    """CLI entry point for the calibration tool."""
    parser = argparse.ArgumentParser(
        description=(
            "Interactive servo calibration: record physical zero & limits, "
            "write them back to hardware_config.yaml."
        )
    )
    parser.add_argument(
        "motor_name",
        type=str,
        help="Motor to calibrate. Use 'all' to step through every motor in the config.",
        choices=MOTOR_NAMES + ["all"],
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Path to hardware_config.yaml (default: {DEFAULT_CONFIG}).",
    )
    parser.add_argument(
        "--wireless",
        action="store_true",
        help="Use the Raspberry Pi UART instead of USB-RS485 (Dreambo wireless version).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run interactively but do NOT write to the YAML file.",
    )
    args = parser.parse_args()

    ports = find_serial_port(wireless_version=args.wireless)
    if not ports:
        print(
            "[FAIL] No serial port found via VID:PID lookup. "
            "Check USB connection and permissions, or pass --wireless."
        )
        sys.exit(1)
    port = ports[0]
    print(f"Using serial port: {port}")

    cfg = parse_yaml_config(str(args.config))
    baudrate = cfg.serial.baudrate

    if args.motor_name == "all":
        names = list(cfg.motors.keys())
    else:
        if args.motor_name not in cfg.motors:
            print(f"[FAIL] Motor '{args.motor_name}' is not in {args.config}.")
            sys.exit(1)
        names = [args.motor_name]

    print()
    print("Only ONE motor should be connected to the bus at a time.")
    print("Physically swap motors between iterations when calibrating 'all'.")
    print()

    updated: list[str] = []
    for i, name in enumerate(names):
        if i > 0:
            input(f"Press Enter when motor '{name}' is connected and ready... ")
        result = calibrate_motor(port, name, cfg.motors[name], baudrate)
        if result is None:
            continue
        if args.dry_run:
            print(f"[DRY-RUN] Would update {name}: {result}")
        else:
            update_yaml_file(args.config, name, result)
            updated.append(name)

    print()
    print("Calibration session complete.")
    if updated and not args.dry_run:
        print(f"Updated motors in YAML: {', '.join(updated)}")
        print(
            "Next: run `python -m dreambo_torso.tools.setup_motor <config> "
            "<motor_name> <serialport> --update-config` to push the new values "
            "into each servo's EEPROM."
        )


if __name__ == "__main__":
    main()
