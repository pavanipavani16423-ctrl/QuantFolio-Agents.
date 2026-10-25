"""Local Qiskit Aer simulation. No paid hardware or network access is needed."""

from collections.abc import Mapping

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Parameter
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2

Binding = Mapping[Parameter, float]


class AerBackend:
    name = "qiskit_aer"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self._simulator = AerSimulator(method="statevector", seed_simulator=seed)

    def compile(self, circuit: QuantumCircuit) -> QuantumCircuit:
        # No coupling map: qubit i stays qubit i, so statevector indices keep their meaning.
        return transpile(circuit, self._simulator, optimization_level=1, seed_transpiler=self.seed)

    def probabilities(self, compiled: QuantumCircuit, binding: Binding) -> np.ndarray:
        """Exact |amplitude|^2 for every basis state (index k: qubit i = bit i of k)."""
        bound = compiled.assign_parameters(dict(binding), inplace=False)
        bound.save_statevector()
        state = self._simulator.run(bound).result().get_statevector()
        return np.abs(np.asarray(state)) ** 2

    def compile_measured(self, circuit: QuantumCircuit) -> QuantumCircuit:
        measured = circuit.copy()
        measured.measure_all()
        return transpile(measured, self._simulator, optimization_level=1, seed_transpiler=self.seed)

    def sample(
        self, compiled_measured: QuantumCircuit, binding: Binding, shots: int
    ) -> dict[str, int]:
        values = [binding[p] for p in compiled_measured.parameters]
        sampler = SamplerV2(seed=self.seed)
        result = sampler.run([(compiled_measured, values)], shots=shots).result()[0]
        return result.data.meas.get_counts()
