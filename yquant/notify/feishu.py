"""Feishu (Lark) webhook notifier."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any

from yquant.config import AppConfig
from yquant.notify.alerts import AlertMessage

# A transport takes the webhook URL and the JSON payload and delivers it.
Transport = Callable[[str, dict[str, Any]], None]


class FeishuNotifier:
    """Post plain-text alerts to a Feishu custom-bot webhook."""

    def __init__(self, webhook_url: str, *, transport: Transport | None = None) -> None:
        if not webhook_url.strip():
            raise ValueError("webhook_url must not be empty")
        self.webhook_url = webhook_url
        self._transport = transport or _requests_transport

    def send(self, message: AlertMessage) -> None:
        payload = {
            "msg_type": "text",
            "content": {"text": f"{message.title}\n{message.text}"},
        }
        self._transport(self.webhook_url, payload)


def notifier_from_env(
    config: AppConfig,
    *,
    transport: Transport | None = None,
) -> FeishuNotifier | None:
    """Build a notifier from the configured webhook env var, or ``None`` if unset.

    Returning ``None`` when the secret is absent lets callers treat alerting as
    best-effort: no webhook configured means jobs still run, just silently.
    """

    webhook_url = os.getenv(config.notification.feishu.webhook_env, "").strip()
    if not webhook_url:
        return None
    return FeishuNotifier(webhook_url, transport=transport)


def _requests_transport(url: str, payload: dict[str, Any]) -> None:
    requests = importlib.import_module("requests")
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
