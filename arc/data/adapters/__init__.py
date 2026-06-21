"""Source adapters: fetch raw provider data -> parse to a clean event-time Series ->
emit bitemporal Observations (with the contract's publication lag applied).

Refactor of the monolithic data_collector.py: one adapter per source, NO merging /
rescaling / calibration here (those leak; they belong in causal feature transforms). The
network call lives in ``fetch_raw``; ``parse`` is pure and unit-tested with fixtures.
"""

from arc.data.adapters.base import Adapter
from arc.data.adapters.bcb_sgs import BcbSgsAdapter
from arc.data.adapters.bcb_focus import BcbFocusAdapter
from arc.data.adapters.fred import FredAdapter
from arc.data.adapters.tesouro_ntnb import TesouroNtnbAdapter
from arc.data.adapters.cftc_cot import CftcCotAdapter
from arc.data.adapters.bcb_flows import FLOW_SERIES, build_monthly_flow, flow_contracts
from arc.data.adapters.csv_bridge import observations_from_csv

__all__ = [
    "Adapter", "BcbSgsAdapter", "BcbFocusAdapter", "FredAdapter",
    "TesouroNtnbAdapter", "CftcCotAdapter",
    "FLOW_SERIES", "build_monthly_flow", "flow_contracts",
    "observations_from_csv",
]
