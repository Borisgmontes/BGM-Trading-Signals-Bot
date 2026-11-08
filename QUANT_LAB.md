# BGM Quant Lab — BTC research MVP

Status: experimental research branch only. This module does not connect to a broker, place orders, or change BTC Radar runtime.

## First architecture slice

- quant_lab/data.py: paginated public BTCUSDT OHLCV download from Binance.US; drops the latest possibly open candle.
- quant_lab/indicators.py: causal EMA, RSI, ATR, Bollinger, volume ratio and MACD histogram.
- quant_lab/strategy.py: constrained, reproducible strategy definitions and candidate generation.
- quant_lab/backtest.py: close-confirmed signals, next-bar-open entries, ATR stops, R-multiple targets, fees/slippage, conservative stop-first handling when TP and SL touch in one candle.
- quant_lab/validation.py: train/out-of-sample report, fixed-strategy walk-forward windows and bootstrap resampling of observed trade returns.
- quant_lab/cli.py: research workflow and JSON report output.

## Run locally

    pip install -r requirements.txt
    python -m quant_lab.cli --timeframe 5m --candles 5000 --candidates 100
    python -m unittest tests.test_quant_lab -v

## Research safeguards and limitations

1. Signals are evaluated on completed candles; simulated entries occur at the next candle open.
2. Fees and slippage are deducted on entry and exit.
3. If stop and target are both touched in one OHLC candle, the simulator assumes the adverse stop happened first.
4. The out-of-sample segment is not used to generate candidate rules.
5. Bootstrap resamples observed trades; it does not simulate new market regimes or prove future profitability.
6. Current walk-forward reports fixed-strategy results over consecutive windows; it does not yet re-optimize on each rolling training window.
7. Ranking is a preliminary research filter, not approval to trade. Minimum sample sizes, parameter stability, exchange costs, funding, latency and paper trading remain mandatory before any MT5 adapter is enabled.

## Next stages

- True rolling walk-forward optimizer with separate training and test windows.
- Parameter-sensitivity analysis and strategy-family deduplication.
- Persistent experiment store in SQLite/PostgreSQL.
- Read-only MT5 symbol/specification adapter, then a separate demo-only execution bridge after validation.
- Web dashboard for experiment control and strategy comparison.
