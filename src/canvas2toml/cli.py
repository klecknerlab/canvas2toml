"""Command-line interface for canvas2toml."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import textwrap
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from . import Course, __version__, toml_string


GRADING_INFO_BODY = textwrap.dedent(
    """This file is used to auto-upload grades and comments to the Canvas LMS.

You should not edit anything apart from the `score` and `comment` fields **inside** each `[[submission]]` block.

Note that the comments support **Markdown** formatting.  This means you can
include things like:

  - Emphasis: *italic* and **bold**
  - Lists
    1. Including numbered lists
    2. And sub-lists
  - Code blocks
  - Unicode characters, e.g., ∇·E = ρ/ε₀ (not Latex!)

The suggested format for grading homeworks is to give a per question score and
optional comment(s).  For example:

----

**Problem 1**: 2/3 points

  - Minor mistake in calculation.

**Problem 2**: 5/5 points

**Problem 3**: 0/2 points

**Problem 4**: 3/5 points

  - Sign mistake
  - Wrong initial values
----
"""
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canvas2toml",
        description="CLI helper for Canvas ↔ TOML utilities.",
    )
    parser.add_argument(
        "-c",
        "--course",
        default="course_info.toml",
        help="Path to course info TOML (default: ./course_info.toml).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Override output TOML filename (applies to get commands).",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # help --------------------------------------------------------------
    help_parser = subparsers.add_parser("help", help="Show this help message.")
    help_parser.set_defaults(func=lambda args: parser.print_help())

    # upload ------------------------------------------------------------
    upload_parser = subparsers.add_parser(
        "upload", help="Upload scores from a TOML file."
    )
    upload_parser.add_argument(
        "input",
        help="Path to a TOML file containing [[submission]] entries with score/comment.",
    )
    upload_parser.set_defaults(func=cmd_upload)

    # get ---------------------------------------------------------------
    get_parser = subparsers.add_parser("get", help="Fetch data from Canvas.")
    get_subparsers = get_parser.add_subparsers(dest="get_target")

    assignments_parser = get_subparsers.add_parser(
        "assignments",
        help="Download assignment metadata and save to TOML.",
    )
    assignments_parser.add_argument(
        "-a",
        "--anon",
        action="store_true",
        help="Remove student names from generated TOML.",
    )
    assignments_parser.set_defaults(func=cmd_get_assignments)

    quiz_parser = get_subparsers.add_parser(
        "quiz",
        help="Download quiz responses and save to TOML.",
    )
    quiz_parser.set_defaults(func=cmd_get_quiz)

    # hist --------------------------------------------------------------
    hist_parser = subparsers.add_parser(
        "hist",
        help="Generate histograms from a graded TOML file (scores and per-question points).",
    )
    hist_parser.add_argument(
        "input",
        help="Path to graded TOML file with [[submission]] entries.",
    )
    hist_parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Directory to write PNG histograms (default: current directory).",
    )
    hist_parser.set_defaults(func=cmd_hist)

    # Default to help when no command is provided.
    parser.set_defaults(func=lambda args: parser.print_help())
    return parser


# ---- helpers ------------------------------------------------------------
def _validate_course(path: str | Path) -> Course | None:
    course_path = Path(path).expanduser()
    if not course_path.is_file():
        sys.stderr.write(
            "Course configuration not found.\n"
            f"Expected a TOML file at: {course_path}\n"
            "Create it with keys: base_url, course_id, token. Example:\n"
            'base_url = "https://school.instructure.com"\n'
            'course_id = 12345\n'
            'token = "YOUR_API_TOKEN"\n'
        )
        return None

    try:
        return Course(config=course_path)
    except Exception as exc:  # pragma: no cover - surface config issues to user
        sys.stderr.write(f"Failed to load course config: {exc}\n")
        return None


def _prompt_choice(items: list[dict], label_key: str) -> dict | None:
    """Display a numbered list and prompt the user to pick one."""
    if not items:
        print("No items found.")
        return None

    for idx, item in enumerate(items, start=1):
        name = item.get(label_key) or item.get("title") or item.get("name") or "Untitled"
        due = item.get("due_at")
        suffix = f" (due {due})" if due else ""
        print(f"{idx}) {name}{suffix}")

    while True:
        choice = input("Enter a number (or 'q' to cancel): ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return None
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(items):
                return items[num - 1]
        print(f"Please enter a value between 1 and {len(items)}, or 'q' to cancel.")


def _safe_filename(title: str, suffix: str = "") -> str:
    """Create a filesystem-friendly filename."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_")
    if not slug:
        slug = "unnamed"
    return f"{slug}{suffix}"


