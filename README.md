# The Brief

Two automated intelligence emails for a private Australian property group,
built on one pipeline.

| Edition | Cadence | Covers |
|---|---|---|
| **The Asset Brief** | Weekday mornings, ~5:30am AEST | Australian commercial property — transactions, capital and funding, leasing, tenant health, alternatives, operations and compliance, ASX price-sensitive announcements |
| **The Franchise Brief** | Thursday mornings, ~6:30am AEST | Australian franchising — franchisors and franchisees, the PE/VC and listed companies that invest in them, the landlords that house them, network movement and regulation |

Both read at two levels: a strategic layer for a CEO/COO deciding capital
allocation, and an operational layer for the team running the assets.

## How an edition gets made

1. **ASX feed** — price-sensitive announcements pulled from the ASX API for
   every ticker in the edition's config, each linked to its PDF.
2. **Deep-read** — up to 3 substantive announcements per edition have their
   PDFs downloaded and analysed for what most readers miss: cap rate movements
   buried in the notes, WALE shifts, expiry cliffs, covenant headroom, store
   network plans.
3. **Research** — parallel passes over two independent providers:
   - **Anthropic clusters**, hard-restricted to the config's source allowlist.
   - **Grok passes** over the open web. This is not redundancy: every major
     Australian masthead blocks Anthropic's crawler (see Known limits), so
     Grok is the only route to AFR, The Australian, SMH and The Age. It runs
     three passes — general news, a comparables hunt for priced-and-yielded
     transactions, and a market-intelligence sweep for research releases,
     assets coming to market, fund M&A and policy.
4. **Relevance gate** — every finding is scored 0–10 against the reader's
   actual jobs and anything below `min_relevance` is dropped *before* the
   editor sees it. Dropped items are logged with their score, so the threshold
   is tuned from evidence rather than guesswork.
5. **Recency guard** — enforced in code, not just requested in the prompt.
   A finding with no verifiable publication date, or older than its category
   allows, is rejected and logged. High-scoring undated findings get a
   targeted date lookup first rather than being discarded.
6. **Cross-edition de-duplication** — a daily email that repeats itself gets
   ignored. Findings whose URL was already published are dropped, as are
   those re-reporting a published story under a different URL. Legitimate
   follow-ups come through the deal tracker, which reports a *verifiable*
   state change rather than an editorial judgement.
7. **Editor** — one Opus call writes the edition and a structured deal log.
8. **Link verification** — every `<a href>` is checked against the URLs that
   actually came back from research. Anything else is unlinked and logged.
9. **Deterministic blocks** — the trend table and forward calendar are
   computed in plain Python and never pass through a model.
10. **Send and persist** — emailed via Gmail; archived to `docs/`, deal log
    appended to `data/memory_*.json`, both committed back by the workflow.

## Setting it up for yourself

This repo is configured for one specific Australian property group. The
watchlists, markets and tickers are a **worked example, not a default** —
treat replacing them as step one, not a later refinement. The brief is only
as useful as the config, because that is what every relevance score is
measured against.

**1. Take your own copy.** Fork it, or clone and push to a new private repo.
Keep it private: `data/memory_*.json` becomes a proprietary comparables
database, and the config names the tenants and competitors you care about.

**2. Get three credentials.**

| Need | Where | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Add credit — this is not a free tier workload |
| `XAI_API_KEY` | [console.x.ai](https://console.x.ai) | Not optional in practice: without it you lose every major masthead (see Known limits) |
| Gmail app password | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) | Requires 2-Step Verification on the account first |

**3. Make the config yours.** In `config.yml`:
- `watchlist` — your tenants, your competitors, your markets, and `own_group`
  set to your own organisation so the brief doesn't write about you as a rival.
- `portfolio` — your actual assets. It ships empty, and filling it in is the
  single biggest quality difference available: it shifts scoring from "is this
  important?" to "does this touch something we own?"
- `asx_tickers` — **verify every code against the ASX API before adding it.**
  A delisted or wrong code returns HTTP 400 and is skipped with a warning, so
  it fails silently forever. Two of the original tickers were dead for months.
- `allowed_domains` — your trade press. Check the run log after adding one;
  a domain that blocks Anthropic's crawler makes the API reject the whole
  request, and the code will tell you which to remove.

Do the same in `config_franchise.yml`, or delete that edition and its workflow
if you only want the daily.

