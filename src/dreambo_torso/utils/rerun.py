"""Rerun logging for the Dreambo torso.

Streams per-subsystem joint positions and (when available) the camera
frame to Rerun. URDF-based transform visualization will return once
the new Dreambo torso URDF is finalized.
"""

import json
import logging
import time
from datetime import datetime
from threading import Event, Thread
from typing import Optional

import numpy as np
import requests
import rerun as rr

from dreambo_torso.dreambo_torso import Dreambo
from dreambo_torso.media.media_manager import MediaBackend


_SUBSYSTEM_JOINT_NAMES = {
    "neck": ["neck_yaw", "neck_pitch", "neck_roll"],
    "left_arm": ["left_arm_theta_a", "left_arm_theta_b"],
    "right_arm": ["right_arm_theta_a", "right_arm_theta_b"],
    "nose": ["nose_top", "nose_left", "nose_right"],
}


class Rerun:
    """Rerun logger for the Dreambo torso."""

    def __init__(
        self,
        reachymini: Dreambo,
        app_id: str = "dreambo_torso_rerun",
        spawn: bool = True,
    ) -> None:
        """Initialize a Rerun recording targeting the given Dreambo client."""
        rr.init(app_id, spawn=spawn)
        self.app_id = app_id
        self._reachymini = reachymini
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(reachymini.logger.getEffectiveLevel())

        self._robot_ip = "localhost"
        status = self._reachymini.client.get_status()
        if status.wireless_version and status.wlan_ip:
            self._robot_ip = status.wlan_ip

        self.recording = rr.get_global_data_recording()
        rr.set_time("dreambo_torso", timestamp=time.time(), recording=self.recording)

        self.running = Event()
        self.thread_log_camera: Optional[Thread] = None
        if (
            reachymini.media.backend == MediaBackend.GSTREAMER
            or reachymini.media.backend == MediaBackend.DEFAULT
        ):
            self.thread_log_camera = Thread(target=self.log_camera, daemon=True)
        self.thread_log_movements = Thread(target=self.log_movements, daemon=True)

    def start(self) -> None:
        """Start the background logging threads."""
        if self.thread_log_camera is not None:
            self.thread_log_camera.start()
        self.thread_log_movements.start()

    def stop(self) -> None:
        """Signal the background threads to stop."""
        self.running.set()

    def log_camera(self) -> None:
        """Stream the camera frame to Rerun (no calibration overlay)."""
        if self._reachymini.media.camera is None:
            self.logger.warning("Camera is not initialized.")
            return

        self.logger.info("Starting camera logging to Rerun.")

        cam_K = np.array(
            [
                [550.3564, 0.0, 638.0112],
                [0.0, 549.1653, 364.589],
                [0.0, 0.0, 1.0],
            ]
        )

        while not self.running.is_set():
            frame = self._reachymini.media.get_frame()
            if frame is None:
                return
            if isinstance(frame, bytes):
                self.logger.warning(
                    "Received frame is jpeg. Please use default backend."
                )
                return

            rr.set_time("dreambo_torso", timestamp=time.time(), recording=self.recording)
            rr.log(
                "camera/image",
                rr.Pinhole(
                    image_from_camera=rr.datatypes.Mat3x3(cam_K),
                    width=frame.shape[1],
                    height=frame.shape[0],
                    image_plane_distance=0.8,
                    camera_xyz=rr.ViewCoordinates.RDF,
                ),
                rr.Image(frame, color_model="bgr").compress(),
                recording=self.recording,
            )

    def log_movements(self) -> None:
        """Poll the daemon's /api/state/full and log per-subsystem joint values."""
        url = f"http://{self._robot_ip}:8000/api/state/full"
        params = {
            "with_control_mode": "false",
            "with_neck": "true",
            "with_left_arm": "true",
            "with_right_arm": "true",
            "with_nose": "true",
        }

        target_period = 0.02  # 50 Hz, matches daemon control loop
        session = requests.Session()

        while not self.running.is_set():
            loop_start = time.time()

            try:
                msg = session.get(url, params=params, timeout=0.5)
            except requests.RequestException:
                time.sleep(target_period)
                continue

            if msg.status_code != 200:
                self.logger.error(
                    f"Request failed with status {msg.status_code}: {msg.text}"
                )
                time.sleep(target_period)
                continue
            try:
                data = json.loads(msg.text)
            except Exception:
                continue

            if data.get("timestamp"):
                api_ts = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                ).timestamp()
            else:
                api_ts = time.time()
            rr.set_time("dreambo_torso", timestamp=api_ts, recording=self.recording)

            for sub, names in _SUBSYSTEM_JOINT_NAMES.items():
                values = data.get(sub)
                if not values or len(values) != len(names):
                    continue
                for name, value in zip(names, values):
                    rr.log(
                        f"joints/{sub}/{name}",
                        rr.Scalars(value),
                        recording=self.recording,
                    )

            elapsed = time.time() - loop_start
            remaining = target_period - elapsed
            if remaining > 0:
                time.sleep(remaining)
