"""Tick step isolation: one failing step must not take later steps down with it."""

from gridscrapers.tick import run_step


class AbortingConn:
    """Mimics Postgres: after a failed statement every later one is refused
    ("current transaction is aborted") until the transaction is rolled back."""

    def __init__(self):
        self.aborted = False
        self.committed: list[str] = []
        self.rollbacks = 0
        self._pending: list[str] = []

    def execute(self, sql):
        if self.aborted:
            raise RuntimeError("current transaction is aborted, commands ignored")
        if sql == "bad":
            self.aborted = True
            raise RuntimeError("division by zero")
        self._pending.append(sql)

    def commit(self):
        if self.aborted:
            raise RuntimeError("cannot commit an aborted transaction")
        self.committed.extend(self._pending)
        self._pending = []

    def rollback(self):
        self.aborted = False
        self._pending = []
        self.rollbacks += 1


def test_failed_step_does_not_poison_the_next():
    conn, failures = AbortingConn(), []

    run_step(conn, "ci backtest", lambda c: c.execute("bad"), failures)
    out = run_step(conn, "estimation", lambda c: c.execute("write mix") or 32, failures)

    assert out == 32
    assert conn.committed == ["write mix"]
    assert len(failures) == 1 and failures[0].startswith("ci backtest failed")


def test_successful_step_commits_and_returns_its_result():
    conn, failures = AbortingConn(), []
    assert run_step(conn, "cross-check", lambda c: c.execute("q") or ["IN-MH"], failures) == ["IN-MH"]
    assert conn.committed == ["q"] and failures == [] and conn.rollbacks == 0


def test_failed_step_returns_none_and_discards_its_partial_writes():
    conn, failures = AbortingConn(), []

    def half_then_fail(c):
        c.execute("partial insert")
        c.execute("bad")

    assert run_step(conn, "psp ingest", half_then_fail, failures) is None
    assert conn.committed == [] and conn.rollbacks == 1
