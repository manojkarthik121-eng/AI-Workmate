from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import re
import difflib
import os
import time
import urllib.request
import urllib.error


HOST = "127.0.0.1"
PORT = 8000
MAX_REQUEST_BYTES = 1024 * 1024  # 1 MiB limit for incoming note requests

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


os.chdir(os.path.dirname(os.path.abspath(__file__)))


def send_json(handler, status, data):
    response = json.dumps(data).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(response)))
    handler.end_headers()
    handler.wfile.write(response)



def extract_response_section(answer, section_name, next_section_name):
    """Extract a section whether headings use Markdown or plain-text labels."""
    text = str(answer or "")

    def heading_pattern(name):
        escaped = re.escape(name).replace(r"\ ", r"\s+")
        return re.compile(
            r"^[ \t]*(?:#{1,6}[ \t]*)?" + escaped
            + r"[ \t]*:?[ \t]*$",
            re.I | re.M
        )

    start_match = heading_pattern(section_name).search(text)
    if not start_match:
        return ""

    content_start = start_match.end()
    while content_start < len(text) and text[content_start] in "\r\n":
        content_start += 1

    end = len(text)
    if next_section_name:
        next_match = heading_pattern(next_section_name).search(text, content_start)
        if next_match:
            end = next_match.start()

    return text[content_start:end].strip()


def section_lines(section_text):
    lines = []
    for line in str(section_text or "").splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        cleaned = cleaned.replace("**", "").strip()
        cleaned = re.sub(r"^#{1,6}\s*", "", cleaned).strip()

        if not cleaned:
            continue

        # Gemini may wrap task details onto a separate continuation line.
        # Attach parenthetical details to the preceding task instead of
        # treating the details as a standalone Action Item or Priority.
        if cleaned.startswith("(") and lines:
            lines[-1] = lines[-1].rstrip() + " " + cleaned
            continue

        # Ignore section labels and empty-state messages, not actual tasks.
        if re.match(
            r"^(HIGH|MEDIUM|LOW)\s+PRIORITY(?:\s*\(\d+\))?\s*$",
            cleaned,
            re.I
        ):
            continue

        if re.match(
            r"^(no actionable tasks|no tasks to prioritize|no tasks in this category|there are no tasks)\b",
            cleaned,
            re.I
        ):
            continue

        if re.match(r"^\d+\s+of\s+\d+\s+tasks?\s+completed$", cleaned, re.I):
            continue

        lines.append(cleaned)

    return lines


def normalise_task(text):
    text = re.sub(r"\b(HIGH|MEDIUM|LOW)\b\s*:?", " ", str(text), flags=re.I)
    text = re.sub(r"\b(TODAY|TOMORROW|THIS WEEKEND|NEXT WEEK)\b", " ", text, flags=re.I)
    text = re.sub(r"\([^)]*\)", " ", text)
    words = re.findall(r"[a-z0-9]+", text.lower())
    ignored = {
        "a", "an", "the", "to", "and", "or", "of", "for", "in", "on",
        "by", "before", "after", "at", "with", "is", "are", "be",
        "do", "does", "need", "needs", "must", "should", "today",
        "tomorrow", "attend", "complete", "finish"
    }
    return [word for word in words if word not in ignored]


def tasks_are_similar(first, second):
    first_words = normalise_task(first)
    second_words = normalise_task(second)

    if not first_words or not second_words:
        return False

    first_set = set(first_words)
    second_set = set(second_words)

    # Exact normalized matches are safe, including short task descriptions.
    if first_set == second_set:
        return True

    overlap = len(first_set.intersection(second_set))
    denominator = min(len(first_set), len(second_set))

    # Require at least two shared meaningful words. A single shared word
    # such as "customer" must not make an email match a customer meeting.
    if overlap >= 2 and denominator > 0:
        if (overlap / denominator) >= 0.75:
            return True

    # Keep fuzzy matching for genuine paraphrases, but use a much higher
    # threshold and avoid fuzzy matching very short descriptions.
    first_text = " ".join(first_words)
    second_text = " ".join(second_words)

    if len(first_words) >= 2 and len(second_words) >= 2:
        return difflib.SequenceMatcher(
            None, first_text, second_text
        ).ratio() >= 0.82

    return False


