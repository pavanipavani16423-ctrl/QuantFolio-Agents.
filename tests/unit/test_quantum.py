import math

import numpy as np
import pytest
from qiskit.quantum_info import Statevector

from app.quant.portfolio import select_exact, selection_problem
from app.quantum.circuits import build_qaoa_circuit, cost_hamiltonian, dicke_state
from app.quantum.fastsim import FastQAOASimulator
from app.quantum.qaoa_solver import QAOAConfig, run_qaoa
from app.quantum.qubo import QUBO
from app.quantum.simulator import AerBackend


@pytest.mark.parametrize(("n", "k"), [(3, 1), (4, 2), (5, 3), (6, 2), (7, 4)])
def test_dicke_state_is_uniform_over_weight_k(n: int, k: int) -> None:
    probs = np.abs(Statevector(dicke_state(n, k)).data) ** 2
    weights = np.array([bin(i).count("1") for i in range(2**n)])
    assert np.allclose(probs[weights == k], 1 / math.comb(n, k))
    assert probs[weights != k].sum() < 1e-12


def _random_qubo(n: int, seed: int = 3) -> QUBO:
    rng = np.random.default_rng(seed)
    return QUBO(linear=rng.normal(size=n),
                quadratic={(i, j): rng.normal() for i in range(n) for j in range(i + 1, n)})


@pytest.mark.parametrize("mixer", ["x", "xy"])
def test_fast_simulator_matches_qiskit_aer(mixer: str) -> None:
    n, k = 6, 3
    qubo = _random_qubo(n)
    h = cost_hamiltonian(qubo)
    circuit = build_qaoa_circuit(h, reps=2, mixer=mixer, hamming_weight=k)
    backend = AerBackend()
    angles = np.array([0.3, 0.7, 0.4, 0.2])  # gamma0, gamma1, beta0, beta1
    aer = backend.probabilities(backend.compile(circuit.ansatz), dict(zip(circuit.ordered_parameters(), angles, strict=True)))
    fast = FastQAOASimulator((qubo.all_energies() - h.offset) / h.scale, n, mixer, k)
    assert np.abs(aer - fast.probabilities(angles[:2], angles[2:])).max() < 1e-9


def test_xy_mixer_never_leaves_the_feasible_subspace() -> None:
    qubo = _random_qubo(7)
    res = run_qaoa(qubo, QAOAConfig(reps=1, maxiter=15, shots=512, mixer="xy", hamming_weight=3))
    assert res.feasible_probability == pytest.approx(1.0, abs=1e-9)
    assert res.feasible_sample_fraction == 1.0
    assert all(int(s.bits.sum()) == 3 for s in res.samples)


def test_selection_qubo_energy_matches_equal_weight_utility() -> None:
    rng = np.random.default_rng(0)
    n, k = 8, 3
    a = rng.normal(size=(n, n))
    cov = a @ a.T / n * 0.05
    mu = rng.uniform(0.0, 0.3, size=n)
    sp = selection_problem([f"T{i}" for i in range(n)], ["S"] * 4 + ["R"] * 4, mu, cov, k, 4.0, 1.0)
    qubo = sp.qubo(with_penalty=False)
    for _ in range(10):
        x = np.zeros(n, dtype=int)
        x[rng.choice(n, size=k, replace=False)] = 1
        assert qubo.energy(x) == pytest.approx(-sp.utility(x))
    # with the penalty, the unconstrained ground state has exactly k ones
    bits, _ = sp.qubo(with_penalty=True).brute_force()
    assert int(bits.sum()) == k


def test_exact_selection_equals_brute_force_over_feasible_sets() -> None:
    rng = np.random.default_rng(5)
    n, k = 9, 4
    a = rng.normal(size=(n, n))
    sp = selection_problem([f"T{i}" for i in range(n)], ["A", "A", "A", "B", "B", "B", "C", "C", "C"],
                           rng.uniform(0, 0.3, n), a @ a.T * 0.01, k, 3.0, 0.5)
    result = select_exact(sp)
    best = max((x for x in (np.array([(i >> b) & 1 for b in range(n)]) for i in range(2**n)) if sp.feasible(x)),
               key=sp.utility)
    assert result.utility == pytest.approx(sp.utility(best))
    assert result.feasible
