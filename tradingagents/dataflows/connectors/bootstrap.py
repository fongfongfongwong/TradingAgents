"""Auto-register all available connectors at startup.

Call ``bootstrap_connectors()`` once during app initialization to populate
the :class:`ConnectorRegistry` singleton with every concrete connector
whose dependencies are importable.
"""

from __future__ import annotations

import logging

from .registry import ConnectorRegistry

logger = logging.getLogger(__name__)


def bootstrap_connectors() -> int:
    """Import and register all connectors, skipping any that fail.

    Returns the number of connectors successfully registered.
    """
    registry = ConnectorRegistry()

    # Each entry: (module_path_relative, class_name)
    _CONNECTORS: list[tuple[str, str]] = [
        (".yfinance_connector", "YFinanceConnector"),
        (".databento_connector", "DatabentoConnector"),
        (".finnhub_connector", "FinnhubConnector"),
        (".fred_connector", "FREDConnector"),
        (".sec_edgar_connector", "SECEdgarConnector"),
        (".cboe_connector", "CBOEConnector"),
        (".fear_greed_connector", "FearGreedConnector"),
        (".aaii_connector", "AAIIConnector"),
        (".apewisdom_connector", "ApeWisdomConnector"),
        (".dbnomics_connector", "DBnomicsConnector"),
        (".polygon_connector", "PolygonConnector"),
        (".alpaca_news_connector", "AlpacaNewsConnector"),
        (".finbert_connector", "FinBERTConnector"),
        (".fmp_connector", "FMPConnector"),
        (".fintel_connector", "FintelConnector"),
        (".gpr_connector", "GPRConnector"),
        (".orats_connector", "ORATSConnector"),
        (".quiver_connector", "QuiverConnector"),
        (".unusual_whales_connector", "UnusualWhalesConnector"),
        (".sec_api_connector", "SECAPIConnector"),
        (".capitaliq_connector", "CapitalIQConnector"),
        (".databento_options_connector", "DatabentoOptionsConnector"),
    ]

    registered = 0
    for module_path, class_name in _CONNECTORS:
        try:
            import importlib

            mod = importlib.import_module(
                module_path, package="tradingagents.dataflows.connectors"
            )
            cls = getattr(mod, class_name)
            connector = cls()

            if connector.name in registry:
                logger.debug("Connector '%s' already registered, skipping", connector.name)
                continue

            registry.register(connector)
            registered += 1
        except Exception as exc:
            logger.debug(
                "Skipping connector %s.%s: %s", module_path, class_name, exc
            )

    logger.info(
        "bootstrap_connectors: registered %d/%d connectors",
        registered,
        len(_CONNECTORS),
    )
    return registered
