"""Reachy Mini SDK."""

from importlib.metadata import version

from dreambo.apps.app import ReachyMiniApp
from dreambo.dreambo import Dreambo

__version__ = version("dreambo")

__all__ = ["Dreambo", "ReachyMiniApp", "__version__"]
