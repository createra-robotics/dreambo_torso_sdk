"""Rewrite the Feetech arm offset registers to lock in a new radian-zero.

Persistent across power cycles — the current physical arm pose becomes
``(0, 0, 0, 0) rad`` and stays that way until called again.

Usage:
    1. Hand-position both arms at the pose you want to be "(0, 0, 0, 0) rad".
    2. uv run python scripts/set_arm_home.py
"""

from dreambo_motor_controller import DreamboMotorController

SERIAL = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B79034031-if00"
CAN = "can0"


def main() -> None:
    """Drive the controller, write the offset registers, print the verify readback."""
    c = DreamboMotorController(SERIAL, CAN)
    observed = c.set_arm_home()
    print("post-zero present (rad):", observed)
    print("[left_pitch, left_yaw, right_pitch, right_yaw]")


if __name__ == "__main__":
    main()