def extract_scheduled_events(text):
    """Extract likely scheduled commitments using event names and time anchors.

    This is a conservative text heuristic, not a full natural-language parser.
    """
    event_pattern = re.compile(
        r"\b(?:(?P<descriptor>customer|team|manager|client|project|weekly|daily|sales|performance|staff|department|one[- ]on[- ]one)\s+)?"
        r"(?P<kind>meeting|appointment|review|call|interview|demo|training|consultation|session|presentation)\b",
        re.I
    )

    date_pattern = re.compile(
        r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.I
    )
    time_pattern = re.compile(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        re.I
    )

    events = []
    for match in event_pattern.finditer(str(text or "")):
        kind = match.group("kind").lower()
        descriptor = (match.group("descriptor") or "").lower().replace(" ", "-")

        # A bare "review" often means reviewing a document, not attending an event.
        if kind == "review" and not descriptor:
            continue

        # Restrict date/time matching to the same sentence or clause so one
        # meeting cannot accidentally inherit the next meeting's time.
        left_boundaries = [text.rfind(mark, 0, match.start())
                           for mark in (".", "!", "?", ";", "\n")]
        segment_start = max(left_boundaries) + 1

        right_positions = [text.find(mark, match.end())
                           for mark in (".", "!", "?", ";", "\n")]
        right_positions = [position for position in right_positions if position != -1]
        segment_end = min(right_positions) if right_positions else len(text)

        segment = text[segment_start:segment_end]
        local_match_start = match.start() - segment_start
        local_match_end = match.end() - segment_start

        date_match = date_pattern.search(segment)
        date_value = date_match.group(1).lower() if date_match else ""

        time_matches = list(time_pattern.finditer(segment))
        following_times = [item for item in time_matches
                           if 0 <= item.start() - local_match_end <= 110]
        preceding_times = [item for item in time_matches
                           if 0 <= local_match_start - item.end() <= 35]
        if following_times:
            time_match = following_times[0]
        elif preceding_times:
            time_match = preceding_times[-1]
        else:
            time_match = None

        time_value = ""
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")
            meridiem = time_match.group(3).lower()
            time_value = str(hour) + ":" + str(minute).zfill(2) + meridiem

        # Keep different timed instances distinct, while deduplicating repeated
        # references to the same event at the same time.
        events.append((descriptor, kind, date_value, time_value))

    unique_events = []
    for event in events:
        if event not in unique_events:
            unique_events.append(event)

    return unique_events


def event_is_present(source_event, action_events):
    source_descriptor, source_kind, source_date, source_time = source_event

    for action_event in action_events:
        action_descriptor, action_kind, action_date, action_time = action_event

        if source_kind != action_kind or source_descriptor != action_descriptor:
            continue

        if source_date and action_date and source_date != action_date:
            continue

        if source_time and action_time and source_time != action_time:
            continue

        return action_event

    return None



