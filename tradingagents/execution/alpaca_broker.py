"""Alpaca broker stub for future live trading integration."""


class AlpacaBroker:
    """Stub broker with the same interface as PaperBroker for future Alpaca integration."""

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        paper: bool = True,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper

    def submit_order(self, ticker: str, action: str, shares: int, price: float) -> dict:
        raise NotImplementedError("Alpaca integration coming in Phase D")

    def get_position(self, ticker: str) -> dict:
        raise NotImplementedError("Alpaca integration coming in Phase D")

    def get_portfolio(self) -> dict:
        raise NotImplementedError("Alpaca integration coming in Phase D")

    def update_prices(self, prices: dict[str, float]) -> None:
        raise NotImplementedError("Alpaca integration coming in Phase D")

    def close_position(self, ticker: str, price: float) -> dict:
        raise NotImplementedError("Alpaca integration coming in Phase D")

    def get_trade_history(self) -> list[dict]:
        raise NotImplementedError("Alpaca integration coming in Phase D")
