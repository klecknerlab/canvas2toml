"""canvas2toml package."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable
import time
import csv
import re
import requests
from urllib.parse import quote

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

__all__ = ["__version__", "Course"]
__version__ = "0.1.0"


def try_int(s):
    s = s.strip()
    try:
        return int(s)
    except:
        try:
            return float(s)
        except: 
            return 0

def parse_quiz_csv(csv_bytes):
    name_col = None
    id_col = None
    sis_id_col = None
    q_col = []
    q_prompts = []
    max_points = []

    reader = csv.reader(csv_bytes.decode().splitlines())
    
    headers = reader.__next__()
    for i, col_name in enumerate(headers):
        if col_name == "name":
            name_col = i
        elif col_name == "id":
            id_col = i
        elif col_name == "sis_id":
            sis_id_col = i
        else:
            m = re.match(r"^\d+:\s+(.*)", col_name)
            if m: # question column
                q_col.append(i)
                q_prompts.append(m.group(1))
                max_points.append(try_int(headers[i+1]))
    
    names = []  
    ids = []
    sis_ids = []
    answers = [[] for i in range(len(q_col))]
    points = [[] for i in range(len(q_col))]
    
    for row in reader:
        names.append(row[name_col])
        ids.append(row[id_col])
        sis_ids.append(row[sis_id_col])
        for i, q in enumerate(q_col):
            answers[i].append(row[q])
            points[i].append(try_int(row[q+1]))
            
    points = [p if any(p) else None for p in points]

    return {
        "names": names,
        "ids": ids,
        "sis_ids": sis_ids,
        "questions": q_prompts,
        "answers": answers,
        "points": points,
        "max_points": max_points
    }
    
import textwrap
from markdownify import markdownify as md
# import pd

def name_lf(name):
    parts = name.split(" ", 1)
    if len(parts) == 2:
        return f"{parts[1]}, {parts[0]}"
    return name

def toml_escape_basic(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s

def toml_string(s) -> str:
    s = '\n'.join(textwrap.fill(p, 80) for p in toml_escape_basic(s).splitlines())

    if "\n" in s:
        esc = s.replace('"""', '\\"""')
        return '"""\n' + s + '\n"""'
    else:
        return '"' + s + '"'

def generate_quiz_toml(quiz_info, student_analysis, prepend_info = {}):
    tout = ""

    assignment_id = quiz_info.get("assignment_id") or quiz_info.get("id")
    if assignment_id is not None:
        tout += f"assignment_id = {assignment_id}\n"
    
    quiz_id = quiz_info.get("quiz_id") or quiz_info.get("id")
    if quiz_id is not None:
        tout += f"quiz_id = {quiz_id}\n"
    
    if 'title' in quiz_info:
        tout += f"title = {toml_string(quiz_info['title'])}\n"
        
    if 'description' in quiz_info:
        tout += f"description = {toml_string(md(quiz_info['description']))}\n"
        
    tout += "\n"
    
    for key, value in prepend_info.items():
        tout += f"{key} = {toml_string(value)}\n"

    for qn, prompt in enumerate(student_analysis['questions']):
        tout += f"""
q{qn+1}_prompt = {toml_string(prompt)}
q{qn+1}_max_points = {student_analysis['max_points'][qn]}
"""

    names = student_analysis['names']
    ids = student_analysis['ids']
    sis_ids = student_analysis['sis_ids']
    answers = student_analysis['answers']
    points = student_analysis['points']
    
    lf_names = [name_lf(n) for n in names]
    order = sorted(range(len(names)), key=lambda i: lf_names[i])

    for i in order:
        tout += f"""
[[submission]]
name = {toml_string(names[i])}
id = {ids[i]}
sis_id = {sis_ids[i]}

