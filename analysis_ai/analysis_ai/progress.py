"""Progress/cancellation hooks shared by every pipeline stage.

A stage takes a `Ctx` and calls `ctx.check()` between units of work (chunks,
notes, embedding batches). The CLI passes a printing Ctx; the web service passes
one wired to a job record, so the same code powers both and any job can be
cancelled at its next checkpoint.
"""


class Cancelled(Exception):
    """Raised by Ctx.check() when the user cancelled the running job."""


class Ctx:
    def __init__(self, log=print, is_cancelled=lambda: False, on_progress=None):
        self._log = log
        self._is_cancelled = is_cancelled
        self._on_progress = on_progress

    def log(self, message: str) -> None:
        self._log(message)

    def check(self) -> None:
        if self._is_cancelled():
            raise Cancelled()

    def progress(self, done: int, total: int, current: str = "") -> None:
        if self._on_progress:
            self._on_progress(done, total, current)
