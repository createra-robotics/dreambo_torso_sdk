from dreambo_torso import Dreambo
from dreambo_torso.utils import create_head_pose

with Dreambo() as dreambo_torso:
    # Look up and tilt head
    dreambo_torso.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        duration=1.0
    )