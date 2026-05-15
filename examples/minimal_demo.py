"""Minimal demo: nod the neck and waggle the nose in a loop."""

# START doc_example

import time

import numpy as np

from dreambo_torso import Dreambo

with Dreambo(media_backend="no_media") as mini:
    mini.goto_target(neck=[0.0, 0.2, 0.0], nose=[0.0, 0.0, 0.0], duration=1.0)
    try:
        while True:
            t = time.time()

            pitch = 0.2 + np.deg2rad(10 * np.sin(2 * np.pi * 0.5 * t))
            nose_top = np.deg2rad(15 * np.sin(2 * np.pi * 0.5 * t))

            mini.set_target(neck=[0.0, pitch, 0.0], nose=[nose_top, 0.0, 0.0])
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass

# END doc_example
