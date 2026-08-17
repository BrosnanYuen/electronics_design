"""Force-directed schematic placement optimizer.

This module is a self-contained port of the force-directed placement physics
from the MIT-licensed `kicad-tools` project
(`src/kicad_tools/optim/{placement,components,geometry,config}.py`,
Copyright (c) 2024 RJ Walters).  No kicad-tools dependency is used; the
algorithm code is copied and adapted here so that `ltspice_netlist_to_kicad_sch`
can place schematic symbols with the same physics model:

- Component bodies carry electrostatic-like charge and repel each other
  (sampled edge-to-edge 1/r^2 falloff forces).
- Net connections act as Hooke-law springs pulling connected pins together
  (star topology, with power and clock nets using distinct stiffness).
- A rectangular page boundary repels components and hard-clamps them inside.
- A torsion potential biases rotations toward 90-degree orientations.
- Simulation runs with velocity damping until convergence, then positions
  snap to a placement grid and rotations snap to 90 degrees.

The public entry point used by the conversion pipeline is
:class:`ForceDirectedPlacer`.
"""

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import math  # Compute forces, energy, and grid snapping.
from dataclasses import dataclass  # Use small record types for the physics model.
from dataclasses import field  # Provide mutable default lists for components and springs.
from typing import Dict  # Type force and component mappings.
from typing import Iterable  # Type spring-creation inputs.
from typing import Iterator  # Type polygon edge iterators.
from typing import List  # Type collected model records.
from typing import Optional  # Type optional configuration parameters.
from typing import Sequence  # Type immutable model sequences.
from typing import Tuple  # Type tuple-based helper results.

import numpy as np  # Pack component state for compiled force calculations.
from numba import njit  # Compile the sampled edge-repulsion kernel.

__all__ = ["ForceDirectedPlacer", "PlacementConfig"]  # Export the public placement API.


@njit(cache=True)
def _edge_force(  # Compute sampled force on one receiving edge from one source edge.
    receiver_x1: float,
    receiver_y1: float,
    receiver_x2: float,
    receiver_y2: float,
    source_x1: float,
    source_y1: float,
    source_x2: float,
    source_y2: float,
    charge_density: float,
    min_distance: float,
    samples: int,
) -> Tuple[float, float]:
    receiver_dx = receiver_x2 - receiver_x1  # Compute the receiving edge vector.
    receiver_dy = receiver_y2 - receiver_y1  # Compute the receiving edge vector.
    receiver_length = math.sqrt(receiver_dx * receiver_dx + receiver_dy * receiver_dy)  # Measure the receiving edge.
    source_dx = source_x2 - source_x1  # Compute the source edge vector.
    source_dy = source_y2 - source_y1  # Compute the source edge vector.
    source_length_squared = source_dx * source_dx + source_dy * source_dy  # Measure the squared source edge.
    if receiver_length < 1.0e-10 or source_length_squared < 1.0e-20:  # Skip degenerate edges.
        return 0.0, 0.0  # Return zero force.
    source_length = math.sqrt(source_length_squared)  # Measure the source edge.
    sample_charge = charge_density * receiver_length / samples  # Distribute receiver charge across samples.
    force_x = 0.0  # Accumulate force X.
    force_y = 0.0  # Accumulate force Y.
    for sample_index in range(samples):  # Walk evenly spaced receiving-edge samples.
        parameter = (sample_index + 0.5) / samples  # Compute the midpoint sample parameter.
        sample_x = receiver_x1 + receiver_dx * parameter  # Compute sample X.
        sample_y = receiver_y1 + receiver_dy * parameter  # Compute sample Y.
        projection = ((sample_x - source_x1) * source_dx + (sample_y - source_y1) * source_dy) / source_length_squared  # Project onto the source segment.
        projection = max(0.0, min(1.0, projection))  # Clamp projection to the segment.
        closest_x = source_x1 + source_dx * projection  # Compute closest source point X.
        closest_y = source_y1 + source_dy * projection  # Compute closest source point Y.
        displacement_x = sample_x - closest_x  # Compute outward displacement X.
        displacement_y = sample_y - closest_y  # Compute outward displacement Y.
        raw_distance = math.sqrt(displacement_x * displacement_x + displacement_y * displacement_y)  # Measure raw displacement.
        distance = max(raw_distance, min_distance)  # Clamp the force denominator.
        if raw_distance < 1.0e-10:  # Match the zero-vector normalization behavior.
            continue  # This coincident sample contributes no directed force.
        magnitude = sample_charge * source_length / (distance * distance)  # Compute inverse-square force magnitude.
        force_x += displacement_x / raw_distance * magnitude  # Accumulate directed force X.
        force_y += displacement_y / raw_distance * magnitude  # Accumulate directed force Y.
    return force_x, force_y  # Return the sampled edge force.


