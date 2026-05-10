"""Motor setup script for the Dreambo torso.

This script allows to configure the motors of the Dreambo torso by setting their ID, baudrate, offset, angle limits, return delay time, and removing the input voltage error.

The motor needs to be configured one by one, so you will need to connect only one motor at a time to the serial port. You can specify which motor to configure by passing its name as an argument.

If not specified, it assumes the motor is in the factory settings (ID 1 and baudrate 1000000). If it's not the case, you will need to use a tool like FeeTech Debug Tool to first reset it or manually specify the ID and baudrate.

Please note that all values given in the configuration file are in the motor's raw units.
"""

import argparse
import time
from pathlib import Path

from servocom import Sm40BlPyController, Sts3025BlPyController

from dreambo.utils.hardware_config.parser import MotorConfig, parse_yaml_config

FACTORY_DEFAULT_ID = 1
FACTORY_DEFAULT_BAUDRATE = 1000000
SERIAL_TIMEOUT = 0.01  # seconds
MOTOR_SETUP_DELAY = 0.1  # seconds

# Dreambo torso bus layout — arms are SM40BL (IDs 1-4), nose is STS3025BL (IDs 5-7).
ARM_IDS = {1, 2, 3, 4}
NOSE_IDS = {5, 6, 7}

# FeeTech STS/SM control-table baudrate enum.
FT_BAUDRATE_CONV_TABLE = {
    1000000: 0,
    500000: 1,
    250000: 2,
    128000: 3,
    115200: 4,
    76800: 5,
    57600: 6,
    38400: 7,
}

id2name = {
    1: "left_arm_pitch",
    2: "left_arm_yaw",
    3: "right_arm_pitch",
    4: "right_arm_yaw",
    5: "note_top",
    6: "nose_left",
    7: "nose_right",
}

# (TX + RX) * (1 start + 8 data + 1 stop)
COMMANDS_BITS_LENGTH = {
    "Ping": (10 + 14) * 10,
    "Read": (14 + 15) * 10,
    "Write": (16 + 11) * 10,
}


def _make_controller(serial_port: str, family_id: int, baudrate: int, timeout: float):
    """Return the FeeTech servo controller class for the bus the motor lives on.

    `family_id` is the *target* motor id (i.e. the id it will have once configured),
    not the id currently on the wire — the family is determined by the physical
    motor, which the caller knows from configuration.
    """
    if family_id in ARM_IDS:
        return Sm40BlPyController(serial_port, baudrate=baudrate, timeout=timeout)
    if family_id in NOSE_IDS:
        return Sts3025BlPyController(serial_port, baudrate=baudrate, timeout=timeout)
    raise ValueError(
        f"Unknown motor id {family_id}; expected one of {sorted(ARM_IDS | NOSE_IDS)}."
    )


def setup_motor(
    motor_config: MotorConfig,
    serial_port: str,
    from_baudrate: int,
    target_baudrate: int,
    from_id: int,
) -> None:
    """Set up the motor with the given configuration."""
    if not lookup_for_motor(
        serial_port,
        from_id,
        from_baudrate,
        family_id=motor_config.id,
    ):
        raise RuntimeError(
            f"Motor '{id2name.get(from_id, from_id)}' not found!"
        )

    # Make sure the torque is disabled to be able to write EEPROM
    disable_torque(serial_port, from_id, from_baudrate, family_id=motor_config.id)
    try:
        if from_baudrate != target_baudrate:
            change_baudrate(
                serial_port,
                id=from_id,
                base_baudrate=from_baudrate,
                target_baudrate=target_baudrate,
                family_id=motor_config.id,
            )
            time.sleep(MOTOR_SETUP_DELAY)

        if from_id != motor_config.id:
            change_id(
                serial_port,
                current_id=from_id,
                new_id=motor_config.id,
                baudrate=target_baudrate,
            )
            time.sleep(MOTOR_SETUP_DELAY)

        change_offset(
            serial_port,
            id=motor_config.id,
            offset=motor_config.offset,
            baudrate=target_baudrate,
        )

        time.sleep(MOTOR_SETUP_DELAY)

        change_angle_limits(
            serial_port,
            id=motor_config.id,
            angle_limit_min=motor_config.angle_limit_min,
            angle_limit_max=motor_config.angle_limit_max,
            baudrate=target_baudrate,
        )

        time.sleep(MOTOR_SETUP_DELAY)

        change_shutdown_error(
            serial_port,
            id=motor_config.id,
            baudrate=target_baudrate,
            shutdown_error=motor_config.shutdown_error,
        )

        time.sleep(MOTOR_SETUP_DELAY)

        change_return_delay_time(
            serial_port,
            id=motor_config.id,
            return_delay_time=motor_config.return_delay_time,
            baudrate=target_baudrate,
        )

        time.sleep(MOTOR_SETUP_DELAY)

        change_operating_mode(
            serial_port,
            id=motor_config.id,
            operating_mode=motor_config.operating_mode,
            baudrate=target_baudrate,
        )

        time.sleep(MOTOR_SETUP_DELAY)
    except Exception as e:
        print(f"Error while setting up motor ID {from_id}: {e}")
        raise e


