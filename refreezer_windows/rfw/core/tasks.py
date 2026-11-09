"""Background work for the GUI: callables run on a pool, results come back on the Tk thread.

Workers never touch widgets: they put messages on a queue that ``drain`` (called from the
Tk thread by the poll loop) applies. Message kinds: "ok", "err", "status", "call".
No Tk import here; the window passes the status/error/busy callbacks in.
"""

import queue
from concurrent.futures import ThreadPoolExecutor


def gather(*fns):
    """Run independent blocking calls side by side; results in argument order.

    The first failing call (in argument order) re-raises, like running them one by one.
    """
    if len(fns) < 2:
        return tuple(fn() for fn in fns)
    with ThreadPoolExecutor(max_workers=len(fns), thread_name_prefix="rfw-gather") as ex:
        futs = [ex.submit(fn) for fn in fns]
        return tuple(f.result() for f in futs)


class TaskRunner:
    def __init__(self, on_status, on_error, on_busy, workers=3, executor=None):
        """``on_busy(True)`` fires per started task, ``on_busy(False)`` once all are done."""
        self.q = queue.Queue()
        self.pool = executor or ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rfw-bg")
        self.busy = 0
        self._on_status, self._on_error, self._on_busy = on_status, on_error, on_busy

    def run(self, fn, on_ok=None, status=None):
        """Run ``fn`` on the pool; ``on_ok(result)`` later runs on the Tk thread."""
        if status:
            self._on_status(status)
        self.busy += 1
        self._on_busy(True)

        def task():
            try:
                self.q.put(("ok", on_ok, fn()))
            except Exception as e:  # shown on the Tk thread
                self.q.put(("err", None, e))

        self.pool.submit(task)

    def post(self, fn):
        """Any thread: run ``fn()`` on the Tk thread at the next drain (e.g. global hotkeys)."""
        self.q.put(("call", fn, None))

    def post_status(self, text):
        """Any thread: show ``text`` in the status line at the next drain."""
        self.q.put(("status", None, text))

    def progress(self, done, total, label):
        self.post_status(f"{label}: {done}/{total}")

    def drain(self):
        """Tk thread: apply everything posted since the last call."""
        while True:
            try:
                kind, cb, payload = self.q.get_nowait()
            except queue.Empty:
                return
            if kind == "status":
                self._on_status(payload)
                continue
            if kind == "call":
                cb()
                continue
            self.busy -= 1
            if self.busy <= 0:
                self.busy = 0
                self._on_busy(False)
            if kind == "err":
                self._on_error(payload)
            elif cb:
                cb(payload)

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