@njit(cache=True)
def _compiled_body_forces(  # Compute component and page-boundary repulsion without Python object churn.
    positions: np.ndarray,
    rotations: np.ndarray,
    widths: np.ndarray,
    heights: np.ndarray,
    fixed: np.ndarray,
    boundary_width: float,
    boundary_height: float,
    charge_density: float,
    min_distance: float,
    samples: int,
    cutoff: float,
    boundary_scale: float,
    rotation_stiffness: float,
) -> Tuple[np.ndarray, np.ndarray]:
    count = positions.shape[0]  # Read the component count.
    corners = np.empty((count, 4, 2), dtype=np.float64)  # Store rotated rectangle corners.
    for component_index in range(count):  # Build every component outline once.
        half_width = widths[component_index] / 2.0  # Compute half width.
        half_height = heights[component_index] / 2.0  # Compute half height.
        radians = math.radians(rotations[component_index])  # Convert rotation to radians.
        cosine = math.cos(radians)  # Compute rotation cosine.
        sine = math.sin(radians)  # Compute rotation sine.
        local_x = (-half_width, half_width, half_width, -half_width)  # Define rectangle corner X offsets.
        local_y = (-half_height, -half_height, half_height, half_height)  # Define rectangle corner Y offsets.
        for corner_index in range(4):  # Rotate and translate each corner.
            corners[component_index, corner_index, 0] = positions[component_index, 0] + local_x[corner_index] * cosine - local_y[corner_index] * sine  # Store world X.
            corners[component_index, corner_index, 1] = positions[component_index, 1] + local_x[corner_index] * sine + local_y[corner_index] * cosine  # Store world Y.
    forces = np.zeros((count, 2), dtype=np.float64)  # Accumulate body forces.
    torques = np.zeros(count, dtype=np.float64)  # Accumulate body torques.
    cutoff_squared = cutoff * cutoff  # Precompute the pair cutoff.
    for first_index in range(count):  # Walk each unique component pair.
        for second_index in range(first_index + 1, count):  # Walk later components.
            if fixed[first_index] and fixed[second_index]:  # Two fixed bodies need no force calculation.
                continue  # Move to the next pair.
            delta_x = positions[first_index, 0] - positions[second_index, 0]  # Compute center separation X.
            delta_y = positions[first_index, 1] - positions[second_index, 1]  # Compute center separation Y.
            if delta_x * delta_x + delta_y * delta_y > cutoff_squared:  # Skip distant pairs.
                continue  # Move to the next pair.
            for first_edge in range(4):  # Walk first-component receiving edges.
                first_next = (first_edge + 1) % 4  # Resolve the edge endpoint.
                first_center_x = (corners[first_index, first_edge, 0] + corners[first_index, first_next, 0]) * 0.5  # Compute edge center X.
                first_center_y = (corners[first_index, first_edge, 1] + corners[first_index, first_next, 1]) * 0.5  # Compute edge center Y.
                for second_edge in range(4):  # Walk second-component source edges.
                    second_next = (second_edge + 1) % 4  # Resolve the source endpoint.
                    if not fixed[first_index]:  # Apply pair repulsion to a movable first component.
                        force_x, force_y = _edge_force(corners[first_index, first_edge, 0], corners[first_index, first_edge, 1], corners[first_index, first_next, 0], corners[first_index, first_next, 1], corners[second_index, second_edge, 0], corners[second_index, second_edge, 1], corners[second_index, second_next, 0], corners[second_index, second_next, 1], charge_density, min_distance, samples)  # Compute force on the first edge.
                        forces[first_index, 0] += force_x  # Accumulate first-component force X.
                        forces[first_index, 1] += force_y  # Accumulate first-component force Y.
                        torques[first_index] += (first_center_x - positions[first_index, 0]) * force_y - (first_center_y - positions[first_index, 1]) * force_x  # Accumulate first-component torque.
                    if not fixed[second_index]:  # Compute the asymmetric sampled reaction for a movable counterpart.
                        second_center_x = (corners[second_index, second_edge, 0] + corners[second_index, second_next, 0]) * 0.5  # Compute counterpart edge center X.
                        second_center_y = (corners[second_index, second_edge, 1] + corners[second_index, second_next, 1]) * 0.5  # Compute counterpart edge center Y.
                        reaction_x, reaction_y = _edge_force(corners[second_index, second_edge, 0], corners[second_index, second_edge, 1], corners[second_index, second_next, 0], corners[second_index, second_next, 1], corners[first_index, first_edge, 0], corners[first_index, first_edge, 1], corners[first_index, first_next, 0], corners[first_index, first_next, 1], charge_density, min_distance, samples)  # Compute force on the counterpart edge.
                        forces[second_index, 0] += reaction_x  # Accumulate counterpart force X.
                        forces[second_index, 1] += reaction_y  # Accumulate counterpart force Y.
                        torques[second_index] += (second_center_x - positions[second_index, 0]) * reaction_y - (second_center_y - positions[second_index, 1]) * reaction_x  # Accumulate counterpart torque.
    boundary_edges = np.array(((0.0, 0.0, boundary_width, 0.0), (boundary_width, 0.0, boundary_width, boundary_height), (boundary_width, boundary_height, 0.0, boundary_height), (0.0, boundary_height, 0.0, 0.0)), dtype=np.float64)  # Build page edges.
    for component_index in range(count):  # Apply page-boundary and rotation forces.
        if fixed[component_index]:  # Skip fixed components.
            continue  # Move to the next component.
        inside = 0.0 <= positions[component_index, 0] <= boundary_width and 0.0 <= positions[component_index, 1] <= boundary_height  # Test the page rectangle.
        signed_scale = boundary_scale if inside else -boundary_scale * 10.0  # Push inward or pull escaped bodies back.
        for body_edge in range(4):  # Walk body receiving edges.
            body_next = (body_edge + 1) % 4  # Resolve the body endpoint.
            edge_center_x = (corners[component_index, body_edge, 0] + corners[component_index, body_next, 0]) * 0.5  # Compute body edge center X.
            edge_center_y = (corners[component_index, body_edge, 1] + corners[component_index, body_next, 1]) * 0.5  # Compute body edge center Y.
            for boundary_edge in range(4):  # Walk page source edges.
                force_x, force_y = _edge_force(corners[component_index, body_edge, 0], corners[component_index, body_edge, 1], corners[component_index, body_next, 0], corners[component_index, body_next, 1], boundary_edges[boundary_edge, 0], boundary_edges[boundary_edge, 1], boundary_edges[boundary_edge, 2], boundary_edges[boundary_edge, 3], charge_density, min_distance, samples)  # Compute raw page force.
                force_x *= signed_scale  # Scale boundary force X.
                force_y *= signed_scale  # Scale boundary force Y.
                forces[component_index, 0] += force_x  # Accumulate page force X.
                forces[component_index, 1] += force_y  # Accumulate page force Y.
                torques[component_index] += (edge_center_x - positions[component_index, 0]) * force_y - (edge_center_y - positions[component_index, 1]) * force_x  # Accumulate page torque.
        torques[component_index] += -rotation_stiffness * math.sin(math.radians(rotations[component_index] * 4.0))  # Apply the 90-degree torsion well.
    return forces, torques  # Return compiled repulsion results.


