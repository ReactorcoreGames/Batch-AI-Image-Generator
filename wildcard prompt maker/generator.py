"""
Pure logic for expanding a template + wildcard sets into a list of prompts.
No tkinter here, so it can be tested/reused independently of the GUI.
"""

import itertools
import re
import os


WILDCARD_PATTERN = re.compile(r"\{([^{}]+)\}")


def find_wildcards_in_template(template):
    """Return the list of {name} wildcard names used in the template, in order, de-duplicated."""
    seen = []
    for name in WILDCARD_PATTERN.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def parse_entries(raw_text):
    """Split a comma-separated entries string into a clean list, dropping empties."""
    parts = [p.strip() for p in raw_text.split(",")]
    return [p for p in parts if p]


def generate_prompts(template, wildcard_sets):
    """
    template: str containing {label} placeholders
    wildcard_sets: dict of label -> list of entry strings
    Returns (lines, warnings) where lines is the generated prompt list and
    warnings is a list of human-readable problems (unused sets, missing sets, empty sets).
    """
    warnings = []
    used_names = find_wildcards_in_template(template)

    missing = [name for name in used_names if name not in wildcard_sets]
    if missing:
        warnings.append(
            "Template uses {%s} but there is no wildcard set with that label."
            % "}, {".join(missing)
        )

    empty = [name for name in used_names if name in wildcard_sets and not wildcard_sets[name]]
    if empty:
        warnings.append(
            "Wildcard set(s) with no entries: %s" % ", ".join(empty)
        )

    unused = [label for label in wildcard_sets if label not in used_names]
    if unused:
        warnings.append(
            "Wildcard set(s) not referenced in the template (ignored): %s" % ", ".join(unused)
        )

    if missing or empty:
        return [], warnings

    if not used_names:
        return [template], warnings

    value_lists = [wildcard_sets[name] for name in used_names]
    lines = []
    for combo in itertools.product(*value_lists):
        substitutions = dict(zip(used_names, combo))
        lines.append(template.format(**substitutions))

    return lines, warnings


def write_prompts_file(output_path, lines):
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def unique_output_path(folder, filename):
    """If filename already exists in folder, the caller decides overwrite vs rename;
    this just builds the full path."""
    return os.path.join(folder, filename)
