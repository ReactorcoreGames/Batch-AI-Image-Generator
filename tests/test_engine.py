"""Offline tests for the pieces that must not be validated against the live API.

Covers the failure taxonomy in particular: a content block must never be
retried, a 429 must be, and a crash must not eat a job's retry budget. Those
paths are the ones that quietly ruin an overnight batch, and provoking them
for real would mean deliberately abusing a shared free tier.

Run:  python -m pytest tests/ -q      (or: python tests/test_engine.py)
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx                                                   # noqa: E402

from core import db as dbmod                                  # noqa: E402
from core import models as M                                  # noqa: E402
from core import prompts as P                                 # noqa: E402
from core import recipes as RC                                # noqa: E402
from core import reference as R                               # noqa: E402
from core.engine import (                                  # noqa: E402
    DEFAULT_MAX_ATTEMPTS,
    PAID_MAX_ATTEMPTS,
    BatchConfig,
    BatchEngine,
)
from core.providers.base import (                             # noqa: E402
    ContentBlocked,
    GenerationResult,
    PermanentError,
    Provider,
    QuotaExhausted,
    RateLimited,
    TransientError,
)
from core.providers.cloudflare import (                        # noqa: E402
    CloudflareProvider,
    _PresignedURL,
)

# A 1x1 red PNG — decodable, and NOT flat-colour-blank by accident.
PNG_2x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000200000001080200000073b6"
    "9d3b0000001649444154789c62f8cfc0f01f8cc7080cff0100f5ff01ff9e9c"
    "2f7f0000000049454e44ae426082"
)


class FakeProvider(Provider):
    """Scripted provider: a list of outcomes per line number."""

    name = "fake"

    def __init__(self, script: dict[int, list]):
        self.script = script
        self.calls: list[str] = []

    def generate(self, model, prompt, width, height, seed=None, **kw):
        self.calls.append(prompt)
        line = int(prompt.split("#")[1].split()[0])
        outcomes = self.script.get(line, [])
        outcome = outcomes.pop(0) if outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        return GenerationResult(
            image_bytes=PNG_2x1, ext=".png", width=width, height=height,
            model=model.key, model_id=model.id, provider="fake", seed=seed,
            elapsed=0.01, cost_estimate=model.cost_per_image(width, height),
            tiles=M.tile_count(width, height), response_encoding="raw",
        )


def make_batch(tmp: Path, script: dict, **overrides):
    pf = tmp / "p.txt"
    pf.write_text(
        "\r\n".join(f"prompt #{i} of the batch" for i in range(1, 5)),
        encoding="utf-8",
    )
    cfg = BatchConfig(
        prompt_file=pf, output_dir=tmp / "out", model="lightning",
        ratio="1:1", tier="draft", concurrency=1, delay=0.0,
        max_attempts=3, **overrides,
    )
    return BatchEngine(cfg, provider=FakeProvider(script))


def test_content_block_is_never_retried(tmp: Path) -> None:
    eng = make_batch(tmp, {2: [ContentBlocked("filtered")] * 9})
    p = eng.run()
    assert p.blocked == 1, p
    assert p.done == 3, p
    # Exactly ONE call for line 2 — a block must not consume the retry budget.
    assert sum("#2 " in c for c in eng.provider.calls) == 1, eng.provider.calls
    # And retry-failed must leave it alone.
    assert eng.store.requeue_failed(eng.batch_id) == 0
    eng.close()
    print("ok  content block: 1 attempt, permanent, not requeued")


def test_transient_is_retried_then_succeeds(tmp: Path) -> None:
    eng = make_batch(tmp, {3: [TransientError("boom"), TransientError("boom")]})
    p = eng.run()
    assert p.done == 4 and p.failed == 0, p
    assert sum("#3 " in c for c in eng.provider.calls) == 3, eng.provider.calls
    eng.close()
    print("ok  transient: retried twice, then succeeded")


def test_attempts_are_capped(tmp: Path) -> None:
    eng = make_batch(tmp, {1: [TransientError("always")] * 20})
    p = eng.run()
    assert p.failed == 1 and p.done == 3, p
    assert sum("#1 " in c for c in eng.provider.calls) == 3, eng.provider.calls
    # A failed job IS retryable, unlike a blocked one.
    assert eng.store.requeue_failed(eng.batch_id) == 1
    eng.close()
    print("ok  attempts capped at max_attempts, then failed + requeueable")


def _fake_429(body: dict) -> httpx.Response:
    return httpx.Response(
        429, json=body, request=httpx.Request("POST", "https://example.invalid/"),
    )


def test_quota_exhausted_429_is_not_retried() -> None:
    """Code 4006 must be classified as QuotaExhausted, never RateLimited.

    Verbatim body measured 2026-09-05 against the live API.
    """
    body = {
        "code": 4006,
        "message": (
            "AiError: AiError: you have used up your daily free allocation "
            "of 10,000 neurons, please upgrade to Cloudflare's Workers Paid "
            "plan if you would like to continue usage."
        ),
    }
    r = _fake_429({"success": False, "errors": [body], "result": None})
    try:
        CloudflareProvider._raise_for_status(r)
        assert False, "expected QuotaExhausted to be raised"
    except QuotaExhausted:
        pass
    except RateLimited:
        assert False, "4006 must not be classified as a retryable rate limit"
    print("ok  429 code 4006 classified as QuotaExhausted, not RateLimited")


def test_plain_429_is_still_rate_limited() -> None:
    """A 429 WITHOUT code 4006 must keep behaving as an ordinary rate limit."""
    r = _fake_429({"success": False, "errors": [{"code": 10000, "message": "slow down"}]})
    try:
        CloudflareProvider._raise_for_status(r)
        assert False, "expected RateLimited to be raised"
    except QuotaExhausted:
        assert False, "a non-4006 429 must not be classified as quota exhaustion"
    except RateLimited:
        pass
    print("ok  429 without code 4006 still classified as RateLimited")


def test_quota_exhausted_stops_the_batch_without_failing_the_job(tmp: Path) -> None:
    """QuotaExhausted must abort the whole batch, and the job it hit must be
    left `pending` (via release), never marked `failed` — it was never given
    a fair attempt, and the existing resume path must pick it up unchanged.
    """
    eng = make_batch(
        tmp,
        {2: [QuotaExhausted("daily free neuron allowance exhausted")]},
    )
    p = eng.run()
    assert eng.quota_exhausted, "engine must record that quota was exhausted"
    assert p.failed == 0, "the job that hit the wall must not be marked failed"
    # Prompt #1 (line_no 1) legitimately completed before the wall was hit.
    # Prompt #2 (line_no 3) is the one that raised QuotaExhausted, and every
    # job after it was never attempted — all of those must stay pending so
    # the existing resume path picks them up unchanged.
    jobs = sorted(eng.store.jobs(eng.batch_id), key=lambda j: j.line_no)
    assert jobs[0].status == dbmod.DONE, jobs[0]
    assert all(j.status == dbmod.PENDING for j in jobs[1:]), (
        f"jobs from the quota wall onward must stay pending, got "
        f"{[(j.line_no, j.status) for j in jobs]}"
    )
    eng.close()
    print("ok  quota exhaustion stops the batch, job released not failed")


def test_rate_limit_is_retried(tmp: Path) -> None:
    eng = make_batch(tmp, {2: [RateLimited("429", retry_after=0.01)]})
    p = eng.run()
    assert p.done == 4 and p.failed == 0, p
    eng.close()
    print("ok  429: honoured Retry-After and retried")


def test_crash_recovery_refunds_the_attempt(tmp: Path) -> None:
    eng = make_batch(tmp, {})
    eng.prepare()
    job = eng.store.claim_next(eng.batch_id)      # simulate a claimed job
    assert job.attempts == 1
    n = eng.store.reset_running(eng.batch_id)     # simulate the crash + restart
    assert n == 1
    again = eng.store.claim_next(eng.batch_id)
    assert again.attempts == 1, "a crash must not eat the retry budget"
    eng.close()
    print("ok  crash recovery: running reset to pending, attempt refunded")


def test_overwrite_protection(tmp: Path) -> None:
    eng = make_batch(tmp, {})
    eng.run()
    eng.close()
    # Same output dir, fresh database: resume must recognise the files on disk
    # even with no job history at all.
    for db in (tmp / "out").glob(".batchgen.db*"):
        db.unlink()
    eng2 = make_batch(tmp, {})
    p = eng2.run()
    assert p.skipped == 4 and p.done == 0, p
    assert eng2.provider.calls == [], "no API calls when outputs exist"
    eng2.close()
    print("ok  overwrite protection: existing outputs skipped, no calls")


def test_prompt_loader_crlf() -> None:
    """The real test file is CRLF with no trailing newline."""
    lines = P.load_prompts("test_prompts.txt", "STYLE")
    assert len(lines) == 6, len(lines)
    assert all("\r" not in ln.final for ln in lines), "carriage return leaked"
    assert lines[-1].original.startswith("Epic montage"), "last line dropped"
    assert lines[0].final.endswith("STYLE")
    print("ok  prompt loader: 6 lines, no CR, final unterminated line kept")


def test_sizes_are_valid_for_every_model() -> None:
    for spec in M.ALL_MODELS:
        for ratio in M.RATIOS:
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, spec.key)
                errs = spec.validate_size(w, h)
                assert not errs, f"{spec.key} {ratio}/{tier} {w}x{h}: {errs}"
    print("ok  every ratio x tier size is valid for every model")


def test_pricing_matches_published_tables() -> None:
    expect = {"draft": 0.57, "standard": 1.72, "high": 2.29}
    for tier, want in expect.items():
        w, h = M.size_for("16:9", tier, "klein4b")
        got = M.estimate("klein4b", w, h).cost_per_1000
        assert abs(got - want) < 0.01, f"{tier}: {got} != {want}"
    for spec in M.CLOUDFLARE_MODELS[:3]:
        assert M.estimate(spec.key, 1536, 864).cost_per_1000 == 0.0
    assert M.estimate("klein9b", 1536, 864).over_budget
    print("ok  pricing matches the published tier tables")


def test_filenames_are_deterministic_and_safe() -> None:
    a = P.build_filename("test_prompts.txt", 7, "A prompt: with / bad \\ chars!", ".jpg")
    b = P.build_filename("test_prompts.txt", 7, "A prompt: with / bad \\ chars!", ".jpg")
    assert a == b, "filenames must be deterministic"
    assert not set(a) & set('<>:"/\\|?*'), a
    assert a.startswith("test_prompts-007-"), a
    assert P.sanitize_fragment("con") == "con_", "windows reserved name"
    print("ok  filenames deterministic, sanitized, reserved names handled")


def test_filenames_stay_short_and_distinguishing() -> None:
    """Names must stay well inside Windows' 260-character path limit AND
    still tell one image from the next.

    The prompts in a batch typically share a long boilerplate opening and
    differ only at the tail, so a plain head-truncation produces a folder of
    near-identical names. Words are taken from both ends to avoid that.
    """
    prompts = [
        "Distant low angle background of a field at day. Cloudy weather.",
        "Distant low angle background of a forest at dawn. Rainy weather.",
        "Distant low angle background of a desert at dusk. Clear weather.",
        "Distant low angle background of a wasteland at night. Snowy weather.",
    ]
    names = [
        P.build_filename("test_prompts.txt", i, text, ".jpg", corpus=prompts)
        for i, text in enumerate(prompts, start=1)
    ]

    for name in names:
        assert len(name) <= 64, f"{len(name)} chars is too long: {name}"

    # The varying term must survive into the name, or the batch is unreadable.
    for name, word in zip(names, ("cloudy", "rainy", "clear", "snowy")):
        assert word in name, f"{word!r} was dropped from {name}"

    # The SUBJECT must survive too. These four lines differ in subject, time
    # and weather; before the corpus pass only the weather word made it, and
    # at a narrower budget all four names collapsed into one.
    for name, word in zip(names, ("field", "forest", "desert", "wasteland")):
        assert word in name, f"{word!r} was dropped from {name}"

    assert len(set(names)) == len(names), "names collided"

    # Degenerate inputs must not produce an empty or unsafe fragment.
    assert P.sanitize_fragment("!!!", drop_stopwords=True) == "prompt"
    assert P.sanitize_fragment("the of a an", drop_stopwords=True)
    long_word = "z" * 200
    assert len(P.sanitize_fragment(long_word, drop_stopwords=True)) <= \
        P.DEFAULT_FRAGMENT_LEN

    print("ok  filenames compact, collision-free, keep distinguishing words")


def test_a_changed_style_suffix_changes_the_filename() -> None:
    """THE REPORTED BUG (2026-09-13): same prompt + new style = no new image.

    The suffix is part of the image, so it has to be part of the image's
    identity. It was in neither the filename nor find_batch()'s WHERE clause,
    so a rerun reattached to the finished batch, found the old file on disk,
    and skipped -- silently, which read as the program ignoring the new style.
    """
    prompt = "A lighthouse on a cliff"
    a = "Soft painterly illustration, warm light, gentle bloom."
    b = "Harsh neon photography, cold rim light, high contrast."

    def name(suffix):
        return P.build_filename(
            "p.txt", 1, prompt, ".png", style_suffix=suffix,
            hash_parts=P.image_hash_parts(
                final_prompt=f"{prompt} {suffix}", model="lightning",
                width=1024, height=576),
        )

    assert name(a) != name(b), "a changed style suffix must change the filename"
    assert name(a) == name(a), "naming must stay deterministic"
    assert "--" in name(a), "prompt and style need a visible divider"
    # The slug must come from the suffix TEXT, so an edited-but-unsaved preset
    # cannot make the filename assert a style the image does not have.
    assert "painterly" in name(a) and "neon" in name(b)
    print("ok  a changed style suffix changes the filename")


def test_the_hash_covers_every_image_affecting_setting() -> None:
    """Derived, never random: resume rebuilds the name to find the image."""
    base = dict(final_prompt="a cat", model="lightning", width=1024, height=576)
    tag = lambda **kw: P._hash_tag(P.image_hash_parts(**{**base, **kw}))

    assert tag() == tag(), "the hash must be deterministic"
    for field, value in (
        ("final_prompt", "a dog"), ("model", "sdxl"), ("width", 1536),
        ("height", 864), ("negative_prompt", "blurry"), ("guidance", 9.0),
        ("steps", 12), ("prompt_expansion", "raw"), ("content_filter", "off"),
    ):
        assert tag(**{field: value}) != tag(), f"{field} is missing from the hash"

    # The SEED is deliberately absent: including it would mean a random-seed
    # rerun never resumes, since every image would want a new filename.
    parts = P.image_hash_parts(**base)
    assert not any(isinstance(p, int) and p > 10_000 for p in parts[4:]), \
        "a seed must not leak into the filename hash"
    print("ok  the filename hash covers every image-affecting setting but seed")


def test_style_suffix_is_part_of_batch_identity(tmp: Path) -> None:
    """find_batch() must not reattach across a changed style suffix."""
    store = dbmod.JobStore(tmp / "id.db")
    args = dict(source_file="p.txt", output_dir=str(tmp), provider="cloudflare",
                model="lightning", ratio="16:9", tier="standard",
                width=1024, height=576)
    store.create_batch(style_suffix="style A", **args)

    found = store.find_batch("p.txt", str(tmp), "lightning", 1024, 576, "style A")
    assert found is not None, "an identical batch must be reattached to"
    missed = store.find_batch("p.txt", str(tmp), "lightning", 1024, 576, "style B")
    assert missed is None, "a different style suffix must be a different batch"
    store.close()
    print("ok  the style suffix is part of batch identity")


def test_regenerate_requeues_finished_jobs(tmp: Path) -> None:
    """The one thing `overwrite` could never do.

    Overwrite is checked only once a job is RUNNING, and a `done` row is never
    handed out by claim_next() -- so ticking it and rerunning a finished batch
    reached that check on no job at all and generated nothing.
    """
    store = dbmod.JobStore(tmp / "regen.db")
    bid = store.create_batch(
        source_file="p.txt", style_suffix="", output_dir=str(tmp),
        provider="cloudflare", model="lightning", ratio="16:9",
        tier="standard", width=1024, height=576)
    store.add_jobs(bid, [
        {"line_no": i, "original_prompt": f"p{i}", "final_prompt": f"p{i}",
         "provider": "cloudflare", "model": "lightning",
         "width": 1024, "height": 576}
        for i in range(1, 5)
    ])
    for _ in range(4):
        job = store.claim_next(bid)
        assert job is not None
    ids = [j.id for j in store.jobs(bid)]
    store.mark_done(ids[0], "a.png", 1, 0.0)
    store.mark_status(ids[1], dbmod.SKIPPED, "exists")
    store.mark_status(ids[2], dbmod.BLOCKED, "refused")
    store.mark_status(ids[3], dbmod.FAILED, "network")

    # Regenerate covers what the CURRENT settings would generate, not the
    # whole prompt file: prepare() only ever creates job rows for the first
    # `limit` lines, so a 5-of-100 run has 5 rows and Regenerate redoes those
    # 5. The button says "Regenerate" rather than "Regenerate All" because of
    # this -- "All" promised a scope it does not have.
    n = store.requeue_finished(bid)
    assert n == 2, f"done + skipped should requeue, got {n}"
    counts = store.counts(bid)
    assert counts[dbmod.PENDING] == 2
    # Blocked stays blocked: the same text is refused again, at cost.
    assert counts[dbmod.BLOCKED] == 1, "regenerate must not retry blocked jobs"
    # Failed is Retry Failed's job, kept separate so the two actions stay
    # distinct and differently priced.
    assert counts[dbmod.FAILED] == 1, "regenerate must not touch failed jobs"
    store.close()
    print("ok  regenerate requeues finished jobs, never blocked ones")


def test_overwrite_does_not_redo_a_finished_batch(tmp: Path) -> None:
    """Overwrite is a FILE-collision flag, not a regenerate switch.

    Reported by the user 2026-09-13: they ticked Overwrite, pressed Start on a
    finished batch and got "0 pending" with no images. That is correct
    behaviour badly labelled -- `claim_next()` never hands out a `done` row, so
    the overwrite check in `_generate_one` is reached for no job at all.

    This is pinned rather than "fixed" because making Overwrite re-queue
    finished work would silently re-bill a paid batch whenever the box happened
    to be ticked. Regenerate is the explicit, confirmed action instead.
    """
    pf = tmp / "ow.txt"
    pf.write_text("\r\n".join(f"prompt #{i} of the batch" for i in range(1, 5)),
                  encoding="utf-8")
    out = tmp / "out"

    def run(**kw):
        fake = FakeProvider({})
        cfg = BatchConfig(prompt_file=pf, output_dir=out, model="lightning",
                          ratio="1:1", tier="draft", concurrency=1, delay=0.0,
                          **kw)
        with BatchEngine(cfg, provider=fake) as eng:
            eng.prepare()
            eng.run(**{k: v for k, v in kw.items() if k == "regenerate"})
        return len(fake.calls)

    assert run() == 4, "first run should generate everything"
    assert run(overwrite=True) == 0, (
        "overwrite must NOT re-queue finished jobs -- if this starts passing "
        "4, a ticked checkbox silently re-bills the whole batch")
    # Regenerate is the control that actually does it.
    fake = FakeProvider({})
    cfg = BatchConfig(prompt_file=pf, output_dir=out, model="lightning",
                      ratio="1:1", tier="draft", concurrency=1, delay=0.0)
    with BatchEngine(cfg, provider=fake) as eng:
        eng.prepare()
        eng.run(regenerate=True)
    assert len(fake.calls) == 4, "Regenerate must redo the finished batch"
    print("ok  overwrite never redoes a finished batch; Regenerate does")


def test_regenerate_respects_the_generate_slider(tmp: Path) -> None:
    """Regenerate covers the current run, not the whole prompt file.

    Asked directly by the user (2026-09-13), and the answer is yes -- but for
    a reason worth pinning: `limit` is applied in load_lines(), so prepare()
    never creates rows for lines past it. There is nothing else in the batch
    for requeue_finished() to pick up. If limiting ever moved later (to the
    claim, say), a 5-of-100 Regenerate would quietly become 100 images -- on a
    paid model, a 20x bill.
    """
    pf = tmp / "eight.txt"
    pf.write_text("\r\n".join(f"prompt #{i} about a distinct thing {c}"
                              for i, c in enumerate("abcdefgh", start=1)),
                  encoding="utf-8")
    out = tmp / "limited"
    fake = FakeProvider({})
    cfg = BatchConfig(prompt_file=pf, output_dir=out, model="lightning",
                      ratio="1:1", tier="draft", concurrency=1, delay=0.0,
                      limit=3)

    with BatchEngine(cfg, provider=fake) as eng:
        eng.prepare()
        eng.run()
    assert len(fake.calls) == 3, f"limit ignored on the first run: {len(fake.calls)}"

    fake.calls.clear()
    with BatchEngine(cfg, provider=fake) as eng:
        eng.prepare()
        eng.run(regenerate=True)
    assert len(fake.calls) == 3, (
        f"regenerate produced {len(fake.calls)} images for a 3-of-8 run -- "
        "it must never exceed what the current settings would generate")
    assert len(list(out.glob("*.png"))) == 3, "regenerate must replace, not add"
    print("ok  regenerate respects the Generate slider, never the whole file")


def test_limit_takes_the_first_n_prompts(tmp: Path) -> None:
    """The prompt-count slider must cap the RUN, not just the preview.

    Applied in load_lines(), which is the single place prompts enter the
    engine -- so the planner, the cost estimate and the dry run cannot
    disagree about how many images a run will make.
    """
    eng = make_batch(tmp, {}, limit=2)
    lines = eng.load_lines()
    assert len(lines) == 2, f"limit ignored: got {len(lines)} lines"
    # The first two PROMPTS, whatever file lines they sit on -- the fixture is
    # blank-line separated, so line_no is 1 and 3 rather than 1 and 2.
    assert [ln.original for ln in lines] == [
        "prompt #1 of the batch", "prompt #2 of the batch"], (
        "limit must take the FIRST n: resume keys a job on its line number, "
        "so a capped run and a later full run have to share their overlap"
    )

    info = eng.dry_run()
    assert info["jobs"] == 2, f"dry run disagrees with the limit: {info['jobs']}"
    assert len(info["lines"]) == 2

    prog = eng.run()
    assert prog.done == 2, f"expected 2 images, made {prog.done}"
    eng.close()

    # And the un-capped run of the same file reuses those two rather than
    # remaking them -- the reason the cap is a prefix and not a sample.
    eng2 = make_batch(tmp, {})
    prog2 = eng2.run()
    calls = list(eng2.provider.calls)
    eng2.close()

    # Asserted on API CALLS, not on the skipped counter: the reused jobs are
    # already DONE in the reattached batch row, so they are never claimed and
    # never counted as skips. Calls are what would cost money twice.
    assert calls == ["prompt #3 of the batch", "prompt #4 of the batch"], (
        f"a full run must only generate the prompts the test run left, got {calls}"
    )
    assert prog2.done == 4, f"all 4 accounted for, done={prog2.done}"
    print("ok  limit caps the run at the first N and a full run reuses them")


def test_limit_none_and_oversize_mean_everything(tmp: Path) -> None:
    """No limit, or one larger than the file, must generate the whole file."""
    assert len(make_batch(tmp, {}).load_lines()) == 4
    assert len(make_batch(tmp, {}, limit=None).load_lines()) == 4
    assert len(make_batch(tmp, {}, limit=99).load_lines()) == 4
    print("ok  an absent or oversized limit generates the whole file")


def test_length_advice_grades_against_the_model(tmp: Path) -> None:
    """The soft counter must grade against the SELECTED model's budget.

    SD's CLIP encoder caps at 77 tokens (~300 chars) and silently drops the
    rest; klein reads ~512 tokens. The same text is therefore fine on one and
    truncated on the other, which is the entire point of making the limit a
    per-model property rather than one number in the GUI.
    """
    sd = M.get_model("lightning")
    klein = M.get_model("klein4b")
    assert sd.prompt_soft_limit < klein.prompt_soft_limit, (
        "klein must have the larger prompt budget"
    )

    short = "a quiet forest at dawn"
    assert P.length_advice(short, sd.prompt_soft_limit,
                           sd.prompt_hard_limit).level == "ok"

    # Long enough to overflow SD, comfortably inside klein.
    long = "a quiet forest at dawn, " * 30
    assert len(long) > sd.prompt_hard_limit
    assert len(long) < klein.prompt_soft_limit
    assert P.length_advice(long, sd.prompt_soft_limit,
                           sd.prompt_hard_limit).level == "over"
    assert P.length_advice(long, klein.prompt_soft_limit,
                           klein.prompt_hard_limit).level == "ok"

    # The middle band exists so the warning arrives before truncation, not at
    # the moment it happens.
    near = "x" * (sd.prompt_soft_limit + 1)
    assert P.length_advice(near, sd.prompt_soft_limit,
                           sd.prompt_hard_limit).level == "near"

    # Advice only: nothing may mutate or truncate the text.
    adv = P.length_advice(long, sd.prompt_soft_limit, sd.prompt_hard_limit)
    assert adv.chars == len(long), "length_advice must not alter the prompt"
    print("ok  length advice grades per-model and never truncates")


def test_negative_layers_compose_and_dedupe() -> None:
    """Negative presets are stackable layers, joined with duplicates dropped.

    Layers are DESIGNED to overlap -- a quality floor and an anatomy fixer both
    reasonably list "blurry" -- so deduplication is the normal path rather than
    an error case.
    """
    quality = "worst quality, low resolution, blurry, jpeg artifacts"
    anatomy = "bad hands, extra fingers, Blurry, deformed"

    out = P.compose_negative([quality, anatomy])
    terms = P.split_terms(out)

    # Deduplicated case-insensitively...
    assert len(terms) == len(set(t.casefold() for t in terms)), out
    assert terms.count("blurry") == 1, out
    assert "Blurry" not in terms, "first occurrence wins, keeping its casing"

    # ...but nothing is LOST: every distinct term from both layers survives.
    expected = {t.casefold() for t in P.split_terms(quality)} | {
        t.casefold() for t in P.split_terms(anatomy)}
    assert {t.casefold() for t in terms} == expected, out

    # Order is preserved. CLIP weights earlier tokens more heavily, so the
    # order layers were ticked in is a quality lever, not cosmetics.
    assert terms[0] == "worst quality", terms
    assert terms.index("bad hands") > terms.index("jpeg artifacts"), terms

    # Degenerate inputs must not produce stray commas or whitespace.
    assert P.compose_negative([]) == ""
    assert P.compose_negative(["", "  "]) == ""
    assert P.compose_negative(["a,, b ,", ""]) == "a, b"
    print("ok  negative layers compose in order, deduplicated, nothing lost")



# ---------------------------------------------------------------------------
# Cloudflare AI Gateway models (p-image and the families that follow it).
# ---------------------------------------------------------------------------

def _fake_json_200(body: dict) -> httpx.Response:
    return httpx.Response(
        200, json=body,
        request=httpx.Request("POST", "https://example.invalid/"),
    )


def test_gateway_data_uri_and_bare_base64_both_decode() -> None:
    """result.image is a data: URI on gateway models and BARE base64 on klein
    -- the same field path carrying two different shapes.

    This is the trap the whole p-image implementation turns on: decoding a
    data URI as bare base64 does not raise, it yields garbage. Both shapes
    must come back as the identical original bytes.
    """
    import base64 as _b64

    raw = _b64.b64encode(PNG_2x1).decode()
    pimage = M.get_model("p-image")
    klein = M.get_model("klein4b")

    # Gateway shape: data URI, plus the `state` field klein does not have.
    r = _fake_json_200(
        {"state": "Completed", "result": {"image": "data:image/jpeg;base64," + raw}}
    )
    got = CloudflareProvider._extract_image(r, pimage)
    assert got == PNG_2x1, "data: URI did not decode back to the original bytes"

    # Native klein shape: bare base64, no state field.
    r2 = _fake_json_200({"result": {"image": raw}})
    got2 = CloudflareProvider._extract_image(r2, klein)
    assert got2 == PNG_2x1, "bare base64 regressed"

    # And the prefix strip must be driven by the CONTENT, not the declared
    # encoding -- a data URI arriving on klein's spec must still decode.
    r3 = _fake_json_200({"result": {"image": "data:image/png;base64," + raw}})
    assert CloudflareProvider._extract_image(r3, klein) == PNG_2x1
    print("ok  gateway data: URI and bare base64 both decode to the same bytes")


def test_gateway_incomplete_state_is_transient() -> None:
    """A state other than Completed must not be treated as a success.

    Only "Completed" is documented; anything else is unknown territory and
    retrying is the safe reading, not shipping whatever was in result.image.
    """
    import base64 as _b64
    raw = _b64.b64encode(PNG_2x1).decode()
    r = _fake_json_200(
        {"state": "Failed", "result": {"image": "data:image/jpeg;base64," + raw}}
    )
    try:
        CloudflareProvider._extract_image(r, M.get_model("p-image"))
        assert False, "a non-Completed state must not be accepted"
    except TransientError:
        pass
    print("ok  gateway non-Completed state raises TransientError")


def test_gateway_402_is_quota_not_bad_request() -> None:
    """402 means no prepaid credit -- fatal for the batch, never retried.

    Gateway models bill from prepaid credit rather than the daily free neuron
    allowance, so this is a distinct state the native models never produce.
    """
    r = httpx.Response(
        402,
        json={"success": False,
              "errors": [{"code": 5001, "message": "Insufficient balance"}]},
        request=httpx.Request("POST", "https://example.invalid/"),
    )
    try:
        CloudflareProvider._raise_for_status(r)
        assert False, "expected QuotaExhausted"
    except QuotaExhausted as e:
        assert "credit" in str(e).lower(), "the message must explain prepaid credit"
    print("ok  gateway 402 classified as QuotaExhausted with a credit message")


def test_gateway_7003_is_permanent_and_named() -> None:
    """Gateway validation errors (7003) are permanent, like native 5006."""
    r = httpx.Response(
        400,
        json={"success": False,
              "errors": [{"code": 7003, "message": "invalid field 'steps'"}]},
        request=httpx.Request("POST", "https://example.invalid/"),
    )
    try:
        CloudflareProvider._raise_for_status(r)
        assert False, "expected PermanentError"
    except QuotaExhausted:
        assert False, "7003 is a bad request, not quota exhaustion"
    except PermanentError as e:
        assert "7003" in str(e), "the gateway code should be named in the message"
    print("ok  gateway 400/7003 classified as a named PermanentError")


def test_gateway_payload_shape() -> None:
    """The model id goes in the BODY, not the URL path, and p-image needs
    aspect_ratio='custom' before width/height are honoured at all."""
    pimage = M.get_model("p-image")
    body = CloudflareProvider._gateway_payload(pimage, "a cat", 1280, 720, 4242)
    assert body["model"] == "pruna/p-image", body
    inp = body["input"]
    assert inp["prompt"] == "a cat"
    assert inp["aspect_ratio"] == "custom", (
        "width/height are ignored unless aspect_ratio is 'custom'"
    )
    assert inp["width"] == 1280 and inp["height"] == 720
    assert inp["seed"] == 4242
    # Fields the model does not accept must never be sent.
    for banned in ("negative_prompt", "guidance", "num_steps", "steps"):
        assert banned not in inp, banned + " must not be sent to p-image"
    print("ok  gateway payload puts the model in the body, sends no illegal fields")


def test_gateway_pricing_is_flat_and_tiles_are_suppressed() -> None:
    """Gateway models bill per IMAGE, not per tile.

    The tile count is the native billing unit and is meaningless here; showing
    it would imply the 'generate large, downscale locally' headroom that these
    models do not have.
    """
    small = M.estimate("p-image", 512, 512, 1)
    large = M.estimate("p-image", 1440, 1440, 1)
    assert small.cost_per_image == large.cost_per_image, (
        "flat pricing must not vary with size"
    )
    assert abs(small.cost_per_1000 - 5.00) < 1e-9, small.cost_per_1000
    assert small.bills_per_tile is False
    assert small.free_images_per_day is None, (
        "gateway models draw on prepaid credit, not the free neuron allowance"
    )
    # The native models must be untouched by all of this.
    k = M.estimate("klein4b", 1536, 864, 1)
    assert k.bills_per_tile is True and k.free_images_per_day is not None
    print("ok  gateway pricing is flat, tiles and free-allowance suppressed")


def test_cost_tier_markers_match_the_decided_scheme() -> None:
    """The five cost bands, and the markers derived from them.

    REVISED 2026-09-05 from three bands to five. The old scheme said only
    "free / within $5 / within $50 / above", which lumped a $15 model in with
    a $50 one and described everything above $5 as "over budget" -- this
    project's internal policy rather than a fact about the price. Thresholds
    are now the user's: LOW <= $5, MEDIUM <= $20, HIGH <= $50, EXTREME above.

    Bounds are INCLUSIVE, so a model sitting exactly on a round number lands
    in the cheaper band. p-image at exactly $5.00 is the live case.
    """
    assert M.cost_band("lightning") == "free"
    assert M.cost_band("poll-flux") == "free"
    assert M.cost_band("klein4b") == "low"          # $1.72
    assert M.cost_band("p-image") == "low"          # exactly $5.00, inclusive
    assert M.cost_band("klein9b") == "medium"       # $16.94
    assert M.cost_band("krea-turbo") == "medium"    # $15.00
    assert M.cost_band("krea-medium") == "high"     # $30.00
    assert M.cost_band("recraft-utility") == "high" # $35.00
    assert M.cost_band("nano-banana-2") == "extreme"

    # The marker is a VIEW over the band, never a parallel calculation --
    # that is what stops the dropdown and the cost calculator disagreeing.
    for spec in M.ALL_MODELS:
        assert (M.cost_tier_marker(spec.key)
                == M.COST_BAND_MARKERS[M.cost_band(spec.key)])

    # Boundaries, checked directly rather than via whichever model happens to
    # sit near one today.
    assert M.cost_band_for_price(0) == "free"
    assert M.cost_band_for_price(5.00) == "low"
    assert M.cost_band_for_price(5.01) == "medium"
    assert M.cost_band_for_price(20.00) == "medium"
    assert M.cost_band_for_price(20.01) == "high"
    assert M.cost_band_for_price(50.00) == "high"
    assert M.cost_band_for_price(50.01) == "extreme"

    # Every band must have a label and a style, or the GUI raises a KeyError
    # on a model nobody thought to click.
    for band in M.COST_BAND_LABELS:
        assert M.COST_BAND_LABELS[band]
        assert band in M.COST_BAND_STYLES
        assert band in M.COST_BAND_MARKERS

def test_pimage_sizes_respect_its_own_cap() -> None:
    """p-image caps at 1440 AND requires multiples of 16 -- and the x16 rule is
    the binding one at 16:9, where 1440x810 is illegal because 810 is not a
    multiple of 16. Its best 16:9 is 1280x720, SMALLER than the program's
    Standard 16:9, so it gets its own table rather than a High substitution."""
    spec = M.get_model("p-image")
    for ratio in M.RATIOS:
        for tier in M.TIERS:
            w, h = M.size_for(ratio, tier, "p-image")
            assert not spec.validate_size(w, h), (
                "%s/%s = %dx%d is illegal for p-image" % (ratio, tier, w, h)
            )
            assert w % 16 == 0 and h % 16 == 0, "%dx%d is not a multiple of 16" % (w, h)
            assert max(w, h) <= 1440, "%dx%d exceeds p-image's 1440 cap" % (w, h)
    assert M.size_for("16:9", "standard", "p-image") == (1280, 720)
    # The native models keep the tile-optimal table untouched.
    assert M.size_for("16:9", "standard", "klein4b") == (1536, 864)
    assert M.size_for("16:9", "high", "klein4b") == (1792, 1008)
    print("ok  p-image sizes respect its 1440 cap and the x16 rule")



def test_krea_returns_a_url_not_bytes() -> None:
    """krea's result.image is a PRESIGNED URL, not image data.

    It must come back as the _PresignedURL marker so the caller knows a second
    GET is needed. Returning it as ordinary bytes would write a text file full
    of a URL and call it a PNG.
    """
    from core.providers.cloudflare import _PresignedURL

    url = "https://examples.aig.cloudflare.com/krea/krea-2-medium/default.png"
    r = _fake_json_200({"state": "Completed", "result": {"image": url}})
    got = CloudflareProvider._extract_image(r, M.get_model("krea-turbo"))
    assert isinstance(got, _PresignedURL), type(got)
    assert str(got) == url
    print("ok  krea result.image comes back as a presigned-URL marker")


def test_presigned_fetch_never_sends_the_api_token() -> None:
    """The signed URL must be fetched WITHOUT the Authorization header.

    The URL already carries its own signature, and forwarding the Cloudflare
    token to whatever host it points at would leak the credential to a third
    party. This is a security property, not a preference.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return httpx.Response(200, content=PNG_2x1)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    prov = CloudflareProvider(account_id="acct", api_token="SECRET-TOKEN",
                              client=client)
    data = prov._fetch_presigned("https://signed.example/img.png", 30.0)
    assert data == PNG_2x1
    joined = " ".join(f"{k}: {v}" for k, v in seen["headers"].items())
    assert "SECRET-TOKEN" not in joined, (
        "the API token must never be sent to a presigned URL host: " + joined
    )
    assert "authorization" not in {k.lower() for k in seen["headers"]}
    print("ok  presigned fetch sends no Authorization header")