@dataclass
class Vector2D:  # A lightweight 2D vector used by the physics model.
    """2D vector for physics calculations (ported from kicad-tools geometry)."""

    x: float = 0.0  # Horizontal component.
    y: float = 0.0  # Vertical component.

    def __add__(self, other: "Vector2D") -> "Vector2D":  # Vector addition.
        return Vector2D(self.x + other.x, self.y + other.y)  # Return the sum vector.

    def __sub__(self, other: "Vector2D") -> "Vector2D":  # Vector subtraction.
        return Vector2D(self.x - other.x, self.y - other.y)  # Return the difference vector.

    def __mul__(self, scalar: float) -> "Vector2D":  # Scalar multiplication.
        return Vector2D(self.x * scalar, self.y * scalar)  # Return the scaled vector.

    def __rmul__(self, scalar: float) -> "Vector2D":  # Reverse scalar multiplication.
        return self.__mul__(scalar)  # Reuse the forward multiplication.

    def __neg__(self) -> "Vector2D":  # Vector negation.
        return Vector2D(-self.x, -self.y)  # Return the negated vector.

    def dot(self, other: "Vector2D") -> float:  # Dot product.
        return self.x * other.x + self.y * other.y  # Return the scalar product.

    def cross(self, other: "Vector2D") -> float:  # 2D cross product.
        return self.x * other.y - self.y * other.x  # Return the scalar z-component.

    def magnitude(self) -> float:  # Vector length.
        return math.sqrt(self.x * self.x + self.y * self.y)  # Return the Euclidean length.

    def magnitude_squared(self) -> float:  # Squared vector length.
        return self.x * self.x + self.y * self.y  # Return the squared length.

    def normalized(self) -> "Vector2D":  # Unit vector in the same direction.
        mag = self.magnitude()  # Compute the current length.
        if mag < 1e-10:  # Guard the zero vector.
            return Vector2D(0.0, 0.0)  # Return the zero vector unchanged.
        return Vector2D(self.x / mag, self.y / mag)  # Return the unit vector.


