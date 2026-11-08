"""Transparent, rule-based strategy quality gates; not a predictive AI model."""
from __future__ import annotations

def score_candidate(validation: dict, min_oos_trades: int = 30) -> dict:
    train = validation["train"]
    test = validation["out_of_sample"]
    pf = test.get("profit_factor")
    trades = int(test.get("trades", 0))
    drawdown = float(test.get("max_drawdown_pct", 100.0))
    net = float(test.get("net_return_pct", 0.0))
    expectancy = float(test.get("expectancy_pct", 0.0))
    checks = {
        "minimum_oos_trades": trades >= min_oos_trades,
        "positive_oos_return": net > 0,
        "profit_factor_at_least_1_10": pf is not None and pf >= 1.10,
        "drawdown_at_most_25_pct": drawdown <= 25.0,
    }
    passed = all(checks.values())
    # Transparent 0-100 research score. Failing any hard gate forces score to zero.
    if passed:
        pf_component = min(float(pf), 3.0) / 3.0
        return_component = min(max(net, 0.0), 50.0) / 50.0
        dd_component = max(0.0, 1.0 - drawdown / 25.0)
        expectancy_component = min(max(expectancy, 0.0), 2.0) / 2.0
        score = 100 * (0.35*pf_component + 0.30*return_component +
                       0.20*dd_component + 0.15*expectancy_component)
    else:
        score = 0.0
    return {"research_score": round(score, 2), "eligible_for_paper_testing": passed,
            "gates": checks, "note": "Rule-based filter only; not an AI prediction or a profitability guarantee."}


def score_training_candidate(result: dict, min_trades: int = 30) -> dict:
    """Rank parameter combinations on training data only; never inspect OOS here."""
    pf = result.get("profit_factor")
    trades = int(result.get("trades", 0))
    drawdown = float(result.get("max_drawdown_pct", 100.0))
    net = float(result.get("net_return_pct", 0.0))
    expectancy = float(result.get("expectancy_pct", 0.0))
    checks = {
        "minimum_train_trades": trades >= min_trades,
        "positive_train_return": net > 0,
        "profit_factor_at_least_1_10": pf is not None and pf >= 1.10,
        "drawdown_at_most_25_pct": drawdown <= 25.0,
    }
    passed = all(checks.values())
    if passed:
        pf_component = min(float(pf), 3.0) / 3.0
        return_component = min(max(net, 0.0), 50.0) / 50.0
        dd_component = max(0.0, 1.0 - drawdown / 25.0)
        expectancy_component = min(max(expectancy, 0.0), 2.0) / 2.0
        score = 100 * (0.35*pf_component + 0.30*return_component +
                       0.20*dd_component + 0.15*expectancy_component)
    else:
        score = 0.0
    return {"training_score": round(score, 2), "training_gates": checks,
            "note": "Training-only ranking. Out-of-sample data is not used to select parameters."}
