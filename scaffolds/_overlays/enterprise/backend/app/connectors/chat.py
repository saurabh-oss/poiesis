"""Slack and Microsoft Teams. Written by Poiesis, and read-only.

Both take the same message — a title, a line of text, a few facts, a link — and render
it the way each product shows it best: Block Kit for Slack, an Adaptive Card for Teams.

    from ..connectors import slack, teams
    card = dict(title="Auto-close paused", text="Precision fell to 91% this week",
                facts={"Threshold": "85", "Undone closures": "6"}, link=("Open DupeGuard", url))
    slack().post(**card)
    teams().post(**card)

Slack is live with SLACK_WEBHOOK_URL (an incoming webhook, one channel) or with
SLACK_BOT_TOKEN and SLACK_CHANNEL (chat.postMessage, any channel the bot is in, and
threaded replies). Teams is live with TEAMS_WEBHOOK_URL: a Workflows "post to a channel
when a webhook request is received" URL, or a classic incoming webhook.
"""
from __future__ import annotations

from typing import Any

from .base import Connector, ConnectorError, Result, Setting, http_json

Facts = dict[str, Any] | list[tuple[str, Any]] | None


def _facts(facts: Facts) -> list[tuple[str, str]]:
    if not facts:
        return []
    items = facts.items() if isinstance(facts, dict) else facts
    return [(str(k), str(v)) for k, v in items][:10]


class Slack(Connector):
    name = "slack"
    title = "Slack"
    category = "Messaging"
    description = "Post formatted messages to a Slack channel, and reply in threads."
    vendor_url = "https://api.slack.com/messaging/webhooks"
    settings = (
        Setting("SLACK_WEBHOOK_URL", "Incoming webhook URL", secret=True, help="https://hooks.slack.com/services/…"),
        Setting("SLACK_BOT_TOKEN", "Bot token", secret=True, help="xoxb-… with chat:write, instead of a webhook"),
        Setting("SLACK_CHANNEL", "Channel", help="#support-leads (with a bot token)"),
    )
    live_when_any = (("SLACK_WEBHOOK_URL",), ("SLACK_BOT_TOKEN", "SLACK_CHANNEL"))
    operations = {"post": "Post a message (title, text, facts, a link) to a channel"}

    @staticmethod
    def blocks(title: str, text: str, facts: Facts, link: tuple[str, str] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"type": "header", "text": {"type": "plain_text", "text": title[:150]}}]
        if text:
            out.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}})
        pairs = _facts(facts)
        if pairs:
            out.append({"type": "section", "fields": [{"type": "mrkdwn", "text": f"*{k}*\n{v}"} for k, v in pairs]})
        if link and link[1].startswith("http"):
            out.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": link[0][:75]},
                                                         "url": link[1]}]})
        return out

    def post(self, title: str, text: str = "", *, facts: Facts = None, link: tuple[str, str] | None = None,
             channel: str | None = None, thread: str | None = None, idempotency_key: str | None = None,
             ref: str | None = None) -> Result:
        fallback = f"{title}: {text}" if text else title
        body: dict[str, Any] = {"text": fallback[:3000], "blocks": self.blocks(title, text, facts, link)}

        def live() -> Result:
            if self.setting("SLACK_BOT_TOKEN") and (channel or self.setting("SLACK_CHANNEL")):
                payload = {**body, "channel": channel or self.setting("SLACK_CHANNEL"), **({"thread_ts": thread} if thread else {})}
                _, data = http_json("POST", "https://slack.com/api/chat.postMessage", body=payload,
                                    headers={"Authorization": f"Bearer {self.setting('SLACK_BOT_TOKEN')}",
                                             "Content-Type": "application/json; charset=utf-8"})
                if not isinstance(data, dict) or not data.get("ok"):
                    error = (data or {}).get("error") if isinstance(data, dict) else data
                    raise ConnectorError(f"Slack refused the message: {error}", retryable=error == "ratelimited")
                return Result(True, self.name, "post", "live", key=data.get("ts"),
                              data={"channel": data.get("channel"), "ts": data.get("ts")})
            _, data = http_json("POST", self.setting("SLACK_WEBHOOK_URL"), body=body)
            if data not in (None, "ok"):
                raise ConnectorError(f"Slack refused the message: {data}")
            return Result(True, self.name, "post", "live", data={"channel": "webhook"})

        def sandbox() -> Result:
            key = f"slack-{self.store.next_number(self.name, 'message', 1)}"
            record = {"key": key, "channel": channel or self.setting("SLACK_CHANNEL") or "#general",
                      "title": title, "text": text, "facts": _facts(facts), "link": list(link) if link else None,
                      "thread": thread, "blocks": body["blocks"]}
            self._remember(key, "message", record)
            return Result(True, self.name, "post", "sandbox", key=key, url=self._sandbox_url(key), data=record)

        return self._call("post", {"title": title, "text": text, "channel": channel, "facts": _facts(facts)},
                          live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)


class Teams(Connector):
    name = "teams"
    title = "Microsoft Teams"
    category = "Messaging"
    description = "Post Adaptive Card messages to a Teams channel through a Workflows or incoming webhook."
    vendor_url = "https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook"
    settings = (
        Setting("TEAMS_WEBHOOK_URL", "Webhook URL", required=True, secret=True,
                help="Workflows → 'Post to a channel when a webhook request is received'"),
    )
    operations = {"post": "Post a card (title, text, facts, a link) to a channel"}

    @staticmethod
    def card(title: str, text: str, facts: Facts, link: tuple[str, str] | None) -> dict[str, Any]:
        body: list[dict[str, Any]] = [{"type": "TextBlock", "text": title[:200], "weight": "Bolder", "size": "Medium", "wrap": True}]
        if text:
            body.append({"type": "TextBlock", "text": text[:3000], "wrap": True})
        pairs = _facts(facts)
        if pairs:
            body.append({"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in pairs]})
        card: dict[str, Any] = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                                "version": "1.4", "body": body}
        if link and link[1].startswith("http"):
            card["actions"] = [{"type": "Action.OpenUrl", "title": link[0][:60], "url": link[1]}]
        return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                                                    "contentUrl": None, "content": card}]}

    def post(self, title: str, text: str = "", *, facts: Facts = None, link: tuple[str, str] | None = None,
             idempotency_key: str | None = None, ref: str | None = None) -> Result:
        payload = self.card(title, text, facts, link)

        def live() -> Result:
            status, data = http_json("POST", self.setting("TEAMS_WEBHOOK_URL"), body=payload)
            if isinstance(data, str) and data.strip() not in ("", "1") and "error" in data.lower():
                raise ConnectorError(f"Teams refused the card: {data[:300]}")
            return Result(True, self.name, "post", "live", data={"status": status})

        def sandbox() -> Result:
            key = f"teams-{self.store.next_number(self.name, 'message', 1)}"
            record = {"key": key, "title": title, "text": text, "facts": _facts(facts),
                      "link": list(link) if link else None, "card": payload}
            self._remember(key, "message", record)
            return Result(True, self.name, "post", "sandbox", key=key, url=self._sandbox_url(key), data=record)

        return self._call("post", {"title": title, "text": text, "facts": _facts(facts)},
                          live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)