@dataclass
class Polygon:  # A closed polygon used for component bodies and the page boundary.
    """Closed polygon represented as a list of vertices (ported from kicad-tools)."""

    vertices: List[Vector2D] = field(default_factory=list)  # Ordered corner vertices.

    @classmethod
    def rectangle(cls, x: float, y: float, width: float, height: float) -> "Polygon":  # Build a centered rectangle.
        hw, hh = width / 2, height / 2  # Compute half extents.
        return cls(  # Assemble the corner list.
            vertices=[  # Emit the four corners.
                Vector2D(x - hw, y - hh),  # Bottom-left.
                Vector2D(x + hw, y - hh),  # Bottom-right.
                Vector2D(x + hw, y + hh),  # Top-right.
                Vector2D(x - hw, y + hh),  # Top-left.
            ]  # Finish the corner list.
        )  # Return the rectangle polygon.

    @classmethod
    def from_rotated_rectangle(cls, x: float, y: float, width: float, height: float, rotation: float = 0.0) -> "Polygon":  # Build a rotated centered rectangle.
        hw, hh = width / 2, height / 2  # Compute half extents.
        corners = [  # Start with the unrotated corner offsets.
            Vector2D(-hw, -hh),  # Bottom-left.
            Vector2D(hw, -hh),  # Bottom-right.
            Vector2D(hw, hh),  # Top-right.
            Vector2D(-hw, hh),  # Top-left.
        ]  # Finish the offset list.
        radians = math.radians(rotation)  # Convert the rotation to radians.
        cosine, sine = math.cos(radians), math.sin(radians)  # Precompute the trig values.
        rotated: List[Vector2D] = []  # Collect the rotated corners.
        for corner in corners:  # Walk every corner offset.
            rotated.append(  # Apply the screen-space rotation and translation.
                Vector2D(x + corner.x * cosine - corner.y * sine, y + corner.x * sine + corner.y * cosine)  # Rotated corner.
            )  # Append the rotated corner.
        return cls(vertices=rotated)  # Return the rotated rectangle polygon.

    def edges(self) -> Iterator[Tuple[Vector2D, Vector2D]]:  # Iterate edges as start/end pairs.
        count = len(self.vertices)  # Read the vertex count.
        for index in range(count):  # Walk every vertex.
            yield self.vertices[index], self.vertices[(index + 1) % count]  # Yield the edge pair.

    def perimeter(self) -> float:  # Compute the polygon perimeter.
        return sum((end - start).magnitude() for start, end in self.edges())  # Return the total edge length.

    def contains_point(self, point: Vector2D) -> bool:  # Ray-casting point-in-polygon test.
        count = len(self.vertices)  # Read the vertex count.
        inside = False  # Initialize the inside flag.
        previous = count - 1  # Start with the last vertex.
        for index in range(count):  # Walk every vertex.
            current_vertex, previous_vertex = self.vertices[index], self.vertices[previous]  # Read the edge endpoints.
            if (current_vertex.y > point.y) != (previous_vertex.y > point.y):  # Skip non-crossing edges.
                crossing_x = (previous_vertex.x - current_vertex.x) * (point.y - current_vertex.y) / (previous_vertex.y - current_vertex.y) + current_vertex.x  # Compute the crossing X.
                if point.x < crossing_x:  # Detect a ray crossing.
                    inside = not inside  # Flip the inside flag.
            previous = index  # Advance the previous vertex.
        return inside  # Return the inside result.


@dataclass
class PlacementConfig:  # Physics and convergence parameters (trimmed port of kicad-tools PlacementConfig).
    """Configuration for the force-directed placement optimizer."""

    charge_density: float = 100.0  # Charge per mm of component edge.
    min_distance: float = 0.5  # Minimum force distance preventing singularities.
    edge_samples: int = 3  # Samples per edge for edge-to-edge repulsion.
    repulsion_cutoff: float = 60.0  # Skip repulsion pairs farther apart than this center distance.
    spring_stiffness: float = 10.0  # Default net spring constant.
    power_net_stiffness: float = 5.0  # Softer springs for power nets.
    clock_net_stiffness: float = 20.0  # Stiffer springs for clock nets.
    damping: float = 0.85  # Linear velocity damping factor.
    angular_damping: float = 0.80  # Angular velocity damping factor.
    max_velocity: float = 10.0  # Maximum linear velocity in mm per step.
    max_force: float = 0.0  # Maximum net force; zero auto-scales from the boundary perimeter.
    rotation_stiffness: float = 10.0  # Torsion spring stiffness toward 90-degree wells.
    boundary_charge: float = 200.0  # Extra charge carried by page boundary edges.
    boundary_margin: float = 2.54  # Minimum distance between component outlines and the page boundary.
    auto_scale_boundary: bool = True  # Scale boundary charge with component density.
    energy_threshold: float = 0.01  # Stop when system energy falls below this value.
    velocity_threshold: float = 0.001  # Stop when the maximum velocity falls below this value.
    position_grid: float = 1.27  # Placement grid in mm.
    rotation_grid: float = 90.0  # Rotation grid in degrees.


@dataclass
class PlacePin:  # A pin carried by one placed component.
    """A component pin with local screen-space offsets from the symbol origin."""

    number: str  # Pin number used to match net springs.
    offset_x: float  # Local X offset in schematic screen space.
    offset_y: float  # Local Y offset in schematic screen space.

    def world_position(self, origin: Vector2D, rotation: float) -> Vector2D:  # Compute the absolute screen position.
        radians = math.radians(rotation)  # Convert the rotation to radians.
        cosine, sine = math.cos(radians), math.sin(radians)  # Precompute trig values.
        return Vector2D(  # Apply the screen-space rotation and translation.
            origin.x + self.offset_x * cosine - self.offset_y * sine,  # Rotated X coordinate.
            origin.y + self.offset_x * sine + self.offset_y * cosine,  # Rotated Y coordinate.
        )  # Return the absolute position.


