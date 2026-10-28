from pathlib import Path

core_path = Path("share_sniper_core.py")
source = core_path.read_text(encoding="utf-8")

patches = [
    ('CORE_WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL","AVGO","BARC.L","QCOM","BA","SPCX","DKS"]',
     'CORE_WATCHLIST = ["TSLA","NVDA","META","AMZN","GOOGL","AVGO","BARC.L","QCOM","BA","SPCX","DKS","APP","BAC"]'),
    ('    "DKS":"DICK\'S Sporting Goods",\n',
     '    "DKS":"DICK\'S Sporting Goods",\n    "APP":"AppLovin Corporation",\n    "BAC":"Bank of America",\n'),
    ('    "DKS":"Special-event rebound candidate after the Foot Locker-driven sell-off. Do not chase the bounce: only actionable at $125 or below, and check that the post-crash floor/fundamentals are holding before buying.",\n',
     '    "DKS":"Special-event rebound candidate after the Foot Locker-driven sell-off. Do not chase the bounce: only actionable at $125 or below, and check that the post-crash floor/fundamentals are holding before buying.",\n    "APP":"High-volatility AI advertising rebound candidate. Preferred Sniper zone $280-$290. Green means investigate/check fundamentals, not automatic buy: confirm no materially worse SEC/regulatory or data-practice developments, AXON economics breakdown, or significant growth/e-commerce deterioration. Initial rebound objective roughly $325-$350; do not chase above the target zone.",\n    "BAC":"Large-cap US bank rebound watchlist. Preferred buy investigation zone $46-$47; check credit quality, regulatory news, earnings and whether a recovery is developing. A price in the zone is not an automatic buy signal.",\n'),
    ('    "DKS": (120.0, 125.0),\n',
     '    "DKS": (120.0, 125.0),\n    "APP": (280.0, 290.0),\n    "BAC": (46.0, 47.0),\n'),
]

for old, new in patches:
    if source.count(old) != 1:
        raise RuntimeError(f"APP patch mismatch: expected exactly one occurrence of {old[:40]!r}")
    source = source.replace(old, new, 1)

exec(compile(source, "share_sniper_core.py", "exec"), globals(), globals())
