"""Demonstration data for the standard entities. Written by Poiesis, and read-only.

One coherent story, a little over two years long (so that every month has the same month
a year earlier to be compared with), of a mid-sized organisation buying things:
requisitions approved under a delegation of authority, orders sent to sixty-odd
suppliers, goods received (mostly on time), invoices matched (mostly first time), weekly
payment runs, contracts coming up for renewal, a budget per cost centre that two of them
are over. Spend is concentrated the way it really is: ten suppliers carry most of it.
Every screen has work to do on day one: requisitions waiting for approval, invoice
exceptions of every kind, overdue invoices in every ageing bucket, a payment run to
approve, contracts to decide on.

The platform calls this for the standard tables a data model has, and the Data Designer
writes only the rest:

    rows(tables, today=date.today())   ->   {"supplier": [{...}, ...], "invoice": [...], ...}

`tables` maps each table the application has to its column names; rows are produced for
the standard ones among them, holding only the columns the table has. Ids are positions:
the third supplier returned is supplier 3. Deterministic for a given `today` and `seed`.
It depends on nothing but the standard library and `standard.py`, so it runs on its own:

    python backend/app/finance/demo.py < tables.json > rows.json
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import sys
from typing import Any

try:
    from . import standard
except ImportError:  # run as a script, from its own directory
    import standard  # type: ignore[no-redef]

MONTHS_BACK = 27
FISCAL_START_MONTH = 4
VAT = 0.20

FAMILIES: dict[str, list[tuple[str, str, bool]]] = {
    "IT": [("IT-SW", "Software & SaaS", False), ("IT-HW", "Hardware & devices", False), ("IT-CL", "Cloud & hosting", False),
           ("IT-TC", "Telecoms & connectivity", False), ("IT-SV", "IT services & support", False)],
    "Professional services": [("PS-CO", "Consulting", False), ("PS-LG", "Legal services", False),
                              ("PS-AU", "Audit & tax", False), ("PS-RC", "Recruitment & contractors", False),
                              ("PS-TR", "Training & development", False)],
    "Facilities": [("FA-RN", "Rent & rates", False), ("FA-UT", "Utilities", False), ("FA-CL", "Cleaning & waste", False),
                   ("FA-SC", "Security", False), ("FA-MN", "Maintenance & repairs", False)],
    "Marketing": [("MK-MD", "Media & advertising", False), ("MK-AG", "Creative agencies", False),
                  ("MK-EV", "Events & sponsorship", False)],
    "Travel": [("TR-AR", "Air & rail", False), ("TR-HT", "Hotels & subsistence", False), ("TR-FL", "Fleet & vehicle hire", False)],
    "Logistics": [("LG-FR", "Freight & haulage", True), ("LG-WH", "Warehousing", True), ("LG-PK", "Packaging", True)],
    "Direct materials": [("DM-RM", "Raw materials", True), ("DM-CP", "Components & sub-assemblies", True)],
}
# How the organisation's spend divides between the families, roughly.
FAMILY_WEIGHT = {"IT": 22, "Professional services": 14, "Facilities": 13, "Marketing": 8, "Travel": 4, "Logistics": 12,
                 "Direct materials": 27}
STRATEGIC = {"DM-RM", "DM-CP", "IT-CL", "LG-FR", "IT-SW", "PS-RC", "MK-MD", "FA-MN"}   # where one supplier carries the category
EXEMPT_FROM_PO = {"FA-RN", "FA-UT", "IT-TC"}          # rent, utilities and telecoms are billed without an order

COST_CENTERS = [
    ("CC-1000", "Executive Office", "Executive", "Sofia Lindgren"), ("CC-1100", "Finance", "Finance", "Rachel Whitmore"),
    ("CC-1200", "Procurement", "Finance", "Ingrid Solberg"), ("CC-1300", "People & Culture", "HR", "Grace Adeyemi"),
    ("CC-1400", "Legal & Compliance", "Legal", "Marcus Bell"), ("CC-2000", "IT Infrastructure", "Technology", "Priyanka Nair"),
    ("CC-2100", "Software Engineering", "Technology", "Owen Hughes"), ("CC-2200", "Data & Analytics", "Technology", "Laura Fischer"),
    ("CC-3000", "Operations — Leeds", "Operations", "Tom Ashworth"), ("CC-3100", "Operations — Glasgow", "Operations", "Fiona MacLeod"),
    ("CC-3200", "Logistics & Distribution", "Operations", "Carlos Romero"), ("CC-4000", "Marketing", "Commercial", "Hannah Price"),
    ("CC-4100", "Sales", "Commercial", "James Okafor"), ("CC-5000", "Facilities & Estates", "Facilities", "Irene Walsh"),
]
# Which families each cost centre buys, and how heavily.
CC_FAMILIES = {
    "CC-1000": {"Professional services": 5, "Travel": 3}, "CC-1100": {"Professional services": 6, "IT": 2},
    "CC-1200": {"Professional services": 3, "IT": 2, "Travel": 1}, "CC-1300": {"Professional services": 7, "Travel": 1},
    "CC-1400": {"Professional services": 8}, "CC-2000": {"IT": 12, "Professional services": 2},
    "CC-2100": {"IT": 9, "Professional services": 4}, "CC-2200": {"IT": 6, "Professional services": 2},
    "CC-3000": {"Direct materials": 14, "Logistics": 4, "Facilities": 2}, "CC-3100": {"Direct materials": 11, "Logistics": 3, "Facilities": 2},
    "CC-3200": {"Logistics": 9, "Travel": 2}, "CC-4000": {"Marketing": 9, "Travel": 1, "IT": 1},
    "CC-4100": {"Travel": 3, "Marketing": 2, "IT": 1}, "CC-5000": {"Facilities": 12, "IT": 1},
}
OVER_BUDGET = {"CC-2100": 0.84, "CC-3200": 0.91}       # budget as a share of what they are spending
REGIONS = ["London", "North", "Scotland", "Midlands", "South West"]

GL = [("6100", "Software subscriptions"), ("6110", "IT equipment"), ("6120", "Hosting & cloud services"), ("6130", "Telecommunications"),
      ("6200", "Consultancy fees"), ("6210", "Legal fees"), ("6220", "Audit & accountancy"), ("6230", "Agency & contractor staff"),
      ("6240", "Staff training"), ("6300", "Rent & rates"), ("6310", "Light, heat & power"), ("6320", "Cleaning & waste"),
      ("6330", "Security services"), ("6340", "Repairs & maintenance"), ("6400", "Advertising & media"), ("6410", "Agency fees"),
      ("6420", "Events & exhibitions"), ("6500", "Travel"), ("6510", "Accommodation & subsistence"), ("6520", "Vehicle hire & fleet"),
      ("5100", "Carriage & freight"), ("5110", "Warehousing"), ("5120", "Packaging materials"), ("5000", "Raw materials"),
      ("5010", "Components")]
GL_OF = {"IT-SW": "6100", "IT-HW": "6110", "IT-CL": "6120", "IT-TC": "6130", "IT-SV": "6200", "PS-CO": "6200",
         "PS-LG": "6210", "PS-AU": "6220", "PS-RC": "6230", "PS-TR": "6240", "FA-RN": "6300", "FA-UT": "6310",
         "FA-CL": "6320", "FA-SC": "6330", "FA-MN": "6340", "MK-MD": "6400", "MK-AG": "6410", "MK-EV": "6420",
         "TR-AR": "6500", "TR-HT": "6510", "TR-FL": "6520", "LG-FR": "5100", "LG-WH": "5110", "LG-PK": "5120",
         "DM-RM": "5000", "DM-CP": "5010"}

PLACES = ["Northgate", "Calder", "Ashby", "Kestrel", "Marlow", "Pennine", "Harbour", "Thornfield", "Blackwater", "Severn",
          "Langdale", "Whitby", "Castlefield", "Redwood", "Fairmont", "Holloway", "Stirling", "Beacon", "Meridian", "Ironbridge",
          "Oakhurst", "Riverside", "Summit", "Tamar", "Wexford", "Lindisfarne", "Arden", "Brightwell", "Corran", "Dunmore"]
TRADES = {
    "IT-SW": ["Software", "Systems", "Digital", "Cloudworks"], "IT-HW": ["Computing", "Devices", "Technology Supplies"],
    "IT-CL": ["Hosting", "Data Centres", "Cloud Services"], "IT-TC": ["Telecom", "Networks", "Connect"],
    "IT-SV": ["IT Services", "Managed Services", "Support Desk"], "PS-CO": ["Consulting", "Advisory", "Partners"],
    "PS-LG": ["Legal", "Solicitors", "Law"], "PS-AU": ["Chartered Accountants", "Audit", "Tax Advisers"],
    "PS-RC": ["Recruitment", "Talent", "Resourcing"], "PS-TR": ["Training", "Learning", "Academy"],
    "FA-RN": ["Estates", "Property", "Land & Estates"], "FA-UT": ["Energy", "Power & Gas", "Water"],
    "FA-CL": ["Cleaning Services", "Environmental", "Waste Management"], "FA-SC": ["Security", "Guarding", "Protection"],
    "FA-MN": ["Building Services", "Maintenance", "Engineering Services"], "MK-MD": ["Media", "Outdoor", "Broadcast"],
    "MK-AG": ["Creative", "Studio", "Communications"], "MK-EV": ["Events", "Exhibitions", "Live"],
    "TR-AR": ["Travel", "Business Travel"], "TR-HT": ["Hotels", "Hospitality"], "TR-FL": ["Fleet", "Vehicle Hire"],
    "LG-FR": ["Haulage", "Freight", "Logistics"], "LG-WH": ["Warehousing", "Storage & Distribution"],
    "LG-PK": ["Packaging", "Cartons", "Pallets & Packaging"], "DM-RM": ["Metals", "Polymers", "Materials", "Chemicals"],
    "DM-CP": ["Components", "Precision Engineering", "Assemblies", "Electronics"],
}
SUFFIX = {"United Kingdom": ["Ltd", "Ltd", "Ltd", "Group plc", "LLP", "(UK) Ltd"], "Ireland": ["Ltd", "DAC"],
          "Germany": ["GmbH", "AG"], "Netherlands": ["B.V."], "France": ["SAS", "SARL"], "United States": ["Inc.", "LLC"],
          "India": ["Pvt Ltd"], "Poland": ["Sp. z o.o."]}
COUNTRIES = [("United Kingdom", "GBP", ["Leeds", "Manchester", "Birmingham", "Glasgow", "Bristol", "London", "Sheffield",
                                      "Newcastle", "Cardiff", "Nottingham"], 66),
             ("Ireland", "EUR", ["Dublin", "Cork"], 5), ("Germany", "EUR", ["Hamburg", "Munich", "Stuttgart"], 8),
             ("Netherlands", "EUR", ["Rotterdam", "Eindhoven"], 5), ("France", "EUR", ["Lyon", "Lille"], 4),
             ("United States", "USD", ["Boston", "Austin", "Seattle"], 6), ("India", "INR", ["Pune", "Bengaluru"], 4),
             ("Poland", "PLN", ["Gdańsk", "Wrocław"], 2)]
TERMS = ["NET30"] * 9 + ["NET45"] * 3 + ["NET60"] * 3 + ["2/10NET30"] * 3 + ["EOM30"] * 2
REQUESTERS = ["Nadia Rahman", "Ben Thackeray", "Chloe Martin", "Yusuf Demir", "Ellie Watson", "Ravi Shankar", "Megan O'Neill",
              "Lukas Brandt", "Amara Nwosu", "Sean Gallagher", "Priya Desai", "Jack Pemberton", "Holly Fraser", "Omar Siddiqui",
              "Katie Lowe", "Dylan Reyes", "Freya Madsen", "Tariq Aziz"]
BUYERS = ["Daniel Moreau", "Asha Verma", "Callum Reid", "Beatriz Santos", "Niamh Doyle"]
CLERKS = ["Kofi Mensah", "Emily Carter", "Zofia Kowalska"]
RECEIVERS = ["Goods In — Leeds", "Goods In — Glasgow", "Service desk", "Facilities desk"]

ITEMS: dict[str, list[tuple[str, str, float, float]]] = {      # description, unit, typical price, typical quantity
    "IT-SW": [("CRM platform licences, annual", "licence", 540, 60), ("Project management suite, per seat", "licence", 96, 140),
              ("Endpoint protection renewal", "licence", 31, 450), ("Data warehouse subscription", "month", 4200, 12),
              ("Design software, team plan", "licence", 480, 18), ("E-signature service, annual", "licence", 210, 40)],
    "IT-HW": [("14-inch business laptops", "each", 1180, 25), ("27-inch monitors", "each", 265, 40), ("Docking stations", "each", 145, 40),
              ("Network switches, 48-port", "each", 2350, 4), ("Conference room displays", "each", 1890, 3)],
    "IT-CL": [("Cloud compute, reserved capacity", "month", 18500, 3), ("Object storage and transfer", "month", 3900, 3),
              ("Managed database service", "month", 6200, 3), ("Content delivery network", "month", 1450, 6)],
    "IT-TC": [("Leased line, head office", "month", 980, 3), ("Mobile voice and data plans", "month", 3150, 1),
              ("SD-WAN service, 12 sites", "month", 5400, 3)],
    "IT-SV": [("Service desk outsourcing", "month", 12800, 3), ("Penetration test and report", "day", 1150, 8),
              ("Network upgrade, professional services", "day", 890, 14)],
    "PS-CO": [("Operating model review", "day", 1450, 24), ("ERP selection advisory", "day", 1600, 15), ("Process improvement workshops", "day", 1250, 6)],
    "PS-LG": [("Commercial contract review", "hour", 310, 22), ("Employment advice", "hour", 285, 12), ("Property lease negotiation", "hour", 340, 30)],
    "PS-AU": [("Statutory audit fee, interim", "each", 28500, 1), ("Corporation tax compliance", "each", 9400, 1), ("VAT health check", "day", 1100, 5)],
    "PS-RC": [("Contract developer, 3 months", "day", 520, 60), ("Permanent placement fee", "each", 11200, 1), ("Temporary warehouse staff", "hour", 17.5, 640)],
    "PS-TR": [("Leadership programme, cohort of 12", "each", 14400, 1), ("Health and safety refresher", "day", 780, 3), ("Procurement skills certification", "each", 1350, 6)],
    "FA-RN": [("Quarterly rent, Leeds distribution centre", "quarter", 86500, 1), ("Quarterly rent, Glasgow office", "quarter", 41200, 1), ("Service charge, head office", "quarter", 18900, 1)],
    "FA-UT": [("Electricity, half-hourly supply", "month", 21400, 1), ("Gas supply", "month", 7900, 1), ("Water and wastewater", "month", 2350, 1)],
    "FA-CL": [("Contract cleaning", "month", 6850, 1), ("Confidential waste collection", "month", 640, 1), ("Window cleaning", "visit", 920, 2)],
    "FA-SC": [("Manned guarding", "month", 9300, 1), ("CCTV maintenance", "quarter", 2150, 1), ("Access control upgrade", "each", 12400, 1)],
    "FA-MN": [("HVAC planned maintenance", "quarter", 5600, 1), ("Lift servicing", "quarter", 1850, 1), ("Roof repairs, bay 4", "each", 16800, 1), ("Electrical testing", "day", 680, 4)],
    "MK-MD": [("Paid search, monthly spend", "month", 22000, 1), ("Trade press advertising", "insertion", 3400, 4), ("Outdoor campaign, regional", "each", 38000, 1)],
    "MK-AG": [("Brand refresh, creative", "day", 950, 20), ("Video production", "each", 17500, 1), ("Website design sprint", "day", 880, 15)],
    "MK-EV": [("Exhibition stand build", "each", 24500, 1), ("Customer conference venue", "each", 31000, 1), ("Sponsorship, industry awards", "each", 12000, 1)],
    "TR-AR": [("Rail travel, monthly account", "month", 4800, 1), ("Flights, monthly account", "month", 7600, 1)],
    "TR-HT": [("Hotel accommodation, monthly account", "month", 5900, 1), ("Sales kick-off accommodation", "night", 145, 120)],
    "TR-FL": [("Van hire, long term", "month", 3450, 3), ("Pool car lease", "month", 410, 8)],
    "LG-FR": [("Pallet distribution, UK", "pallet", 46, 900), ("Container haulage", "move", 385, 60), ("Express parcel service", "month", 8700, 1)],
    "LG-WH": [("Overflow storage", "pallet-week", 3.4, 6400), ("Pick and pack services", "month", 16400, 1)],
    "LG-PK": [("Corrugated cartons", "thousand", 412, 45), ("Stretch wrap", "roll", 11.8, 1200), ("Timber pallets", "each", 9.6, 2500)],
    "DM-RM": [("Aluminium extrusion, 6063", "tonne", 2840, 28), ("Polypropylene granules", "tonne", 1180, 40), ("Stainless sheet, 304", "tonne", 3120, 14),
              ("Industrial adhesives", "drum", 640, 30), ("Powder coating", "kg", 7.4, 4200)],
    "DM-CP": [("Control boards, rev C", "each", 38.5, 2400), ("Bearing assemblies", "each", 14.2, 5000), ("Wiring harnesses", "each", 22.8, 3200),
              ("Machined housings", "each", 61, 1500), ("Fasteners, assorted", "box", 28, 600)],
}
SAVING_TITLES = ["Consolidate {c} with two suppliers", "Renegotiate {c} rates at renewal", "Move {c} to a three-year agreement",
                 "Reduce {c} demand through policy", "Rationalise the {c} specification", "Rebid {c} across the framework",
                 "Volume rebate on {c}", "Switch {c} to catalogue ordering"]
REJECTIONS = ["No budget left this quarter; resubmit in the next period", "A preferred supplier already covers this",
              "Needs three quotes at this value", "Duplicate of an earlier request", "Specification is unclear; please add detail"]
EXCEPTIONS = {
    "price_variance": ["Unit price on the invoice is above the order price", "Invoice includes a surcharge that is not on the order",
                       "Price uplift applied without an agreed variation"],
    "quantity_variance": ["Invoiced for more than was receipted", "Part delivery invoiced in full"],
    "no_receipt": ["Invoice received before the goods were booked in", "Service not yet confirmed as delivered"],
    "no_po": ["No purchase order quoted; supplier asked for the order number", "Bought outside the ordering process"],
    "duplicate_suspect": ["Same supplier and amount as an earlier invoice", "Invoice number differs only by a leading zero"],
}


def _iso(value: dt.date | dt.datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat()
    return value.isoformat()


def _at(day: dt.date, rnd: random.Random, first: int = 8, last: int = 17) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, rnd.randint(first, last), rnd.randint(0, 59), tzinfo=dt.timezone.utc)


def _add_months(d: dt.date, months: int) -> dt.date:
    index = d.year * 12 + d.month - 1 + months
    year, month = divmod(index, 12)
    last = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month]
    return dt.date(year, month + 1, min(d.day, last))


def _workday(d: dt.date, forward: bool = True) -> dt.date:
    while d.weekday() >= 5:
        d += dt.timedelta(days=1 if forward else -1)
    return d


def fiscal_year(d: dt.date, start_month: int = FISCAL_START_MONTH) -> int:
    return d.year + 1 if start_month != 1 and d.month >= start_month else d.year


def fiscal_period(d: dt.date, start_month: int = FISCAL_START_MONTH) -> int:
    return (d.month - start_month) % 12 + 1


def _due(invoice_date: dt.date, terms: str) -> dt.date:
    if terms.startswith("EOM"):
        first_next = _add_months(invoice_date.replace(day=1), 1)
        return first_next - dt.timedelta(days=1) + dt.timedelta(days=int(terms[3:] or 30))
    days = int(terms.split("NET")[-1] or 30)
    return invoice_date + dt.timedelta(days=days)


def risk(otif: float, quality: float, financial: float, compliance: float, share: float) -> tuple[float, str]:
    """PROC-05, as `rules.supplier_risk` computes it (a test keeps the two in step)."""
    weights = {"delivery": 25, "quality": 20, "financial": 25, "compliance": 20, "dependency": 10}
    raw = {"delivery": 100 - otif, "quality": 100 - quality, "financial": 100 - financial, "compliance": 100 - compliance,
           "dependency": min(100.0, max(0.0, share * 2))}
    score = 0.0
    for k, v in raw.items():
        v = min(100.0, max(0.0, v))
        score += round(min(100.0, v * (4 if k != "dependency" else 1)) * weights[k] / 100, 1)
    score = round(score, 1)
    return score, "low" if score < 34 else "medium" if score < 67 else "high"


class _Story:
    def __init__(self, today: dt.date, seed: int, scale: float, currency: str) -> None:
        self.today = today
        self.rnd = random.Random(seed)
        self.scale = scale
        self.currency = currency
        self.start = _add_months(today.replace(day=1), -MONTHS_BACK)
        self.t: dict[str, list[dict[str, Any]]] = {name: [] for name in standard.ORDER}
        self.cat_ids: dict[str, int] = {}
        self.cc_ids: dict[str, int] = {}
        self.gl_ids: dict[str, int] = {}
        self.by_cat: dict[str, list[int]] = {}
        self.weight: dict[int, float] = {}

    def add(self, table: str, row: dict[str, Any]) -> int:
        self.t[table].append(row)
        return len(self.t[table])

    def money(self, value: float) -> float:
        return round(value + 1e-9, 2)

    # -- reference data ------------------------------------------------------------------
    def reference(self) -> None:
        rnd = self.rnd
        for i, (code, name, dept, owner) in enumerate(COST_CENTERS):
            self.cc_ids[code] = self.add("cost_center", {"code": code, "name": name, "department": dept, "owner_name": owner,
                                                         "region": REGIONS[i % len(REGIONS)], "is_active": True})
        for code, name in GL:
            kind = "capex" if code == "6110" else "expense"
            self.gl_ids[code] = self.add("gl_account", {"code": code, "name": name, "account_type": kind})
        managers = ["Ingrid Solberg", "Daniel Moreau", "Asha Verma", "Callum Reid", "Beatriz Santos", "Niamh Doyle"]
        for f_i, (family, cats) in enumerate(FAMILIES.items()):
            for code, name, direct in cats:
                self.cat_ids[code] = self.add("spend_category", {"code": code, "name": name, "family": family,
                                                                 "is_direct": direct, "manager_name": managers[f_i % len(managers)]})
        for m in range(MONTHS_BACK + 1):
            day = _add_months(self.start, m)
            for ccy, base, drift in (("EUR", 1.17, 0.012), ("USD", 1.27, 0.018), ("INR", 106.0, 1.4), ("PLN", 5.05, 0.06)):
                rate = base + drift * math.sin(m / 2.3 + len(ccy)) + rnd.uniform(-drift, drift) / 2
                self.add("exchange_rate", {"base_currency": self.currency, "currency": ccy, "rate": round(rate, 4),
                                           "rate_date": _iso(day)})

    def suppliers(self) -> None:
        rnd = self.rnd
        used: set[str] = set()
        codes = [c for fam in FAMILIES.values() for c, _, _ in fam]
        per_cat = {c: 2 for c in codes}
        for c in ("DM-RM", "DM-CP", "IT-SW", "LG-FR", "PS-CO", "IT-SV", "FA-MN", "PS-RC", "MK-AG", "IT-HW", "LG-PK", "PS-TR"):
            per_cat[c] += 1
        # The first supplier of every category is active; among the others are the ones being
        # onboarded, the suspended and the retired.
        others = sum(per_cat.values()) - len(codes)
        special = ["approved"] * 5 + ["under_review"] * 4 + ["prospective"] * 3 + ["suspended"] * 2 + ["retired"] * 2
        statuses = special + ["active"] * max(0, others - len(special))
        rnd.shuffle(statuses)
        n = 0
        for code in codes:
            family = next(f for f, cats in FAMILIES.items() if any(c == code for c, _, _ in cats))
            for k in range(per_cat[code]):
                country, ccy, cities, _ = rnd.choices(COUNTRIES, weights=[c[3] for c in COUNTRIES])[0]
                if code in ("FA-RN", "FA-UT", "FA-CL", "FA-SC", "TR-FL"):
                    country, ccy, cities, _ = COUNTRIES[0]
                while True:
                    name = f"{rnd.choice(PLACES)} {rnd.choice(TRADES[code])} {rnd.choice(SUFFIX[country])}"
                    if name not in used:
                        used.add(name)
                        break
                status = statuses.pop() if k > 0 and statuses else "active"
                n += 1
                otif = round(min(99.5, max(62, rnd.gauss(93, 6))), 1)
                quality = round(min(99.9, max(80, rnd.gauss(96.5, 3))), 1)
                financial = round(min(99, max(45, rnd.gauss(92, 8))), 1)
                compliance = rnd.choice([100] * 7 + [95, 90, 75])
                if status == "suspended":
                    otif, financial, compliance = min(otif, 74.0), min(financial, 62.0), 60
                weight = FAMILY_WEIGHT[family] / len(FAMILIES[family]) * (1.0 / (k + 1) ** 2.0) * rnd.uniform(0.8, 1.2)
                if k == 0 and code in STRATEGIC:
                    weight *= 3.0
                onboarded = self.start - dt.timedelta(days=rnd.randint(60, 2400))
                sid = self.add("supplier", {
                    "code": f"SUP-{10400 + n * 7:05d}", "name": name, "spend_category_id": self.cat_ids[code], "country": country,
                    "city": rnd.choice(cities), "status": status, "payment_terms": rnd.choice(TERMS), "currency": ccy,
                    "is_preferred": k == 0 and rnd.random() < 0.8, "is_contracted": False, "otif_pct": otif,
                    "quality_pct": quality, "tax_id": f"{'GB' if country == 'United Kingdom' else country[:2].upper()}{rnd.randint(100000000, 999999999)}",
                    "email": "accounts@" + "".join(ch for ch in name.lower().split(" ")[0] + name.lower().split(" ")[1] if ch.isalnum()) + ".example",
                    "onboarded_at": _iso(onboarded if status not in ("prospective", "under_review") else None),
                    "_code": code, "_financial": financial, "_compliance": compliance,
                })
                if status in ("active", "approved", "suspended", "retired"):
                    self.by_cat.setdefault(code, []).append(sid)
                    self.weight[sid] = weight if status in ("active", "approved") else weight * 0.25

    def contracts(self) -> None:
        rnd, today = self.rnd, self.today
        owners = BUYERS + ["Ingrid Solberg"]
        chosen = sorted(self.weight, key=lambda s: -self.weight[s])[:40]
        plan = (["active"] * 22 + ["expiring"] * 7 + ["expired"] * 4 + ["in_negotiation"] * 3 + ["draft"] * 2 + ["signed"] * 1
                + ["terminated"] * 1)
        rnd.shuffle(plan)
        for i, sid in enumerate(chosen):
            s = self.t["supplier"][sid - 1]
            status = plan[i % len(plan)]
            years = rnd.choice([1, 2, 3, 3, 5])
            if status == "expiring":
                end = today + dt.timedelta(days=rnd.randint(6, 88))
            elif status == "expired":
                end = today - dt.timedelta(days=rnd.randint(5, 150))
            elif status == "terminated":
                end = today - dt.timedelta(days=rnd.randint(30, 200))
            elif status in ("draft", "in_negotiation", "signed"):
                end = today + dt.timedelta(days=365 * years + rnd.randint(20, 80))
            else:
                end = today + dt.timedelta(days=rnd.randint(100, 365 * years))
            start = _add_months(end, -12 * years) + dt.timedelta(days=1)
            annual = round(self.weight[sid] * 1_150_000 / 100 * rnd.uniform(0.8, 1.2), -2)
            category = next(name for fam in FAMILIES.values() for c, name, _ in fam if c == s["_code"])
            self.add("contract", {
                "reference": f"CTR-{start.year}-{1000 + i * 13:04d}", "title": f"{category} — {s['name']}",
                "supplier_id": sid, "spend_category_id": s["spend_category_id"], "owner_name": rnd.choice(owners),
                "status": status, "start_date": _iso(start), "end_date": _iso(end), "value": self.money(annual * years),
                "annual_value": self.money(annual), "currency": self.currency, "notice_days": rnd.choice([30, 60, 90, 90]),
                "auto_renew": rnd.random() < 0.35,
            })
            if status in ("active", "expiring", "signed"):
                s["is_contracted"] = True
                s["_contract"] = len(self.t["contract"])

    # -- the buying --------------------------------------------------------------------
    def pick_supplier(self, code: str) -> int:
        pool = self.by_cat.get(code) or [1]
        return self.rnd.choices(pool, weights=[self.weight[s] for s in pool])[0]

    def lines_for(self, code: str, target: float) -> list[dict[str, Any]]:
        rnd = self.rnd
        chosen = rnd.sample(ITEMS[code], k=min(len(ITEMS[code]), rnd.choice([1, 1, 2, 2, 3])))
        lines = []
        for i, (desc, unit, price, qty) in enumerate(chosen, start=1):
            standard_price = round(price * rnd.uniform(0.97, 1.03), 2)
            unit_price = round(standard_price * rnd.choice([1, 1, 1, 0.97, 0.95, 0.92, 1.02, 1.04]), 2)
            quantity = max(1, round(qty * rnd.uniform(0.5, 1.5)))
            lines.append({"line_no": i, "description": desc, "quantity": float(quantity), "unit": unit, "unit_price": unit_price,
                          "standard_price": standard_price, "amount": self.money(quantity * unit_price),
                          "spend_category_id": self.cat_ids[code], "gl_account_id": self.gl_ids[GL_OF[code]]})
        whole = sum(l["amount"] for l in lines)
        if target and whole:
            factor = target / whole
            for l in lines:
                l["quantity"] = float(max(1, round(l["quantity"] * factor)))
                l["amount"] = self.money(l["quantity"] * l["unit_price"])
        return lines

    def orders(self) -> None:
        rnd, today = self.rnd, self.today
        span = (today - self.start).days
        count = int(640 * self.scale)
        plan = []
        for cc, fams in CC_FAMILIES.items():
            for family, w in fams.items():
                plan.append((cc, family, w))
        weights = [w for _, _, w in plan]
        for n in range(count):
            cc, family, _ = rnd.choices(plan, weights=weights)[0]
            code = rnd.choice([c for c, _, _ in FAMILIES[family] if c not in EXEMPT_FROM_PO] or [FAMILIES[family][0][0]])
            sid = self.pick_supplier(code)
            s = self.t["supplier"][sid - 1]
            # The organisation buys a little more each year, and the last weeks hold the work in progress.
            age = int(span * rnd.random() ** 1.12) if n % 12 else rnd.randint(0, 16)
            order_date = _workday(today - dt.timedelta(days=age), forward=False)
            target = min(160_000, max(350, rnd.lognormvariate(9.1, 0.95))) * (1.6 if family == "Direct materials" else 1)
            lines = self.lines_for(code, target)
            amount = self.money(sum(l["amount"] for l in lines))
            lead = rnd.randint(5, 40) if family != "Professional services" else rnd.randint(20, 75)
            expected = _workday(order_date + dt.timedelta(days=lead))
            on_time = rnd.random() * 100 < s["otif_pct"]
            delivered = expected - dt.timedelta(days=rnd.randint(0, 4)) if on_time else expected + dt.timedelta(days=rnd.randint(1, 18))
            delivered = _workday(max(delivered, order_date + dt.timedelta(days=1)))
            status, received_amount = "sent", 0.0
            if s["status"] in ("suspended", "retired") and age < 120:
                age, order_date = age + 150, _workday(order_date - dt.timedelta(days=150), forward=False)
                expected, delivered = expected - dt.timedelta(days=150), delivered - dt.timedelta(days=150)
            if rnd.random() < 0.025:
                status = "cancelled"
            elif age <= 2:
                status = rnd.choice(["draft", "pending_approval", "pending_approval"])
            elif age <= 6 and rnd.random() < 0.6:
                status = rnd.choice(["pending_approval", "approved", "approved", "sent"])
            elif delivered <= today:
                part = rnd.random() < 0.09
                status = "partially_received" if part else "received"
                received_amount = self.money(amount * rnd.uniform(0.35, 0.8)) if part else amount
            requester = rnd.choice(REQUESTERS)
            po_id = self.add("purchase_order", {
                "reference": f"PO-45{10020000 + n * 37:08d}"[:13], "supplier_id": sid, "requisition_id": None,
                "contract_id": s.get("_contract"), "cost_center_id": self.cc_ids[cc], "spend_category_id": self.cat_ids[code],
                "buyer_name": rnd.choice(BUYERS), "status": status, "amount": amount, "currency": self.currency,
                "received_amount": received_amount, "invoiced_amount": 0.0, "order_date": _iso(order_date),
                "expected_delivery": _iso(expected), "delivered_at": _iso(delivered) if status == "received" else None,
                "payment_terms": s["payment_terms"], "created_at": _iso(_at(order_date, rnd)),
                "_code": code, "_cc": cc, "_family": family, "_requester": requester, "_delivered": delivered,
                "_on_time": on_time, "_title": lines[0]["description"],
            })
            share = received_amount / amount if amount else 0
            for l in lines:
                got = l["quantity"] if share >= 1 else float(round(l["quantity"] * share))
                self.add("purchase_order_line", {**l, "purchase_order_id": po_id, "received_quantity": got, "invoiced_quantity": 0.0})
            if received_amount:
                parts = [received_amount] if (share < 1 or rnd.random() < 0.8) else [self.money(received_amount * 0.6), self.money(received_amount * 0.4)]
                for j, part_amount in enumerate(parts):
                    when = delivered - dt.timedelta(days=(len(parts) - 1 - j) * rnd.randint(3, 9))
                    self.add("goods_receipt", {
                        "reference": f"GR-50{len(self.t['goods_receipt']) * 3 + 100231:06d}", "purchase_order_id": po_id,
                        "received_by": rnd.choice(RECEIVERS), "received_at": _iso(_at(max(when, order_date), rnd, 7, 16)),
                        "quantity": float(sum(l["quantity"] for l in lines)) * (part_amount / amount if amount else 0),
                        "amount": part_amount, "status": "posted", "on_time": on_time, "in_full": share >= 1,
                        "quality_ok": rnd.random() * 100 < s["quality_pct"],
                    })

    def requisitions(self) -> None:
        rnd, today = self.rnd, self.today
        approvers = {c: o for c, _, _, o in COST_CENTERS}
        # Every order of the last fourteen months came from a request that was approved and ordered.
        for po_id, po in enumerate(self.t["purchase_order"], start=1):
            order_date = dt.date.fromisoformat(po["order_date"])
            if (today - order_date).days > 430 or po["status"] == "cancelled":
                continue
            created = _workday(order_date - dt.timedelta(days=rnd.randint(3, 14)), forward=False)
            submitted = created + dt.timedelta(days=rnd.randint(0, 1))
            approved = submitted + dt.timedelta(days=rnd.choice([0, 1, 1, 1, 2, 2, 3, 5]))
            rid = self.add("requisition", {
                "reference": f"PR-{104000 + len(self.t['requisition']) * 11}", "title": po["_title"],
                "justification": "Needed for planned work; budgeted this year.", "requester_name": po["_requester"],
                "cost_center_id": po["cost_center_id"], "spend_category_id": po["spend_category_id"],
                "supplier_id": po["supplier_id"], "amount": po["amount"], "currency": self.currency, "status": "ordered",
                "needed_by": po["expected_delivery"], "created_at": _iso(_at(created, rnd)),
                "submitted_at": _iso(_at(submitted, rnd)), "approved_at": _iso(_at(min(approved, order_date), rnd)),
                "approver_name": approvers[po["_cc"]], "purchase_order_id": po_id,
            })
            po["requisition_id"] = rid
        # … and the ones still in progress, refused or dropped.
        plan = [(cc, fam, w) for cc, fams in CC_FAMILIES.items() for fam, w in fams.items()]
        states = ["draft"] * 12 + ["submitted"] * 19 + ["approved"] * 13 + ["rejected"] * 10 + ["cancelled"] * 6
        for status in states[: int(len(states) * self.scale) or 1]:
            cc, family, _ = rnd.choices(plan, weights=[w for _, _, w in plan])[0]
            code = rnd.choice([c for c, _, _ in FAMILIES[family] if c not in EXEMPT_FROM_PO] or [FAMILIES[family][0][0]])
            desc, unit, price, qty = rnd.choice(ITEMS[code])
            amount = self.money(price * max(1, round(qty * rnd.uniform(0.4, 1.4))))
            age = {"draft": rnd.randint(0, 6), "submitted": rnd.choice([0, 0, 1, 1, 2, 3, 4, 6, 9]), "approved": rnd.randint(0, 5),
                   "rejected": rnd.randint(2, 40), "cancelled": rnd.randint(3, 60)}[status]
            created = _workday(today - dt.timedelta(days=age + rnd.randint(0, 2)), forward=False)
            submitted = None if status == "draft" else min(today, created + dt.timedelta(days=rnd.randint(0, 1)))
            decided = status in ("approved", "rejected")
            self.add("requisition", {
                "reference": f"PR-{104000 + len(self.t['requisition']) * 11}", "title": desc,
                "justification": rnd.choice(["Replacement for equipment at end of life.", "Needed for the Q3 programme; in the approved budget.",
                                             "Supplier price held until the end of the month.", "Capacity for the peak season.",
                                             "Renewal of an existing service."])
                                 + (f" Refused: {rnd.choice(REJECTIONS)}." if status == "rejected" else ""),
                "requester_name": rnd.choice(REQUESTERS), "cost_center_id": self.cc_ids[cc],
                "spend_category_id": self.cat_ids[code], "supplier_id": self.pick_supplier(code) if rnd.random() < 0.7 else None,
                "amount": amount, "currency": self.currency, "status": status,
                "needed_by": _iso(today + dt.timedelta(days=rnd.randint(7, 60))), "created_at": _iso(_at(created, rnd)),
                "submitted_at": _iso(_at(submitted, rnd)) if submitted else None,
                "approved_at": _iso(_at(min(today, submitted + dt.timedelta(days=rnd.randint(0, 2))), rnd)) if decided else None,
                "approver_name": approvers[cc] if decided else None, "purchase_order_id": None,
            })

        # Two requests that look like one split to stay under the first approval limit (PROC-11).
        if self.scale >= 0.5:
            sid = self.pick_supplier("IT-HW")
            for k, (title, amount, age) in enumerate([("Laptops for the analytics team, first batch", 4800.0, 6),
                                                      ("Laptops for the analytics team, second batch", 4650.0, 4)]):
                created = _workday(today - dt.timedelta(days=age), forward=False)
                self.add("requisition", {
                    "reference": f"PR-{104000 + len(self.t['requisition']) * 11}", "title": title,
                    "justification": "Replacement for equipment at end of life.", "requester_name": "Ben Thackeray",
                    "cost_center_id": self.cc_ids["CC-2200"], "spend_category_id": self.cat_ids["IT-HW"], "supplier_id": sid,
                    "amount": amount, "currency": self.currency, "status": "approved" if k == 0 else "submitted",
                    "needed_by": _iso(today + dt.timedelta(days=21)), "created_at": _iso(_at(created, rnd)),
                    "submitted_at": _iso(_at(created, rnd, 17, 18)),
                    "approved_at": _iso(_at(min(today, created + dt.timedelta(days=1)), rnd)) if k == 0 else None,
                    "approver_name": approvers["CC-2200"] if k == 0 else None, "purchase_order_id": None,
                })

    # -- the paying --------------------------------------------------------------------
    def run_for(self, day: dt.date) -> dt.date:
        """The payment run that pays something due on `day`: the Thursday on or before it."""
        return day - dt.timedelta(days=(day.weekday() - 3) % 7)

    def invoices(self) -> None:
        rnd, today = self.rnd, self.today
        drafts: list[dict[str, Any]] = []
        for po_id, po in enumerate(self.t["purchase_order"], start=1):
            s = self.t["supplier"][po["supplier_id"] - 1]
            received = po["received_amount"]
            if received <= 0:
                if po["status"] == "sent" and rnd.random() < 0.07:       # the invoice beat the goods
                    drafts.append(self.draft(po_id, po, s, po["amount"], _workday(dt.date.fromisoformat(po["order_date"])
                                             + dt.timedelta(days=rnd.randint(3, 12))), "no_receipt"))
                continue
            delivered = po["_delivered"]
            kind = rnd.choices(["matched", "price_variance", "quantity_variance"], weights=[88, 8, 4])[0]
            net = received
            if kind == "price_variance":
                net = self.money(received * rnd.uniform(1.035, 1.12))
            elif kind == "quantity_variance":
                net = self.money(received * rnd.uniform(1.08, 1.3))
            if po["status"] == "partially_received" and rnd.random() < 0.3:
                continue
            day = _workday(delivered + dt.timedelta(days=rnd.randint(1, 16)))
            if day > today:
                continue
            drafts.append(self.draft(po_id, po, s, net, day, kind))
            po["invoiced_amount"] = self.money(min(net, po["amount"] * 1.3))
        # Bought without an order: rent, utilities and telecoms (as agreed), and what slipped past procurement.
        span = (today - self.start).days
        for code in ("FA-RN", "FA-UT", "IT-TC"):
            for sid in self.by_cat.get(code, [])[:2]:
                s = self.t["supplier"][sid - 1]
                step = 91 if code == "FA-RN" else 30
                for k in range(span // step + 1):
                    day = _workday(self.start + dt.timedelta(days=k * step + rnd.randint(0, 5)))
                    if day > today:
                        break
                    desc, _, price, _ = rnd.choice(ITEMS[code])
                    drafts.append(self.draft(None, {"cost_center_id": self.cc_ids["CC-5000" if code != "IT-TC" else "CC-2000"],
                                                    "spend_category_id": self.cat_ids[code], "_code": code}, s,
                                             self.money(price * rnd.uniform(0.85, 1.2)), day, "no_po"))
        for _ in range(int(60 * self.scale)):
            cc = rnd.choice(list(CC_FAMILIES))
            family = rnd.choice(list(CC_FAMILIES[cc]))
            code = rnd.choice([c for c, _, _ in FAMILIES[family]])
            s_id = self.pick_supplier(code)
            day = _workday(today - dt.timedelta(days=int(span * rnd.random() ** 1.2)), forward=False)
            drafts.append(self.draft(None, {"cost_center_id": self.cc_ids[cc], "spend_category_id": self.cat_ids[code], "_code": code},
                                     self.t["supplier"][s_id - 1], self.money(min(18_000, max(90, rnd.lognormvariate(6.9, 1.0)))),
                                     day, "no_po", supplier_id=s_id))
        # Three that look like invoices already received.
        pool = [d for d in drafts if d["_kind"] == "matched" and (today - d["_date"]).days < 70]
        for original in rnd.sample(pool, k=min(3, len(pool))):
            copy = dict(original)
            number = original["supplier_invoice_number"]
            copy.update({"supplier_invoice_number": number.replace("-", "-0", 1) if rnd.random() < 0.5 else number + "A",
                         "_kind": "duplicate_suspect", "_date": min(today, original["_date"] + dt.timedelta(days=rnd.randint(4, 21)))})
            drafts.append(copy)
        drafts.sort(key=lambda d: d["_date"])
        self.settle(drafts)

    def draft(self, po_id: int | None, po: dict[str, Any], s: dict[str, Any], net: float, day: dt.date, kind: str,
              supplier_id: int | None = None) -> dict[str, Any]:
        rnd = self.rnd
        sid = supplier_id or po.get("supplier_id") or (self.t["supplier"].index(s) + 1)
        tax = self.money(net * VAT) if s["country"] == "United Kingdom" else 0.0
        prefix = "".join(w[0] for w in s["name"].split()[:2]).upper()
        return {
            "supplier_invoice_number": f"{prefix}-{rnd.randint(10000, 99999)}", "supplier_id": sid, "purchase_order_id": po_id,
            "cost_center_id": po["cost_center_id"], "spend_category_id": po["spend_category_id"], "net_amount": self.money(net),
            "tax_amount": tax, "amount": self.money(net + tax), "currency": self.currency, "payment_terms": s["payment_terms"],
            "_kind": kind, "_date": day, "_code": po.get("_code"), "_discount": s["payment_terms"].startswith("2/10"),
        }

    def settle(self, drafts: list[dict[str, Any]]) -> None:
        """Take each invoice as far through matching, approval and payment as its age allows."""
        rnd, today = self.rnd, self.today
        approvers = {self.cc_ids[c]: o for c, _, _, o in COST_CENTERS}
        runs: dict[dt.date, list[dict[str, Any]]] = {}
        kept = [0, 0, 0, 0, 0]
        for n, d in enumerate(drafts):
            day, kind = d.pop("_date"), d.pop("_kind")
            code, discount = d.pop("_code"), d.pop("_discount")
            received = min(today, _workday(day + dt.timedelta(days=rnd.randint(1, 5))))
            due = _due(day, d["payment_terms"])
            age = (today - received).days
            row = {"reference": f"INV-{day:%y%m%d}-{n % 10000:04d}", **d, "invoice_date": _iso(day),
                   "received_at": _iso(_at(received, rnd)), "due_date": _iso(due), "status": "received", "match_status": kind,
                   "exception_reason": None, "approver_name": None, "approved_at": None, "paid_at": None, "payment_id": None,
                   "discount_available": self.money(d["amount"] * 0.02) if discount else 0.0, "discount_taken": 0.0}
            exempt = kind == "no_po" and (code in EXEMPT_FROM_PO or d["amount"] <= 1000)
            is_exception = kind != "matched" and not exempt
            if is_exception:
                # The older an exception, the likelier it was sorted out; what is left is the queue,
                # with at least a couple in every ageing bucket so the ageing screen has each to show.
                late = (today - due).days
                band = 0 if late <= 0 else 1 if late <= 30 else 2 if late <= 60 else 3 if late <= 90 else 4
                resolved = age > 12 and rnd.random() < (0.45 if age <= 45 else 0.62 if age <= 75 else 0.74 if age <= 110
                                                        else 0.9 if age <= 150 else 1.0)
                if resolved and kind != "duplicate_suspect" and kept[band] < 2 and late < 200:
                    resolved = False
                if not resolved:
                    kept[band] += 1
                if not resolved:
                    row.update({"status": "exception", "exception_reason": rnd.choice(EXCEPTIONS[kind])})
                    if kind == "duplicate_suspect" or rnd.random() < 0.06:
                        row["status"] = "rejected" if age > 20 and rnd.random() < 0.5 else "exception"
                    self.t["invoice"].append(row)
                    continue
                received = received + dt.timedelta(days=rnd.randint(4, 12))
                if kind == "duplicate_suspect":
                    row.update({"status": "rejected", "exception_reason": EXCEPTIONS[kind][0]})
                    self.t["invoice"].append(row)
                    continue
            if age < 3:
                self.t["invoice"].append(row)
                continue
            row["status"] = "matched"
            slow = rnd.random() < 0.17
            approved = _workday(received + dt.timedelta(days=rnd.randint(14, 48) if slow else rnd.randint(2, 7)))
            if approved > today:
                self.t["invoice"].append(row)
                continue
            row.update({"status": "approved", "approver_name": approvers.get(d["cost_center_id"], "Rachel Whitmore"),
                        "approved_at": _iso(_at(approved, rnd))})
            early = discount and not slow and rnd.random() < 0.7
            target = day + dt.timedelta(days=9) if early else due
            run = self.run_for(max(target, approved + dt.timedelta(days=1)))
            if run <= approved:
                run += dt.timedelta(days=7)
            if early and run > day + dt.timedelta(days=10):
                early = False
            if early:
                row["discount_taken"] = row["discount_available"]
            if run > today + dt.timedelta(days=13):
                self.t["invoice"].append(row)
                continue
            row["status"] = "scheduled" if run > today - dt.timedelta(days=1) else "paid"
            row["_run"] = run
            runs.setdefault(run, []).append(row)
            self.t["invoice"].append(row)
        self.payments(runs)

    def payments(self, runs: dict[dt.date, list[dict[str, Any]]]) -> None:
        rnd, today = self.rnd, self.today
        methods = ["bacs"] * 7 + ["faster_payment"] * 2 + ["chaps"]
        for run_day in sorted(runs):
            rows = runs[run_day]
            future = run_day > today - dt.timedelta(days=1)
            if future:
                status = "approved" if run_day == min(d for d in runs if d > today - dt.timedelta(days=1)) else "proposed"
            else:
                status = "released" if (today - run_day).days < 2 else "completed"
            by_supplier: dict[int, list[dict[str, Any]]] = {}
            for r in rows:
                by_supplier.setdefault(r["supplier_id"], []).append(r)
            week = run_day.isocalendar()
            run_id = self.add("payment_run", {
                "reference": f"RUN-{week[0]}-{week[1]:02d}", "status": status, "run_date": _iso(run_day),
                "total_amount": self.money(sum(r["amount"] - r["discount_taken"] for r in rows)),
                "payment_count": len(by_supplier), "currency": self.currency, "created_by": rnd.choice(CLERKS),
                "approved_by": None if status == "proposed" else "Rachel Whitmore",
            })
            for sid, items in by_supplier.items():
                foreign = self.t["supplier"][sid - 1]["country"] != "United Kingdom"
                pay_status = {"proposed": "proposed", "approved": "approved", "released": "released", "completed": "completed"}[status]
                # A payment the bank returned is paid again in a later run: only recent ones are still failed.
                if status == "completed" and (today - run_day).days <= 35 and rnd.random() < 0.07:
                    pay_status = "failed"
                pid = self.add("payment", {
                    "reference": f"PAY-{9_800_000 + len(self.t['payment']) * 3:07d}", "supplier_id": sid, "payment_run_id": run_id,
                    "amount": self.money(sum(r["amount"] - r["discount_taken"] for r in items)), "currency": self.currency,
                    "method": "sepa" if foreign and rnd.random() < 0.7 else "wire" if foreign else rnd.choice(methods),
                    "status": pay_status, "scheduled_for": _iso(run_day),
                    "paid_at": _iso(_at(run_day, rnd, 9, 11)) if status in ("released", "completed") and pay_status != "failed" else None,
                    "discount_taken": self.money(sum(r["discount_taken"] for r in items)),
                })
                for r in items:
                    r["payment_id"] = pid
                    if status in ("released", "completed") and pay_status != "failed":
                        r["status"], r["paid_at"] = "paid", _iso(_at(run_day, rnd, 9, 11))
                    else:
                        r["status"], r["discount_taken"] = "scheduled", 0.0
        for r in self.t["invoice"]:
            r.pop("_run", None)

    # -- budgets and the rest ---------------------------------------------------------------
    def budgets(self) -> None:
        """A budget per cost centre and category family: what it is on course to spend this
        year, give or take — most a little under, a couple over."""
        rnd, today = self.rnd, self.today
        family_of = {self.cat_ids[c]: f for f, cats in FAMILIES.items() for c, _, _ in cats}
        first_cat = {f: self.cat_ids[cats[0][0]] for f, cats in FAMILIES.items()}
        code_of = {v: k for k, v in self.cc_ids.items()}
        this_year = fiscal_year(today)
        spent: dict[tuple[int, str, int], float] = {}
        for inv in self.t["invoice"]:
            if inv["status"] == "rejected":
                continue
            year = fiscal_year(dt.date.fromisoformat(inv["invoice_date"]))
            key = (inv["cost_center_id"], family_of[inv["spend_category_id"]], year)
            spent[key] = spent.get(key, 0.0) + inv["net_amount"]
        days_in_month = (_add_months(today.replace(day=1), 1) - today.replace(day=1)).days
        elapsed = {this_year: fiscal_period(today) - 1 + today.day / days_in_month}
        first_prior = dt.date(this_year - 2 if FISCAL_START_MONTH != 1 else this_year - 1, FISCAL_START_MONTH, 1)
        covered = sum(1 for p in range(12) if _add_months(first_prior, p) >= self.start)
        elapsed[this_year - 1] = float(covered)
        use = {cc: rnd.uniform(0.84, 1.01) for cc in self.cc_ids.values()}
        for code, share in OVER_BUDGET.items():
            use[self.cc_ids[code]] = 1 / share
        pairs = sorted({(cc, fam) for cc, fam, _ in spent})
        # Early in a fiscal year there is too little spend to read a rate from: use the last twelve months.
        year_ago = _add_months(today, -12)
        trailing: dict[tuple[int, str], float] = {}
        for inv in self.t["invoice"]:
            if inv["status"] != "rejected" and dt.date.fromisoformat(inv["invoice_date"]) > year_ago:
                key2 = (inv["cost_center_id"], family_of[inv["spend_category_id"]])
                trailing[key2] = trailing.get(key2, 0.0) + inv["net_amount"]
        for cc_id, family in pairs:
            for year in (this_year - 1, this_year):
                rate = trailing.get((cc_id, family), 0.0) / 12
                if elapsed[year] >= 3 and spent.get((cc_id, family, year)):
                    rate = spent[(cc_id, family, year)] / elapsed[year]
                monthly = rate / use[cc_id] * rnd.uniform(0.97, 1.03) * (0.95 if year < this_year else 1.0)
                first = dt.date(year - 1 if FISCAL_START_MONTH != 1 else year, FISCAL_START_MONTH, 1)
                for period in range(1, 13):
                    start = _add_months(first, period - 1)
                    season = 1 + 0.06 * math.sin((start.month - 1) / 12 * 2 * math.pi)
                    self.add("budget_line", {
                        "fiscal_year": year, "period": period, "period_start": _iso(start), "cost_center_id": cc_id,
                        "spend_category_id": first_cat[family], "gl_account_id": None,
                        "amount": max(100.0, round(monthly * season, -1)), "currency": self.currency,
                    })

    def extras(self) -> None:
        rnd, today = self.rnd, self.today
        names = {v: n for fam in FAMILIES.values() for c, n, _ in fam for k, v in self.cat_ids.items() if k == c}
        states = ["realised"] * 10 + ["in_progress"] * 9 + ["identified"] * 7 + ["cancelled"] * 2
        for i, status in enumerate(states):
            sid = rnd.choice(sorted(self.weight, key=lambda s: -self.weight[s])[:30])
            s = self.t["supplier"][sid - 1]
            baseline = round(self.weight[sid] * 1_000_000 / 100 * rnd.uniform(0.5, 1.1), -2)
            pct = rnd.uniform(0.03, 0.14)
            identified = round(baseline * pct, -1)
            realised = identified * {"realised": rnd.uniform(0.85, 1.05), "in_progress": rnd.uniform(0.2, 0.7)}.get(status, 0)
            self.add("savings_initiative", {
                "title": rnd.choice(SAVING_TITLES).format(c=names[s["spend_category_id"]].lower()),
                "spend_category_id": s["spend_category_id"], "supplier_id": sid, "owner_name": rnd.choice(BUYERS + ["Ingrid Solberg"]),
                "saving_type": rnd.choice(["negotiation", "negotiation", "consolidation", "demand", "specification", "process"]),
                "status": status, "baseline_amount": self.money(baseline), "negotiated_amount": self.money(baseline - identified),
                "identified_saving": self.money(identified), "realised_saving": self.money(round(realised, -1)),
                "fiscal_year": fiscal_year(today), "created_at": _iso(_at(today - dt.timedelta(days=rnd.randint(10, 300)), rnd)),
            })
        reasons = ["Peak season temporary staff", "Unplanned roof repair", "Licence true-up after the audit",
                   "Move budget from travel to training", "New site fit-out", "Supplier price increase from April",
                   "Campaign brought forward", "Hardware refresh deferred to next year"]
        for i, status in enumerate(["proposed", "proposed", "proposed", "approved", "applied", "applied", "applied", "rejected"]):
            cc = rnd.choice(list(CC_FAMILIES))
            family = rnd.choice(list(CC_FAMILIES[cc]))
            created = today - dt.timedelta(days=rnd.randint(0, 6) if status == "proposed" else rnd.randint(8, 120))
            self.add("budget_change", {
                "cost_center_id": self.cc_ids[cc], "spend_category_id": self.cat_ids[FAMILIES[family][0][0]],
                "fiscal_year": fiscal_year(today), "amount_delta": float(rnd.choice([-20000, -8000, 6000, 12000, 15000, 25000, 40000])),
                "reason": reasons[i % len(reasons)], "requested_by": next(o for c, _, _, o in COST_CENTERS if c == cc),
                "status": status, "created_at": _iso(_at(created, rnd)),
                "decided_at": None if status == "proposed" else _iso(_at(created + dt.timedelta(days=rnd.randint(1, 4)), rnd)),
            })

    def finish(self) -> None:
        """Supplier risk, from what the story made of each supplier."""
        spend: dict[int, float] = {}
        by_cat: dict[int, float] = {}
        for inv in self.t["invoice"]:
            if inv["status"] != "rejected":
                spend[inv["supplier_id"]] = spend.get(inv["supplier_id"], 0) + inv["net_amount"]
                by_cat[inv["spend_category_id"]] = by_cat.get(inv["spend_category_id"], 0) + inv["net_amount"]
        for sid, s in enumerate(self.t["supplier"], start=1):
            whole = by_cat.get(s["spend_category_id"], 0)
            share = 100 * spend.get(sid, 0) / whole if whole else 0
            s["risk_score"], s["risk_rating"] = risk(s["otif_pct"], s["quality_pct"], s.pop("_financial"), s.pop("_compliance"), share)
            if s["status"] == "suspended":
                s["risk_rating"] = "high"
                s["risk_score"] = max(s["risk_score"], 71.0)
        for table in self.t.values():
            for row in table:
                for key in [k for k in row if k.startswith("_")]:
                    del row[key]

    def tell(self) -> dict[str, list[dict[str, Any]]]:
        self.reference()
        self.suppliers()
        self.contracts()
        self.orders()
        self.requisitions()
        self.invoices()
        self.budgets()
        self.extras()
        self.finish()
        return self.t


def rows(tables: dict[str, Any] | None = None, *, today: dt.date | str | None = None, seed: int = 20260401,
         scale: float = 1.0, currency: str = "GBP") -> dict[str, list[dict[str, Any]]]:
    """Rows for the standard tables among `tables` (all of them when None), in an order
    every reference resolves in, each row holding only the columns its table has."""
    if isinstance(today, str):
        today = dt.date.fromisoformat(today[:10])
    story = _Story(today or dt.date.today(), seed, scale, currency).tell()
    if tables is None:
        return {name: story[name] for name in standard.ORDER}
    have = {str(name).lower(): {str(c).lower() for c in cols} for name, cols in tables.items()}
    out: dict[str, list[dict[str, Any]]] = {}
    for name in standard.ORDER:
        if name not in have:
            continue
        keep = have[name]
        refs = {c[0]: c[1][4:] for c in standard.ENTITIES[name]["columns"] if c[1].startswith("ref:")}
        table = []
        for row in story[name]:
            kept = {k: v for k, v in row.items() if k in keep}
            for column, target in refs.items():
                if column in kept and target not in have:
                    kept[column] = None          # the table it points at is not in this application
            table.append(kept)
        out[name] = table
    return out


def main() -> None:
    request = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    result = rows(request.get("tables"), today=request.get("today"), seed=int(request.get("seed") or 20260401),
                  scale=float(request.get("scale") or 1.0), currency=request.get("currency") or "GBP")
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