def test_presigned_fetch_failures_are_transient() -> None:
    """A failed fetch means a PAID image was lost, so it must be retryable.

    The image was generated and billed before the URL was handed over. Marking
    this permanent would throw away an image the user has already paid for.
    """
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    prov = CloudflareProvider(
        account_id="a", api_token="t",
        client=httpx.Client(transport=httpx.MockTransport(fail)),
    )
    try:
        prov._fetch_presigned("https://signed.example/img.png", 5.0)
        assert False, "expected TransientError"
    except TransientError as e:
        assert "billed" in str(e).lower(), (
            "the message should say the image was already paid for"
        )

    # A non-HTTPS URL is a different matter: refuse it outright rather than
    # downgrading the connection.
    try:
        prov._fetch_presigned("http://signed.example/img.png", 5.0)
        assert False, "expected PermanentError for a plaintext URL"
    except PermanentError:
        pass
    print("ok  presigned fetch failures are transient; plaintext URLs refused")


def test_krea_payload_uses_the_ratio_enum_not_pixels() -> None:
    """krea takes aspect_ratio + resolution and REJECTS width/height.

    Both fields are required, so neither may be omitted, and the pixels the
    rest of the app carries around must not leak into the request.
    """
    spec = M.get_model("krea-turbo")
    for ratio in M.RATIOS:
        w, h = M.size_for(ratio, "standard", "krea-turbo")
        body = CloudflareProvider._gateway_payload(spec, "a cat", w, h, 7)
        inp = body["input"]
        assert body["model"] == "krea/krea-2-medium-turbo"
        assert inp["aspect_ratio"] == ratio, (ratio, inp["aspect_ratio"])
        assert inp["resolution"] == "1K", "1K is the only accepted value"
        assert inp["seed"] == 7
        for banned in ("width", "height", "negative_prompt", "guidance",
                       "num_steps", "steps"):
            assert banned not in inp, banned + " must not be sent to krea"
    print("ok  krea payload sends the ratio enum and 1K, never pixels")


