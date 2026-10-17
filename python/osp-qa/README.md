# osp-qa

**Layer:** L3. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** Simulator, path coverage, static checks, reproducibility package. Pure.

Internal package; not published.

**Now (task M1):** `build_report(plan, sim_result)` turns an `osp-sim/1` simulation result
(from `web/engine-sim`, run on the server by `osp_runtime.sim_sidecar`) into the
`osp-sim-report/1` coverage and balance report: chi-square checks (`stats.py`, no SciPy)
for assigned conditions and randomiser orders, and warnings for unreachable nodes,
never-taken branch arms, unreached ends, required questions never shown and pages
simulated participants got stuck on. Coverage is `exhaustive` only when every path was
enumerated; otherwise it is labelled `sampled`, with the reasons.
