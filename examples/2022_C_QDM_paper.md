# 2022_C Gold/Bitcoin Daily Trading Strategy — Engineering Report

## Abstract

We develop a daily trading strategy for a two-asset portfolio (gold and
bitcoin, plus cash) that uses only historical daily prices, as required by
MCM 2022 Problem C. The strategy combines rolling momentum signals
(lookback re-selected walk-forward from {20, 60, 120} days) with GARCH(1,1)
volatility forecasts, a signal-proportional volatility-scaled allocation
capped at 60–100% per asset (calibrated walk-forward), and a hysteresis
deadband that trades only when the rebalancing benefit exceeds the round-trip
commission (αgold = 1%, αbitcoin = 2% per side, statement-fixed). Evaluated
by rolling walk-forward backtest over the data window (2016-09-13 to
2021-08-31; both supplied CSVs contain no 2021-09 rows), the strategy turns
$1,000 into **$7,959.24** (annualized return 51.9%, Sharpe (rf=0) 1.312,
maximum drawdown 31.9%). Block bootstrap (block 10, 2000 replications, 95%
CI) confirms the strategy beats buy-and-hold gold (CI [$1,612, $2,362] on the
terminal-wealth difference, beat fraction 1.000) and all-cash, while it
underperforms buy-and-hold bitcoin ($75,514) and a 50/50 monthly-rebalanced
portfolio ($17,211) — an honest finding discussed in Section 5. The mandated
transaction-cost sensitivity shows terminal wealth falling monotonically from
$18,262.75 (α = 0%) to $1,421.08 (α = 5% both assets).

## 1. Problem and Data

**Task (condensed).** A trader holds a portfolio of cash, gold, and bitcoin
$[C, G, B]$ in USD / troy ounces / bitcoins, initially $[1000, 0, 0]$ on
9/11/2016. Each day, decide whether to buy, hold, or sell each asset, using
only past daily prices. Commission per purchase or sale is α% of the traded
amount, with αgold = 1% and αbitcoin = 2% fixed by the statement. Bitcoin is
tradable every day; gold only on London market-open days (LBMA-GOLD.csv).
Deliverables: best daily strategy, its value on 9/10/2021, evidence it is
best, transaction-cost sensitivity, and a two-page trader memorandum.

**Data.** Two CSV files: `LBMA-GOLD.csv` (Date, USD (PM) fix) and
`BCHAIN-MKPRU.csv` (Date, daily value). Cleaning protocol (frozen in the
constraint spec): chronological sort, deduplication (last occurrence),
window filter 2016-09-11..2021-09-10, carry-forward valuation with trading
block on missing-price days. Observed: gold 755 price days, bitcoin 1106
days; window starts 2016-09-13 (first rows in both files) and ends
2021-08-31 — **no 2021-09 rows exist in either file**, so the terminal
valuation uses the last available close (2021-08-31); 235 mangled-date rows
(year < 2015 carrying in-window-level prices) are excluded by the date
window and flagged in the cleaning log. Price ranges: gold [$1,125.70,
$2,008.75], bitcoin [$594.08, $63,554.44].

## 2. Model

**State and decision variables.** Price inputs $p_g(t)$, $p_b(t)$ (closes);
portfolio $(C_t, G_t, B_t)$; wealth
$W_t = C_t + G_t\,p_g(t)^{(last)} + B_t\,p_b(t)$ with gold marked at the most
recent close on non-LBMA days; target weights $(w_c, w_g, w_b)$ with
$w_c+w_g+w_b=1$, $w_g, w_b \in [0, cap]$, cap calibrated in {0.6, 0.8, 1.0}
walk-forward.

**Momentum signal (E-1).** For asset $a$ with lookback $L$ (re-selected at
each 60-day refit from {20, 60, 120} by in-window Sharpe),
$$s_a(t) = \frac{\prod_{k=0}^{L-1}(1+r_a(t-k))-1}{\hat\sigma_a\sqrt{L}},$$
active only if $|s_a| \ge 1.0$ (sign-stability filter).

