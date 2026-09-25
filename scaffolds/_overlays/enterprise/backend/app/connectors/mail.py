"""E-mail over SMTP. Written by Poiesis, and read-only.

    from ..connectors import email
    email().send(["lead@example.com"], "3 duplicates closed automatically",
                 "Tickets 812, 815 and 820 were closed as duplicates of 790.", html="<p>…</p>")

Live when SMTP_HOST and SMTP_FROM are set (SMTP_USERNAME and SMTP_PASSWORD when the
server wants a login; SMTP_SECURITY is starttls, ssl or none). EMAIL_REDIRECT_TO sends
every message to one address instead, for a test environment with real people in its
data. In the sandbox the message is built exactly as it would be sent and kept in the
outbox; EMAIL_SANDBOX_RELAY=host:port also hands it to a local mail catcher such as
Mailpit, where it can be opened as a real e-mail.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Iterable

from .base import Connector, ConnectorError, Result, Setting


def _list(value: str | Iterable[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [v.strip() for v in value if v and v.strip()]


class Email(Connector):
    name = "email"
    title = "E-mail"
    category = "Messaging"
    description = "Send plain-text and HTML e-mail through any SMTP server (Microsoft 365, Gmail, SES, Postfix)."
    vendor_url = "https://docs.python.org/3/library/smtplib.html"
    settings = (
        Setting("SMTP_HOST", "SMTP server", required=True, help="smtp.office365.com"),
        Setting("SMTP_PORT", "Port", default="587"),
        Setting("SMTP_SECURITY", "Security", default="starttls", help="starttls, ssl or none"),
        Setting("SMTP_USERNAME", "Username"),
        Setting("SMTP_PASSWORD", "Password", secret=True),
        Setting("SMTP_FROM", "From address", required=True, help="DupeGuard <no-reply@example.com>"),
        Setting("EMAIL_REDIRECT_TO", "Redirect all mail to", help="Test environments: one inbox gets everything"),
        Setting("EMAIL_SANDBOX_RELAY", "Sandbox relay", help="host:port of a local mail catcher (Mailpit)"),
    )
    operations = {"send": "Send an e-mail to one or more people"}

    def _message(self, to: list[str], subject: str, text: str, html: str | None, cc: list[str],
                 reply_to: str | None, headers: dict[str, str] | None) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.setting("SMTP_FROM") or "no-reply@sandbox.local"
        redirect = self.setting("EMAIL_REDIRECT_TO")
        msg["To"] = redirect or ", ".join(to)
        if cc and not redirect:
            msg["Cc"] = ", ".join(cc)
        if redirect:
            msg["X-Original-To"] = ", ".join(to + cc)
        if reply_to:
            msg["Reply-To"] = reply_to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain="poiesis.local")
        for k, v in (headers or {}).items():
            msg[k] = v
        msg.set_content(text or "")
        if html:
            msg.add_alternative(html, subtype="html")
        return msg

    def _deliver(self, msg: EmailMessage, host: str, port: int, security: str, user: str, password: str) -> None:
        try:
            if security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(host, port, timeout=20)
            with server:
                if security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if user:
                    server.login(user, password)
                refused = server.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise ConnectorError(f"SMTP login refused: {exc.smtp_code} {exc.smtp_error!r}") from None
        except smtplib.SMTPRecipientsRefused as exc:
            raise ConnectorError(f"every recipient was refused: {', '.join(exc.recipients)}") from None
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as exc:
            raise ConnectorError(f"SMTP {host}:{port} unreachable: {exc}", retryable=True) from None
        except smtplib.SMTPResponseException as exc:
            raise ConnectorError(f"SMTP said {exc.smtp_code}: {exc.smtp_error!r}", retryable=exc.smtp_code >= 400 and exc.smtp_code < 500) from None
        if refused:
            raise ConnectorError(f"refused recipients: {', '.join(refused)}")

    def send(self, to: str | Iterable[str], subject: str, text: str, *, html: str | None = None,
             cc: str | Iterable[str] | None = None, reply_to: str | None = None,
             headers: dict[str, str] | None = None, idempotency_key: str | None = None,
             ref: str | None = None) -> Result:
        to_list, cc_list = _list(to), _list(cc)
        if not to_list:
            return Result(False, self.name, "send", self.mode, error="no recipient")
        msg = self._message(to_list, subject, text, html, cc_list, reply_to, headers)
        preview = {"from": msg["From"], "to": msg["To"], "cc": msg.get("Cc"), "subject": subject,
                   "text": text[:4000], "html": (html or "")[:12000], "message_id": msg["Message-ID"]}

        def live() -> Result:
            security = (self.setting("SMTP_SECURITY") or "starttls").lower()
            port = int(self.setting("SMTP_PORT") or (465 if security == "ssl" else 587))
            self._deliver(msg, self.setting("SMTP_HOST"), port, security,
                          self.setting("SMTP_USERNAME"), self.setting("SMTP_PASSWORD"))
            return Result(True, self.name, "send", "live", key=msg["Message-ID"], data=preview)

        def sandbox() -> Result:
            relay = self.setting("EMAIL_SANDBOX_RELAY")
            relayed = False
            if relay:
                host, _, port = relay.partition(":")
                try:
                    self._deliver(msg, host, int(port or 1025), "none", "", "")
                    relayed = True
                except ConnectorError:
                    relayed = False  # the catcher is optional; the outbox still has the message
            key = f"mail-{self.store.next_number(self.name, 'mail', 1)}"
            self._remember(key, "mail", {**preview, "key": key, "relayed": relayed})
            return Result(True, self.name, "send", "sandbox", key=key, url=self._sandbox_url(key),
                          data={**preview, "relayed": relayed})

        return self._call("send", {"to": to_list, "cc": cc_list, "subject": subject, "text": text, "html": html,
                                   "reply_to": reply_to},
                          live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)
