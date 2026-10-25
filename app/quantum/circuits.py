"""Cost Hamiltonian and QAOA circuit construction.

Two ansatz families:

* ``x``  - standard QAOA (Farhi et al., 2014): |+>^n start, transverse-field X mixer. Any
  bitstring can come out, so constraints must be added to the cost as penalties.
* ``xy`` - Quantum Alternating Operator Ansatz (Hadfield et al., 2019) for "choose exactly k":
  start in the Dicke state |D(n,k)> (equal superposition of all weight-k bitstrings) and mix
  with the ring XY mixer sum_i (X_i X_{i+1} + Y_i Y_{i+1}) / 2, which only swaps 0s and 1s and
  so never leaves the weight-k subspace. Every sample satisfies the cardinality constraint.
"""

from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Parameter
from qiskit.circuit.library import RYGate, qaoa_ansatz
from qiskit.quantum_info import SparsePauliOp

from app.quantum.qubo import QUBO

# Transpile to a hardware-like basis so depth / two-qubit-gate counts are meaningful.
METRIC_BASIS = ["rz", "sx", "x", "cx"]


@dataclass
class CostHamiltonian:
    operator: SparsePauliOp  # scaled so the largest |coefficient| is 1
    scale: float  # original = scale * operator (+ offset)
    offset: float


def cost_hamiltonian(qubo: QUBO) -> CostHamiltonian:
    h, J, offset = qubo.to_ising()
    terms: list[tuple[str, list[int], float]] = [
        ("Z", [i], float(v)) for i, v in enumerate(h) if abs(v) > 1e-12
    ]
    terms += [("ZZ", [i, j], float(v)) for (i, j), v in J.items() if abs(v) > 1e-12]
    scale = max((abs(c) for *_, c in terms), default=1.0) or 1.0
    if not terms:  # constant QUBO: keep a valid (zero) operator on n qubits
        terms = [("Z", [0], 0.0)]
    operator = SparsePauliOp.from_sparse_list(
        [(p, idx, c / scale) for p, idx, c in terms], num_qubits=qubo.num_vars
    ).simplify(atol=0)
    return CostHamiltonian(operator=operator, scale=scale, offset=offset)


def _scs(n: int, k: int) -> QuantumCircuit:
    """Split & Cyclic Shift unitary SCS_{n,k} of Baertschi & Eidenbenz (2019)."""
    qc = QuantumCircuit(n)
    qc.cx(n - 2, n - 1)
    qc.append(RYGate(2 * np.arccos(np.sqrt(1 / n))).control(1), [n - 1, n - 2])
    qc.cx(n - 2, n - 1)
    for l in range(2, k + 1):  # noqa: E741 - notation of the paper
        qc.cx(n - l - 1, n - 1)
        qc.append(RYGate(2 * np.arccos(np.sqrt(l / n))).control(2), [n - 1, n - l, n - l - 1])
        qc.cx(n - l - 1, n - 1)
    return qc


def dicke_state(n: int, k: int) -> QuantumCircuit:
    """Deterministic O(nk)-gate preparation of |D(n,k)> (Baertschi & Eidenbenz, 2019)."""
    if not 0 <= k <= n:
        raise ValueError("need 0 <= k <= n")
    qc = QuantumCircuit(n, name=f"Dicke({n},{k})")
    if k == 0:
        return qc
    qc.x(range(n - k, n))
    if k == n:
        return qc
    for l in range(n, k, -1):  # noqa: E741
        qc.compose(_scs(l, k), qubits=range(l), inplace=True)
    for l in range(k, 1, -1):  # noqa: E741
        qc.compose(_scs(l, l - 1), qubits=range(l), inplace=True)
    return qc


def ring_xy_mixer(n: int) -> SparsePauliOp:
    pairs = [(i, (i + 1) % n) for i in range(n)] if n > 2 else [(0, 1)]
    terms = [(p, [i, j], 0.5) for i, j in pairs for p in ("XX", "YY")]
    return SparsePauliOp.from_sparse_list(terms, num_qubits=n)


@dataclass
class QAOACircuit:
    ansatz: QuantumCircuit  # parameterized, no measurements
    betas: list[Parameter]
    gammas: list[Parameter]
    reps: int
    mixer: str

    def ordered_parameters(self) -> list[Parameter]:
        return [*self.gammas, *self.betas]


def build_qaoa_circuit(
    hamiltonian: CostHamiltonian, reps: int, mixer: str = "x", hamming_weight: int | None = None
) -> QAOACircuit:
    n = hamiltonian.operator.num_qubits
    if mixer == "x":
        ansatz = qaoa_ansatz(cost_operator=hamiltonian.operator, reps=reps, flatten=True)
    elif mixer == "xy":
        if hamming_weight is None:
            raise ValueError("the XY mixer needs the Hamming weight k of the feasible states")
        ansatz = qaoa_ansatz(
            cost_operator=hamiltonian.operator,
            reps=reps,
            initial_state=dicke_state(n, hamming_weight),
            mixer_operator=ring_xy_mixer(n),
            flatten=True,
        )
    else:
        raise ValueError("mixer must be 'x' or 'xy'")
    by_name = {p.name: p for p in ansatz.parameters}
    betas = [by_name[f"β[{i}]"] for i in range(reps)]
    gammas = [by_name[f"γ[{i}]"] for i in range(reps)]
    return QAOACircuit(ansatz=ansatz, betas=betas, gammas=gammas, reps=reps, mixer=mixer)


def circuit_metrics(circuit: QuantumCircuit, seed: int = 0) -> dict[str, int | dict[str, int]]:
    measured = circuit.copy()
    measured.measure_all()
    compiled = transpile(
        measured, basis_gates=METRIC_BASIS, optimization_level=1, seed_transpiler=seed
    )
    ops = {name: int(count) for name, count in compiled.count_ops().items()}
    return {
        "num_qubits": circuit.num_qubits,
        "depth": int(compiled.depth()),
        "two_qubit_gates": ops.get("cx", 0),
        "gate_counts": ops,
        "num_parameters": circuit.num_parameters,
    }
