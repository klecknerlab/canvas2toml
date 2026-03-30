# canvas2toml

Python package for interacting with Canvas, uploading and downloading results
to/from TOML files.  

Provides a Python module, as well as a command line tool.

The main intended use is to download quiz or assignments into a single file
which can be graded by hand, adding `score` and `comment` fields for each
student.  The resulting scores can then be uploaded to Canvas with a single
command.

License: Apache 2.0.

## Installation

```bash
pip install -e .
```

## Usage

Show help:

```bash
canvas2toml --help
```

Common commands (and options):

- `canvas2toml get assignments [-o FILE] [-a/--anon]`
  - Prompts you to pick an assignment, asks whether to download PDF submissions (default Y).
  - PDFs: saves as `<assignment_title>_<studentid>.pdf` in `<output_stem>_submissions/`; by default skips files that already exist and reports `downloaded X, skipped existing Y`. Use `--force-download-pdfs` to re-download everything.
  - TOML includes `grading_info`, assignment metadata (with `due_at` when available), and sorted `[[submission]]` blocks containing ids, optional names (omitted with `--anon`), current scores, latest comments (converted to HTML), optional `file` pointers to PDFs, and timing fields when provided by Canvas:
    - `submitted_at` (raw timestamp from Canvas)
    - `days_late` (fractional days late, two decimals; only present if submitted after `due_at`)

- `canvas2toml get quiz [-o FILE]`
  - Prompts for a quiz, downloads responses, and writes TOML including both `assignment_id` and `quiz_id` (useful for New Quizzes).
  - Adds `due_at`, per-student `submitted_at`, and `days_late` (two decimal days when after due time) when present in the Student Analysis report.

- `canvas2toml update INPUT.toml [--force-download-pdfs]`
  - Fetches **any submissions not already present** in the TOML from Canvas and prepends their blank `[[submission]]` blocks before the existing entries.
  - Reads `assignment_id` from the existing TOML — no extra arguments needed. No due-date filtering; all missing students are added regardless of when they submitted. Submissions already in the TOML but **without a `file` field** (i.e., the student had not uploaded at the time of the original download) are also treated as new and prepended.
  - Auto-detects whether the original download was anonymized (by checking whether any existing submission has a `name` field) and writes new blocks to match.
  - Prompts to download PDFs into the same `<input_stem>_submissions/` directory as the original (default Y; skips existing unless `--force-download-pdfs`).
  - New blocks have `score = 0` and a blank `comment` placeholder, with `submitted_at` and `days_late` pre-filled (if `due_at` is present in the TOML). The late-penalty fields (`max_days_late`, `deduction_percent_per_day`) are applied automatically at upload/report time.

- `canvas2toml upload INPUT.toml`
  - Uploads `score` and `comment`/`comments` from each `[[submission]]`.
  - Confirms count before proceeding, backs up prior scores/comments to `<input_stem>_backup_<timestamp>.toml`, then posts grades and comments (HTML) using both grade and comments endpoints.
  - Uses `sis_id`/`sis_login_id` when present; falls back to `user_id`/`id`.
  - **Automatic late penalty**: if the top-level TOML contains `max_days_late` and `deduction_percent_per_day`, a deduction is computed in-memory for any submission with `days_late > 0` and applied to the uploaded score and comment. The source TOML is never modified.

- `canvas2toml hist INPUT.toml -o DIR`
  - Builds PNG histograms for total `score` and per-question `qN_points` fields into a single `<input_stem>_hist.png` (plus console messages). Requires optional `matplotlib` (`pip install matplotlib`).
- `canvas2toml report INPUT.toml [-o FILE]`
  - Creates a standalone HTML report with an embedded score histogram (base64 PNG) and per-student sections showing name/id, score, and comments (Markdown converted to HTML). Defaults output to `<input_stem>_report.html`.
  - **Automatic late penalty**: same deduction logic as `upload` — if `max_days_late` and `deduction_percent_per_day` are present, the displayed scores and comments in the report reflect the penalty without modifying the source TOML.

- `canvas2toml help` (or no args): show help.

### Automatic late penalty

Add two fields to the top-level section of an assignment TOML to enable automatic late deductions:

```toml
max_days_late = 5
deduction_percent_per_day = 10
```

At `upload` and `report` time, for any submission with `days_late > 0`:

1. `days_late` is rounded to the nearest 0.1 days, then capped at `max_days_late`.
2. The deduction percentage is `days_used × deduction_percent_per_day`.
3. The deduction in points is `points_possible × deduction_pct / 100`, rounded to the nearest 0.1.
4. The deduction is subtracted from the score (floored at 0), and a note is appended to the comment:

   ```
   *Late penalty: 2.4 day(s) × 10%/day = 24.0% = −24.0 point(s)*
   ```

The source TOML is never modified; the penalty is applied in-memory only.

### Course configuration

The CLI looks for `course_info.toml` in the current directory by default (override with `-c/--course`). The file must contain your Canvas connection details:

```toml
base_url = "https://school.instructure.com"
course_id = 12345
token = "YOUR_API_TOKEN"
```

Steps to create `course_info.toml` and get a Canvas token:
1) In Canvas, click Account → Settings (upper-left sidebar).
2) Scroll to the **Approved Integrations** / **New Access Token** section and click **+ New Access Token**.
3) Enter a purpose/name (e.g., “canvas2toml”), optional expiry, then click **Generate Token**. Copy the token immediately; Canvas will only show it once.
4) Find the base URL in your browser address bar while viewing the course (e.g., `https://ucmerced.instructure.com`). Copy the numeric course ID from the course URL (e.g., `/courses/37329` → `37329`).
5) Create a file named `course_info.toml` alongside where you’ll run the CLI with the contents shown above, replacing `base_url`, `course_id`, and `token` with your values.
6) Keep this file private; the token grants API access to your account. Rotate the token in Canvas if it is ever exposed.
