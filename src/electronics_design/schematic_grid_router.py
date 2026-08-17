"""Grid-based A* schematic wire routing.

This module is a self-contained port of the grid-routing essentials from the
MIT-licensed `kicad-tools` project (`src/kicad_tools/router/grid.py` and
`src/kicad_tools/router/pathfinder.py`, Copyright (c) 2024 RJ Walters).  No
kicad-tools dependency is used; the algorithm code is copied and adapted so
that `ltspice_netlist_to_kicad_sch` can route schematic wires with the same
approach kicad-tools uses for PCB tracks:

- A rectangular routing grid backed by a NumPy blocked bitmap.
- A* search over grid cells using a binary heap, g-score arrays, a
  Manhattan heuristic, and direction-aware turn penalties.
- Net ownership per cell: routed cells block foreign nets, and a relaxed
  (soft) mode lets a stuck net cross foreign cells at high cost.
- Path reconstruction compresses collinear cells into axis-aligned wire
  segments in world coordinates.

The public entry point used by the conversion pipeline is
:class:`GridRouter`.
"""

from __future__ import annotations  # Postpone annotation evaluation for forward references.

import heapq  # Priority queue for the A* open set.
import math  # Compute heuristic distances.
from typing import Dict  # Type ownership lookups.
from typing import List  # Type collected paths and segments.
from typing import Optional  # Type optional routing results.
from typing import Sequence  # Type immutable point sequences.
from typing import Set  # Type visited and goal cell sets.
from typing import Tuple  # Type coordinate tuples.

import numpy as np  # Back the blocked bitmap and cost arrays.
from numba import njit  # Compile the per-cell A* search kernel.

__all__ = ["GridRouter"]  # Export the public routing API.

Point = Tuple[float, float]  # Represent one world coordinate pair.
Cell = Tuple[int, int]  # Represent one grid cell coordinate pair.

@njit(cache=True)
def _nearest_goal_distance(cell_x: int, cell_y: int, goal_cells: np.ndarray) -> float:  # Compute the nearest-goal Manhattan heuristic in compiled code.
    best = 1.0e30  # Start above every possible page-grid distance.
    for index in range(goal_cells.shape[0]):  # Walk the remaining terminals.
        distance = abs(cell_x - goal_cells[index, 0]) + abs(cell_y - goal_cells[index, 1])  # Compute Manhattan distance.
        if distance < best:  # Keep the closest terminal.
            best = float(distance)  # Store the improved heuristic.
    return best  # Return the admissible nearest-goal estimate.


