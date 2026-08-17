"""Deterministic evolutionary seeding for schematic component placement.

This module is a self-contained adaptation of the genetic placement ideas in
the MIT-licensed ``kicad-tools`` project
(``src/kicad_tools/optim/evolutionary.py``, Copyright (c) 2024 RJ Walters).
It deliberately depends only on this package and NumPy/Numba.  The best
chromosome is applied to :class:`ForceDirectedPlacer`, whose physics engine can
then perform the local refinement phase.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from numba import njit

from .force_directed_placement import ForceDirectedPlacer

__all__ = ["EvolutionaryPlacementConfig", "EvolutionarySchematicPlacer"]


@dataclass
class EvolutionaryPlacementConfig:
    """Configuration for the bounded genetic placement search."""

    population_size: int = 18
    generations: int = 16
    elitism: int = 3
    crossover_rate: float = 0.8
    mutation_rate: float = 0.18
    position_mutation_sigma: float = 6.35
    rotation_mutation_rate: float = 0.08
    convergence_generations: int = 6
    convergence_threshold: float = 1e-4
    random_seed: int = 0


@njit(cache=True)
def _population_costs(
    genomes: np.ndarray,
    widths: np.ndarray,
    heights: np.ndarray,
    spring_components: np.ndarray,
    spring_offsets: np.ndarray,
    page_width: float,
    page_height: float,
    boundary_margin: float,
    alignment_tolerance: float,
) -> np.ndarray:
    """Score a population in compiled code; lower cost is better."""

    population_count, component_count, _ = genomes.shape
    costs = np.zeros(population_count, dtype=np.float64)
    for population_index in range(population_count):
        wire_length = 0.0
        aligned = 0
        for spring_index in range(spring_components.shape[0]):
            first = spring_components[spring_index, 0]
            second = spring_components[spring_index, 1]
            first_angle = math.radians(genomes[population_index, first, 2])
            second_angle = math.radians(genomes[population_index, second, 2])
            first_cos, first_sin = math.cos(first_angle), math.sin(first_angle)
            second_cos, second_sin = math.cos(second_angle), math.sin(second_angle)
            first_x = genomes[population_index, first, 0] + spring_offsets[spring_index, 0] * first_cos - spring_offsets[spring_index, 1] * first_sin
            first_y = genomes[population_index, first, 1] + spring_offsets[spring_index, 0] * first_sin + spring_offsets[spring_index, 1] * first_cos
            second_x = genomes[population_index, second, 0] + spring_offsets[spring_index, 2] * second_cos - spring_offsets[spring_index, 3] * second_sin
            second_y = genomes[population_index, second, 1] + spring_offsets[spring_index, 2] * second_sin + spring_offsets[spring_index, 3] * second_cos
            delta_x, delta_y = second_x - first_x, second_y - first_y
            wire_length += math.sqrt(delta_x * delta_x + delta_y * delta_y)
            if abs(delta_x) <= alignment_tolerance or abs(delta_y) <= alignment_tolerance:
                aligned += 1

        overlap_area = 0.0
        congestion = 0.0
        boundary_overflow = 0.0
        for first in range(component_count):
            rotation_slot = int(round(genomes[population_index, first, 2] / 90.0)) % 2
            first_width = heights[first] if rotation_slot else widths[first]
            first_height = widths[first] if rotation_slot else heights[first]
            first_x, first_y = genomes[population_index, first, 0], genomes[population_index, first, 1]
            left = first_x - first_width / 2.0 - boundary_margin
            right = first_x + first_width / 2.0 + boundary_margin
            top = first_y - first_height / 2.0 - boundary_margin
            bottom = first_y + first_height / 2.0 + boundary_margin
            boundary_overflow += max(0.0, -left) + max(0.0, right - page_width)
            boundary_overflow += max(0.0, -top) + max(0.0, bottom - page_height)
            for second in range(first + 1, component_count):
                second_slot = int(round(genomes[population_index, second, 2] / 90.0)) % 2
                second_width = heights[second] if second_slot else widths[second]
                second_height = widths[second] if second_slot else heights[second]
                delta_x = abs(first_x - genomes[population_index, second, 0])
                delta_y = abs(first_y - genomes[population_index, second, 1])
                x_overlap = (first_width + second_width) / 2.0 - delta_x
                y_overlap = (first_height + second_height) / 2.0 - delta_y
                if x_overlap > 0.0 and y_overlap > 0.0:
                    overlap_area += x_overlap * y_overlap
                clearance_x = delta_x - (first_width + second_width) / 2.0
                clearance_y = delta_y - (first_height + second_height) / 2.0
                if clearance_x < boundary_margin and clearance_y < boundary_margin:
                    congestion += max(0.0, boundary_margin - max(clearance_x, clearance_y))

        alignment_ratio = aligned / max(1, spring_components.shape[0])
        costs[population_index] = wire_length + overlap_area * 5000.0 + boundary_overflow * 10000.0 + congestion * 40.0 - alignment_ratio * 20.0
    return costs


class EvolutionarySchematicPlacer:
    """Find a global placement seed before force-directed refinement."""

    def __init__(
        self,
        placer: ForceDirectedPlacer,
        grid: float,
        config: Optional[EvolutionaryPlacementConfig] = None,
    ) -> None:
        self.placer = placer
        self.grid = grid
        self.config = config or EvolutionaryPlacementConfig()
        self._random = random.Random(self.config.random_seed)
        self._components = list(placer.components)
        self._component_indices = {component.ref: index for index, component in enumerate(self._components)}
        self._widths = np.asarray([component.width for component in self._components], dtype=np.float64)
        self._heights = np.asarray([component.height for component in self._components], dtype=np.float64)
        self._spring_components, self._spring_offsets = self._encode_springs()
        xs = [vertex.x for vertex in placer.boundary.vertices]
        ys = [vertex.y for vertex in placer.boundary.vertices]
        self._page_width = max(xs) - min(xs)
        self._page_height = max(ys) - min(ys)

    def _encode_springs(self) -> Tuple[np.ndarray, np.ndarray]:
        component_rows: List[Tuple[int, int]] = []
        offset_rows: List[Tuple[float, float, float, float]] = []
        for spring in self.placer.springs:
            first = self.placer.get_component(spring.comp1_ref)
            second = self.placer.get_component(spring.comp2_ref)
            if first is None or second is None:
                continue
            first_pin = next((pin for pin in first.pins if pin.number == spring.pin1_num), None)
            second_pin = next((pin for pin in second.pins if pin.number == spring.pin2_num), None)
            if first_pin is None or second_pin is None:
                continue
            component_rows.append((self._component_indices[first.ref], self._component_indices[second.ref]))
            offset_rows.append((first_pin.offset_x, first_pin.offset_y, second_pin.offset_x, second_pin.offset_y))
        return (
            np.asarray(component_rows, dtype=np.int64).reshape((-1, 2)),
            np.asarray(offset_rows, dtype=np.float64).reshape((-1, 4)),
        )

    def _current_genome(self) -> np.ndarray:
        return np.asarray([(component.x, component.y, component.rotation) for component in self._components], dtype=np.float64)

    def _random_genome(self) -> np.ndarray:
        genome = np.empty((len(self._components), 3), dtype=np.float64)
        margin = self.placer.config.boundary_margin
        for index, component in enumerate(self._components):
            half_extent = max(component.width, component.height) / 2.0 + margin
            low_x, high_x = half_extent, max(half_extent, self._page_width - half_extent)
            low_y, high_y = half_extent, max(half_extent, self._page_height - half_extent)
            genome[index, 0] = self._snap(self._random.uniform(low_x, high_x))
            genome[index, 1] = self._snap(self._random.uniform(low_y, high_y))
            genome[index, 2] = float(self._random.choice((0, 90, 180, 270)))
        return genome

    def _snap(self, value: float) -> float:
        return round(value / self.grid) * self.grid if self.grid > 0 else value

    def _initial_population(self) -> np.ndarray:
        population_size = max(2, self.config.population_size)
        population = np.empty((population_size, len(self._components), 3), dtype=np.float64)
        population[0] = self._current_genome()
        for index in range(1, population_size):
            population[index] = self._random_genome()
        return population

    def _select(self, costs: np.ndarray) -> int:
        candidates = self._random.sample(range(len(costs)), min(3, len(costs)))
        return min(candidates, key=lambda index: costs[index])

    def _crossover(self, first: np.ndarray, second: np.ndarray) -> np.ndarray:
        if self._random.random() >= self.config.crossover_rate:
            return first.copy()
        partition = self._random.uniform(0.35, 0.65) * self._page_width
        child = second.copy()
        for index in range(len(self._components)):
            if first[index, 0] <= partition:
                child[index] = first[index]
        return child

    def _mutate(self, genome: np.ndarray) -> None:
        margin = self.placer.config.boundary_margin
        for index, component in enumerate(self._components):
            half_extent = max(component.width, component.height) / 2.0 + margin
            if self._random.random() < self.config.mutation_rate:
                genome[index, 0] = self._snap(genome[index, 0] + self._random.gauss(0.0, self.config.position_mutation_sigma))
                genome[index, 1] = self._snap(genome[index, 1] + self._random.gauss(0.0, self.config.position_mutation_sigma))
                genome[index, 0] = min(max(half_extent, genome[index, 0]), max(half_extent, self._page_width - half_extent))
                genome[index, 1] = min(max(half_extent, genome[index, 1]), max(half_extent, self._page_height - half_extent))
            if self._random.random() < self.config.rotation_mutation_rate:
                genome[index, 2] = (genome[index, 2] + self._random.choice((90.0, 180.0, 270.0))) % 360.0

    def optimize(self) -> float:
        """Run the genetic search, apply its best genome, and return its cost."""

        if not self._components:
            return 0.0
        population = self._initial_population()
        best_genome = population[0].copy()
        best_cost = float("inf")
        history: List[float] = []
        generations = max(1, self.config.generations)
        for _generation in range(generations):
            costs = _population_costs(
                population,
                self._widths,
                self._heights,
                self._spring_components,
                self._spring_offsets,
                self._page_width,
                self._page_height,
                self.placer.config.boundary_margin,
                max(self.grid / 2.0, 0.25),
            )
            order = np.argsort(costs)
            if float(costs[order[0]]) < best_cost:
                best_cost = float(costs[order[0]])
                best_genome = population[order[0]].copy()
            history.append(best_cost)
            window = self.config.convergence_generations
            if len(history) >= window and abs(history[-window] - history[-1]) <= max(1.0, abs(history[-window])) * self.config.convergence_threshold:
                break
            next_population = [population[index].copy() for index in order[: max(1, min(self.config.elitism, len(population)))]]
            while len(next_population) < len(population):
                child = self._crossover(population[self._select(costs)], population[self._select(costs)])
                self._mutate(child)
                next_population.append(child)
            population = np.asarray(next_population, dtype=np.float64)

        for index, component in enumerate(self._components):
            component.x = float(best_genome[index, 0])
            component.y = float(best_genome[index, 1])
            component.rotation = float(best_genome[index, 2])
            component.vx = component.vy = component.angular_velocity = 0.0
        return best_cost