def test_krea_has_no_tier_ladder() -> None:
    """krea is locked to 1K, so every tier is the same size.

    The UI needs this to be detectable -- a tier dropdown that silently does
    nothing reads as a bug rather than as a model limitation.
    """
    assert M.has_tier_ladder("krea-turbo") is False
    assert M.has_tier_ladder("krea-medium") is False
    # The models that DO have a ladder must still report one.
    assert M.has_tier_ladder("klein4b") is True
    assert M.has_tier_ladder("lightning") is True
    assert M.has_tier_ladder("p-image") is True
    for ratio in M.RATIOS:
        sizes = {M.size_for(ratio, t, "krea-turbo") for t in M.TIERS}
        assert len(sizes) == 1, (ratio, sizes)
    print("ok  krea reports no tier ladder; the others still do")


def test_krea_pair_prices_and_markers() -> None:
    """The pair ships by decision. Turbo is half the price of medium, and both
    are $$ -- above the ceiling, within tolerance."""
    turbo = M.estimate("krea-turbo", *M.size_for("16:9", "standard", "krea-turbo"))
    med = M.estimate("krea-medium", *M.size_for("16:9", "standard", "krea-medium"))
    assert abs(turbo.cost_per_1000 - 15.00) < 1e-9, turbo.cost_per_1000
    assert abs(med.cost_per_1000 - 30.00) < 1e-9, med.cost_per_1000
    assert med.cost_per_1000 == 2 * turbo.cost_per_1000
    assert M.cost_tier_marker("krea-turbo") == "$$"      # MEDIUM, $15
    assert M.cost_tier_marker("krea-medium") == "$$$"    # HIGH, $30
    for e in (turbo, med):
        assert e.over_budget, "both are above the $5/1000 ceiling"
        assert e.bills_per_tile is False
        assert e.free_images_per_day is None
    print("ok  krea pair priced $15/$30 per 1000, both marked $$")



def test_prompt_expansion_is_always_sent_and_matches_the_vendor_default() -> None:
    """`creativity` must be sent ALWAYS -- its API default is not neutral.

    That half is unchanged and is the important one: staying silent means
    accepting whatever krea decides, and this program's contract is that the
    request says what it wants.

    CHANGED 2026-09-06: the program default moved from "raw" (expansion off)
    to "medium", matching krea's own documented default. The original "raw"
    rested on a misreading -- extra units in one image were attributed to
    expansion rewriting the prompt, but the sidecar showed `creativity: raw`
    was sent and the prompt went through untouched. Krea's docs also state
    that a DETAILED prompt is polished rather than restructured, so the
    style-suffix drift that motivated "raw" does not apply at the prompt
    lengths this program sends.

    Not "high": that level takes deliberate liberty with style and mood, which
    a batch wants held constant across images.
    """
    spec = M.get_model("krea-turbo")
    w, h = M.size_for("16:9", "standard", "krea-turbo")

    inp = CloudflareProvider._gateway_payload(spec, "a cat", w, h, 1)["input"]
    assert "creativity" in inp, (
        "creativity must be sent explicitly -- omitting it accepts krea's own "
        "default silently, which is the whole reason this field is exposed"
    )
    assert inp["creativity"] == M.DEFAULT_PROMPT_EXPANSION
    assert M.DEFAULT_PROMPT_EXPANSION == "medium", (
        "the program default should match krea's documented API default"
    )
    assert M.DEFAULT_PROMPT_EXPANSION == M.KREA_API_DEFAULT_EXPANSION
    assert M.DEFAULT_PROMPT_EXPANSION != "high", (
        "high takes creative liberty with style and mood -- wrong for a batch"
    )

    # An explicit mode is honoured, including turning expansion off.
    for mode in M.PROMPT_EXPANSION_MODES:
        got = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, mode)["input"]
        assert got["creativity"] == mode, (mode, got)

    # An unknown mode is a permanent error, never sent.
    try:
        CloudflareProvider._gateway_payload(spec, "a cat", w, h, 1, "wild")
        assert False, "expected PermanentError for an unknown mode"
    except PermanentError:
        pass
    print("ok  prompt expansion is always sent and matches the vendor default")


def test_prompt_expansion_is_only_sent_where_supported() -> None:
    """Models that do not rewrite prompts must never receive `creativity`.

    Callers pass the setting unconditionally, so the spec flag -- not the
    caller -- decides whether it reaches the wire.
    """
    pimage = M.get_model("p-image")
    assert pimage.supports_prompt_expansion is False
    inp = CloudflareProvider._gateway_payload(
        pimage, "a cat", 1280, 720, 1, "high")["input"]
    assert "creativity" not in inp, (
        "p-image does not accept creativity and must not be sent it"
    )
    for key in ("lightning", "klein4b", "poll-flux"):
        assert M.get_model(key).supports_prompt_expansion is False, key
    assert M.get_model("krea-medium").supports_prompt_expansion is True
    print("ok  creativity is sent only to models that support it")


def test_flux2pro_takes_true_pixels_on_the_shared_size_table() -> None:
    """It is the ONLY wishlist model with pixel-exact control, so the program's
    own SIZES table maps onto it directly rather than needing an override.

    Minimum 64, no multiple-of-16 rule (1537 was accepted in the zero-cost
    field probe). Every size the program can ask for clears both, which is
    why flux2pro has no SIZE_TABLE_OVERRIDES entry -- if one ever appears,
    this test says why it should not have."""
    spec = M.get_model("flux2pro")
    assert spec.size_style == "pixels"
    assert spec.min_dimension == 64
    assert spec.multiple_of_16 is False
    assert "flux2pro" not in M.SIZE_TABLE_OVERRIDES, (
        "flux2pro takes true pixels; it must not own a substituted size table"
    )
    assert M.has_tier_ladder("flux2pro"), "Draft/Standard/High all differ here"

    for ratio in M.RATIOS:
        seen = set()
        for tier in M.TIERS:
            w, h = M.resolve_size("flux2pro", ratio, tier)
            assert (w, h) == M.SIZES[ratio][tier], (ratio, tier, w, h)
            assert min(w, h) >= 64, (ratio, tier, w, h)
            seen.add((w, h))
        assert len(seen) == 3, f"{ratio} should differ at every tier"

    # A size below the minimum is a PERMANENT error, never a retry.
    assert spec.validate_size(32, 32), "32px is under the 64px minimum"
    # ...but an odd, non-multiple-of-16 size is fine here, unlike klein.
    assert spec.validate_size(1537, 865) == []
    print("ok  flux2pro takes true pixels on the shared size table")


def test_flux2pro_is_a_gateway_model_priced_flat_at_30() -> None:
    """Same gateway shape as p-image and krea: id in the BODY, flat per-image
    price, no neuron allowance, and a presigned URL back."""
    spec = M.get_model("flux2pro")
    assert spec.call_style == "gateway"
    assert spec.id == "black-forest-labs/flux-2-pro-preview"
    assert spec.bills_per_tile is False
    # CONFIRMED from Cloudflare's published schema 2026-09-05: result.image is
    # declared `format: uri`, so this is krea's shape, NOT p-image's data URI
    # and NOT klein's bare base64. Three incompatible shapes, one field path.
    assert spec.response_encoding == "json_url"

    w, h = M.size_for("16:9", "standard", "flux2pro")
    est = M.estimate("flux2pro", w, h)
    assert abs(est.cost_per_1000 - 30.00) < 1e-9, est.cost_per_1000
    assert M.cost_tier_marker("flux2pro") == "$$$"       # HIGH, $30
    assert est.over_budget, "above the $5/1000 ceiling"
    assert est.free_images_per_day is None, (
        "gateway models draw on prepaid credit, not the neuron allowance"
    )

    # Flat means FLAT: Draft costs exactly what High costs.
    costs = {M.estimate("flux2pro", *M.size_for("16:9", t, "flux2pro")).cost_per_image
             for t in M.TIERS}
    assert len(costs) == 1, f"flat pricing must not vary by tier: {costs}"
    print("ok  flux2pro is a gateway model priced flat at $30/1000")


def test_safety_tolerance_5_is_the_permissive_end_not_0() -> None:
    """THE DIRECTION IS THE WHOLE POINT.

    safety_tolerance runs 0 = STRICTEST to 5 = MOST PERMISSIVE, which reads
    backwards from what a "tolerance" dial usually implies. Sending 0 for the
    permissive mode would make the filter MAXIMALLY AGGRESSIVE -- the exact
    opposite of the intent, and it would look like the model refusing more
    prompts rather than like a configuration bug.

    Doc-derived from Cloudflare's schema, not measured. This test pins the
    direction so a later edit cannot silently invert it."""
    assert M.SAFETY_TOLERANCE_MIN == 0        # strictest
    assert M.SAFETY_TOLERANCE_MAX == 5        # most permissive
    assert M.SAFETY_TOLERANCE_API_DEFAULT == 2

    spec = M.get_model("flux2pro")
    assert spec.content_filter_field == "safety_tolerance"

    field, value = M.filter_value_for(spec, "permissive")
    assert field == "safety_tolerance"
    assert value == 5, (
        "5 is the PERMISSIVE end. 0 would be the strictest possible setting."
    )
    assert M.filter_value_for(spec, "off")[1] == 5
    print("ok  safety_tolerance 5 is the permissive end, not 0")


def test_content_filter_default_sends_nothing_at_all() -> None:
    """"Provider default" is expressed by SILENCE, not by pinning today's
    documented default value.

    This is the opposite call from krea's `creativity`, and deliberately so.
    creativity is sent always because its API default ("low") is NOT neutral --
    staying silent would accept a prompt rewrite the user never asked for.
    A content filter's provider default IS the neutral choice: it is what the
    user gets everywhere else in the lineup, and pinning the number 2 would
    freeze the program to today's value if the provider ever moved it."""
    for key in ("flux2pro", "p-image"):
        spec = M.get_model(key)
        w, h = M.size_for("16:9", "standard", key)
        assert M.filter_value_for(spec, "default") is None
        # None is NOT the same as "default": it means "the caller expressed no
        # preference", which resolves to the PROGRAM's default (permissive).
        # Only the explicit "default" mode sends nothing.
        assert M.filter_value_for(spec, None) is not None
        inp = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, None, "default")["input"]
        assert spec.content_filter_field not in inp, (
            f"{key} must send nothing at all on the default mode"
        )

    # But "default" is NOT the program's default mode. DECIDED 2026-09-05:
    # this is a BATCH tool, so a spurious refusal costs a slot in an overnight
    # run rather than a rerun, and these two models are the only lever against
    # a refusal that is otherwise invisible (HTTP 200 and a black frame). The
    # program therefore ships asking for the loosest setting each model offers.
    assert M.DEFAULT_CONTENT_FILTER == "permissive"
    for key in ("flux2pro", "p-image"):
        spec = M.get_model(key)
        w, h = M.size_for("16:9", "standard", key)
        # Passing None -- what every caller does when the user has not chosen --
        # must land on permissive, not on silence.
        inp = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, None, None)["input"]
        assert spec.content_filter_field in inp, (
            f"{key} must be sent its filter field by default"
        )
    print("ok  'default' sends nothing, but the program defaults to permissive")


def test_both_filter_controls_get_the_same_treatment() -> None:
    """One program-level setting drives two completely different fields.

    p-image speaks a BOOLEAN (disable_safety_checker); flux-2-pro speaks an
    INTEGER 0-5 (safety_tolerance). The GUI and CLI carry one three-mode
    setting and never have to know which field a given model speaks -- that
    mapping lives in core.models, which is the single source of truth."""
    pimage = M.get_model("p-image")
    assert pimage.content_filter_field == "disable_safety_checker"
    field, value = M.filter_value_for(pimage, "permissive")
    assert field == "disable_safety_checker"
    assert value is True, "the boolean's permissive value is True (checker off)"

    inp = CloudflareProvider._gateway_payload(
        pimage, "a cat", 1280, 720, 1, None, "permissive")["input"]
    assert inp["disable_safety_checker"] is True
    assert "safety_tolerance" not in inp, "wrong field for this model"

    inp = CloudflareProvider._gateway_payload(
        M.get_model("flux2pro"), "a cat", 1536, 864, 1, None, "permissive"
    )["input"]
    assert inp["safety_tolerance"] == 5
    assert "disable_safety_checker" not in inp, "wrong field for this model"

    # Models with no lever never receive either field, however the caller asks.
    for key in ("krea-turbo", "krea-medium"):
        spec = M.get_model(key)
        assert spec.content_filter_field == ""
        w, h = M.size_for("16:9", "standard", key)
        got = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, None, "permissive")["input"]
        for banned in ("safety_tolerance", "disable_safety_checker"):
            assert banned not in got, f"{key} must not be sent {banned}"

    # An unknown mode is a permanent error, never quietly sent.
    try:
        CloudflareProvider._gateway_payload(
            M.get_model("flux2pro"), "a cat", 1536, 864, 1, None, "loose")
        assert False, "expected PermanentError for an unknown filter mode"
    except PermanentError:
        pass
    print("ok  both filter controls share one setting, mapped per model")


def test_output_format_wire_spelling_is_jpeg_not_jpg() -> None:
    """flux-2-pro says "jpeg"; nano-banana will say "jpg". Same format, two
    spellings, and writing the string out by hand at a call site is exactly
    how that ships as a bug.

    output_format also has a NON-NEUTRAL default on this model (it defaults to
    jpeg, silently picking a lossy format), so it is sent explicitly -- the
    same lesson krea's `creativity` taught."""
    spec = M.get_model("flux2pro")
    assert spec.output_format_vocab == "jpeg"
    assert spec.output_format == "jpg", (
        "the SPEC stores the program's internal spelling, which also drives "
        "the dropdown and the file extension"
    )
    assert M.wire_output_format(spec) == "jpeg", (
        "the WIRE value is 'jpeg' on this model -- not 'jpg'"
    )

    inp = CloudflareProvider._gateway_payload(
        spec, "a cat", 1536, 864, 1)["input"]
    assert inp["output_format"] == "jpeg"

    # Models that do not accept the field are never sent it.
    for key in ("p-image", "krea-turbo", "krea-medium"):
        other = M.get_model(key)
        assert other.output_format_vocab == ""
        assert M.wire_output_format(other) is None
        w, h = M.size_for("16:9", "standard", key)
        got = CloudflareProvider._gateway_payload(
            other, "a cat", w, h, 1)["input"]
        assert "output_format" not in got, f"{key} does not accept output_format"
    print("ok  output_format is sent as 'jpeg', and only where accepted")