@njit(cache=True)
def _astar_grid_kernel(  # Run multi-source, multi-goal A* over array-backed routing state.
    blocked: np.ndarray,
    owner_grid: np.ndarray,
    pin_mask: np.ndarray,
    start_cells: np.ndarray,
    goal_cells: np.ndarray,
    net_id: int,
    soft: bool,
    turn_penalty: float,
    soft_foreign_penalty: float,
) -> np.ndarray:
    rows, cols = blocked.shape  # Read the grid dimensions.
    no_direction = 4  # Reserve direction state four for a multi-source root.
    g_scores = np.full((5, rows, cols), np.inf, dtype=np.float64)  # Track costs separately by arrival direction.
    closed = np.zeros((5, rows, cols), dtype=np.bool_)  # Track expanded direction states.
    parent_x = np.full((5, rows, cols), -2, dtype=np.int32)  # Store parent X coordinates.
    parent_y = np.full((5, rows, cols), -2, dtype=np.int32)  # Store parent Y coordinates.
    parent_direction = np.full((5, rows, cols), -2, dtype=np.int8)  # Store parent arrival directions.
    goal_mask = np.zeros((rows, cols), dtype=np.bool_)  # Mark terminal cells for constant-time goal checks.
    for index in range(goal_cells.shape[0]):  # Walk every remaining terminal.
        goal_x, goal_y = goal_cells[index, 0], goal_cells[index, 1]  # Read its cell.
        if 0 <= goal_x < cols and 0 <= goal_y < rows:  # Keep only in-bounds terminals.
            goal_mask[goal_y, goal_x] = True  # Mark the goal cell.
    heap = [(0.0, 0, 0.0, 0, 0, 0)]  # Seed tuple typing for Numba's heap implementation.
    heap.pop()  # Remove the typing sentinel before adding real sources.
    sequence = 0  # Supply deterministic tie-breaking.
    for index in range(start_cells.shape[0]):  # Seed every cell in the existing net tree.
        start_x, start_y = start_cells[index, 0], start_cells[index, 1]  # Read the source cell.
        if not (0 <= start_x < cols and 0 <= start_y < rows):  # Skip invalid sources.
            continue  # Move to the next source.
        if g_scores[no_direction, start_y, start_x] == 0.0:  # Skip duplicate sources.
            continue  # Move to the next source.
        g_scores[no_direction, start_y, start_x] = 0.0  # Seed the source cost.
        parent_x[no_direction, start_y, start_x] = -1  # Mark the source as a reconstruction root.
        heuristic = _nearest_goal_distance(start_x, start_y, goal_cells)  # Compute its initial heuristic.
        heapq.heappush(heap, (heuristic, sequence, 0.0, np.int64(start_x), np.int64(start_y), np.int64(no_direction)))  # Push the source state.
        sequence += 1  # Advance the tie-break sequence.
    max_iterations = cols * rows * 8  # Bound work while allowing direction-state revisits.
    iterations = 0  # Count expanded heap states.
    while heap and iterations < max_iterations:  # Run the compiled A* loop.
        _f_score, _entry_sequence, current_g, current_x, current_y, direction = heapq.heappop(heap)  # Pop the cheapest state.
        if closed[direction, current_y, current_x]:  # Skip stale heap entries.
            continue  # Move to the next entry.
        closed[direction, current_y, current_x] = True  # Close this direction state.
        iterations += 1  # Count the expansion.
        if goal_mask[current_y, current_x]:  # Reconstruct when any remaining terminal is reached.
            length = 1  # Count the goal cell itself.
            walk_x, walk_y, walk_direction = current_x, current_y, direction  # Start at the goal state.
            while parent_x[walk_direction, walk_y, walk_x] >= 0:  # Walk to one of the multi-source roots.
                next_x = parent_x[walk_direction, walk_y, walk_x]  # Read the parent X.
                next_y = parent_y[walk_direction, walk_y, walk_x]  # Read the parent Y.
                next_direction = parent_direction[walk_direction, walk_y, walk_x]  # Read the parent direction.
                walk_x, walk_y, walk_direction = next_x, next_y, next_direction  # Advance to the parent state.
                length += 1  # Count the parent cell.
            path = np.empty((length, 2), dtype=np.int32)  # Allocate the source-to-goal path.
            walk_x, walk_y, walk_direction = current_x, current_y, direction  # Restart at the goal.
            output_index = length - 1  # Fill the array backwards.
            while output_index >= 0:  # Emit every reconstructed cell.
                path[output_index, 0] = walk_x  # Store X.
                path[output_index, 1] = walk_y  # Store Y.
                if output_index == 0:  # Stop after writing the source root.
                    break  # Finish reconstruction.
                next_x = parent_x[walk_direction, walk_y, walk_x]  # Read the parent X.
                next_y = parent_y[walk_direction, walk_y, walk_x]  # Read the parent Y.
                next_direction = parent_direction[walk_direction, walk_y, walk_x]  # Read the parent direction.
                walk_x, walk_y, walk_direction = next_x, next_y, next_direction  # Advance to the parent.
                output_index -= 1  # Move backwards in the output array.
            return path  # Return the successful cell path.
        for next_direction in range(4):  # Walk the four orthogonal neighbors.
            if next_direction == 0:  # Move right.
                neighbor_x, neighbor_y = current_x + 1, current_y  # Compute the neighbor.
            elif next_direction == 1:  # Move left.
                neighbor_x, neighbor_y = current_x - 1, current_y  # Compute the neighbor.
            elif next_direction == 2:  # Move down.
                neighbor_x, neighbor_y = current_x, current_y + 1  # Compute the neighbor.
            else:  # Move up.
                neighbor_x, neighbor_y = current_x, current_y - 1  # Compute the neighbor.
            if not (0 <= neighbor_x < cols and 0 <= neighbor_y < rows):  # Reject out-of-bounds cells.
                continue  # Move to the next direction.
            owner = owner_grid[neighbor_y, neighbor_x]  # Read obstacle or net ownership.
            if blocked[neighbor_y, neighbor_x] and owner != net_id:  # Resolve foreign occupancy.
                if pin_mask[neighbor_y, neighbor_x] or owner < 0 or not soft:  # Keep pins and plain obstacles hard-blocked.
                    continue  # Reject the neighbor.
            step_cost = 1.0  # Start with the unit grid movement cost.
            if blocked[neighbor_y, neighbor_x] and owner != net_id:  # Penalize an allowed soft foreign crossing.
                step_cost += soft_foreign_penalty  # Add the high sharing cost.
            if direction != no_direction and direction != next_direction:  # Penalize a bend.
                step_cost += turn_penalty  # Add the turn cost.
            tentative_g = current_g + step_cost  # Compute the candidate path cost.
            if tentative_g >= g_scores[next_direction, neighbor_y, neighbor_x]:  # Skip non-improving arrivals.
                continue  # Move to the next direction.
            g_scores[next_direction, neighbor_y, neighbor_x] = tentative_g  # Store the improved cost.
            parent_x[next_direction, neighbor_y, neighbor_x] = current_x  # Store the parent X.
            parent_y[next_direction, neighbor_y, neighbor_x] = current_y  # Store the parent Y.
            parent_direction[next_direction, neighbor_y, neighbor_x] = direction  # Store the parent direction.
            heuristic = _nearest_goal_distance(neighbor_x, neighbor_y, goal_cells)  # Estimate the remaining cost.
            heapq.heappush(heap, (tentative_g + heuristic, sequence, tentative_g, np.int64(neighbor_x), np.int64(neighbor_y), np.int64(next_direction)))  # Push the improved state.
            sequence += 1  # Advance the tie-break sequence.
    return np.empty((0, 2), dtype=np.int32)  # Return an empty path on failure.


