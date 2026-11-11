# straufi

Write trading strategies in Python, and run them on [Straufi](https://straufi.com).

```sh
uv add straufi             # or `pip install straufi` or `poetry add straufi`
straufi login              # Logs in in your browser (`--no-browser` prints the URL instead)
straufi init my-strategy   # Creates a strategy on Straufi, and its project and virtual environment
cd my-strategy
straufi build              # Uploads the code and builds it on Straufi
straufi backtest           # Opens the page to test a build on past data
straufi deploy             # Opens the page to run a build
```

## Writing a strategy

A Straufi strategy is a [Python class](https://docs.python.org/3/tutorial/classes.html) that extends the `Strategy` base class.
It must define two methods:
- `config()` (`@staticmethod`) that returns a `Config` object that tells Straufi the instruments, indicators, and historical data you need.
- `run()` that is called when your strategy is triggered, with the data of all your instruments.

```python
from straufi import Config, Every, Instrument, Order, OrderSide, OrderType, Strategy
from straufi.indicators import RSI, BollingerBands


class MeanReversion(Strategy):
    @staticmethod
    def config():
        return Config(
            instruments={
                "btc": Instrument("BTC", "USDT", "binance"),
                "eth": Instrument("ETH", "USDT", "binance"),
            },
            indicators={
                "rsi14": RSI(period=14),
                "bb": BollingerBands(period=20),
            },
            lookback=24,
            interval="1h",
            frequency=Every("1h"),
        )

    def run(self) -> None:
        budgets = self.get_budget()
        positions = self.get_positions()

        for _, instrument in self.instruments():
            df = self.get_df(instrument)
            last = df.iloc[-1]

            broker_budget = budgets.get(instrument.broker, {})
            quote_available = broker_budget.get(instrument.quote, 0.0)  # e.g. how much USDT we can spend
            base_owned = broker_budget.get(instrument.base, 0.0)  # e.g. how much BTC we can sell

            print(f"{instrument}: close={last.close} rsi={last.rsi14:.1f} {instrument.quote}={quote_available}")

            if any(order.instrument == instrument for order in positions):
                # We already have an open order on this instrument
                continue

            if last.rsi14 < 30 and last.close < last.bb_lower and quote_available > 0:
                self.place_order(
                    Order(
                        instrument=instrument,
                        type=OrderType.MARKET,
                        side=OrderSide.BUY,
                        quote_volume=quote_available * 0.1,  # Spend 10% of what's available
                    )
                )
            elif last.rsi14 > 70 and last.close > last.bb_upper and base_owned > 0:
                self.place_order(
                    Order(
                        instrument=instrument,
                        type=OrderType.MARKET,
                        side=OrderSide.SELL,
                        volume=base_owned,  # Sell everything we own
                    )
                )
```

Every time the strategy is triggered, `run` is called once, with the data of all your instruments. In `run`, you can use:
- `self.get_df()`: pandas DataFrame with the OHLCV and indicators of your instruments.
- `self.get_budget()`: how much of each asset you have, by broker then symbol: `{"binance": {"USDT": 100.0}}`.
- `self.get_positions()`: all your open orders, as `Order`s.
- `self.place_order()`: places orders on the market.
- `self.cancel_order()`: cancels open orders (those retrieved from `get_positions()`).
- `self.instruments()`: iterates over your instruments, as `(alias, Instrument)` pairs.

### Indicators

Indicators are computed by Straufi. Each one becomes a column named after its key or, for indicators that produce
several values, one column per value named `<key>_<value>`:

| Indicator | Columns for key `k` |
|---|---|
| `SMA(period)`, `EMA(period)`, `RSI(period=14)`, `ATR(period=14)` | `k` |
| `BollingerBands(period=20)` | `k_upper`, `k_middle`, `k_lower` |
| `MACD(short_period=12, long_period=26, signal_period=9)` | `k_macd`, `k_signal` |

`SMA`, `EMA`, `RSI`, `BollingerBands` and `MACD` also accept `price_type` (`"open"`, `"high"`, `"low"` or `"close"`, the default).

### Orders

| `type` | Requires |
|---|---|
| `MARKET` | `volume` (base asset) **or** `quote_volume` (quote asset) |
| `LIMIT`, `LIMIT_MAKER` | `volume`, `limit_price` |
| `ICEBERG` | `volume`, `limit_price`, `display_volume` |
| `STOP_LOSS`, `TAKE_PROFIT` | `volume`, `trigger_price` and/or `trailing_delta` |
| `STOP_LOSS_LIMIT`, `TAKE_PROFIT_LIMIT` | `volume`, `limit_price`, `trigger_price` and/or `trailing_delta` |

Orders that stay in the order book take a `time_in_force` (`GTC` by default, or `IOC`). Invalid orders are rejected
outright, raising a `straufi.ValidationError` explaining what's wrong.

Helpers: `crossed_above(series, other)` and `crossed_below(series, other)` tell whether a crossover happened on
the last candle.

## The project

`straufi init` creates the strategy on Straufi, and its project and virtual environment (`.venv`) with uv, Poetry or
pip, whichever is available first, with pandas, numpy and ruff installed. Strategies start in paper mode, with the name
of their directory: use `--mode live` and `--name` to change that, and `--no-install` to only create the files.

The `[tool.straufi]` section of `pyproject.toml` tells Straufi where your strategy is, and which one it is:

```toml
[tool.straufi]
entrypoint = "strategy:MeanReversion"  # <file without .py>:<class>
id = "..."                             # The strategy on Straufi
```

## Commands

Run them from the project, or point to it with `--project`.

| Command | Does |
|---|---|
| `straufi build` | Packages the project and builds it on Straufi. With `--dry-run`, only runs the checks and shows the files that would be packaged, without sending anything |
| `straufi backtest` | Opens the page to backtest a build of the strategy on past data, in your browser |
| `straufi deploy` | Opens the page to deploy a build of the strategy, in your browser |
| `straufi status` | Shows what the strategy runs, when it runs next, and its last executions |
| `straufi pause` / `straufi resume` | Stops or restarts the strategy. Its open orders stay open |

`build` only builds the code again if it changed since the last build. Pressing Ctrl+C while it runs cancels it.

`backtest` and `deploy` only open the webapp: you choose the build, its budget and the period of a backtest there. Build
the code first for it to show up there.

## What gets packaged

Everything in the project except virtual environments, caches, `.env` files and what your `.gitignore` files ignore.
Commit a lockfile (`uv.lock`, `poetry.lock`, `pylock.toml` or `requirements.txt`): without one, each build may install
different versions of your dependencies. Symbolic links are refused. A project can have up to 5000 files and 200 MB, and
20 MB once compressed.

## Logging in

`straufi login` opens Straufi in your browser: log in, authorize the CLI, and come back to your terminal. Your login is
kept in your system's keyring (macOS Keychain, Windows Credential Manager, or Secret Service on Linux), or in
`~/.config/straufi/credentials.json`, readable by you only, when there is none. It lasts as long as you use it at least
once every 30 days. `straufi logout` revokes it.

In CI, set the `STRAUFI_TOKEN` environment variable instead: it is used as-is, and never saved.
