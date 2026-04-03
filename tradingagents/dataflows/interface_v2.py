"""Interface v2: connector-aware routing with legacy fallback.

``route_to_connector`` is a superset of ``route_to_vendor``.  When no
connectors are registered in the :class:`ConnectorRegistry`, behaviour is
identical to calling ``route_to_vendor`` directly.
"""

from __future__ import annotations

import logging
from typing import Any

from .interface import route_to_vendor, VENDOR_METHODS
from .connectors.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Method-name  ->  (connector_name, data_type) mapping
# ---------------------------------------------------------------------------

METHOD_CONNECTOR_MAP: dict[str, tuple[str, str]] = {
    "get_stock_data": ("yfinance", "ohlcv"),
    "get_indicators": ("yfinance", "indicators"),
    "get_news": ("finnhub", "news"),
    "get_global_news": ("finnhub", "global_news"),
    "get_fundamentals": ("yfinance", "fundamentals"),
    "get_balance_sheet": ("yfinance", "balance_sheet"),
    "get_cashflow": ("yfinance", "cashflow"),
    "get_income_statement": ("yfinance", "income_statement"),
    "get_insider_transactions": ("yfinance", "insider_transactions"),
}


def _try_connector(method: str, *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Attempt to fulfil *method* via a registered connector.

    Returns ``(True, result)`` on success, ``(False, None)`` when no
    suitable connector is available.
    """
    mapping = METHOD_CONNECTOR_MAP.get(method)
    if mapping is None:
        return False, None

    connector_name, data_type = mapping
    registry = ConnectorRegistry()

    if connector_name not in registry:
        return False, None

    connector = registry.get(connector_name)

    # Build params dict expected by BaseConnector.fetch(ticker, params)
    # The first positional arg is typically the ticker.
    ticker = args[0] if args else kwargs.get("ticker", "")
    params: dict[str, Any] = {"data_type": data_type}
    # Forward remaining positional args as a list and merge kwargs
    if len(args) > 1:
        params["extra_args"] = list(args[1:])
    params.update({k: v for k, v in kwargs.items() if k != "ticker"})

    result = connector.fetch(ticker, params)
    return True, result


def route_to_connector(method: str, *args: Any, **kwargs: Any) -> Any:
    """Route a data request through a connector if available, else fall back.

    1. If a connector is registered that handles *method*, delegate to it.
    2. Otherwise, fall back to :func:`route_to_vendor`.

    The return type matches ``route_to_vendor`` (typically ``str | dict``).
    """
    found, result = _try_connector(method, *args, **kwargs)
    if found:
        logger.debug("route_to_connector: '%s' served by connector", method)
        return result

    logger.debug("route_to_connector: '%s' falling back to route_to_vendor", method)
    return route_to_vendor(method, *args, **kwargs)
