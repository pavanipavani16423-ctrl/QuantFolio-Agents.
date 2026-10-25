"""Quadratic Unconstrained Binary Optimization problems and their Ising form.

    E(x) = offset + Σ_i a_i x_i + Σ_{i<j} b_ij x_i x_j,   x ∈ {0,1}^n

Ising mapping uses the Qiskit convention Z|0⟩ = +|0⟩, Z|1⟩ = −|1⟩, i.e. x_i = (1 − z_i) / 2:

    a x_i       = a/2 − (a/2) z_i
    b x_i x_j   = b/4 (1 − z_i − z_j + z_i z_j)
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

BRUTE_FORCE_LIMIT = 24


@dataclass
class QUBO:
    linear: np.ndarray
    quadratic: dict[tuple[int, int], float]
    offset: float = 0.0
    labels: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.linear = np.asarray(self.linear, dtype=float)
        if not self.labels:
            self.labels = [f"x{i}" for i in range(self.num_vars)]
        if len(self.labels) != self.num_vars:
            raise ValueError("labels must match the number of variables")
        normalized: dict[tuple[int, int], float] = {}
        for (i, j), value in self.quadratic.items():
            if i == j:
                raise ValueError("diagonal terms belong in `linear` (x_i^2 = x_i)")
            if not (0 <= i < self.num_vars and 0 <= j < self.num_vars):
                raise ValueError(f"quadratic index ({i}, {j}) out of range")
            key = (min(i, j), max(i, j))
            normalized[key] = normalized.get(key, 0.0) + float(value)
        self.quadratic = {k: v for k, v in normalized.items() if v != 0.0}

    @property
    def num_vars(self) -> int:
        return int(self.linear.shape[0])

    def energy(self, x: np.ndarray | list[int]) -> float:
        return float(self.energies(np.asarray(x, dtype=np.int8)[None, :])[0])

    def energies(self, X: np.ndarray) -> np.ndarray:
        """Energies of a batch of assignments, shape (k, n) -> (k,)."""
        X = np.asarray(X, dtype=float)
        values = self.offset + X @ self.linear
        for (i, j), b in self.quadratic.items():
            values = values + b * X[:, i] * X[:, j]
        return values

    def all_energies(self) -> np.ndarray:
        """Energy of every basis state, indexed by integer k with x_i = bit i of k.

        This index matches Qiskit's statevector ordering (qubit i = bit i).
        """
        if self.num_vars > BRUTE_FORCE_LIMIT:
            raise ValueError(f"exhaustive evaluation limited to {BRUTE_FORCE_LIMIT} variables")
        k = np.arange(2**self.num_vars, dtype=np.int64)
        bits = ((k[:, None] >> np.arange(self.num_vars)) & 1).astype(np.int8)
        return self.energies(bits)

    def brute_force(self) -> tuple[np.ndarray, float]:
        energies = self.all_energies()
        best = int(np.argmin(energies))
        x = ((best >> np.arange(self.num_vars)) & 1).astype(np.int8)
        return x, float(energies[best])

    def to_ising(self) -> tuple[np.ndarray, dict[tuple[int, int], float], float]:
        h = np.zeros(self.num_vars)
        J: dict[tuple[int, int], float] = {}
        offset = self.offset
        for i, a in enumerate(self.linear):
            offset += a / 2
            h[i] -= a / 2
        for (i, j), b in self.quadratic.items():
            offset += b / 4
            h[i] -= b / 4
            h[j] -= b / 4
            J[(i, j)] = J.get((i, j), 0.0) + b / 4
        return h, J, offset

    def stats(self) -> dict[str, float | int]:
        n = self.num_vars
        possible = n * (n - 1) // 2
        coefficients = [abs(v) for v in self.linear] + [abs(v) for v in self.quadratic.values()]
        return {
            "num_vars": n,
            "quadratic_terms": len(self.quadratic),
            "density": round(len(self.quadratic) / possible, 4) if possible else 0.0,
            "max_abs_coefficient": round(max(coefficients, default=0.0), 4),
        }

    # Serialization (MCP tool arguments are JSON)
    def to_dict(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "linear": [float(v) for v in self.linear],
            "quadratic": [[i, j, float(v)] for (i, j), v in sorted(self.quadratic.items())],
            "offset": float(self.offset),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QUBO":
        return cls(
            linear=np.asarray(data["linear"], dtype=float),
            quadratic={(int(i), int(j)): float(v) for i, j, v in data["quadratic"]},
            offset=float(data.get("offset", 0.0)),
            labels=list(data.get("labels") or []),
        )