def test_reference_fields_are_never_sent_to_the_models_that_cannot_serve_them() -> None:
    """NARROWED 2026-09-19, and narrowed is the whole point — not deleted.

    This test used to assert that NO model ever receives a reference-image
    field, on the ruling that they were a permanent skip. That ruling was
    PARTIALLY REVERSED after measurement: klein, nano-banana and flux-2-pro
    take a local file, and now do.

    Three models still cannot, and each for a measured reason rather than a
    preference -- krea refuses a data: URI outright ("Must be an HTTP(S)
    URL") and would need the user's art hosted publicly; Recraft has no
    reference field at all (`controls` holds only colors/background_color);
    p-image has none either. Deleting this test rather than narrowing it
    would silently stop guarding them, which is why it is still here.
    """
    banned = ("styles", "image_style_references", "moodboards",
              "image_input", "input_images",
              # Recraft: `controls` is skipped wholesale rather than sent
              # partially, and the old note claiming a `controls.image`
              # existed was wrong about the shape though right about the
              # conclusion.
              "controls", "image")
    excluded = ("krea-turbo", "krea-medium", "p-image", *RECRAFT_MODELS)
    # The exclusion list is not written twice: core.models records WHY each
    # one is out, and this asserts the two agree.
    assert set(excluded) == set(M.REFERENCE_IMAGE_EXCLUSIONS), (
        "the excluded models here and REFERENCE_IMAGE_EXCLUSIONS disagree")

    ref = _prepared_reference(64, 64)
    for key in excluded:
        spec = M.get_model(key)
        assert spec.reference_field is None, (
            f"{key} is recorded as unable to take a reference image, but its "
            f"spec names a reference_field")
        w, h = M.size_for("16:9", "standard", key)
        # Handed one ANYWAY: a caller passes it unconditionally, exactly as
        # it does prompt_expansion and content_filter, so the gate has to
        # hold here rather than at the call site.
        inp = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, reference=ref)["input"]
        for field in banned:
            assert field not in inp, f"{key} must not send {field}"
    print("ok  reference fields never reach krea, Recraft or p-image")


# ---------------------------------------------------------------------------
# Style reference image (added 2026-09-19).
#
# Everything here is OFFLINE and synthetic: Pillow images built in memory,
# no network, no API. The one thing that genuinely needed the live API --
# what klein accepts -- was measured once and is recorded in core/reference.py
# rather than re-probed on every test run.
# ---------------------------------------------------------------------------

