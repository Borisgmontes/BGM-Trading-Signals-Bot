# BGM Quant Lab — BTC research MVP

Status: experimental research branch only. This module does not connect to a broker, place orders, or change BTC Radar runtime.

## First architecture slice

- quant_lab/data.py: paginated BTCUSDT OHLCV download from Binance.US; latest candle is excluded only for current-history requests.
- quant_lab/indicators.py: causal EMA, RSI, ATR, Bollinger, volume ratio and MACD histogram.
- quant_lab/strategy.py: constrained, reproducible strategy definitions and candidate generation.
- quant_lab/backtest.py: signal on completed candle, entry at next bar open, ATR stop, R-multiple target, fee/slippage costs, and conservative stop-first handling when TP and SL touch in one candle.
- quant_lab/validation.py: train/out-of-sample report, fixed-strategy walk-forward windows and bootstrap resampling of observed trade returns.
- quant_lab/ranking.py: transparent rule-based quality gates and a 0-100 research score. This is not a predictive AI model.
- quant_lab/cli.py: research workflow and JSON report output.

## Run locally

    pip install -r requirements.txt
    python -m quant_lab.cli --timeframe 5m --candles 5000 --candidates 100
    python -m unittest tests.test_quant_lab -v

## Safeguards and current limitations

1. Signals are evaluated on completed candles; simulated entries occur at the next candle open.
2. Fees and slippage are deducted on entry and exit. The initial model is unleveraged spot-style return accounting.
3. If stop and target are both touched in one OHLC candle, the simulator assumes the adverse stop happened first.
4. Candidate generation uses only constrained, seeded rules. It is a search baseline, not a trained AI model.
5. Out-of-sample data is not used to generate candidate rules. The rule-based score requires at least 30 out-of-sample trades, positive net return, profit factor >= 1.10 and drawdown <= 25% before a candidate is eligible for paper testing.
6. Bootstrap resamples observed trades; it does not simulate new market regimes or prove future profitability.
7. Current walk-forward reports fixed-strategy results over consecutive windows; it does not yet re-optimize on each rolling training window.
8. The score is a preliminary filter, not approval to trade. Parameter stability, exchange costs, funding, latency and paper trading remain mandatory before any MT5 adapter is enabled.

## Next stages

- True rolling walk-forward optimizer with separate training and test windows.
- Parameter-sensitivity analysis, strategy-family deduplication and multi-objective ranking.
- Persist market data, experiments, strategies and metrics in SQLite/PostgreSQL.
- Read-only MT5 symbol/specification adapter, then a separate demo-only execution bridge after validation.
- Web dashboard for experiment control and strategy comparison.
