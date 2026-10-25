"""QAOA for QUBO problems on the local Aer simulator.

Pipeline: QUBO → Ising → scaled cost Hamiltonian → QAOA ansatz(p) → classical optimizer
(COBYLA) on ⟨H⟩ → final sampling with `shots` → energy-ranked samples.

Mixers: ``x`` (standard QAOA) or ``xy`` (Dicke start + ring XY mixer, which keeps exactly
``hamming_weight`` ones in every sample; see `app.quantum.circuits`).

Expectation modes
-----------------
* ``statevector``: exact ⟨H⟩ from the simulated statevector. Smooth objective, but only
  possible on a simulator.
* ``cvar``: CVaR_α of energies estimated from `shots` samples per evaluation (Barkoutsos et
  al., 2020), which is what you would optimize on hardware. Noisier, usually needs more
  iterations.

Reported quality metrics (exact, because n is small enough to enumerate all 2^n states). With
a Hamming-weight constraint, E_min / E_max are taken over the feasible (weight-k) states:
* ``approximation_ratio``: (E_max − ⟨E⟩) / (E_max − E_min) of the final state. 1 = all
  probability on optimal states, 0 = all on the worst feasible states.
* ``optimal_probability``: probability mass on optimal states in the final state.
* ``feasible_probability``: probability mass on weight-k states (1 for the XY mixer).
"""

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from app.quantum.circuits import build_qaoa_circuit, circuit_metrics, cost_hamiltonian
from app.quantum.fastsim import FastQAOASimulator
from app.quantum.qubo import BRUTE_FORCE_LIMIT, QUBO
from app.quantum.simulator import AerBackend
from app.quantum.utils import bits_to_string, index_to_bits, normalized_ratio, qiskit_key_to_bits

MAX_QUBITS = 24


class QAOATimeout(Exception):
    pass


@dataclass
class QAOAConfig:
    reps: int = 2
    shots: int = 1024
    maxiter: int = 100
    seed: int = 0
    expectation_mode: str = "statevector"  # statevector | cvar
    cvar_alpha: float = 0.25
    restarts: int = 1
    time_limit: float | None = None
    top_k: int = 16
    mixer: str = "x"  # x | xy
    hamming_weight: int | None = None  # number of ones in a feasible bitstring (required for xy)
    simulator: str = "fast"  # fast (exact NumPy statevector) | aer, for the optimization loop

    def __post_init__(self) -> None:
        if self.mixer not in ("x", "xy"):
            raise ValueError("mixer must be 'x' or 'xy'")
        if self.mixer == "xy" and self.hamming_weight is None:
            raise ValueError("the xy mixer needs hamming_weight")
        if self.expectation_mode not in ("statevector", "cvar"):
            raise ValueError("expectation_mode must be 'statevector' or 'cvar'")
        if self.reps < 1 or self.shots < 1 or self.maxiter < 1 or self.restarts < 1:
            raise ValueError("reps, shots, maxiter and restarts must be positive")
        if not 0 < self.cvar_alpha <= 1:
            raise ValueError("cvar_alpha must be in (0, 1]")


@dataclass
class Sample:
    bits: np.ndarray
    count: int
    probability: float
    energy: float

    @property
    def bitstring(self) -> str:
        return bits_to_string(self.bits)


@dataclass
class QAOAResult:
    num_qubits: int
    reps: int
    shots: int
    optimizer: str
    expectation_mode: str
    backend: str
    circuit_depth: int
    two_qubit_gates: int
    gate_counts: dict[str, int]
    iterations: int
    convergence: list[float]
    optimal_parameters: dict[str, float]
    final_expectation: float
    samples: list[Sample]  # sorted by energy, best first, at most top_k
    best_bits: np.ndarray
    best_energy: float
    ground_energy: float | None
    approximation_ratio: float | None
    optimal_probability: float | None
    execution_time: float
    mixer: str = "x"
    hamming_weight: int | None = None
    feasible_probability: float | None = None
    feasible_sample_fraction: float | None = None
    feasible_approximation_ratio: float | None = None
    timings: dict[str, float] = field(default_factory=dict)
    timed_out: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "num_qubits": self.num_qubits,
            "reps": self.reps,
            "shots": self.shots,
            "optimizer": self.optimizer,
            "expectation_mode": self.expectation_mode,
            "backend": self.backend,
            "circuit_depth": self.circuit_depth,
            "two_qubit_gates": self.two_qubit_gates,
            "gate_counts": self.gate_counts,
            "iterations": self.iterations,
            "convergence": [round(v, 6) for v in self.convergence],
            "optimal_parameters": self.optimal_parameters,
            "final_expectation": self.final_expectation,
            "samples": [
                {
                    "bitstring": s.bitstring,
                    "count": s.count,
                    "probability": s.probability,
                    "energy": s.energy,
                }
                for s in self.samples
            ],
            "best_bitstring": bits_to_string(self.best_bits),
            "best_energy": self.best_energy,
            "ground_energy": self.ground_energy,
            "approximation_ratio": self.approximation_ratio,
            "optimal_probability": self.optimal_probability,
            "feasible_probability": self.feasible_probability,
            "feasible_sample_fraction": self.feasible_sample_fraction,
            "feasible_approximation_ratio": self.feasible_approximation_ratio,
            "timings": self.timings,
            "mixer": self.mixer,
            "hamming_weight": self.hamming_weight,
            "execution_time": self.execution_time,
            "timed_out": self.timed_out,
            "warnings": self.warnings,
        }