def _pixel_art(w: int = 32, h: int = 32):
    """A flat-block image: four colours, hard edges, no gradient."""
    from PIL import Image

    im = Image.new("RGB", (w, h))
    px = im.load()
    block = max(1, min(w, h) // 4)
    palette = [(0, 0, 0), (220, 50, 50), (40, 190, 90), (240, 220, 120)]
    for y in range(h):
        for x in range(w):
            px[x, y] = palette[((x // block) + (y // block)) % 4]
    return im


def _photo(w: int = 512, h: int = 512):
    """A smooth gradient: tens of thousands of colours, no flat blocks."""
    from PIL import Image

    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 255) // w, (y * 255) // h, (x + y) % 256)
    return im


def _write(tmp, im, name="ref.png"):
    path = Path(tmp) / name
    im.save(path)
    return path


def _prepared_reference(w: int = 64, h: int = 64):
    """A PreparedReference without touching the filesystem."""
    import io as _io

    buf = _io.BytesIO()
    _pixel_art(w, h).save(buf, format="PNG")
    return R.PreparedReference(
        path=Path("synthetic.png"), data=buf.getvalue(),
        width=w, height=h, source_width=w, source_height=h,
        source_format="png", resampler="", resampler_reason="test",
        transform="none", scale_factor=1.0, detected_pixel_art=True,
    )


def test_reference_image_helpers_are_derived_from_the_registry() -> None:
    """No model list may be hardcoded outside core.models.

    supports_reference_image() is to this feature what cost_band() is to
    pricing: the ONE place the question is answered. A list written into the
    GUI, the CLI or the engine is a second source of truth that drifts the
    moment a model is added.
    """
    supported = {m.key for m in M.models_supporting_reference_image()}
    assert supported == {"klein4b", "klein9b", "flux2pro",
                         "nano-banana-2-lite", "nano-banana-2"}
    for key in supported:
        assert M.supports_reference_image(key)
        spec = M.get_model(key)
        # A field with no encoding cannot be sent, and an encoding with no
        # field has nothing to send. Neither half is optional.
        assert spec.reference_encoding in ("multipart", "base64"), key
    for key in M.REFERENCE_IMAGE_EXCLUSIONS:
        assert not M.supports_reference_image(key)
    # The prose list is built from the registry, so a model added later
    # appears in every user-facing message without anyone remembering to.
    sentence = M.reference_models_sentence()
    for key in supported:
        assert M.get_model(key).short_name in sentence
    print("ok  reference capability is derived from the registry, not listed")


def test_only_one_reference_is_sent_and_always_at_index_zero() -> None:
    """One image, at index 0, on every model that takes one.

    Both families accept several (klein `input_image_0..3`, nano-banana and
    flux-2-pro a list). Multi-image and per-image strength are single-image
    EDITING features; this is a batch STYLE lever, by decision.
    """
    ref = _prepared_reference()
    for key in ("nano-banana-2-lite", "nano-banana-2", "flux2pro"):
        spec = M.get_model(key)
        w, h = M.size_for("16:9", "standard", key)
        inp = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 1, reference=ref)["input"]
        sent = inp[spec.reference_field]
        assert isinstance(sent, list), f"{key} must send a list"
        assert len(sent) == 1, f"{key} sent {len(sent)} references, not 1"
        assert sent[0].startswith("data:image/png;base64,"), key
    print("ok  exactly one reference is sent, at index 0")


def test_klein_sends_the_reference_as_a_multipart_part() -> None:
    """klein is the primary target and its path is the multipart one.

    MEASURED 2026-09-19: one more form part carrying the raw bytes with a
    filename and a content-type. Checked through the real request builder
    rather than by inspecting a dict, because the multipart branch is inside
    generate() and a unit test of a helper would not have caught a wiring
    mistake there.
    """
    ref = _prepared_reference()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["type"] = request.headers.get("content-type", "")
        return httpx.Response(
            200, json={"result": {"image": base64.b64encode(
                PNG_2x1).decode("ascii")}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    prov = CloudflareProvider(account_id="acct", api_token="tok", client=client)
    spec = M.get_model("klein4b")
    w, h = M.size_for("16:9", "standard", "klein4b")
    try:
        prov.generate(spec, "a cat", w, h, seed=1, reference=ref)
    except Exception:
        # The response decode is not what is under test here; the request is.
        pass
    assert "multipart/form-data" in captured["type"]
    body = captured["body"]
    assert b'name="input_image_0"' in body, "klein must send input_image_0"
    assert b"image/png" in body
    assert ref.data in body, "the prepared BYTES must be the part's content"
    # And never a second one.
    assert b'name="input_image_1"' not in body
    print("ok  klein sends the reference as one multipart part")


def test_the_64px_floor_is_enforced_per_side_client_side(tmp) -> None:
    """64x48 must be corrected BEFORE it is sent, not sent and refused.

    MEASURED 2026-09-19: the floor binds on EACH DIMENSION, not on the total
    or the longest edge -- 63x63 rejected, 64x64 accepted, 64x48 rejected.
    And the rejection is a generic HTTP 400 naming neither the field nor the
    size, so a user who sends one gets an unexplainable failure on every line
    of the batch unless the program catches it here.
    """
    path = _write(tmp, _pixel_art(64, 48))
    prepared = R.prepare(path)
    assert prepared.width >= R.MIN_DIMENSION
    assert prepared.height >= R.MIN_DIMENSION, (
        "48 is under the floor even though 64 is over it — the floor is "
        "per side")
    assert prepared.transform == "upscale"
    # The provider's own guard agrees, so a reference prepared for one model
    # cannot slip past on another with different limits.
    spec = M.get_model("klein4b")
    CloudflareProvider._validate_reference(spec, prepared)
    tiny = _prepared_reference(64, 64)
    tiny.height = 48
    try:
        CloudflareProvider._validate_reference(spec, tiny)
        raise AssertionError("a 64x48 reference must be refused, not sent")
    except PermanentError as e:
        assert "48" in str(e) and "each side" in str(e)
    print("ok  the 64px floor is enforced per side, before the request")


def test_upscale_is_nearest_and_downscale_is_lanczos(tmp) -> None:
    """The resampler choice is load-bearing and must be pixel-art aware.

    An image is upscaled only because it is BELOW the 64px floor, which means
    it is tiny, which means it is almost certainly pixel art -- and smooth
    resampling blurs the hard edges that are the entire style being
    referenced. The upscale must also be an INTEGER factor, or a fractional
    scale reintroduces exactly the blur NEAREST was chosen to avoid.
    """
    small = R.prepare(_write(tmp, _pixel_art(16, 16), "small.png"))
    assert small.transform == "upscale"
    assert small.resampler == "nearest"
    assert float(small.scale_factor).is_integer(), (
        "a fractional upscale would blur the pixel edges")
    assert small.width == small.source_width * int(small.scale_factor)
    # ~1 MP, never past the ceiling, and never past the target.
    assert small.width * small.height <= R.TARGET_PIXELS
    assert max(small.width, small.height) <= R.MAX_DIMENSION

    big = R.prepare(_write(tmp, _photo(1600, 1200), "big.png"))
    assert big.transform == "downscale"
    assert big.resampler == "lanczos"
    assert big.width * big.height <= R.TARGET_PIXELS
    # No padding, no stretching: the only drift is the x16 snap (4:3 ->
    # 1184x880, about 1%).
    assert abs((big.width / big.height) - (1600 / 1200)) < 0.02
    assert big.width % 16 == 0 and big.height % 16 == 0

    # A 4x pixel-art sheet: lands on 1024x1024 (not the 1025x1025 that
    # rounding sqrt(1.05 MP) gives) and keeps NEAREST even though the 0.8x
    # factor is fractional -- by decision, hard edges beat even columns.
    sheet = R.prepare(_write(tmp, _pixel_art(1280, 1280), "sheet.png"))
    assert sheet.transform == "downscale"
    assert (sheet.width, sheet.height) == (1024, 1024)
    assert sheet.resampler == "nearest"

    mid = R.prepare(_write(tmp, _photo(800, 600), "mid.png"))
    assert mid.transform == "none", "an in-range image must be left alone"
    print("ok  upscale is nearest, downscale is lanczos, ratio is preserved")


def test_the_ratio_guard_accepts_its_exact_endpoints() -> None:
    """3:7 .. 7:3, inclusive — an off-by-one here refuses legal input.

    The window comes from PREFERED_KONTEXT_RESOLUTIONS, whose own extremes
    are 672x1568 and 1568x672. If the program refused its own source table's
    endpoints it would be rejecting sizes the ecosystem treats as canonical.
    """
    R.check_aspect(1568, 672)
    R.check_aspect(672, 1568)
    R.check_aspect(1024, 1024)
    R.check_aspect(256, 256)
    for w, h in ((128, 32), (256, 32), (384, 32), (32, 128)):
        try:
            R.check_aspect(w, h)
            raise AssertionError(f"{w}x{h} must be refused")
        except R.ReferenceError as e:
            msg = str(e)
            # The message must name the ACTUAL NUMBERS and a remedy.
            # "Unsupported aspect ratio" tells a user nothing.
            assert f"{w}x{h}" in msg, msg
            assert "crop" in msg.lower(), msg
    print("ok  the ratio guard is inclusive at 3:7 and 7:3, and says why")


def test_pixel_art_detection_and_the_manual_override(tmp) -> None:
    """Auto is measured to be reliable; a manual choice always wins over it.

    Two signals, both cheap: the distinct colour count, and whether the image
    survives a nearest half-scale round trip unchanged. Pixel art scores 4
    colours / 0.000; a photo scores ~97k / 0.529. The manual options exist
    because detection CAN be wrong and the user knows their own file.
    """
    art = _write(tmp, _pixel_art(32, 32), "art.png")
    photo = _write(tmp, _photo(512, 512), "photo.png")

    assert R.prepare(art).detected_pixel_art is True
    assert R.prepare(photo).detected_pixel_art is False

    # Pixel art mangled through JPEG must STILL read as pixel art -- that is
    # the case naive detection breaks on, and the one the colour count exists
    # to rescue: JPEG ringing on every hard edge pushes the round-trip signal
    # right up while the palette stays tiny.
    #
    # Saved at its OWN size, not resized first: a bicubic resize genuinely
    # destroys the pixel edges, so such an image is no longer pixel art and
    # classifying it as artwork would be correct rather than a failure. An
    # earlier draft of this test made exactly that mistake.
    jpeg = Path(tmp) / "art.jpg"
    _pixel_art(32, 32).save(jpeg, quality=85)
    assert R.prepare(jpeg).detected_pixel_art is True, (
        "JPEG'd pixel art must stay on the pixel-art side")

    # And the mirror case, which the round trip alone gets WRONG: a smooth
    # gradient survives a half-scale round trip untouched (it has no detail
    # to lose), so only the colour count separates it from a sprite.
    smooth = _write(tmp, _photo(600, 600), "smooth.png")
    assert R.prepare(smooth).detected_pixel_art is False

    # A manual choice is not consulted against the detector at all.
    forced = R.prepare(art, "lanczos")
    assert forced.resampler == "lanczos"
    assert forced.detected_pixel_art is None, (
        "detection must not run when the user has chosen")
    assert forced.resampler_reason == "your choice"
    big_forced = R.prepare(_write(tmp, _photo(1600, 1200), "p2.png"), "nearest")
    assert big_forced.resampler == "nearest"
    print("ok  pixel-art detection works and a manual choice always wins")


def test_a_ratio_mismatch_warns_and_never_refuses(tmp) -> None:
    """A 1:1 sprite against a 16:9 batch is reasonable, not an error.

    The reference carries STYLE; the output ratio carries COMPOSITION. Only
    the 3:7..7:3 window is a hard refusal, because that is about the model
    being unable to use the image at all. Conflating the two would refuse a
    perfectly ordinary thing to want.
    """
    square = _write(tmp, _pixel_art(128, 128), "sq.png")
    prepared = R.prepare(square, output_size=(1536, 864))
    assert prepared.data, "a ratio mismatch must still produce a usable image"
    note = " ".join(prepared.warnings)
    assert "1:1" in note and "16:9" in note
    # The CONSEQUENCE, not the verdict.
    assert "re-frame" in note, note
    assert "still transfers" in note, note

    # Close enough is silent: 1024x1024 against a 1:1 output must not nag.
    quiet = R.prepare(square, output_size=(1024, 1024))
    assert not any("re-frame" in w for w in quiet.warnings)
    print("ok  a ratio mismatch warns with the consequence and never refuses")


def test_the_hash_follows_the_bytes_not_the_path(tmp) -> None:
    """Content hash, never path — the style-suffix bug's exact failure shape.

    Swap a different sprite in under the same filename and a path-keyed
    identity would reattach to the finished batch, find the old images on
    disk and generate nothing, silently. The same file under two names must
    hash identically, and two different files under one name must not.
    """
    a = _write(tmp, _pixel_art(64, 64), "same.png")
    b = _write(tmp, _pixel_art(64, 64), "renamed.png")
    assert R.prepare(a).content_hash == R.prepare(b).content_hash, (
        "identical bytes under different names must hash the same")

    before = R.prepare(a).content_hash
    # A genuinely DIFFERENT image written over the same path. A transposed
    # checkerboard is not different enough -- it is symmetric, so it comes
    # back byte-identical and the test would pass for the wrong reason.
    _photo(64, 64).save(a)
    assert R.prepare(a).content_hash != before, (
        "different bytes under the SAME name must hash differently — this is "
        "the swap that a path-keyed identity would silently miss")

    # And the resampler is covered for free, because it changes the bytes --
    # which is why it is deliberately not a separate hash part.
    big = _write(tmp, _photo(1600, 1200), "big.png")
    assert (R.prepare(big, "nearest").content_hash
            != R.prepare(big, "lanczos").content_hash)
    print("ok  the reference hash follows the bytes, never the path")


def test_hash_parts_are_unchanged_when_no_reference_is_set() -> None:
    """Backward compatibility, and it was VERIFIED rather than assumed.

    The parts are joined with a separator, so a trailing None appends an
    empty FIELD and changes the digest. Appending it unconditionally would
    have renamed every image in every batch made before this feature, so each
    would have looked unfinished, resumed, and regenerated -- an entire
    re-bill on a paid model from a filename change nobody asked for. The part
    is therefore OMITTED, not passed as None.
    """
    base = P.image_hash_parts("a cat", "klein4b", 1536, 864)
    explicit_none = P.image_hash_parts("a cat", "klein4b", 1536, 864,
                                       reference_hash=None)
    assert P._hash_tag(base) == P._hash_tag(explicit_none)
    assert len(explicit_none) == len(base)

    with_ref = P.image_hash_parts("a cat", "klein4b", 1536, 864,
                                  reference_hash="deadbeef")
    assert P._hash_tag(with_ref) != P._hash_tag(base), (
        "a reference is image-affecting and MUST change the filename")
    assert R.hash_part(None) is None
    print("ok  no reference means the old filenames and resume are untouched")


def test_a_changed_reference_is_a_changed_BATCH_not_just_a_changed_name(tmp) -> None:
    """BOTH identity gates, because fixing one and not the other leaves the bug.

    This program has already been bitten once by exactly this: the style
    suffix was in `build_filename()` but not in `find_batch()`, so a rerun
    reattached to the finished batch, found every job `done` and generated
    nothing -- silently. CLAUDE.md records the lesson as "fixing only one
    leaves the symptom".

    So the reference is in both. A changed reference must produce a different
    batch row AND a different filename; an identical one must reattach to the
    same row; and a batch with NO reference must keep reattaching exactly as
    it did before the feature existed.
    """
    prompts = Path(tmp) / "p.txt"
    prompts.write_text("a cat\n", encoding="utf-8")
    out = Path(tmp) / "out"
    a = _write(tmp, _pixel_art(64, 64), "a.png")
    b = _write(tmp, _photo(64, 64), "b.png")

    def batch_id(ref):
        cfg = BatchConfig(prompt_file=prompts, output_dir=out,
                          model="klein4b", ratio="1:1", tier="draft",
                          reference_image=ref)
        with BatchEngine(cfg, provider=FakeProvider({})) as eng:
            return eng.prepare()

    none1, none2 = batch_id(None), batch_id(None)
    assert none1 == none2, "an unchanged referenceless batch must reattach"

    a1, a2 = batch_id(a), batch_id(a)
    assert a1 == a2, "an unchanged reference must reattach to the same batch"
    assert a1 != none1, "adding a reference changes the image, so the batch"
    assert batch_id(b) not in (a1, none1), (
        "a DIFFERENT reference must be a different batch — otherwise the "
        "rerun finds every job done and generates nothing")

    # And the batch made before any of this existed still reattaches: the
    # column defaults to '' and a referenceless run asks for ''.
    assert batch_id(None) == none1
    print("ok  a changed reference changes the batch identity, not only the name")


def test_reference_influence_phrase_is_per_model_and_off_by_default(tmp) -> None:
    """The sentence names the reference in the MODEL's own words, and only
    when a reference is actually being sent.

    klein addresses inputs by index ("image 0"); the other families have no
    documented index convention. And a phrase pointing at "image 0" on a
    model that was never given an image 0 would point the model at nothing.
    """
    # The user's exact wording (2026-10-15) -- pinned so an edit is deliberate.
    k4 = M.get_model("klein4b")
    assert [R.influence_phrase(m, k4) for m in R.INFLUENCE_MODES] == [
        "No influence from image 0.",
        "Subtle influences from image 0.",
        "Medium influence from image 0.",
        "Heavy influence from image 0.",
        "Exact style as image 0.",
    ]
    assert R.DEFAULT_INFLUENCE == "none"
    nano = R.influence_phrase("medium", M.get_model("nano-banana-2"))
    assert nano == "Medium influence from the reference image."
    assert R.influence_phrase("medium", M.get_model("p-image")) == ""
    for mode in R.INFLUENCE_MODES:
        assert mode in R.INFLUENCE_LABELS

    prompts = Path(tmp) / "p.txt"
    prompts.write_text("a cat\n", encoding="utf-8")
    ref = _write(tmp, _pixel_art(64, 64), "a.png")

    def final(ref_path, mode, model="klein4b"):
        cfg = BatchConfig(prompt_file=prompts, output_dir=Path(tmp) / "out",
                          model=model, ratio="1:1", tier="draft",
                          reference_image=ref_path, reference_influence=mode)
        with BatchEngine(cfg, provider=FakeProvider({})) as eng:
            return eng.load_lines()[0].final

    assert final(ref, "none") == "a cat. No influence from image 0."
    assert final(ref, "medium") == "a cat. Medium influence from image 0."
    assert final(None, "medium") == "a cat", (
        "no reference is being sent, so there is nothing to refer to")
    assert final(ref, "medium", model="krea-turbo") == "a cat", (
        "a model that drops the reference must drop the sentence too")
    print("ok  the influence sentence is per model and only sent with a reference")


def test_with_influence_never_edits_the_users_text() -> None:
    """It only chooses a joiner, so the added part is exactly the tail --
    which is what the GUI preview slices off to colour it."""
    p = "In the art style of image 0."
    assert R.with_influence("Thick outlines.", p) == "Thick outlines. " + p
    assert R.with_influence("pixel art", p) == "pixel art. " + p
    assert R.with_influence("pixel art,", p) == "pixel art, " + p
    assert R.with_influence("", p) == p
    assert R.with_influence("pixel art", "") == "pixel art"
    for text in ("Thick outlines.", "pixel art", "a, b,"):
        assert R.with_influence(text, p).startswith(text)
    print("ok  the influence sentence is appended without editing the prompt")


def test_a_changed_influence_is_a_changed_batch_and_a_changed_name(tmp) -> None:
    """BOTH identity gates, the lesson the style suffix taught.

    The sentence changes every final prompt, so switching Influence must not
    reattach to a finished batch and generate nothing. Off must reattach to
    the batch made before the setting existed.
    """
    prompts = Path(tmp) / "p.txt"
    prompts.write_text("a cat\n", encoding="utf-8")
    out = Path(tmp) / "out"
    ref = _write(tmp, _pixel_art(64, 64), "a.png")

    def ident(mode):
        cfg = BatchConfig(prompt_file=prompts, output_dir=out,
                          model="klein4b", ratio="1:1", tier="draft",
                          reference_image=ref, reference_influence=mode)
        with BatchEngine(cfg, provider=FakeProvider({})) as eng:
            return eng.prepare(), eng.dry_run()["lines"][0]["filename"]

    def legacy():
        # A config built with no influence argument at all, as every batch
        # before this setting was.
        cfg = BatchConfig(prompt_file=prompts, output_dir=out,
                          model="klein4b", ratio="1:1", tier="draft",
                          reference_image=ref)
        with BatchEngine(cfg, provider=FakeProvider({})) as eng:
            return eng.prepare(), eng.dry_run()["lines"][0]["filename"]

    got = [ident(m) for m in R.INFLUENCE_MODES]
    assert legacy() == got[0], "an unset influence must mean the default"
    assert ident("medium") == got[2], "an unchanged setting must reattach"
    assert len({g[0] for g in got}) == len(got), (
        "a changed influence must be a different BATCH, or the rerun finds "
        "every job done and generates nothing")
    assert len({g[1] for g in got}) == len(got), (
        "a changed influence must be a different FILENAME")
    print("ok  a changed influence changes the batch identity and the name")


def test_an_unusable_reference_fails_the_dry_run_too(tmp) -> None:
    """A dry run is where a user checks before paying, so it must refuse too.

    And on a model that cannot take one, the dry run says the reference is
    being IGNORED rather than dropping it silently -- the batch still runs,
    and the user should not have to work that out from the images.
    """
    prompts = Path(tmp) / "p.txt"
    prompts.write_text("a cat\n", encoding="utf-8")
    out = Path(tmp) / "out"

    strip = _write(tmp, _pixel_art(384, 32), "strip.png")
    cfg = BatchConfig(prompt_file=prompts, output_dir=out, model="klein4b",
                      reference_image=strip)
    with BatchEngine(cfg, provider=FakeProvider({})) as eng:
        try:
            eng.dry_run()
            raise AssertionError("a 12:1 strip must fail the dry run")
        except R.ReferenceError as e:
            assert "12:1" in str(e)

    good = _write(tmp, _pixel_art(128, 128), "ok.png")
    cfg2 = BatchConfig(prompt_file=prompts, output_dir=out, model="krea-turbo",
                       reference_image=good)
    with BatchEngine(cfg2, provider=FakeProvider({})) as eng:
        info = eng.dry_run()
    assert info["reference"] is None
    assert info["reference_requested"] is True
    assert info["reference_supported"] is False, (
        "the dry run must distinguish 'none asked for' from 'asked for and "
        "impossible' — they print different things")
    print("ok  an unusable reference fails the dry run, and a dropped one says so")


# The Recraft pair. Ships as a pair by decision: Utility is general-purpose,
# V4.1 is art-directed, they cost the same, and V4.1 scores LOWER (Elo 1198 vs
# 1218) -- so neither is the other's upgrade. Every Recraft test runs over both,
# because the field list, the size enum and the response shape are identical
# and a quirk that holds for one must hold for the other.
RECRAFT_MODELS = ("recraft-utility", "recraft-v41")

# Google's nano-banana family. Only Lite ships today; nano-banana-2 is the
# last model on the list and joins this tuple when it lands, so every
# nano-banana test covers both without being rewritten.
NANO_BANANA_MODELS = ("nano-banana-2-lite", "nano-banana-2")


def test_every_size_enum_model_owns_a_size_table() -> None:
    """A size_enum model with no SIZE_TABLE_OVERRIDES entry is a BILLED bug.

    Without an override, size_for() falls back to the shared SIZES table and
    hands back 1536x864 at Standard 16:9 -- which is not a legal Recraft size.
    On any other gateway model that request would be rejected for free; on
    this family it is charged for and THEN refused. This exact omission
    happened while adding the second model of the pair, so it is pinned here
    rather than left to be caught by whoever adds the next enum model.
    """
    for spec in M.ALL_MODELS:
        if spec.size_style != "size_enum":
            continue
        assert spec.key in M.SIZE_TABLE_OVERRIDES, (
            f"{spec.key} speaks a size enum but owns no size table — it would "
            f"fall back to the shared SIZES table and send an illegal size "
            f"that costs money to have refused")
        for ratio in M.RATIOS:
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, spec.key)
                assert not spec.validate_size(w, h), (
                    f"{spec.key} {ratio}/{tier} resolves to an illegal "
                    f"{w}x{h}")
    print("ok  every size_enum model owns a size table of legal values")


def test_recraft_sends_a_validated_size_enum_not_pixels() -> None:
    """Recraft speaks an opaque "WxH" enum and rejects aspect_ratio outright.

    Every one of the program's five ratios must map to a legal enum value,
    and neither width/height nor aspect_ratio may appear in the body.
    """
    for key in RECRAFT_MODELS:
      spec = M.get_model(key)
      for ratio in M.RATIOS:
        for tier in M.TIERS:
            w, h = M.size_for(ratio, tier, key)
            inp = CloudflareProvider._gateway_payload(
                spec, "a cat", w, h, 4242)["input"]
            assert inp["size"] == f"{w}x{h}", inp
            assert inp["size"] in M.RECRAFT_SIZE_ENUM, inp["size"]
            for banned in ("width", "height", "aspect_ratio", "resolution",
                           "seed", "negative_prompt", "guidance", "num_steps",
                           "steps", "style", "substyle"):
                assert banned not in inp, banned + " must not be sent to recraft"
    print("ok  recraft sends a validated size enum, never pixels or a ratio")


def test_recraft_bad_size_fails_locally_before_it_can_be_billed() -> None:
    """THE asymmetry that makes this family different.

    Every other gateway model's validation is free -- the gateway rejects a
    malformed request before charging. Recraft's gateway only type-checks that
    `size` is a STRING and defers the value check to Recraft, so a bad value
    is BILLED and then fails at generation time. The check therefore has to
    happen client-side, and it must raise rather than send.
    """
    spec = M.get_model("recraft-utility")
    for bad in ((1536, 864), (1024, 1023), (2048, 1152), (0, 0)):
        try:
            CloudflareProvider._gateway_payload(spec, "a cat", *bad, None)
        except PermanentError as e:
            assert "not one of Recraft" in str(e), str(e)
        else:
            raise AssertionError(
                f"{bad} was accepted; a bad recraft size must never reach the "
                f"API, because it is charged for before it fails"
            )
    # And the validator itself is the only door.
    try:
        M.recraft_size_string(1536, 864)
    except ValueError:
        pass
    else:
        raise AssertionError("recraft_size_string accepted an illegal size")
    # validate_size must catch it too, not just the provider: an enum model's
    # legal sizes are a SET, so the min/max/x16 checks are not sufficient.
    # 1024x768 is inside Recraft's 768-1344 bounds and is still illegal, and
    # the GUI readout and `cli dry-run` both read validate_size.
    assert spec.validate_size(1024, 768), (
        "1024x768 is inside the bounds but not in the enum — validate_size "
        "must reject it, or dry-run would call a size that costs money to "
        "have refused")
    assert not spec.validate_size(1344, 768), spec.validate_size(1344, 768)
    print("ok  an illegal recraft size is refused locally, never billed")


def test_recraft_size_default_is_a_square_so_size_is_always_sent() -> None:
    """Recraft's own default for `size` is 1024x1024 -- a SQUARE.

    That makes silence non-neutral: omitting the field would quietly turn a
    16:9 batch into 1:1 crops. Same call as krea's `creativity` and
    flux-2-pro's `output_format`.
    """
    assert M.RECRAFT_DEFAULT_SIZE == "1024x1024"
    assert M.RECRAFT_DEFAULT_SIZE in M.RECRAFT_SIZE_ENUM
    spec = M.get_model("recraft-utility")
    w, h = M.size_for("16:9", "standard", "recraft-utility")
    inp = CloudflareProvider._gateway_payload(spec, "a cat", w, h, None)["input"]
    assert "size" in inp, "size must be sent even when it is not overridden"
    assert inp["size"] != M.RECRAFT_DEFAULT_SIZE, (
        "16:9 must not silently fall back to the square default")
    print("ok  recraft always sends `size`; its API default is a square")


def test_recraft_has_no_seed_and_no_tier_ladder() -> None:
    for key in RECRAFT_MODELS:
        spec = M.get_model(key)
        assert not spec.supports_seed, (
            f"{key} exposes no seed field; reproducibility is impossible")
        assert not M.has_tier_ladder(key), (
            f"{key} has one fixed size per ratio -- the tier dropdown must "
            f"disable rather than silently do nothing")
        # A seed passed in anyway must be dropped, not sent.
        w, h = M.size_for("16:9", "standard", key)
        inp = CloudflareProvider._gateway_payload(
            spec, "a cat", w, h, 99)["input"]
        assert "seed" not in inp, inp
        # Every tier is the same size, and therefore the same price.
        costs = {M.estimate(key, *M.size_for("16:9", t, key)).cost_per_1000
                 for t in M.TIERS}
        assert costs == {35.0}, (key, costs)
    print("ok  recraft pair: no seed, no tier ladder, one flat price")


def test_seedless_model_records_no_seed_in_its_metadata() -> None:
    """A seed that was never sent must not be written to the sidecar.

    The engine generates a seed for every job regardless of model. On a
    seedless model the provider drops it -- but recording it anyway would
    promise a reproducibility that does not exist: re-running with that seed
    gives a different image and no clue why.
    """
    import core.imagecheck as _ic

    class _Resp:
        headers = {"content-type": "image/png"}

    png = _ic_sample()
    for key in (*RECRAFT_MODELS, *NANO_BANANA_MODELS):
        w, h = M.size_for("16:9", "standard", key)
        res = CloudflareProvider._finish(
            png, _Resp(), M.get_model(key), "a cat", w, h, 4242, 1.0)
        assert res.seed is None, f"{key} recorded seed {res.seed}"
    res = CloudflareProvider._finish(
        png, _Resp(), M.get_model("flux2pro"),
        "a cat", 1536, 864, 4242, 1.0)
    assert res.seed == 4242, "a model that DOES take a seed must record it"
    print("ok  a seed is recorded only where it was actually sent")


def _ic_sample() -> bytes:
    """A tiny non-blank PNG that passes decodes()/is_blank()."""
    from io import BytesIO
    from PIL import Image
    img = Image.new("RGB", (8, 8), (10, 20, 30))
    for x in range(8):
        img.putpixel((x, 0), (250, 240, 230))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_recraft_is_a_flat_priced_gateway_model_returning_a_url() -> None:
    for key in RECRAFT_MODELS:
        _assert_recraft_shape(key)
    print("ok  recraft pair: gateway, flat $35/1000, $$ marker, presigned URL")


def _assert_recraft_shape(key: str) -> None:
    spec = M.get_model(key)
    assert spec.call_style == "gateway"
    assert spec.size_style == "size_enum"
    assert not spec.bills_per_tile, (
        "tile counts are meaningless next to a flat per-image price")
    # result.image is a PRESIGNED URL (doc-derived, cross-checked), the krea
    # shape -- not klein's bare base64 and not p-image's data URI.
    assert spec.response_encoding == "json_url"
    est = M.estimate(key, 1344, 768)
    assert abs(est.cost_per_1000 - 35.0) < 0.001, est.cost_per_1000
    assert est.over_budget, "$35/1000 is above the $5 ceiling"
    assert M.cost_tier_marker(key) == "$$$", "$35/1000 is the HIGH band"
    assert est.free_images_per_day is None, (
        "gateway models draw on prepaid credit, not the neuron allowance")


def test_recraft_16x9_is_smaller_than_the_programs_standard() -> None:
    """A fact the UI must state rather than hide.

    Recraft's 16:9 is 1344x768 against the program's Standard 1536x864 --
    fewer pixels for $35/1000 instead of $0-$1.72. Pinned so a later edit
    cannot quietly "fix" the table to the tabled size, which Recraft would
    charge for and then reject.
    """
    sw, sh = M.SIZES["16:9"]["standard"]
    for key in RECRAFT_MODELS:
        w, h = M.size_for("16:9", "standard", key)
        assert (w, h) == (1344, 768), (key, w, h)
        assert w * h < sw * sh, f"{key} 16:9 should be SMALLER than Standard"
    assert f"{sw}x{sh}" not in M.RECRAFT_SIZE_ENUM, (
        "the program's Standard 16:9 is NOT a legal Recraft size")
    print("ok  recraft 16:9 is 1344x768 — smaller than Standard, and priced $$")


def test_nano_banana_sends_a_ratio_and_a_resolution_word_never_pixels() -> None:
    """nano-banana speaks krea's vocabulary: an aspect_ratio enum plus a
    resolution WORD. It has no width/height field at all, so sending pixels
    would be a malformed request.

    Every one of the program's five ratios must map to a legal enum value.
    """
    legal_ratios = set(M.RATIO_TO_ENUM.values())
    for key in NANO_BANANA_MODELS:
        spec = M.get_model(key)
        for ratio in M.RATIOS:
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, key)
                inp = CloudflareProvider._gateway_payload(
                    spec, "a cat", w, h, 1234)["input"]
                assert inp["aspect_ratio"] in legal_ratios, inp
                assert inp["aspect_ratio"] == M.RATIO_TO_ENUM[ratio], (
                    f"{key} {ratio} sent {inp['aspect_ratio']!r}")
                assert inp["resolution"] in M.NANO_BANANA_RESOLUTIONS, inp
                assert "width" not in inp and "height" not in inp, (
                    f"{key} has no width/height field; sending pixels is a "
                    f"malformed request")
                assert "size" not in inp, "that is Recraft's vocabulary"
    print("ok  nano-banana sends a ratio enum + a resolution word, never pixels")


def test_nano_banana_resolution_is_looked_up_never_derived_from_the_tier() -> None:
    """THE most expensive mistake available in this family, and the reason
    nano_banana_resolution() exists.

    The Draft/Standard/High dropdown maps onto 1K/2K/4K *deceptively* well --
    but the two models in the family do not agree about the mapping. Lite is
    pinned to 1K at every tier; its sibling is not. Deriving the resolution
    from the tier NAME would send 4K on a model priced only at 1K, and on
    nano-banana-2 a 4K image costs 2.3x a 1K one -- a quoted price and a sent
    resolution that disagree bill the user for something the estimate never
    showed them.
    """
    for key in NANO_BANANA_MODELS:
        mapping = M.NANO_BANANA_TIER_RESOLUTION[key]
        assert set(mapping) == set(M.TIERS), (
            f"{key} must map EVERY tier; a missing one becomes a KeyError at "
            f"request time")
        for tier in M.TIERS:
            assert M.nano_banana_resolution(key, tier) == mapping[tier]
            assert mapping[tier] in M.NANO_BANANA_RESOLUTIONS

    lite = M.NANO_BANANA_TIER_RESOLUTION["nano-banana-2-lite"]
    assert set(lite.values()) == {"1K"}, (
        "nano-banana-2-lite is pinned to 1K: Cloudflare's schema declares "
        "2K/4K but three independent sources say Lite renders 1K only, and "
        "Google publishes NO 2K/4K price for it. An unpriceable batch is "
        "worse than a smaller one. Unpin this only alongside real prices.")
    print("ok  nano-banana resolution is looked up per model, not derived")


def test_nano_banana_price_follows_the_resolution_not_a_flat_number() -> None:
    """The ONE family where a bigger tier genuinely costs more money.

    Every other gateway model is flat per image, so _flat_per_image() is right
    for them and wrong here. This exercises the mechanism on a FULL 1K/2K/4K
    ladder -- the shape nano-banana-2 will use -- because Lite is pinned to 1K
    and cannot exercise it alone. Without this the per-resolution pricing
    would stay untested until the expensive model landed.
    """
    prices = {"1K": 0.067, "2K": 0.101, "4K": 0.151}
    f = M._per_resolution(prices)
    for ratio, per_res in M.SIZES_NANO_BANANA.items():
        for res, (w, h) in per_res.items():
            assert abs(f(w, h) - prices[res]) < 1e-9, (
                f"{ratio} {res} {w}x{h} priced {f(w, h)}, expected "
                f"{prices[res]} -- the price must follow the RESOLUTION")

    # An unrecognised size falls back to the DEAREST price, never the
    # cheapest: if the estimate has to be wrong, it must not be wrong in the
    # direction that surprises the user with a bill.
    assert f(999, 999) == max(prices.values())

    # And Lite quotes its one real price at every tier, rather than
    # pretending the tier changes something.
    lite = M.get_model("nano-banana-2-lite")
    seen = {round(lite.cost_per_1000(*M.size_for("16:9", t, lite.key)), 2)
            for t in M.TIERS}
    assert seen == {34.00}, seen
    print("ok  nano-banana price follows the resolution tier, not a flat rate")


def test_nano_banana_output_format_is_jpg_not_jpeg() -> None:
    """The spelling differs from flux-2-pro's for the identical format, which
    is exactly the bug wire_output_format() exists to prevent.

    Cloudflare states the enum (jpg|png) but NO default, and Google publishes
    none either -- so unlike flux-2-pro, where the non-neutral `jpeg` default
    was documented, here the default is simply UNKNOWN. It is sent explicitly
    for that reason: an unknown default cannot be assumed neutral.
    """
    nb = M.get_model("nano-banana-2-lite")
    assert M.wire_output_format(nb) == "jpg", "nano-banana says jpg"
    assert M.wire_output_format(M.get_model("flux2pro")) == "jpeg", (
        "flux-2-pro says jpeg for the SAME format -- if these two ever agree, "
        "one of them is being written out by hand at a call site")

    w, h = M.size_for("16:9", "standard", nb.key)
    inp = CloudflareProvider._gateway_payload(nb, "a cat", w, h, None)["input"]
    assert inp["output_format"] == "jpg", inp
    print("ok  nano-banana sends output_format 'jpg', flux-2-pro sends 'jpeg'")


def test_nano_banana_has_no_seed_and_records_none() -> None:
    """No seed field exists, so reproducibility is impossible -- a stronger
    statement than "the control is greyed out", and one the GUI makes.

    Recraft built this path; this verifies the flag is set and that a seed
    passed in is DROPPED rather than forwarded to a model with no such field.
    """
    for key in NANO_BANANA_MODELS:
        spec = M.get_model(key)
        assert spec.supports_seed is False, key
        w, h = M.size_for("16:9", "standard", key)
        inp = CloudflareProvider._gateway_payload(spec, "a cat", w, h, 4242)["input"]
        assert "seed" not in inp, f"{key} accepts no seed field"
    print("ok  nano-banana accepts no seed and never sends one")


def test_nano_banana_sizes_are_published_not_estimated() -> None:
    """Krea's sizes are a guess shown with a "~ estimated"; Google publishes
    nano-banana's exactly, so the same marker would be dishonest in the other
    direction.

    The GUI readout was originally keyed on size_style, which made it wrong
    the moment a second model shared krea's vocabulary. sizes_published asks
    the honest question directly, and this pins the answers.
    """
    assert M.get_model("nano-banana-2-lite").sizes_published is True
    for key in ("krea-turbo", "krea-medium"):
        assert M.get_model(key).sizes_published is False, (
            f"{key} is the ONLY family whose displayed size is an estimate")
    # Both families speak the same size vocabulary, which is precisely why
    # sizes_published cannot be derived from it.
    assert (M.get_model("nano-banana-2-lite").size_style
            == M.get_model("krea-turbo").size_style
            == "aspect_ratio_resolution")
    # Google's published dimensions, verbatim, and every tier an exact 2x.
    assert M.SIZES_NANO_BANANA["16:9"]["1K"] == (1344, 768)
    assert M.SIZES_NANO_BANANA["16:9"]["2K"] == (2688, 1536)
    assert M.SIZES_NANO_BANANA["16:9"]["4K"] == (5376, 3072)
    assert M.SIZES_NANO_BANANA["1:1"]["1K"] == (1024, 1024)
    for per_res in M.SIZES_NANO_BANANA.values():
        w1, h1 = per_res["1K"]
        assert per_res["2K"] == (w1 * 2, h1 * 2)
        assert per_res["4K"] == (w1 * 4, h1 * 4)
    print("ok  nano-banana sizes are published; only krea's are estimated")


def test_nano_banana_is_a_gateway_model_returning_a_url() -> None:
    """Gateway plumbing: body-addressed, prepaid credit, presigned URL.

    The two models share every one of these, and differ ONLY in price shape:
    Lite is pinned to 1K so it quotes one number, while nano-banana-2 has a
    real ladder. `bills_per_tile` is False on both -- neither uses Cloudflare's
    native tile billing -- but that is not the same as "flat", which is why
    this test no longer says so.
    """
    expected_marker = {"nano-banana-2-lite": "$$$",   # HIGH, $34
                       "nano-banana-2": "$$$$"}     # EXTREME, $67-151
    for key in NANO_BANANA_MODELS:
        spec = M.get_model(key)
        assert spec.call_style == "gateway"
        assert spec.bills_per_tile is False, (
            "a tile count beside a per-image price is a meaningless number")
        assert spec.response_encoding == "json_url", (
            "result.image is a PRESIGNED URL -- confirmed on Cloudflare's own "
            "model page and cross-checked against the nano-banana-2 page")
        assert spec.is_free is False
        assert M.cost_tier_marker(key) == expected_marker[key], (
            f"{key}: {M.cost_tier_marker(key)}")
        w, h = M.size_for("16:9", "standard", key)
        body = CloudflareProvider._gateway_payload(spec, "a cat", w, h, None)
        assert body["model"] == spec.id, "the id goes in the BODY, not the URL"
        est = M.estimate(key, w, h, 10)
        assert est.free_images_per_day is None, (
            "no neuron allowance -- this is prepaid credit")
    print("ok  nano-banana: gateway, prepaid credit, presigned URL, right marker")


def test_nano_banana_2_has_a_real_tier_ladder_that_changes_the_price() -> None:
    """The ONE model in the program where the quality tier changes the bill.

    Everywhere else the tier is free (native models bill per tile, so a bigger
    size inside the same tile count costs the same) or fixed (every other
    gateway model is flat per image). Here Draft/Standard/High map to
    1K/2K/4K at $67/$101/$151 per 1000, so a High batch costs 2.25x a Draft
    one. If the sent resolution and the quoted price ever disagree, the user
    is billed for something the estimate never showed them.
    """
    key = "nano-banana-2"
    spec = M.get_model(key)
    assert M.has_tier_ladder(key), "the tier dropdown must ENABLE for this one"

    expected = {"draft": ("1K", 67.00), "standard": ("2K", 101.00),
                "high": ("4K", 151.00)}
    for tier, (res, per_1000) in expected.items():
        w, h = M.size_for("16:9", tier, key)
        # The price quoted...
        assert abs(spec.cost_per_1000(w, h) - per_1000) < 1e-6, (
            f"{tier} quoted {spec.cost_per_1000(w, h)}, expected {per_1000}")
        # ...and the resolution actually SENT must agree.
        inp = CloudflareProvider._gateway_payload(spec, "a cat", w, h, None)["input"]
        assert inp["resolution"] == res, (
            f"{tier} quotes the {res} price but sends {inp['resolution']!r} — "
            f"a quoted price and a sent resolution that disagree bill the "
            f"user for something the estimate never showed them")
        assert M.nano_banana_resolution(key, tier) == res

    # Distinct sizes AND distinct prices at every tier -- the thing that makes
    # this family different from every other gateway model.
    sizes = {M.size_for("16:9", t, key) for t in M.TIERS}
    prices = {spec.cost_per_1000(*M.size_for("16:9", t, key)) for t in M.TIERS}
    assert len(sizes) == 3 and len(prices) == 3, (sizes, prices)

    # And Lite, by contrast, must NOT have gained a ladder.
    assert not M.has_tier_ladder("nano-banana-2-lite")
    print("ok  nano-banana-2 has a real tier ladder; price follows resolution")


def test_nano_banana_2_is_dollar_dollar_dollar_at_every_tier() -> None:
    """The fixed dropdown marker is only safe because no tier drops below the
    tolerance. Pinned so a future price cut cannot silently make the marker a
    lie -- the source doc flagged this as the one model whose label could move.
    """
    key = "nano-banana-2"
    spec = M.get_model(key)
    assert M.cost_tier_marker(key) == "$$$$"   # EXTREME: above $50/1000
    for ratio in M.RATIOS:
        for tier in M.TIERS:
            w, h = M.size_for(ratio, tier, key)
            per_1000 = spec.cost_per_1000(w, h)
            assert per_1000 > M.COST_TIER_TOLERANCE_PER_1000, (
                f"{ratio}/{tier} is ${per_1000}/1000, at or below the "
                f"${M.COST_TIER_TOLERANCE_PER_1000} tolerance — the fixed "
                f"$$$ marker would no longer be honest")
            est = M.estimate(key, w, h, 10)
            assert est.over_budget, "the over-budget warning must fire"
    print("ok  nano-banana-2 is $$$ and over budget at every ratio and tier")


def test_cost_tier_marker_prices_a_model_at_a_size_it_can_serve() -> None:
    """The marker's fixed reference size is 1536x864, which several models
    cannot serve at all.

    On a per-resolution model that matters: 1536x864 is not a nano-banana
    size, so pricing the marker there lands on _per_resolution's unknown-size
    fallback and quotes the DEAREST tier. That fallback is right for a cost
    estimate (never understate a bill) and wrong for a browsing marker, which
    should describe the ordinary case. Nothing moves today -- both nano-banana
    models are $$ or $$$ at every tier -- so this pins the mechanism before a
    model in a straddling band relies on it.
    """
    ref_ratio, ref_tier = M.COST_TIER_REFERENCE_RATIO_TIER
    for spec in M.ALL_MODELS:
        if spec.key not in M.SIZE_TABLE_OVERRIDES:
            continue
        w, h = M.size_for(ref_ratio, ref_tier, spec.key)
        assert not spec.validate_size(w, h), (
            f"{spec.key} is marked at {w}x{h}, which it cannot serve")
    # The specific case: the shared reference is NOT a nano-banana size, so
    # the override path is doing real work rather than being a no-op.
    assert not any(M.COST_TIER_REFERENCE_SIZE in per.values()
                   for per in M.SIZES_NANO_BANANA.values())
    print("ok  cost markers are priced at a size the model can actually serve")


def test_nano_banana_grounding_fields_are_never_sent() -> None:
    """google_search / image_search are skipped for a BILLING reason, and the
    distinction from the img2img skips is worth keeping straight.

    Grounding is charged separately -- $14 per 1000 search queries after 5000
    free per month -- and Google is explicit that one prompt may trigger
    several billable queries. Through a pass-through gateway, on a monthly
    allowance the program cannot see, that is unpriceable by construction. It
    would make the estimate silently wrong by an unbounded amount on the most
    expensive model in the lineup.

    (image_search is ALSO reference-image shaped, so it is doubly excluded;
    google_search is excluded purely on cost visibility.)
    """
    for key in NANO_BANANA_MODELS:
        spec = M.get_model(key)
        for ratio in M.RATIOS:
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, key)
                inp = CloudflareProvider._gateway_payload(
                    spec, "a cat", w, h, None)["input"]
                for f in M.NANO_BANANA_GROUNDING_FIELDS:
                    assert f not in inp, (
                        f"{key} must not send {f}: grounding is billed "
                        f"separately per search query and would make the "
                        f"cost estimate unbounded")
    print("ok  nano-banana grounding fields are never sent (billing reason)")


def test_nano_banana_2_4k_does_not_trigger_a_degradation_warning() -> None:
    """5376x3072 is far above the shared 1024px safe threshold, but this model
    is natively specified to 4K -- warning about duplicated structures and
    geometry drift would be flatly wrong, and would teach users to ignore a
    warning that is real on the SD models.
    """
    key = "nano-banana-2"
    spec = M.get_model(key)
    w, h = M.size_for("16:9", "high", key)
    assert (w, h) == (5376, 3072)
    assert not spec.size_warnings(w, h), spec.size_warnings(w, h)
    assert not spec.validate_size(w, h), spec.validate_size(w, h)
    # The SD models must still warn -- this is a per-model ceiling, not a
    # weakening of the check.
    sd = M.get_model("lightning")
    assert sd.size_warnings(2048, 1152), "SD degradation warning must survive"
    print("ok  nano-banana-2 renders 4K without a bogus degradation warning")


def test_model_dropdown_labels_fit_the_combobox():
    """Every model label fits the Provider tab's dropdown width.

    The label is assembled from the model name plus a default marker, a cost
    marker and the delivered format, so it grows whenever any of those change.
    It has already been widened twice for exactly that reason (44 -> 52 -> 60),
    each time AFTER a name was found truncated in the running GUI. A truncated
    model name is worse than a wide dropdown, and this is cheap to check
    offline, so it is pinned here rather than rediscovered by eye.

    Kept in sync BY HAND with the width= on gui/tabs/provider.py's model
    combobox -- importing the GUI here would drag Tk into an offline suite.
    """
    from gui.tabs.provider import ProviderTab

    combo_width = 60          # gui/tabs/provider.py, self.model_combo
    for spec in M.ALL_MODELS:
        label = ProviderTab._label(spec)
        assert len(label) <= combo_width, (
            f"{spec.key}: label is {len(label)} chars, combobox holds "
            f"{combo_width} -- widen the combobox or shorten the label: {label!r}"
        )


def test_price_notes_read_as_guidance_not_as_engineering_notes():
    """Per-model notes are shown to USERS, so they use the user's vocabulary.

    These strings moved from a tooltip into a label under the model dropdown,
    which made it obvious they had been written as developer shorthand: they
    referenced this project's internal budget policy ("the $5/1000 ceiling",
    "within tolerance") and raw Elo numbers, neither of which means anything
    to someone choosing a model. They also said "per 1000" with no noun.

    This does not police style -- it pins the specific vocabulary that was
    wrong, so it cannot drift back in when a model is edited.
    """
    # "neurons" was banned here in an earlier pass and that was WRONG: it is
    # Cloudflare's own published term for their compute credit, it appears in
    # their dashboard, and the free daily allowance cannot be explained
    # without it. The notes now front-load it, glossed on first use. What
    # stays banned is vocabulary internal to THIS PROJECT ("the ceiling",
    # "tolerance"), plus scores and billing units a user cannot act on.
    banned = ("ceiling", "tolerance", "Elo", "tiles", "over budget")
    for spec in M.ALL_MODELS:
        note = spec.price_note
        assert note, f"{spec.key}: has no price_note"
        for word in banned:
            assert word.lower() not in note.lower(), (
                f"{spec.key}: price_note uses internal vocabulary {word!r}, "
                f"which the user has no referent for: {note!r}"
            )
        if "per 1000" in note:
            assert "per 1000 images" in note, (
                f"{spec.key}: 'per 1000' needs its noun -- per 1000 what? "
                f"{note!r}"
            )


def test_tier_labels_fit_the_tier_combobox():
    """Every per-model tier label fits the dropdown, at every ratio.

    These labels are GENERATED (caption + size + sometimes a price), so unlike
    a hardcoded string they can grow when a model is added or a price changes,
    with nothing to make that visible until a user sees a clipped line. The
    first draft ran to 83 characters against a 56-wide box for exactly that
    reason. Kept in sync BY HAND with the width= on the tier combobox.
    """
    combo_width = 70          # gui/tabs/provider.py, self.tier_combo
    for spec in M.ALL_MODELS:
        for tier in M.TIERS:
            for ratio in M.RATIOS:
                label = M.tier_description(spec.key, tier, ratio)
                assert len(label) <= combo_width, (
                    f"{spec.key} {tier} {ratio}: tier label is {len(label)} "
                    f"chars, combobox holds {combo_width}: {label!r}"
                )


def test_only_nano_banana_2_has_a_tier_that_changes_price():
    """The price-lever branch fires for exactly one model, and it is computed.

    tier_changes_price() derives this from the price function rather than
    naming a model, so a second by-resolution model would pick the behaviour
    up automatically. This test pins the CURRENT answer so that a refactor
    which quietly breaks the derivation is caught -- if it ever returns False
    for nano-banana-2, the dropdown silently stops warning that High costs
    2.3x Draft on the most expensive model in the lineup.
    """
    assert M.tier_changes_price("nano-banana-2"), (
        "nano-banana-2 bills $67/$101/$151 by tier -- its dropdown MUST say so"
    )
    for key in ("krea-turbo", "recraft-utility", "p-image", "flux2pro",
                "nano-banana-2-lite"):
        assert not M.tier_changes_price(key), (
            f"{key} is flat per image -- claiming the tier changes its price "
            f"would push users to a smaller image for a saving that does not "
            f"exist"
        )
    for key in ("lightning", "sdxl", "dreamshaper"):
        assert not M.tier_changes_price(key), f"{key} is free"


def test_tier_labels_never_promise_a_saving_that_does_not_exist():
    """A flat-priced model must not describe Draft as "cheapest".

    Most of the gateway lineup charges the same for every size. Telling a user
    that Draft is cheaper there is a straightforward falsehood that costs them
    pixels for nothing -- which is what the single hardcoded label set used to
    do for every model in the program.
    """
    for spec in M.ALL_MODELS:
        if M.tier_changes_price(spec.key) or spec.is_free:
            continue
        draft = M.tier_description(spec.key, "draft")
        assert "cheap" not in draft.lower(), (
            f"{spec.key} costs the same at every size, so {draft!r} promises "
            f"a saving that does not exist"
        )


def test_price_lever_tiers_show_distinguishable_prices():
    """Two tiers that cost different amounts must not render identically.

    Found while writing this: at zero decimal places klein-4b's ladder read
    "$1 / $2 / $2" -- two tiers showing the same figure despite costing
    different amounts. A price control whose numbers collide is worse than one
    showing no numbers at all, so the decimal places are chosen to keep them
    apart and this stops that being undone.

    SCOPE, stated honestly: it compares whole labels, so it only fires when
    two tiers are indistinguishable in EVERY part -- caption, size and price
    together. Today the differing caption and size would mask a price
    collision on their own, which means this is a backstop against the labels
    becoming genuinely ambiguous, not a precise assertion about the money
    alone. Verified to fire by making two labels identical.
    """
    for spec in M.ALL_MODELS:
        if not M.tier_changes_price(spec.key):
            continue
        for ratio in M.RATIOS:
            shown, real = [], []
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, spec.key)
                shown.append(M.tier_description(spec.key, tier, ratio))
                real.append(round(spec.cost_per_1000(w, h), 6))
            for i in range(len(M.TIERS)):
                for j in range(i + 1, len(M.TIERS)):
                    if real[i] != real[j]:
                        assert shown[i] != shown[j], (
                            f"{spec.key} {ratio}: {M.TIERS[i]} and {M.TIERS[j]} "
                            f"cost {real[i]} vs {real[j]} but both display as "
                            f"{shown[i]!r}"
                        )


