STARTING_BALANCE = 100_000
RISK_PER_TRADE = 0.01              # risk at most 1% of the balance on one trade
MAX_POSITION_FRACTION = 0.30       # never put more than 30% of the balance in one stock
MIN_REWARD_RISK = 1.5              # the possible gain must be at least 1.5x the possible loss
MIN_STOP_RANGE_FRACTION = 0.33     # NEW: stop at least a third of the typical daily range away
MAX_TARGET_RANGE_FRACTION = 1.0    # NEW: target no further than one typical daily range away


def size_trade(balance, entry, stop, target, avg_range):      # CHANGED: new avg_range argument
    if not (stop < entry < target):
        return {"ok": False, "reason": "needs stop < entry < target"}

    risk_per_share = entry - stop
    reward_per_share = target - entry

    if risk_per_share < MIN_STOP_RANGE_FRACTION * avg_range:                                    # NEW
        return {"ok": False, "reason": f"stop is only {risk_per_share:.2f} away; normal wobble ({avg_range:.2f} a day) would hit it"}
    if reward_per_share > MAX_TARGET_RANGE_FRACTION * avg_range:                                # NEW
        return {"ok": False, "reason": f"target is {reward_per_share:.2f} away, more than a typical day's range ({avg_range:.2f})"}

    reward_risk = reward_per_share / risk_per_share
    if reward_risk < MIN_REWARD_RISK:
        return {"ok": False, "reason": f"reward/risk {reward_risk:.3f} is below {MIN_REWARD_RISK}"}

    max_loss = balance * RISK_PER_TRADE
    shares_by_risk = int(max_loss // risk_per_share)
    shares_by_cash = int((balance * MAX_POSITION_FRACTION) // entry)
    shares = min(shares_by_risk, shares_by_cash)
    if shares < 1:
        return {"ok": False, "reason": "not even 1 share fits the rules"}

    return {
        "ok": True,
        "shares": shares,
        "cost": shares * entry,
        "max_loss": shares * risk_per_share,
        "max_gain": shares * reward_per_share,
        "reward_risk": reward_risk,
    }