#!/usr/bin/env python3
"""Batch AI image generation — command line interface.

This is a real, documented feature, not a test harness: it ships alongside the
GUI and is covered in guide.md.

    python cli.py models
    python cli.py check
    python cli.py estimate --model klein4b --ratio 16:9 --tier standard --count 500
    python cli.py dry-run  test_prompts.txt -o out --style test_style_prompt_addon.txt
    python cli.py run      test_prompts.txt -o out --style test_style_prompt_addon.txt
    python cli.py resume   test_prompts.txt -o out
    python cli.py retry-failed test_prompts.txt -o out
    python cli.py status   -o out

Credentials are read from `credentials.json` next to the program -- the same
file the GUI writes -- or from the environment (CLOUDFLARE_ACCOUNT_ID,
CLOUDFLARE_API_TOKEN, POLLINATIONS_API_KEY), which takes priority. They are
never read from or written to the job database.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core import db as dbmod
from core import models as M
from core import reference as R
from core import prompts as P
from core.engine import (
    DEFAULT_CONCURRENCY,
    DEFAULT_DELAY,
    DEFAULT_MAX_ATTEMPTS,
    PAID_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
    BatchConfig,
    BatchEngine,
    Progress,
)
from core.imagecheck import CONVERT_FORMATS
from core.providers import PollinationsProvider, get_provider
from core.providers.cloudflare import USAGE_DASHBOARD_URL
from utils.credentials import apply_to_environment


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def money(x: float) -> str:
    return "free" if x <= 0 else f"${x:,.4f}" if x < 0.01 else f"${x:,.2f}"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_models(args: argparse.Namespace) -> int:
    w, h = M.size_for(args.ratio, args.tier)
    print(f"Models — priced at {args.ratio} '{args.tier}' tier\n")
    hdr = f"{'key':<18} {'provider':<12} {'size':<11} {'$/1000':>12}  notes"
    print(hdr)
    print("-" * len(hdr))
    for m in M.ALL_MODELS:
        mw, mh = M.size_for(args.ratio, args.tier, m.key)
        est = M.estimate(m.key, mw, mh)
        notes = []
        if est.errors:
            notes.append("UNSUPPORTED at this size")
        # Cost BAND, not a binary over/under. See core.models.COST_BAND_*:
        # the old flag gave $5.01 and $151 the identical word.
        band = M.cost_band_for_price(est.cost_per_1000)
        if band not in ("free", "low"):
            notes.append(M.COST_BAND_LABELS[band])
        if est.warnings:
            notes.append("quality warning above ~1024px")
        # Column widths: 18 fits "nano-banana-2-lite" and 12 fits the price
        # plus a four-character EXTREME marker. Both were overflowing and
        # ragging the table -- the price field was padded to 9 while
        # "$101.00 $$$$" is 12.
        marker = M.cost_tier_marker(m.key)
        price = "free" if m.is_free else f"${est.cost_per_1000:,.2f} {marker}"
        print(
            f"{m.key:<18} {m.provider:<12} {mw}x{mh:<6} {price:>12}  "
            + "; ".join(notes)
        )
    bands = " · ".join(
        f"{M.COST_BAND_LABELS[b]} ≤ ${lim:,.0f}"
        for b, lim in M.COST_BAND_LIMITS)
    print(f"\nDefault: {M.DEFAULT_MODEL}")
    print(f"Cost bands (per 1000 images): {bands} · "
          f"{M.COST_BAND_LABELS['extreme']} above "
          f"${M.COST_BAND_LIMITS[-1][1]:,.0f}")
    print("\nSizes (tile-optimal — every entry is the largest exact-ratio, "
          "multiple-of-16 size fitting its tile count):")
    print(f"  {'ratio':<7}" + "".join(f"{t:<16}" for t in M.TIERS))
    for r in M.RATIOS:
        row = f"  {r:<7}"
        for t in M.TIERS:
            sw, sh = M.size_for(r, t)
            row += f"{f'{sw}x{sh}':<10}{f'({M.tile_count(sw, sh)}t)':<6}"
        print(row)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    rc = 0
    for name in ("cloudflare", "pollinations"):
        if args.provider and args.provider != name:
            continue
        if name == "pollinations" and args.no_key:
            p = PollinationsProvider(api_key="")
        else:
            p = get_provider(name)
        with p:
            ok, msg = p.check()
        print(f"[{'OK ' if ok else 'FAIL'}] {msg}")
        if not ok and name == "cloudflare":
            rc = 1
    print(f"\nUsage dashboard: {USAGE_DASHBOARD_URL}")
    print("Note: the API's neuron counter reads 0 even for models that bill, "
          "so in-app figures are client-side estimates. See SPIKE_RESULTS.md.")
    return rc


def cmd_estimate(args: argparse.Namespace) -> int:
    w, h = (args.width, args.height) if args.width and args.height else \
        M.size_for(args.ratio, args.tier, args.model)
    est = M.estimate(args.model, w, h, args.count)
    spec = M.get_model(args.model)

    print(f"model            {spec.key}  ({spec.id})")
    # Tiles are Cloudflare's NATIVE billing unit. Gateway models bill flat per
    # image, so a tile count beside one is meaningless -- see models.py.
    if est.bills_per_tile:
        print(f"size             {w}x{h}   {est.tiles} tile(s), {est.megapixels} MP")
    else:
        print(f"size             {w}x{h}   {est.megapixels} MP (billed flat "
              f"per image, not per tile)")
    print(f"cost per image   {money(est.cost_per_image)}")
    print(f"cost per 1000    {money(est.cost_per_1000)}")
    print(f"{args.count} image(s)   {money(est.total_cost)}")
    if est.free_images_per_day is not None:
        print(f"free tier        ~{est.free_images_per_day} images/day (ESTIMATE)")
    elif est.is_free:
        print("free tier        free model — no neuron cost")
    else:
        # Paid, but NOT against the daily neuron allowance. Saying "free
        # model" here (the old else-branch) would have been flatly wrong.
        print("free tier        n/a — billed from prepaid credit, not the "
              "daily neuron allowance")
    if spec.price_note:
        print(f"note             {spec.price_note}")
    if spec.licence:
        print(f"licence          {spec.licence}")
    for e in est.errors:
        print(f"ERROR            {e}")
    for wn in est.warnings:
        print(f"WARNING          {wn}")
    # Cost band, in the SAME words the GUI uses. The top band leads with the
    # batch TOTAL -- the number that actually lands on the card -- because the
    # same sentence at $15 and at $151 is a warning users learn to skip.
    band = M.cost_band_for_price(est.cost_per_1000)
    if band not in ("free", "low"):
        label = M.COST_BAND_LABELS[band]
        print(f"cost band        {label} — "
              f"${est.cost_per_1000:,.2f} per 1000 images")
        if band == "extreme":
            print(f"                 this run of {est.count} image(s) costs "
                  f"about ${est.total_cost:,.2f} — intended for occasional "
                  f"single images, NOT batch work")
    return 1 if est.errors else 0


def resolve_prompt_file(args: argparse.Namespace) -> Path:
    """The prompt file to run, honouring the --prompt one-off override.

    `--prompt "text"` is the CLI half of the GUI's single-custom-prompt box,
    and it works the same way: the text is written to a real single-line .txt
    inside the output folder and handed to the engine as an ordinary file. The
    engine has no notion of a one-off run, and deliberately so -- the prompt
    file's path keys batch identity and seeds every filename.
    """
    text = (getattr(args, "prompt", None) or "").strip()
    if text:
        return P.materialize_one_off(text, args.output)
    if not getattr(args, "prompt_file", None):
        raise SystemExit(
            "error: give a prompt file, or --prompt \"one prompt\" to "
            "generate a single image without one")
    return Path(args.prompt_file)


def build_config(args: argparse.Namespace) -> BatchConfig:
    return BatchConfig(
        prompt_file=resolve_prompt_file(args),
        output_dir=Path(args.output),
        model=args.model,
        ratio=args.ratio,
        tier=args.tier,
        width=args.width,
        height=args.height,
        style_file=Path(args.style) if args.style else None,
        style_suffix=args.style_text or "",
        # A one-off is exactly one image, whatever --limit says.
        limit=1 if getattr(args, "prompt", None) else getattr(args, "prompt_limit", None),
        negative_prompt=args.negative,
        guidance=args.guidance,
        prompt_expansion=getattr(args, "prompt_expansion", None),
        content_filter=getattr(args, "content_filter", None),
        reference_image=(Path(args.reference_image)
                         if getattr(args, "reference_image", None) else None),
        reference_resample=getattr(args, "reference_resample",
                                   R.DEFAULT_RESAMPLE),
        reference_influence=getattr(args, "reference_influence",
                                    R.DEFAULT_INFLUENCE),
        steps=args.steps,
        seed=args.seed,
        random_seed=args.seed is None,
        concurrency=args.concurrency,
        delay=args.delay,
        max_attempts=args.max_attempts,
        timeout=args.timeout,
        overwrite=args.overwrite,
        output_format=args.format,
        jpeg_quality=args.jpeg_quality,
    )


def provider_for(args: argparse.Namespace):
    """Build the provider, honouring --no-key.

    Mirrors the GUI's "Pollinations - no key needed" mode: with a key saved,
    the provider would otherwise pick it up from the environment and the
    keyless lane could not be exercised deliberately. Returns None to let the
    engine construct its own provider as usual.
    """
    spec = M.get_model(args.model)
    if spec.provider == "pollinations" and getattr(args, "no_key", False):
        return PollinationsProvider(api_key="")   # explicit empty: send no key
    return None


def cmd_dry_run(args: argparse.Namespace) -> int:
    with BatchEngine(build_config(args)) as eng:
        info = eng.dry_run()

    print(f"prompt file      {info['prompt_file']}")
    print(f"output dir       {info['output_dir']}")
    print(f"jobs             {info['jobs']}")
    print(f"model            {info['model']}  ({info['model_id']})")
    if info.get("bills_per_tile", True):
        print(f"size             {info['size']}  ({info['ratio']} / {info['tier']}, "
              f"{info['tiles']} tiles, {info['megapixels']} MP)")
    else:
        print(f"size             {info['size']}  ({info['ratio']} / {info['tier']}, "
              f"{info['megapixels']} MP, billed flat per image)")
    print(f"cost per image   {money(info['cost_per_image'])}")
    print(f"cost per 1000    {money(info['cost_per_1000'])}")
    print(f"TOTAL            {money(info['total_cost'])}")
    if info["free_images_per_day"] is not None:
        print(f"free tier        ~{info['free_images_per_day']} images/day (ESTIMATE)")
    for wn in info["warnings"]:
        print(f"WARNING          {wn}")
    for e in info["errors"]:
        print(f"ERROR            {e}")
    band = M.cost_band_for_price(info["cost_per_1000"])
    if band not in ("free", "low"):
        print(f"cost band        {M.COST_BAND_LABELS[band]} — "
              f"${info['cost_per_1000']:,.2f} per 1000 images")
        if band == "extreme":
            print(f"                 THIS BATCH: ${info['total_cost']:,.2f} "
                  f"for {info['jobs']} image(s) — intended for occasional "
                  f"single images, NOT batch work")
    # The reference, printed the same way the GUI's status label renders it:
    # both consume the ONE PreparedReference from core.reference rather than
    # each deciding for themselves what will be sent. A dry run is where a
    # user checks before paying, so the TRANSFORMATION belongs here and not
    # just the path -- a 16x16 sprite going out at 1024x1024 is the
    # surprising part, and it is the part a path alone hides.
    ref = info.get("reference")
    if ref is not None:
        print(f"reference image  {ref['path']}")
        print(f"                 {ref['describe']}")
        for wn in ref["warnings"]:
            print(f"                 {wn}")
        if info.get("reference_influence"):
            print(f"influence        adds “{info['reference_influence']}” "
                  f"to every prompt")
    elif info.get("reference_requested") and not info.get("reference_supported", True):
        # Said out loud rather than silently dropped: on a model with no
        # reference field the batch still runs, and the user should not have
        # to work out from the images that their reference was ignored.
        print(f"reference image  ignored — {info['model']} accepts none. "
              f"Use {M.reference_models_sentence()}.")
    if info["style_suffix"]:
        print(f"\nstyle suffix     {info['style_suffix'][:100]}...")
    print("\njobs:")
    for ln in info["lines"]:
        print(f"  {ln['line_no']:>3}  {ln['filename']}")
        print(f"       {ln['original'][:96]}")
    print("\n(dry run — no API calls were made)")
    return 1 if info["errors"] else 0


def _progress_printer() -> "callable":
    last = [""]

    def show(p: Progress) -> None:
        line = (
            f"\r{p.finished}/{p.total}  done={p.done} failed={p.failed} "
            f"blocked={p.blocked} skipped={p.skipped} inflight={p.in_flight} "
            f"{p.elapsed:.0f}s {money(p.cost)}"
        )
        if line != last[0]:
            sys.stdout.write(line.ljust(len(last[0])))
            sys.stdout.flush()
            last[0] = line

    return show


def _run(args: argparse.Namespace, retry_failed: bool,
         regenerate: bool = False) -> int:
    cfg = build_config(args)
    show = None if args.quiet else _progress_printer()
    with BatchEngine(cfg, provider=provider_for(args),
                     on_progress=show) as eng:
        batch_id = eng.prepare()
        try:
            p = eng.run(retry_failed=retry_failed, regenerate=regenerate)
        except KeyboardInterrupt:
            eng.cancel()
            print("\ncancelled — rerun `resume` to continue where this left off")
            return 130
        if show:
            print()
        print(
            f"batch {batch_id}: {p.done} done, {p.failed} failed, "
            f"{p.blocked} blocked, {p.skipped} skipped in {p.elapsed:.0f}s "
            f"— estimated cost {money(p.cost)}"
        )
        if p.blocked:
            print(f"{p.blocked} prompt(s) refused by the content filter. These "
                  "are NOT retried — rewrite the prompts.")
        if p.failed:
            print(f"{p.failed} job(s) failed. Rerun with `retry-failed` to "
                  "attempt them again.")
        if eng.quota_exhausted:
            print(f"stopped: {eng.quota_exhausted}. This is expected on the "
                  "free daily allowance, not an error — remaining prompts are "
                  "still queued, rerun `resume` later once the allowance resets "
                  "(the reset time is not reliable, so just try again after a "
                  "while).")
    return 1 if (p.failed or p.blocked) else 0


def cmd_run(args: argparse.Namespace) -> int:
    return _run(args, retry_failed=False)


def cmd_resume(args: argparse.Namespace) -> int:
    return _run(args, retry_failed=False)


def cmd_retry_failed(args: argparse.Namespace) -> int:
    return _run(args, retry_failed=True)


def cmd_regenerate(args: argparse.Namespace) -> int:
    return _run(args, retry_failed=False, regenerate=True)


def cmd_status(args: argparse.Namespace) -> int:
    db_path = Path(args.output) / ".batchgen.db"
    if not db_path.exists():
        print(f"no batch database at {db_path}")
        return 1
    with dbmod.JobStore(db_path) as store:
        batches = store.list_batches(limit=args.limit)
        if not batches:
            print("no batches recorded")
            return 0
        for b in batches:
            c = store.counts(b["id"])
            print(
                f"batch {b['id']}  {Path(b['source_file']).name}  {b['model']}  "
                f"{b['width']}x{b['height']}  created {b['created_at']}"
            )
            print(
                f"    total={c['total']} done={c['done']} pending={c['pending']} "
                f"failed={c['failed']} blocked={c['blocked']} skipped={c['skipped']} "
                f"  cost {money(store.total_cost(b['id']))}"
            )
            if args.verbose:
                for j in store.jobs(b["id"]):
                    mark = {"done": "ok", "failed": "!!", "blocked": "XX",
                            "skipped": "--", "pending": "..", "running": ">>"}[j.status]
                    print(f"      [{mark}] {j.line_no:>3} {j.original_prompt[:60]}")
                    if j.error:
                        print(f"           {j.error[:110]}")
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cli.py",
        description="Batch AI image generation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    def add_size_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", default=M.DEFAULT_MODEL,
                       help=f"model key (default: {M.DEFAULT_MODEL})")
        p.add_argument("--ratio", default=M.DEFAULT_RATIO, choices=list(M.RATIOS))
        p.add_argument("--tier", default=M.DEFAULT_TIER, choices=list(M.TIERS))
        p.add_argument("--width", type=int, help="override the ratio/tier size")
        p.add_argument("--height", type=int)

    def add_batch_opts(p: argparse.ArgumentParser) -> None:
        # Optional so --prompt can stand in for it. A missing file with no
        # --prompt is caught by resolve_prompt_file() with a message that
        # names both ways of supplying one, which argparse's own "required"
        # error could not do.
        p.add_argument("prompt_file", nargs="?",
                       help="a .txt file, one prompt per line")
        p.add_argument("--prompt", metavar="TEXT",
                       help="generate ONE image from TEXT instead of reading "
                            "a prompt file — for trying an idea before it is "
                            "worth writing a file for. The style suffix and "
                            "every other setting still apply.")
        p.add_argument("-o", "--output", required=True, help="output directory")
        p.add_argument("--style", help="file holding the style suffix")
        p.add_argument("--style-text", help="style suffix given inline; wins "
                                            "over --style if both are set")
        p.add_argument("--limit", dest="prompt_limit", type=int, metavar="N",
                       help="generate only the first N prompts in the file — "
                            "for trying a style on a few before committing to "
                            "the whole batch")
        add_size_opts(p)
        p.add_argument("--negative", help="negative prompt (SD models only)")
        p.add_argument("--guidance", type=float)
        p.add_argument("--steps", type=int, help="ignored where not settable (klein)")
        p.add_argument(
            "--prompt-expansion", choices=list(M.PROMPT_EXPANSION_MODES),
            default=M.DEFAULT_PROMPT_EXPANSION,
            help="krea only: how much the model may REWRITE your prompt "
                 "before generating. Default 'raw' (off) — note the API's own "
                 "default is 'low', i.e. on. Expansion rewrites the style "
                 "suffix as well as the subject, so keep it off for prompts "
                 "you have written carefully.")
        p.add_argument(
            "--content-filter", choices=list(M.CONTENT_FILTER_MODES),
            default=M.DEFAULT_CONTENT_FILTER,
            help="p-image and FLUX.2 pro only: how strict the provider's own "
                 "content filter should be. Defaults to 'permissive' - the "
                 "loosest setting the model offers - because a spurious "
                 "refusal in a batch costs a slot in an overnight run, and "
                 "these are the only two models with any lever against it. "
                 "'default' hands the decision back to the provider by "
                 "sending nothing. This does not disable moderation. Every "
                 "other model in the lineup exposes no filter control at all "
                 "and ignores this.")
        p.add_argument(
            "--reference-image", metavar="PATH",
            help="one style reference image, sent with EVERY prompt in the "
                 "batch. Works on the FLUX.2 klein pair, the Nano Banana pair "
                 "and FLUX.2 pro; every other model accepts no such field and "
                 "ignores it (with a log line, not an error). PNG, JPEG or "
                 "WebP; any size and any roughly-square shape - it is resized "
                 "to about 1 megapixel for you, and anything under 64px a "
                 "side is enlarged because the models reject it outright.")
        p.add_argument(
            "--reference-resample", choices=list(R.RESAMPLE_MODES),
            default=R.DEFAULT_RESAMPLE,
            help="how the reference is resized. 'auto' (the default) detects "
                 "pixel art and keeps its hard edges with nearest-neighbour, "
                 "smoothing anything else with lanczos. Override it when you "
                 "know better than the detector.")
        p.add_argument(
            "--reference-influence", choices=list(R.INFLUENCE_MODES),
            default=R.DEFAULT_INFLUENCE,
            help="add a sentence to the end of every prompt asking the model "
                 "to follow the reference, e.g. 'medium' adds \"Medium "
                 "influence from image 0.\" (klein's wording; other models "
                 "say \"the reference image\"). Even 'none' adds a sentence. "
                 "Only applied when --reference-image "
                 "is given and the model accepts one. No model offers a real "
                 "strength setting - this is wording, not a weight.")
        p.add_argument("--seed", type=int,
                       help="fixed seed for every image; omit for random per image")
        p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                       help=f"parallel requests (default {DEFAULT_CONCURRENCY}; "
                            "kept low on purpose — free tiers are a courtesy)")
        p.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                       help=f"seconds between requests (default {DEFAULT_DELAY})")
        p.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS,
                       help=f"total tries per image, not retries (default "
                            f"{DEFAULT_MAX_ATTEMPTS}). PAID models are capped "
                            f"at {PAID_MAX_ATTEMPTS} regardless, because a "
                            "retry is billed as a new image; rate limits are "
                            "exempt, being rejected before they cost anything")
        p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
        p.add_argument("--format", default="keep",
                       choices=list(CONVERT_FORMATS),
                       help="re-encode locally after downloading. 'keep' saves "
                            "exactly what arrived and is always best quality")
        p.add_argument("--jpeg-quality", type=int, default=95,
                       help="quality for --format jpg (default 95)")
        p.add_argument("--no-key", action="store_true",
                       help="pollinations: ignore any saved API key and use "
                            "the keyless lane deliberately")
        p.add_argument("--overwrite", action="store_true",
                       help="regenerate images that already exist (off by default)")
        p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("models", help="list models, prices and sizes")
    p.add_argument("--ratio", default=M.DEFAULT_RATIO, choices=list(M.RATIOS))
    p.add_argument("--tier", default=M.DEFAULT_TIER, choices=list(M.TIERS))
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("check", help="validate credentials and reachability")
    p.add_argument("--provider", choices=["cloudflare", "pollinations"])
    p.add_argument("--no-key", action="store_true",
                   help="pollinations: test the keyless lane even if a key is saved")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("estimate", help="cost for N images (no API calls)")
    add_size_opts(p)
    p.add_argument("--count", type=int, default=1000)
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("dry-run", help="job list + cost estimate, zero API calls")
    add_batch_opts(p)
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("run", help="generate the batch")
    add_batch_opts(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("resume", help="continue a batch, skipping finished jobs")
    add_batch_opts(p)
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("retry-failed", help="requeue failed jobs (never blocked ones)")
    add_batch_opts(p)
    p.set_defaults(func=cmd_retry_failed)

    p = sub.add_parser(
        "regenerate",
        help="generate finished jobs AGAIN, replacing their images "
             "(charges the full batch again on a paid model)")
    add_batch_opts(p)
    p.set_defaults(func=cmd_regenerate)

    p = sub.add_parser("status", help="show recorded batches")
    p.add_argument("-o", "--output", required=True, help="output directory")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--verbose", action="store_true", help="list individual jobs")
    p.set_defaults(func=cmd_status)

    return ap


def main(argv: list[str] | None = None) -> int:
    # Output redirected to a file or pipe on Windows is encoded with the ANSI
    # code page (cp1252), which has no "→" or "—" -- and the reference and
    # cost lines use both, so a dry-run piped anywhere crashed mid-report.
    # UTF-8 is what a pipe should carry anyway; a real console already
    # prints Unicode and is unaffected. errors="replace" is the backstop.
    for stream in (sys.stdout, sys.stderr):
        if (stream.encoding or "").lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    # Same file the GUI writes. Real environment variables still win.
    apply_to_environment()
    setup_logging(getattr(args, "verbose", False) and args.command != "status")
    try:
        return args.func(args)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"error: file not found: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