def _current_score_and_comment(sub: dict) -> tuple[float | int | None, str | None]:
    """Extract current score and most recent comment from a submission dict."""
    score = sub.get("score")
    if score is None:
        score = sub.get("entered_score") or sub.get("grade")

    comment_text = None
    comments = sub.get("submission_comments") or []
    if isinstance(comments, list) and comments:
        # Take most recent comment; Canvas returns chronological order.
        latest = comments[-1]
        comment_text = latest.get("comment") or latest.get("text_comment")
    return score, comment_text


def _triple(s: str | None, *, blank_line: bool = False) -> str:
    """Return TOML triple-quoted string literal for the given text (empty allowed).

    If blank_line is True, wrap with a leading/trailing newline for readability:
    \"\"\"\ntext\n\"\"\" (even when text is empty).
    """
    s = "" if s is None else str(s)
    s = s.replace('"""', '\\"""')
    if blank_line:
        return f'"""\n{s}\n"""'
    return f'"""{s}"""'


def _assignment_to_toml(assignment: dict) -> str:
    """Serialize a single assignment dict to a lightweight TOML string."""
    lines: list[str] = [f"grading_info = {_triple(GRADING_INFO_BODY)}"]
    simple_fields = {
        "assignment_id": assignment.get("id"),
        "title": assignment.get("name"),
        "html_url": assignment.get("html_url"),
        "due_at": assignment.get("due_at"),
        "points_possible": assignment.get("points_possible"),
    }
    for key, value in simple_fields.items():
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{key} = {value}")
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        else:
            lines.append(f"{key} = {toml_string(str(value))}")

    return "\n".join(lines)


def _markdown_to_html(text: str | None) -> str | None:
    """Convert Markdown to HTML if possible; fall back to original text."""
    if text is None:
        return None
    try:
        import markdown  # type: ignore
    except Exception:
        return str(text)
    try:
        return markdown.markdown(str(text))
    except Exception:
        return str(text)


def _submission_block(
    sub: dict,
    file_rel: str | None = None,
    *,
    score=None,
    comment=None,
    anon: bool = False,
) -> str:
    """Create a TOML submission block with placeholders for scoring."""
    parts: list[str] = ["", "[[submission]]"]
    user = sub.get("user") or {}
    name = sub.get("name") or user.get("name")
    if name and not anon:
        parts.append(f"name = {toml_string(str(name))}")
    user_id = sub.get("user_id") or sub.get("id") or user.get("id")
    if user_id is not None:
        parts.append(f"id = {user_id}")
    sis_id = (
        sub.get("sis_id")
        or sub.get("sis_user_id")
        or user.get("sis_user_id")
        or user.get("sis_login_id")
    )
    if sis_id:
        parts.append(f"sis_id = {toml_string(str(sis_id))}")
    if file_rel:
        parts.append(f'file = "{file_rel}"')
    if score is None:
        parts.append("score = 0")
    else:
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            parts.append(f"score = {score}")
        else:
            parts.append(f"score = {toml_string(str(score))}")
    html_comment = _markdown_to_html(comment)
    parts.append(f"comment = {_triple(html_comment, blank_line=True)}")
    return "\n".join(parts)


# ---- commands -----------------------------------------------------------
def _load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y_%m_%d_%H:%M:%S")