@dataclass
class PlaceComponent:  # A placeable schematic symbol body with physics state.
    """A component model carrying position, rotation, pins, and velocities."""

    ref: str  # Reference designator.
    x: float = 0.0  # Symbol origin X in schematic space.
    y: float = 0.0  # Symbol origin Y in schematic space.
    rotation: float = 0.0  # Current rotation in degrees.
    width: float = 5.08  # Body width in mm.
    height: float = 5.08  # Body height in mm.
    pins: List[PlacePin] = field(default_factory=list)  # Pins attached to the symbol.
    fixed: bool = False  # Fixed components do not move.
    mass: float = 1.0  # Physics mass.
    vx: float = 0.0  # Linear velocity X.
    vy: float = 0.0  # Linear velocity Y.
    angular_velocity: float = 0.0  # Angular velocity in degrees per step.

    def position(self) -> Vector2D:  # Return the origin position vector.
        return Vector2D(self.x, self.y)  # Build the position vector.

    def outline(self) -> Polygon:  # Build the current rotated body polygon.
        return Polygon.from_rotated_rectangle(self.x, self.y, self.width, self.height, self.rotation)  # Return the body outline.

    def pin_position(self, pin_number: str) -> Optional[Vector2D]:  # Resolve one pin's absolute position.
        for pin in self.pins:  # Walk the component pins.
            if pin.number == pin_number:  # Match the requested pin number.
                return pin.world_position(self.position(), self.rotation)  # Return the absolute pin position.
        return None  # Return None when the pin does not exist.

    def apply_force(self, force: Vector2D, dt: float) -> None:  # Integrate one linear force.
        if self.fixed:  # Skip fixed components.
            return  # Leave the velocity unchanged.
        self.vx += force.x / self.mass * dt  # Update the X velocity.
        self.vy += force.y / self.mass * dt  # Update the Y velocity.

    def apply_torque(self, torque: float, dt: float) -> None:  # Integrate one rotational torque.
        if self.fixed:  # Skip fixed components.
            return  # Leave the angular velocity unchanged.
        inertia = self.mass * (self.width**2 + self.height**2) / 12  # Moment of inertia for the rectangular body.
        self.angular_velocity += torque / inertia * dt  # Update the angular velocity.

    def update_position(self, dt: float) -> None:  # Advance position and rotation from velocities.
        if self.fixed:  # Skip fixed components.
            return  # Leave the pose unchanged.
        self.x += self.vx * dt  # Update the X coordinate.
        self.y += self.vy * dt  # Update the Y coordinate.
        if abs(self.angular_velocity) > 15.0:  # Clamp the angular velocity magnitude.
            self.angular_velocity = math.copysign(15.0, self.angular_velocity)  # Clamp to the maximum.
        self.rotation = (self.rotation + self.angular_velocity * dt) % 360  # Update and wrap the rotation.

    def apply_damping(self, linear: float, angular: float) -> None:  # Apply velocity damping.
        self.vx *= linear  # Damp the X velocity.
        self.vy *= linear  # Damp the Y velocity.
        self.angular_velocity *= angular  # Damp the angular velocity.

    def rotation_potential_torque(self, stiffness: float) -> float:  # Restoring torque toward 90-degree wells.
        if self.fixed:  # Skip fixed components.
            return 0.0  # Return zero torque.
        return -stiffness * math.sin(math.radians(self.rotation * 4))  # Return the torsion torque.

    def rotation_potential_energy(self, stiffness: float) -> float:  # Torsion potential energy.
        return stiffness * (1 - math.cos(math.radians(self.rotation * 4)))  # Return the well energy.


@dataclass
class PlaceSpring:  # A Hooke-law spring between two pins.
    """A spring connecting two pins on the same net."""

    comp1_ref: str  # First component reference.
    pin1_num: str  # First pin number.
    comp2_ref: str  # Second component reference.
    pin2_num: str  # Second pin number.
    stiffness: float = 1.0  # Spring constant.
    rest_length: float = 0.0  # Natural length.


