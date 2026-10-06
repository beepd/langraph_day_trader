import random, sys
sys.path.insert(0, ".")   # run this from the project folder
import rules as R

print("== 1. the real plans from your forced run (with the real ranges from the rejection messages) ==")
cases = [  # name, entry, stop, target, avg_range  (stop/target distances taken from the rejection texts)
    ("TRENT (old prompt)",  2858.90, 2858.90 - 19.00, 2858.90 + 39.20, 57.74),
    ("VEDL",                265.60,  265.60 - 2.30,  265.60 + 6.50,  5.81),
    ("KOTAKBANK",           431.90,  431.90 - 3.80,  431.90 + 12.10, 9.36),
    ("GODREJCP",            872.50,  872.50 - 6.90,  872.50 + 16.00, 15.08),
]
for name, entry, stop, target, rng in cases:
    s2, t2, notes = R.nudge_plan(entry, round(stop, 2), round(target, 2), rng)
    res = R.size_trade(100467.0, entry, s2, t2, rng)
    before = R.size_trade(100467.0, entry, round(stop, 2), round(target, 2), rng)
    print(f"   {name:<20} before: {'accepted' if before['ok'] else 'REJECTED: ' + before['reason'][:44]:<58} after nudge: {'ACCEPTED' if res['ok'] else 'rejected: ' + res['reason'][:40]}"
          + (f" ({res['shares']} shares, risk {res['max_loss']:.0f}, reward {res['max_gain']:.0f})" if res['ok'] else ""))
    for n in notes: print("        note:", n)

print("\n== 2. plans too far from the limits are NOT rescued ==")
for label, args in [("target 3 ranges away", (100.0, 93.0, 160.0, 20.0)), ("stop only 20% of the minimum", (100.0, 99.0, 112.0, 20.0)), ("stop above the buy price", (100.0, 101.0, 112.0, 20.0)), ("target below the buy price", (100.0, 93.0, 99.0, 20.0))]:
    s2, t2, notes = R.nudge_plan(*args)
    print(f"   {label:<30} unchanged: {(s2, t2) == (args[1], args[2])} | outcome: {R.size_trade(100000, args[0], s2, t2, args[3])}")

print("\n== 3. property test: 200,000 random plans ==")
random.seed(11)
tick = lambda x: abs(round(x / 0.05) * 0.05 - x) < 1e-6
bad = []; nudged = accepted_before = accepted_after = 0
for i in range(200_000):
    entry = round(random.choice([13.14, 87.35, 263.15, 431.90, 872.50, 2858.90, 7122.50, random.uniform(10, 8000)]) / 0.05) * 0.05
    entry = round(entry, 2)
    rng = random.uniform(0.01, 0.045) * entry
    stop = round(round((entry - random.uniform(0.05, 1.3) * rng) / 0.05) * 0.05, 2)
    target = round(round((entry + random.uniform(0.2, 2.0) * rng) / 0.05) * 0.05, 2)
    before = R.size_trade(100467.0, entry, stop, target, rng)
    s2, t2, notes = R.nudge_plan(entry, stop, target, rng)
    after = R.size_trade(100467.0, entry, s2, t2, rng)
    accepted_before += before["ok"]; accepted_after += after["ok"]; nudged += bool(notes)
    # rules that must always hold
    if notes:
        if s2 > stop + 1e-9: bad.append(("stop moved closer", entry, stop, target, rng))
        if t2 > target + 1e-9: bad.append(("target moved farther", entry, stop, target, rng))
        if not (tick(s2) and tick(t2)): bad.append(("price off the 0.05 grid", entry, s2, t2))
    if after["ok"]:
        if not (entry - s2 >= R.MIN_STOP_RANGE_FRACTION * rng - 1e-9): bad.append(("accepted stop too close", entry, s2, rng))
        if not (t2 - entry <= R.MAX_TARGET_RANGE_FRACTION * rng + 1e-9): bad.append(("accepted target too far", entry, t2, rng))
        if not (after["reward_risk"] >= R.MIN_REWARD_RISK - 1e-9): bad.append(("accepted ratio too low", entry, s2, t2))
        if after["cost"] > 100467.0 * R.MAX_POSITION_FRACTION + 1e-6: bad.append(("accepted over the cash cap",))
        if after["max_loss"] > 100467.0 * R.RISK_PER_TRADE + 1e-6: bad.append(("accepted over the risk cap",))
    if before["ok"] and (s2, t2) != (stop, target): bad.append(("changed a plan that was already legal", entry, stop, target, rng))
print(f"   plans tested {200_000:,} | nudged {nudged:,} | accepted before the nudge {accepted_before:,} -> after {accepted_after:,}")
print(f"   rule violations found: {len(bad)}", bad[:3] if bad else "(none)")