def _write_backup_header(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_keys = ("assignment_id", "title", "description")
    with path.open("w", encoding="utf-8") as fh:
        for key in header_keys:
            if key in data and data[key] is not None:
                fh.write(f"{key} = {toml_string(str(data[key]))}\n")


def _append_backup_submission(path: Path, submission: dict, previous: dict) -> None:
    """Append a submission backup entry to the backup TOML file."""
    prev_score = (
        previous.get("score")
        or previous.get("entered_score")
        or previous.get("grade")
    )
    comments = previous.get("submission_comments") or []
    prev_comment_parts = []
    for item in comments:
        text = item.get("comment")
        author = item.get("author_name")
        if text:
            prev_comment_parts.append(f"{author}: {text}" if author else text)
    prev_comment = "; ".join(prev_comment_parts) if prev_comment_parts else None

    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n[[submission]]\n")
        for key in ("name", "id", "sis_id"):
            if key in submission and submission[key] is not None:
                value = submission[key]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    fh.write(f"{key} = {value}\n")
                else:
                    fh.write(f"{key} = {toml_string(str(value))}\n")
        if prev_score is not None:
            if isinstance(prev_score, (int, float)) and not isinstance(prev_score, bool):
                fh.write(f"previous_score = {prev_score}\n")
            else:
                fh.write(f"previous_score = {toml_string(str(prev_score))}\n")
        if prev_comment:
            fh.write(f"previous_comment = {toml_string(prev_comment)}\n")


def _count_valid_submissions(submissions: list[dict]) -> int:
    return sum(
        1
        for sub in submissions
        if ("score" in sub and sub["score"] is not None)
        or ("comment" in sub and sub["comment"])
    )


def _resolve_user_ref(submission: dict) -> str | None:
    """Pick the best identifier for a submission."""
    sis = submission.get("sis_id")
    if sis:
        sis_val = str(sis).strip()
        if sis_val:
            return f"sis_user_id:{sis_val}"
    sis_login = submission.get("sis_login_id")
    if sis_login:
        val = str(sis_login).strip()
        if val:
            return f"sis_login_id:{val}"
    for key in ("canvas_id", "user_id", "id"):
        if submission.get(key) is not None:
            val = str(submission[key]).strip()
            if val:
                return val
    return None


def cmd_upload(args: argparse.Namespace) -> int:
    course = _validate_course(args.course)
    if course is None:
        return 1

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input TOML not found: {input_path}")
        return 1

    data = _load_toml(input_path)
    assignment_id = data.get("assignment_id")
    submissions = data.get("submission") or []

    if assignment_id is None:
        print("assignment_id is required in the TOML file.")
        return 1
    if not submissions:
        print("No submissions found in the TOML file.")
        return 1

    valid_count = _count_valid_submissions(submissions)
    if valid_count == 0:
        print("No submissions contain score or comment to upload.")
        return 0

    confirm = input(
        f"Found {valid_count} submissions with scores/comments to upload. Proceed? [y/N]: "
    ).strip().lower()
    if confirm not in {"y", "yes"}:
        print("Upload cancelled.")
        return 0

    backup_base = input_path.stem
    backup_path = input_path.with_name(
        f"{backup_base}_backup_{_timestamp()}.toml"
    )
    _write_backup_header(backup_path, data)

    processed = 0
    resolved_cache: dict[str, int | str] = {}

    for submission in submissions:
        score = submission.get("score")
        comment = submission.get("comment", submission.get("comments"))
        user_ref = _resolve_user_ref(submission)
        if user_ref is None or (score is None and comment is None):
            continue

        try:
            if user_ref in resolved_cache:
                resolved_user_id = resolved_cache[user_ref]
            else:
                resolved_user_id = course.resolve_canvas_user_id(user_ref) or user_ref
                resolved_cache[user_ref] = resolved_user_id
            previous = course.get_submission(assignment_id, resolved_user_id)
            _append_backup_submission(backup_path, submission, previous)
            attempt = previous.get("attempt") if isinstance(previous, dict) else None
            comment_text_raw = None if comment is None else str(comment).rstrip()
            comment_text = _markdown_to_html(comment_text_raw)
            course.update_submission(
                assignment_id,
                resolved_user_id,
                score=score,
                comment=comment_text,
                attempt=attempt,
            )
            if comment_text is not None:
                try:
                    course.add_comment(
                        assignment_id,
                        resolved_user_id,
                        comment=comment_text,
                        attempt=attempt,
                    )
                except Exception as exc:
                    print(f"Warning: comment not posted for user {resolved_user_id}: {exc}")
            processed += 1
            print(f"[{processed}/{valid_count}] Updated user {resolved_user_id}")
        except Exception as exc:  # pragma: no cover - show progress during batch
            print(f"Failed to update user {user_ref}: {exc}")

    print(f"Backup of previous scores/comments saved to {backup_path}")
    return 0


def cmd_hist(args: argparse.Namespace) -> int:
    """Generate histograms for total scores and per-question points."""
    data = _load_toml(Path(args.input))
    submissions = data.get("submission") or []
    if not submissions:
        print("No submissions found in the TOML file.")
        return 1

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional dependency
        print(
            "matplotlib is required for this command. Install with 'pip install matplotlib'."
        )
        print(f"Import error: {exc}")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _to_float(val):
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        try:
            return float(str(val))
        except Exception:
            return None

    # Total score histogram
    scores = [_to_float(sub.get("score")) for sub in submissions]
    scores = [s for s in scores if s is not None]
    if not scores:
        print("No numeric 'score' values found; skipping total score histogram.")

    # Per-question histograms
    import re as _re

    question_values: dict[str, list[float]] = {}
    for sub in submissions:
        for key, val in sub.items():
            m = _re.match(r"^q(\d+)_points$", key)
            if not m:
                continue
            v = _to_float(val)
            if v is None:
                continue
            question_values.setdefault(key, []).append(v)

    if not question_values and not scores:
        print("No histogram data found.")
        return 0

    # Compose into a single multi-plot PNG
    plots = []
    if scores:
        plots.append(("Total Scores", scores, "Score"))
    for key, values in sorted(question_values.items()):
        if values:
            plots.append((f"{key} Distribution", values, "Points"))

    n = len(plots)
    ncols = 2 if n > 1 else 1
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4 * nrows))
    if nrows == 1 and ncols == 1:
        axes = [[axes]]
    elif nrows == 1:
        axes = [axes]

    for ax, (title, values, xlabel) in zip([a for row in axes for a in row], plots):
        ax.hist(values, bins="auto", edgecolor="black")
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Count")

    # Hide unused axes if any
    for ax in [a for row in axes for a in row][len(plots):]:
        ax.axis("off")

    plt.tight_layout()
    base = Path(args.input).stem
    out_file = out_dir / f"{base}_hist.png"
    fig.savefig(out_file)
    plt.close(fig)
    print(f"Wrote {out_file}")

    return 0