def split_note_sentences(text):
    """Split notes into short clauses for conservative duration matching."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def duration_matches(text):
    """Return explicit hour/minute durations as minutes, preserving order."""
    pattern = re.compile(
        r"\b(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>hours?|hrs?|minutes?|mins?)\b",
        re.I
    )
    found = []
    for match in pattern.finditer(str(text or "")):
        amount = float(match.group("amount"))
        unit = match.group("unit").lower()
        minutes = int(round(amount * (60 if unit.startswith(("h", "hr")) else 1)))
        found.append((minutes, match.group(0)))
    return found


def date_label_in_text(text):
    match = re.search(
        r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        str(text or ""),
        re.I
    )
    return match.group(1).lower() if match else ""


def is_fixed_commitment_text(text):
    value = str(text or "")
    # "Product presentation" / "prepare the presentation" usually means a
    # deliverable, not an appointment whose duration should be excluded from
    # flexible-work estimates.
    if re.search(r"\b(product presentation|prepare (?:the )?presentation|finish (?:the )?presentation)\b", value, re.I):
        value = re.sub(r"\bpresentation\b", "deliverable", value, flags=re.I)
    return bool(re.search(
        r"\b(meeting|appointment|manager review|team review|customer review|"
        r"interview|demo|training|consultation|presentation|scheduled call)\b",
        value,
        re.I
    ))


def extract_available_work_windows(user_text):
    """Extract day-specific available work time; meetings are not deducted."""
    windows = {}
    for sentence in split_note_sentences(user_text):
        if not re.search(r"\bavailable\b", sentence, re.I):
            continue

        dates = list(re.finditer(
            r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            sentence,
            re.I
        ))
        durations = list(re.finditer(
            r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)\b",
            sentence,
            re.I
        ))

        for date_match in dates:
            preceding = []
            following = []
            for duration_match in durations:
                if duration_match.end() <= date_match.start():
                    distance = date_match.start() - duration_match.end()
                    if distance <= 55:
                        preceding.append((distance, duration_match))
                elif duration_match.start() >= date_match.end():
                    distance = duration_match.start() - date_match.end()
                    if distance <= 35:
                        following.append((distance, duration_match))

            candidates = preceding if preceding else following
            if not candidates:
                continue

            duration_match = sorted(candidates, key=lambda item: item[0])[0][1]
            amount = float(duration_match.group(1))
            unit = duration_match.group(2).lower()
            minutes = int(round(amount * (60 if unit.startswith(("h", "hr")) else 1)))
            day = date_match.group(1).lower()
            # If the same day is mentioned more than once, use the largest
            # explicitly stated window rather than accidentally double-counting it.
            windows[day] = max(windows.get(day, 0), minutes)

    return windows


def extract_work_duration_mentions(user_text):
    """Find explicit durations for flexible work, excluding fixed events."""
    sentences = split_note_sentences(user_text)
    mentions = []

    for index, sentence in enumerate(sentences):
        durations = duration_matches(sentence)
        if not durations:
            continue
        # Availability figures describe capacity, not task effort.
        if re.search(r"\bavailable\b", sentence, re.I):
            continue

        context = sentence
        # Link a short follow-up such as "It will take 2 hours" to the
        # immediately preceding task sentence.
        if re.match(r"^(it|this|that)\s+(?:will\s+)?take\b", sentence, re.I):
            if index > 0:
                context = sentences[index - 1]

        combined = context + " " + sentence
        if is_fixed_commitment_text(combined):
            continue

        day = date_label_in_text(context) or date_label_in_text(sentence)

        # A task's estimate and its deadline are often stated in separate
        # sentences (for example, "report takes 3 hours" followed by
        # "the report is due today"). Link an unambiguous shared task noun
        # so capacity validation can compare the estimate with that day's
        # available work window.
        if not day:
            context_words = {
                word for word in normalise_task(context)
                if len(word) >= 4 and not word.isdigit()
            }
            for candidate in sentences:
                if not re.search(r"\b(due|deadline)\b", candidate, re.I):
                    continue
                candidate_day = date_label_in_text(candidate)
                if not candidate_day:
                    continue
                candidate_words = {
                    word for word in normalise_task(candidate)
                    if len(word) >= 4 and not word.isdigit()
                }
                if context_words.intersection(candidate_words):
                    day = candidate_day
                    break

        for minutes, original in durations:
            mentions.append({
                "context": context,
                "day": day,
                "minutes": minutes,
                "original": original
            })

    return mentions


def duration_context_matches(source_context, action_text):
    """Match a duration-bearing source sentence to its Action Item."""
    if tasks_are_similar(source_context, action_text):
        return True

    ignored = {
        "i", "my", "we", "our", "it", "this", "that", "taking", "total",
        "duration", "hour", "hours", "hr", "hrs", "minute", "minutes",
        "min", "mins", "am", "pm", "today", "tomorrow", "monday",
        "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    }

    def meaningful_words(value):
        return {
            word for word in normalise_task(value)
            if word not in ignored and not word.isdigit()
        }

    source_words = meaningful_words(source_context)
    action_words = meaningful_words(action_text)
    return bool(action_words) and action_words.issubset(source_words)


def format_minutes(minutes):
    if minutes % 60 == 0:
        hours = minutes // 60
        return str(hours) + (" hour" if hours == 1 else " hours")
    if minutes > 60:
        hours = minutes // 60
        remainder = minutes % 60
        return str(hours) + " hour " + str(remainder) + " minutes"
    return str(minutes) + (" minute" if minutes == 1 else " minutes")


def validate_schedule_capacity(user_text, action_items):
    """Flag explicit duration omissions and day-window capacity risks.

    Available work time is interpreted as focused work time, excluding fixed
    meetings and appointments. This is a conservative heuristic, not a full
    calendar or natural-language scheduling engine.
    """
    warnings = []
    windows = extract_available_work_windows(user_text)

    # Preserve durations for fixed appointments separately from flexible work.
    for sentence in split_note_sentences(user_text):
        event_durations = duration_matches(sentence)
        source_events = extract_scheduled_events(sentence)
        if not event_durations or not source_events:
            continue

        for source_event in source_events:
            matching_action = None
            for action in action_items:
                action_events = extract_scheduled_events(action)
                if event_is_present(source_event, action_events) is not None:
                    matching_action = action
                    break

            if matching_action is None:
                continue

            action_durations = [value[0] for value in duration_matches(matching_action)]
            for minutes, original in event_durations:
                if minutes not in action_durations:
                    warnings.append(
                        "A stated appointment duration may be missing or changed in Action Items ("
                        + original + "): " + matching_action
                    )

    work_mentions = extract_work_duration_mentions(user_text)

    matched_mentions = []
    for mention in work_mentions:
        matching_action = None
        for action in action_items:
            if duration_context_matches(mention["context"], action):
                matching_action = action
                break

        if matching_action is None:
            continue

        matched_mentions.append((mention, matching_action))
        action_durations = [value[0] for value in duration_matches(matching_action)]
        if mention["minutes"] not in action_durations:
            warnings.append(
                "A stated work duration may be missing or changed in Action Items ("
                + mention["original"] + "): " + matching_action
            )

    # Check cumulative capacity through today/tomorrow so work due tomorrow
    # can use any explicitly available work time today as well.
    day_order = ["today", "tomorrow"]
    for deadline_index, deadline_day in enumerate(day_order):
        required = sum(
            mention["minutes"]
            for mention, action in matched_mentions
            if mention["day"] in day_order[:deadline_index + 1]
        )
        relevant_days = day_order[:deadline_index + 1]
        if not any(day in windows for day in relevant_days):
            continue
        # Only compare when each day represented by a dated work estimate has
        # a corresponding availability window; missing windows are unknown.
        dated_work_days = {
            mention["day"] for mention, action in matched_mentions
            if mention["day"] in relevant_days
        }
        if not dated_work_days or not dated_work_days.issubset(set(windows)):
            continue
        available = sum(windows.get(day, 0) for day in relevant_days)
        if required > available:
            warnings.append(
                "Stated work may exceed available working time through "
                + deadline_day + ": " + format_minutes(required)
                + " required versus " + format_minutes(available)
                + " available. Fixed meetings are excluded from this calculation."
            )
            break

    # Avoid repeating the same duration warning if multiple source mentions
    # map to the same Action Item.
    unique_warnings = []
    for warning in warnings:
        if warning not in unique_warnings:
            unique_warnings.append(warning)
    return unique_warnings



def preserve_work_durations_in_sections(user_text, answer):
    """Copy explicit task-effort estimates into matching Action Items and Priorities.

    This is a deterministic formatting safeguard: it does not invent estimates
    and only copies durations explicitly stated by the user.
    """
    mentions = extract_work_duration_mentions(user_text)
    if not mentions:
        return answer

    def update_section(text, heading, next_heading, priority_mode=False):
        pattern = re.compile(
            r"(^[ \t]*(?:#{1,6}[ \t]*)?" + re.escape(heading)
            + r"[ \t]*:?[ \t]*\n)(.*?)(?=^[ \t]*(?:#{1,6}[ \t]*)?"
            + re.escape(next_heading) + r"[ \t]*:?[ \t]*$|\Z)",
            re.I | re.M | re.S
        )
        match = pattern.search(text)
        if not match:
            return text

        body = match.group(2)
        updated_lines = []
        for line in body.splitlines():
            stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            task_text = re.sub(r"^\s*(?:HIGH|MEDIUM|LOW)\s*:\s*", "", stripped, flags=re.I)
            if not task_text:
                updated_lines.append(line)
                continue

            durations_to_add = []
            for mention in mentions:
                if duration_context_matches(mention["context"], task_text):
                    existing = [value[0] for value in duration_matches(task_text)]
                    if mention["minutes"] not in existing:
                        label = format_minutes(mention["minutes"])
                        if label not in durations_to_add:
                            durations_to_add.append(label)

            if durations_to_add:
                # Add only user-provided effort estimates; keep deadline text intact.
                suffix = " (" + "; ".join(durations_to_add) + ")"
                line = line.rstrip() + suffix
            updated_lines.append(line)

        # Keep a newline before the next section heading. Without this,
        # headings can be joined to the final task line and later validators
        # cannot reliably extract the sections.
        replacement = match.group(1) + "\n".join(updated_lines) + "\n"
        return text[:match.start()] + replacement + text[match.end():]

    # Apply independently so the same stated estimate appears consistently
    # in both sections without adding or removing tasks.
    answer = update_section(answer, "ACTION ITEMS", "PRIORITIES")
    answer = update_section(answer, "PRIORITIES", "SUGGESTED NEXT STEPS", True)
    return answer


def normalize_escaped_markdown(answer):
    """Normalize Gemini's escaped Markdown control markers robustly."""
    text = str(answer or "")
    # Remove one or more backslashes before Markdown headings and bullets,
    # including when Gemini nests a heading after a bullet marker.
    text = re.sub(r"\\+(?=#{1,6}[ \t]|[-*+][ \t])", "", text)
    # Remove escaping before numbered-list punctuation (e.g. 1\.).
    text = re.sub(r"(?m)^([ \t]*\d+)\\+([.)])", r"\1\2", text)
    # Collapse repeated bullet prefixes, including nested forms such as '- - '.
    text = re.sub(r"(?m)^([ \t]*)(?:[-*+][ \t]+)+", r"\1- ", text)
    return text


