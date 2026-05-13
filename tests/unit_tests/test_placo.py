import platform

import pytest


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Placo is not available on Windows"
)
def test_load_kinematics():  # noqa: D100, D103
    from dreambo_torso.utils.constants import URDF_ROOT_PATH
    from dreambo_torso.kinematics import PlacoKinematics

    # Test loading the kinematics
    kinematics = PlacoKinematics(URDF_ROOT_PATH)
    assert kinematics is not None, "Failed to load PlacoKinematics."
