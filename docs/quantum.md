# The quantum part: QAOA for stock selection

## The problem

Each client mandate says "hold exactly *k* stocks" (8, 10 or 12) out of the *n* allowed ones
(18-20 after exclusions). Choosing which *k* is a combinatorial problem: C(20,10) = 184,756
possible portfolios. It is a natural fit for a quantum optimizer because every decision is
yes/no: **one qubit per stock**, `1` = hold it.

## Formulation (QUBO)

With expected returns `mu` and the Ledoit-Wolf covariance `Sigma` (estimated on the training
window), and equal weights `1/k` for the selection step, the utility of a set `S` is

```
U(S) = (1/k) sum_{i in S} mu_i  -  lambda (1/k^2) sum_{i,j in S} Sigma_ij
```

Minimizing `E(x) = -U(x)` over `x in {0,1}^n` is a QUBO:

```
E(x) = sum_i (-mu_i/k + lambda Sigma_ii/k^2) x_i  +  sum_{i<j} (2 lambda Sigma_ij / k^2) x_i x_j
```

`lambda` is the client's risk-aversion coefficient from the mandate. For the standard X-mixer
QAOA the cardinality constraint is added as a penalty `A (sum_i x_i - k)^2`, with `A` larger
than any single-variable gain. After selection, every method gets the **same** weight
optimizer (long-only mean-variance with the mandate's position, sector and volatility
limits), so the comparison isolates the selection step.

Code: `app/quant/portfolio.py` (`SelectionProblem.qubo`).

## Two QAOA designs

| | Standard QAOA (`x`) | Constraint-preserving QAOA (`xy`, default) |
|---|---|---|
| start state | `|+>^n` (all 2^n bitstrings) | Dicke state `|D(n,k)>` (all weight-k bitstrings) |
| mixer | `sum_i X_i` | ring XY mixer `sum_i (X_i X_{i+1} + Y_i Y_{i+1})/2` |
| constraint | penalty term in the cost | built in: the state never leaves weight k |
| reference | Farhi, Goldstone, Gutmann (2014) | Hadfield et al. (2019), Wang et al. (2020) |

The Dicke state is prepared with the deterministic O(nk) circuit of Baertschi & Eidenbenz
(2019) (`app/quantum/circuits.py::dicke_state`); a unit test checks it is uniform over all
weight-k states for several (n, k).

Angles are optimized with COBYLA starting from a linear-ramp schedule (an annealing-like
initial point), on the exact expectation value; the final state is measured with 2,048 shots.

## Simulation and how it is validated

Everything runs on a laptop CPU. The transpiled 20-qubit XY circuit has about 2,000 CX gates,
so a gate-by-gate simulation takes ~1 s per circuit evaluation. For the angle-optimization
loop, `app/quantum/fastsim.py` applies the **same unitaries** directly:

* cost layer `exp(-i gamma H_C)` as an elementwise phase (H_C is diagonal),
* X mixer as one RX(2 beta) per qubit,
* XY mixer as a rotation inside each `{|01>, |10>}` pair subspace, in the same ring order,
* and, for the XY mixer, only the C(n,k) amplitudes of the feasible subspace are stored
  (184,756 instead of 1,048,576 at n=20).

`tests/unit/test_quantum.py` checks that these probabilities equal Qiskit Aer's statevector
of the circuit built by Qiskit's `qaoa_ansatz` (max difference < 1e-9). The **final shots
are sampled from the real circuit on Qiskit Aer**. Circuit depth and gate counts are
reported after transpiling to `{rz, sx, x, cx}`.

## Quality metrics

Because n <= 20, the energy of every basis state can be enumerated, so the reported metrics
are exact, not estimated:

* `gap` - utility shortfall of QAOA's best valid sample vs exhaustive search (0 = optimal),
* `approximation ratio` - over feasible states, (E_max - <E>) / (E_max - E_min),
* `P(best)` - probability of measuring an optimal portfolio,
* `P(valid)` - probability of measuring exactly k stocks (1 for the XY mixer).

## What this does and does not show

* It shows how a quantum optimizer plugs into a real agent workflow (an MCP tool with
  resource caps), and measures it honestly against an exact classical answer.
* It does **not** show quantum advantage. At 18-20 assets exhaustive search takes well
  under a second; the simulator is slower than the classical solver, as expected. The
  probability of measuring the optimum directly is small (well under 1%); QAOA finds the
  optimum here because the best of 2,048 shots is kept.
* Real hardware would add noise; the XY circuit's depth (~2,000 CX) is beyond today's
  noisy devices without error mitigation.

Results: see [evaluation.md](evaluation.md).
