"""AI Workmate - turns messy notes into a clear plan using Gemini.

How it works (much simpler than before):
1. The browser sends the user's notes to /organise.
2. We ask Gemini to answer in a fixed JSON shape (summary, tasks, steps...).
3. We turn that JSON into the same text layout the web page already shows.

Because every task comes with its own priority inside the JSON, the old
"repair" and "validation" regex code is no longer needed.
Works on Python 3.8 and newer.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler


# ---------------------------------------------------------------- settings

HOST = "127.0.0.1"
PORT = 8000
MAX_REQUEST_BYTES = 1024 * 1024  # 1 MiB limit for incoming note requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ALLOWED_HOSTS = {
    "127.0.0.1:" + str(PORT),
    "localhost:" + str(PORT),
}
ALLOWED_ORIGINS = {
    "http://127.0.0.1:" + str(PORT),
    "http://localhost:" + str(PORT),
}

# Inside GitHub Codespaces the page is opened through a forwarded link like
# https://<codespace-name>-8000.app.github.dev, so allow that one address too.
CODESPACE_NAME = os.environ.get("CODESPACE_NAME")
if CODESPACE_NAME:
    _forward_domain = os.environ.get(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    _codespace_host = (
        CODESPACE_NAME + "-" + str(PORT) + "." + _forward_domain
    ).lower()
    ALLOWED_HOSTS.add(_codespace_host)
    ALLOWED_ORIGINS.add("https://" + _codespace_host)

PRIORITY_LEVELS = ("HIGH", "MEDIUM", "LOW")


class UserError(Exception):
    """A problem the user can fix (shown to them as-is)."""


# ---------------------------------------------------------------- Gemini

# This tells Gemini exactly what shape the answer must have.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "action_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "task": {"type": "STRING"},
                    "priority": {
                        "type": "STRING",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                    },
                    "deadline": {"type": "STRING"},
                    "duration": {"type": "STRING"},
                },
                "required": ["task", "priority"],
            },
        },
        "next_steps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "warnings": {"type": "ARRAY", "items": {"type": "STRING"}},
        "drafts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "subject": {"type": "STRING"},
                    "body": {"type": "STRING"},
                },
                "required": ["body"],
            },
        },
    },
    "required": ["summary", "action_items", "next_steps"],
}


def build_prompt(user_text):
    today = datetime.date.today()
    today_text = today.strftime("%A, %d %B %Y")

    return """You are AI Workmate, a practical personal work assistant.
Today is """ + today_text + """.

Read the user's notes and understand their situation first. Then fill in the
JSON fields below.

Separate tasks from goals, ideas, questions and background context.
Only real tasks and commitments become action items. Do not turn wishes,
ideas or open questions into tasks. Never invent facts, commitments or
deadlines.

summary:
  2-4 concise sentences about the user's real situation: context, goals,
  commitments, deadlines and constraints. Do not just repeat the notes.

action_items (one entry per task, no duplicates):
  task      Short description of what to do. Include every pending meeting,
            appointment or call, written like: Attend [meeting].
            Leave out anything the user says is already finished.
  priority  HIGH = urgent or serious consequences if delayed.
            MEDIUM = important, should be done reasonably soon.
            LOW = flexible, optional or long-term.
            Do not make everything HIGH. Do not invent urgency.
  deadline  The deadline or time exactly as the user gave it (for example
            "today 3pm"). Empty string if none was given.
  duration  The user's own time estimate or meeting length if given.
            Empty string if not given. Never make one up.

next_steps:
  Practical, specific steps in a sensible order, starting with the most
  important one. If the user gave available time, plan within it using
  their own estimates, leave a small buffer, and respect breaks. If
  something does not fit, say so instead of pretending it does. Do not
  repeat the action items word for word.

warnings:
  Real problems only: scheduling conflicts, not enough time, a task due
  after its deadline, or important missing information (ask one short
  question). Empty list if everything is fine.
  When checking time, add up ONLY durations the user actually stated. If a
  task has no stated estimate, never guess one: say that its time is
  unknown instead.

drafts:
  Only emails or messages that would genuinely help. Empty list if none.

USER'S NOTES:

