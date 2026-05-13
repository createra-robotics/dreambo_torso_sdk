"""Utility constants for the reachy_mini package."""

from importlib.resources import files

import dreambo_torso

URDF_ROOT_PATH: str = str(files(dreambo_torso).joinpath("descriptions/reachy_mini/urdf"))
ASSETS_ROOT_PATH: str = str(files(dreambo_torso).joinpath("assets/"))
MODELS_ROOT_PATH: str = str(files(dreambo_torso).joinpath("assets/models"))
