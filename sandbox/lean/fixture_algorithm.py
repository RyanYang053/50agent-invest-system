"""Fixed synthetic LEAN developer fixture. Not an investment strategy."""
from AlgorithmImports import *
import json


class AtlasLeanAccountingFixture(QCAlgorithm):
    def initialize(self):
        if self.live_mode:
            raise RuntimeError("Atlas fixture forbids live mode")
        self.set_start_date(2020, 1, 2)
        self.set_end_date(2020, 1, 3)
        self.set_cash(10000)
        security = self.add_equity("ATLASFICT", Resolution.MINUTE, fill_forward=False)
        security.set_data_normalization_mode(DataNormalizationMode.RAW)
        security.set_fee_model(ConstantFeeModel(1, "USD"))
        security.set_slippage_model(ConstantSlippageModel(0))
        self.symbol = security.symbol
        self.set_benchmark(self.symbol)
        self.stage = 0
        self.bars = {}
        self.fills = []

    def on_data(self, data):
        if not data.bars.contains_key(self.symbol):
            return
        bar = data.bars[self.symbol]
        date = self.time.strftime("%Y-%m-%d")
        price = float(bar.close)
        item = self.bars.setdefault(date, {"count": 0, "close_min": price, "close_max": price})
        item["count"] += 1
        item["close_min"] = min(item["close_min"], price)
        item["close_max"] = max(item["close_max"], price)
        if self.stage == 0 and self.time.day == 2:
            self.stage = 1
            self.market_order(self.symbol, 10, tag="synthetic-fixture-buy")
        elif self.stage == 1 and self.time.day == 3 and self.portfolio[self.symbol].quantity == 10:
            self.stage = 2
            self.market_order(self.symbol, -10, tag="synthetic-fixture-sell")

    def on_order_event(self, order_event):
        if order_event.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            return
        self.fills.append({
            "order_id": int(order_event.order_id),
            "symbol": str(order_event.symbol.value),
            "quantity": float(order_event.fill_quantity),
            "price": float(order_event.fill_price),
            "fee": float(order_event.order_fee.value.amount),
            "fee_currency": str(order_event.order_fee.value.currency),
            "date": self.time.strftime("%Y-%m-%d")
        })

    def on_end_of_algorithm(self):
        receipt = {
            "kind": "ATLAS_LEAN_SYNTHETIC_ACCOUNTING_V1",
            "live_mode": bool(self.live_mode),
            "bars": self.bars,
            "fills": self.fills,
            "ending_quantity": float(self.portfolio[self.symbol].quantity),
            "ending_cash": float(self.portfolio.cash_book["USD"].amount),
            "ending_nav": float(self.portfolio.total_portfolio_value)
        }
        self.debug("ATLAS_LEAN_RECEIPT:" + json.dumps(receipt, separators=(",", ":"), allow_nan=False))
