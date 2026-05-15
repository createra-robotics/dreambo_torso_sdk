"""Minimal getting-started example: connect to Dreambo and tilt the neck up."""

from dreambo_torso import Dreambo

with Dreambo() as dreambo:
    # Chin-up nod with arms at rest.
    dreambo.goto_target(neck=[0.0, 0.35, 0.0], duration=1.0)