def test_setup_pages_quote_the_registrys_own_prices():
    """The shipped HTML setup pages must not drift from core/models.py.

    The pages bake their figures in as literal text, because they ship beside
    the exe and must open offline with no generation step. That makes them a
    SECOND place a price lives -- exactly the drift make_model_collage.py was
    built to prevent, after a hand-typed collage label got both klein figures
    wrong at once.

    So the numbers are written by hand but VERIFIED here: every price, marker,
    band label, size and neuron rate the pages state is re-derived from the
    registry and must appear in the HTML. Change a price in core/models.py and
    this test names the page that still quotes the old one.

    It checks presence, not context -- a cheap check that catches the whole
    failure mode (a stale number) without pinning the prose around it.
    """
    import re as _re

    root = Path(__file__).resolve().parent.parent
    pages = [p for p in (root / "1 first time setup tutorial.html",
                         root / "2 advanced usage tutorial.html") if p.exists()]
    # Both ship, so finding only one means a rename went half-done -- the
    # failure this catches is a page still named the old thing in the build
    # script while the test silently checks nothing.
    if not pages:
        return                      # source-only checkout: nothing to verify
    assert len(pages) == 2, (
        f"found only {[p.name for p in pages]} -- both setup pages ship "
        f"together. If they were renamed, update this test and "
        f"build_release.bat to match."
    )

    for page in pages:
        html = page.read_text(encoding="utf-8")
        where = page.name

        def needs(text: str, what: str):
            assert text in html, (
                f"{where} does not contain {what} ({text!r}). It is quoted "
                f"from core/models.py -- update the page to match the registry."
            )

        # Every paid model's price and marker, at the size the page quotes.
        # Keyed on the model's DISTINCTIVE name, not a leading word: "FLUX.2"
        # alone matches klein 4B and would then demand 9B's price on a page
        # that deliberately never mentions 9B.
        paid_names = {
            "klein4b": "klein 4B", "klein9b": "klein 9B",
            "p-image": "P-Image", "krea-turbo": "Krea 2 Medium Turbo",
            "krea-medium": "Krea 2 Medium", "flux2pro": "FLUX.2 pro",
            "recraft-utility": "Recraft V4.1 Utility",
            "recraft-v41": "Recraft V4.1",
            "nano-banana-2-lite": "Nano Banana 2 Lite",
            "nano-banana-2": "Nano Banana 2",
        }
        for m in M.ALL_MODELS:
            if m.is_free:
                continue
            assert m.key in paid_names, (
                f"new paid model {m.key!r} -- add it to paid_names here and "
                f"decide whether the setup pages should mention it."
            )
            if paid_names[m.key] not in html:
                continue
            w, h = M.size_for("16:9", "standard", m.key)
            est = M.estimate(m.key, w, h, 1)
            # nano-banana-2 prints a whole tier ladder rather than one price.
            if M.tier_changes_price(m.key) and not m.bills_per_tile:
                for tier in M.TIERS:
                    tw, th = M.size_for("16:9", tier, m.key)
                    p = M.estimate(m.key, tw, th, 1).cost_per_1000
                    needs(f"${p:,.0f}", f"{m.key}'s {tier} price")
            else:
                needs(f"${est.cost_per_1000:,.2f}", f"{m.key}'s price")
            needs(M.cost_tier_marker(m.key), f"{m.key}'s cost marker")

        # The klein lane: measured neuron rates and the free/day estimates.
        # These moved once already (2026-09-06), which is why they are pinned.
        #
        # Only checked where the page actually discusses the model. The slim
        # checklist names klein 4B once, as the "try this next" pointer, and
        # never mentions 9B -- demanding every figure on every page would push
        # the paid detail back into the page whose entire job is leaving it out.
        for key, name in (("klein4b", "klein 4B"), ("klein9b", "klein 9B")):
            spec = M.get_model(key)
            if name not in html:
                continue
            w, h = M.size_for("16:9", "standard", key)
            est = M.estimate(key, w, h, 1)
            assert spec.measured_neurons_per_tile is not None
            # Bounded match: a bare "~7" is a substring of "~75", so klein 9B
            # could go stale while the test still passed on 4B's number.
            assert _re.search(rf"~{est.free_images_per_day}\b", html), (
                f"{where} does not contain {key}'s free images/day "
                f"('~{est.free_images_per_day}'). It is quoted from "
                f"core/models.py -- update the page to match the registry."
            )
            needs(f"${est.cost_per_1000:,.2f}", f"{key}'s price")
            # The reference page prints the measured neuron rate as well; the
            # checklist does not, so pin it only where it appears.
            per_image = f"{spec.measured_neurons_per_tile * est.tiles:.2f}"
            if "neurons" in html.lower() and "Neurons / image" in html:
                needs(per_image, f"{key}'s measured neurons per image")

        # Sizes a user is told to expect. Four models in this lineup return
        # something other than the shared table, so these are not decorative.
        for key in ("lightning", "klein4b", "p-image", "recraft-utility"):
            w, h = M.size_for("16:9", "standard", key)
            if f"{w}×" in html:
                needs(f"{w}×{h}", f"{key}'s Standard 16:9 size")

        # The cost-band vocabulary, wherever a page prints the scale at all.
        if "COST</" in html or "COST<" in html:
            for band, _limit in M.COST_BAND_LIMITS:
                needs(M.COST_BAND_LABELS[band], f"the {band} band label")

        # Lane sizes. Flattening these is the easiest way to mislead someone.
        free_models = [m for m in M.ALL_MODELS if m.is_free]
        gateway = [m for m in M.ALL_MODELS if m.call_style == "gateway"]
        cloudflare = [m for m in M.ALL_MODELS if m.provider == "cloudflare"]
        assert len(free_models) == 5, (
            f"{len(free_models)} free models now, but the setup pages say "
            f"five bill nothing. Update both."
        )
        assert len(gateway) == 8, (
            f"{len(gateway)} gateway models now, but the setup pages say "
            f"eight are on prepaid credit. Update both."
        )
        assert len(cloudflare) == 13, (
            f"{len(cloudflare)} Cloudflare models now, but the setup pages "
            f"and changelog.md both say thirteen. Update them together."
        )

        # The pages must open offline. An INLINE script is fine (the checklist
        # persists its ticks in localStorage); what must never appear is a
        # remote resource, which would render a blank or unstyled page for a
        # user with no connection.
        for banned in ("cdnjs", "googleapis", "gstatic", "unpkg", "jsdelivr",
                       "@import", "src=\"http", "src='http"):
            assert banned not in html.lower(), (
                f"{where} references {banned!r}. These pages ship beside the "
                f"exe and must render with no network."
            )
        assert "<script src" not in html.lower().replace(" ", " "), (
            f"{where} loads an external script; inline it instead."
        )

        # Local images must actually exist, or the page ships with broken
        # frames -- the screenshots live in promo/, which build_release.bat
        # copies into the same release folder.
        from urllib.parse import unquote
        bat = (root / "build_release.bat").read_text(
            encoding="utf-8", errors="replace")
        for rel in _re.findall(r'src="(?!https?:)([^"]+)"', html):
            target = root / unquote(rel)
            assert target.exists(), (
                f"{where} references a missing local file: {rel!r}"
            )
            # Existing in the source tree is not enough -- the page ships in
            # the release folder, so whatever it points at has to be copied
            # there too. assets/icon og (2).jpg was the icon MASTER and was
            # not shipped until the setup pages started using it as artwork.
            # Only actual copy/xcopy lines count -- a mention in a comment
            # ships nothing, and an earlier version of this check was fooled
            # by exactly that.
            copies = [ln for ln in bat.split("\n")
                      if _re.match(r"\s*(copy|xcopy)\s", ln, _re.I)]
            top = unquote(rel).split("/")[0]
            name = unquote(rel).split("/")[-1]
            # A wildcard/recursive copy of the whole folder ships everything
            # under it (promo\* does). Anything else must name the file:
            # assets\ is copied one file at a time, so "assets\icon.ico"
            # existing says nothing about a second asset beside it.
            shipped = any(
                name in ln or f"{top}\\*" in ln
                for ln in copies
            )
            assert shipped, (
                f"{where} shows {rel!r}, but no copy line in "
                f"build_release.bat puts it in the release -- it would be a "
                f"broken image frame in the shipped zip."
            )

        # Never ship a dashboard deep-link carrying a real account ID: it is
        # wrong for every other user, and it puts the author's account ID in
        # a public zip. The /?to=/:account/ form resolves per-reader instead.

        leaked = _re.search(r"dash\.cloudflare\.com/[0-9a-f]{32}", html)
        assert not leaked, (
            f"{where} hard-codes a Cloudflare account ID "
            f"({leaked.group(0)!r}). Use the account-agnostic redirect: "
            f"dash.cloudflare.com/?to=/:account/..."
        )


