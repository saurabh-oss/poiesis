"""Money that adds up. Written by Poiesis, and read-only.

Amounts are stored as plain numbers and travel as JSON numbers, but they are never
computed as binary floats: 0.1 + 0.2 is not 0.3 there, and an invoice that is a penny
out fails its match. Every calculation in the library goes through `D()` and Decimal,
and is rounded once, at the end, to the currency's minor unit.

    from ..finance import money
    total = money.total(line.amount for line in lines)                  # Decimal, exact
    net, tax, gross = money.add_tax(1250, rate=20)                      # 1250.00, 250.00, 1500.00
    shares = money.allocate(1000, [1, 1, 1])                            # 333.34, 333.33, 333.33 — sums to 1000
    money.fmt(1234567.5, "GBP")            -> "£1,234,567.50"
    money.fmt(1234567.5, "GBP", compact=True) -> "£1.23M"
    money.fmt(-420, "EUR", accounting=True)   -> "(€420.00)"
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

ZERO = Decimal("0")
# ISO 4217 minor units, where they are not 2.
MINOR_UNITS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "HUF": 2, "BHD": 3, "KWD": 3, "OMR": 3,
               "JOD": 3, "TND": 3}
SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$", "INR": "₹", "JPY": "¥", "CNY": "¥", "CHF": "CHF ", "AUD": "A$",
           "CAD": "C$", "SGD": "S$", "AED": "AED ", "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "PLN": "zł ",
           "ZAR": "R ", "BRL": "R$", "MXN": "MX$", "HKD": "HK$", "NZD": "NZ$"}
ROUNDINGS = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN}


def D(value: Any) -> Decimal:
    """Any stored or received amount as a Decimal. None and "" are zero; a float goes
    through its shortest text form, so 0.1 is 0.1 and not 0.1000000000000000055…"""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Money):
        return value.amount
    try:
        if isinstance(value, float):
            return Decimal(repr(value))
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{value!r} is not an amount") from None


def minor_units(currency: str = "GBP") -> int:
    return MINOR_UNITS.get((currency or "GBP").upper(), 2)


def quantize(value: Any, currency: str = "GBP", rounding: str = "half_up") -> Decimal:
    """Rounded to the currency's minor unit: pennies for GBP, whole yen for JPY."""
    return D(value).quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUNDINGS.get(rounding, ROUND_HALF_UP))


def number(value: Any, currency: str = "GBP") -> float:
    """A rounded amount as the plain number a column or a JSON response holds."""
    return float(quantize(value, currency))


def total(values: Iterable[Any], currency: str = "GBP") -> Decimal:
    """An exact sum, rounded once at the end."""
    acc = ZERO
    for v in values:
        acc += D(v)
    return quantize(acc, currency)


def allocate(amount: Any, weights: Iterable[Any], currency: str = "GBP") -> list[Decimal]:
    """Split an amount in proportion to `weights` so the parts sum to it exactly.

    The pennies left over after rounding down go to the largest remainders, so a
    1,000.00 invoice split three ways is 333.34 + 333.33 + 333.33, never 999.99."""
    ws = [D(w) for w in weights]
    if not ws:
        return []
    whole = quantize(amount, currency)
    sign = -1 if whole < 0 else 1
    whole = abs(whole)
    unit = Decimal(1).scaleb(-minor_units(currency))
    weight_sum = sum(ws, ZERO)
    if weight_sum <= 0:
        ws = [Decimal(1)] * len(ws)
        weight_sum = Decimal(len(ws))
    exact = [whole * w / weight_sum for w in ws]
    floors = [(e / unit).to_integral_value(rounding="ROUND_FLOOR") * unit for e in exact]
    left = int(((whole - sum(floors, ZERO)) / unit).to_integral_value())
    order = sorted(range(len(ws)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += unit
    return [sign * f for f in floors]


def convert(amount: Any, rate: Any, to_currency: str = "GBP") -> Decimal:
    """`amount` × `rate`, in the target currency's minor units. `rate` is how many units
    of the target currency one unit of the amount's currency buys."""
    r = D(rate)
    if r <= 0:
        raise ValueError("an exchange rate must be greater than zero")
    return quantize(D(amount) * r, to_currency)


def add_tax(net: Any, rate: Any, currency: str = "GBP") -> tuple[Decimal, Decimal, Decimal]:
    """(net, tax, gross) from a net amount and a rate in percent."""
    n = quantize(net, currency)
    tax = quantize(n * D(rate) / 100, currency)
    return n, tax, n + tax


def remove_tax(gross: Any, rate: Any, currency: str = "GBP") -> tuple[Decimal, Decimal, Decimal]:
    """(net, tax, gross) from a gross amount and a rate in percent."""
    g = quantize(gross, currency)
    net = quantize(g / (1 + D(rate) / 100), currency)
    return net, g - net, g


def pct(part: Any, whole: Any, places: int = 1) -> float | None:
    """`part` as a percentage of `whole`; None when there is no whole to be a part of."""
    w = D(whole)
    if w == 0:
        return None
    return float((D(part) / w * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def symbol(currency: str = "GBP") -> str:
    return SYMBOLS.get((currency or "GBP").upper(), f"{(currency or '').upper()} ")


def fmt(value: Any, currency: str = "GBP", *, compact: bool = False, accounting: bool = False,
        signed: bool = False) -> str:
    """An amount as people read it. `compact` for headline tiles (£1.23M), `accounting`
    for statements (negatives in brackets), `signed` for variances (+£120.00)."""
    if value is None or value == "":
        return "—"
    amount = D(value)
    negative = amount < 0
    magnitude = abs(amount)
    if compact and magnitude >= 1000:
        for limit, suffix in ((Decimal("1e12"), "T"), (Decimal("1e9"), "B"), (Decimal("1e6"), "M"), (Decimal("1e3"), "k")):
            if magnitude >= limit:
                scaled = magnitude / limit
                places = 2 if scaled < 10 else 1 if scaled < 100 else 0
                text = f"{scaled.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):f}{suffix}"
                break
    else:
        places = minor_units(currency)
        text = f"{magnitude.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,.{places}f}"
    body = f"{symbol(currency)}{text}"
    if negative:
        return f"({body})" if accounting else f"-{body}"
    return f"+{body}" if signed and amount > 0 else body


@dataclass(frozen=True)
class Money:
    """An amount with its currency, for code that must not add pounds to euros."""
    amount: Decimal
    currency: str = "GBP"

    @classmethod
    def of(cls, value: Any, currency: str = "GBP") -> "Money":
        return cls(quantize(value, currency), (currency or "GBP").upper())

    def _same(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError("Money adds to Money; use Money.of(value, currency)")
        if other.currency != self.currency:
            raise ValueError(f"cannot combine {self.currency} with {other.currency}: convert one first")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Any) -> "Money":
        return Money.of(self.amount * D(factor), self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount <= other.amount

    def allocate(self, weights: Iterable[Any]) -> list["Money"]:
        return [Money(a, self.currency) for a in allocate(self.amount, weights, self.currency)]

    def convert(self, rate: Any, to_currency: str) -> "Money":
        return Money(convert(self.amount, rate, to_currency), to_currency.upper())

    def __float__(self) -> float:
        return float(self.amount)

    def __str__(self) -> str:
        return fmt(self.amount, self.currency)
