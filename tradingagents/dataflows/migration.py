"""Migration helpers: wrap legacy vendor functions as connectors.

``LegacyAdapter`` turns a plain ``{method_name: callable}`` dict into a
:class:`BaseConnector` so that existing vendor functions can be consumed
through the new connector framework without rewriting them.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .connectors.base import BaseConnector, ConnectorCategory

logger = logging.getLogger(__name__)


class LegacyAdapter(BaseConnector):
    """Wraps a dict of ``{method_name: callable}`` as a :class:`BaseConnector`.

    Parameters
    ----------
    adapter_name:
        Unique name for this adapter (used as ``connector.name``).
    methods:
        Mapping of method names to their callable implementations.
    adapter_tier:
        Pricing tier (defaults to 1 / free).
    adapter_categories:
        Data categories this adapter provides.
    """

    def __init__(
        self,
        adapter_name: str,
        methods: dict[str, Callable[..., Any]],
        adapter_tier: int = 1,
        adapter_categories: list[ConnectorCategory] | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._name = adapter_name
        self._methods = dict(methods)
        self._tier = adapter_tier
        self._categories = adapter_categories or [ConnectorCategory.MARKET_DATA]

    # -- abstract property implementations ------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def categories(self) -> list[ConnectorCategory]:
        return list(self._categories)

    # -- fetch ----------------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to the wrapped legacy callable based on ``data_type``."""
        data_type = params.get("data_type", "")
        method_name = params.get("method_name", data_type)

        if method_name not in self._methods:
            raise KeyError(
                f"LegacyAdapter '{self._name}' has no method '{method_name}'. "
                f"Available: {list(self._methods.keys())}"
            )

        func = self._methods[method_name]
        extra_args = params.get("extra_args", [])

        # Call the legacy function: func(ticker, *extra_args, **remaining_params)
        remaining = {
            k: v
            for k, v in params.items()
            if k not in ("data_type", "method_name", "extra_args")
        }

        result = func(ticker, *extra_args, **remaining)

        # Normalise to dict if the legacy function returns a string
        if isinstance(result, str):
            return {"data": result, "source": self._name, "method": method_name}
        if isinstance(result, dict):
            result.setdefault("source", self._name)
            result.setdefault("method", method_name)
            return result
        return {"data": result, "source": self._name, "method": method_name}

    # -- convenience ----------------------------------------------------------

    @property
    def method_names(self) -> list[str]:
        """Return the list of wrapped method names."""
        return list(self._methods.keys())


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Category mapping for the legacy vendor groups
_VENDOR_GROUP_CATEGORIES: dict[str, list[ConnectorCategory]] = {
    "get_stock_data": [ConnectorCategory.MARKET_DATA],
    "get_indicators": [ConnectorCategory.MARKET_DATA],
    "get_fundamentals": [ConnectorCategory.FUNDAMENTALS],
    "get_balance_sheet": [ConnectorCategory.FUNDAMENTALS],
    "get_cashflow": [ConnectorCategory.FUNDAMENTALS],
    "get_income_statement": [ConnectorCategory.FUNDAMENTALS],
    "get_news": [ConnectorCategory.NEWS],
    "get_global_news": [ConnectorCategory.NEWS],
    "get_insider_transactions": [ConnectorCategory.FUNDAMENTALS],
}


def create_legacy_adapters() -> dict[str, LegacyAdapter]:
    """Create :class:`LegacyAdapter` instances from ``VENDOR_METHODS`` in interface.py.

    Returns a dict of ``{vendor_name: LegacyAdapter}``, one adapter per
    vendor, each wrapping all methods that vendor supports.
    """
    from .interface import VENDOR_METHODS

    # Invert: vendor -> {method_name: callable}
    vendor_methods: dict[str, dict[str, Callable[..., Any]]] = {}
    vendor_categories: dict[str, set[ConnectorCategory]] = {}

    for method_name, vendors in VENDOR_METHODS.items():
        for vendor_name, impl in vendors.items():
            func = impl[0] if isinstance(impl, list) else impl
            vendor_methods.setdefault(vendor_name, {})[method_name] = func
            cats = _VENDOR_GROUP_CATEGORIES.get(method_name, [ConnectorCategory.MARKET_DATA])
            vendor_categories.setdefault(vendor_name, set()).update(cats)

    adapters: dict[str, LegacyAdapter] = {}
    for vendor_name, methods in vendor_methods.items():
        adapters[vendor_name] = LegacyAdapter(
            adapter_name=f"legacy_{vendor_name}",
            methods=methods,
            adapter_tier=1,
            adapter_categories=list(vendor_categories.get(vendor_name, set())),
        )

    logger.info(
        "Created %d legacy adapters: %s",
        len(adapters),
        list(adapters.keys()),
    )
    return adapters