def test_no_source_file_still_uses_the_old_budget_vocabulary():
    """The whole app describes price with the SAME words.

    Before 2026-09-05 four places wrote their own version of "OVER BUDGET ...
    exceeds the $5.00 ceiling for this project" -- the Provider tab, the Run
    tab's dry-run log, two CLI commands and the paid-generation confirmation
    dialog. That phrasing described this project's internal budget policy,
    which the user has never heard of and cannot act on, and it was binary:
    $5.01 and $151 got the identical sentence.

    They now all render M.COST_BAND_LABELS. This test scans the source so a
    fifth site cannot quietly reintroduce the old vocabulary -- which is
    exactly how the four diverged in the first place.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    files = [root / "cli.py", root / "gui" / "app.py",
             root / "gui" / "tabs" / "provider.py",
             root / "gui" / "tabs" / "run.py"]
    banned = re.compile(r"(OVER BUDGET|budget ceiling|ceiling for this project)")
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            code = line.split("#")[0]          # comments may discuss the change
            assert not banned.search(code), (
                f"{f.name}:{i} still uses the old budget vocabulary -- use "
                f"M.COST_BAND_LABELS so every screen says the same thing: "
                f"{line.strip()!r}"
            )


def test_every_model_has_a_band_label_and_style():
    """No model can reach the GUI without a band, a label and a style.

    The Provider tab indexes COST_BAND_STYLES directly, so a band without an
    entry is a KeyError the moment someone selects that model -- a crash
    nobody would hit until a specific dropdown row was clicked.
    """
    for spec in M.ALL_MODELS:
        band = M.cost_band(spec.key)
        assert band in M.COST_BAND_LABELS, f"{spec.key}: band {band!r}"
        assert band in M.COST_BAND_STYLES, f"{spec.key}: band {band!r}"
        assert band in M.COST_BAND_MARKERS, f"{spec.key}: band {band!r}"


def test_disabled_parameter_boxes_have_something_honest_to_show():
    """Every model can say what its greyed-out Steps and Guidance boxes use.

    The GUI shows a model's fixed value in a disabled box (klein's 4 steps) and
    "n/a" when the model takes no such parameter at all. The two must not read
    the same, so a model claiming a parameter is settable has to actually have
    a default worth showing -- otherwise the box greys out displaying nothing,
    which is what it looked like before and is indistinguishable from an empty
    box waiting for input.

    This is the registry half of that contract; the GUI half (that the
    placeholder is never persisted as a user setting) is exercised by hand
    against the running app, since it needs Tk.
    """
    for spec in M.ALL_MODELS:
        if not spec.steps_settable:
            # Either a known fixed count, or genuinely no such parameter.
            # Both are fine -- what matters is that _param_note can tell them
            # apart, which it does on default_steps being None.
            assert spec.default_steps is None or spec.default_steps > 0, (
                f"{spec.key}: default_steps={spec.default_steps!r} would show "
                f"as a meaningless placeholder in the disabled Steps box"
            )
        if not spec.supports_guidance:
            assert spec.default_guidance is None or spec.default_guidance > 0, (
                f"{spec.key}: default_guidance={spec.default_guidance!r} would "
                f"show as a meaningless placeholder in the disabled box"
            )
        # A model that DOES accept a parameter must have a usable default, or
        # leaving the box empty sends nothing and the model picks its own.
        if spec.steps_settable and spec.default_steps is not None:
            assert spec.max_steps is None or spec.default_steps <= spec.max_steps, (
                f"{spec.key}: default_steps {spec.default_steps} exceeds "
                f"max_steps {spec.max_steps}"
            )


def test_pollinations_never_asks_for_a_size_it_will_not_get():
    """Every Pollinations size fits the MEASURED ~0.59 MP platform cap.

    MEASURED 2026-09-05 with cache-defeating unique prompts, on both models:
    the service silently scales anything larger down to that budget and
    returns HTTP 200 with no error. Asking for 1536x864 returned 1024x576
    while the sidecar recorded 1536x864, because GenerationResult is built
    from the REQUESTED size -- the same silent-wrong-result shape as the
    black-image content filter.

    The four Standard sizes were then each requested against the live API and
    each came back at exactly the size asked for, so this table is verified
    rather than merely computed.
    """
    for key in ("poll-flux", "poll-dreamshaper"):
        assert key in M.SIZE_TABLE_OVERRIDES, (
            f"{key} must own a size table -- without one it falls back to the "
            f"shared SIZES and asks for 1536x864, which is silently clamped"
        )
        for ratio in M.RATIOS:
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, key)
                assert w * h <= M.POLLINATIONS_MAX_PIXELS, (
                    f"{key} {ratio} {tier}: {w}x{h} = {w * h:,} px is above "
                    f"the measured {M.POLLINATIONS_MAX_PIXELS:,} px cap and "
                    f"would be silently downscaled"
                )
                assert w % 8 == 0 and h % 8 == 0, f"{key} {ratio} {tier}: {w}x{h}"


def test_pollinations_ratios_are_exact():
    """A clamped image keeps its ratio, so the tabled ratios must be exact.

    If a tabled size were not exactly the named ratio the user would get a
    subtly different shape than the one they picked -- and because the service
    preserves ratio while scaling, that error would survive the clamp rather
    than being corrected by it.
    """
    expect = {"16:9": (16, 9), "3:2": (3, 2), "1:1": (1, 1),
              "2:3": (2, 3), "9:16": (9, 16)}
    for key in ("poll-flux", "poll-dreamshaper"):
        for ratio, (rw, rh) in expect.items():
            for tier in M.TIERS:
                w, h = M.size_for(ratio, tier, key)
                assert w * rh == h * rw, (
                    f"{key} {ratio} {tier}: {w}x{h} is not exactly {rw}:{rh}"
                )


def test_sd_models_never_default_to_a_size_they_cannot_render_well():
    """The program must not SHIP a default that triggers its own warning.

    Until 2026-09-06 the three SD models used the shared table, so the default
    tier and ratio asked for 1536x864 -- half again their ~1024px training
    size. The images degraded and the program warned about a setting the user
    had never chosen. Standard is now capped to the training size.

    HIGH deliberately still exceeds it: the ability to push past the limit is
    kept as an opt-in via the tier dropdown, and the warning must still fire
    there. A test that only checked "never warns" would quietly bless removing
    that option, so both halves are asserted.
    """
    for key in ("lightning", "sdxl", "dreamshaper"):
        spec = M.get_model(key)
        for ratio in M.RATIOS:
            for tier in ("draft", "standard"):
                w, h = M.size_for(ratio, tier, key)
                assert max(w, h) <= spec.max_safe_dimension, (
                    f"{key} {ratio} {tier} = {w}x{h} exceeds the "
                    f"{spec.max_safe_dimension}px training size"
                )
                assert not spec.size_warnings(w, h), (
                    f"{key} {ratio} {tier} warns on a default the user did "
                    f"not choose: {spec.size_warnings(w, h)}"
                )
                assert w % 16 == 0 and h % 16 == 0, (key, ratio, tier, w, h)

        # High is the opt-in past the limit, and must still say so.
        w, h = M.size_for("16:9", "high", key)
        assert max(w, h) > spec.max_safe_dimension, (
            f"{key} high should still offer the large size as an opt-in"
        )
        assert spec.size_warnings(w, h), (
            f"{key} high exceeds the training size and must still warn"
        )

    # The gateway and klein models are unaffected -- they render these sizes
    # natively, and firing the SD warning there would cry wolf.
    for key in ("klein4b", "nano-banana-2"):
        w, h = M.size_for("16:9", "standard", key)
        assert not M.get_model(key).size_warnings(w, h), key
    print("ok  SD defaults stay inside the training size; High still opts out")


def test_a_paid_model_is_never_retried_but_a_free_one_is():
    """Measured 2026-09-06: a parse bug bought FOUR copies of one p-image.

    A retry on a paid model does not recover the image already billed for --
    it generates and bills another. So the attempt budget is 1 there, while a
    free model keeps the normal budget. The 429 carve-out is the point of the
    split: a rate limit is rejected before it costs anything.
    """
    assert PAID_MAX_ATTEMPTS == 1, "a paid model must get one try and no retry"
    assert DEFAULT_MAX_ATTEMPTS == 3

    def budget(model_key, exc):
        cfg = BatchConfig(
            prompt_file=Path("x.txt"), output_dir=Path("o"), model=model_key
        )
        eng = BatchEngine.__new__(BatchEngine)
        eng.cfg = cfg
        return BatchEngine._attempt_budget(eng, exc)

    boom = TransientError("unreadable")
    assert budget("p-image", boom) == 1, "paid model must not retry"
    assert budget("nano-banana-2", boom) == 1
    assert budget("lightning", boom) == DEFAULT_MAX_ATTEMPTS, "free model retries"

    # A 429 is never billed, so it keeps the full budget even when paid --
    # capping it would fail jobs that cost nothing to recover.
    limited = RateLimited("slow down")
    assert budget("p-image", limited) == DEFAULT_MAX_ATTEMPTS
    assert budget("lightning", limited) == DEFAULT_MAX_ATTEMPTS


def test_an_unreadable_paid_response_fails_permanently():
    """A 200 the program cannot read was still generated and billed.

    Retrying it buys a second copy rather than recovering the first, so on a
    paid model it is PERMANENT. On a free model the same fault costs nothing
    and stays transient.
    """
    paid = M.get_model("p-image")
    free = M.get_model("lightning")
    assert isinstance(
        CloudflareProvider._unreadable(paid, "nope"), PermanentError
    ), "an unreadable paid response must not be retried"
    assert isinstance(
        CloudflareProvider._unreadable(free, "nope"), TransientError
    ), "a free model should still retry -- it costs nothing"


def test_gateway_image_is_found_however_deeply_it_is_nested():
    """MEASURED 2026-09-06: the live gateway nests deeper than documented.

    The real shape is {"result": {"state": ..., "result": {"image": ...}}}.
    Reading a fixed depth returned None on a good response and the retry that
    followed was billed. Both shapes must parse, and a non-Completed state
    must still be caught at whatever level it appears.
    """
    class R:
        headers = {"content-type": "application/json"}
        content = b""

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    spec = M.get_model("p-image")
    nested = {"result": {"state": "Completed",
                         "result": {"image": "https://gw.example/x"}}}
    flat = {"result": {"image": "https://gw.example/y"}}
    for shape in (nested, flat):
        out = CloudflareProvider._extract_image(R(shape), spec)
        # _PresignedURL is a str subclass, so identity is the check here --
        # a bare str would mean the URL was mistaken for image data.
        assert isinstance(out, _PresignedURL), f"no image found in {shape}"
        assert str(out).startswith("https://"), out

    klein = M.get_model("klein4b")
    png_magic = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
    raw = base64.b64encode(png_magic).decode()
    assert CloudflareProvider._extract_image(
        R({"result": {"image": raw}}), klein
    ).startswith(png_magic)

    for bad in ({"result": {"state": "Queued", "result": {}}},
                {"result": {"result": {"state": "Failed"}}}):
        try:
            CloudflareProvider._extract_image(R(bad), spec)
        except Exception as e:
            assert "not Completed" in str(e), f"wrong error for {bad}: {e}"
        else:
            raise AssertionError(f"an incomplete state was accepted: {bad}")


def test_sidecar_flags_a_size_the_provider_quietly_changed():
    """The metadata says outright when delivered size != requested size.

    Two similar keys sitting side by side (`width`/`height` versus
    `actual_dimensions`) leaves the comparison to whoever reads the file
    later, and nobody does. `size_mismatch` states it.
    """
    import inspect
    from core import engine as eng

    src = inspect.getsource(eng)
    assert '"size_mismatch"' in src, (
        "the sidecar must record whether the provider resized the image"
    )
    assert "actual_dimensions" in src



def test_a_one_off_prompt_becomes_a_real_resumable_file(tmp):
    """The override is materialised as a file, not special-cased in the engine.

    The prompt file's PATH is batch identity: it keys find_batch() for resume
    and seeds every filename. Threading a text box through the engine under a
    sentinel path would make two different one-offs collide on one batch row
    and one filename. Writing a real single-line .txt means resume, naming and
    the sidecar's source_file all keep working with no engine change at all.
    """
    a = P.materialize_one_off("a misty forest at dawn", tmp)
    assert a.is_file(), "the one-off must exist on disk as a real file"
    assert a.read_text(encoding="utf-8").strip() == "a misty forest at dawn"

    lines = P.load_prompts(a, "cinematic")
    assert len(lines) == 1, f"a one-off is exactly one prompt, got {len(lines)}"
    assert lines[0].final == "a misty forest at dawn cinematic", (
        "the style suffix must still be appended to a one-off")

    # Same text must resume, not duplicate.
    assert P.materialize_one_off("a misty forest at dawn", tmp) == a, (
        "an identical one-off must reuse its path so the batch resumes")

    # Different text must NOT inherit another prompt's batch. The stem keeps
    # words from BOTH ends of the prompt, so these two genuinely collide on
    # "misty_dawn" -- which is the case the guard exists for, and a pair that
    # merely sanitizes differently would never exercise it.
    b = P.materialize_one_off("a misty forest of tall pines at dawn", tmp)
    c = P.materialize_one_off("a misty forest of dark spruces at dawn", tmp)
    assert b != c, (
        "two prompts sharing a filename stem must still be separate batches — "
        "otherwise the second silently resumes into the first's images")
    assert P.load_prompts(b)[0].original != P.load_prompts(c)[0].original, (
        "a colliding one-off must not overwrite the other's prompt text")
    assert len({a, b, c}) == 3, (
        "different one-off prompts must be different batches")

    # Newlines would silently turn one image into several.
    m = P.materialize_one_off("line one\nline two", tmp)
    assert len(P.load_prompts(m)) == 1, (
        "a multi-line one-off must collapse to ONE prompt, not become several")

    # An empty override is not a runnable batch of one blank image.
    for empty in ("", "   ", "\n\n"):
        try:
            P.materialize_one_off(empty, tmp)
        except ValueError:
            pass
        else:
            raise AssertionError("an empty one-off prompt must be rejected")


def test_one_off_text_persists_outside_config_json(tmp):
    """Free-form user text does not belong wedged into a JSON string field.

    The user may paste anything into that box, so it round-trips through its
    own .txt and config.json's shape stays independent of what they type.
    """
    weird = 'quotes " backslash \\ braces {} dash — tab\there'
    P.write_one_off(tmp, weird)
    assert P.read_one_off(tmp) == weird, (
        "the override text must round-trip intact")

    # Absent on first run, and a failure here must never block the GUI build.
    assert P.read_one_off(Path(tmp) / "nope") == "", (
        "an absent override file must read as empty, not raise")


def test_shipped_recipes_doc_actually_parses() -> None:
    """recipes.md is a runtime input, so its format is load-bearing.

    The Helpers tab is built from it. An edit that removes or mangles the
    markers leaves the tab empty, and nothing else in the program would
    notice -- which is exactly why this is pinned here.
    """
    data = RC.load()
    assert data.found, "recipes.md must ship and be findable from source"
    assert data.links, "the <links> block must still parse into links"
    assert data.recipes, "at least one <recipe> block must still parse"

    for link in data.links:
        assert link.url.startswith("http"), f"bad url: {link!r}"
        assert link.name, f"link with no name: {link!r}"

    # Every recipe the GUI captions must still exist under that name: the
    # captions are keyed by name, so a rename silently drops the caption.
    from gui.tabs.helpers import CAPTIONS
    names = {r.name for r in data.recipes}
    missing = set(CAPTIONS) - names
    assert not missing, (
        f"CAPTIONS names recipes that recipes.md no longer has: {missing}")


def test_recipe_parser_ignores_prose_and_unmarked_fences() -> None:
    """Markers match intent, not shape.

    The whole reason for the tags is that shape-matching captures prose added
    later. A bullet with a URL in an unrelated section, and a fenced block
    that is only an illustration, must both stay out of the GUI.
    """
    doc = """
