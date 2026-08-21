from AlgorithmImports import *


class BuyAndHoldSPY(QCAlgorithm):
    """
    Buy-and-hold SPY baseline for the AFTS project.
    Deploys 100% of capital into SPY on the first bar and holds through
    the entire period. Serves as the benchmark against which every
    Carver-style systematic strategy is measured.
    """

    def initialize(self):
        self.set_start_date(2015, 1, 1)
        self.set_end_date(2026, 8, 1)
        self.set_cash(50_000)
        self.set_brokerage_model(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN
        )

        self._spy = self.add_equity(
            "SPY", Resolution.DAILY,
            data_normalization_mode=DataNormalizationMode.ADJUSTED,
        ).symbol

        self._invested = False
        self.log(f"Live mode: {self.live_mode}")

    def on_data(self, data):
        if self._invested:
            return
        if self._spy not in data.bars:
            return
        self.set_holdings(self._spy, 1.0)
        self._invested = True
        self.log(f"BUY SPY @ {data.bars[self._spy].close:.2f}")
