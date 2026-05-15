"""Dreambo Torso sound Direction of Arrival (DoA) → neck motion example.

This script reads the DoA angle from the daemon's REST endpoint
(``/api/state/doa``) and turns the head toward the speaker by driving
the three Damiao neck motors directly through
``dreambo_motor_controller.DreamboMotorController``.

DoA convention (from ``dreambo_torso.media.audio_doa``):

    angle in radians, 0 = left, π/2 = front/back, π = right.

The example maps that angle to neck yaw with::

    neck_yaw = π/2 - doa_angle

so 0 rad → look left, π/2 rad → look forward, π rad → look right.
Pitch and roll are held at 0.

Caveat: the daemon's control loop also owns the CAN bus (``can0``).
Running this example while the daemon is active means both processes
write neck targets on every cycle and the daemon may pull the head back
to its idle target between our writes. Either run with the daemon's
neck disabled, or live with the jitter.
"""

# START doc_example

import random
import time

import numpy as np
import requests
from dreambo_motor_controller import DreamboMotorController

THRESHOLD_RAD = 0.04  # ignore DoA changes smaller than ~2°

# Motor command loop. The Damiao motors hold their target with PD control;
# updating that target at 100 Hz with soft gains and per-tick slewing is
# what makes the head sweep look continuous instead of stepped.
MOTOR_LOOP_HZ = 100
MOTOR_LOOP_PERIOD_S = 1.0 / MOTOR_LOOP_HZ

# DoA poll: HTTP would otherwise stall the motor loop. We fetch a few
# times per second and let the motor loop slew toward the latest target.
DOA_FETCH_PERIOD_S = 0.3
DOA_FETCH_TIMEOUT_S = 0.2

# Throttle the per-tick print so 100 Hz output doesn't drown the terminal.
PRINT_PERIOD_S = 0.5

# Soft MIT gains per neck joint, mirroring the reference sweep script:
# yaw is a DM-J4310-2EC, pitch and roll are DM-J4340P-2EC. Defaults inside
# the controller can be much stiffer and produce snappy step responses.
NECK_YAW_GAINS = (30.0, 1.0)
NECK_PITCH_GAINS = (60.0, 2.0)
NECK_ROLL_GAINS = (60.0, 2.0)

# Tracking gains: per-tick fraction of the remaining error to consume.
# Higher = snappier follow; lower = smoother but slower to converge.
# Each axis is also clamped by its MAX_*_RATE so it never overspeeds.
TRACK_GAIN_YAW = 0.08
TRACK_GAIN_PITCH = 0.04
TRACK_GAIN_ROLL = 0.04

# Hard angular-velocity cap per axis (rad/s) — only kicks in when the error
# is large enough that the proportional step would exceed this cap.
MAX_YAW_RATE_RAD_S = 1.5   # ~86°/s
MAX_PITCH_RATE_RAD_S = 0.6
MAX_ROLL_RATE_RAD_S = 0.6
# Use only a fraction of the hard pitch/roll envelope for the idle
# personality motion so the head never throws itself to the rail.
PERSONALITY_RANGE_FRACTION = 0.5
# Range of seconds between picking a new random pitch/roll target.
PERSONALITY_REFRESH_S = (2.0, 5.0)


def doa_to_neck_yaw(doa_angle_rad: float) -> float:
    """Map DoA (0=left, π/2=front, π=right) to neck yaw (left positive)."""
    return (np.pi / 2.0) - doa_angle_rad


def safe_clamp(
    value: float, limits: tuple[float, float], axis_name: str
) -> float:
    """Clamp *value* to [lower, upper] and print a warning when clipped."""
    lower, upper = limits
    if value < lower or value > upper:
        clamped = max(lower, min(upper, value))
        print(
            f"  ! {axis_name}={value:+.2f} rad outside "
            f"[{lower:+.2f}, {upper:+.2f}] — clamped to {clamped:+.2f} rad"
        )
        return clamped
    return value


def random_personality_target(limits: tuple[float, float]) -> float:
    """Pick a random target inside *limits*, narrowed by PERSONALITY_RANGE_FRACTION."""
    lower, upper = limits
    centre = 0.5 * (lower + upper)
    half_span = 0.5 * (upper - lower) * PERSONALITY_RANGE_FRACTION
    return random.uniform(centre - half_span, centre + half_span)


def slew(current: float, target: float, max_step: float) -> float:
    """Advance *current* toward *target* by at most *max_step* per call."""
    error = target - current
    if abs(error) <= max_step:
        return target
    return current + (max_step if error > 0 else -max_step)


def slew_proportional(
    current: float, target: float, gain: float, max_step: float
) -> float:
    """Move *current* toward *target* using P-control with a velocity cap.

    Each tick consumes ``gain`` of the remaining error (like a joystick
    stick whose deflection is the audio direction), then the resulting
    step is clamped to ±``max_step`` so a large error doesn't overspeed
    the motor. The result is natural exponential easing: fast when far,
    smooth when close, no abrupt stop on arrival.
    """
    error = target - current
    step = gain * error
    if step > max_step:
        step = max_step
    elif step < -max_step:
        step = -max_step
    return current + step


