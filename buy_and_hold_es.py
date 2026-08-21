from AlgorithmImports import *


class BuyAndHoldES(QCAlgorithm):
    """
    Buy-and-hold MES (Micro E-mini S&P 500) futures baseline.

    Rolls to the next front-month contract exactly 5 calendar days before
    expiry, matching the Carver AFTS rule. Uses additive (backwards Panama
    Canal) back-adjustment so the continuous price series reflects true P&L
    from rolling, consistent with the book's back-adjustment methodology.
    """

    ROLL_DAYS = 5  # calendar days before expiry to roll

    def initialize(self):
        self.set_start_date(2015, 1, 1)
        self.set_end_date(2026, 8, 1)
        self.set_cash(50_000)
        self.set_brokerage_model(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN
        )

        # Continuous contract — used only for back-adjusted price data.
        # BACKWARDS_PANAMA_CANAL: additive adjustment, last contract = true price.
        # Matches Carver's back-adjustment: subtract differential from all
        # earlier contracts so no artificial jump occurs at the roll date.
        self._es = self.add_future(
            Futures.Indices.MICRO_SP_500_E_MINI,
            resolution=Resolution.DAILY,
            data_mapping_mode=DataMappingMode.OPEN_INTEREST,
            data_normalization_mode=DataNormalizationMode.BACKWARDS_PANAMA_CANAL,
            contract_depth_offset=0,
        )
        # 182 days ensures both front and back quarterly contracts are visible
        # (quarterly back month expires ~91-96 days after the front).
        self._es.set_filter(0, 182)

        self._held_contract = None  # Symbol of the contract we currently hold
        self.log(f"Live mode: {self.live_mode}")

    def on_data(self, data: Slice):
        chain = data.futures_chains.get(self._es.symbol)
        if not chain:
            return

        # Sort available contracts by expiry; front month is first.
        contracts = sorted(chain, key=lambda c: c.expiry)
        if not contracts:
            return

        front = contracts[0]

        # Guard: if the held contract expired or was settled externally, reset
        # so we re-enter cleanly rather than getting stuck with a stale symbol.
        if self._held_contract is not None:
            holding = self.portfolio.get(self._held_contract)
            if holding is None or holding.quantity == 0:
                self._held_contract = None

        # --- Initial entry ---
        if self._held_contract is None:
            self._enter(front.symbol, front.last_price)
            return

        # --- Roll check: if we hold the front month and it expires within
        #     ROLL_DAYS calendar days, roll to the next contract. ---
        days_left = (front.expiry.date() - self.time.date()).days
        if self._held_contract == front.symbol and days_left <= self.ROLL_DAYS:
            if len(contracts) < 2:
                return  # back month not yet in filter window; wait
            back = contracts[1]
            self._roll(front.symbol, back.symbol, front.last_price, back.last_price)

    def _enter(self, symbol: Symbol, price: float):
        qty = self._target_contracts(symbol)
        self.market_order(symbol, qty)
        self._held_contract = symbol
        self.log(f"ENTER {symbol.value} x{qty} @ {price:.2f}")

    def _roll(self, old: Symbol, new: Symbol, old_price: float, new_price: float):
        qty = self.portfolio[old].quantity
        adjustment = old_price - new_price
        self.liquidate(old, tag=f"Roll out @ {old_price:.2f}")
        self.market_order(new, qty, tag=f"Roll in @ {new_price:.2f} (adj {adjustment:+.2f})")
        self._held_contract = new
        self.log(
            f"ROLL {old.value} → {new.value} | "
            f"prices {old_price:.2f} / {new_price:.2f} | "
            f"adjustment {adjustment:+.2f}"
        )

    def _target_contracts(self, symbol: Symbol) -> int:
        """Allocate 100% of portfolio equity to MES, rounded to nearest contract."""
        multiplier = self.securities[symbol].symbol_properties.contract_multiplier
        price = self.securities[symbol].price
        if price <= 0 or multiplier <= 0:
            return 1
        notional_per_contract = price * multiplier
        return max(1, round(self.portfolio.total_portfolio_value / notional_per_contract))
