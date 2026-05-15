# Claude Code Prompt: Spherical 5-Bar Linkage Kinematics Library

## Project Brief

Build a kinematics library for a **spherical 5-bar linkage** mechanism (as used in Disney's Olaf robot shoulder joint). The library should have a **Rust core** for performance with **Python bindings** via PyO3/maturin.

## Mechanism Specification

The mechanism is a 2-DOF parallel spherical linkage where:

- All 5 revolute joint axes intersect at a single common point (the sphere center, which is also the virtual shoulder joint)
- **Link 1 (ground)**: fixed frame holding two servos with **orthogonal output shafts** intersecting at the sphere center
- **Link 2 (input A)**: curved arm driven by the lower YAW servo, rotates about axis `z_A` (vertical)
- **Link 3 (input B)**: curved arm driven by the upper servo, rotates about axis `z_B` (perpendicular to `z_A`, intersecting at origin)
- **Link 4 & Link 5 (coupler)**: a single rigid coupler body that joins both input arms via two revolute joints; the coupler is the end-effector
- Each link's "length" is an **angular arc** on the unit sphere (not a linear length), parameterized by an angle α_i

## Required Features

### Core Math (Rust crate `spherical5bar`)

1. **Configuration representation**
   - Input joint angles: `(θ_A, θ_B)` ∈ ℝ²
   - End-effector orientation: a unit quaternion or rotation matrix (SO(3))
   - Link geometry struct holding the 5 arc angles `α_1..α_5` and the two ground-axis orientations

2. **Forward kinematics**: `(θ_A, θ_B) → R ∈ SO(3)`
   - Solve the spherical loop closure equation
   - Return the rotation of the coupler frame relative to ground
   - Handle the branch/assembly-mode ambiguity (Olaf-style "same handedness" constraint — see Intuitive Surgical patent US 10,433,923 for the constraint formulation)

3. **Inverse kinematics**: `R → (θ_A, θ_B)`
   - Closed-form solution preferred (spherical 5-bar admits one)
   - Return all valid branches with assembly-mode labels

4. **Jacobian**: `J(θ) ∈ ℝ^{3×2}` mapping joint velocities to angular velocity of the coupler (in body or spatial frame — support both)

5. **Singularity detection**: compute `det(J^T J)` or condition number; flag Type I (boundary) and Type II (parallel/internal) singularities

6. **Workspace sampling**: given joint limits on `θ_A, θ_B`, enumerate reachable orientations; return as a point cloud on SO(3) or as a spherical region for the end-effector pointing direction

### Python Bindings (`spherical5bar-py`)

- Expose all core functions with NumPy-friendly signatures (accept/return `np.ndarray`)
- Quaternions as `(w, x, y, z)` arrays; rotations as `3×3` arrays
- Vectorized FK/IK that accepts a batch of configurations `(N, 2) → (N, 3, 3)`
- Type stubs (`.pyi`) for IDE support

### Visualization Helper (Python only)

- A `plot_mechanism(theta_A, theta_B, geometry)` function using matplotlib 3D that draws:
  - The unit sphere (light wireframe)
  - The 5 great-circle arcs representing the links
  - The 5 joint axes as radial vectors from the origin
  - The end-effector pointing direction

## Conventions & Constraints

- **Units**: all angles in radians internally; provide degree helpers
- **Rotation convention**: active rotations, right-handed, body-frame composition (R_new = R_old · R_delta)
- **No `unsafe` Rust** in the core math; use `nalgebra` for linear algebra
- **Determinism**: FK must be pure; IK should be deterministic given a branch selector
- **Errors**: use `thiserror` in Rust; raise typed exceptions in Python (`UnreachableError`, `SingularConfigurationError`)

## Testing Requirements

1. **Round-trip property test**: for random `(θ_A, θ_B)` in the valid range, `IK(FK(θ)) == θ` up to branch selection
2. **Jacobian numerical check**: finite-difference the FK and compare against analytical Jacobian (tolerance 1e-6)
3. **Known configuration**: at `(θ_A, θ_B) = (0, 0)` with a symmetric geometry, the coupler frame should match a hand-computed expected rotation
4. **Singularity case**: construct a geometry where a known singularity exists and verify it's detected
5. Use `proptest` in Rust and `hypothesis` in Python for property-based tests
6. Benchmark FK with `criterion`: target sub-microsecond for a single FK call

## Project Layout Example

```
spherical5bar/
├── Cargo.toml              # workspace
├── crates/
│   ├── core/               # pure Rust kinematics
│   │   ├── src/lib.rs
│   │   ├── src/geometry.rs # Geometry struct, builders
│   │   ├── src/fk.rs
│   │   ├── src/ik.rs
│   │   ├── src/jacobian.rs
│   │   └── benches/fk.rs
│   └── pybind/             # PyO3 bindings
│       └── src/lib.rs
├── python/
│   ├── spherical5bar/
│   │   ├── __init__.py
│   │   ├── viz.py          # matplotlib visualization
│   │   └── _core.pyi       # type stubs
│   └── tests/
│       └── test_kinematics.py
├── pyproject.toml          # maturin build
└── README.md
```

## Build & Tooling

- Use **maturin** for building the Python wheel
- `cargo test`, `cargo clippy -- -D warnings`, `cargo fmt --check` must all pass
- Python: `pytest`, `ruff`, `mypy --strict`
- Provide a `justfile` or `Makefile` with `build`, `test`, `bench`, `lint` targets

## What I'd Like You to Do

1. **Start by asking me 3-5 clarifying questions** about geometry conventions (axis directions, default arc angles for Olaf-like geometry, whether I want quaternions or matrices as the primary rotation type, etc.)
2. Propose the public API (Rust trait/struct signatures + Python function signatures) in a short doc and wait for my approval
3. Implement the core Rust crate first with full tests; show me the FK derivation as comments in `fk.rs`
4. Then add PyO3 bindings
5. Then the visualization helper
6. Finally, write a README with a worked example replicating Olaf-like shoulder motion

## References

- Disney Olaf paper: arXiv:2512.16705 (Section on spherical 5-bar shoulder)
- Intuitive Surgical patents US 8,142,420 / US 10,433,923 (5-bar spherical, handedness constraint)
- MDPI Robotics 2019, 8(1), 11 — iCub wrist comparison (kinematic equations for spherical 5-bar)

---

# Deployment