""" + user_text


def parse_model_json(answer):
    """Turn Gemini's text into a Python dict (tolerates ```json fences)."""
    text = str(answer or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Gemini did not return a JSON object.")
    return data


def call_gemini(user_text):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY is not configured.")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + GEMINI_MODEL + ":generateContent"
    )

    payload = {
        "contents": [{"parts": [{"text": build_prompt(user_text)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    last_error = None

    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))

            candidates = result.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned no response.")

            parts = candidates[0].get("content", {}).get("parts", [])
            answer = "\n".join(
                part.get("text", "") for part in parts if part.get("text")
            ).strip()
            if not answer:
                raise ValueError("Gemini returned an empty response.")

            return parse_model_json(answer)

        except urllib.error.HTTPError as error:
            last_error = error.read().decode("utf-8", errors="replace")
            # Only retry temporary problems (rate limit / server trouble).
            if error.code not in (429, 500, 502, 503, 504):
                raise Exception(
                    "Gemini API error " + str(error.code) + ": " + last_error
                )

        except urllib.error.URLError as error:
            last_error = str(error)

        except ValueError as error:
            # Bad or empty JSON from the model: trying again usually fixes it.
            last_error = str(error)

        if attempt < 3:
            time.sleep(2 * (attempt + 1))

    raise Exception(
        "Gemini request failed after 4 attempts: " + str(last_error)
    )


# ------------------------------------------------- cleaning and formatting

def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_response(data):
    """Make sure the model's JSON has the right shape, whatever it sent."""
    tasks = []
    seen = set()

    for item in data.get("action_items") or []:
        if not isinstance(item, dict):
            continue

        task = clean_text(item.get("task"))
        if not task or task.lower() in seen:
            continue
        seen.add(task.lower())

        priority = clean_text(item.get("priority")).upper()
        if priority not in PRIORITY_LEVELS:
            priority = "MEDIUM"

        tasks.append({
            "task": task,
            "priority": priority,
            "deadline": clean_text(item.get("deadline")),
            "duration": clean_text(item.get("duration")),
        })

    drafts = []
    for item in data.get("drafts") or []:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "").strip()
        if body:
            drafts.append({
                "subject": clean_text(item.get("subject")),
                "body": body,
            })

    def clean_list(key):
        return [
            clean_text(entry)
            for entry in (data.get(key) or [])
            if clean_text(entry)
        ]

    return {
        "summary": clean_text(data.get("summary")),
        "tasks": tasks,
        "next_steps": clean_list("next_steps"),
        "warnings": clean_list("warnings"),
        "drafts": drafts,
    }


def describe_task(task):
    """'Write report (today 3pm, 2 hours)'"""
    details = [part for part in (task["deadline"], task["duration"]) if part]
    if details:
        return task["task"] + " (" + ", ".join(details) + ")"
    return task["task"]


SECTION_ORDER = (
    ("SUMMARY", "summary"),
    ("ACTION ITEMS", "action_items"),
    ("PRIORITIES", "priorities"),
    ("SUGGESTED NEXT STEPS", "next_steps"),
    ("DRAFTS", "drafts"),
)


def render_sections(clean):
    """Build the text of each section. Returns {section name: text}."""
    tasks = clean["tasks"]

    # Action items
    if tasks:
        action_items = "\n".join("- " + describe_task(t) for t in tasks)
    else:
        action_items = "No actionable tasks."

    # Priorities
    if tasks:
        lines = []
        for level in PRIORITY_LEVELS:
            group = [t for t in tasks if t["priority"] == level]
            lines.append("#### " + level + " PRIORITY (" + str(len(group)) + ")")
            if group:
                for task in group:
                    lines.append("- " + level + ": " + describe_task(task))
            else:
                lines.append("No tasks in this category.")
            lines.append("")
        priorities = "\n".join(lines).strip()
    else:
        priorities = "No tasks to prioritize."

    # Next steps
    if clean["next_steps"]:
        next_steps = "\n".join(
            str(number) + ". " + step
            for number, step in enumerate(clean["next_steps"], start=1)
        )
    else:
        next_steps = "No next steps needed."

    # Drafts
    if clean["drafts"]:
        blocks = []
        for draft in clean["drafts"]:
            block = ""
            if draft["subject"]:
                block += "Subject: " + draft["subject"] + "\n\n"
            block += draft["body"]
            blocks.append(block)
        drafts = "\n\n".join(blocks)
    else:
        drafts = "No drafts needed."

    return {
        "summary": clean["summary"] or "No summary available.",
        "action_items": action_items,
        "priorities": priorities,
        "next_steps": next_steps,
        "drafts": drafts,
    }


def render_result(sections):
    """Join the sections into one text block (kept for older pages)."""
    return "\n\n".join(
        title + ":\n" + sections[key] for title, key in SECTION_ORDER
    )


def organise_notes(user_text):
    """Notes in, (sections dict, warnings list) out."""
    clean = clean_response(call_gemini(user_text))
    return render_sections(clean), clean["warnings"]


# ---------------------------------------------------------------- server

def send_json(handler, status, data):
    response = json.dumps(data).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(response)))
    handler.end_headers()
    handler.wfile.write(response)


