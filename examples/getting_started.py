from dreambo import Dreambo
from dreambo.utils import create_head_pose

with Dreambo() as dreambo:
    # Look up and tilt head
    dreambo.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        duration=1.0
    )