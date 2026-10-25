"""Exact NumPy statevector simulation of the two QAOA ansatz families in `circuits`.

The angle-optimization loop evaluates the circuit hundreds of times. A generic gate-by-gate
simulator spends most of that time on the transpiled Dicke-state and XY-mixer gates (about
2,000 CX gates at 20 qubits). This module applies the same unitaries directly:

* cost layer  exp(-i gamma H_C)          -> elementwise phase (H_C is diagonal)
* X mixer     exp(-i beta sum_i X_i)     -> one RX(2 beta) per qubit
* XY mixer    prod_(i,j) exp(-i beta (X_i X_j + Y_i Y_j)/2), ring order (0,1), (1,2), ...
              -> a rotation inside each {|01>, |10>} pair subspace
* Dicke start |D(n,k)>                   -> uniform amplitudes on weight-k basis states

With the XY mixer the state never leaves the weight-k subspace, so only its C(n,k) amplitudes
are stored (184,756 instead of 1,048,576 at n=20, k=10).

`tests/unit/test_quantum.py` checks that the result equals Qiskit Aer's statevector for the
circuit built by `build_qaoa_circuit`. The final shots are still sampled from that circuit
on Aer.
"""

import numpy as np


class FastQAOASimulator:
    def __init__(self, diagonal: np.ndarray, n: int, mixer: str, hamming_weight: int | None):
        self.n = n
        self.mixer = mixer
        index = np.arange(2**n, dtype=np.int64)
        if mixer == "x":
            self.support = index
        elif mixer == "xy":
            weights = np.bitwise_count(index.astype(np.uint64))
            self.support = index[weights == hamming_weight]  # sorted basis indices
            pairs = [(i, (i + 1) % n) for i in range(n)] if n > 2 else [(0, 1)]
            self.pairs = []
            for i, j in pairs:
                s = self.support
                a = np.flatnonzero((((s >> i) & 1) == 0) & (((s >> j) & 1) == 1))
                partner = s[a] ^ (1 << i) ^ (1 << j)
                self.pairs.append((a, np.searchsorted(s, partner)))
        else:
            raise ValueError("mixer must be 'x' or 'xy'")
        # eigenvalues of the (scaled) cost operator on the stored amplitudes
        self.phases = np.asarray(diagonal, dtype=float)[self.support]
        size = self.support.size
        self.initial = np.full(size, 1 / np.sqrt(size), dtype=complex)

    def _x_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        c, s = np.cos(beta), -1j * np.sin(beta)
        for q in range(self.n):
            view = psi.reshape(2 ** (self.n - q - 1), 2, 2**q)
            zero, one = view[:, 0, :].copy(), view[:, 1, :]
            view[:, 0, :] = c * zero + s * one
            view[:, 1, :] = s * zero + c * view[:, 1, :]
        return psi

    def _xy_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        c, s = np.cos(beta), -1j * np.sin(beta)
        for a, b in self.pairs:
            pa, pb = psi[a], psi[b]
            psi[a] = c * pa + s * pb
            psi[b] = s * pa + c * pb
        return psi

    def support_state(self, gammas: np.ndarray, betas: np.ndarray) -> np.ndarray:
        psi = self.initial.copy()
        for gamma, beta in zip(gammas, betas, strict=True):
            psi *= np.exp(-1j * gamma * self.phases)
            psi = self._x_mixer(psi, beta) if self.mixer == "x" else self._xy_mixer(psi, beta)
        return psi

    def support_probabilities(self, gammas: np.ndarray, betas: np.ndarray) -> np.ndarray:
        return np.abs(self.support_state(gammas, betas)) ** 2

    def probabilities(self, gammas: np.ndarray, betas: np.ndarray) -> np.ndarray:
        """Probabilities over all 2^n basis states (zeros outside the support)."""
        full = np.zeros(2**self.n)
        full[self.support] = self.support_probabilities(gammas, betas)
        return full