def _initial_points(reps: int, restarts: int, rng: np.random.Generator) -> list[np.ndarray]:
    """Linear-ramp schedule (an annealing-inspired start), then random restarts."""
    t = (np.arange(reps) + 0.5) / reps
    delta = 0.8
    points = [np.concatenate([t * delta, (1 - t) * delta])]  # [γ..., β...]
    for _ in range(restarts - 1):
        points.append(
            np.concatenate([rng.uniform(0, np.pi, reps), rng.uniform(0, np.pi / 2, reps)])
        )
    return points


def run_qaoa(qubo: QUBO, config: QAOAConfig | None = None) -> QAOAResult:
    config = config or QAOAConfig()
    n = qubo.num_vars
    if n == 0:
        raise ValueError("QUBO has no variables")
    if n > MAX_QUBITS:
        raise ValueError(f"{n} qubits exceeds the simulator limit of {MAX_QUBITS}")
    started = time.perf_counter()
    rng = np.random.default_rng(config.seed)
    warnings: list[str] = []

    hamiltonian = cost_hamiltonian(qubo)
    qaoa = build_qaoa_circuit(hamiltonian, config.reps, config.mixer, config.hamming_weight)
    metrics = circuit_metrics(qaoa.ansatz, seed=config.seed)
    backend = AerBackend(seed=config.seed)
    compiled_measured = backend.compile_measured(qaoa.ansatz)
    params = qaoa.ordered_parameters()

    # Exact energy of every basis state: cheap for n ≤ 24 and used for the expectation value
    # and for honest quality metrics (ground energy, approximation ratio).
    diagonal = qubo.all_energies() if n <= BRUTE_FORCE_LIMIT else None
    feasible = None
    if diagonal is not None:
        if config.hamming_weight is not None:
            weights = np.bitwise_count(np.arange(2**n, dtype=np.uint64))
            feasible = weights == config.hamming_weight
        else:
            feasible = np.ones(diagonal.shape, dtype=bool)

    fast = None
    if diagonal is not None and config.simulator == "fast":
        # eigenvalues of the scaled cost operator the circuit actually evolves under
        fast = FastQAOASimulator(
            (diagonal - hamiltonian.offset) / hamiltonian.scale, n, config.mixer,
            config.hamming_weight,
        )
    elif config.expectation_mode == "statevector" and diagonal is None:
        raise ValueError(f"statevector mode needs n <= {BRUTE_FORCE_LIMIT}")
    compiled_cache: dict[str, object] = {}

    def probabilities(x: np.ndarray) -> np.ndarray:
        if fast is not None:
            return fast.probabilities(x[: config.reps], x[config.reps :])
        if "sv" not in compiled_cache:
            compiled_cache["sv"] = backend.compile(qaoa.ansatz)
        return backend.probabilities(compiled_cache["sv"], binding(x))

    support_energies = diagonal[fast.support] if fast is not None else None

    def expectation(x: np.ndarray) -> float:
        if fast is not None:
            return float(fast.support_probabilities(x[: config.reps], x[config.reps :]) @ support_energies)
        return float(probabilities(x) @ diagonal)

    convergence: list[float] = []
    best_seen: dict[str, object] = {"value": np.inf, "x": None}

    def binding(x: np.ndarray) -> dict:
        return dict(zip(params, (float(v) for v in x), strict=True))

    def objective(x: np.ndarray) -> float:
        if config.time_limit is not None and time.perf_counter() - started > config.time_limit:
            raise QAOATimeout
        if config.expectation_mode == "statevector":
            value = expectation(x)
        else:
            counts = backend.sample(compiled_measured, binding(x), config.shots)
            value = _cvar(qubo, counts, n, config.cvar_alpha)
        convergence.append(value)
        if value < best_seen["value"]:
            best_seen.update(value=value, x=np.array(x))
        return value

    timed_out = False
    optimize_started = time.perf_counter()
    for start in _initial_points(config.reps, config.restarts, rng):
        try:
            minimize(
                objective,
                start,
                method="COBYLA",
                options={"maxiter": config.maxiter, "rhobeg": 0.4},
            )
        except QAOATimeout:
            timed_out = True
            warnings.append(f"optimizer stopped at the {config.time_limit}s time limit")
            break
    if best_seen["x"] is None:
        raise RuntimeError("QAOA time limit expired before the first circuit evaluation")
    x_opt = best_seen["x"]
    optimize_seconds = time.perf_counter() - optimize_started

    # final measurement: the real circuit, sampled on Qiskit Aer
    sample_started = time.perf_counter()
    counts = backend.sample(compiled_measured, binding(x_opt), config.shots)
    sample_seconds = time.perf_counter() - sample_started
    samples = _rank_samples(qubo, counts, n, config.shots)
    best = samples[0]

    ground_energy = approximation_ratio = optimal_probability = feasible_probability = None
    feasible_approximation_ratio = None
    final_expectation = float(best_seen["value"])
    if diagonal is not None:
        probs = probabilities(x_opt)
        feasible_probability = float(probs[feasible].sum())
        ground_energy = float(diagonal[feasible].min())
        worst = float(diagonal[feasible].max())
        final_expectation = float(probs @ diagonal)
        approximation_ratio = normalized_ratio(final_expectation, ground_energy, worst)
        if feasible_probability > 0:
            conditional = float(probs[feasible] @ diagonal[feasible]) / feasible_probability
            feasible_approximation_ratio = normalized_ratio(conditional, ground_energy, worst)
        optimal_probability = float(probs[feasible & np.isclose(diagonal, ground_energy)].sum())
    feasible_sample_fraction = None
    if config.hamming_weight is not None:
        feasible_sample_fraction = float(
            sum(s.count for s in samples if int(s.bits.sum()) == config.hamming_weight)
            / config.shots
        )
    timings = {
        "optimize_seconds": round(optimize_seconds, 3),
        "sample_seconds": round(sample_seconds, 3),
    }

    return QAOAResult(
        num_qubits=n,
        reps=config.reps,
        shots=config.shots,
        optimizer="COBYLA",
        expectation_mode=config.expectation_mode,
        backend=(
            f"{backend.name} (final shots); angle optimization on "
            + ("exact NumPy statevector" if fast is not None else "Aer statevector")
        ),
        circuit_depth=int(metrics["depth"]),
        two_qubit_gates=int(metrics["two_qubit_gates"]),
        gate_counts=dict(metrics["gate_counts"]),
        iterations=len(convergence),
        convergence=convergence,
        optimal_parameters={p.name: float(v) for p, v in zip(params, x_opt, strict=True)},
        final_expectation=final_expectation,
        samples=samples[: config.top_k],
        best_bits=best.bits,
        best_energy=best.energy,
        ground_energy=ground_energy,
        approximation_ratio=approximation_ratio,
        optimal_probability=optimal_probability,
        execution_time=round(time.perf_counter() - started, 4),
        timed_out=timed_out,
        warnings=warnings,
        mixer=config.mixer,
        hamming_weight=config.hamming_weight,
        feasible_probability=feasible_probability,
        feasible_sample_fraction=feasible_sample_fraction,
        feasible_approximation_ratio=feasible_approximation_ratio,
        timings=timings,
    )


