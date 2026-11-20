# Data gaps

India publishes a great deal of electricity data. Almost none of it is
comparable.

That distinction matters, and it is the argument of this page. The common
assumption — inside and outside the sector — is that the numbers are secret, or
that utilities are withholding them. They are not. Thirty-two states publish
demand. Regional load despatch centres publish daily generation. The Central
Electricity Authority publishes monthly capacity and daily generation. The
problem is that each publishes to its own convention, on its own cadence, in its
own format, with its own boundary definitions. There is no layer that makes them
line up.

This project is that layer, and building it surfaced exactly where the public
record thins out. What follows is not a list of caveats about our numbers. It is
a list of things India cannot currently know about its own grid, each with the
measurement that would close it.

Every figure below is checkable against the live API. Where a number moves, the
endpoint is named.

---

## 1. Three states in thirty-two report what they are actually burning

Live, fuel-level generation — a real SCADA feed saying *this much coal, this
much solar, right now* — is published by **Punjab, Delhi, Karnataka,
Chhattisgarh and Maharashtra**. Everything else is inferred from yesterday's
reports or the day before's dispatch schedule.

At the time of writing, `GET /v1/zones` returns **3 states measured, 13 on
day-old actuals, 15 on a blended daily report, and 1 with no carbon intensity at
all.** Five states publish live mixes; three were reporting when this was
written, because Punjab's API returns intermittent 500s and Maharashtra's needs
a vision model to read a JPEG.

So the honest position is not "four of thirty-two." It is **three to five of
thirty-two, depending on the hour** — and which three is not stable.

The consequence is that for 90% of India, the fuel mix behind any given
megawatt is a modelled estimate, not an observation. Our estimates are
backtested daily against published actuals and labelled as estimates
everywhere they appear. That makes them honest. It does not make them
measurements.

**What would close it:** SLDCs already have this data — it is on the operator's
screen in every control room in the country. It needs to leave the control room
in a machine-readable form. Chhattisgarh does exactly this today with an HTML
table refreshed every 30 seconds, so the bar is not technical.

## 2. Plant-level dispatch exists for about twelve states

MERIT publishes plant-wise scheduled dispatch, which is what lets a schedule be
mapped to a fuel via the plant registry. It covers **roughly 12 of 31 states**.

For the rest, the fallback is a state-level fuel split with no plant attached.
That is workable for a carbon number and useless for anything that needs to know
*which* plant moved — curtailment analysis, congestion, marginal emissions, the
question of which generator sets the price at 8pm.

**What would close it:** extending MERIT's plant-wise coverage to the remaining
states. The scheduling data exists; it is exchanged between generators and load
despatch centres continuously. Only the published subset is partial.

## 3. States do not agree on what counts as their generation

This is the gap that does the most quiet damage, because nothing about it looks
broken.

CEA's daily renewable report attributes **ISTS-connected renewable parks to the
state that physically hosts them**. Rajasthan hosts a very large amount of solar
that is contracted to buyers in other states. The result: **Rajasthan's solar in
the RE report reads roughly four times its control-area number.**

Neither figure is wrong. They answer different questions — *what was generated
inside this boundary* versus *what this state's grid actually drew on*. But they
are published without the distinction being explicit, and anyone combining them
produces a number that is confidently incorrect.

The same ambiguity runs through every import-heavy state. Kerala imports
roughly 90% of its electricity; Tamil Nadu around 40%. Our carbon intensity for
those states describes **in-state generation**, not consumption, because
imported energy arrives with no fuel mix attached. We assign it a deliberately
conservative near-coal factor and label the result estimated — which is why
Kerala, a hydro-rich state, does not read as one.

**What would close it:** inter-state flow data at time-block resolution.
Attribute imports to the exporting state's actual mix and consumption-based
accounting becomes possible. The flows are measured — they settle financially
every fifteen minutes — but are not published in a usable form.

## 4. The current plant registry has no coordinates — and most solar has no address

A current registry does exist. NITI Aayog's India Climate & Energy Dashboard
publishes India's power plants unit by unit, with status, commissioning date and
owner, and its operational total — **559 GW in November 2026** — matches CEA's
installed capacity to within 1%. It replaced a four-year-old open registry on
this map.

What it doesn't have is a single coordinate. Every map of Indian power plants
therefore has to guess where they are. Ours places 394 of 443 coal, gas,
nuclear and large hydro plants by matching their names against the 2021 WRI
registry and OpenStreetMap, and puts the other 46 at the centre of their
district, marked as approximate.

Solar and wind are worse: they are published only as **totals per district**,
and **139 of India's 171 GW of solar only as totals per state** — "districts
not specified". From public data, you cannot say where most of India's solar
fleet is. The map draws these as discs, not columns, so a state's 36 GW is never
read as one plant.

And the registry is machine-readable in name only. The download sits behind a
CAPTCHA, the dashboard's own API returns encrypted responses, and no licence for
reuse is stated.

**What would close it:** the same table with a coordinate (or at least a stable
plant identifier shared with CEA's reports), renewable capacity listed project
by project rather than summed by district, an open licence, and a plain file
download.

## 5. Ownership is published — except for the fastest-growing half of the grid

The same registry names an implementing agency for every coal, gas, nuclear and
hydro unit: NTPC runs 52 GW of coal, Adani Power 12 GW, MAHAGENCO 10 GW. That
closes a gap the previous open registry left wide open — it carried an owner for
4% of capacity, and not NTPC's.

But solar and wind, **230 GW and 41% of India's capacity**, come with no owner at
all, because they're only published as totals. So *what share of a state's
renewable power is private, and whose* still can't be answered from public data
— for exactly the segment growing fastest. CEA's state-wise sector split (state,
private, central) helps, but it is capacity, not generation, and solar and wind
run at far lower capacity factors than coal.

**What would close it:** renewable projects listed individually with their
developer. The tender and connectivity records that would make this possible
already exist at SECI, the CTU and the state agencies; they aren't joined up or
published as one table.

## 6. The sources are not as independent as they look

Vidyut Pravah and MERIT are different websites run by different teams with
different interfaces. They read the **same NLDC backend**. Many states' demand
values are byte-identical between them at the same time block.

This matters because cross-checking two sources against each other feels like
validation and here is not. If NLDC publishes a wrong number, both carry it
identically, and any consistency check between them passes. Genuine independent
validation for our numbers comes only from the separate SLDC, RLDC report and
CEA chains — which is why we run a daily backtest against published actuals
rather than a live cross-check.

**What would close it:** nothing, on the publisher's side. This one is a
reminder for anyone building on Indian grid data: count your independent
chains, not your endpoints.

---

## Why publish this

A project that reports its own limitations with numbers attached is making a
different claim than one that reports only its outputs. Every gap above is
either visible in our API responses or documented in
[METHODOLOGY.md](/methodology) — this page collects them so they can be argued
with rather than discovered.

It is also, deliberately, a request. Each section ends with the specific
measurement that would close it. Most are not expensive. Several are schema
decisions on data that already exists and already moves between institutions
every fifteen minutes. The
[draft National Electricity Data Sharing Framework](https://www.downtoearth.org.in/energy/indias-draft-power-data-framework-aims-to-make-electricity-sector-data-public-but-remains-voluntary)
proposes a CEA-mandated machine-readable standard across 66 datasets, which
would address more of this list than anything else currently on the table.

If you operate one of these systems and something here is wrong or out of date,
that is worth more to us than a correction to any single number — the code is
open at
[github.com/ADIMANV/India-Energy-Data](https://github.com/ADIMANV/India-Energy-Data).
