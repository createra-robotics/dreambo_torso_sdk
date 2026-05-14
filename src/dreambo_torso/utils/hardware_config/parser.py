"""Module to parse Dreambo hardware configuration from a YAML file."""

from dataclasses import dataclass, field

import yaml


@dataclass
class MotorConfig:
    """Motor configuration."""

    id: int
    offset: int
    angle_limit_min: int
    angle_limit_max: int
    return_delay_time: int
    shutdown_error: int
    operating_mode: int
    pid: tuple[int, int, int] | None = None


@dataclass
class ActuatorConfig:
    """CAN actuator (Damiao DM-Jxxxx) configuration.

    Limits are radians, not raw encoder ticks — the DM firmware works in SI
    units. ``motor_model`` names a ``motorcom.MitLimits`` preset (``dm4310``,
    ``dm4340p``, …) used to clamp the MIT setpoint.
    """

    bus: str
    can_id: int
    master_id: int
    motor_model: str
    offset: float
    lower_limit: float
    upper_limit: float
    operating_mode: int
    kp: float
    kd: float


@dataclass
class SerialConfig:
    """Serial configuration."""

    baudrate: int


@dataclass
class DreamboConfig:
    """Dreambo Robot configuration."""

    version: str
    serial: SerialConfig
    motors: dict[str, MotorConfig]
    actuators: dict[str, ActuatorConfig] = field(default_factory=dict)


def parse_yaml_config(filename: str) -> DreamboConfig:
    """Parse the YAML configuration file and return a DreamboConfig."""
    with open(filename, "r") as file:
        conf = yaml.load(file, Loader=yaml.FullLoader)

    version = conf["version"]

    motor_ids = {}
    for motor in conf["motors"]:
        for name, params in motor.items():
            motor_ids[name] = MotorConfig(
                id=params["id"],
                offset=params["offset"],
                angle_limit_min=params["lower_limit"],
                angle_limit_max=params["upper_limit"],
                return_delay_time=params["return_delay_time"],
                shutdown_error=params["shutdown_error"],
                operating_mode=params["operating_mode"],
                pid=params.get("pid"),
            )

    actuators: dict[str, ActuatorConfig] = {}
    for entry in conf.get("actuators") or []:
        for name, params in entry.items():
            actuators[name] = ActuatorConfig(
                bus=params["bus"],
                can_id=int(params["can_id"]),
                master_id=int(params["master_id"]),
                motor_model=str(params["motor_model"]),
                offset=float(params.get("offset", 0.0)),
                lower_limit=float(params["lower_limit"]),
                upper_limit=float(params["upper_limit"]),
                operating_mode=int(params.get("operating_mode", 0)),
                kp=float(params["kp"]),
                kd=float(params["kd"]),
            )

    serial = SerialConfig(baudrate=conf["serial"]["baudrate"])

    return DreamboConfig(
        version=version,
        serial=serial,
        motors=motor_ids,
        actuators=actuators,
    )