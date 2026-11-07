"""SQLite job store.

This is what makes crash-resume correct rather than fragile, and what lets
concurrent workers update status without stepping on each other.

Status vocabulary — `blocked` is deliberately distinct from `failed`:

    pending   queued, never attempted
    running   claimed by a worker (reset to pending on resume — a `running`
              row at startup means the app died mid-flight)
    done      image written to disk
    failed    transient failures exhausted the retry budget; retryable
    blocked   the provider's content filter refused. PERMANENT: the prompt
              itself is the problem, so `retry-failed` must never pick it up
    skipped   an existing output file was kept (overwrite protection)
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
BLOCKED = "blocked"
SKIPPED = "skipped"

RETRYABLE_STATUSES = (FAILED,)          # blocked is deliberately excluded
TERMINAL_STATUSES = (DONE, BLOCKED, SKIPPED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file   TEXT NOT NULL,
    style_suffix  TEXT NOT NULL DEFAULT '',
    -- Content hash of the style reference image actually SENT, or '' for a
    -- batch with none. Part of the batch IDENTITY for the same reason
    -- style_suffix is: it is part of the image. See find_batch().
    reference_hash TEXT NOT NULL DEFAULT '',
    output_dir    TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    ratio         TEXT NOT NULL,
    tier          TEXT NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        INTEGER NOT NULL REFERENCES batches(id),
    line_no         INTEGER NOT NULL,
    original_prompt TEXT NOT NULL,
    final_prompt    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    width           INTEGER NOT NULL,
    height          INTEGER NOT NULL,
    seed            INTEGER,
    output_path     TEXT,
    cost_estimate   REAL NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    UNIQUE (batch_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_jobs_batch_status ON jobs (batch_id, status);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: int
    batch_id: int
    line_no: int
    original_prompt: str
    final_prompt: str
    status: str
    attempts: int
    provider: str
    model: str
    width: int
    height: int
    seed: int | None
    output_path: str | None
    cost_estimate: float
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            batch_id=row["batch_id"],
            line_no=row["line_no"],
            original_prompt=row["original_prompt"],
            final_prompt=row["final_prompt"],
            status=row["status"],
            attempts=row["attempts"],
            provider=row["provider"],
            model=row["model"],
            width=row["width"],
            height=row["height"],
            seed=row["seed"],
            output_path=row["output_path"],
            cost_estimate=row["cost_estimate"],
            error=row["error"],
        )


class JobStore:
    """Thread-safe SQLite wrapper.

    One connection guarded by a lock, with WAL enabled. At the concurrency this
    app deliberately uses (1-2 workers) that is simpler and more predictable
    than a connection pool, and it makes 'claim a job' genuinely atomic.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns that a database created by an older version lacks.

        `CREATE TABLE IF NOT EXISTS` does NOTHING to a table that already
        exists, so a new column in SCHEMA reaches a fresh database and no
        other. Every `.batchgen.db` already on a user's disk would then be
        missing it, and the very first query naming it would raise.

        Additive only, and each one has a DEFAULT, so an existing batch keeps
        the identity it was created with: a batch made before reference
        images existed reads back reference_hash='' and reattaches exactly as
        it always did.
        """
        with self._lock:
            have = {r["name"] for r in
                    self._conn.execute("PRAGMA table_info(batches)")}
            if "reference_hash" not in have:
                self._conn.execute(
                    "ALTER TABLE batches ADD COLUMN reference_hash "
                    "TEXT NOT NULL DEFAULT ''")
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # -- batches ----------------------------------------------------------

    def create_batch(
        self,
        source_file: str,
        style_suffix: str,
        output_dir: str,
        provider: str,
        model: str,
        ratio: str,
        tier: str,
        width: int,
        height: int,
        reference_hash: str = "",
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO batches (source_file, style_suffix, "
                "reference_hash, output_dir, provider, model, ratio, tier, "
                "width, height, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(source_file), style_suffix, reference_hash,
                    str(output_dir), provider, model, ratio, tier, width,
                    height, utcnow(),
                ),
            )
            return int(cur.lastrowid)

    def get_batch(self, batch_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()

    def latest_batch(self) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM batches ORDER BY id DESC LIMIT 1"
            ).fetchone()

    def list_batches(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM batches ORDER BY id DESC LIMIT ?", (limit,)
                )
            )

    def find_batch(
        self, source_file: str, output_dir: str, model: str, width: int,
        height: int, style_suffix: str = "", reference_hash: str = "",
    ) -> sqlite3.Row | None:
        """An existing batch with identical parameters — the thing `resume`
        reattaches to so a rerun continues instead of duplicating work.

        `style_suffix` is part of the identity because it is part of the image.
        It was stored by create_batch() from the start but not compared, so
        changing the style and rerunning the same prompts reattached to the old
        batch, found every job already `done`, and generated nothing -- with no
        error, which made it read as the program ignoring the new style.

        `reference_hash` is here for exactly the same reason, and it is here
        rather than only in the FILENAME because fixing one gate and not the
        other leaves the symptom -- which is the lesson the style-suffix bug
        taught this program once already. A changed reference is a changed
        image, so it must be a changed batch.

        It is the CONTENT hash of the prepared bytes, never the path: swapping
        a different sprite in under the same filename has to count as a
        change, and a path would say it was the same batch.
        """
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM batches WHERE source_file=? AND output_dir=? "
                "AND model=? AND width=? AND height=? AND style_suffix=? "
                "AND reference_hash=? "
                "ORDER BY id DESC LIMIT 1",
                (str(source_file), str(output_dir), model, width, height,
                 style_suffix, reference_hash),
            ).fetchone()

    def finish_batch(self, batch_id: int) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE batches SET finished_at=? WHERE id=?", (utcnow(), batch_id)
            )

    # -- jobs -------------------------------------------------------------

    def add_jobs(self, batch_id: int, rows: list[dict]) -> int:
        """Insert job rows. Idempotent on (batch_id, line_no), so re-adding an
        already-populated batch adds nothing rather than duplicating."""
        now = utcnow()
        with self._tx() as c:
            cur = c.executemany(
                "INSERT OR IGNORE INTO jobs (batch_id, line_no, original_prompt, "
                "final_prompt, provider, model, width, height, seed, "
                "cost_estimate, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        batch_id, r["line_no"], r["original_prompt"],
                        r["final_prompt"], r["provider"], r["model"],
                        r["width"], r["height"], r.get("seed"),
                        r.get("cost_estimate", 0.0), now,
                    )
                    for r in rows
                ],
            )
            return cur.rowcount

    def claim_next(self, batch_id: int) -> Job | None:
        """Atomically take the next pending job. Returns None when the queue
        is empty. The UPDATE...WHERE status='pending' is what makes two workers
        unable to claim the same row."""
        with self._tx() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE batch_id=? AND status=? "
                "ORDER BY line_no LIMIT 1",
                (batch_id, PENDING),
            ).fetchone()
            if row is None:
                return None
            cur = c.execute(
                "UPDATE jobs SET status=?, started_at=?, attempts=attempts+1 "
                "WHERE id=? AND status=?",
                (RUNNING, utcnow(), row["id"], PENDING),
            )
            if cur.rowcount == 0:
                return None      # another worker won the race; caller retries
            row = c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            return Job.from_row(row)

    def mark_done(
        self, job_id: int, output_path: str, seed: int | None, cost: float
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE jobs SET status=?, output_path=?, seed=?, "
                "cost_estimate=?, error=NULL, finished_at=? WHERE id=?",
                (DONE, str(output_path), seed, cost, utcnow(), job_id),
            )

    def mark_status(self, job_id: int, status: str, error: str | None = None) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error, utcnow(), job_id),
            )

    def release(self, job_id: int, error: str | None = None) -> None:
        """Put a claimed job back on the queue for another attempt."""
        with self._tx() as c:
            c.execute(
                "UPDATE jobs SET status=?, error=? WHERE id=?",
                (PENDING, error, job_id),
            )

    def reset_running(self, batch_id: int) -> int:
        """A `running` row at startup means the process died holding it.

        The attempt is refunded as well as the status reset — a crash is not
        the job's fault and must not eat its retry budget.
        """
        with self._tx() as c:
            cur = c.execute(
                "UPDATE jobs SET status=?, attempts=MAX(attempts-1, 0) "
                "WHERE batch_id=? AND status=?",
                (PENDING, batch_id, RUNNING),
            )
            return cur.rowcount

    def requeue_failed(self, batch_id: int, reset_attempts: bool = True) -> int:
        """Requeue `failed` jobs only. `blocked` is never touched: the content
        filter refused the prompt, and retrying it burns quota for nothing."""
        with self._tx() as c:
            sql = (
                "UPDATE jobs SET status=?, error=NULL"
                + (", attempts=0" if reset_attempts else "")
                + " WHERE batch_id=? AND status=?"
            )
            cur = c.execute(sql, (PENDING, batch_id, FAILED))
            return cur.rowcount

    def requeue_finished(self, batch_id: int) -> int:
        """Requeue `done` and `skipped` jobs — the Regenerate action.

        This is the ONE thing `overwrite` could never do. Overwrite is a
        file-level flag, checked only once a job is already running; a `done`
        row is never handed out by claim_next(), so ticking overwrite and
        rerunning a finished batch reached that check on no job at all and
        generated nothing.

        `blocked` is left alone, exactly as requeue_failed() leaves it: the
        content filter refused the prompt, and the same text refuses again.
        `failed` is left to requeue_failed() so "retry what broke" and
        "generate it all again" stay separate, differently-priced actions.
        """
        with self._tx() as c:
            cur = c.execute(
                "UPDATE jobs SET status=?, error=NULL, attempts=0 "
                "WHERE batch_id=? AND status IN (?,?)",
                (PENDING, batch_id, DONE, SKIPPED),
            )
            return cur.rowcount

    def jobs(self, batch_id: int, status: str | None = None) -> list[Job]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE batch_id=? AND status=? ORDER BY line_no",
                    (batch_id, status),
                )
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE batch_id=? ORDER BY line_no", (batch_id,)
                )
            return [Job.from_row(r) for r in rows]

    def counts(self, batch_id: int) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) n FROM jobs WHERE batch_id=? GROUP BY status",
                (batch_id,),
            )
            out = {s: 0 for s in (PENDING, RUNNING, DONE, FAILED, BLOCKED, SKIPPED)}
            for r in rows:
                out[r["status"]] = r["n"]
            out["total"] = sum(
                v for k, v in out.items() if k != "total"
            )
            return out

    def total_cost(self, batch_id: int) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_estimate),0) c FROM jobs "
                "WHERE batch_id=? AND status=?",
                (batch_id, DONE),
            ).fetchone()
            return float(row["c"])
