"""Utility constants for the reachy_mini package."""

from importlib.resources import files

import dreambo

URDF_ROOT_PATH: str = str(files(dreambo).joinpath("descriptions/reachy_mini/urdf"))
ASSETS_ROOT_PATH: str = str(files(dreambo).joinpath("assets/"))
MODELS_ROOT_PATH: str = str(files(dreambo).joinpath("assets/models"))
