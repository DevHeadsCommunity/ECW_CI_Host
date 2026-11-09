"""ECW automation without a dependency on a particular CI provider."""

from .client import ECWClient, ECWError
from .config import RunConfig
from .runner import RunResult, run_test

__version__ = "0.1.0"
__all__ = ["ECWClient", "ECWError", "RunConfig", "RunResult", "run_test"]
