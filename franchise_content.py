"""Editorial content for The Franchise Brief.

Kept separate from editions.py so that file stays a readable index of what
editions exist, and separate from daily_brief.py so the pipeline stays
edition-agnostic. Nothing here is executable logic — it is the brief's
editorial position, expressed as prompts.
"""

BRIEF_DESC = ("a WEEKLY Australian franchising brief read by landlords, "
              "investors and franchise operators")

DEAL_THRESHOLD = "$2 million"   # franchise deals run smaller than property

GEOGRAPHY = (
    "Australia and New Zealand, with attention to Queensland and New South "
    "Wales. Include international brand news only where it changes an "
    "Australian network."
)

PRIORITY_SOURCES = [
        "afr.com", "theaustralian.com.au", "smh.com.au", "insideretail.com.au",
        "qsrmedia.com.au", "hospitalitymagazine.com.au", "smartcompany.com.au",
        "franchisebusiness.com.au", "insidesmallbusiness.com.au",
        "startupdaily.net", "businessnewsaustralia.com", "accc.gov.au",
        "franchise.org.au", "insidefmcg.com.au", "ragtrader.com.au",
    ]

AUDIENCE = """This brief is read by people whose money and buildings are tied to
franchise networks. It serves three overlapping readers in one email:

  1. THE LANDLORD — owns centres and buildings occupied by franchised
     businesses. Cares about which brands are expanding, which are closing
     stores, which franchisees are failing, what a network's unit economics
     mean for rent-paying capacity, and which franchisors are strong enough
     to underwrite a 10-year lease.
  2. THE INVESTOR — evaluates franchise systems as investments: multiples
     paid, deal structures, which private equity and VC firms are buying and
     exiting, how listed franchisors are trading, roll-ups and consolidation,
     and franchisee-level M&A.
  3. THE OPERATOR — runs or advises franchise systems. Cares about network
     growth and churn, franchisee profitability and disputes, the Franchising
     Code, ACCC enforcement, disclosure obligations, wage compliance,
     supply-chain and input costs, and technology adoption.

Score for the HIGHEST of the three. A private equity firm buying a food group
matters to the investor even if no landlord acts on it this week; a brand
closing 40 stores matters to the landlord even if the investor shrugs."""

RELEVANCE_RUBRIC = """Score every finding 0-10 for how much it changes a decision for those readers.
  9-10  Changes a decision now. A franchise brand entering administration or
        announcing mass closures; a network's store count moving materially;
        a franchise system changing hands with a price or multiple disclosed;
        ACCC enforcement or a Franchising Code change with a compliance date.
  7-8   Strong signal. A franchisor's results with unit economics, network
        numbers or same-store sales; a PE or VC firm entering or exiting the
        sector; a significant franchisee-level acquisition or roll-up; a
        landmark franchisee dispute or class action; a major brand's rollout
        target or format change.
  5-6   Useful context. Sector-wide data on franchise growth, closures or
        profitability; consumer spending data that bears on franchise
        categories; a notable executive appointment at a franchise group.
  3-4   Peripheral. Corporate news with no read-through to a network, a
        balance sheet or a site; minor product launches; awards.
  0-2   Noise. Share-price commentary, opinion pieces, sponsored content,
        franchise-recruitment marketing dressed as news, generic
        "top 10 franchises to buy" listicles.

CALIBRATION — these matter more than they first appear:
  - Store COUNTS are the core metric of this beat. Any item carrying an
    opening or closing number, a network total, or a rollout target is at
    least a 7 — that is the landlord's pipeline and the investor's growth rate.
  - Franchisee distress (not just franchisor distress) is a 7+. Franchisees
    are the actual tenants on the lease.
  - A transaction is only fully useful with a PRICE or MULTIPLE. Capture it
    whenever disclosed; it is the scarcest number in this sector.
  - A senior appointment at a franchisor or a major franchisee group is a 7,
    not a 4. Who runs a network determines whether it opens or closes stores,
    and a chief development officer hire is a growth signal in itself.
  - Regulatory change scores high even when dull. The Franchising Code drives
    the cost base of every network in the country."""

RESEARCH_CLUSTERS = {
    "networks_brands": (
        "Franchise network and brand news: store openings, closures and net "
        "network movement; rollout and expansion targets; brands entering or "
        "exiting Australia; format changes and new store concepts; "
        "master franchise and area development agreements; rebrands, "
        "brand collapses and administrations; same-store sales and unit "
        "economics disclosed by franchisors. Always capture STORE COUNTS."
    ),
    "capital_deals": (
        "Franchise sector capital and M&A: private equity and venture capital "
        "investments, exits and auction processes involving franchise or "
        "multi-site consumer businesses; trade sales of franchise systems; "
        "franchisee-level acquisitions and roll-ups; IPOs and delistings; "
        "capital raisings; valuation multiples and prices paid; which firms "
        "are buying and which are selling."
    ),
    "people_appointments": (
        "People movement across Australian franchising: CEO, COO, CFO, chief "
        "development, chief operating and general manager appointments and "
        "departures at franchisors, franchisee groups, master franchisees and "
        "the private equity firms that own them; board and chair changes; "
        "founders stepping back or selling down; heads of franchise "
        "development, network operations and property/leasing roles; senior "
        "hires poached between networks; new country or state managers for "
        "international brands entering Australia. Capture the person's NAME, "
        "the role, the brand, where they came from, and what they achieved "
        "there — a hire from a network that tripled its store count is a "
        "signal about where the new employer intends to go."
    ),
    "regulation_disputes": (
        "Franchising regulation and conflict: Franchising Code of Conduct "
        "changes, ACCC investigations, enforcement and court action; "
        "franchisee class actions and disputes; disclosure document and "
        "unfair contract term obligations; Fair Work and wage compliance in "
        "franchise networks; ASBFEO interventions; state fair trading "
        "decisions affecting franchising."
    ),
}