class WorkmateHandler(SimpleHTTPRequestHandler):

    def end_headers(self):
        # Never let the browser keep an old copy of the page.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def host_is_allowed(self):
        # Only answer requests addressed to our local host name. This helps
        # block DNS-rebinding style access to the local server.
        return self.headers.get("Host", "").lower() in ALLOWED_HOSTS

    def do_GET(self):
        if not self.host_is_allowed():
            send_json(self, 403, {"error": "Request host not allowed."})
            return
        super().do_GET()

    def do_HEAD(self):
        if not self.host_is_allowed():
            self.send_error(403, "Request host not allowed.")
            return
        super().do_HEAD()

    def do_POST(self):
        if not self.host_is_allowed():
            send_json(self, 403, {"error": "Request host not allowed."})
            return

        # Reject browser requests that come from other websites.
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            send_json(self, 403, {"error": "Request origin not allowed."})
            return

        if self.path != "/organise":
            send_json(self, 404, {"error": "Endpoint not found."})
            return

        try:
            user_text = self.read_notes()
            sections, warnings = organise_notes(user_text)

            # "sections" lets the page read each part directly, so a task
            # that happens to contain a word like "drafts" cannot confuse it.
            # "result" is the same content as one text block.
            send_json(self, 200, {
                "result": render_result(sections),
                "sections": sections,
                "validation_warnings": warnings,
            })

        except UserError as error:
            send_json(self, error.args[1] if len(error.args) > 1 else 400,
                      {"error": str(error.args[0])})

        except Exception as error:
            # Details stay in this console window, not in the browser.
            print("Error:", str(error))
            send_json(self, 500, {
                "error": "Something went wrong while organising your notes. "
                         "Please try again."
            })

    def read_notes(self):
        """Read and check the request body. Returns the notes text."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            raise UserError("Invalid Content-Length header.", 400)

        if length < 0:
            raise UserError("Invalid request size.", 400)

        if length > MAX_REQUEST_BYTES:
            raise UserError(
                "Request is too large. Please shorten your notes and try again.",
                413,
            )

        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise UserError("Request was not valid JSON.", 400)

        if not isinstance(body, dict):
            raise UserError("Request was not valid JSON.", 400)

        # The page may send the notes under any of these names.
        text = (
            body.get("text")
            or body.get("notes")
            or body.get("user_text")
            or body.get("input")
            or ""
        )

        if not isinstance(text, str):
            raise UserError("Notes must be text.", 400)
        if not text.strip():
            raise UserError("Please enter some notes.", 400)

        return text


def check_page(folder):
    """Return a message saying which index.html is being served."""
    page = os.path.join(folder, "index.html")
    try:
        with open(page, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return "WARNING: could not read " + page

    if "sectionText" in text:
        return "Page file OK (new version): " + page
    return (
        "WARNING: this index.html is an OLD version, so tasks may be cut "
        "off.\n         Replace it with the new index.html: " + page
    )


def main():
    # Serve index.html and friends from the folder this file lives in.
    folder = os.path.dirname(os.path.abspath(__file__))
    os.chdir(folder)

    print("AI Workmate server starting...")
    print(check_page(folder))
    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY is not set. Organising notes will fail.")

    try:
        server = HTTPServer((HOST, PORT), WorkmateHandler)
    except OSError:
        print("Could not start: port " + str(PORT) + " is already in use.")
        print("AI Workmate may already be running. Close the other window")
        print("(or press Stop in Thonny) and try again.")
        return 1

    print("Serving AI Workmate at http://" + HOST + ":" + str(PORT))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAI Workmate server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
