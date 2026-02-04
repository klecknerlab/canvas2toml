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
  - Saves PDFs as `<assignment_title>_<studentid>.pdf` in `<output_stem>_submissions/`.
  - Generates a TOML with `grading_info`, assignment metadata, and sorted `[[submission]]` blocks containing ids, optional names (omitted with `--anon`), current scores, latest comments (converted to HTML), and `file` pointers to downloaded PDFs.

- `canvas2toml get quiz [-o FILE]`
  - Prompts for a quiz, downloads responses, and writes TOML including both `assignment_id` and `quiz_id` (useful for New Quizzes).

- `canvas2toml upload INPUT.toml`
  - Uploads `score` and `comment`/`comments` from each `[[submission]]`.
  - Confirms count before proceeding, backs up prior scores/comments to `<input_stem>_backup_<timestamp>.toml`, then posts grades and comments (HTML) using both grade and comments endpoints.
  - Uses `sis_id`/`sis_login_id` when present; falls back to `user_id`/`id`.

- `canvas2toml hist INPUT.toml -o DIR`
  - Builds PNG histograms for total `score` and per-question `qN_points` fields into a single `<input_stem>_hist.png` (plus console messages). Requires optional `matplotlib` (`pip install matplotlib`).

- `canvas2toml help` (or no args): show help.

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