def lookup_for_motor(
    serial_port: str,
    id: int,
    baudrate: int,
    silent: bool = False,
    family_id: int | None = None,
) -> bool:
    """Check if a motor with the given ID is reachable on the specified serial port."""
    if not silent:
        print(
            f"Looking for motor with ID {id} on port {serial_port}...",
            end="",
            flush=True,
        )
    c = _make_controller(
        serial_port,
        family_id if family_id is not None else id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Ping"]) / baudrate,
    )
    ret = c.ping(id)
    if not silent:
        print(f"{'[OK]' if ret else '[FAIL]'}")
    return ret


def disable_torque(
    serial_port: str, id: int, baudrate: int, family_id: int | None = None
) -> None:
    """Disable the torque of the motor with the given ID on the specified serial port."""
    print(f"Disabling torque for motor with ID {id}...", end="", flush=True)
    c = _make_controller(
        serial_port,
        family_id if family_id is not None else id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_torque_enable(id, False)
    print("[OK]")


def change_baudrate(
    serial_port: str,
    id: int,
    base_baudrate: int,
    target_baudrate: int,
    family_id: int | None = None,
) -> None:
    """Change the baudrate of the motor with the given ID on the specified serial port."""
    print(f"Changing baudrate to {target_baudrate}...", end="", flush=True)
    c = _make_controller(
        serial_port,
        family_id if family_id is not None else id,
        base_baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / base_baudrate,
    )
    c.write_baudrate(id, FT_BAUDRATE_CONV_TABLE[target_baudrate])
    print("[OK]")


def change_id(serial_port: str, current_id: int, new_id: int, baudrate: int) -> None:
    """Change the ID of the motor with the given current ID on the specified serial port."""
    print(f"Changing ID from {current_id} to {new_id}...", end="", flush=True)
    c = _make_controller(
        serial_port,
        new_id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_id(current_id, new_id)
    print("[OK]")


def change_offset(serial_port: str, id: int, offset: int, baudrate: int) -> None:
    """Change the offset of the motor with the given ID on the specified serial port."""
    print(f"Changing offset for motor with ID {id} to {offset}...", end="", flush=True)
    c = _make_controller(
        serial_port,
        id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_raw_offset(id, offset)
    print("[OK]")


def change_operating_mode(
    serial_port: str, id: int, operating_mode: int, baudrate: int
) -> None:
    """Change the operating mode of the motor with the given ID on the specified serial port."""
    print(
        f"Changing operating mode for motor with ID {id} to {operating_mode}...",
        end="",
        flush=True,
    )
    c = _make_controller(
        serial_port,
        id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_mode(id, operating_mode)
    print("[OK]")


def change_angle_limits(
    serial_port: str,
    id: int,
    angle_limit_min: int,
    angle_limit_max: int,
    baudrate: int,
) -> None:
    """Change the angle limits of the motor with the given ID on the specified serial port."""
    print(
        f"Changing angle limits for motor with ID {id} to [{angle_limit_min}, {angle_limit_max}]...",
        end="",
        flush=True,
    )
    c = _make_controller(
        serial_port,
        id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_raw_min_angle_limit(id, angle_limit_min)
    c.write_raw_max_angle_limit(id, angle_limit_max)
    print("[OK]")


def change_shutdown_error(
    serial_port: str, id: int, baudrate: int, shutdown_error: int
) -> None:
    """Change the shutdown error of the motor with the given ID on the specified serial port."""
    print(
        f"Changing shutdown error for motor with ID {id} to {shutdown_error}...",
        end="",
        flush=True,
    )
    c = _make_controller(
        serial_port,
        id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_unloading_condition(id, shutdown_error)
    print("[OK]")


def change_return_delay_time(
    serial_port: str, id: int, return_delay_time: int, baudrate: int
) -> None:
    """Change the return delay time of the motor with the given ID on the specified serial port."""
    print(
        f"Changing return delay time for motor with ID {id} to {return_delay_time}...",
        end="",
        flush=True,
    )
    c = _make_controller(
        serial_port,
        id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )
    c.write_return_delay_time(id, return_delay_time)
    print("[OK]")


def light_led_up(serial_port: str, id: int, baudrate: int) -> None:
    """Blink the motor LED briefly (~0.5s) by inducing an angle-limit alarm.

    FeeTech SM40BL/STS3025BL have no direct LED on/off — the LED only flashes
    when a condition enabled in reg 0x14 (LED Alarm Conditions) is currently
    active. Sequence:
      1. Save current alarm mask and raw min/max angle limits.
      2. Enable all alarm-flash bits (0x14 = 0xFE).
      3. Collapse the angle window to [0, 1] so the present position falls
         outside it and the angle-limit alarm asserts → LED flashes.
      4. Sleep so the flash is visible.
      5. Restore the saved alarm mask and angle limits.

    Assumes torque is disabled while called (the state setup_motor leaves the
    motor in). The five EEPROM writes per call are intended for the one-shot
    reflash flow, not for repeated runtime use.
    """
    c = _make_controller(
        serial_port,
        family_id=id,
        baudrate=baudrate,
        timeout=SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Write"]) / baudrate,
    )

    saved_alarm = c.read_led_alarm_condition(id)[0]
    saved_min = c.read_raw_min_angle_limit(id)[0]
    saved_max = c.read_raw_max_angle_limit(id)[0]

    try:
        c.write_led_alarm_condition(id, 0xFE)
        c.write_raw_min_angle_limit(id, 0)
        c.write_raw_max_angle_limit(id, 1)
        time.sleep(0.5)
    finally:
        c.write_raw_min_angle_limit(id, saved_min)
        c.write_raw_max_angle_limit(id, saved_max)
        c.write_led_alarm_condition(id, saved_alarm)


def light_led_down(serial_port: str, id: int, baudrate: int) -> None:
    """No-op: light_led_up restores LED state before returning."""
    return


def check_configuration(
    motor_config: MotorConfig, serial_port: str, baudrate: int
) -> None:
    """Check the configuration of the motor with the given ID on the specified serial port."""
    c = _make_controller(
        serial_port,
        motor_config.id,
        baudrate,
        SERIAL_TIMEOUT + float(COMMANDS_BITS_LENGTH["Read"]) / baudrate,
    )

    print("Checking configuration...")

    # Check if there is a motor with the desired ID
    if not c.ping(motor_config.id):
        raise RuntimeError(f"No motor with ID {motor_config.id} found, cannot proceed")
    print(f"Found motor with ID {motor_config.id} [OK].")

    # Read return delay time
    return_delay = c.read_return_delay_time(motor_config.id)[0]
    if return_delay != motor_config.return_delay_time:
        raise RuntimeError(
            f"Return delay time is {return_delay}, expected {motor_config.return_delay_time}"
        )
    print(f"Return delay time is correct: {return_delay} [OK].")

    # Read operating mode
    operating_mode = c.read_mode(motor_config.id)[0]
    if operating_mode != motor_config.operating_mode:
        raise RuntimeError(
            f"Operating mode is {operating_mode}, expected {motor_config.operating_mode}"
        )
    print(f"Operating mode is correct: {operating_mode} [OK].")

    # Read angle limits
    angle_limit_min = c.read_raw_min_angle_limit(motor_config.id)[0]
    angle_limit_max = c.read_raw_max_angle_limit(motor_config.id)[0]
    if angle_limit_min != motor_config.angle_limit_min:
        raise RuntimeError(
            f"Angle limit min is {angle_limit_min}, expected {motor_config.angle_limit_min}"
        )
    if angle_limit_max != motor_config.angle_limit_max:
        raise RuntimeError(
            f"Angle limit max is {angle_limit_max}, expected {motor_config.angle_limit_max}"
        )
    print(
        f"Angle limits are correct: [{motor_config.angle_limit_min}, {motor_config.angle_limit_max}] [OK]."
    )

    # Read homing offset
    offset = c.read_raw_offset(motor_config.id)[0]
    if offset != motor_config.offset:
        raise RuntimeError(f"Homing offset is {offset}, expected {motor_config.offset}")
    print(f"Homing offset is correct: {offset} [OK].")

    # Read shutdown
    shutdown = c.read_unloading_condition(motor_config.id)[0]
    if shutdown != motor_config.shutdown_error:
        raise RuntimeError(
            f"Shutdown is {shutdown}, expected {motor_config.shutdown_error}"
        )
    print(f"Shutdown error is correct: {shutdown} [OK].")

    print("Configuration is correct [OK]!")


def run(args: argparse.Namespace) -> None:
    """Entry point for the Dreambo torso motor configuration tool."""
    config = parse_yaml_config(args.config_file)

    if args.motor_name == "all":
        motors = list(config.motors.keys())
    else:
        motors = [args.motor_name]

    for motor_name in motors:
        motor_config = config.motors[motor_name]

        if args.update_config:
            args.from_id = motor_config.id
            args.from_baudrate = config.serial.baudrate

        if not args.check_only:
            setup_motor(
                motor_config,
                args.serialport,
                from_id=args.from_id,
                from_baudrate=args.from_baudrate,
                target_baudrate=config.serial.baudrate,
            )

        try:
            check_configuration(
                motor_config,
                args.serialport,
                baudrate=config.serial.baudrate,
            )
        except RuntimeError as e:
            print(f"[FAIL] Configuration check failed for motor '{motor_name}': {e}")
            return

        light_led_up(
            args.serialport,
            motor_config.id,
            baudrate=config.serial.baudrate,
        )


if __name__ == "__main__":
    """Entry point for the Dreambo torso motor configuration tool."""
    parser = argparse.ArgumentParser(description="Motor Configuration tool")
    parser.add_argument(
        "config_file",
        type=Path,
        help="Path to the hardware configuration file (default: hardware_config.yaml).",
    )
    parser.add_argument(
        "motor_name",
        type=str,
        help="Name of the motor to configure.",
        choices=[
            "left_arm_pitch",
            "left_arm_yaw",
            "right_arm_pitch",
            "right_arm_yaw",
            "nose_top",
            "nose_left",
            "nose_right",
            "all",
        ],
    )
    parser.add_argument(
        "serialport",
        type=str,
        help="Serial port for communication with the motor.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check the configuration without applying changes.",
    )
    parser.add_argument(
        "--from-id",
        type=int,
        default=FACTORY_DEFAULT_ID,
        help=f"Current ID of the motor (default: {FACTORY_DEFAULT_ID}).",
    )
    parser.add_argument(
        "--from-baudrate",
        type=int,
        default=FACTORY_DEFAULT_BAUDRATE,
        help=f"Current baudrate of the motor (default: {FACTORY_DEFAULT_BAUDRATE}).",
    )
    parser.add_argument(
        "--update-config",
        action="store_true",
        help="Update a specific motor (assumes it already has the correct id and baudrate).",
    )
    args = parser.parse_args()
    run(args)