# Doc

<links>
Claude - https://claude.ai
Some Name - With - Dashes - https://example.com
not a link at all
</links>

Here is an illustrative block that is NOT a recipe:

```
this must never become a button
```

<recipe name="Real One">
```
the real prompt
YOUR_TEXT
```
</recipe>

## Recovering

- Check https://example.org/help for more, which is not an assistant link.
"""
    data = RC.parse(doc)

    assert [l.name for l in data.links] == ["Claude", "Some Name - With - Dashes"], (
        "links must come only from the <links> block, splitting on the LAST "
        "separator so a dashed name survives")
    assert all("example.org" not in l.url for l in data.links), (
        "a URL in unrelated prose must never become a link")

    assert [r.name for r in data.recipes] == ["Real One"], (
        "only fenced blocks inside <recipe> tags become buttons")
    assert data.recipes[0].text == "the real prompt\nYOUR_TEXT", (
        "the fence itself must not end up on the clipboard")


def test_broken_recipes_doc_degrades_instead_of_raising() -> None:
    """A user can edit this file in Notepad and break it.

    A broken document must produce an empty tab that says so, never a program
    that will not start -- and "found but unparseable" must stay
    distinguishable from "missing", because the two have opposite fixes.
    """
    for junk in ("", "no markers here at all", "<links>", "<recipe name=",
                 "<recipe name=\"x\">\n```\n", "\x00\xff binary-ish"):
        data = RC.parse(junk)
        assert data.empty, f"expected nothing parsed from {junk!r}"
        assert data.links == () and data.recipes == ()

    # Missing and empty are different states.
    assert not RC.Recipes((), (), None).found
    assert RC.Recipes((), (), Path("x.md")).found


def test_recipes_placeholders_are_double_clickable() -> None:
    """Placeholders are single tokens so one double-click selects them.

    They were `[BRACKETED PHRASES]`, which a double-click cannot select.
    """
    for recipe in RC.load().recipes:
        assert "[" not in recipe.text and "]" not in recipe.text, (
            f"{recipe.name}: bracketed placeholders are not double-clickable")
        for token in ("YOUR_TEXT", "YOUR_PROMPT", "DESCRIBE_THE_LOOK_YOU_WANT"):
            if token in recipe.text:
                break
        else:
            raise AssertionError(
                f"{recipe.name}: no recognisable placeholder token")


def main() -> int:
    import shutil
    import tempfile

    tests = [
        test_prompt_loader_crlf,
        test_sizes_are_valid_for_every_model,
        test_pricing_matches_published_tables,
        test_filenames_are_deterministic_and_safe,
        test_filenames_stay_short_and_distinguishing,
        test_a_changed_style_suffix_changes_the_filename,
        test_the_hash_covers_every_image_affecting_setting,
        test_style_suffix_is_part_of_batch_identity,
        test_regenerate_requeues_finished_jobs,
        test_overwrite_does_not_redo_a_finished_batch,
        test_regenerate_respects_the_generate_slider,
        test_content_block_is_never_retried,
        test_transient_is_retried_then_succeeds,
        test_attempts_are_capped,
        test_rate_limit_is_retried,
        test_quota_exhausted_429_is_not_retried,
        test_plain_429_is_still_rate_limited,
        test_quota_exhausted_stops_the_batch_without_failing_the_job,
        test_crash_recovery_refunds_the_attempt,
        test_overwrite_protection,
        test_limit_takes_the_first_n_prompts,
        test_limit_none_and_oversize_mean_everything,
        test_length_advice_grades_against_the_model,
        test_negative_layers_compose_and_dedupe,
        test_gateway_data_uri_and_bare_base64_both_decode,
        test_gateway_incomplete_state_is_transient,
        test_gateway_402_is_quota_not_bad_request,
        test_gateway_7003_is_permanent_and_named,
        test_gateway_payload_shape,
        test_gateway_pricing_is_flat_and_tiles_are_suppressed,
        test_cost_tier_markers_match_the_decided_scheme,
        test_pimage_sizes_respect_its_own_cap,
        test_krea_returns_a_url_not_bytes,
        test_presigned_fetch_never_sends_the_api_token,
        test_presigned_fetch_failures_are_transient,
        test_krea_payload_uses_the_ratio_enum_not_pixels,
        test_krea_has_no_tier_ladder,
        test_krea_pair_prices_and_markers,
        test_prompt_expansion_is_always_sent_and_matches_the_vendor_default,
        test_prompt_expansion_is_only_sent_where_supported,
        test_reference_fields_are_never_sent_to_the_models_that_cannot_serve_them,
        test_reference_image_helpers_are_derived_from_the_registry,
        test_only_one_reference_is_sent_and_always_at_index_zero,
        test_klein_sends_the_reference_as_a_multipart_part,
        test_the_64px_floor_is_enforced_per_side_client_side,
        test_upscale_is_nearest_and_downscale_is_lanczos,
        test_the_ratio_guard_accepts_its_exact_endpoints,
        test_pixel_art_detection_and_the_manual_override,
        test_a_ratio_mismatch_warns_and_never_refuses,
        test_the_hash_follows_the_bytes_not_the_path,
        test_hash_parts_are_unchanged_when_no_reference_is_set,
        test_an_unusable_reference_fails_the_dry_run_too,
        test_reference_influence_phrase_is_per_model_and_off_by_default,
        test_with_influence_never_edits_the_users_text,
        test_a_changed_influence_is_a_changed_batch_and_a_changed_name,
        test_a_changed_reference_is_a_changed_BATCH_not_just_a_changed_name,
        test_flux2pro_takes_true_pixels_on_the_shared_size_table,
        test_flux2pro_is_a_gateway_model_priced_flat_at_30,
        test_safety_tolerance_5_is_the_permissive_end_not_0,
        test_content_filter_default_sends_nothing_at_all,
        test_both_filter_controls_get_the_same_treatment,
        test_output_format_wire_spelling_is_jpeg_not_jpg,
        test_every_size_enum_model_owns_a_size_table,
        test_recraft_sends_a_validated_size_enum_not_pixels,
        test_recraft_bad_size_fails_locally_before_it_can_be_billed,
        test_recraft_size_default_is_a_square_so_size_is_always_sent,
        test_recraft_has_no_seed_and_no_tier_ladder,
        test_seedless_model_records_no_seed_in_its_metadata,
        test_recraft_is_a_flat_priced_gateway_model_returning_a_url,
        test_recraft_16x9_is_smaller_than_the_programs_standard,
        test_nano_banana_sends_a_ratio_and_a_resolution_word_never_pixels,
        test_nano_banana_resolution_is_looked_up_never_derived_from_the_tier,
        test_nano_banana_price_follows_the_resolution_not_a_flat_number,
        test_nano_banana_output_format_is_jpg_not_jpeg,
        test_nano_banana_has_no_seed_and_records_none,
        test_nano_banana_sizes_are_published_not_estimated,
        test_nano_banana_is_a_gateway_model_returning_a_url,
        test_nano_banana_2_has_a_real_tier_ladder_that_changes_the_price,
        test_nano_banana_2_is_dollar_dollar_dollar_at_every_tier,
        test_cost_tier_marker_prices_a_model_at_a_size_it_can_serve,
        test_nano_banana_grounding_fields_are_never_sent,
        test_nano_banana_2_4k_does_not_trigger_a_degradation_warning,
        test_model_dropdown_labels_fit_the_combobox,
        test_price_notes_read_as_guidance_not_as_engineering_notes,
        test_tier_labels_fit_the_tier_combobox,
        test_only_nano_banana_2_has_a_tier_that_changes_price,
        test_tier_labels_never_promise_a_saving_that_does_not_exist,
        test_price_lever_tiers_show_distinguishable_prices,
        test_no_source_file_still_uses_the_old_budget_vocabulary,
        test_setup_pages_quote_the_registrys_own_prices,
        test_every_model_has_a_band_label_and_style,
        test_disabled_parameter_boxes_have_something_honest_to_show,
        test_pollinations_never_asks_for_a_size_it_will_not_get,
        test_pollinations_ratios_are_exact,
        test_sidecar_flags_a_size_the_provider_quietly_changed,
        test_sd_models_never_default_to_a_size_they_cannot_render_well,
        test_a_paid_model_is_never_retried_but_a_free_one_is,
        test_an_unreadable_paid_response_fails_permanently,
        test_gateway_image_is_found_however_deeply_it_is_nested,
        test_a_one_off_prompt_becomes_a_real_resumable_file,
        test_one_off_text_persists_outside_config_json,
        test_shipped_recipes_doc_actually_parses,
        test_recipe_parser_ignores_prose_and_unmarked_fences,
        test_broken_recipes_doc_degrades_instead_of_raising,
        test_recipes_placeholders_are_double_clickable,
    ]
    failed = 0
    for t in tests:
        needs_tmp = "tmp" in t.__code__.co_varnames[: t.__code__.co_argcount]
        d = Path(tempfile.mkdtemp(prefix="batchgen_test_"))
        try:
            t(d) if needs_tmp else t()
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