COVERAGE = """COVER ALL OF THE FOLLOWING. The first two are the ones general news
misses, so search them explicitly rather than hoping they surface:

  1. DEALS AND CAPITAL — private equity and venture capital investments,
     exits and auction processes in franchise and multi-site consumer
     businesses; trade sales of franchise systems; franchisee-level
     acquisitions and roll-ups; IPOs, delistings and capital raisings.
     ALWAYS capture the price or multiple where disclosed.
  2. STORE OPENINGS AND CLOSURES — the core of this brief. For every network
     movement capture as much as is reported: how many stores, WHERE (suburb,
     centre, state), the opening or closing DATE, the investment figure, jobs
     created, the format, whether the site is franchisee or corporate owned,
     and the network total before and after. Also capture forward pipeline:
     rollout targets, sites under construction, leases signed, development
     agreements, and how many the brand says it will open this year and next.
     A landlord reads this section as a leasing pipeline, so vague statements
     like "expanding nationally" are worthless without numbers and locations.
  2b. PEOPLE MOVEMENT — senior appointments and departures at franchisors,
     large franchisee groups, master franchisees and their PE owners: CEO,
     COO, CFO, chief development officer, heads of franchise development,
     operations and property. Give the person's name, the role, who they
     replaced, where they came from and what the network did under them.
     Executive moves telegraph strategy months before it is announced.
  3. Franchisee health — profitability, distress, administrations, disputes,
     class actions, sentiment surveys, franchisee association activity.
  4. Regulation — Franchising Code of Conduct, ACCC investigation and
     enforcement, disclosure obligations, unfair contract terms, Fair Work
     and wage compliance in networks, ASBFEO matters.
  5. Listed franchisor results — same-store sales, network totals, margins,
     guidance, unit economics.
  6. The property angle — franchise brands taking or surrendering sites,
     centre tenancy mix, what network moves mean for landlords.
  7. Consumer demand data bearing on franchise categories: QSR, coffee,
     fitness, beauty, automotive services, education, home services.
  8. People moves at franchise groups and their investors; franchise
     technology and systems adoption."""

INTEL_CATEGORIES = """Search for Australian FRANCHISE SECTOR intelligence — the slower-moving
material that shapes the sector rather than breaking news. Hunt each of these
four categories explicitly:

  1. SECTOR RESEARCH AND DATA — franchise sector size, growth and closure
     rates; franchisee profitability and sentiment surveys; IBISWorld,
     FRANdata, Franchise Council of Australia and bank/consultant research;
     consumer spending by franchise category (QSR, coffee, fitness, beauty,
     automotive services, education, home services); wage, food and occupancy
     cost indices that hit franchisee margins. Capture the NUMBERS.
  2. SYSTEMS CHANGING HANDS — franchise systems for sale, auction processes
     under way, brands seeking investors or master franchisees, networks
     being wound down or restructured. What is COMING to market matters as
     much as what has been done.
  3. FUND, PLATFORM AND CORPORATE M&A — private equity and VC raising funds
     for or exiting consumer/multi-site businesses; franchisee roll-ups and
     consolidators; listed franchisor takeover approaches and privatisations;
     international brands appointing Australian master franchisees.
  4. REGULATION AND POLICY — Franchising Code of Conduct amendments, ACCC
     enforcement and guidance, disclosure and unfair contract term rules,
     Fair Work and wage compliance actions in networks, ASBFEO reports,
     state retail lease legislation affecting franchised sites."""

SECTION_PLAN = """SECTIONS, in order. OMIT any section with no genuine news — never pad one
with a placeholder line. If the whole week is thin, say so once at the top:
0. THE WEEK IN FRANCHISING — 3-4 sentences for an owner or investor: what
   moved this week and what it implies about where the sector is heading.
   Reason from the evidence below; if it does not support a view, say so
   rather than manufacturing one.
1. THE BIG ONE — the week's most significant story, 2-3 sentences in <p> tags
   plus one sharp line on what it means.
2. DEALS & CAPITAL — private equity and VC moves, trade sales, roll-ups,
   raisings, IPOs. Give the price or multiple whenever it was disclosed, and
   say what the buyer appears to be betting on.
3. NETWORK MOVES — openings, closures, net store movement, rollout targets,
   brands entering or leaving. Lead with the NUMBERS and be specific: how
   many stores, which suburbs or centres, what dates, what investment, what
   the network total is now. Where a brand has stated a forward target,
   give it. "Expanding in Queensland" is not a story; "three sites opening
   September to November, targeting 10 in WA within four years" is.
4. FRANCHISEE WATCH — franchisee profitability, distress, disputes and
   sentiment. These are the businesses actually on the lease.
5. THE LANDLORD ANGLE — what this week's franchise news means for sites,
   leases, covenants and centre tenancy mix. Make the property implication
   explicit; do not leave the reader to infer it.
6. REGULATION & THE CODE — Franchising Code, ACCC, Fair Work, disclosure and
   dispute-resolution changes. Lead with anything carrying a deadline or cost.
7. RESULTS & NUMBERS — listed franchisor results and sector data: same-store
   sales, network totals, margins, guidance. Figures first, publisher second.
8. PEOPLE MOVES — senior appointments and exits at franchisors, franchisee
   groups, master franchisees and their PE owners. For each: name, role,
   brand, who they replaced, where they came from and what they did there.
   Say what the hire signals — a chief development officer joining from a
   network that tripled its footprint is a growth statement. Three to five
   items where the week supports it; this is a section readers use to see
   where the sector is heading, not filler."""
