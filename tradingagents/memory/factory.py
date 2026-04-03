"""Factory function for creating memory backends.

Usage::

    from tradingagents.memory.factory import create_memory

    mem = create_memory("bull_memory", config)
"""

from __future__ import annotations

from tradingagents.agents.utils.memory import FinancialSituationMemory


def create_memory(name: str, config: dict = None) -> FinancialSituationMemory:
    """Create a memory instance based on configuration.

    Parameters
    ----------
    name : str
        Identifier for this memory instance (e.g. "bull_memory").
    config : dict, optional
        The full TradingAgents config dict.  The ``memory_backend`` key
        determines which backend is returned:

        - ``"bm25"`` (default) -- original ``FinancialSituationMemory``
        - ``"hybrid"`` -- ``HybridFinancialMemory`` (BM25 + vector via RRF)

        If the hybrid backend cannot be imported (e.g. missing sklearn),
        the factory silently falls back to the BM25 backend.

    Returns
    -------
    FinancialSituationMemory or HybridFinancialMemory
        Both expose the same public API: ``add_situations``,
        ``get_memories``, and ``clear``.
    """
    cfg = config or {}
    backend = cfg.get("memory_backend", "bm25")

    if backend == "hybrid":
        try:
            from tradingagents.memory.financial_memory import HybridFinancialMemory

            return HybridFinancialMemory(name, config=cfg)
        except Exception:
            # Graceful fallback -- missing dependency or import error
            pass

    # Default: original BM25-only memory
    return FinancialSituationMemory(name, config=cfg)