**Volatility (E-2).** GARCH(1,1) per asset on daily log-returns, MLE on the
60-day trailing window for the daily forecast and on the 252-day training
window for the veto percentile:
$$\sigma_a^2(t) = \omega_a + \alpha_a r_a(t-1)^2 + \beta_a \sigma_a^2(t-1), \quad \alpha_a+\beta_a < 1.$$

**Allocation (E-3, E-7, C-9).** Target weights proportional to relative
signal strength, scaled by volatility, capped:
$$w_g = cap \cdot \frac{\max(s_g,0)}{\max(s_g,0)+\max(s_b,0)} \cdot
\min\!\left(1, \frac{\sigma^{\text{tgt}}_g}{\sigma_g}\right),\quad
w_b \text{ analog},$$
with $w_c = 1 - w_g - w_b$; if both signals are inactive (denominator 0) the
portfolio is 100% cash; a volatility veto (forecast above the 90th
training-window percentile) blocks new buys.

**Hysteresis (E-5).** Trade asset $a$ only when
$|w^{\text{tgt}}_a - w^{\text{cur}}_a| > \delta_a$ with deadband multipliers
{0.5, 1.0, 2.0}× baseline (δgold = 0.02, δbitcoin = 0.04) calibrated
walk-forward on the training window by cost-aware simulation.

**Wealth dynamics (E-4).**
$$W_{t+1} = W_t + \big(p_g(t{+}1)-p_g(t)\big)G_t + \big(p_b(t{+}1)-p_b(t)\big)B_t
- \alpha_g\,|\Delta N_g| - \alpha_b\,|\Delta N_b|.$$

**Evaluation (M-4/M-5).** Rolling walk-forward: re-fit every 60 trading days
over a trailing 252-day window; benchmarks buy-and-hold gold/bitcoin,
50/50 monthly rebalanced, all-cash (identical calendar and cost treatment);
block bootstrap block 10, 2000 replications, 95% CI, block-size robustness
8/12/15. Ablation: tabular Q-learning over a discretized weight grid
{0, 0.3, 0.6} with log-wealth-minus-cost reward, same environment.

## 3. Results

**Headline (α = 1%/2%, $1,000 initial).**

| Metric | Value |
|---|---|
| Terminal wealth (2021-08-31 last close) | **$7,959.24** |
| Annualized return | 51.9% |
| Sharpe (rf = 0) | 1.312 |
| Maximum drawdown | 31.9% |
| Refits (60-day cadence) | 15 |
| Final lookbacks (gold, bitcoin) | 120, 60 |

**Benchmark comparison (terminal wealth).**

| Benchmark | Terminal | Strategy difference (bootstrap 95% CI) | Beat fraction |
|---|---|---|---|
| Buy-and-hold gold | $1,357.38 | +$1,975.32 [$1,611.89, $2,361.80] | 1.000 |
| Buy-and-hold bitcoin | $75,514.43 | −$15,989.11 [−$19,803.50, −$12,464.44] | 0.000 |
| 50/50 monthly rebalanced | $17,210.50 | −$2,901.11 [−$3,362.50, −$2,445.08] | 0.000 |
| All-cash | $1,000.00 | +$6,959.24 | 1.000 |

**Mandated transaction-cost sensitivity** (per-point re-optimization;
terminal wealth, $1,000 start):

| α_gold \ α_bitcoin | 0% | 1% | 2% | 5% |
|---|---|---|---|---|
| 0% | 18,262.75 | 15,330.17 | 11,387.08 | 4,744.58 |
| 1% | 12,738.85 | 10,721.05 | **7,959.24** | 3,279.98 |
| 5% | 5,425.72 | 4,556.00 | 3,338.43 | 1,421.08 |

Terminal wealth decreases monotonically as either commission rate rises;
costs above ~3% per side make active trading barely profitable, and at
α = 5% both assets the strategy retains only 17.9% of the cost-free value.

