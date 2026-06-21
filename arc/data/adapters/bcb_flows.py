"""BCB external-flow series (BPM6 financial account) — the missing 'idp_flow' /
'portfolio_flow' inputs the engine wires but whose CSVs were absent.

These are *monthly* balance-of-payments flows published by the BCB under the BPM6
framework and exposed through the SAME public SGS endpoint the rest of the BCB data
uses (https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados). This module is a
THIN catalog + month-end normalizer: it does NOT re-implement the HTTP/parse logic —
it delegates to ``BcbSgsAdapter.parse`` (which already handles BR dates + comma
decimals). Network stays lazy (only ``BcbSgsAdapter.fetch_raw`` touches the wire).

Series chosen (evidence: BCB Portal de Dados Abertos dataset titles/URLs):
  - IDP_FLOW       -> SGS 22885  "Investimentos diretos no país - IDP - mensal - líquido"
  - PORTFOLIO_FLOW -> SGS 22924  "Investimentos em carteira - passivos - mensal - líquido"
                      (the aggregate of equities + debt securities + funds, net)

Both are monthly, in USD millions (US$ milhões), BPM6, history from Jan/1995.
Net (líquido) is used so the engine's rolling-sum z-score reflects net inflows
(positive) vs outflows (negative) — the FX-relevant signal.

FX flow ("fluxo cambial contratado") is intentionally NOT included: the BCB does not
publish it as a stable SGS code — it is a separate weekly/monthly press release with
its own statistics file. See ``FX_FLOW_NOTE`` and the final report for the caveat.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.bcb_sgs import BASE_URL, BcbSgsAdapter

# BPM6 monthly external-sector flows are published "up to four weeks after the reference
# period"; we floor the publication lag at 30 calendar days (same convention as the debt
# series in the catalog). The bitemporal store still prefers a true publish_ts when given.
_BPM6_LAG_DAYS = 30
_BPM6_UNIT = "usd_mn"  # US$ millions

# The catalog of flow series. Each row is the data-contract seed for one series.
# ``name`` is the engine-facing series_id (matches macro_risk_os_v2 load_series keys).
FLOW_SERIES: list[dict[str, Any]] = [
    {
        "name": "IDP_FLOW",
        "sgs_code": "22885",
        "unit": _BPM6_UNIT,
        "lag_days": _BPM6_LAG_DAYS,
        "description": "Foreign direct investment in Brazil (IDP), monthly net, USD mn (SGS 22885, BPM6)",
    },
    {
        "name": "PORTFOLIO_FLOW",
        "sgs_code": "22924",
        "unit": _BPM6_UNIT,
        "lag_days": _BPM6_LAG_DAYS,
        "description": (
            "Foreign portfolio investment liabilities (equities+debt+funds), monthly net, "
            "USD mn (SGS 22924, BPM6)"
        ),
    },
]

# Documented-but-unavailable: BCB FX flow ("fluxo cambial") has no stable SGS code.
FX_FLOW_NOTE = (
    "BCB 'fluxo cambial contratado' (weekly/monthly contracted FX flow) is NOT a SGS "
    "series; it is a standalone press release/statistics file. It cannot be fetched via "
    "the SGS endpoint, so it is excluded from FLOW_SERIES. If needed, a dedicated adapter "
    "must scrape the BCB FX-flow statistics page (out of scope for this SGS-delegating module)."
)


def flow_contracts() -> list[SeriesContract]:
    """Build the :class:`SeriesContract` for each flow series.

    Pure (no network). These can be merged into the master ``_CATALOG`` so the standard
    BcbSgsAdapter ingest path (``fetch`` -> publication-lag-stamped Observations) works.
    valid_min/valid_max are deliberately wide and symmetric: net BPM6 flows can be large
    and negative (capital flight) or positive (strong months); +/- 50_000 USD mn comfortably
    bounds Brazil's monthly history while still catching unit/parse blowups.
    """
    contracts: list[SeriesContract] = []
    for row in FLOW_SERIES:
        contracts.append(
            SeriesContract(
                series_id=row["name"],
                source="BCB_SGS",
                source_code=row["sgs_code"],
                frequency="M",
                unit=row["unit"],
                publication_lag_days=row["lag_days"],
                valid_min=-50_000.0,
                valid_max=50_000.0,
                allowed_revision_abs=5_000.0,
                license="BCB open data",
                description=row["description"],
            )
        )
    return contracts


def to_month_end(series: pd.Series) -> pd.Series:
    """Snap an event-time-indexed flow Series to month-end stamps.

    BCB returns BPM6 monthly observations dated on the FIRST day of the reference month
    (dd=01). The engine aligns everything to month-end (``to_monthly``), so we normalize
    here to the period's month-end timestamp and keep the LAST value per month (defensive
    against any intra-month duplicates). Pure; no network.
    """
    if series.empty:
        return pd.Series(dtype="float64")
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    # collapse to one value per calendar month, then stamp at month-end
    s = s.groupby(s.index.to_period("M")).last()
    s.index = s.index.to_timestamp(how="end").normalize()
    s.index.name = series.index.name
    return s


def parse_flow(raw: Any) -> pd.Series:
    """Parse a raw SGS payload into a month-end flow Series.

    Delegates the BR-date / comma-decimal parsing to ``BcbSgsAdapter.parse`` (single source
    of truth), then applies :func:`to_month_end`. Pure; takes already-fetched ``raw``."""
    parsed = BcbSgsAdapter().parse(raw)
    return to_month_end(parsed)


def build_monthly_flow(
    name: str,
    *,
    adapter: Optional[BcbSgsAdapter] = None,
    since=None,
) -> pd.Series:
    """Fetch + parse one flow series to a tidy month-end Series (USD mn).

    This is the only function that touches the network, and it does so lazily via the
    existing ``BcbSgsAdapter`` (which imports ``requests`` lazily). Returns an empty Series
    for an unknown ``name`` is NOT desired — we raise, to fail loud on a typo'd series id.
    """
    contract = _contract_by_name(name)
    a = adapter or BcbSgsAdapter()
    raw = a.fetch_raw(contract, since)
    return parse_flow(raw)


def _contract_by_name(name: str) -> SeriesContract:
    for c in flow_contracts():
        if c.series_id == name:
            return c
    have = [r["name"] for r in FLOW_SERIES]
    raise KeyError(f"no BCB flow series '{name}' (have: {have})")


def sgs_is_up(timeout: float = 8) -> bool:
    """Cheap, side-effect-free health probe of the BCB SGS endpoint.

    Probes a known SMALL slice of a real flow series (the IDP code, last 1 obs) and
    returns ``True`` only on an HTTP 200 whose body parses as JSON. Any failure — 502,
    timeout, connection error, non-200, or unparseable body — returns ``False`` so the
    caller can route to the provenance-verified IPEADATA fallback while SGS is down.

    Network stays lazy (``requests`` imported inside). Does NOT raise: a probe is meant
    to be observable, not fatal. The moment ``api.bcb.gov.br`` recovers this flips back to
    ``True`` and the canonical SGS route is used again.
    """
    import requests  # lazy: keeps module import light for tests/CI

    code = _contract_by_name("IDP_FLOW").source_code  # 22885 — a real, small flow series
    url = BASE_URL.format(code=code)
    try:
        r = requests.get(url, params={"formato": "json", "ultimos": "1"}, timeout=timeout)
        if r.status_code != 200:
            return False
        r.json()  # must parse as JSON to count as a healthy canonical response
        return True
    except Exception:  # noqa: BLE001 — any error (502/timeout/parse) means SGS is down
        return False


# ---------------------------------------------------------------------------
# IPEADATA fallback (used ONLY when the primary SGS route is down).
#
# The BCB SGS endpoint is the primary source. When it is unreachable (e.g. the
# 502s observed on api.bcb.gov.br for 22885/22924), the SAME BPM6 balance-of-
# payments flows are *also* re-published by IPEADATA — but IPEADATA mirrors them
# under its own SERCODIGO. We must NEVER adopt an IPEADATA series unless its
# metadata UNAMBIGUOUSLY confirms it is the same economic concept *and* that BCB
# (Bacen) is the source. An unconfirmable match is a FAILURE, not a substitution.
#
# Candidate SERCODIGOs (verified against the IPEADATA odata4 Metadados endpoint):
#   IDP_FLOW       -> BPAG12_IDP12  "Balanco de pagamentos - investimento direto pais - saldo"
#                     == SGS 22885 "Investimentos diretos no pais - IDP - mensal - liquido"
#   PORTFOLIO_FLOW -> BPAG12_ICP12  "Balanco de pagamentos - investimento carteira - passivos - saldo"
#                     == SGS 22924 "Investimentos em carteira - passivos - mensal - liquido"
# Both are FNTSIGLA "Bacen/BP (BPM6)", PERNOME "Mensal", UNINOME "US$" (milhoes),
# monthly history from Jan/1995 — i.e. the identical BPM6 net flow the SGS codes carry.
_IPEADATA_BASE = "http://www.ipeadata.gov.br/api/odata4/"

# Per flow: ordered candidate SERCODIGOs + the metadata signature each must satisfy.
# ``must_all`` tokens (lowercased, accent-stripped) MUST all appear in SERNOME;
# ``must_none`` tokens disqualify a near-miss (e.g. the *exterior* / *ativos* mirror
# series, which are the opposite economic concept and must never be substituted).
_IPEADATA_FLOW_MAP: dict[str, dict[str, Any]] = {
    "IDP_FLOW": {
        "codes": ["BPAG12_IDP12"],
        "must_all": ["investimento direto", "pais", "saldo"],
        "must_none": ["exterior", "renda", "ingressos", "saidas", "intercompanhia", "participacao"],
        "concept": "BPM6 net foreign direct investment in Brazil (IDP), monthly",
        "sgs_equivalent": "22885",
    },
    "PORTFOLIO_FLOW": {
        "codes": ["BPAG12_ICP12"],
        "must_all": ["investimento carteira", "passivos", "saldo"],
        "must_none": ["ativos", "renda", "ingressos", "saidas"],
        "concept": "BPM6 net foreign portfolio investment liabilities, monthly",
        "sgs_equivalent": "22924",
    },
}

# Accept only when the source is unambiguously the Brazilian central bank.
_IPEADATA_SOURCE_TOKENS = ("bacen", "banco central do brasil", "bcb")
# ...and only the BPM6 balance-of-payments framework (not PII/old BPM5 mirrors).
_IPEADATA_BPM6_TOKENS = ("bpm6", "balanco de pagamentos", "balano de pagamentos")


def _strip_accents(text: str) -> str:
    """Lowercase + drop diacritics so token checks survive IPEADATA's mixed encoding."""
    import unicodedata

    norm = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def _ipeadata_get(url: str, *, timeout: float) -> Any:
    """Lazy GET + JSON parse of an IPEADATA odata4 URL (best-effort decode)."""
    import json
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "arc-macro/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted gov host)
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _verify_ipeadata_metadata(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Confirm an IPEADATA metadata row is the SAME BCB BPM6 series we want.

    Pure (takes already-fetched metadata). Raises ``ValueError`` if the source is not
    Bacen/BCB, if it is not the BPM6 balance-of-payments framework, or if SERNOME does
    not match the required IDP / portfolio-liabilities concept (missing a required token
    or carrying a disqualifying one). Returns the provenance dict on success — so a
    wrong-source/wrong-name series is REJECTED, never silently substituted."""
    spec = _IPEADATA_FLOW_MAP[name]
    sernome = meta.get("SERNOME", "")
    fnt = " ".join(str(meta.get(k, "")) for k in ("FNTSIGLA", "FNTNOME", "FNTURL"))
    name_norm = _strip_accents(sernome)
    fnt_norm = _strip_accents(fnt)

    if not any(tok in fnt_norm for tok in _IPEADATA_SOURCE_TOKENS):
        raise ValueError(
            f"{name}: IPEADATA source not confirmed as BCB/Bacen "
            f"(FONTE={meta.get('FNTSIGLA')!r}/{meta.get('FNTNOME')!r}); refusing to substitute"
        )
    if not any(tok in fnt_norm or tok in name_norm for tok in _IPEADATA_BPM6_TOKENS):
        raise ValueError(
            f"{name}: IPEADATA series not confirmed as BPM6 balance-of-payments "
            f"(FONTE={meta.get('FNTSIGLA')!r}, NOME={sernome!r}); refusing to substitute"
        )
    missing = [tok for tok in spec["must_all"] if _strip_accents(tok) not in name_norm]
    if missing:
        raise ValueError(
            f"{name}: IPEADATA SERNOME {sernome!r} does not match the {spec['concept']} "
            f"definition (missing tokens: {missing}); refusing to substitute"
        )
    bad = [tok for tok in spec["must_none"] if _strip_accents(tok) in name_norm]
    if bad:
        raise ValueError(
            f"{name}: IPEADATA SERNOME {sernome!r} matches a DIFFERENT concept "
            f"(disqualifying tokens: {bad}); refusing to substitute"
        )
    return {
        "route": "IPEADATA",
        "series_id": name,
        "sercodigo": meta.get("SERCODIGO"),
        "sernome": sernome,
        "fonte": meta.get("FNTSIGLA"),
        "fonte_nome": meta.get("FNTNOME"),
        "periodicidade": meta.get("PERNOME"),
        "unidade": _join_unit(meta),
        "sgs_equivalent": spec["sgs_equivalent"],
        "concept": spec["concept"],
        "verified": True,
    }


def _join_unit(meta: dict[str, Any]) -> str:
    """IPEADATA splits unit across UNINOME ('US$') + MULNOME ('milhoes'); join them."""
    parts = [str(meta.get("UNINOME", "")).strip(), str(meta.get("MULNOME", "")).strip()]
    return " ".join(p for p in parts if p)


def _parse_ipeadata_values(values: Any) -> pd.Series:
    """IPEADATA ValoresSerie payload -> month-end float Series.

    Each row is ``{'VALDATA': ISO8601, 'VALVALOR': float, ...}`` (values dated on the
    FIRST of the reference month, like SGS). We coerce to float, index by VALDATA, drop
    NaN, then snap to month-end via :func:`to_month_end`. Pure; no network."""
    if not values:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(values)
    if "VALDATA" not in df.columns or "VALVALOR" not in df.columns:
        raise ValueError(f"IPEADATA values payload missing VALDATA/VALVALOR (cols={list(df.columns)})")
    idx = pd.to_datetime(df["VALDATA"], utc=True, errors="coerce").dt.tz_localize(None)
    vals = pd.to_numeric(df["VALVALOR"], errors="coerce")
    s = pd.Series(vals.values, index=idx).dropna()
    s = s[s.index.notna()].sort_index()
    return to_month_end(s)


def fetch_flow_ipeadata(name: str, *, timeout: float = 15) -> tuple[pd.Series, dict[str, Any]]:
    """Fallback fetch of one BPM6 flow from IPEADATA — ONLY if the match is confirmed.

    Used when the primary BCB SGS route (:func:`build_monthly_flow`) is down. IPEADATA
    re-publishes the SAME BPM6 balance-of-payments flows under its own SERCODIGO; this
    function maps ``IDP_FLOW`` / ``PORTFOLIO_FLOW`` to the candidate IPEADATA codes,
    VERIFIES via the Metadados endpoint that the source is Bacen/BCB and the SERNOME
    matches the BPM6 IDP / portfolio-liabilities definition (recording FONTE/UNIDADE/
    PERNOME provenance), then fetches the Valores endpoint and normalizes to a month-end
    Series (reusing :func:`to_month_end`).

    Returns ``(series, provenance_dict)``. Network stays lazy (urllib imported inside).
    Raises ``KeyError`` for an unknown ``name`` and ``ValueError`` if the match cannot be
    confirmed — it NEVER returns a different series. The SGS path remains primary and will
    work again when BCB recovers."""
    if name not in _IPEADATA_FLOW_MAP:
        have = sorted(_IPEADATA_FLOW_MAP)
        raise KeyError(f"no IPEADATA fallback mapping for flow series '{name}' (have: {have})")

    spec = _IPEADATA_FLOW_MAP[name]
    errors: list[str] = []
    for code in spec["codes"]:
        meta_url = _IPEADATA_BASE + f"Metadados('{code}')"
        try:
            meta_payload = _ipeadata_get(meta_url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — network/parse: record and try next candidate
            errors.append(f"{code}: metadata fetch failed ({type(exc).__name__}: {exc})")
            continue
        meta = _coerce_single(meta_payload)
        if not meta:
            errors.append(f"{code}: empty metadata payload")
            continue
        # VERIFY first; only fetch values once the concept+source are confirmed.
        provenance = _verify_ipeadata_metadata(name, meta)

        val_url = _IPEADATA_BASE + f"ValoresSerie(SERCODIGO='{code}')"
        try:
            val_payload = _ipeadata_get(val_url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code}: values fetch failed ({type(exc).__name__}: {exc})")
            continue
        values = val_payload.get("value", val_payload) if isinstance(val_payload, dict) else val_payload
        series = _parse_ipeadata_values(values)
        if series.empty:
            errors.append(f"{code}: confirmed match but empty value series")
            continue
        provenance["n"] = int(len(series))
        provenance["range"] = f"{series.index[0].date()}..{series.index[-1].date()}"
        series.name = name
        return series, provenance

    raise ValueError(
        f"{name}: could not confirm an IPEADATA BPM6 match; not substituting. Tried "
        f"{spec['codes']}. Reasons: " + " | ".join(errors)
    )


def _coerce_single(payload: Any) -> dict[str, Any]:
    """Metadados may return a bare entity or an odata ``{'value': [...]}`` collection."""
    if isinstance(payload, dict):
        if "value" in payload and isinstance(payload["value"], list):
            return payload["value"][0] if payload["value"] else {}
        return payload
    if isinstance(payload, list):
        return payload[0] if payload else {}
    return {}