"""
        for qn, (ans, pts) in enumerate(zip(answers, points)):
            tout += f"q{qn+1}_answer = {toml_string(ans[i])}\n"
            if pts:
                tout += f"q{qn+1}_points = {pts[i]}\n"
            tout += "\n"

    return tout


class Course:
    """Basic Canvas course configuration holder."""

    def __init__(
        self,
        config: str | Path | None = None,
        *,
        base_url: str | None = None,
        course_id: str | int | None = None,
        token: str | None = None,
    ) -> None:
        """Initialize with either a config file path or explicit values.

        Args:
            config: Path to TOML file containing keys ``base_url``, ``course_id``, ``token``.
            base_url: Canvas base URL (e.g., "https://school.instructure.com").
            course_id: Canvas course ID.
            token: API token.
        """
        if config is not None:
            with Path(config).expanduser().open("rb") as fh:
                data = tomllib.load(fh)
            base_url = data.get("base_url", base_url)
            course_id = data.get("course_id", course_id)
            token = data.get("token", token)

        # Normalize base_url to avoid double slashes when building API URLs.
        self.base_url = base_url.rstrip("/") if base_url else base_url
        self.course_id = course_id
        self.token = token
        self._user_cache: dict[str, int] = {}

    def list_quizzes_and_assignments(self) -> list[dict]:
        """Return quizzes and assignments as dictionaries.

        Each dict should contain at least the assignment/quiz identifier,
        title/name, and any fields required for later lookups. This is a stub;
        wire it to the Canvas API in a future change.
        """
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")

        assignments = self.get_assignments()
        quizzes = self.get_quizzes()

        normalized = []
        for item in assignments:
            normalized.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "html_url": item.get("html_url"),
                    "due_at": item.get("due_at"),
                    "points_possible": item.get("points_possible"),
                    "type": "assignment",
                    "raw": item,
                }
            )
        for item in quizzes:
            normalized.append(
                {
                    "id": item.get("id"),
                    "quiz_id": item.get("id"),
                    "assignment_id": item.get("assignment_id"),
                    "name": item.get("title") or item.get("quiz_name"),
                    "html_url": item.get("html_url"),
                    "due_at": item.get("due_at"),
                    "points_possible": item.get("points_possible"),
                    "type": "quiz",
                    "raw": item,
                }
            )
        return normalized

    def get_assignments(self) -> list[dict]:
        """Return all assignments for the course."""
        return self.get_collection("assignments")

    def get_quizzes(self) -> list[dict]:
        """Return all quizzes for the course."""
        return self.get_collection("quizzes")

    def get_collection(self, collection: str) -> list[dict]:
        """Fetch any Canvas course collection by name (e.g., 'assignments')."""
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")
        url = f"{self.base_url}/api/v1/courses/{self.course_id}/{collection}"
        return self._paginate(url)

    def get_submissions(self, assignment_id: int | str) -> list[dict]:
        """Return submissions for a given assignment (includes user and attachments)."""
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")
        url = (
            f"{self.base_url}/api/v1/courses/{self.course_id}"
            f"/assignments/{assignment_id}/submissions"
        )
        params = {
            "per_page": 100,
            "include[]": ["submission_history", "user", "attachments"],
        }
        return self._paginate(url, params=params)

    def get_submission(self, assignment_id: int | str, user_id: int | str) -> dict:
        """Fetch a single submission for a user/assignment."""
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")
        url = self._submission_url(assignment_id, user_id)
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def update_submission(
        self,
        assignment_id: int | str,
        user_id: int | str,
        *,
        score: float | int | None = None,
        comment: str | None = None,
        attempt: int | None = None,
        group_comment: bool | None = None,
    ) -> dict:
        """Update grade and/or comment for a submission."""
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")
        url = self._submission_url(assignment_id, user_id)
        payload: dict[str, object] = {}
        if score is not None:
            payload["submission[posted_grade]"] = score
        if comment is not None:
            payload["comment[text_comment]"] = comment
        if attempt is not None:
            payload["comment[attempt]"] = attempt
        if group_comment is not None:
            payload["comment[group_comment]"] = bool(group_comment)

        resp = requests.put(url, headers=self._headers(), data=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def add_comment(
        self,
        assignment_id: int | str,
        user_id: int | str,
        *,
        comment: str,
        attempt: int | None = None,
        group_comment: bool | None = None,
    ) -> dict:
        """Add a text comment to a submission via the comments endpoint."""
        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")
        url = (
            f"{self.base_url}/api/v1/courses/{self.course_id}"
            f"/assignments/{quote(str(assignment_id), safe='')}"
            f"/submissions/{quote(str(user_id), safe='')}/comments"
        )
        payload: dict[str, object] = {"comment[text_comment]": comment}
        if attempt is not None:
            payload["comment[attempt]"] = attempt
        if group_comment is not None:
            payload["comment[group_comment]"] = bool(group_comment)
        resp = requests.post(url, headers=self._headers(), data=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def resolve_canvas_user_id(self, user_ref: str) -> int | None:
        """Resolve a user reference (sis_user_id:..., login_id, or numeric id) to Canvas user id.

        The Submissions API accepts SIS user ids in the path, but some institutions
        do not enable that flag. This helper looks up the user first so we can
        fall back to the numeric Canvas id.
        """
        if user_ref is None:
            return None

        # If already numeric, return as int.
        if str(user_ref).isdigit():
            return int(user_ref)

        # Check local cache first.
        cached = self._user_cache.get(user_ref)
        if cached:
            return cached

        # Try SIS user and login lookups.
        if not (self.base_url and self.token):
            raise ValueError("base_url and token are required.")
        candidates = []
        ref = str(user_ref).strip()
        if ref.startswith("sis_user_id:"):
            candidates.append(ref)
            candidates.append(ref.replace("sis_user_id:", "sis_login_id:", 1))
        elif ref.startswith("sis_login_id:"):
            candidates.append(ref)
            candidates.append(ref.replace("sis_login_id:", "sis_user_id:", 1))
        else:
            candidates.append(f"sis_user_id:{ref}")
            candidates.append(f"sis_login_id:{ref}")

        for cand in candidates:
            url = f"{self.base_url}/api/v1/users/{quote(cand, safe=':')}"
            resp = requests.get(url, headers=self._headers(), timeout=15)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            cid = data.get("id")
            if cid:
                self._user_cache[user_ref] = cid
                return cid

        # Fallback: scan course users and try to match sis_user_id or login_id.
        try:
            users = self._paginate(
                f"{self.base_url}/api/v1/courses/{self.course_id}/users?enrollment_type[]=student&include[]=sis_user_id&per_page=100"
            )
            for u in users:
                cid = u.get("id")
                if not cid:
                    continue
                sis_uid = u.get("sis_user_id")
                login_id = u.get("login_id")
                if sis_uid:
                    key = f"sis_user_id:{sis_uid}"
                    self._user_cache[key] = cid
                if login_id:
                    key = f"sis_login_id:{login_id}"
                    self._user_cache[key] = cid
                # Populate plain ids too
                self._user_cache[str(cid)] = cid

            cached = self._user_cache.get(user_ref)
            if cached:
                return cached
        except Exception:
            pass

        return None

    def _submission_url(self, assignment_id: int | str, user_id: int | str) -> str:
        """Build a safe submission URL, allowing sis_user_id: references."""
        assignment = quote(str(assignment_id).strip(), safe="")
        user = quote(str(user_id).strip(), safe="")
        return (
            f"{self.base_url}/api/v1/courses/{self.course_id}"
            f"/assignments/{assignment}/submissions/{user}"
        )

    def download_file(self, url: str, dest: Path) -> None:
        """Download a file to the given destination path."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, headers=self._headers(), stream=True, timeout=60) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)

    def _paginate(self, url: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages for a Canvas collection endpoint."""
        results: list[dict] = []
        first_params = params
        while url:
            resp = requests.get(
                url, headers=self._headers(), params=first_params, timeout=30
            )
            resp.raise_for_status()
            page_items = resp.json()
            if isinstance(page_items, dict):
                # Some endpoints may return dict with 'quizzes' etc.
                page_items = list(page_items.values())
            if not isinstance(page_items, Iterable):
                raise TypeError("Unexpected response structure from Canvas API")
            results.extend(page_items)
            url = self._next_link(resp.headers.get("Link"))
            first_params = None  # only on first request
        return results

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _next_link(link_header: str | None) -> str | None:
        """Parse Canvas-style Link header for the 'next' rel."""
        if not link_header:
            return None
        for part in link_header.split(","):
            section = part.strip().split(";")
            if len(section) < 2:
                continue
            url_part, *params = section
            url = url_part.strip()[1:-1]  # remove <>
            rel = None
            for p in params:
                if "rel=" in p:
                    rel = p.split("=", 1)[1].strip().strip('"')
            if rel == "next":
                return url
        return None

    # ---- Quiz reports -------------------------------------------------
    def download_quiz_student_analysis(
        self,
        quiz: int | dict,
        raw : bool = False,
        *,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
    ) -> bytes:
        """Download the Student Analysis CSV for a quiz.

        Args:
            quiz: Quiz ID or quiz dict (must contain ``id``).
            poll_interval: Seconds between status checks while report is generated.
            timeout: Maximum seconds to wait for report generation.

        Returns:
            Raw CSV bytes.
        """
        quiz_id = quiz if isinstance(quiz, int) else quiz.get("id")
        if quiz_id is None:
            raise ValueError("Quiz id is required to download student analysis.")

        if not (self.base_url and self.course_id and self.token):
            raise ValueError("base_url, course_id, and token are required.")

        reports_url = (
            f"{self.base_url}/api/v1/courses/{self.course_id}/quizzes/{quiz_id}/reports"
        )
        params = {"quiz_report[report_type]": "student_analysis"}
        create_resp = requests.post(
            reports_url, headers=self._headers(), params=params, timeout=30
        )
        create_resp.raise_for_status()
        report = create_resp.json()

        report_id = report.get("id")
        start_time = time.time()

        def _has_file(data: dict) -> dict | None:
            file_info = data.get("file")
            if isinstance(file_info, dict) and file_info.get("url"):
                return file_info
            return None

        file_info = _has_file(report)
        while not file_info:
            if time.time() - start_time > timeout:
                raise TimeoutError("Timed out waiting for quiz report to be ready.")

            if not report_id:
                raise RuntimeError("Report ID missing; cannot poll for completion.")

            poll_url = f"{reports_url}/{report_id}"
            poll_resp = requests.get(poll_url, headers=self._headers(), timeout=30)
            poll_resp.raise_for_status()
            report = poll_resp.json()
            file_info = _has_file(report)
            if file_info:
                break
            time.sleep(poll_interval)

        download_url = file_info["url"]
        download_resp = requests.get(download_url, headers=self._headers(), timeout=60)
        download_resp.raise_for_status()

        if raw:
            return download_resp.content
        else:
            return parse_quiz_csv(download_resp.content)
        
    def generate_quiz_toml(self, quiz_info, prepend_info = {}):
        """Generate a TOML representation of the quiz and student analysis.

        Args:
            quiz_info: Quiz information dict (should contain at least 'id' and 'title').
            prepend_info: Additional key-value pairs to prepend to the TOML output.

        Returns:
            TOML string.
        """ 

        student_analysis = self.download_quiz_student_analysis(quiz_info)
        return generate_quiz_toml(quiz_info, student_analysis, prepend_info)
    
    def save_quiz_toml(self, quiz_info, filepath: str | Path, prepend_info = {}):
        """Save the TOML representation of the quiz and student analysis to a file.

        Args:
            quiz_info: Quiz information dict (should contain at least 'id' and 'title').
            filepath: Path to save the TOML file.
            prepend_info: Additional key-value pairs to prepend to the TOML output.
        """ 

        toml_content = self.generate_quiz_toml(quiz_info, prepend_info)
        
        with Path(filepath).open("w", encoding="utf-8") as fh:
            fh.write(toml_content)