def cmd_get_assignments(args: argparse.Namespace) -> int:
    course = _validate_course(args.course)
    if course is None:
        return 1

    assignments = course.get_assignments()
    choice = _prompt_choice(assignments, "name")
    if choice is None:
        return 0

    title = choice.get("name") or "assignment"
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(f"{choice.get('id')}_{_safe_filename(title)}.toml")

    download_pdfs = (
        input("Download PDF submissions? [Y/n]: ").strip().lower() not in {"n", "no"}
    )

    submissions_dir = out_path.parent / f"{out_path.stem}_submissions"
    submissions = course.get_submissions(choice.get("id"))

    file_map: dict[str, str] = {}
    if download_pdfs:
        for sub in submissions:
            attachments = sub.get("attachments") or []
            if not attachments:
                continue
            user = sub.get("user") or {}
            student_name = (
                sub.get("name")
                or user.get("name")
                or f"student_{sub.get('user_id') or 'unknown'}"
            )
            student_id = sub.get("user_id") or sub.get("id") or user.get("id")
            for att in attachments:
                fname = att.get("filename") or att.get("display_name")
                if not fname:
                    continue
                if not fname.lower().endswith(".pdf"):
                    continue
                url = att.get("url") or att.get("download_url") or att.get("href")
                if not url:
                    continue
                sid_part = _safe_filename(str(student_id)) if student_id else _safe_filename(student_name)
                hw_part = _safe_filename(title)
                safe_fname = f"{hw_part}_{sid_part}.pdf"
                dest = submissions_dir / safe_fname
                try:
                    course.download_file(url, dest)
                    file_map[str(sub.get("user_id") or sub.get("id") or "")] = dest.name
                    break  # only first PDF per submission
                except Exception as exc:  # pragma: no cover
                    print(f"Failed to download {fname}: {exc}")

    # Sort submissions for deterministic TOML output (by name then id).
    def _sort_key(sub):
        user = sub.get("user") or {}
        name = sub.get("name") or user.get("name") or ""
        uid = str(sub.get("user_id") or sub.get("id") or "")
        return (name.lower(), uid)

    sorted_subs = sorted(submissions, key=_sort_key)

    content_parts = [_assignment_to_toml(choice)]
    for sub in sorted_subs:
        uid = str(sub.get("user_id") or sub.get("id") or "")
        file_rel = None
        if uid and uid in file_map:
            file_rel = f"{submissions_dir.name}/{file_map[uid]}"
        score, comment = _current_score_and_comment(sub)
        content_parts.append(
            _submission_block(
                sub,
                file_rel=file_rel,
                score=score,
                comment=comment,
                anon=args.anon,
            )
        )

    out_path.write_text("\n".join(content_parts), encoding="utf-8")
    print(f"Saved assignment to {out_path}")
    if submissions_dir.exists():
        print(f"Downloaded PDFs to {submissions_dir}")
    return 0


def cmd_get_quiz(args: argparse.Namespace) -> int:
    course = _validate_course(args.course)
    if course is None:
        return 1

    quizzes = course.get_quizzes()
    choice = _prompt_choice(quizzes, "title")
    if choice is None:
        return 0

    title = choice.get("title") or choice.get("quiz_name") or "quiz"
    if args.output:
        filename = args.output
    else:
        filename = f"{choice.get('id')}_{_safe_filename(title, suffix='_responses')}.toml"
    # Ensure quiz_id is preserved when available (New Quizzes often use quiz_id distinct from assignment id)
    if "quiz_id" not in choice and choice.get("id") and choice.get("quiz_id", None) is None:
        # Some APIs return 'quiz_id' nested; keep whatever exists, otherwise leave as is.
        pass

    course.save_quiz_toml(choice, filename)
    print(f"Saved quiz responses to {filename}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # When the user runs `canvas2toml` with no args or with `help`,
    # argparse will route to the help function we set as default.
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
