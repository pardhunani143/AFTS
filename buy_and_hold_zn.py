from AlgorithmImports import *


class BuyAndHoldZN(QCAlgorithm):
    """
    Buy-and-hold 10-Year T-Note futures (ZN) baseline.

    Earns the duration/interest-rate risk premium. Rolls 25 days before
    expiry per Carver's AFTS bond-futures roll rule (bonds need more lead
    time than equity index futures because of physical delivery). Uses
    additive (backwards Panama Canal) back-adjustment, identical to the
    MES baseline.

    Contract specs (Carver AFTS):
        Symbol/Exchange : TN (ZN), CBOT
        Multiplier      : $1,000 per point
        Tick size       : 0.015625 (1/64)
        Expiry months   : Quarterly (Mar/Jun/Sep/Dec)
        Roll            : ~25 days before expiry
    """

    ROLL_DAYS = 25  # calendar days before expiry to roll

    def initialize(self):
        self.set_start_date(2015, 1, 1)
        self.set_end_date(2026, 8, 1)
        self.set_cash(50_000)
        self.set_brokerage_model(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN
        )

        self._zn = self.add_future(
            Futures.Financials.Y_10_TREASURY_NOTE,
            resolution=Resolution.DAILY,
            data_mapping_mode=DataMappingMode.OPEN_INTEREST,
            data_normalization_mode=DataNormalizationMode.BACKWARDS_PANAMA_CANAL,
            contract_depth_offset=0,
        )
        # Back month expires ~66 days after roll trigger (25 days before front
        # expiry + ~91 days to back expiry), well within a 182-day window.
        self._zn.set_filter(0, 182)

        self._held_contract = None
        self.log(f"Live mode: {self.live_mode}")

    def on_data(self, data: Slice):
        chain = data.futures_chains.get(self._zn.symbol)
        if not chain:
            return

        contracts = sorted(chain, key=lambda c: c.expiry)
        if not contracts:
            return

        front = contracts[0]

        # Guard: reset if position expired or was settled externally.
        if self._held_contract is not None:
            holding = self.portfolio.get(self._held_contract)
            if holding is None or holding.quantity == 0:
                self._held_contract = None

        if self._held_contract is None:
            self._enter(front.symbol, front.last_price)
            return

        days_left = (front.expiry.date() - self.time.date()).days
        if self._held_contract == front.symbol and days_left <= self.ROLL_DAYS:
            if len(contracts) < 2:
                return
            back = contracts[1]
            self._roll(front.symbol, back.symbol, front.last_price, back.last_price)

    def _enter(self, symbol: Symbol, price: float):
        qty = self._target_contracts(symbol)
        self.market_order(symbol, qty)
        self._held_contract = symbol
        self.log(f"ENTER {symbol.value} x{qty} @ {price:.4f}")

    def _roll(self, old: Symbol, new: Symbol, old_price: float, new_price: float):
        qty = self.portfolio[old].quantity
        adjustment = old_price - new_price
        self.liquidate(old, tag=f"Roll out @ {old_price:.4f}")
        self.market_order(new, qty, tag=f"Roll in @ {new_price:.4f} (adj {adjustment:+.4f})")
        self._held_contract = new
        self.log(
            f"ROLL {old.value} → {new.value} | "
            f"prices {old_price:.4f} / {new_price:.4f} | "
            f"adjustment {adjustment:+.4f}"
        )

    def _target_contracts(self, symbol: Symbol) -> int:
        """
        Allocate 100% of portfolio equity to ZN notional.

        ZN is quoted in points (e.g. 110.5) with $1,000/point, so one
        contract has ~$110,000 notional at typical prices. A $50K account
        starts with 1 contract (~2× leverage), scaling up as equity grows.
        """
        multiplier = self.securities[symbol].symbol_properties.contract_multiplier
        price = self.securities[symbol].price
        if price <= 0 or multiplier <= 0:
            return 1
        notional_per_contract = price * multiplier
        return max(1, round(self.portfolio.total_portfolio_value / notional_per_contract))
