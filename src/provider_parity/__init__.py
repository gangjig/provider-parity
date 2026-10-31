"""provider-parity: is the same model from a different provider the same model?"""

from .compare import (
    ParityReport,
    PairComparison,
    ProviderSummary,
    build_insights,
    compare,
    normalize_text,
)
from .demo import demo_records
from .probes import Checker, Probe, load_probes, run_checker
from .runner import (
    ProviderConfig,
    Record,
    load_providers,
    load_records,
    run_probes,
)

__version__ = "0.1.0"

__all__ = [
    "Checker",
    "PairComparison",
    "ParityReport",
    "Probe",
    "ProviderConfig",
    "ProviderSummary",
    "Record",
    "build_insights",
    "compare",
    "demo_records",
    "load_probes",
    "load_providers",
    "load_records",
    "normalize_text",
    "run_checker",
    "run_probes",
    "__version__",
]