def _rank_samples(qubo: QUBO, counts: dict[str, int], n: int, shots: int) -> list[Sample]:
    keys = list(counts)
    bits = np.array([qiskit_key_to_bits(k, n) for k in keys])
    energies = qubo.energies(bits)
    samples = [
        Sample(
            bits=bits[i], count=counts[k], probability=counts[k] / shots, energy=float(energies[i])
        )
        for i, k in enumerate(keys)
    ]
    return sorted(samples, key=lambda s: (s.energy, -s.count))


def _cvar(qubo: QUBO, counts: dict[str, int], n: int, alpha: float) -> float:
    ranked = _rank_samples(qubo, counts, n, sum(counts.values()))
    budget = alpha * sum(counts.values())
    total, used = 0.0, 0.0
    for sample in ranked:
        take = min(sample.count, budget - used)
        total += take * sample.energy
        used += take
        if used >= budget:
            break
    return total / used


def exact_ground_state(qubo: QUBO) -> tuple[str, float]:
    """Brute-force reference used by tests and benchmarks (n ≤ 24)."""
    x, energy = qubo.brute_force()
    return bits_to_string(x), energy


__all__ = ["QAOAConfig", "QAOAResult", "Sample", "run_qaoa", "exact_ground_state", "index_to_bits"]