class GridRouter:  # A* router over a single-layer world grid (ported core).
    """Route axis-aligned wires on a grid while avoiding obstacles and foreign nets.

    Cells carry an owner net id; cells owned by another net are blocked for
    new routes by default.  ``route`` returns world-space wire segments that
    always include the exact terminal points, adding short orthogonal
    approach stubs when a terminal is off-grid.
    """

    def __init__(  # Initialize the routing grid.
        self,  # Accept the instance.
        resolution: float,  # Grid resolution in world units (mm).
        origin_x: float,  # World X of the grid's minimum corner.
        origin_y: float,  # World Y of the grid's minimum corner.
        width: float,  # Routing area width in world units.
        height: float,  # Routing area height in world units.
    ) -> None:  # Return nothing.
        self.resolution = float(resolution)  # Store the grid resolution.
        self.origin_x = float(origin_x)  # Store the grid origin X.
        self.origin_y = float(origin_y)  # Store the grid origin Y.
        self.cols = max(1, int(math.ceil(width / self.resolution)) + 1)  # Compute the column count.
        self.rows = max(1, int(math.ceil(height / self.resolution)) + 1)  # Compute the row count.
        self.blocked = np.zeros((self.rows, self.cols), dtype=np.bool_)  # Hard obstacle bitmap.
        self.owner_grid = np.zeros((self.rows, self.cols), dtype=np.int32)  # Array-backed ownership for the compiled A* kernel; -1 means a plain obstacle.
        self.pin_mask = np.zeros((self.rows, self.cols), dtype=np.bool_)  # Array-backed foreign-pin exclusion mask.
        self.owner_net: Dict[Cell, int] = {}  # Map owned cells onto their net id.
        self.pin_cells: Set[Cell] = set()  # Pin cells that foreign nets may never traverse, even in soft mode.
        self.turn_penalty = 1.0  # Extra cost applied when the path changes direction.
        self.soft_foreign_penalty = 1000.0  # Cost multiplier for crossing foreign cells in soft mode.
        self.net_counter = 0  # Allocate sequential net ids.
        self.last_routed_cells: Optional[List[Cell]] = None  # Cell path of the most recent successful route.
        self.last_routed_sub_paths: Optional[List[List[Cell]]] = None  # Individual tree branches from the most recent successful route.

    def world_to_cell(self, x: float, y: float) -> Cell:  # Convert one world point onto its grid cell.
        cell_x = int(round((float(x) - self.origin_x) / self.resolution))  # Compute the column index.
        cell_y = int(round((float(y) - self.origin_y) / self.resolution))  # Compute the row index.
        return cell_x, cell_y  # Return the cell coordinates.

    def cell_to_world(self, cell_x: int, cell_y: int) -> Point:  # Convert one grid cell back to its world center.
        return (self.origin_x + cell_x * self.resolution, self.origin_y + cell_y * self.resolution)  # Return the world center point.

    def cell_in_bounds(self, cell_x: int, cell_y: int) -> bool:  # Check whether a cell lies inside the grid.
        return 0 <= cell_x < self.cols and 0 <= cell_y < self.rows  # Return the bounds result.

    def block_rectangle(self, x1: float, y1: float, x2: float, y2: float) -> None:  # Block the cells covered by one world rectangle.
        low_x, high_x = min(x1, x2), max(x1, x2)  # Normalize the X bounds.
        low_y, high_y = min(y1, y2), max(y1, y2)  # Normalize the Y bounds.
        start_cell = self.world_to_cell(low_x, low_y)  # Compute the first covered cell.
        end_cell = self.world_to_cell(high_x, high_y)  # Compute the last covered cell.
        for cell_y in range(max(0, start_cell[1]), min(self.rows - 1, end_cell[1]) + 1):  # Walk the covered rows.
            for cell_x in range(max(0, start_cell[0]), min(self.cols - 1, end_cell[0]) + 1):  # Walk the covered columns.
                self.blocked[cell_y, cell_x] = True  # Mark the cell as blocked.
                self.owner_grid[cell_y, cell_x] = -1  # Mark the cell as a plain obstacle.
                self.owner_net.pop((cell_x, cell_y), None)  # Drop any prior ownership.

    def block_cell(self, cell_x: int, cell_y: int, net_id: Optional[int] = None) -> None:  # Block one grid cell with optional net ownership.
        if not self.cell_in_bounds(cell_x, cell_y):  # Skip out-of-bounds cells.
            return  # Leave the bitmap unchanged.
        self.blocked[cell_y, cell_x] = True  # Mark the cell as blocked.
        if net_id is None:  # Keep ownership absent for plain obstacles.
            self.owner_grid[cell_y, cell_x] = -1  # Mark a plain obstacle in the compiled ownership grid.
            self.owner_net.pop((cell_x, cell_y), None)  # Drop any prior ownership.
        else:  # Record the owning net.
            self.owner_grid[cell_y, cell_x] = net_id  # Store ownership in the compiled grid.
            self.owner_net[(cell_x, cell_y)] = net_id  # Store the net ownership.

    def block_pin_cell(self, cell_x: int, cell_y: int, net_id: int) -> None:  # Block one pin cell that only its own net may ever enter.
        self.block_cell(cell_x, cell_y, net_id)  # Mark the cell with net ownership.
        if self.cell_in_bounds(cell_x, cell_y):  # Keep the array mask in bounds.
            self.pin_mask[cell_y, cell_x] = True  # Mark the pin cell for compiled hard exclusion.
        self.pin_cells.add((cell_x, cell_y))  # Record the pin cell for hard exclusion.

    def _find_cell_path(self, start_cells: Sequence[Cell], goal_cells: Set[Cell], net_id: int, soft: bool) -> Optional[List[Cell]]:  # A* search from any connected-tree cell to any remaining terminal.
        if not start_cells or not goal_cells:  # Reject empty endpoint sets defensively.
            return None  # Report that no path can be built.
        start_array = np.asarray(start_cells, dtype=np.int32)  # Convert sources for the compiled kernel.
        goal_array = np.asarray(sorted(goal_cells), dtype=np.int32)  # Sort and convert goals for deterministic compiled traversal.
        path_array = _astar_grid_kernel(self.blocked, self.owner_grid, self.pin_mask, start_array, goal_array, int(net_id), bool(soft), self.turn_penalty, self.soft_foreign_penalty)  # Run compiled A*.
        if path_array.shape[0] == 0:  # Detect routing failure.
            return None  # Report that no path exists.
        return [(int(row[0]), int(row[1])) for row in path_array]  # Convert the path back to Python cell tuples.

    def mark_cells(self, cells: Sequence[Cell], net_id: int) -> None:  # Claim one path's cells for a net without stealing foreign cells.
        for cell in cells:  # Walk the path cells.
            owner = self.owner_net.get(cell)  # Read the existing cell owner.
            if owner is not None and owner != net_id:  # Never overwrite foreign-owned cells.
                continue  # Leave the foreign cell untouched so sharing stays detectable.
            self.blocked[cell[1], cell[0]] = True  # Mark the cell as occupied.
            self.owner_grid[cell[1], cell[0]] = net_id  # Store ownership for compiled searches.
            self.owner_net[cell] = net_id  # Record the owning net.

    def unmark_cells(self, cells: Sequence[Cell], net_id: int) -> None:  # Release one path's cells.
        for cell in cells:  # Walk the path cells.
            if self.owner_net.get(cell) == net_id:  # Only release cells owned by this net.
                self.blocked[cell[1], cell[0]] = False  # Clear the occupancy flag.
                self.owner_grid[cell[1], cell[0]] = 0  # Clear compiled ownership.
                self.owner_net.pop(cell, None)  # Drop the ownership.

    def _compress_cells(self, cells: Sequence[Cell]) -> List[Point]:  # Compress collinear cells into corner points.
        points: List[Point] = []  # Collect the compressed polyline points.
        for cell in cells:  # Walk every path cell.
            points.append(self.cell_to_world(cell[0], cell[1]))  # Convert the cell to its world center.
        if len(points) <= 2:  # Short paths need no compression.
            return points  # Return the raw points.
        compressed: List[Point] = [points[0]]  # Start with the first point.
        for index in range(1, len(points) - 1):  # Walk the interior points.
            previous = compressed[-1]  # Read the last kept point.
            current = points[index]  # Read the current point.
            following = points[index + 1]  # Read the next point.
            same_x = abs(previous[0] - current[0]) < 1e-9 and abs(current[0] - following[0]) < 1e-9  # Detect a collinear vertical run.
            same_y = abs(previous[1] - current[1]) < 1e-9 and abs(current[1] - following[1]) < 1e-9  # Detect a collinear horizontal run.
            if not (same_x or same_y):  # Keep the corner point.
                compressed.append(current)  # Append the turning point.
        compressed.append(points[-1])  # Append the final point.
        return compressed  # Return the compressed point list.

    def _approach_stub(self, terminal: Point, cell: Cell) -> List[Point]:  # Build an orthogonal stub from an exact terminal to its grid cell center.
        grid_point = self.cell_to_world(cell[0], cell[1])  # Compute the grid cell center.
        if abs(terminal[0] - grid_point[0]) < 1e-9 and abs(terminal[1] - grid_point[1]) < 1e-9:  # Detect an on-grid terminal.
            return []  # No stub is required.
        return [terminal, (terminal[0], grid_point[1]), grid_point]  # Return the two-segment orthogonal jog.

    def route(self, terminals: Sequence[Point], net_id: Optional[int] = None, soft: bool = False) -> Optional[List[Tuple[Point, Point]]]:  # Route one multi-terminal net and return world segments.
        self.last_routed_cells = None  # Clear stale state before every routing attempt.
        self.last_routed_sub_paths = None  # Clear stale branch state before every routing attempt.
        if net_id is None:  # Allocate a fresh net id when none was supplied.
            net_id = self.net_counter  # Reuse the current counter.
            self.net_counter += 1  # Advance the counter.
        unique_cells: List[Cell] = []  # Collect distinct terminal cells.
        for terminal in terminals:  # Walk the terminal points.
            cell = self.world_to_cell(terminal[0], terminal[1])  # Convert the terminal to a grid cell.
            if cell not in unique_cells:  # Deduplicate coincident terminals.
                unique_cells.append(cell)  # Append the distinct cell.
        if len(unique_cells) < 2:  # Coincident-cell terminals connect with direct pin-to-pin segments.
            self.last_routed_cells = list(unique_cells)  # Record the trivial cell path.
            self.last_routed_sub_paths = [list(unique_cells)]  # Record the trivial branch.
            segments: List[Tuple[Point, Point]] = []  # Collect the direct connection segments.
            first = terminals[0]  # Read the first terminal point.
            for terminal in terminals[1:]:  # Walk the remaining terminal points.
                if (round(first[0], 6), round(first[1], 6)) != (round(terminal[0], 6), round(terminal[1], 6)):  # Skip exact duplicates.
                    segments.append((first, terminal))  # Append the direct connection segment.
            return segments  # Return the direct segments.
        routed_cells: List[Cell] = []  # Accumulate every cell claimed by this net.
        connected_cells: Set[Cell] = {unique_cells[0]}  # Seed the connected tree with the first terminal.
        connected_order: List[Cell] = [unique_cells[0]]  # Keep deterministic source ordering for the next search.
        remaining_cells: Set[Cell] = set(unique_cells[1:])  # Track the remaining terminals.
        sub_paths: List[List[Cell]] = []  # Keep every greedy connection as its own path.
        while remaining_cells:  # Grow the connection tree greedily.
            path = self._find_cell_path(connected_order, remaining_cells, net_id, soft)  # Connect the existing tree to the nearest reachable terminal in one A* search.
            if path is None:  # Abort when no terminal can be reached.
                return None  # Report the routing failure.
            sub_paths.append(path)  # Keep the connection as a standalone path.
            routed_cells.extend(path)  # Accumulate the routed cells.
            for cell in path:  # Add every cell of the path to the connected tree.
                if cell not in connected_cells:  # Only extend the deterministic order with new cells.
                    connected_order.append(cell)  # Append the new tree cell.
                connected_cells.add(cell)  # Extend the tree with the path cell.
            remaining_cells.discard(path[-1])  # Drop the terminal reached by this path.
        self.mark_cells(routed_cells, net_id)  # Claim the routed cells for this net.
        self.last_routed_cells = list(routed_cells)  # Record the routed cell path for ownership checks.
        self.last_routed_sub_paths = [list(path) for path in sub_paths]  # Preserve branch boundaries for exact corner checks.
        # Compress each greedy connection separately so no phantom jump segments appear between sub-paths.
        polylines: List[List[Point]] = [self._compress_cells(sub_path) for sub_path in sub_paths]  # Compress every sub-path independently.
        # Merge per-terminal approach stubs so every exact terminal lies on the wire.
        point_to_cell: Dict[Tuple[float, float], Cell] = {}  # Map rounded terminal coordinates onto cells.
        for terminal in terminals:  # Walk every terminal, including terminals sharing one cell.
            point_to_cell[(round(terminal[0], 6), round(terminal[1], 6))] = self.world_to_cell(terminal[0], terminal[1])  # Store its actual grid cell.
        stubs: List[List[Point]] = []  # Collect the approach stubs.
        for terminal in terminals:  # Walk the terminals again.
            stubs.append(self._approach_stub(terminal, point_to_cell[(round(terminal[0], 6), round(terminal[1], 6))]))  # Build the terminal stub.
        return self._assemble_segments(polylines, stubs)  # Assemble and return the final wire segments.

    def _assemble_segments(self, polylines: Sequence[Sequence[Point]], stubs: List[List[Point]]) -> List[Tuple[Point, Point]]:  # Join the per-sub-path polylines with terminal stubs.
        segments: List[Tuple[Point, Point]] = []  # Collect the output segments.
        seen: Set[Tuple[float, float, float, float]] = set()  # Deduplicate identical segments.
        for polyline in polylines:  # Walk the compressed sub-path polylines.
            for index in range(len(polyline) - 1):  # Walk the polyline segments.
                segments.append((polyline[index], polyline[index + 1]))  # Append the polyline segment.
        for stub in stubs:  # Walk the terminal stubs.
            for index in range(len(stub) - 1):  # Walk the stub segments.
                segments.append((stub[index], stub[index + 1]))  # Append the stub segment.
        unique_segments: List[Tuple[Point, Point]] = []  # Collect deduplicated segments.
        for segment in segments:  # Walk the collected segments.
            key = (round(segment[0][0], 6), round(segment[0][1], 6), round(segment[1][0], 6), round(segment[1][1], 6))  # Build the segment key.
            if key in seen:  # Skip duplicate segments.
                continue  # Move to the next segment.
            seen.add(key)  # Record the segment.
            unique_segments.append(segment)  # Keep the unique segment.
        return unique_segments  # Return the assembled segments.

    def path_shares_foreign_cells(self, cells: Sequence[Cell], net_id: int) -> bool:  # Detect cells already owned by another net.
        for cell in cells:  # Walk the candidate cells.
            owner = self.owner_net.get(cell)  # Read the cell owner.
            if owner is not None and owner != net_id:  # Detect a foreign owned cell.
                return True  # Report the foreign sharing.
        return False  # Report a clean path.

    def compressed_points(self, cells: Sequence[Cell]) -> List[Point]:  # Compress one cell path into its polyline corner points.
        return self._compress_cells(cells)  # Return the compressed world points.

    def routed_corner_points(self) -> List[Point]:  # Return actual corners from every branch of the most recent route.
        corners: List[Point] = []  # Collect branch-local compressed points.
        for path in self.last_routed_sub_paths or []:  # Preserve branch boundaries to avoid phantom jump corners.
            corners.extend(self._compress_cells(path))  # Append this branch's actual points.
        return corners  # Return all emitted route corners.

    def foreign_shared_cells(self, cells: Sequence[Cell], net_id: int) -> List[Cell]:  # List the cells shared with foreign nets.
        shared: List[Cell] = []  # Collect the shared cells.
        for cell in cells:  # Walk the candidate cells.
            owner = self.owner_net.get(cell)  # Read the cell owner.
            if owner is not None and owner != net_id:  # Detect a foreign owned cell.
                shared.append(cell)  # Record the shared cell.
        return shared  # Return the shared cell list.
