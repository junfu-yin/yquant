"""Outbound alerting for unattended M1 jobs.

The notifier is transport-injectable so alert formatting and routing are unit
tested without any network. Real delivery uses the Feishu webhook whose env var
name lives in config (never the secret itself).
"""

from yquant.notify.alerts import (
    AlertMessage,
    freshness_alert,
    live_reconcile_alert,
    reconcile_alert,
)
from yquant.notify.feishu import FeishuNotifier, notifier_from_env

__all__ = [
    "AlertMessage",
    "FeishuNotifier",
    "freshness_alert",
    "live_reconcile_alert",
    "notifier_from_env",
    "reconcile_alert",
]
