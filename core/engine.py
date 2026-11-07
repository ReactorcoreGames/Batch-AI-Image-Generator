"""Batch engine — prompt file in, images plus sidecar metadata out.

Design notes worth keeping in view:

* **Politeness is a requirement, not a setting.** Default concurrency is 2 with
  a deliberate inter-request delay, and 429 is always honoured. Cloudflare's
  free tier is a courtesy; hammering it risks the account.

* **Download immediately.** The image bytes are written the moment they arrive.
  Nothing holds a provider URL for later.

* **The failure taxonomy drives everything.** A content block is permanent and
  must never be retried; a 429 is retry-with-patience; a 500 is retry-with-
  backoff. Getting these confused either burns quota or discards good jobs.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import db as dbmod
from . import imagecheck
from . import models as M
from . import prompts as P
from . import reference as R
from .providers import get_provider
from .providers.base import (
    AuthError,
    ContentBlocked,
    PermanentError,
    Provider,
    QuotaExhausted,
    RateLimited,
    TransientError,
)

log = logging.getLogger("batchgen.engine")

# "the reference has not been prepared yet", distinct from a prepared value
# of None ("this batch has no reference"). Without the distinction, a batch
# with no reference would re-run the preparation check on every single job.
_UNPREPARED = object()

# Conservative on purpose. See the politeness note above.
DEFAULT_CONCURRENCY = 2
DEFAULT_DELAY = 1.0          # seconds between requests, per worker
# Attempts are TOTAL TRIES, not retries: 3 means one try plus two retries.
DEFAULT_MAX_ATTEMPTS = 3
# A PAID model gets exactly ONE try and no retries. Measured 2026-09-06: a
# parsing bug turned one wanted p-image into FOUR billed generations, because
# a perfectly good response was misread as transient and retried. A retry on a
# paid model is a fresh charge for the same picture, so the budget that made
# sense on a free endpoint is the wrong default the moment money is involved.
# The user's call, and deliberately stricter than the free lane.
PAID_MAX_ATTEMPTS = 1
DEFAULT_TIMEOUT = 180.0
MAX_BACKOFF = 120.0


@dataclass
class BatchConfig:
    prompt_file: Path
    output_dir: Path
    model: str = M.DEFAULT_MODEL
    ratio: str = M.DEFAULT_RATIO
    tier: M.Tier = M.DEFAULT_TIER
    width: int | None = None          # overrides ratio/tier when given
    height: int | None = None
    style_file: Path | None = None
    style_suffix: str = ""
    # Generate only the first N prompts in the file. None = all of them.
    # This is a TEST-BATCH control: it exists so a style can be tried on 5 of
    # 100 prompts without maintaining a second prompt file. It takes the first
    # N rather than a random N deliberately -- resume identifies a job by line
    # number, so a stable prefix means a limited run and a later full run share
    # their overlapping images instead of regenerating them.
    limit: int | None = None
    negative_prompt: str | None = None
    guidance: float | None = None
    steps: int | None = None
    # Prompt expansion mode, for models that rewrite the prompt before
    # generating (krea). None means the program default, which is "raw" --
    # expansion OFF -- not the API's own default of "low".
    prompt_expansion: str | None = None
    # Content-filter mode for the two models that expose a lever on their own
    # filter (p-image, flux-2-pro). None means the program default, which is
    # "permissive" -- the loosest setting each model offers, NOT the provider's
    # own. A batch tool pays for a spurious refusal in a slot of an overnight
    # run; see DEFAULT_CONTENT_FILTER in core/models.py for the full reasoning.
    content_filter: str | None = None
    # ONE global style reference image, applied to every prompt in the batch,
    # on the models whose spec names a reference_field. None means no
    # reference -- and that is not the same as an empty path: the flag and
    # the path persist separately in the GUI, so unticking keeps the
    # selection. See core/reference.py for the whole decision layer.
    reference_image: Path | None = None
    reference_resample: str = R.DEFAULT_RESAMPLE
    # A sentence appended to every prompt asking the model to follow the
    # reference (none | subtle | medium | heavy | exact). Applied only when
    # a reference is actually being sent -- see influence_phrase() below.
    reference_influence: str = R.DEFAULT_INFLUENCE
    seed: int | None = None           # fixed seed; None = random per image
    random_seed: bool = True
    concurrency: int = DEFAULT_CONCURRENCY
    delay: float = DEFAULT_DELAY
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    timeout: float = DEFAULT_TIMEOUT
    overwrite: bool = False
    output_format: str = "keep"   # keep | png | jpg | webp
    jpeg_quality: int = 95
    db_path: Path | None = None

    def resolved_size(self) -> tuple[int, int]:
        if self.width and self.height:
            return self.width, self.height
        return M.size_for(self.ratio, self.tier, self.model)


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    failed: int = 0
    blocked: int = 0
    skipped: int = 0
    in_flight: int = 0
    cost: float = 0.0
    started: float = field(default_factory=time.time)
    current: str = ""

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    @property
    def finished(self) -> int:
        return self.done + self.failed + self.blocked + self.skipped


ProgressCallback = Callable[[Progress], None]


class BatchEngine:
    """Runs one batch. Pause / resume / cancel are supported so the same
    object can back both the CLI and (in Session 3) the GUI."""

    def __init__(
        self,
        config: BatchConfig,
        provider: Provider | None = None,
        store: dbmod.JobStore | None = None,
        on_progress: ProgressCallback | None = None,
    ):
        self.cfg = config
        self.spec = M.get_model(config.model)
        self.width, self.height = config.resolved_size()

        self.cfg.output_dir = Path(self.cfg.output_dir)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        db_path = config.db_path or (self.cfg.output_dir / ".batchgen.db")
        self.store = store or dbmod.JobStore(db_path)
        self._owns_store = store is None

        self.provider = provider or get_provider(self.spec.provider)
        self._owns_provider = provider is None

        self.on_progress = on_progress
        self.progress = Progress()

        self._pause = threading.Event()
        self._pause.set()               # set == running
        self._cancel = threading.Event()
        self._rate_lock = threading.Lock()
        self._next_allowed = 0.0
        self._lock = threading.Lock()
        self.batch_id: int | None = None
        self.quota_exhausted: str | None = None
        self._corpus: list[str] | None = None
        # Prepared ONCE for the whole batch, not per image: decoding and
        # resizing the same file for every line of a 500-image run would be
        # pure waste, and two workers preparing it concurrently could in
        # principle disagree and hash differently. Sentinel rather than None,
        # because None is a legitimate prepared value ("no reference").
        self._reference: object = _UNPREPARED

    # -- lifecycle --------------------------------------------------------

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()          # unblock any worker parked on the pause gate

    @property
    def paused(self) -> bool:
        return not self._pause.is_set()

    def close(self) -> None:
        if self._owns_provider:
            self.provider.close()
        if self._owns_store:
            self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- planning ---------------------------------------------------------

    def load_lines(self) -> list[P.PromptLine]:
        """The single place prompts enter the engine.

        `limit` is applied HERE and nowhere else, so the job planner, the cost
        estimate and the dry run cannot disagree about how many images a run
        will actually produce.
        """
        suffix = self.cfg.style_suffix or P.load_style_suffix(self.cfg.style_file)
        lines = P.load_prompts(self.cfg.prompt_file, suffix)
        limit = self.cfg.limit
        if limit is not None and limit >= 0:
            lines = lines[:limit]
        # The influence phrase goes on HERE, so it is in `final` -- and so in
        # the request, the job row, the sidecar and the filename hash alike.
        # `original` stays the user's own line: it names the file and keys
        # the boilerplate corpus, neither of which this sentence belongs in.
        phrase = self.influence_phrase()
        if phrase:
            for ln in lines:
                ln.final = R.with_influence(ln.final, phrase)
        return lines

    def influence_phrase(self) -> str:
        """The reference-influence sentence for this batch, or "".

        Gated on the same two facts that put a reference in the request -- a
        path was given AND the model has a reference field -- rather than on
        self.reference(), so asking for the phrase never decodes the image
        and never raises over a bad file. The file itself is still validated
        by reference() before anything is sent.
        """
        if self.cfg.reference_image is None:
            return ""
        return R.influence_phrase(self.cfg.reference_influence, self.spec)

    def naming_corpus(self) -> list[str]:
        """Every prompt in the file, for the keep-what-varies filename slug.

        Cached: the workers ask for this per job, and re-reading the prompt
        file on each one would also risk two jobs naming themselves off
        different corpora if the file were edited mid-run.

        Deliberately UNLIMITED -- `load_lines()` applies cfg.limit, and naming
        off a truncated corpus would make a 5-of-100 test run and the later
        full run disagree about which words are boilerplate, so the same line
        would be named two different things and resume would regenerate it.
        """
        if self._corpus is None:
            suffix = (self.cfg.style_suffix
                      or P.load_style_suffix(self.cfg.style_file))
            self._corpus = [
                ln.original
                for ln in P.load_prompts(self.cfg.prompt_file, suffix)
            ]
        return self._corpus

    def reference(self) -> "R.PreparedReference | None":
        """The prepared style reference for this batch, or None.

        Cached, and prepared exactly once -- see the note on `_reference`.

        A reference set for a model that cannot take one is DROPPED with a
        log line rather than raising: the models are chosen in one dropdown
        and the reference in another, so the combination is reachable by
        ordinary use, and failing a whole batch over it would be a worse
        answer than generating without the reference and saying so. The GUI
        disables the control and says why before it gets this far.

        An unusable FILE, by contrast, raises: the user picked that file
        deliberately, the message names the actual numbers and the remedy,
        and silently generating several hundred images without the style
        they asked for is the failure this refuses to commit.
        """
        if self._reference is _UNPREPARED:
            self._reference = self._prepare_reference()
        return self._reference   # type: ignore[return-value]

    def _prepare_reference(self) -> "R.PreparedReference | None":
        if self.cfg.reference_image is None:
            return None
        if self.spec.reference_field is None:
            log.warning(
                "%s cannot take a style reference image, so %s is being "
                "ignored for this batch. Models that can: %s",
                self.spec.short_name, Path(self.cfg.reference_image).name,
                M.reference_models_sentence())
            return None
        return R.prepare(
            self.cfg.reference_image,
            self.cfg.reference_resample,
            output_size=(self.width, self.height),
        )

    def _name_args(self, original: str, final: str, corpus: Sequence[str]) -> dict:
        """The naming inputs, in ONE place.

        `_write_output` and `existing_output` must agree exactly or resume
        looks for a filename nothing was written under -- and on a paid model
        that means buying an image that is already on disk.
        """
        suffix = self.cfg.style_suffix or P.load_style_suffix(self.cfg.style_file)
        return {
            "style_suffix": suffix,
            "corpus": corpus,
            "hash_parts": P.image_hash_parts(
                final_prompt=final,
                model=self.spec.key,
                width=self.width,
                height=self.height,
                negative_prompt=self.cfg.negative_prompt,
                guidance=self.cfg.guidance,
                steps=(self.cfg.steps if self.spec.steps_settable
                       else self.spec.default_steps),
                prompt_expansion=self.cfg.prompt_expansion,
                content_filter=self.cfg.content_filter,
                # The reference is image-affecting, so it is part of the
                # image's identity -- by CONTENT hash, so swapping a
                # different sprite in under the same filename regenerates
                # rather than silently resuming and doing nothing.
                reference_hash=R.hash_part(self.reference()),
            ),
        }

    def prepare(self, reuse: bool = True) -> int:
        """Create or reattach to a batch and populate its job rows.

        Reattaching is what makes `resume` work: an identical batch already in
        the database is continued rather than duplicated.
        """
        lines = self.load_lines()
        suffix = self.cfg.style_suffix or P.load_style_suffix(self.cfg.style_file)
        # The reference is part of the batch's IDENTITY, not just of the
        # filename. Both gates need it: the style-suffix bug was in the
        # filename AND in find_batch(), and fixing only one left the symptom.
        # "" rather than None for a batch with no reference, so the column's
        # DEFAULT and this agree and every pre-existing batch still matches.
        ref_hash = R.hash_part(self.reference()) or ""

        # The influence phrase changes every final prompt, so it is part of
        # the batch identity too -- carried on the stored suffix, which is
        # what find_batch() compares. With influence off it is the bare
        # suffix, so every batch made before the setting existed still
        # matches. (The filename gate is covered by the final-prompt hash.)
        suffix = R.with_influence(suffix, self.influence_phrase())

        row = (
            self.store.find_batch(
                str(self.cfg.prompt_file), str(self.cfg.output_dir),
                self.spec.key, self.width, self.height, suffix, ref_hash,
            )
            if reuse
            else None
        )
        if row is not None:
            self.batch_id = int(row["id"])
            reset = self.store.reset_running(self.batch_id)
            if reset:
                log.info("reset %d job(s) left 'running' by a previous crash", reset)
        else:
            self.batch_id = self.store.create_batch(
                source_file=str(self.cfg.prompt_file),
                style_suffix=suffix,
                output_dir=str(self.cfg.output_dir),
                provider=self.spec.provider,
                model=self.spec.key,
                ratio=self.cfg.ratio,
                tier=self.cfg.tier,
                width=self.width,
                height=self.height,
                reference_hash=ref_hash,
            )

        per_image = self.spec.cost_per_image(self.width, self.height)
        self.store.add_jobs(
            self.batch_id,
            [
                {
                    "line_no": ln.line_no,
                    "original_prompt": ln.original,
                    "final_prompt": ln.final,
                    "provider": self.spec.provider,
                    "model": self.spec.key,
                    "width": self.width,
                    "height": self.height,
                    "seed": self.cfg.seed,
                    "cost_estimate": per_image,
                }
                for ln in lines
            ],
        )
        return self.batch_id

    def _reference_metadata(self) -> dict:
        """The sidecar's record of the style reference, or empty.

        Returns NOTHING at all when no reference was used, rather than a
        block of nulls: every sidecar already on disk has no such keys, and a
        run without a reference should keep matching them.
        """
        ref = self.reference()
        if ref is None:
            return {}
        return {
            "reference_image": str(ref.path),
            "reference_sent_size": [ref.width, ref.height],
            "reference_source_size": [ref.source_width, ref.source_height],
            "reference_resampler": ref.resampler or "none",
            "reference_hash": ref.content_hash,
        }

    def dry_run(self) -> dict:
        """Job count + cost estimate with ZERO API calls."""
        lines = self.load_lines()
        est = M.estimate(self.spec.key, self.width, self.height, len(lines))
        suffix = self.cfg.style_suffix or P.load_style_suffix(self.cfg.style_file)
        # An unusable reference must fail HERE too, with the same message the
        # GUI shows -- a dry run that quietly ignored a bad reference and
        # then let the real run refuse it would be worse than no dry run.
        ref = self.reference()

        # The real extension, not a guess: a chosen output_format wins,
        # otherwise it is whatever this model actually delivers (measured per
        # model -- the content-type header lies, and several models that
        # declare PNG send JPEG). Hardcoding .png here made the dry run name
        # files that the batch would never write.
        if self.cfg.output_format not in ("", "keep", "original"):
            ext = "." + self.cfg.output_format.lstrip(".")
        else:
            ext = "." + self.spec.output_format
        return {
            "prompt_file": str(self.cfg.prompt_file),
            "output_ext": ext,
            "output_dir": str(self.cfg.output_dir),
            "jobs": len(lines),
            "model": self.spec.key,
            "model_id": self.spec.id,
            "provider": self.spec.provider,
            "size": f"{self.width}x{self.height}",
            "ratio": self.cfg.ratio,
            "tier": self.cfg.tier,
            "tiles": est.tiles,
            "bills_per_tile": est.bills_per_tile,
            "cost_tier": est.cost_tier,
            "megapixels": est.megapixels,
            "cost_per_image": est.cost_per_image,
            "cost_per_1000": est.cost_per_1000,
            "total_cost": est.total_cost,
            "is_free": est.is_free,
            "over_budget": est.over_budget,
            "free_images_per_day": est.free_images_per_day,
            "warnings": est.warnings,
            "errors": est.errors,
            "style_suffix": suffix,
            # The reference, described the same way the GUI status label
            # describes it -- both render this one verdict rather than each
            # computing its own, which is why core.reference owns the whole
            # decision layer. A dry run is where a user checks before paying,
            # so the TRANSFORMATION has to appear here and not just the path.
            "reference": (
                None if ref is None else {
                    "path": str(ref.path),
                    "sent_size": ref.size_text,
                    "source_size": ref.source_size_text,
                    "resampler": ref.resampler or "none",
                    "resampler_reason": ref.resampler_reason,
                    "transform": ref.transform,
                    "describe": ref.describe(),
                    "warnings": list(ref.warnings),
                }
            ),
            # Two different Nones, and the CLI has to tell them apart: "no
            # reference was asked for" and "one was asked for and this model
            # cannot take it" need different output, and only the second is
            # worth saying out loud.
            # The sentence added to every prompt, shown on its own line by the
            # CLI so it is visible rather than buried in each final prompt.
            "reference_influence": self.influence_phrase(),
            "reference_requested": self.cfg.reference_image is not None,
            "reference_supported": self.spec.reference_field is not None,
            "lines": [
                {"line_no": ln.line_no, "original": ln.original, "final": ln.final,
                 # Must match what the run will actually write, including the
                 # hash -- a dry run that names files the batch would not
                 # produce is worse than no preview.
                 "filename": P.build_filename(
                     self.cfg.prompt_file, ln.line_no, ln.original, ext,
                     **self._name_args(ln.original, ln.final,
                                       self.naming_corpus()))}
                for ln in lines
            ],
        }

    # -- running ----------------------------------------------------------

    def run(self, retry_failed: bool = False, regenerate: bool = False) -> Progress:
        if self.batch_id is None:
            self.prepare()
        assert self.batch_id is not None

        if retry_failed:
            n = self.store.requeue_failed(self.batch_id)
            log.info("requeued %d failed job(s)", n)

        if regenerate:
            # Requeueing alone is not enough: the job would be claimed and then
            # immediately skipped again by the on-disk check in _generate_one.
            # Regenerate means "make it again regardless", so it implies
            # overwrite for this run -- otherwise the image lands beside the
            # old one as `_2` and the folder fills with near-duplicates.
            self.cfg.overwrite = True
            n = self.store.requeue_finished(self.batch_id)
            log.info("regenerating %d finished job(s)", n)

        errs = self.spec.validate_size(self.width, self.height)
        if errs:
            raise ValueError("; ".join(errs))
        for w in self.spec.size_warnings(self.width, self.height):
            log.warning(w)

        counts = self.store.counts(self.batch_id)
        with self._lock:
            self.progress = Progress(
                total=counts["total"],
                done=counts[dbmod.DONE],
                failed=counts[dbmod.FAILED],
                blocked=counts[dbmod.BLOCKED],
                skipped=counts[dbmod.SKIPPED],
                cost=self.store.total_cost(self.batch_id),
            )
        self._emit()

        workers = max(1, int(self.cfg.concurrency))

        # Some providers cap how many requests may be in flight per IP and
        # reject the surplus outright rather than queueing it. Exceeding that
        # cannot go faster -- it only produces 429s that eat each job's retry
        # budget -- so honour the provider's own limit.
        cap = getattr(self.provider, "max_concurrency", 0)
        if cap and workers > cap:
            log.warning(
                "%s allows %d concurrent request(s); reducing concurrency "
                "from %d to %d", self.provider.name, cap, workers, cap,
            )
            workers = cap
        log.info(
            "batch %d: %d job(s), %d pending, model=%s size=%dx%d "
            "concurrency=%d delay=%.1fs",
            self.batch_id, counts["total"], counts[dbmod.PENDING],
            self.spec.key, self.width, self.height, workers, self.cfg.delay,
        )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._worker) for _ in range(workers)]
            for f in futures:
                f.result()

        if not self._cancel.is_set():
            self.store.finish_batch(self.batch_id)
        return self.progress

    def _worker(self) -> None:
        while not self._cancel.is_set():
            self._pause.wait()
            if self._cancel.is_set():
                return
            job = self.store.claim_next(self.batch_id)
            if job is None:
                return
            try:
                self._process(job)
            except QuotaExhausted as e:
                # A batch-level stop, not a per-job failure: the wall does not
                # move for hours, so every remaining job would burn its full
                # retry budget against it for nothing. The job that surfaced
                # this was never given a fair attempt, so it is released back
                # to pending (not failed) — the existing resume path picks it
                # up unchanged once the allowance recovers.
                log.warning("quota exhausted, stopping batch: %s", e)
                self.store.release(job.id, str(e))
                with self._lock:
                    self.quota_exhausted = str(e)
                self._cancel.set()
                return
            except AuthError as e:
                # Credentials are a whole-batch problem, not a job problem.
                # Continuing would just burn every remaining job identically.
                log.error("authentication failed, cancelling batch: %s", e)
                self.store.release(job.id, str(e))
                self._cancel.set()
                return
            except Exception as e:  # never let one job kill a worker
                log.exception("unexpected error on line %d", job.line_no)
                self.store.mark_status(job.id, dbmod.FAILED, f"{type(e).__name__}: {e}")
                self._bump(failed=1)

    def _process(self, job: dbmod.Job) -> None:
        with self._lock:
            self.progress.in_flight += 1
            # 100 clipped mid-sentence on almost every real prompt. MEASURED
            # 2026-09-13 at the 900px minimum window width: the GUI's label
            # reserves two lines (27px empty, 50px at two), and 160 characters
            # is the most that still fits them -- 240 spilled to three lines
            # and made the panels below it jump on every image, which is the
            # exact failure `reserve_lines` exists to prevent.
            self.progress.current = job.original_prompt[:160]
        self._emit()
        try:
            self._generate_one(job)
        finally:
            with self._lock:
                self.progress.in_flight -= 1

    def _generate_one(self, job: dbmod.Job) -> None:
        # Resume: an image already on disk means this job is done, regardless
        # of what the database thinks. Overwrite protection lives here.
        if not self.cfg.overwrite:
            existing = P.existing_output(
                self.cfg.output_dir, self.cfg.prompt_file, job.line_no,
                job.original_prompt,
                **self._name_args(job.original_prompt, job.final_prompt,
                                  self.naming_corpus()),
            )
            if existing is not None:
                log.info("line %d: keeping existing %s", job.line_no, existing.name)
                self.store.mark_status(job.id, dbmod.SKIPPED, "output already exists")
                self._bump(skipped=1)
                return

        seed = job.seed
        if seed is None:
            seed = (
                random.randint(0, 2**31 - 1)
                if self.cfg.random_seed
                else self.cfg.seed
            )

        try:
            self._throttle()
            result = self.provider.generate(
                self.spec,
                job.final_prompt,
                self.width,
                self.height,
                seed=seed,
                negative_prompt=self.cfg.negative_prompt,
                guidance=self.cfg.guidance,
                prompt_expansion=self.cfg.prompt_expansion,
                content_filter=self.cfg.content_filter,
                reference=self.reference(),
                steps=self.cfg.steps,
                timeout=self.cfg.timeout,
            )
        except ContentBlocked as e:
            # PERMANENT by definition — the prompt is the problem. Retrying
            # burns quota and produces the same black frame every time.
            log.warning("line %d BLOCKED by content filter: %s", job.line_no, e)
            self.store.mark_status(job.id, dbmod.BLOCKED, str(e))
            self._bump(blocked=1)
            return
        except QuotaExhausted:
            # Handled by the caller (_worker): batch-level stop, job left
            # untouched so it can be released rather than marked failed.
            raise
        except PermanentError as e:
            log.error("line %d permanent failure: %s", job.line_no, e)
            self.store.mark_status(job.id, dbmod.FAILED, str(e))
            self._bump(failed=1)
            return
        except (RateLimited, TransientError) as e:
            self._handle_transient(job, e)
            return

        path = self._write_output(job, result)
        self.store.mark_done(job.id, str(path), result.seed, result.cost_estimate)
        with self._lock:
            self.progress.done += 1
            self.progress.cost += result.cost_estimate
        self._emit()
        log.info(
            "line %d done in %.1fs -> %s (%s, %d bytes)",
            job.line_no, result.elapsed, path.name, result.ext, len(result.image_bytes),
        )
        # A provider that quietly resized the image must SAY so. Pollinations
        # clamps anything above ~0.59 MP and returns HTTP 200 with no error,
        # so without this a batch reports complete success while every file is
        # smaller than asked for -- the same silent-wrong-result shape as the
        # black-image content filter, and just as invisible in the log.
        actual = result.actual_dimensions
        if actual is not None and tuple(actual) != (result.width, result.height):
            log.warning(
                "line %d: provider returned %dx%d, not the requested %dx%d "
                "(the file and its .json record what actually arrived)",
                job.line_no, actual[0], actual[1], result.width, result.height,
            )

    def _attempt_budget(self, exc: Exception) -> int:
        """How many total tries this failure is allowed.

        A PAID model gets one try and no retries, because every retry is a
        fresh charge for the same image. The exception is a rate limit: a 429
        is rejected BEFORE generating, so it is never billed, and capping it
        would fail jobs that cost nothing to recover. That distinction is the
        whole point -- the cap exists to stop repeat SPENDING, not to stop
        repeat requests.
        """
        if isinstance(exc, RateLimited):
            return self.cfg.max_attempts
        if M.get_model(self.cfg.model).is_free:
            return self.cfg.max_attempts
        return min(self.cfg.max_attempts, PAID_MAX_ATTEMPTS)

    def _handle_transient(self, job: dbmod.Job, exc: Exception) -> None:
        """Retry with backoff, or give up once the attempt budget is spent."""
        budget = self._attempt_budget(exc)
        if job.attempts >= budget:
            log.error(
                "line %d failed after %d attempt(s): %s",
                job.line_no, job.attempts, exc,
            )
            self.store.mark_status(
                job.id, dbmod.FAILED, f"after {job.attempts} attempts: {exc}"
            )
            if budget == 1:
                log.error(
                    "line %d was NOT retried: %s is a paid model and a retry "
                    "would be charged again for the same image",
                    job.line_no, self.cfg.model,
                )
            self._bump(failed=1)
            return

        if isinstance(exc, RateLimited) and exc.retry_after:
            wait = min(float(exc.retry_after), MAX_BACKOFF)
            kind = "rate limited"
        else:
            # Exponential with jitter. Jitter matters with >1 worker: without
            # it, workers that get limited together retry in lockstep forever.
            base = min(2.0 ** job.attempts, MAX_BACKOFF)
            wait = base * (0.5 + random.random() * 0.5)
            kind = "rate limited" if isinstance(exc, RateLimited) else "transient"

        log.warning(
            "line %d %s (attempt %d/%d), backing off %.1fs: %s",
            job.line_no, kind, job.attempts, budget, wait, exc,
        )
        if isinstance(exc, RateLimited):
            # Push the shared gate out so EVERY worker waits, not just this one.
            with self._rate_lock:
                self._next_allowed = max(self._next_allowed, time.time() + wait)

        self.store.release(job.id, str(exc))
        self._sleep(wait)

    def _write_output(self, job: dbmod.Job, result) -> Path:
        """Write image + sidecar JSON.

        The extension comes from sniffed magic bytes, never from the declared
        content-type. When `output_format` asks for a specific type the bytes
        are re-encoded locally first -- providers do not offer a format
        parameter, so this is the only place a choice can be honoured.
        """
        data, ext = result.image_bytes, result.ext
        converted_from = None
        if self.cfg.output_format not in ("", "keep", "original"):
            data, ext = imagecheck.convert_image(
                result.image_bytes, self.cfg.output_format, self.cfg.jpeg_quality
            )
            if ext != result.ext:
                converted_from = result.ext.lstrip(".")

        name = P.build_filename(
            self.cfg.prompt_file, job.line_no, job.original_prompt, ext,
            **self._name_args(job.original_prompt, job.final_prompt,
                              self.naming_corpus()),
        )
        path = self.cfg.output_dir / name
        if path.exists() and not self.cfg.overwrite:
            path = P.unique_path(path)
        path.write_bytes(data)

        sidecar = {
            "original_prompt": job.original_prompt,
            "final_prompt": job.final_prompt,
            "style_suffix": self.cfg.style_suffix
            or P.load_style_suffix(self.cfg.style_file),
            "negative_prompt": self.cfg.negative_prompt,
            "guidance": self.cfg.guidance,
            "prompt_expansion": self.cfg.prompt_expansion,
            "content_filter": self.cfg.content_filter,
            # The style reference, recorded as what was actually SENT: the
            # prepared size and the content hash, not just the path. A path
            # alone would not say whether the file has changed since, and the
            # prepared size is the surprising part -- a 16x16 sprite goes out
            # at 1024x1024.
            **self._reference_metadata(),
            "steps": self.cfg.steps if self.spec.steps_settable else self.spec.default_steps,
            "provider": result.provider,
            "model": result.model,
            "model_id": result.model_id,
            "seed": result.seed,
            # REQUESTED size. Kept under the plain names for compatibility
            # with every sidecar already on disk.
            "width": result.width,
            "height": result.height,
            # DELIVERED size, sniffed from the returned bytes. These differ
            # whenever a provider quietly resizes: Pollinations clamps
            # anything above ~0.59 MP down to that budget and returns HTTP 200
            # with no error, so a sidecar recording only the request would
            # assert a size the file does not have. `size_mismatch` states it
            # outright rather than leaving two similar keys to be compared by
            # whoever reads the file later.
            "actual_dimensions": result.actual_dimensions,
            "size_mismatch": (
                result.actual_dimensions is not None
                and tuple(result.actual_dimensions) != (result.width,
                                                        result.height)
            ),
            "ratio": self.cfg.ratio,
            "tier": self.cfg.tier,
            "tiles": result.tiles,
            "cost_estimate_usd": result.cost_estimate,
            "elapsed_seconds": result.elapsed,
            "format": ext.lstrip("."),
            "provider_format": result.ext.lstrip("."),
            "converted_from": converted_from,
            "declared_content_type": result.declared_content_type,
            "response_encoding": result.response_encoding,
            "source_file": str(self.cfg.prompt_file),
            "line_no": job.line_no,
            "batch_id": self.batch_id,
            "job_id": job.id,
            "generated_at": dbmod.utcnow(),
            "image_file": path.name,
        }
        path.with_suffix(".json").write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    # -- pacing -----------------------------------------------------------

    def _throttle(self) -> None:
        """Enforce the inter-request delay across all workers.

        The gate is shared, so concurrency 2 with a 1s delay means one request
        per second overall — not two. That is the intent: the delay describes
        how hard we hit the provider, not how fast one worker spins.
        """
        with self._rate_lock:
            now = time.time()
            wait = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + max(0.0, self.cfg.delay)
        if wait > 0:
            self._sleep(wait)

    def _sleep(self, seconds: float) -> None:
        """Interruptible sleep — cancel must not have to wait out a backoff."""
        deadline = time.time() + seconds
        while not self._cancel.is_set():
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.25))

    # -- progress ---------------------------------------------------------

    def _bump(self, **kw: int) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self.progress, k, getattr(self.progress, k) + v)
        self._emit()

    def _emit(self) -> None:
        if self.on_progress:
            try:
                self.on_progress(self.progress)
            except Exception:
                log.debug("progress callback raised", exc_info=True)
