"""Path tracing GUI for CAD-style wire, obstacle and flag drawing on a 2D grid."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np


def are_wires_horizontal_or_vertical(wires: np.ndarray) -> bool:
    wires = np.asarray(wires)
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("wires must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    return bool(np.all((wires[:, 0] == wires[:, 2]) | (wires[:, 1] == wires[:, 3])))


def are_wires_connected(wires: np.ndarray) -> bool:
    wires = np.asarray(wires)
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("wires must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    n = len(wires)
    if n <= 1:
        return True
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri = _find(i)
        rj = _find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if _wires_share_point(tuple(wires[i]), tuple(wires[j])):
                _union(i, j)
    root = _find(0)
    return all(_find(i) == root for i in range(1, n))


def are_wires_intersecting_obstacles_fast(wires: np.ndarray, obstacles: np.ndarray) -> bool:
    wires = np.asarray(wires)
    obstacles = np.asarray(obstacles)
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("wires must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    if obstacles.ndim != 2 or obstacles.shape[1] != 4:
        raise ValueError("obstacles must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    for wire in wires:
        for obstacle in obstacles:
            if _lines_intersect(tuple(wire), tuple(obstacle)):
                return True
    return False


def are_wires_intersecting_obstacles_detailed(
    wires: np.ndarray,
    obstacles: np.ndarray,
) -> Tuple[bool, Optional[np.ndarray]]:
    wires = np.asarray(wires)
    obstacles = np.asarray(obstacles)
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("wires must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    if obstacles.ndim != 2 or obstacles.shape[1] != 4:
        raise ValueError("obstacles must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    intersections: List[List[int]] = []
    for wire_idx, wire in enumerate(wires):
        for obstacle_idx, obstacle in enumerate(obstacles):
            if _lines_intersect(tuple(wire), tuple(obstacle)):
                intersections.append([wire_idx, obstacle_idx])
    if not intersections:
        return False, None
    return True, np.array(intersections, dtype=int)


def get_wires_startpos_endpos(wires: np.ndarray) -> np.ndarray:
    wires = np.asarray(wires)
    if wires.ndim != 2 or wires.shape[1] != 4:
        raise ValueError("wires must be a 2D array with 4 columns: X1, Y1, X2, Y2")
    n = len(wires)
    if n == 0:
        raise ValueError("wires must form a single continuous path with at least two endpoints")
    wire_tuples = [(int(w[0]), int(w[1]), int(w[2]), int(w[3])) for w in wires]
    point_counts: dict[Tuple[int, int], int] = {}
    for w in wire_tuples:
        first_point = (w[0], w[1])
        second_point = (w[2], w[3])
        point_counts[first_point] = point_counts.get(first_point, 0) + 1
        point_counts[second_point] = point_counts.get(second_point, 0) + 1
    parent = list(range(n))
    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def _union(i: int, j: int) -> None:
        ri = _find(i)
        rj = _find(j)
        if ri != rj:
            parent[rj] = ri
    for i in range(n):
        wi = wire_tuples[i]
        for j in range(i + 1, n):
            wj = wire_tuples[j]
            if _wires_share_point(wi, wj):
                _union(i, j)
    for i in range(n):
        wi = wire_tuples[i]
        for j in range(n):
            if i == j:
                continue
            wj = wire_tuples[j]
            if _point_on_wire_interior((wi[0], wi[1]), wj) or _point_on_wire_interior((wi[2], wi[3]), wj):
                _union(i, j)
    root = _find(0)
    if any(_find(i) != root for i in range(1, n)):
        raise ValueError("wires must form a single continuous path with at least two endpoints")
    for point in list(point_counts.keys()):
        for w in wire_tuples:
            if _point_on_wire_interior(point, w):
                point_counts[point] = point_counts.get(point, 0) + 2
    endpoints = [point for point, count in point_counts.items() if count == 1]
    if len(endpoints) < 2:
        raise ValueError("wires must form a single continuous path with at least two endpoints")
    endpoints.sort(key=lambda pt: (pt[0], pt[1]))
    return np.array(endpoints, dtype=int)


def _lines_intersect(w1: Tuple[int, int, int, int], w2: Tuple[int, int, int, int]) -> bool:
    x1a, y1a, x2a, y2a = w1
    x1b, y1b, x2b, y2b = w2
    a_vert = x1a == x2a
    b_vert = x1b == x2b
    if a_vert and b_vert:
        if x1a != x1b:
            return False
        return _ranges_overlap(y1a, y2a, y1b, y2b)
    if not a_vert and not b_vert:
        if y1a != y1b:
            return False
        return _ranges_overlap(x1a, x2a, x1b, x2b)
    if a_vert:
        vx, vy1, vy2 = x1a, y1a, y2a
        hx1, hx2, hy = x1b, x2b, y1b
    else:
        vx, vy1, vy2 = x1b, y1b, y2b
        hx1, hx2, hy = x1a, x2a, y1a
    return min(hx1, hx2) <= vx <= max(hx1, hx2) and min(vy1, vy2) <= hy <= max(vy1, vy2)


def _ranges_overlap(a1: int, a2: int, b1: int, b2: int) -> bool:
    return max(min(a1, a2), min(b1, b2)) <= min(max(a1, a2), max(b1, b2))


def _point_on_wire_interior(point: Tuple[int, int], wire: Tuple[int, int, int, int]) -> bool:
    px, py = point
    x1, y1, x2, y2 = wire
    if px == x1 and py == y1:
        return False
    if px == x2 and py == y2:
        return False
    if x1 == x2:
        if px != x1:
            return False
        return min(y1, y2) < py < max(y1, y2)
    if y1 == y2:
        if py != y1:
            return False
        return min(x1, x2) < px < max(x1, x2)
    if x1 == x2 or y1 == y2:
        return False
    cross_product = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if cross_product != 0:
        return False
    return min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2)


def _wires_share_point(w1: Tuple[int, int, int, int], w2: Tuple[int, int, int, int]) -> bool:
    x1a, y1a, x2a, y2a = w1
    x1b, y1b, x2b, y2b = w2
    a_vert = x1a == x2a
    b_vert = x1b == x2b
    if a_vert and b_vert:
        if x1a != x1b:
            return False
        return _ranges_overlap(y1a, y2a, y1b, y2b)
    if not a_vert and not b_vert:
        if y1a != y1b:
            return False
        return _ranges_overlap(x1a, x2a, x1b, x2b)
    if a_vert:
        vx, vy1, vy2 = x1a, y1a, y2a
        hx1, hx2, hy = x1b, x2b, y1b
    else:
        vx, vy1, vy2 = x1b, y1b, y2b
        hx1, hx2, hy = x1a, x2a, y1a
    if not (min(hx1, hx2) <= vx <= max(hx1, hx2)):
        return False
    if not (min(vy1, vy2) <= hy <= max(vy1, vy2)):
        return False
    intersection = (vx, hy)
    endpoints = {(x1a, y1a), (x2a, y2a), (x1b, y1b), (x2b, y2b)}
    return intersection in endpoints


class _PathTracingGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Path Tracing Debug GUI")
        root.geometry("900x700")

        self.grid_spacing = tk.IntVar(value=16)
        self.grid_points_x = tk.IntVar(value=400)
        self.grid_points_y = tk.IntVar(value=400)
        self.current_mode = tk.StringVar(value="WIRE")

        self.wires: List[Tuple[int, int, int, int]] = []
        self.obstacles: List[Tuple[int, int, int, int]] = []
        self.flags: List[Tuple[int, int]] = []

        self.wire_items: List[int] = []
        self.obstacle_items: List[int] = []
        self.flag_items: List[Tuple[int, int]] = []

        self.draw_start: Optional[Tuple[int, int]] = None
        self.preview_line: Optional[int] = None
        self.preview_flag_lines: Optional[Tuple[int, int]] = None
        self.last_motion_grid: Optional[Tuple[int, int]] = None

        self._build_ui()
        self._redraw_grid()

    def _to_pixel(self, gx: int, gy: int) -> Tuple[int, int]:
        spacing = self.grid_spacing.get()
        return gx * spacing, gy * spacing

    def _to_grid(self, px: int, py: int) -> Tuple[int, int]:
        spacing = self.grid_spacing.get()
        return round(px / spacing), round(py / spacing)

    def _pixel_w(self) -> int:
        return self.grid_points_x.get() * self.grid_spacing.get()

    def _pixel_h(self) -> int:
        return self.grid_points_y.get() * self.grid_spacing.get()

    def _clear_preview(self) -> None:
        if self.preview_line is not None:
            self.canvas.delete(self.preview_line)
            self.preview_line = None
        if self.preview_flag_lines is not None:
            self.canvas.delete(self.preview_flag_lines[0])
            self.canvas.delete(self.preview_flag_lines[1])
            self.preview_flag_lines = None
        self.last_motion_grid = None

    def _cancel_drawing(self) -> None:
        self._clear_preview()
        self.draw_start = None

    def _build_ui(self) -> None:
        ctrl = ttk.Frame(self.root, padding=5)
        ctrl.pack(fill=tk.X)

        ttk.Label(ctrl, text="Spacing:").pack(side=tk.LEFT)
        ttk.Entry(ctrl, textvariable=self.grid_spacing, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(ctrl, text="W:").pack(side=tk.LEFT)
        ttk.Entry(ctrl, textvariable=self.grid_points_x, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(ctrl, text="H:").pack(side=tk.LEFT)
        ttk.Entry(ctrl, textvariable=self.grid_points_y, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="Apply Grid", command=self._apply_grid).pack(side=tk.LEFT, padx=4)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=4, fill=tk.Y)

        ttk.Button(ctrl, text="WIRE", command=lambda: self._set_mode("WIRE")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="OBSTACLE", command=lambda: self._set_mode("OBSTACLE")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="FLAG", command=lambda: self._set_mode("FLAG")).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=4, fill=tk.Y)

        ttk.Button(ctrl, text="DELETE", command=lambda: self._set_mode("DELETE")).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="DELETE ALL", command=self._delete_all).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=4, fill=tk.Y)

        ttk.Button(ctrl, text="SAVE AS", command=self._save).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="LOAD", command=self._load).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=4, fill=tk.Y)

        ttk.Button(ctrl, text="AUTO ROUTE", command=self._auto_route).pack(side=tk.LEFT, padx=2)

        ttk.Button(ctrl, text="INTERSECTIONS", command=self._check_intersections).pack(side=tk.LEFT, padx=2)

        self.mode_label = ttk.Label(ctrl, text="Mode: WIRE", foreground="gray")
        self.mode_label.pack(side=tk.RIGHT, padx=4)
        self.current_mode.trace_add("write", lambda *_: self._update_mode_label())

        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        self.vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)

        self.canvas = tk.Canvas(
            canvas_frame, bg="white",
            xscrollcommand=self.hbar.set,
            yscrollcommand=self.vbar.set,
        )
        self.hbar.config(command=self.canvas.xview)
        self.vbar.config(command=self.canvas.yview)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)

    def _set_mode(self, mode: str) -> None:
        self._cancel_drawing()
        self.current_mode.set(mode)

    def _update_mode_label(self) -> None:
        self.mode_label.config(text=f"Mode: {self.current_mode.get()}")

    def _apply_grid(self) -> None:
        try:
            spacing = int(self.grid_spacing.get())
            width_pts = int(self.grid_points_x.get())
            height_pts = int(self.grid_points_y.get())
        except (ValueError, tk.TclError):
            return
        if spacing < 2 or width_pts < 1 or height_pts < 1:
            return
        self._cancel_drawing()
        self._redraw_grid()

    def _redraw_grid(self) -> None:
        self.canvas.delete("grid")
        self.canvas.delete("line")
        self.canvas.delete("flag")

        spacing = self.grid_spacing.get()
        w_grid = self.grid_points_x.get()
        h_grid = self.grid_points_y.get()
        pw = w_grid * spacing
        ph = h_grid * spacing

        self.canvas.config(scrollregion=(0, 0, pw, ph))

        for col in range(w_grid + 1):
            x = col * spacing
            self.canvas.create_line(x, 0, x, ph, fill="#e0e0e0", tags="grid")
        for row in range(h_grid + 1):
            y = row * spacing
            self.canvas.create_line(0, y, pw, y, fill="#e0e0e0", tags="grid")

        self.wire_items.clear()
        for gx1, gy1, gx2, gy2 in self.wires:
            p1 = self._to_pixel(gx1, gy1)
            p2 = self._to_pixel(gx2, gy2)
            item = self.canvas.create_line(*p1, *p2, fill="black", width=2, tags=("line",))
            self.wire_items.append(item)

        self.obstacle_items.clear()
        for gx1, gy1, gx2, gy2 in self.obstacles:
            p1 = self._to_pixel(gx1, gy1)
            p2 = self._to_pixel(gx2, gy2)
            item = self.canvas.create_line(*p1, *p2, fill="red", width=2, tags=("line",))
            self.obstacle_items.append(item)

        for gx, gy in self.flags:
            px, py = self._to_pixel(gx, gy)
            half = max(4, spacing // 4)
            self.canvas.create_line(px - half, py - half, px + half, py + half, fill="blue", width=2, tags=("flag",))
            self.canvas.create_line(px - half, py + half, px + half, py - half, fill="blue", width=2, tags=("flag",))

    def _on_motion(self, event: tk.Event) -> None:
        mode = self.current_mode.get()
        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))
        gx, gy = self._to_grid(cx, cy)

        if self.last_motion_grid == (gx, gy):
            return
        self.last_motion_grid = (gx, gy)

        if mode == "FLAG":
            self._draw_preview_flag(gx, gy)
        elif mode in ("WIRE", "OBSTACLE") and self.draw_start is not None:
            self._draw_preview_line(gx, gy)

    def _draw_preview_flag(self, gx: int, gy: int) -> None:
        if self.preview_flag_lines is not None:
            self.canvas.delete(self.preview_flag_lines[0])
            self.canvas.delete(self.preview_flag_lines[1])
        px, py = self._to_pixel(gx, gy)
        half = max(4, self.grid_spacing.get() // 4)
        line1 = self.canvas.create_line(px - half, py - half, px + half, py + half, fill="blue", width=2)
        line2 = self.canvas.create_line(px - half, py + half, px + half, py - half, fill="blue", width=2)
        self.preview_flag_lines = (line1, line2)

    def _draw_preview_line(self, cursor_gx: int, cursor_gy: int) -> None:
        if self.preview_line is not None:
            self.canvas.delete(self.preview_line)
        sgx, sgy = self.draw_start  # type: ignore[union-attr]
        if abs(cursor_gx - sgx) > abs(cursor_gy - sgy):
            egx, egy = cursor_gx, sgy
        else:
            egx, egy = sgx, cursor_gy
        p1 = self._to_pixel(sgx, sgy)
        p2 = self._to_pixel(egx, egy)
        color = "red" if self.current_mode.get() == "OBSTACLE" else "black"
        self.preview_line = self.canvas.create_line(*p1, *p2, fill=color, width=2)

    def _on_click(self, event: tk.Event) -> None:
        mode = self.current_mode.get()
        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))
        gx, gy = self._to_grid(cx, cy)

        if mode in ("WIRE", "OBSTACLE"):
            if self.draw_start is None:
                self.draw_start = (gx, gy)
            else:
                sgx, sgy = self.draw_start
                if abs(gx - sgx) > abs(gy - sgy):
                    egx, egy = gx, sgy
                else:
                    egx, egy = sgx, gy
                self._clear_preview()
                self.draw_start = None
                if sgx == egx and sgy == egy:
                    return
                p1 = self._to_pixel(sgx, sgy)
                p2 = self._to_pixel(egx, egy)
                color = "red" if mode == "OBSTACLE" else "black"
                item = self.canvas.create_line(*p1, *p2, fill=color, width=2, tags=("line",))
                if mode == "OBSTACLE":
                    self.obstacles.append((sgx, sgy, egx, egy))
                    self.obstacle_items.append(item)
                else:
                    self.wires.append((sgx, sgy, egx, egy))
                    self.wire_items.append(item)
            return

        if mode == "FLAG":
            if self.preview_flag_lines is not None:
                self.canvas.itemconfig(self.preview_flag_lines[0], tags=("flag",))
                self.canvas.itemconfig(self.preview_flag_lines[1], tags=("flag",))
                self.preview_flag_lines = None
            else:
                px, py = self._to_pixel(gx, gy)
                half = max(4, self.grid_spacing.get() // 4)
                self.canvas.create_line(px - half, py - half, px + half, py + half, fill="blue", width=2, tags=("flag",))
                self.canvas.create_line(px - half, py + half, px + half, py - half, fill="blue", width=2, tags=("flag",))
            self.flags.append((gx, gy))
            self.flag_items.append((gx, gy))
            self.last_motion_grid = None
            return

        if mode == "DELETE":
            self._delete_at(int(cx), int(cy))

    def _delete_at(self, px: int, py: int) -> None:
        threshold = max(6, self.grid_spacing.get() // 2)

        for idx, (fgx, fgy) in enumerate(self.flag_items):
            fpx, fpy = self._to_pixel(fgx, fgy)
            if abs(px - fpx) <= threshold and abs(py - fpy) <= threshold:
                items = self.canvas.find_overlapping(px - threshold, py - threshold, px + threshold, py + threshold)
                for item in items:
                    if "flag" in self.canvas.gettags(item):
                        self.canvas.delete(item)
                del self.flag_items[idx]
                del self.flags[idx]
                return

        for idx, item in enumerate(self.wire_items):
            gx1, gy1, gx2, gy2 = self.wires[idx]
            if self._near_segment(px, py, gx1, gy1, gx2, gy2, threshold):
                self.canvas.delete(item)
                del self.wire_items[idx]
                del self.wires[idx]
                return

        for idx, item in enumerate(self.obstacle_items):
            gx1, gy1, gx2, gy2 = self.obstacles[idx]
            if self._near_segment(px, py, gx1, gy1, gx2, gy2, threshold):
                self.canvas.delete(item)
                del self.obstacle_items[idx]
                del self.obstacles[idx]
                return

    def _near_segment(self, px: int, py: int, gx1: int, gy1: int, gx2: int, gy2: int, threshold: int) -> bool:
        spacing = self.grid_spacing.get()
        px1, py1 = gx1 * spacing, gy1 * spacing
        px2, py2 = gx2 * spacing, gy2 * spacing
        if px1 == px2:
            return abs(px - px1) <= threshold and min(py1, py2) - threshold <= py <= max(py1, py2) + threshold
        return abs(py - py1) <= threshold and min(px1, px2) - threshold <= px <= max(px1, px2) + threshold

    def _delete_all(self) -> None:
        self._cancel_drawing()
        self.canvas.delete("line")
        self.canvas.delete("flag")
        self.wires.clear()
        self.obstacles.clear()
        self.flags.clear()
        self.wire_items.clear()
        self.obstacle_items.clear()
        self.flag_items.clear()
        self.current_mode.set("WIRE")

    def _auto_route(self) -> None:
        if len(self.flags) != 2:
            messagebox.showinfo("AUTO ROUTE", "Exactly two FLAG points are required for auto routing.")
            return
        if not self.obstacles:
            messagebox.showinfo("AUTO ROUTE", "At least one obstacle is required for auto routing.")
            return
        from .autoroute import auto_route_wires

        spacing = self.grid_spacing.get()
        (gx1, gy1), (gx2, gy2) = self.flags
        start_x = gx1 * spacing
        start_y = gy1 * spacing
        end_x = gx2 * spacing
        end_y = gy2 * spacing
        obstacles_array = np.array(
            [[ox1 * spacing, oy1 * spacing, ox2 * spacing, oy2 * spacing] for ox1, oy1, ox2, oy2 in self.obstacles],
            dtype=int,
        )
        try:
            new_wires = auto_route_wires(start_x, start_y, end_x, end_y, obstacles_array, spacing, spacing)
        except ValueError as error:
            messagebox.showinfo("AUTO ROUTE", f"No valid route found: {error}")
            return
        self._cancel_drawing()
        for px1, py1, px2, py2 in new_wires:
            ngx1, ngy1 = px1 // spacing, py1 // spacing
            ngx2, ngy2 = px2 // spacing, py2 // spacing
            self.wires.append((ngx1, ngy1, ngx2, ngy2))
            item = self.canvas.create_line(px1, py1, px2, py2, fill="black", width=2, tags=("line",))
            self.wire_items.append(item)

    def _check_intersections(self) -> None:
        if not self.wires:
            messagebox.showinfo("INTERSECTIONS", "No wires to check.")
            return
        if not self.obstacles:
            messagebox.showinfo("INTERSECTIONS", "No obstacles to check.")
            return
        wires_array = np.array(self.wires, dtype=int)
        obstacles_array = np.array(self.obstacles, dtype=int)
        if are_wires_intersecting_obstacles_fast(wires_array, obstacles_array):
            messagebox.showinfo("INTERSECTIONS", "Wires INTERSECT obstacles!")
        else:
            messagebox.showinfo("INTERSECTIONS", "Wires DO NOT intersect obstacles.")

    def _save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if not path:
            return
        spacing = self.grid_spacing.get()
        with open(path, "w", encoding="utf-8") as f:
            for gx1, gy1, gx2, gy2 in self.wires:
                f.write(f"WIRE {gx1 * spacing} {gy1 * spacing} {gx2 * spacing} {gy2 * spacing}\n")
            for gx1, gy1, gx2, gy2 in self.obstacles:
                f.write(f"OBSTACLE {gx1 * spacing} {gy1 * spacing} {gx2 * spacing} {gy2 * spacing}\n")
            for gx, gy in self.flags:
                f.write(f"FLAG {gx * spacing} {gy * spacing}\n")

    def _load(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_lines = [line.strip() for line in f if line.strip() != ""]
        except OSError:
            return
        self._delete_all()
        spacing = self.grid_spacing.get()
        for line in raw_lines:
            parts = line.split()
            if not parts:
                continue
            kind = parts[0].upper()
            if kind == "WIRE" and len(parts) == 5:
                px1, py1, px2, py2 = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                gx1, gy1 = px1 // spacing, py1 // spacing
                gx2, gy2 = px2 // spacing, py2 // spacing
                self.wires.append((gx1, gy1, gx2, gy2))
                item = self.canvas.create_line(px1, py1, px2, py2, fill="black", width=2, tags=("line",))
                self.wire_items.append(item)
            elif kind == "OBSTACLE" and len(parts) == 5:
                px1, py1, px2, py2 = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                gx1, gy1 = px1 // spacing, py1 // spacing
                gx2, gy2 = px2 // spacing, py2 // spacing
                self.obstacles.append((gx1, gy1, gx2, gy2))
                item = self.canvas.create_line(px1, py1, px2, py2, fill="red", width=2, tags=("line",))
                self.obstacle_items.append(item)
            elif kind == "FLAG" and len(parts) == 3:
                px, py = int(parts[1]), int(parts[2])
                gx, gy = px // spacing, py // spacing
                self.flags.append((gx, gy))
                self.flag_items.append((gx, gy))
                half = max(4, spacing // 4)
                self.canvas.create_line(px - half, py - half, px + half, py + half, fill="blue", width=2, tags=("flag",))
                self.canvas.create_line(px - half, py + half, px + half, py - half, fill="blue", width=2, tags=("flag",))


def gui_debug() -> None:
    root = tk.Tk()
    _PathTracingGUI(root)
    root.mainloop()
