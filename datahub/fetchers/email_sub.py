"""Email-subscription sources (邮件订阅).

These arrive by email and require an inbound mailbox (IMAP) or a webhook bridge,
which is an out-of-band integration. This fetcher records the source as a no-op
so it appears in the catalog and scheduler without erroring; wire it to a mailbox
poller when that integration is available."""

from __future__ import annotations

from .base import Fetcher, FetchResult


class EmailSubscriptionFetcher(Fetcher):
    method_keywords = ("邮件", "email", "newsletter（邮件", "mail")

    def fetch(self, source) -> FetchResult:
        return FetchResult(status="skipped", note="email subscription: needs mailbox bridge")