class ForceDirectedPlacer:  # Force-directed placement engine (ported physics core).
    """Optimize schematic symbol placement using a physics simulation.

    Component bodies repel each other through sampled charged edges, net
    connections pull pins together through springs, the page boundary
    repels and clamps bodies, and a torsion potential snaps rotations to
    90 degrees.  Call :meth:`run` until convergence and then
    :meth:`snap_to_grid` to finalize discrete schematic poses.
    """

    def __init__(  # Initialize the placement engine.
        self,  # Accept the instance.
        boundary_width: float,  # Page boundary width in mm.
        boundary_height: float,  # Page boundary height in mm.
        config: Optional[PlacementConfig] = None,  # Accept optional physics parameters.
    ) -> None:  # Return nothing.
        self.config = config or PlacementConfig()  # Store the physics configuration.
        self.boundary = Polygon.rectangle(boundary_width / 2, boundary_height / 2, boundary_width, boundary_height)  # Build the page boundary.
        self.components: List[PlaceComponent] = []  # Collect placed components.
        self.springs: List[PlaceSpring] = []  # Collect net springs.
        self._component_map: Dict[str, PlaceComponent] = {}  # Index components by reference.

    def add_component(  # Register one component.
        self,  # Accept the instance.
        ref: str,  # Reference designator.
        x: float,  # Initial origin X.
        y: float,  # Initial origin Y.
        width: float,  # Body width in mm.
        height: float,  # Body height in mm.
        pins: Sequence[Tuple[str, float, float]] = (),  # Pins as (number, offset_x, offset_y) tuples.
    ) -> None:  # Return nothing.
        component = PlaceComponent(  # Build the component record.
            ref=ref,  # Store the reference.
            x=x,  # Store the initial X.
            y=y,  # Store the initial Y.
            width=width,  # Store the body width.
            height=height,  # Store the body height.
            pins=[PlacePin(number=pin_number, offset_x=offset_x, offset_y=offset_y) for pin_number, offset_x, offset_y in pins],  # Convert the pin tuples.
        )  # Finish the component record.
        self.components.append(component)  # Append the component.
        self._component_map[ref] = component  # Index the component.

    def get_component(self, ref: str) -> Optional[PlaceComponent]:  # Look up one placed component by reference.
        return self._component_map.get(ref)  # Return the component or None.

    def create_springs_from_nets(  # Create star-topology springs for every net.
        self,  # Accept the instance.
        net_pins: Dict[str, Sequence[Tuple[str, str]]],  # Map net names onto (reference, pin number) pairs.
    ) -> None:  # Return nothing.
        for net_name, pins in net_pins.items():  # Walk every net.
            if len(pins) < 2:  # Skip single-pin nets because they carry no attraction.
                continue  # Move to the next net.
            stiffness = self._net_stiffness(net_name)  # Resolve the net-specific spring constant.
            first_ref, first_pin = pins[0]  # Read the star center pin.
            for other_ref, other_pin in pins[1:]:  # Walk the remaining pins.
                self.springs.append(  # Create one star arm.
                    PlaceSpring(  # Build the spring record.
                        comp1_ref=first_ref,  # Store the center component.
                        pin1_num=first_pin,  # Store the center pin.
                        comp2_ref=other_ref,  # Store the spoke component.
                        pin2_num=other_pin,  # Store the spoke pin.
                        stiffness=stiffness,  # Store the net stiffness.
                        rest_length=0.0,  # Nets want zero length.
                    )  # Finish the spring record.
                )  # Append the spring to the list.

    def _net_stiffness(self, net_name: str) -> float:  # Resolve the spring stiffness for one net name.
        lowered = net_name.lower()  # Normalize the net name.
        if any(token in lowered for token in ("clk", "clock", "mclk", "sclk", "bclk", "xtal")):  # Detect clock nets.
            return self.config.clock_net_stiffness  # Return the stiffer clock constant.
        if any(token in lowered for token in ("vcc", "vdd", "gnd", "+3", "+5", "+12", "-12", "pwr", "v+", "v-")):  # Detect power nets.
            return self.config.power_net_stiffness  # Return the softer power constant.
        return self.config.spring_stiffness  # Return the default constant.

    def compute_edge_to_point_force(  # Compute the repulsion of one point from one charged segment.
        self,  # Accept the instance.
        point: Vector2D,  # The test point.
        edge_start: Vector2D,  # Segment start.
        edge_end: Vector2D,  # Segment end.
        charge_density: float,  # Linear charge density.
    ) -> Vector2D:  # Return the force vector.
        edge = edge_end - edge_start  # Compute the edge vector.
        edge_len = edge.magnitude()  # Compute the edge length.
        if edge_len < 1e-10:  # Skip degenerate edges.
            return Vector2D(0.0, 0.0)  # Return zero force.
        to_point = point - edge_start  # Vector from the edge start to the point.
        t = max(0.0, min(1.0, to_point.dot(edge) / (edge_len * edge_len)))  # Project the point onto the segment.
        closest = edge_start + edge * t  # Compute the closest point on the segment.
        displacement = point - closest  # Vector from the closest point to the test point.
        distance = max(displacement.magnitude(), self.config.min_distance)  # Clamp the distance against singularities.
        force_mag = charge_density * edge_len / (distance * distance)  # Line-charge 1/r^2 falloff magnitude.
        return displacement.normalized() * force_mag  # Return the directed force.

    def compute_edge_to_edge_force(  # Compute the sampled force between two charged edges.
        self,  # Accept the instance.
        edge1_start: Vector2D,  # Receiving edge start.
        edge1_end: Vector2D,  # Receiving edge end.
        edge2_start: Vector2D,  # Source edge start.
        edge2_end: Vector2D,  # Source edge end.
    ) -> Vector2D:  # Return the net force on the receiving edge.
        edge1 = edge1_end - edge1_start  # Compute the receiving edge vector.
        edge1_len = edge1.magnitude()  # Compute the receiving edge length.
        if edge1_len < 1e-10:  # Skip degenerate receiving edges.
            return Vector2D(0.0, 0.0)  # Return zero force.
        num_samples = self.config.edge_samples  # Read the sample count.
        total_force = Vector2D(0.0, 0.0)  # Accumulate the sampled forces.
        for index in range(num_samples):  # Walk the sample positions.
            t = (index + 0.5) / num_samples  # Compute the sample parameter.
            sample_point = edge1_start + edge1 * t  # Compute the sample point.
            sample_charge = self.config.charge_density * edge1_len / num_samples  # Distribute the edge charge over the samples.
            total_force = total_force + self.compute_edge_to_point_force(sample_point, edge2_start, edge2_end, sample_charge)  # Accumulate the sample force.
        return total_force  # Return the sampled net force.

    def _effective_boundary_charge(self) -> float:  # Auto-scale the boundary charge with component density.
        charge = self.config.boundary_charge  # Start with the configured charge.
        if self.config.auto_scale_boundary:  # Apply density scaling when enabled.
            movable_count = sum(1 for component in self.components if not component.fixed)  # Count movable components.
            charge *= max(1.0, movable_count / 20.0)  # Scale the charge with the component density.
        return charge  # Return the effective boundary charge.

    def _compute_max_force(self) -> float:  # Resolve the force clamp limit.
        if self.config.max_force > 0:  # Use an explicit clamp when configured.
            return self.config.max_force  # Return the configured clamp.
        return self.config.boundary_charge * self.boundary.perimeter() / 4  # Auto-scale from the boundary perimeter.

    def compute_forces_and_torques(self) -> Tuple[Dict[str, Vector2D], Dict[str, float]]:  # Compute net forces and torques on every component.
        positions = np.asarray([(component.x, component.y) for component in self.components], dtype=np.float64)  # Pack component centers.
        rotations = np.asarray([component.rotation for component in self.components], dtype=np.float64)  # Pack component rotations.
        widths = np.asarray([component.width for component in self.components], dtype=np.float64)  # Pack component widths.
        heights = np.asarray([component.height for component in self.components], dtype=np.float64)  # Pack component heights.
        fixed = np.asarray([component.fixed for component in self.components], dtype=np.bool_)  # Pack fixed-state flags.
        boundary_scale = self._effective_boundary_charge() / self.config.charge_density  # Compute the boundary force scale.
        boundary_width = max(vertex.x for vertex in self.boundary.vertices) - min(vertex.x for vertex in self.boundary.vertices)  # Measure page width.
        boundary_height = max(vertex.y for vertex in self.boundary.vertices) - min(vertex.y for vertex in self.boundary.vertices)  # Measure page height.
        body_forces, body_torques = _compiled_body_forces(positions, rotations, widths, heights, fixed, boundary_width, boundary_height, self.config.charge_density, self.config.min_distance, self.config.edge_samples, self.config.repulsion_cutoff, boundary_scale, self.config.rotation_stiffness)  # Compute repulsion in compiled code.
        forces: Dict[str, Vector2D] = {component.ref: Vector2D(float(body_forces[index, 0]), float(body_forces[index, 1])) for index, component in enumerate(self.components)}  # Convert compiled forces into the model mapping.
        torques: Dict[str, float] = {component.ref: float(body_torques[index]) for index, component in enumerate(self.components)}  # Convert compiled torques into the model mapping.
        for spring in self.springs:  # Walk every net spring.
            component1 = self._component_map.get(spring.comp1_ref)  # Resolve the first component.
            component2 = self._component_map.get(spring.comp2_ref)  # Resolve the second component.
            if component1 is None or component2 is None:  # Skip springs referencing unknown components.
                continue  # Move to the next spring.
            position1 = component1.pin_position(spring.pin1_num)  # Resolve the first pin position.
            position2 = component2.pin_position(spring.pin2_num)  # Resolve the second pin position.
            if position1 is None or position2 is None:  # Skip springs with missing pins.
                continue  # Move to the next spring.
            delta = position2 - position1  # Vector from pin one to pin two.
            distance = delta.magnitude()  # Compute the pin separation.
            if distance < 1e-10:  # Skip degenerate springs.
                continue  # Move to the next spring.
            force_magnitude = spring.stiffness * (distance - spring.rest_length)  # Hooke's law magnitude.
            direction = delta.normalized()  # Unit direction from pin one to pin two.
            force1 = direction * force_magnitude  # Force on component one.
            if not component1.fixed:  # Apply the force to the first component.
                forces[component1.ref] = forces[component1.ref] + force1  # Accumulate the spring force.
                torques[component1.ref] += (position1 - component1.position()).cross(force1)  # Accumulate the spring torque.
            if not component2.fixed:  # Apply the reaction to the second component.
                forces[component2.ref] = forces[component2.ref] - force1  # Accumulate the reaction force.
                torques[component2.ref] += (position2 - component2.position()).cross(-force1)  # Accumulate the reaction torque.
        return forces, torques  # Return the net forces and torques.

    def compute_energy(self) -> float:  # Compute the total system energy.
        kinetic = 0.0  # Accumulate kinetic energy.
        for component in self.components:  # Walk every component.
            if component.fixed:  # Skip fixed components.
                continue  # Move to the next component.
            kinetic += 0.5 * component.mass * (component.vx**2 + component.vy**2)  # Accumulate linear kinetic energy.
            inertia = component.mass * (component.width**2 + component.height**2) / 12  # Compute the moment of inertia.
            kinetic += 0.5 * inertia * math.radians(component.angular_velocity) ** 2  # Accumulate rotational kinetic energy.
        potential = 0.0  # Accumulate potential energy.
        for spring in self.springs:  # Walk every spring.
            component1 = self._component_map.get(spring.comp1_ref)  # Resolve the first component.
            component2 = self._component_map.get(spring.comp2_ref)  # Resolve the second component.
            position1 = component1.pin_position(spring.pin1_num) if component1 is not None else None  # Resolve the first pin.
            position2 = component2.pin_position(spring.pin2_num) if component2 is not None else None  # Resolve the second pin.
            if position1 is None or position2 is None:  # Skip springs with missing pins.
                continue  # Move to the next spring.
            extension = (position2 - position1).magnitude() - spring.rest_length  # Compute the spring extension.
            potential += 0.5 * spring.stiffness * extension * extension  # Accumulate the spring potential.
        for component in self.components:  # Walk every component.
            if not component.fixed:  # Skip fixed components.
                potential += component.rotation_potential_energy(self.config.rotation_stiffness)  # Accumulate the torsion potential.
        return kinetic + potential  # Return the total energy.

    def step(self, dt: float) -> None:  # Run one physics simulation step.
        forces, torques = self.compute_forces_and_torques()  # Compute the net forces and torques.
        max_force = self._compute_max_force()  # Resolve the force clamp limit.
        for component in self.components:  # Walk every component.
            if component.fixed:  # Skip fixed components.
                continue  # Move to the next component.
            force = forces[component.ref]  # Read the net force.
            force_magnitude = force.magnitude()  # Compute the force magnitude.
            if force_magnitude > max_force:  # Clamp the net force.
                force = force * (max_force / force_magnitude)  # Scale the force to the clamp.
            component.apply_force(force, dt)  # Integrate the linear force.
            component.apply_torque(torques[component.ref], dt)  # Integrate the rotational torque.
            speed = math.sqrt(component.vx**2 + component.vy**2)  # Compute the linear speed.
            if speed > self.config.max_velocity:  # Clamp the linear velocity.
                scale = self.config.max_velocity / speed  # Compute the velocity scale.
                component.vx *= scale  # Clamp the X velocity.
                component.vy *= scale  # Clamp the Y velocity.
            component.apply_damping(self.config.damping, self.config.angular_damping)  # Apply velocity damping.
        min_x = min(vertex.x for vertex in self.boundary.vertices)  # Read the boundary minimum X.
        max_x = max(vertex.x for vertex in self.boundary.vertices)  # Read the boundary maximum X.
        min_y = min(vertex.y for vertex in self.boundary.vertices)  # Read the boundary minimum Y.
        max_y = max(vertex.y for vertex in self.boundary.vertices)  # Read the boundary maximum Y.
        for component in self.components:  # Walk every component for position clamping.
            if component.fixed:  # Skip fixed components.
                continue  # Move to the next component.
            component.update_position(dt)  # Advance the pose from the velocities.
            half_w = component.width / 2 + self.config.boundary_margin  # Compute the X clamp half-extent.
            half_h = component.height / 2 + self.config.boundary_margin  # Compute the Y clamp half-extent.
            low_x, high_x = min_x + half_w, max_x - half_w  # Compute the X clamp bounds.
            low_y, high_y = min_y + half_h, max_y - half_h  # Compute the Y clamp bounds.
            if low_x > high_x:  # Collapse inverted clamp boxes defensively.
                low_x = high_x = (min_x + max_x) / 2  # Clamp to the boundary center.
            if low_y > high_y:  # Collapse inverted clamp boxes defensively.
                low_y = high_y = (min_y + max_y) / 2  # Clamp to the boundary center.
            component.x = max(low_x, min(high_x, component.x))  # Clamp the X coordinate.
            component.y = max(low_y, min(high_y, component.y))  # Clamp the Y coordinate.
            if component.x <= low_x or component.x >= high_x:  # Kill outward velocity at the X walls.
                component.vx = 0.0  # Zero the X velocity.
            if component.y <= low_y or component.y >= high_y:  # Kill outward velocity at the Y walls.
                component.vy = 0.0  # Zero the Y velocity.

    def run(self, iterations: int = 200, dt: float = 0.01) -> int:  # Run the simulation until convergence or the iteration cap.
        for index in range(iterations):  # Walk the iteration budget.
            self.step(dt)  # Run one physics step.
            energy = self.compute_energy()  # Compute the total system energy.
            max_velocity = 0.0  # Track the maximum remaining velocity.
            for component in self.components:  # Walk every component.
                if not component.fixed:  # Skip fixed components.
                    max_velocity = max(max_velocity, math.sqrt(component.vx**2 + component.vy**2))  # Update the maximum velocity.
            if energy < self.config.energy_threshold and max_velocity < self.config.velocity_threshold:  # Detect convergence.
                return index + 1  # Return the converged iteration count.
        return iterations  # Return the exhausted iteration count.

    def snap_to_grid(self, position_grid: Optional[float] = None, rotation_grid: Optional[float] = None) -> None:  # Snap poses onto the discrete placement grids.
        position_grid = position_grid or self.config.position_grid  # Resolve the position grid.
        rotation_grid = rotation_grid if rotation_grid is not None else self.config.rotation_grid  # Resolve the rotation grid.
        for component in self.components:  # Walk every component.
            if component.fixed:  # Skip fixed components.
                continue  # Move to the next component.
            if position_grid > 0:  # Snap positions when a grid is configured.
                component.x = round(component.x / position_grid) * position_grid  # Snap the X coordinate.
                component.y = round(component.y / position_grid) * position_grid  # Snap the Y coordinate.
                component.vx = 0.0  # Zero the X velocity.
                component.vy = 0.0  # Zero the Y velocity.
            if rotation_grid > 0:  # Snap rotations when a grid is configured.
                component.rotation = round(component.rotation / rotation_grid) * rotation_grid % 360  # Snap the rotation angle.
                component.angular_velocity = 0.0  # Zero the angular velocity.
