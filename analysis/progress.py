"""Progress lines for long analysis runs, written so a Slurm log shows where a job is.

    log = Log("phase2", steps=12)
    with log.step("accuracy against the labels"):
        bar = log.bar("clusterings", total=len(runs))
        for r in runs: ...; bar.tick()

prints, flushed at once (Slurm buffers stdout otherwise):

    [phase2 10:02:13 +0:00:41] step 3/12: accuracy against the labels
    [phase2 10:02:43 +0:01:11]   clusterings 1,240/6,225 (20%) · 0:00:30 in this step · about 0:02:00 left
    [phase2 10:04:51 +0:03:19]   done in 0:02:38

A bar stays silent for a step that finishes within 10 s; a longer one prints at each tenth of
its total (at most every 5 s) and at least every 30 s, so a step that stalls still shows its
last count. PHASE2_QUIET=1 silences everything.
"""

import os
import sys
import time
from contextlib import contextmanager
from datetime import timedelta


def _hms(seconds):
    return str(timedelta(seconds=int(max(seconds, 0))))


class Bar:
    """Counts items; prints only once a step has run QUIET_S seconds (a quick step stays one line),
    then at each tenth of the total (no more often than every MIN_GAP_S) and at least every EVERY_S."""
    QUIET_S, MIN_GAP_S, EVERY_S = 10.0, 5.0, 30.0

    def __init__(self, log, label, total):
        self.log, self.label, self.total = log, label, max(int(total), 0)
        self.n, self.t0 = 0, time.monotonic()
        self.last_t, self.next_frac, self.printed = self.t0, 0.1, False

    def tick(self, n=1):
        self.n += n
        now = time.monotonic()
        frac = self.n / self.total if self.total else 1.0
        crossed = frac >= self.next_frac
        while self.next_frac <= frac:
            self.next_frac += 0.1
        done = self.n >= self.total
        if now - self.t0 < self.QUIET_S and not (done and self.printed):
            return
        if not (done or now - self.last_t >= self.EVERY_S or (crossed and now - self.last_t >= self.MIN_GAP_S)):
            return
        self.last_t, self.printed = now, True
        spent = now - self.t0
        eta = f" · about {_hms(spent / self.n * (self.total - self.n))} left" if self.n and not done else ""
        self.log.say(f"  {self.label} {self.n:,}/{self.total:,} ({100 * frac:.0f}%) · {_hms(spent)} in this step{eta}")


class _Null:
    def tick(self, n=1):
        pass


class Log:
    def __init__(self, name, steps=0):
        self.name, self.steps, self.i = name, steps, 0
        self.t0 = time.monotonic()
        self.quiet = os.environ.get("PHASE2_QUIET") == "1"

    def say(self, msg):
        if self.quiet:
            return
        stamp = time.strftime("%H:%M:%S")
        print(f"[{self.name} {stamp} +{_hms(time.monotonic() - self.t0)}] {msg}", file=sys.stdout, flush=True)

    @contextmanager
    def step(self, label):
        self.i += 1
        of = f"/{self.steps}" if self.steps else ""
        self.say(f"step {self.i}{of}: {label}")
        t = time.monotonic()
        yield self
        self.say(f"  done in {_hms(time.monotonic() - t)}")

    def bar(self, label, total):
        return _Null() if self.quiet else Bar(self, label, total)


NULL = Log("quiet")
NULL.quiet = True
