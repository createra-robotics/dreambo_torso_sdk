"""Real-robot backend for Dreambo torso.

Drives the four torso subsystems through :class:`DreamboPyControlLoop`
from ``dreambo_motor_controller``:

- neck      via ``set_neck_position(..)``      (3 DM motors over CAN)
- left_arm  via ``set_left_arm_position(..)``  (Feetech serial servos)
- right_arm via ``set_right_arm_position(..)`` (Feetech serial servos)
- nose      via ``set_nose_position(..)``      (Feetech serial servos)
"""

import logging
import struct
import time
from datetime import timedelta
from multiprocessing import Event  # more accurate than threading.Event
from typing import Annotated, Any

import numpy as np
import numpy.typing as npt
from dreambo_motor_controller import DreamboPyControlLoop

from dreambo_torso.io.protocol import (
    ImuDataMsg,
    JointPositionsMsg,
    MotorControlMode,
    RobotBackendStatus,
)
from dreambo_torso.utils.hardware_config.parser import parse_yaml_config

from ..abstract import ARM_DOF, NECK_DOF, NOSE_DOF, Backend


class RobotBackend(Backend):
    """Real-robot backend for the Dreambo torso."""

    def __init__(
        self,
        serialport: str,
        log_level: str = "INFO",
        hardware_error_check_frequency: float = 1.0,
        use_audio: bool = True,
        wireless_version: bool = False,
        hardware_config_filepath: str | None = None,
    ) -> None:
        """Open the motor controller and prep the control loop."""
        super().__init__(
            log_level=log_level,
            use_audio=use_audio,
            wireless_version=wireless_version,
        )

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)

        self.control_loop_frequency = 50.0  # Hz
        self.c: DreamboPyControlLoop | None = DreamboPyControlLoop(
            serialport,
            read_position_loop_period=timedelta(
                seconds=1.0 / self.control_loop_frequency
            ),
            allowed_retries=5,
            stats_pub_period=timedelta(seconds=1.0),
        )

        self.name2id = self.c.get_motor_name_id()
        if hardware_config_filepath is not None:
            config = parse_yaml_config(hardware_config_filepath)
            for motor_name, motor_conf in config.motors.items():
                if motor_conf.pid is not None:
                    motor_id = self.name2id[motor_name]
                    p, i, d = motor_conf.pid
                    self.logger.info(
                        f"Setting PID gains for motor '{motor_name}' (ID: {motor_id}): "
                        f"P={p}, I={i}, D={d}"
                    )
                    self.c.async_write_pid_gains(motor_id, p, i, d)

        self.motor_control_mode = self._infer_control_mode()
        self._torque_enabled = self.motor_control_mode != MotorControlMode.Disabled
        self.logger.info(f"Motor control mode: {self.motor_control_mode}")
        self.last_alive: float | None = None

        self._status = RobotBackendStatus(
            motor_control_mode=self.motor_control_mode,
            ready=False,
            last_alive=None,
            control_loop_stats={},
        )
        self._stats_record_period = 1.0  # seconds
        self._stats: dict[str, Any] = {
            "timestamps": [],
            "nb_error": 0,
            "record_period": self._stats_record_period,
        }

        if hardware_error_check_frequency <= 0:
            raise ValueError(
                "hardware_error_check_frequency must be positive and non-zero (Hz)."
            )
        self.hardware_error_check_period = 1.0 / hardware_error_check_frequency

        # IMU stub (kept for future wireless integration).
        self.bmi088 = None

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Drive the motor controller at ``control_loop_frequency``."""
        assert self.c is not None, "Motor controller not initialized or already closed."

        period = 1.0 / self.control_loop_frequency
        self.stats_record_t0 = time.time()
        self.last_hardware_error_check_time = time.time()
        next_call_event = Event()

        while not self.should_stop.is_set():
            start_t = time.time()
            self._stats["timestamps"].append(time.time())
            self._update()
            took = time.time() - start_t

            sleep_time = period - took
            if sleep_time < 0:
                self.logger.debug(
                    f"Control loop took too long: {took * 1000:.3f} ms, "
                    f"expected {period * 1000:.3f} ms"
                )
                sleep_time = 0.001

            next_call_event.clear()
            next_call_event.wait(sleep_time)

    def _update(self) -> None:
        assert self.c is not None, "Motor controller not initialized or already closed."

        if self._torque_enabled:
            if self.target_neck_joint_positions is not None:
                self.c.set_neck_position(self.target_neck_joint_positions.tolist())
            if self.target_left_arm_joint_positions is not None:
                self.c.set_left_arm_position(
                    self.target_left_arm_joint_positions.tolist()
                )
            if self.target_right_arm_joint_positions is not None:
                self.c.set_right_arm_position(
                    self.target_right_arm_joint_positions.tolist()
                )
            if self.target_nose_joint_positions is not None:
                self.c.set_nose_position(self.target_nose_joint_positions.tolist())

        try:
            self._refresh_present_positions()

            if (
                self.joint_positions_publisher is not None
                and not self.is_shutting_down
                and self.current_neck_joint_positions is not None
                and self.current_left_arm_joint_positions is not None
                and self.current_right_arm_joint_positions is not None
                and self.current_nose_joint_positions is not None
            ):
                self.joint_positions_publisher.put(
                    JointPositionsMsg(
                        neck=self.current_neck_joint_positions.tolist(),
                        left_arm=self.current_left_arm_joint_positions.tolist(),
                        right_arm=self.current_right_arm_joint_positions.tolist(),
                        nose=self.current_nose_joint_positions.tolist(),
                    )
                )

                if self.imu_publisher is not None and self.bmi088 is not None:
                    imu_msg = self.get_imu_data()
                    if imu_msg is not None:
                        self.imu_publisher.put(imu_msg)

            self.last_alive = time.time()
            self.ready.set()
        except RuntimeError as e:
            self._stats["nb_error"] += 1
            if self.last_alive is not None and self.last_alive + 1 < time.time():
                self.error = "No response from the robot's motor for the last second."
                self.logger.error(
                    "No response from the robot for the last second, stopping."
                )
                raise e

        if time.time() - self.stats_record_t0 > self._stats_record_period:
            dt = np.diff(self._stats["timestamps"])
            if len(dt) > 1:
                self._status.control_loop_stats["mean_control_loop_frequency"] = float(
                    np.mean(1.0 / dt)
                )
                self._status.control_loop_stats["max_control_loop_interval"] = float(
                    np.max(dt)
                )
                self._status.control_loop_stats["nb_error"] = self._stats["nb_error"]
                self._status.control_loop_stats["motor_controller"] = str(
                    self.c.get_stats()
                )

            self._stats["timestamps"].clear()
            self._stats["nb_error"] = 0
            self.stats_record_t0 = time.time()

        if (
            time.time() - self.last_hardware_error_check_time
            > self.hardware_error_check_period
        ):
            hardware_errors = self.read_hardware_errors()
            if hardware_errors:
                for motor_name, errors in hardware_errors.items():
                    self.logger.error(
                        f"Motor '{motor_name}' hardware errors: {errors}"
                    )
            self.last_hardware_error_check_time = time.time()

    def _refresh_present_positions(self) -> None:
        """Pull cached positions from the motor controller into our state."""
        assert self.c is not None
        pos = self.c.get_last_position()

        try:
            neck = list(self.c.read_neck_positions())
            if len(neck) == NECK_DOF:
                self.current_neck_joint_positions = np.array(neck, dtype=np.float64)
        except Exception:
            # Neck read can fail if the CAN bus isn't up. Leave the cached
            # value alone in that case.
            pass

        left = list(getattr(pos, "left_arm", []))
        right = list(getattr(pos, "right_arm", []))
        nose = list(getattr(pos, "nose", []))

        if len(left) >= ARM_DOF:
            self.current_left_arm_joint_positions = np.array(
                left[:ARM_DOF], dtype=np.float64
            )
        if len(right) >= ARM_DOF:
            self.current_right_arm_joint_positions = np.array(
                right[:ARM_DOF], dtype=np.float64
            )
        if len(nose) >= NOSE_DOF:
            self.current_nose_joint_positions = np.array(
                nose[:NOSE_DOF], dtype=np.float64
            )

    # ------------------------------------------------------------------
    # Life cycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the motor controller and release shared resources."""
        if self.c is not None:
            self.c.close()
        self.c = None
        super().close()

    def get_status(self) -> "RobotBackendStatus":
        """Return the cached :class:`RobotBackendStatus` with the latest error/mode."""
        self._status.error = self.error
        self._status.motor_control_mode = self.motor_control_mode
        return self._status

    # ------------------------------------------------------------------
    # Per-subsystem reads
    # ------------------------------------------------------------------

    def get_present_neck_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NECK_DOF,)]:
        """Return the current neck joint positions [yaw, pitch, roll]."""
        if self.current_neck_joint_positions is None:
            return np.zeros(NECK_DOF, dtype=np.float64)
        return self.current_neck_joint_positions

    def get_present_left_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Return the current left-arm joint positions [theta_a, theta_b]."""
        if self.current_left_arm_joint_positions is None:
            return np.zeros(ARM_DOF, dtype=np.float64)
        return self.current_left_arm_joint_positions

    def get_present_right_arm_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (ARM_DOF,)]:
        """Return the current right-arm joint positions [theta_a, theta_b]."""
        if self.current_right_arm_joint_positions is None:
            return np.zeros(ARM_DOF, dtype=np.float64)
        return self.current_right_arm_joint_positions

    def get_present_nose_joint_positions(
        self,
    ) -> Annotated[npt.NDArray[np.float64], (NOSE_DOF,)]:
        """Return the current nose joint positions [top, left, right]."""
        if self.current_nose_joint_positions is None:
            return np.zeros(NOSE_DOF, dtype=np.float64)
        return self.current_nose_joint_positions

    # ------------------------------------------------------------------
    # Motor control mode
    # ------------------------------------------------------------------

    def enable_motors(self) -> None:
        """Enable torque on every subsystem."""
        assert self.c is not None
        self.c.enable_torque()
        self._torque_enabled = True

    def disable_motors(self) -> None:
        """Disable torque on every subsystem."""
        assert self.c is not None
        self.c.disable_torque()
        self._torque_enabled = False

    def get_motor_control_mode(self) -> MotorControlMode:
        """Return the current motor control mode."""
        return self.motor_control_mode

    def set_motor_control_mode(self, mode: MotorControlMode) -> None:
        """Toggle torque on/off based on the requested control mode."""
        if mode == self.motor_control_mode:
            return

        if mode == MotorControlMode.Enabled:
            self.enable_motors()
        elif mode == MotorControlMode.Disabled:
            self.disable_motors()
        else:
            raise ValueError(f"Unsupported motor control mode: {mode}")

        self.motor_control_mode = mode

    def set_motor_torque_ids(self, ids: list[str], on: bool) -> None:
        """Toggle torque on the named motors."""
        assert self.c is not None
        assert ids, "IDs list cannot be empty or None."
        ids_int = [self.name2id[name] for name in ids]
        if on:
            self.c.enable_torque_on_ids(ids_int)
        else:
            self.c.disable_torque_on_ids(ids_int)

    def _infer_control_mode(self) -> MotorControlMode:
        """Read the controller's torque flag and translate to :class:`MotorControlMode`."""
        assert self.c is not None
        return (
            MotorControlMode.Enabled
            if self.c.is_torque_enabled()
            else MotorControlMode.Disabled
        )

    # ------------------------------------------------------------------
    # IMU (wireless version only)
    # ------------------------------------------------------------------

    def get_imu_data(self) -> ImuDataMsg | None:
        """Read accelerometer / gyro / quaternion / temperature. None if no IMU."""
        if self.bmi088 is None:
            return None
        try:
            accel_x, accel_y, accel_z = self.bmi088.read_accelerometer(m_per_s2=True)
            gyro_x, gyro_y, gyro_z = self.bmi088.read_gyroscope(deg_per_s=False)
            dt = 1.0 / self.control_loop_frequency
            quat = self.bmi088.get_quat(dt)
            temperature = self.bmi088.read_temperature()
            return ImuDataMsg(
                accelerometer=[float(accel_x), float(accel_y), float(accel_z)],
                gyroscope=[float(gyro_x), float(gyro_y), float(gyro_z)],
                quaternion=[float(q) for q in quat],
                temperature=float(temperature),
            )
        except Exception as e:
            self.logger.error(f"Error reading IMU data: {e}")
            return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def read_hardware_errors(self) -> dict[str, list[str]]:
        """Decode Feetech hardware error bytes for every motor on the bus."""
        if self.c is None:
            return {}

        def decode_hardware_error_byte(err_byte: int) -> list[str]:
            bits_to_error = {
                0: "Input Voltage Error",
                2: "Overheating Error",
                4: "Electrical Shock Error",
                5: "Overload Error",
            }
            err_bits = [i for i in range(8) if (err_byte & (1 << i)) != 0]
            return [bits_to_error[b] for b in err_bits if b in bits_to_error]

        def voltage_ok(id: int, allowed_max_voltage: float = 7.8) -> bool:
            assert self.c is not None
            resp_bytes = self.c.async_read_raw_bytes(id, 144, 2)
            resp = struct.unpack("h", bytes(resp_bytes))[0]
            voltage: float = resp / 10.0
            return voltage <= allowed_max_voltage

        errors: dict[str, list[str]] = {}
        for name, id in self.c.get_motor_name_id().items():
            try:
                err_byte = self.c.async_read_raw_bytes(id, 70, 1)
                assert len(err_byte) == 1
                err = decode_hardware_error_byte(err_byte[0])
                if err:
                    if "Input Voltage Error" in err and voltage_ok(id):
                        err.remove("Input Voltage Error")
                    if err:
                        errors[name] = err
            except (RuntimeError, AssertionError) as e:
                self.logger.warning(
                    f"Failed to read hardware errors for motor '{name}' (id={id}): {e}"
                )
        return errors

    def write_raw_packet(self, packet: bytes) -> bytes:
        """Send a raw packet to the motor controller and return its response."""
        assert self.c is not None
        return bytes(self.c.write_raw_packet(packet))