**4. Run it locally before scheduling it.**

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in; .env is gitignored
DRY_RUN=1 python editions.py property
```

That writes `brief_preview.html` and sends nothing. Read it. Then check the
run log: every dropped finding is printed with its relevance score, and every
stale one with its age. That log is how you tune `min_relevance` — from
evidence, not guesswork.

**5. Add the five repo secrets** (Settings → Secrets and variables → Actions):
`ANTHROPIC_API_KEY`, `XAI_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
`RECIPIENT_EMAIL` (comma-separated; all recipients are BCC'd).

**6. Test the workflow, then let it run.**

```bash
gh workflow run "Daily Asset Brief" -f dry_run=true
```

Download the artifact and check it. Then run it once for real. The cron takes
over from there — 5:30am AEST weekdays, and Thursday 6:30am for the franchise
weekly. Times are Brisbane-based (no DST); if your readers are in Sydney or
Melbourne the arrival time drifts by an hour for half the year.

**What to expect in the first fortnight.** The trend table renders nothing
until it has three transactions with yields in a single sector, so it will be
absent at first and that is correct — it refuses to publish a median off thin
data. Yield varies run to run; a quiet week produces a short brief. Both are
working as intended.
## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill it in; .env is gitignored

python editions.py property    # the daily
python editions.py franchise   # the weekly
python editions.py all         # both in sequence
```

`DRY_RUN=1` writes `brief_preview.html` and sends nothing. A second real send
on the same day is refused unless `FORCE_SEND=1`, so a re-run can't double-mail.
## Adding an edition

Editions are one function each in `editions.py`. The pipeline in
`daily_brief.py` is edition-agnostic; an edition supplies only its editorial
position — audience, relevance rubric, research clusters, section order — plus
a config file. `franchise_content.py` is the worked example.

## The trend engine

`data/memory_*.json` accumulates every transaction the brief records — asset,
sector, state, price, yield, buyer type, agent. `portfolio_trends.py` computes
medians and cohort movement from it in plain Python:

> *Retail: median 6.05% across 4 deals (−45bps vs prior cohort)*

It refuses to publish a median under three data points and renders nothing at
all while the database is thin. This is the one thing a competitor cannot get
by subscribing to the same newsletters — and it only builds if editions run
daily, so start it early.

## The control panels: `config.yml` and `config_franchise.yml`

- **`portfolio`** — *the highest-leverage field in the file, and it starts
  empty.* Fill in your actual assets (name, sector, suburb, anchors) and every
  pass shifts from "is this important?" to "does this touch something we own?"
  A centre trading two suburbs from yours is a direct valuation comparable.
- **`watchlist`** — tenants, competitors, markets, agents. Matches get a
  ⚑ WATCHLIST flag and priority placement. `own_group` is you, and is written
  about as such rather than as a rival.
- **`allowed_domains`** — the allowlist for the Anthropic passes. Add a domain
  to admit a source; check the run log afterwards, because a domain that
  blocks the crawler makes the API reject the *whole* request.
- **`blocked_domains`** — never contributed by Grok regardless of score.
  Retail stock-commentary sites live here.
- **`min_relevance`** — the junk filter, 0–10. Start at 5.
- **`max_finding_age_days` / `max_comparable_age_days` / `max_intel_age_days`**
  — recency ceilings by category. News is strict; a comparable stays useful
  far longer than a news story, and a quarterly research release *is* the
  current benchmark for months.
- **`ticker_notes`** — why each listed company matters, shown beside its
  announcements. Without it an unfamiliar ticker is noise.
- **`asx_tickers`** — verify new codes against the ASX API before adding;
  a delisted code fails silently forever.

## Cost

Measured, and printed as a `COST` line at the end of every run:

| | Per edition | Per month |
|---|---|---|
| Asset Brief (daily, ~21/mo) | ~$1.80–2.00 | **~$40** |
| Franchise Brief (weekly, ~4/mo) | ~$2.40–2.50 | **~$10** |

Anthropic only — Grok is billed separately by xAI. Input tokens dominate,
because the server-side search loop resends accumulated results each
iteration. Reducing search count does *not* reliably reduce cost; the model
simply uses more per call.

## Known limits

- **Every major Australian masthead blocks Anthropic's crawler** — AFR, The
  Australian, SMH, The Age, Courier Mail, Brisbane Times, ABC, news.com.au,
  The Guardian. Worse, leaving one in `allowed_domains` makes the API reject
  the entire request. The code strips offending domains and retries, logging
  a warning; prune them when you see it. Grok is what recovers this coverage.
- **Grok is not allowlist-constrained.** It searches the open web, which is
  why it reaches the mastheads — but the "nothing outside the list can appear"
  guarantee does not hold for its findings. Off-list domains are logged every
  run; set `enforce_allowlist_for_grok: true` to restore the hard guarantee at
  the cost of losing sources you have not pre-approved.
- **Yield swings run to run.** A thin week is thin regardless of thresholds;
  raising a ceiling removes a rejection but cannot retrieve what the search
  did not surface.
- **Research-house landing pages are often undated** by design, and are
  rejected by the recency guard even after a date lookup.
- **The ASX API is unofficial** (it is what asx.com.au itself uses). Failures
  are logged and skipped; check the run summary for `[warn] ASX` lines.
- **Trust but verify.** Every item is linked. Click through before repeating
  a number in a meeting.
