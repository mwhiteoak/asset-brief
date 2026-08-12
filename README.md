# The Asset Brief

A daily automated intelligence email for a head of asset management covering Australian commercial property — transactions, leasing, tenant news, alternatives (childcare/aged care), people moves, proptech, ASX price-sensitive announcements and market signals. AU-wide with a QLD/NSW lens. Lands weekday mornings ~5:45am AEST; Monday wraps the weekend; Friday adds a Week in Review.

## How an edition gets made

1. **ASX feed** — price-sensitive announcements are pulled directly from the ASX API for every ticker in `config.yml` (~40 A-REITs, retailers and operators), each linked to its announcement PDF.
2. **Deep-read pass** — up to 3 substantive announcements per edition (results packs, annual reports, investor presentations, strategy/portfolio updates — dividends and director notices are skipped) have their PDFs downloaded and analysed by a dedicated analyst call that hunts for what most readers miss: cap rate movements buried in the notes, WALE shifts, expiry cliffs, impairments, held-for-sale assets, store network plans. Findings render as a "What most will miss" block under the announcement, each with a page reference. Adds roughly $0.20–0.60 on days with results (results season will be the expensive-and-worth-it weeks). Image-only PDFs that defeat text extraction fall back to a plain link.
3. **Research pass** — four parallel Claude calls (capital markets / occupiers & people / alternatives & proptech / operations & compliance), each with web search **hard-restricted to the approved source allowlist** — it technically cannot search or cite anything outside it.
4. **Relevance gate** — every finding is scored 0–10 against the reader's five actual jobs (property management, leasing, marketing, acquisitions & disposals, facilities management) and anything below `min_relevance` in `config.yml` is discarded *before* the editor sees it. Dropped items are logged with their score so you can tune the threshold rather than guess. This is what stops the brief becoming a press-release feed.
5. **Editor pass** — one Claude call receives the surviving findings (highest-scoring first), ASX items, your **watchlist**, the last 14 days of headlines (no repeats) and the **deal tracker** (open LOIs/DD deals it checks for movement), then writes the edition and a structured deal log. Sections with no genuine news are omitted, not padded.
6. **Link verification** — every `<a href>` the editor emits is checked against the set of URLs that actually came back from the research and ASX feeds. Anything else is unlinked and logged. A hallucinated link is worse than no link, because it looks checkable.
7. **Extras** — market signals strip (RBA cash rate, 10yr bond, AUD, A-REIT index move) fetched from official RBA CSVs + Yahoo; optional Grok-sourced funny tweet.
8. **Send & persist** — emailed via Gmail; the edition is archived to `docs/` and the deal log appended to `data/memory.json`, both committed back to the repo. Over time `data/memory.json` becomes your private transactions database — every deal with price, yield, sector and state.

## Setup (~15 minutes)

1. **Create a private GitHub repo** and push these files (keep `.github/workflows/daily-brief.yml` at that exact path).
2. **Gmail app password**: Google Account → Security → enable 2-Step Verification → https://myaccount.google.com/apppasswords → create one named "Asset Brief".
3. **Anthropic API key**: https://console.anthropic.com — add credit. A daily run makes 4 research calls on Sonnet (~32 searches) + 1 editor call on Opus: roughly **$0.80–1.40/day**, call it **$20–30/month**, more in results season when the ASX deep-read fires. The editor is the only Opus call — drop `EDITOR_MODEL` to `claude-sonnet-5` in `daily_brief.py` to roughly halve it.
4. **(Optional) xAI key** for the tweet section: https://console.x.ai. Skip it and that section is simply omitted.
5. **Add repo secrets** (Settings → Secrets and variables → Actions): `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, optionally `RECIPIENT_EMAIL` and `XAI_API_KEY`.
6. **Test**: Actions → "Daily Asset Brief" → Run workflow with **Dry run ticked** — download `brief-preview.html` from the run artifacts and check it. Then run unticked to send for real.

   To test locally instead, copy `.env.example` to `.env`, fill it in, then `pip install -r requirements.txt` and `python daily_brief.py`. `.env` is gitignored. With `DRY_RUN=1` it writes `brief_preview.html` and sends nothing. A second real send on the same day is refused unless you set `FORCE_SEND=1`, so a re-run can't double-mail your list.
7. **(Optional) archive site**: Settings → Pages → deploy from branch, folder `/docs` — gives you a browsable archive of every edition.

## The control panel: `config.yml`

Everything you'll routinely change lives here, no code required:

- **`allowed_domains`** — the source allowlist. This works in reverse of a normal search: nothing outside this list can ever appear. Add a domain to admit a source, delete a line to ban one. Check the run log after adding one — if it blocks the crawler you'll see a warning.
- **`min_relevance`** — the junk filter, 0–10. Findings scoring below it never reach the editor. Start at `5`; raise to `6` if the brief feels padded, drop to `4` if it feels thin. The run log prints every dropped item with its score, so tune from evidence.
- **`watchlist`** — your tenants, competitors, markets and agents. Matches get a ⚑ WATCHLIST flag and priority placement (your anchor tenant entering administration outranks someone else's $100m deal). `own_group` is you — flagged, but not written up as a competitor.
- **`asx_tickers`** — the companies whose price-sensitive announcements are pulled every edition.

Deeper tuning (tone, sections, thresholds, send time) lives at the top of `daily_brief.py` and in the workflow cron (UTC; Brisbane = UTC+10 year-round).

## Notes and known limits

- **The major mastheads are not available, and this is a hard limit.** AFR, The Australian, SMH, The Age, Courier Mail and Brisbane Times all block Anthropic's web crawler. They cannot be searched or cited, and worse, leaving one in `allowed_domains` makes the API reject the **entire** search request — one bad domain silently kills a whole research cluster. The code now strips offending domains and retries, logging `[warn] ... dropping domains blocked to the crawler`; when you see that, delete them from `config.yml`. The practical consequence is that the brief runs on trade press (Australian Property Journal, The Urban Developer, RealCommercial, Inside Retail, The Sector et al.), agency press rooms, industry bodies and the ASX — which is where most of the specifics live anyway, but you will not get AFR scoops here.
- **Verify tickers before adding them.** A delisted or wrong code returns HTTP 400 and is skipped with a warning, so it fails quietly forever. `NSR` and `HPI` were removed for exactly this reason.
- **The deal tracker and Week in Review get smarter with age** — they read from `data/memory.json`, which starts empty. Give it two weeks before judging those features.
- **ASX API** — unofficial (it's what the ASX website itself uses). If it ever changes again, the section fails gracefully and the rest of the email still sends; check the Action logs for `[warn] ASX` lines.
- **Trust but verify** — the model can garble a yield. Every item is linked; click through before repeating a number in a meeting.
- **GitHub cron drifts 5–15 min** at busy times. If a run fails outright, GitHub emails you and you can re-run from the Actions tab.
- **Querying your deal database**: `data/memory.json` is plain JSON — e.g. `python -c "import json;[print(i) for i in json.load(open('data/memory.json'))['items'] if i.get('sector')=='childcare' and i.get('state')=='QLD']"`.