def main() -> None:
    """Stream DoA and drive the neck yaw motor to face the speaker."""
    doa_url = "http://localhost:8000/api/state/doa"

    # Neck-only controller: serialport=None skips the arm/nose serial bus.
    controller = DreamboMotorController(serialport=None, can_bus="can0")
    controller.enable_neck(True)

    # Apply soft MIT gains per joint — the high defaults can be snappy and
    # produce stepped-looking motion when we slew the target every tick.
    controller.set_neck_gains(0, *NECK_YAW_GAINS)
    controller.set_neck_gains(1, *NECK_PITCH_GAINS)
    controller.set_neck_gains(2, *NECK_ROLL_GAINS)
    print(
        f"Neck gains:  yaw={NECK_YAW_GAINS}  "
        f"pitch={NECK_PITCH_GAINS}  roll={NECK_ROLL_GAINS}"
    )

    # Hard safety bounds (lower, upper) per neck joint. The controller also
    # clamps internally, but we clamp here so we can log when a command was
    # out of range and never send an obviously-bad target.
    yaw_limits, pitch_limits, roll_limits = controller.neck_position_limits()
    print(
        f"Neck limits (rad):  yaw {yaw_limits}  "
        f"pitch {pitch_limits}  roll {roll_limits}"
    )

    home_position = [
        safe_clamp(0.0, yaw_limits, "yaw"),
        safe_clamp(0.0, pitch_limits, "pitch"),
        safe_clamp(0.0, roll_limits, "roll"),
    ]

    # Home all three neck joints (yaw, pitch, roll) before starting the DoA
    # loop so the head begins from a known, centered pose. Wait briefly so
    # the motors have time to settle before we start commanding yaw on top.
    print(f"Homing neck to {home_position} rad ...")
    observed_home = controller.set_neck_position(home_position)
    print(f"  observed neck position after homing: {observed_home}")
    time.sleep(0.5)

    # `commanded_*` is what we send to the motor this cycle. `target_*` is
    # the goal we're slewing toward. Yaw targets come from the DoA; pitch
    # and roll targets refresh on a random timer to give the head a gentle
    # idle personality on top of the speaker-tracking yaw motion.
    commanded_yaw, commanded_pitch, commanded_roll = home_position
    target_yaw = commanded_yaw
    target_pitch = commanded_pitch
    target_roll = commanded_roll

    now = time.monotonic()
    last_tick = now
    next_doa_fetch = now
    next_personality_refresh = now
    next_print = now

    try:
        while True:
            tick_start = time.monotonic()
            dt = tick_start - last_tick
            last_tick = tick_start

            # --- Slow DoA poll: update yaw goal at ~DOA_FETCH_PERIOD_S --------
            if tick_start >= next_doa_fetch:
                next_doa_fetch = tick_start + DOA_FETCH_PERIOD_S
                try:
                    response = requests.get(doa_url, timeout=DOA_FETCH_TIMEOUT_S)
                    response.raise_for_status()
                    doa_data = response.json()
                except requests.RequestException as e:
                    print(f"  Error fetching DoA: {e}")
                    doa_data = None

                if doa_data is None:
                    pass  # already logged or daemon not ready
                else:
                    angle = float(doa_data["angle"])
                    speech_detected = bool(doa_data["speech_detected"])
                    if speech_detected:
                        new_target = safe_clamp(
                            doa_to_neck_yaw(angle), yaw_limits, "yaw"
                        )
                        if abs(new_target - target_yaw) > THRESHOLD_RAD:
                            target_yaw = new_target
                            print(
                                f"DOA: angle={angle:.3f} rad "
                                f"({np.degrees(angle):+6.1f}°)  "
                                f"→ yaw goal {target_yaw:+.2f} rad"
                            )

            # --- Refresh idle pitch/roll targets ------------------------------
            if tick_start >= next_personality_refresh:
                target_pitch = safe_clamp(
                    random_personality_target(pitch_limits),
                    pitch_limits,
                    "pitch",
                )
                target_roll = safe_clamp(
                    random_personality_target(roll_limits),
                    roll_limits,
                    "roll",
                )
                next_personality_refresh = tick_start + random.uniform(
                    *PERSONALITY_REFRESH_S
                )

            # --- Slew each axis toward its target ----------------------------
            # P-control on the position error (DoA-error-as-velocity, like a
            # joystick whose deflection is the audio direction) plus a max
            # angular velocity cap. Step = clip(gain*error, ±rate*dt).
            commanded_yaw = safe_clamp(
                slew_proportional(
                    commanded_yaw, target_yaw,
                    TRACK_GAIN_YAW, MAX_YAW_RATE_RAD_S * dt,
                ),
                yaw_limits,
                "yaw",
            )
            commanded_pitch = safe_clamp(
                slew_proportional(
                    commanded_pitch, target_pitch,
                    TRACK_GAIN_PITCH, MAX_PITCH_RATE_RAD_S * dt,
                ),
                pitch_limits,
                "pitch",
            )
            commanded_roll = safe_clamp(
                slew_proportional(
                    commanded_roll, target_roll,
                    TRACK_GAIN_ROLL, MAX_ROLL_RATE_RAD_S * dt,
                ),
                roll_limits,
                "roll",
            )

            controller.set_neck_position(
                [commanded_yaw, commanded_pitch, commanded_roll]
            )

            # Throttled status line (printing at 50 Hz would flood the term).
            if tick_start >= next_print:
                next_print = tick_start + PRINT_PERIOD_S
                print(
                    f"  neck cmd=[{commanded_yaw:+.2f}, "
                    f"{commanded_pitch:+.2f}, {commanded_roll:+.2f}] rad  "
                    f"goals=[{target_yaw:+.2f}, {target_pitch:+.2f}, "
                    f"{target_roll:+.2f}]"
                )

            # Sleep just long enough to maintain the motor loop rate.
            sleep_for = MOTOR_LOOP_PERIOD_S - (time.monotonic() - tick_start)
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        # Centre the head (already clamped to the safe bounds) and release
        # torque so the neck rests gently.
        controller.set_neck_position(home_position)
        controller.enable_neck(False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Exiting...")

# END doc_example