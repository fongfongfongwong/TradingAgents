"""Token counting utilities with approximate and precise methods."""

from __future__ import annotations


class TokenCounter:
    """Count tokens in text using approximate or tiktoken-based methods.

    Parameters
    ----------
    method : str
        ``"approximate"`` for fast character-based estimation (len/4),
        ``"tiktoken"`` for precise sub-word counting (falls back to
        approximate if the tiktoken package is not installed).
    """

    def __init__(self, method: str = "approximate") -> None:
        if method not in ("approximate", "tiktoken"):
            raise ValueError(f"Unknown method: {method!r}. Use 'approximate' or 'tiktoken'.")
        self.method = method
        self._encoding = None

        if method == "tiktoken":
            try:
                import tiktoken  # noqa: F401

                self._encoding = tiktoken.encoding_for_model("gpt-4")
            except (ImportError, Exception):
                # Fall back to approximate when tiktoken is unavailable.
                self.method = "approximate"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def count(self, text: str) -> int:
        """Return the estimated token count for *text*."""
        if not text:
            return 0
        if self.method == "tiktoken" and self._encoding is not None:
            return len(self._encoding.encode(text))
        return self._approximate(text)

    def count_messages(self, messages: list[dict]) -> int:
        """Return the total token count across a list of chat messages.

        Each message is expected to have at least a ``"content"`` key.
        An overhead of 4 tokens per message is added to account for
        role/name framing used by chat-completion APIs.
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            total += self.count(content) + self.count(role) + 4  # per-message overhead
        return total

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _approximate(text: str) -> int:
        """Industry-standard approximation: 1 token ~ 4 characters."""
        return max(1, len(text) // 4)
