"""Release one ledger download's reader and matter lease on every ASGI exit."""
from starlette.responses import StreamingResponse


class TextLedgerStreamingResponse(StreamingResponse):
    def __init__(self, content, *, release_lease, **kwargs):
        self.ledger_iterator = iter(content)
        self.release_lease = release_lease
        super().__init__(self.ledger_iterator, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette's ordinary background task is skipped when body
            # generation or send fails. Its sequential worker iteration has
            # ended here, so close the suspended reader before releasing the
            # deletion lease. The lease release is intentionally idempotent.
            try:
                self.ledger_iterator.close()
            finally:
                self.release_lease()
