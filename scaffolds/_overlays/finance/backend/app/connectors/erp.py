"""The ERP: suppliers, purchase orders, invoices, payments and the ledger. Written by Poiesis, and read-only.

    from ..connectors import erp
    r = erp().create_purchase_order(po.reference, supplier.code, po.amount, lines=lines,
                                    cost_center=cc.code, idempotency_key=f"po-{po.id}")
    if r.ok: po.erp_number = r.key                     # 4500012345

    erp().post_invoice(inv.reference, supplier.code, inv.amount, net=inv.net_amount, tax=inv.tax_amount,
                       invoice_date=inv.invoice_date, due_date=inv.due_date, po_number=po.erp_number,
                       idempotency_key=f"invoice-{inv.id}")
    erp().release_payments(run.reference, payments, idempotency_key=f"run-{run.id}")

With no settings it runs in its sandbox: nothing leaves the application, every call is in
the outbox, and the stand-in keeps the ledger it was given, so an invoice posted can be
read back, a payment batch released and its status followed, and balances asked for.

Live, it speaks one small JSON contract over HTTPS (ERP_BASE_URL, ERP_TOKEN), the one an
integration layer in front of SAP S/4HANA, Oracle Fusion, NetSuite, Dynamics 365 or
Workday exposes; ERP_SYSTEM names which, for the Integrations screen. The paths are
settings, so the contract bends to the gateway rather than the other way round:

    POST {base}/suppliers            PUT {base}/suppliers/{code}
    POST {base}/purchase-orders      GET {base}/purchase-orders/{number}
    POST {base}/invoices             GET {base}/invoices/{document}
    POST {base}/payment-batches      GET {base}/payment-batches/{batch}
    GET  {base}/gl/balances?period=  GET {base}/exchange-rates?date=&base=

Each POST answers {"id": "<the ERP's number>", "url": "<optional link>", …}.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Any, Iterable

from .base import Connector, ConnectorError, Result, Setting, http_json

PO_START = 4500012001
DOCUMENT_START = 5100040001
BATCH_START = 1
SANDBOX_RATES = {"EUR": 1.17, "USD": 1.27, "INR": 106.0, "PLN": 5.05, "CHF": 1.12, "JPY": 190.0, "GBP": 1.0}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value


def _num(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


class Erp(Connector):
    name = "erp"
    title = "ERP"
    category = "Finance"
    description = "Post purchase orders, invoices and payment batches to the ERP; read suppliers, balances and rates."
    vendor_url = ""
    settings = (
        Setting("ERP_BASE_URL", "Integration endpoint", required=True, help="https://integration.your-company.com/erp/v1"),
        Setting("ERP_TOKEN", "Access token", required=True, secret=True, help="A bearer token for the integration endpoint"),
        Setting("ERP_SYSTEM", "ERP system", default="ERP", help="SAP S/4HANA, Oracle Fusion, NetSuite, Dynamics 365, Workday…"),
        Setting("ERP_COMPANY", "Company code", default="1000", help="The legal entity documents are posted to"),
        Setting("ERP_BASE_CURRENCY", "Base currency", default="GBP"),
    )
    operations = {
        "sync_supplier": "Create or update a supplier in the vendor master",
        "create_purchase_order": "Post a purchase order and get its ERP number",
        "get_purchase_order": "Read a purchase order's status, received and invoiced value",
        "post_invoice": "Post a supplier invoice to accounts payable",
        "invoice_status": "Whether an invoice is posted, blocked, scheduled or paid",
        "release_payments": "Send a payment run to the bank interface",
        "payment_status": "Whether a payment batch was accepted, paid or rejected",
        "gl_balances": "Actuals by GL account and cost centre for a period",
        "exchange_rates": "The day's rates against the base currency",
    }

    # -- plumbing -----------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return self.setting("ERP_BASE_URL").rstrip("/") + path

    def _api(self, method: str, path: str, body: Any = None) -> Any:
        return http_json(method, self._url(path), headers={"Authorization": f"Bearer {self.setting('ERP_TOKEN')}"},
                         body=body)[1]

    def _made(self, operation: str, made: Any, what: str) -> Result:
        made = made if isinstance(made, dict) else {}
        key = made.get("id") or made.get("number") or made.get("document")
        if not key:
            raise ConnectorError(f"{self.title} created no {what}: {made}")
        return Result(True, self.name, operation, "live", key=str(key), url=made.get("url"), data=made)

    def _company(self) -> str:
        return self.setting("ERP_COMPANY") or "1000"

    def _base_currency(self) -> str:
        return (self.setting("ERP_BASE_CURRENCY") or "GBP").upper()

    # -- suppliers ---------------------------------------------------------------------------
    def sync_supplier(self, code: str, name: str, *, country: str = "", currency: str = "", payment_terms: str = "",
                      tax_id: str = "", email: str = "", blocked: bool = False, idempotency_key: str | None = None,
                      ref: str | None = None) -> Result:
        body = {"code": code, "name": name, "country": country, "currency": currency or self._base_currency(),
                "payment_terms": payment_terms, "tax_id": tax_id, "email": email, "blocked": bool(blocked),
                "company": self._company()}

        def live() -> Result:
            return self._made("sync_supplier", self._api("PUT", f"/suppliers/{urllib.parse.quote(code)}", body) or
                              {"id": code}, "supplier")

        def sandbox() -> Result:
            known = self.store.get_object(self.name, f"supplier:{code}")
            self._remember(f"supplier:{code}", "supplier", {**(known or {}), **body, "key": code})
            return Result(True, self.name, "sync_supplier", "sandbox", key=code, url=self._sandbox_url(f"supplier:{code}"),
                          data={"code": code, "created": known is None})

        return self._call("sync_supplier", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    # -- purchase orders ---------------------------------------------------------------------
    def create_purchase_order(self, reference: str, supplier_code: str, amount: Any, *, currency: str = "",
                              lines: Iterable[dict[str, Any]] = (), cost_center: str = "", order_date: Any = None,
                              delivery_date: Any = None, idempotency_key: str | None = None,
                              ref: str | None = None) -> Result:
        body = {"reference": reference, "supplier": supplier_code, "amount": _num(amount),
                "currency": (currency or self._base_currency()).upper(), "cost_center": cost_center,
                "order_date": _iso(order_date), "delivery_date": _iso(delivery_date), "company": self._company(),
                "lines": [{"line": i, "description": str(l.get("description", ""))[:200], "quantity": _num(l.get("quantity")),
                           "unit_price": _num(l.get("unit_price")), "amount": _num(l.get("amount")),
                           "gl_account": l.get("gl_account", ""), "cost_center": l.get("cost_center", cost_center)}
                          for i, l in enumerate(lines or [], start=1)]}

        def live() -> Result:
            return self._made("create_purchase_order", self._api("POST", "/purchase-orders", body), "purchase order")

        def sandbox() -> Result:
            number = str(self.store.next_number(self.name, "purchase_order", PO_START))
            self._remember(f"po:{number}", "purchase_order", {**body, "key": number, "number": number, "status": "released",
                                                              "received": 0.0, "invoiced": 0.0})
            return Result(True, self.name, "create_purchase_order", "sandbox", key=number,
                          url=self._sandbox_url(f"po:{number}"), data={"number": number, "status": "released"})

        return self._call("create_purchase_order", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def get_purchase_order(self, number: str) -> Result:
        def live() -> Result:
            data = self._api("GET", f"/purchase-orders/{urllib.parse.quote(str(number))}") or {}
            return Result(True, self.name, "get_purchase_order", "live", key=str(number), data=data)

        def sandbox() -> Result:
            data = self._recall(f"po:{number}")
            return Result(True, self.name, "get_purchase_order", "sandbox", key=str(number),
                          url=self._sandbox_url(f"po:{number}"), data=data)

        return self._call("get_purchase_order", {"number": str(number)}, live=live, sandbox=sandbox)

    # -- invoices ----------------------------------------------------------------------------
    def post_invoice(self, reference: str, supplier_code: str, amount: Any, *, net: Any = None, tax: Any = 0,
                     currency: str = "", invoice_date: Any = None, due_date: Any = None, po_number: str = "",
                     supplier_invoice_number: str = "", lines: Iterable[dict[str, Any]] = (),
                     idempotency_key: str | None = None, ref: str | None = None) -> Result:
        gross = _num(amount)
        body = {"reference": reference, "supplier": supplier_code, "supplier_invoice_number": supplier_invoice_number,
                "amount": gross, "net": _num(net if net is not None else gross - _num(tax)), "tax": _num(tax),
                "currency": (currency or self._base_currency()).upper(), "invoice_date": _iso(invoice_date),
                "due_date": _iso(due_date), "purchase_order": str(po_number or ""), "company": self._company(),
                "lines": [{"gl_account": l.get("gl_account", ""), "cost_center": l.get("cost_center", ""),
                           "amount": _num(l.get("amount")), "description": str(l.get("description", ""))[:200]}
                          for l in lines or []]}

        def live() -> Result:
            return self._made("post_invoice", self._api("POST", "/invoices", body), "document")

        def sandbox() -> Result:
            if body["lines"] and abs(sum(l["amount"] for l in body["lines"]) - body["net"]) > 0.01:
                raise ConnectorError(f"the lines add up to {sum(l['amount'] for l in body['lines']):.2f}, not the net "
                                     f"amount {body['net']:.2f}: the ERP would reject the document")
            document = str(self.store.next_number(self.name, "document", DOCUMENT_START))
            self._remember(f"invoice:{document}", "invoice", {**body, "key": document, "document": document,
                                                              "status": "posted", "payment_batch": None})
            if po_number and self.store.get_object(self.name, f"po:{po_number}"):
                po = self._recall(f"po:{po_number}")
                po["invoiced"] = round(float(po.get("invoiced", 0)) + body["net"], 2)
                self._remember(f"po:{po_number}", "purchase_order", po)
            return Result(True, self.name, "post_invoice", "sandbox", key=document,
                          url=self._sandbox_url(f"invoice:{document}"), data={"document": document, "status": "posted"})

        return self._call("post_invoice", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def invoice_status(self, document: str) -> Result:
        def live() -> Result:
            data = self._api("GET", f"/invoices/{urllib.parse.quote(str(document))}") or {}
            return Result(True, self.name, "invoice_status", "live", key=str(document), data=data)

        def sandbox() -> Result:
            data = self._recall(f"invoice:{document}")
            return Result(True, self.name, "invoice_status", "sandbox", key=str(document),
                          url=self._sandbox_url(f"invoice:{document}"),
                          data={"document": str(document), "status": data["status"], "payment_batch": data.get("payment_batch")})

        return self._call("invoice_status", {"document": str(document)}, live=live, sandbox=sandbox)

    # -- payments ----------------------------------------------------------------------------
    def release_payments(self, run_reference: str, payments: Iterable[dict[str, Any]], *, value_date: Any = None,
                         idempotency_key: str | None = None, ref: str | None = None) -> Result:
        """`payments`: [{"reference", "supplier", "amount", "currency", "method", "documents": [ERP invoice numbers]}]."""
        items = [{"reference": p.get("reference", ""), "supplier": p.get("supplier", ""), "amount": _num(p.get("amount")),
                  "currency": (p.get("currency") or self._base_currency()).upper(), "method": p.get("method", "bacs"),
                  "documents": [str(d) for d in p.get("documents") or []]} for p in payments or []]
        body = {"run": run_reference, "value_date": _iso(value_date), "company": self._company(), "payments": items,
                "total": round(sum(p["amount"] for p in items), 2), "count": len(items)}

        def live() -> Result:
            return self._made("release_payments", self._api("POST", "/payment-batches", body), "payment batch")

        def sandbox() -> Result:
            if not items:
                raise ConnectorError("a payment batch needs at least one payment")
            year = (value_date.year if isinstance(value_date, (dt.date, dt.datetime)) else dt.date.today().year)
            batch = f"PB-{year}-{self.store.next_number(self.name, 'batch', BATCH_START):04d}"
            self._remember(f"batch:{batch}", "payment_batch", {**body, "key": batch, "batch": batch, "status": "accepted"})
            for p in items:
                for document in p["documents"]:
                    if self.store.get_object(self.name, f"invoice:{document}"):
                        inv = self._recall(f"invoice:{document}")
                        inv.update({"status": "paid", "payment_batch": batch})
                        self._remember(f"invoice:{document}", "invoice", inv)
            return Result(True, self.name, "release_payments", "sandbox", key=batch, url=self._sandbox_url(f"batch:{batch}"),
                          data={"batch": batch, "status": "accepted", "count": len(items), "total": body["total"]})

        return self._call("release_payments", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def payment_status(self, batch: str) -> Result:
        def live() -> Result:
            data = self._api("GET", f"/payment-batches/{urllib.parse.quote(str(batch))}") or {}
            return Result(True, self.name, "payment_status", "live", key=str(batch), data=data)

        def sandbox() -> Result:
            data = self._recall(f"batch:{batch}")
            return Result(True, self.name, "payment_status", "sandbox", key=str(batch), url=self._sandbox_url(f"batch:{batch}"),
                          data={"batch": str(batch), "status": data["status"], "count": data["count"], "total": data["total"]})

        return self._call("payment_status", {"batch": str(batch)}, live=live, sandbox=sandbox)

    # -- the ledger ----------------------------------------------------------------------------
    def gl_balances(self, period: str, *, cost_center: str = "") -> Result:
        """Actuals for a period ("2026-09"), by GL account and cost centre."""
        def live() -> Result:
            query = urllib.parse.urlencode({"period": period, **({"cost_center": cost_center} if cost_center else {})})
            data = self._api("GET", f"/gl/balances?{query}") or {}
            rows = data.get("balances", data) if isinstance(data, dict) else data
            return Result(True, self.name, "gl_balances", "live", key=period, data={"period": period, "balances": rows})

        def sandbox() -> Result:
            sums: dict[tuple[str, str], float] = {}
            for inv in self.store.objects(self.name, "invoice"):
                if not str(inv.get("invoice_date") or "").startswith(period):
                    continue
                for line in inv.get("lines") or [{"gl_account": "", "cost_center": "", "amount": inv.get("net", 0)}]:
                    if cost_center and line.get("cost_center") != cost_center:
                        continue
                    key = (str(line.get("gl_account", "")), str(line.get("cost_center", "")))
                    sums[key] = round(sums.get(key, 0.0) + float(line.get("amount") or 0), 2)
            rows = [{"gl_account": a, "cost_center": c, "amount": v, "currency": self._base_currency()}
                    for (a, c), v in sorted(sums.items())]
            return Result(True, self.name, "gl_balances", "sandbox", key=period, data={"period": period, "balances": rows})

        return self._call("gl_balances", {"period": period, "cost_center": cost_center}, live=live, sandbox=sandbox)

    def test(self, actor_name: str = "", app_name: str = "") -> Result:
        """What the Integrations screen's Test does: a call that reads and changes nothing."""
        return self.exchange_rates()

    def exchange_rates(self, date: Any = None, *, base: str = "") -> Result:
        """Units of each currency per one unit of the base currency, on a date."""
        base = (base or self._base_currency()).upper()
        day = _iso(date) or dt.date.today().isoformat()

        def live() -> Result:
            query = urllib.parse.urlencode({"date": day, "base": base})
            data = self._api("GET", f"/exchange-rates?{query}") or {}
            rates = data.get("rates", data) if isinstance(data, dict) else {}
            return Result(True, self.name, "exchange_rates", "live", key=day, data={"base": base, "date": day, "rates": rates})

        def sandbox() -> Result:
            anchor = SANDBOX_RATES.get(base, 1.0)
            rates = {c: round(r / anchor, 4) for c, r in SANDBOX_RATES.items() if c != base}
            return Result(True, self.name, "exchange_rates", "sandbox", key=day, data={"base": base, "date": day, "rates": rates})

        return self._call("exchange_rates", {"date": day, "base": base}, live=live, sandbox=sandbox)

    # -- replay ----------------------------------------------------------------------------------
    def replay(self, operation: str, request: dict[str, Any], *, idempotency_key: str | None = None,
               ref: str | None = None) -> Result:
        """Run a failed call again from what the outbox recorded of it."""
        r = dict(request or {})
        if operation == "sync_supplier":
            return self.sync_supplier(r.get("code", ""), r.get("name", ""), country=r.get("country", ""),
                                      currency=r.get("currency", ""), payment_terms=r.get("payment_terms", ""),
                                      tax_id=r.get("tax_id", ""), email=r.get("email", ""), blocked=bool(r.get("blocked")),
                                      idempotency_key=idempotency_key, ref=ref)
        if operation == "create_purchase_order":
            return self.create_purchase_order(r.get("reference", ""), r.get("supplier", ""), r.get("amount"),
                                              currency=r.get("currency", ""), lines=r.get("lines") or (),
                                              cost_center=r.get("cost_center", ""), order_date=r.get("order_date"),
                                              delivery_date=r.get("delivery_date"), idempotency_key=idempotency_key, ref=ref)
        if operation == "post_invoice":
            return self.post_invoice(r.get("reference", ""), r.get("supplier", ""), r.get("amount"), net=r.get("net"),
                                     tax=r.get("tax", 0), currency=r.get("currency", ""), invoice_date=r.get("invoice_date"),
                                     due_date=r.get("due_date"), po_number=r.get("purchase_order", ""),
                                     supplier_invoice_number=r.get("supplier_invoice_number", ""), lines=r.get("lines") or (),
                                     idempotency_key=idempotency_key, ref=ref)
        if operation == "release_payments":
            return self.release_payments(r.get("run", ""), r.get("payments") or (), value_date=r.get("value_date"),
                                         idempotency_key=idempotency_key, ref=ref)
        return Result(False, self.name, operation, self.mode, error=f"{operation} cannot be replayed")


def erp() -> Erp:
    return Erp()