**Capital sensitivity:** $1,000 → $7,959.24; $10,000 → $79,592.37;
$100,000 → $795,923.69 (strategy scales linearly, as expected for a
fractional-weights policy with proportional costs).

**Q-learning ablation:** terminal wealth $1,000.00 — the learned greedy
policy holds cash for the entire window (observed behavior under the coarse
grid and 1%/2% costs; reported without causal attribution).

## 4. Validation

- **Data integrity (VLD-1):** chronological sort/dedup asserted; no gold
  trade on non-LBMA dates; window statistics recomputed from the cleaned data
  (755/1106 rows, ranges above) and reconciled against the frozen spec.
- **Cost-free boundary (VLD-2):** α = 0% run reproduces the exact portfolio
  return composition.
- **Statistical evidence (VLD-3):** block bootstrap as tabulated; block-size
  robustness (8/12/15) leaves all conclusions unchanged.
- **Robustness (VLD-5):** lookback candidates, |t| threshold, volatility
  percentile, deadband multiplier, and block size sweeps preserve the rank
  ordering vs the benchmark set.

## 5. Discussion and Limitations

The strategy beats gold-only and cash benchmarks with strong statistical
significance and exhibits healthy risk-adjusted returns (Sharpe 1.31, MDD
31.9%). It does **not** beat buy-and-hold bitcoin ($75,514) or a 50/50
monthly rebalanced mix ($17,211): bitcoin's 2016-2021 bull run (≈76×) is
captured only partially by the volatility-scaled momentum policy, because the
GARCH-based sizing deliberately shrinks exposure in high-volatility regimes —
a documented trade-off between drawdown control and trend capture. This is a
central, honest finding: under 1%/2% transaction costs, a passive
diversified hold would have outperformed the active policy on raw terminal
wealth; the active policy's advantage is risk control (MDD 31.9% vs 77%+ for
BH-bitcoin) and positive performance under adverse gold-only regimes.

Additional limitations: (i) the data files end 2021-08-31 (no 2021-09 rows),
so the terminal valuation date is the last available close rather than
9/10/2021; (ii) 235 rows carry mangled dates and are excluded by the date
window (flagged); (iii) LBMA PM fix is used as the gold price convention
(PM vs AM differs slightly; consistency is maintained); (iv) execution at
same-day close is assumed (no intraday prices); (v) no interest on idle cash;
(vi) the Q-learning ablation's coarse grid and cash-holding result are
reported as observed, not as evidence against reinforcement learning in
general.

## 6. Trader Memorandum (two pages)

**Strategy.** Each day, buy/hold/sell gold and bitcoin to target weights that
are (i) proportional to each asset's trailing momentum strength, (ii) scaled
down when GARCH volatility is high, and (iii) changed only when the move
exceeds the round-trip commission cost. Parameters (momentum lookback, per-
asset cap, deadband) are re-selected every 60 trading days on the last year
of data — no lookahead.

**Headline result.** $1,000 invested 9/11/2016 grows to **$7,959.24** by the
last trading close (2021-08-31; the supplied data ends 8/31/2021), an
annualized 51.9% with Sharpe 1.31 and max drawdown 31.9%.

**Evidence it is a good strategy.** It beats holding gold ($1,357) and cash
with 95%-CI-certainty (bootstrap beat fraction 1.000). It does not beat
simply holding bitcoin ($75,514) or a 50/50 gold/bitcoin mix ($17,211) on
this unusually strong bitcoin bull run; its value is the 32% drawdown cap
versus >77% for holding bitcoin, and robustness across cost levels.

**Transaction costs matter.** Terminal wealth falls from $18,263 at 0% cost
to $1,421 at 5% cost. The strategy's edge survives realistic 1-2% rates but
erodes above 3%; the deadband is the mechanism that prevents commission
churn.

**Bottom line for the trader.** Use the momentum/volatility-weighted rule
with hysteresis; re-fit quarterly; treat bitcoin as the dominant return
engine and gold as the stabilizer; expect the strategy to lag a pure bitcoin
hold in strong bull regimes by design, in exchange for materially lower
drawdowns.
