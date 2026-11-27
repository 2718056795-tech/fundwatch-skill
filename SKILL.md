---
name: fundwatch
description: Direct multi-source mainland China fund valuations and portfolio P&L; distinguishes fresh quotes, ETF/index proxy estimates, official NAV and stale data. Use for 实时基金估值、持仓盈亏、基金盯盘、收盘复核.
---

# FundWatch Skill (v0.2.0)

## Setup
Python 3.10+, standard library only. Clone this repository, then run commands from its root. No fund-platform account, token, or paid API required by the program. Do not install unknown dependencies or expose private holdings.

## Required live acceptance
During mainland trading hours (Beijing), run:
```bash
python3 fundwatch.py 011609 --require-live
```
Repeat after 30–60 seconds. Verify **source** timestamps (asof), not merely queried_at. A success exit indicates data meets the freshness check; inspect kind to distinguish provider_estimate from ETF/index proxy. A close_estimate is not a live_estimate. After 15:00:
```bash
python3 fundwatch.py 011609 --require-current
```
Exit 2 means one or more funds lack qualifying current data. Never report unavailable/stale quotes as real-time. Market phase is a weekday clock, not a verified exchange holiday calendar.

## Use
```bash
python3 fundwatch.py 011609 011608
python3 fundwatch.py 011609 --watch 30
python3 fundwatch.py --portfolio /private/portfolio.json --models /private/models.json --history /private/history.jsonl
```
Watch emits one JSON object per poll. Keep the running process only if the Agent environment permits persistent execution. Otherwise use the Agent scheduler to invoke one-shot commands; do not promise continuous monitoring without a functioning scheduler/process. Respect provider rate limits; start with 60–120 seconds for larger portfolios. Stop on access denial; do not circumvent paywalls/authentication.

## Reading results
- official_today: published NAV for current date. Check prior NAV and return before calculating daily P&L.
- live_estimate: source timestamp passes intraday freshness gate (default 90 seconds). May be an ETF/index proxy; no guarantee of exchange-grade real-time feeds.
- lunch_estimate: same-day 11:30–11:35 quote during midday break.
- close_estimate: same-day timestamp at/after 15:00 and at/before 15:30. A 13:42 or 14:59 quote is not accepted.
- latest_official_only / unavailable: no valid current valuation. Do not treat historical market value as today's market value.
- market_quotes: raw underlying security quotes with timestamps; inspect errors and candidate divergence.
- kind: provider_estimate, etf_proxy, index_proxy or official_nav. ETF proxies use exchange price (not ETF iNAV); index proxy uses a configured weight and assumes remaining exposure flat.
- portfolio totals may be partial. Never interpret null as zero. Daily P&L assumes unchanged shares and no distributions/splits; do not use for days with trades without accounting adjustments.

For 011609 the built-in mapping is ETF sh588080, index sh000688, approximate weight 0.95. The weight is a benchmark-model assumption, not measured current holdings. To add other funds, verify their target ETF or tracking index and weight from prospectus/latest reports; save your own mapping using models.example.json. Do not guess mappings. No QDII or active-fund holdings model is automatically inferred.

## Agent policy
Only read public permitted market data; never send holdings to upstream endpoints. Do not execute fund transactions. Cite the source and source timestamp, report status and kind with every estimate. Do not fabricate numbers when all sources fail. For a user requesting 15:00 data, require a valid close_estimate or official_today and distinguish them. If only stale/unavailable, state the blocker.
