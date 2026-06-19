"""ARC Macro 2.0 — foundation package.

Phase 0 seed of the architecture in ARCHITECTURE_SOTA.md. Submodules:
  - arc.contracts : typed artifacts (RunManifest, SeriesContract)  [future: arc-contracts]
  - arc.repro     : deterministic seeding + run manifest capture    [future: arc-repro]
  - arc.causal    : leakage-free (point-in-time) transforms         [future: arc-quant/validation, arc-data/feature_store]

These modules are intentionally dependency-light (numpy/pandas/pydantic only) so the
foundation and its leakage canaries run in any environment and gate CI quickly.
"""

__version__ = "0.1.0"
