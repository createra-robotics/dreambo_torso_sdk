"""Reachy Mini SDK."""

from importlib.metadata import version

from dreambo_torso.apps.app import ReachyMiniApp
from dreambo_torso.dreambo_torso import Dreambo

__version__ = version("dreambo_torso")

__all__ = ["Dreambo", "ReachyMiniApp", "__version__"]
