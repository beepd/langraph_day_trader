import math

STARTING_BALANCE = 100_000
RISK_PER_TRADE = 0.01              # risk at most 1% of the balance on one trade
MAX_POSITION_FRACTION = 0.30       # never put more than 30% of the balance in one stock (3 stocks = 90%)
MIN_REWARD_RISK = 1.5              # the possible gain must be at least 1.5x the possible loss
MIN_STOP_RANGE_FRACTION = 0.33     # NEW: stop at least a third of the typical daily range away
MAX_TARGET_RANGE_FRACTION = 1.0    # NEW: target no further than one typical daily range away
TICK = 0.05                        # NSE prices move in steps of 0.05
NUDGE_TOLERANCE = 0.50             # a plan within 50% of a limit may be nudged inside it; further out, it is rejected


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


def _floor_tick(price):
    return round(math.floor(round(price / TICK, 6)) * TICK, 2)


def nudge_plan(entry, stop, target, avg_range):
    """
    Move a plan that is only slightly outside the legal window just inside it, instead of rejecting it.
      - a stop that is a little too close is moved out to the minimum distance,
      - a target that is a little too far is pulled in to the maximum distance.
    Plans further out than NUDGE_TOLERANCE are left alone (so size_trade rejects them), and so are nonsense plans.
    The nudged plan still goes through size_trade, so every other rule applies as before.
    Returns (stop, target, notes) where notes says in words what was changed.
    """
    notes = []
    if not (stop < entry < target):
        return stop, target, notes
    min_stop = MIN_STOP_RANGE_FRACTION * avg_range
    max_target = MAX_TARGET_RANGE_FRACTION * avg_range
    stop_distance, target_distance = entry - stop, target - entry

    if min_stop * (1 - NUDGE_TOLERANCE) <= stop_distance < min_stop:
        new_stop = _floor_tick(entry - min_stop)
        while entry - new_stop < min_stop:
            new_stop = round(new_stop - TICK, 2)
        notes.append(f"stop moved from {stop:.2f} to {new_stop:.2f} (it was {stop_distance:.2f} away; the minimum is {min_stop:.2f})")
        stop = new_stop
    if max_target < target_distance <= max_target * (1 + NUDGE_TOLERANCE):
        new_target = _floor_tick(entry + max_target)
        while new_target - entry > max_target:
            new_target = round(new_target - TICK, 2)
        notes.append(f"target moved from {target:.2f} to {new_target:.2f} (it was {target_distance:.2f} away; the maximum is {max_target:.2f})")
        target = new_target
    return stop, target, notes