def repair_priority_section(answer):
    """Rebuild priorities cleanly and recover task boundaries when Gemini joins lines."""
    action_section = extract_response_section(answer, "ACTION ITEMS", "PRIORITIES")
    priority_section = extract_response_section(answer, "PRIORITIES", "SUGGESTED NEXT STEPS")
    actions = section_lines(action_section)

    # Parse priority task rows even when Gemini prefixes them with dates,
    # bold Markdown, escaped bullets, or a bullet followed by a heading.
    existing = []
    empty_slots = []
    for raw_line in str(priority_section or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\\+", "", line)
        line = re.sub(r"^(?:(?:[-*+•]|\d+[.)])\s*)+", "", line).strip()
        line = line.replace("**", "").replace("\\", "").strip()
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        match = re.search(r"\b(HIGH|MEDIUM|LOW)\s*:\s*(.+?)\s*$", line, re.I)
        if match:
            level, task = match.group(1).upper(), match.group(2).strip()
            # Remove a leading date label such as TOMORROW - from the task.
            task = re.sub(r"^(?:TODAY|TOMORROW|THIS WEEKEND|NEXT WEEK)\s*[-–—:]\s*", "", task, flags=re.I)
            if task:
                existing.append([level, task])
            else:
                empty_slots.append(level)
            continue
        if re.match(r"^(HIGH|MEDIUM|LOW)\s+PRIORITY(?:\s*\(\d+\))?$", line, re.I):
            continue
        if re.match(r"^(no tasks|no tasks to prioritize|no actionable tasks)", line, re.I):
            continue

    # If the Action Items text was accidentally concatenated into fewer lines
    # than the separately listed priority tasks, use those task rows to restore
    # the missing boundaries. This is safer than guessing split points.
    if len(existing) > len(actions):
        recovered = []
        for level, task in existing:
            if not any(tasks_are_similar(task, prior) for prior in recovered):
                recovered.append(task)
        if len(recovered) > len(actions):
            actions = recovered
            action_pattern = re.compile(
                r"(^[ \t]*(?:#{1,6}[ \t]*)?ACTION ITEMS[ \t]*:?[ \t]*\n)(.*?)(?=^[ \t]*(?:#{1,6}[ \t]*)?PRIORITIES[ \t]*:?[ \t]*$|\Z)",
                re.I | re.M | re.S
            )
            action_match = action_pattern.search(answer)
            if action_match:
                action_body = "\n".join(actions)
                answer = (answer[:action_match.start()] + action_match.group(1)
                          + action_body + "\n\n" + answer[action_match.end():])

    if not actions:
        return answer

    matched_action_indexes = set()
    cleaned = []
    for level, task in existing:
        match_index = None
        for index, action in enumerate(actions):
            if index not in matched_action_indexes and tasks_are_similar(action, task):
                match_index = index
                break
        if match_index is not None:
            matched_action_indexes.add(match_index)
            cleaned.append([level, actions[match_index]])

    missing = [action for index, action in enumerate(actions) if index not in matched_action_indexes]
    for action in missing:
        level = empty_slots.pop(0) if empty_slots else "MEDIUM"
        cleaned.append([level, action])

    # Preserve action order within each category, with a stable category order.
    groups = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for level, action in cleaned:
        groups[level].append(action)

    lines = []
    for level in ("HIGH", "MEDIUM", "LOW"):
        lines.append("#### " + level + " PRIORITY (" + str(len(groups[level])) + ")")
        if groups[level]:
            lines.extend("- " + level + ": " + task for task in groups[level])
        else:
            lines.append("No tasks in this category.")
        lines.append("")
    rebuilt = "\n".join(lines).rstrip()

    # Replace the priority section body while retaining all other sections.
    pattern = re.compile(
        r"(^[ \t]*(?:#{1,6}[ \t]*)?PRIORITIES[ \t]*:?[ \t]*\n)(.*?)(?=^[ \t]*(?:#{1,6}[ \t]*)?SUGGESTED NEXT STEPS[ \t]*:?[ \t]*$|\Z)",
        re.I | re.M | re.S
    )
    match = pattern.search(answer)
    if not match:
        return answer
    return answer[:match.start()] + match.group(1) + rebuilt + "\n\n" + answer[match.end():]


def validate_gemini_response(user_text, answer):
    """Flag likely structural omissions without changing Gemini's response."""
    warnings = []

    action_section = extract_response_section(
        answer, "ACTION ITEMS", "PRIORITIES"
    )
    priority_section = extract_response_section(
        answer, "PRIORITIES", "SUGGESTED NEXT STEPS"
    )

    action_items = section_lines(action_section)
    priority_items = section_lines(priority_section)

    # Match one-to-one so duplicate or extra priority entries are detectable.
    unmatched_priorities = list(range(len(priority_items)))

    for action in action_items:
        matched_index = None
        for index in unmatched_priorities:
            if tasks_are_similar(action, priority_items[index]):
                matched_index = index
                break

        if matched_index is None:
            already_present = any(
                tasks_are_similar(action, priority)
                for priority in priority_items
            )
            if already_present:
                warnings.append(
                    "An Action Item may appear more than once in Priorities: " + action
                )
            else:
                warnings.append(
                    "An Action Item may be missing from Priorities: " + action
                )
        else:
            unmatched_priorities.remove(matched_index)

    for index in unmatched_priorities:
        warnings.append(
            "A Priorities entry may not exist in Action Items: "
            + priority_items[index]
        )

    source_events = extract_scheduled_events(user_text)
    action_events = extract_scheduled_events(action_section)

    for event in source_events:
        if event_is_present(event, action_events) is None:
            descriptor, kind, date_value, time_value = event
            event_name = (descriptor + " " + kind).strip()
            if date_value or time_value:
                event_name += " (" + " ".join(
                    value for value in (date_value, time_value) if value
                ) + ")"
            warnings.append(
                "A scheduled commitment may be missing from Action Items: "
                + event_name
            )

    warnings.extend(validate_schedule_capacity(user_text, action_items))

    return warnings


def organise_with_gemini(user_text):

    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY is not configured.")

    prompt = """
You are AI Workmate, an intelligent and practical personal work assistant.

Understand the user's situation before organising their information.
Do not simply convert every sentence into a task.

INTERNAL UNDERSTANDING:

Distinguish internally between:

1. TASKS: Actual actions the user needs or intends to perform.
2. GOALS: Outcomes the user wants to achieve.
3. IDEAS: Possibilities the user is considering.
4. QUESTIONS: Unresolved uncertainties or decisions.
5. CONTEXT: Background information and constraints.

Do not create additional output sections for these categories.

IMPORTANT:
- Do not turn every goal, idea or question into an action item.
- Do not treat a possibility as a confirmed commitment.
- Preserve important context.
- Never invent facts, commitments or deadlines.

Organise the user's information into exactly these five sections:

SUMMARY:

Write 2-4 concise sentences explaining the user's actual situation.
Capture important context, goals, commitments, deadlines and constraints.
Summarise meaning instead of repeating the user's notes.
Avoid generic introductions and unnecessary wording.
Never add unsupported assumptions.

ACTION ITEMS:

List only genuine tasks and commitments.
Do not list hypothetical ideas, undecided possibilities or general wishes.
Preserve the user's intended meaning.
Put every action item on its own line.
Do not duplicate tasks.
If there are no actionable tasks, say so clearly.

COMMITMENT PRESERVATION RULES:
- Include every genuine pending commitment, even if it is not a conventional task.
- Meetings, appointments, calls and scheduled obligations must not disappear.
- Do not omit a commitment because another task has higher priority.
- Completed commitments must not appear as pending tasks.
- Preserve the original timing and duration when provided.
- Distinguish between tasks requiring work and commitments requiring attendance.

MEETING AND APPOINTMENT RULES:
- Every pending meeting, appointment or scheduled obligation must appear in ACTION ITEMS.
- Format attendance commitments as: Attend [meeting/appointment] ([date and time]).
- Include the original duration when provided.
- Include attendance commitments in PRIORITIES exactly once.
- Do not exclude meetings merely because they require attendance rather than preparation.

PRIORITIES:

Classify genuine tasks according to urgency, importance and consequences.

Every task MUST begin with exactly one of these labels:

HIGH: Task description (deadline)
MEDIUM: Task description (deadline)
LOW: Task description (deadline)

HIGH:
Tasks with immediate deadlines, serious consequences if delayed,
or clearly urgent commitments.

MEDIUM:
Important tasks that should be completed reasonably soon,
but are not immediately urgent.

LOW:
Flexible, optional or long-term tasks without immediate consequences.

ADDITIONAL PRIORITY RULES:
- Never assign HIGH priority merely because a task exists.
- No deadline does not automatically mean LOW priority.
- Consider the user's stated goals and circumstances.
- Consider whether a commitment can realistically be postponed.
- Do not assume every meeting or personal commitment is urgent.
- If urgency is unclear, do not invent urgency.
- Preserve all stated deadlines.
- Include each actionable task only once.
- Do not turn ideas or questions into priority tasks.
- Do not create empty priority headings.
- Do not include priority counts or stray numbers.
CONSISTENCY RULES:
- PRIORITIES must contain exactly the same actionable tasks listed in ACTION ITEMS.
- Every Action Item must appear exactly once in PRIORITIES.
- Never introduce a new task in PRIORITIES.
- Never omit an Action Item from PRIORITIES.
- Preserve the original task meaning and description across both sections.
- Only assign a priority level; do not create additional commitments.
- If ACTION ITEMS contains no actionable tasks, PRIORITIES must contain no tasks either.
- If there are no actionable tasks, clearly state: No tasks to prioritize.

DEADLINE RULES:
- Tasks due TODAY are normally HIGH when genuinely urgent.
- Tasks due TOMORROW are normally at least MEDIUM.
- Tasks due THIS WEEKEND or NEXT WEEK are normally LOW unless more urgent.
- Never invent or change a deadline.
- Distinguish confirmed deadlines from uncertain timing.

SUGGESTED NEXT STEPS:

Give practical, specific and logically ordered next actions.

- Start with the most important immediate action.
- Explain what the user should actually do.
- Account for available time, energy and constraints.
- If the user provides available time, create a realistic schedule
  with estimated durations.
  TIME ESTIMATION RULES:
- Never pretend to know exactly how long an unfamiliar task will take.
- Use the user's stated estimates whenever available.
- If task duration is unknown, provide a cautious estimate and clearly identify it as an estimate.
- Break large tasks into smaller, practical steps where useful.
- Do not allocate nearly all available time to one task without justification.
- Prioritise urgent tasks before optional activities.
- Do not schedule optional activities while an urgent commitment remains unfinished.
- Include short breaks when appropriate.
- Preserve some available time as a buffer whenever possible.
- If there is insufficient information to create a reliable schedule, explain what is unknown rather than inventing precision.
- Never schedule more time than the user has available.
- Leave a reasonable buffer when possible.
- Identify scheduling conflicts instead of pretending everything fits.
- If essential information is missing, acknowledge uncertainty.
- Do not repeat the entire Action Items section.

WORK WINDOW RULES:
- Respect separate available work periods, including breaks and lunch.
- Do not assume the user is continuously available between work periods.
- Place tasks within the available time windows while respecting deadlines.
- Use the user's own duration estimates instead of replacing them.
- Show approximate start and end times when the current time and work windows are known.
- Reserve time for final review and submission when relevant.
- Do not schedule a task after its deadline.

MISSING INFORMATION RULES:
- When essential information is missing, ask one concise clarification question.
- Do not create a precise schedule around an unknown meeting time or deadline.
- Distinguish confirmed urgency from assumed urgency.
- Provide a provisional plan only when useful, clearly marking assumptions.
- Never invent task durations merely to fill available time.
- A deadline does not automatically mean the task must be done immediately.
- Schedule tasks according to their actual deadlines and available time.

FORMATTING:
- Use plain numbered steps.
- Put each numbered step on a separate line.
- Do not output literal backslashes before numbers or bullets.
- Avoid combining multiple steps into one paragraph.
- Keep recommendations concise and actionable.

DRAFTS:

Generate drafts only when they would genuinely help the user.
Use a clear subject and message when drafting emails.
Do not generate unnecessary generic drafts.
If no draft is useful, write: No drafts needed.

GENERAL RULES:
- Be practical, clear and concise.
- Understand before recommending.
- Do not manufacture urgency.
- Do not confuse aspirations with commitments.
- Do not repeat information unnecessarily.
- Never invent facts.


USER'S NOTES:

""" + user_text

    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        + GEMINI_MODEL
        + ":generateContent"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        },
        method="POST"
    )

    last_error = None

    for attempt in range(4):

        try:
            with urllib.request.urlopen(
                request,
                timeout=90
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            candidates = result.get("candidates", [])

            if not candidates:
                raise Exception("Gemini returned no response.")

            parts = candidates[0].get("content", {}).get("parts", [])

            answer = "\n".join(
                part.get("text", "")
                for part in parts
                if part.get("text")
            ).strip()

            if not answer:
                raise Exception("Gemini returned an empty response.")

            return answer

        except urllib.error.HTTPError as error:

            last_error = error.read().decode(
                "utf-8",
                errors="replace"
            )

            if error.code not in (429, 500, 502, 503, 504):
                raise Exception(
                    "Gemini API error " + str(error.code)
                    + ": " + last_error
                )

        except urllib.error.URLError as error:
            last_error = str(error)

        if attempt < 3:
            time.sleep(2 * (attempt + 1))

    raise Exception(
        "Gemini request failed after 4 attempts: "
        + str(last_error)
    )


class WorkmateHandler(SimpleHTTPRequestHandler):

    def do_POST(self):

        # Accept browser requests only from the local app's own origins.
        # Requests from other websites are rejected before notes reach Gemini.
        origin = self.headers.get("Origin")
        allowed_origins = {
            "http://127.0.0.1:8000",
            "http://localhost:8000"
        }

        if origin and origin not in allowed_origins:
            send_json(
                self,
                403,
                {"error": "Request origin not allowed."}
            )
            return

        if self.path != "/organise":
            send_json(
                self,
                404,
                {"error": "Endpoint not found."}
            )
            return

        try:
            try:
                content_length = int(
                    self.headers.get("Content-Length", 0)
                )
            except (TypeError, ValueError):
                send_json(
                    self,
                    400,
                    {"error": "Invalid Content-Length header."}
                )
                return

            if content_length < 0:
                send_json(
                    self,
                    400,
                    {"error": "Invalid request size."}
                )
                return

            if content_length > MAX_REQUEST_BYTES:
                send_json(
                    self,
                    413,
                    {"error": "Request is too large. Please shorten your notes and try again."}
                )
                return

            raw_data = self.rfile.read(content_length)

            received_data = json.loads(
                raw_data.decode("utf-8")
            )

            user_text = (
                received_data.get("text")
                or received_data.get("notes")
                or received_data.get("user_text")
                or received_data.get("input")
                or ""
            )

            if not isinstance(user_text, str):
                raise Exception("Notes must be text.")

            if not user_text.strip():
                raise Exception("Please enter some notes.")

            result = organise_with_gemini(user_text)
            # Normalize escaped Markdown before parsing or repairing sections.
            result = normalize_escaped_markdown(result)
            # First preserve explicit effort estimates in Gemini's original
            # Action Items and Priorities sections.
            result = preserve_work_durations_in_sections(user_text, result)
            # Repair priority rows from the final Action Items list.
            result = repair_priority_section(result)
            # Run the duration safeguard again after repair so any priority
            # rows rebuilt from Action Items receive the same stated estimate.
            result = preserve_work_durations_in_sections(user_text, result)
            validation_warnings = validate_gemini_response(
                user_text, result
            )

            send_json(
                self,
                200,
                {
                    "result": result,
                    "validation_warnings": validation_warnings
                }
            )

        except Exception as error:

            print("Error:", str(error))

            send_json(
                self,
                500,
                {"error": str(error)}
            )


print("AI Workmate server starting...")

server = HTTPServer(
    (HOST, PORT),
    WorkmateHandler
)

print(
    "Serving AI Workmate at "
    "http://" + HOST + ":" + str(PORT)
)

try:
    server.serve_forever()

except KeyboardInterrupt:
    print("\nAI Workmate server stopped.")

finally:
    server.server_close()

