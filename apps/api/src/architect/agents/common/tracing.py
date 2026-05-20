"""Langfuse tracing stub.

For v1 we keep the surface area but skip wiring real Langfuse instrumentation
until we have agents actually running in earnest. The CallbackHandler interface
is the integration point — drop in `langfuse.callback.CallbackHandler(...)`
when ready and the rest of the codebase needs no changes.

Why a no-op stub instead of nothing: agents already accept a `callbacks` list
on `make_model()`; centralizing the "what callbacks should we add" decision
here means the swap is one file when we're ready.
"""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler

from architect.config import Settings


def langfuse_handler(settings: Settings) -> BaseCallbackHandler | None:
    """Return a Langfuse callback handler if configured, else None.

    In v1 this always returns None — wire up the real handler in M3 once
    Langfuse is mandatory infra.
    """
    _ = settings
    return None
