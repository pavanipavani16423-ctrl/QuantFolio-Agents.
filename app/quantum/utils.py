import numpy as np


def qiskit_key_to_bits(key: str, num_qubits: int) -> np.ndarray:
    """Qiskit count keys are little-endian strings (qubit 0 is the rightmost character)."""
    key = key.replace(" ", "").zfill(num_qubits)
    return np.array([int(c) for c in reversed(key)], dtype=np.int8)


def bits_to_string(bits: np.ndarray) -> str:
    """Our display order: variable 0 first."""
    return "".join(str(int(b)) for b in bits)


def index_to_bits(index: int, num_qubits: int) -> np.ndarray:
    return ((index >> np.arange(num_qubits)) & 1).astype(np.int8)


def normalized_ratio(value: float, best: float, worst: float) -> float | None:
    """1.0 at the ground energy, 0.0 at the worst energy (minimization)."""
    if worst - best <= 1e-12:
        return None
    return float(np.clip((worst - value) / (worst - best), 0.0, 1.0))
