"""
Prints what the system is actually doing to the console.

Turn it on or off with DEBUG_LOG in config.py, or DEBUG=true in your .env file.

When it is on, every turn prints:

  1. the message sent to the model to extract facts, and its raw reply
  2. every fact written, and any older fact that was replaced
  3. the search: the cleaned query, the candidates, and how each was scored
  4. the full prompt used to write the reply, including the injected memories
  5. token usage

The fourth one is the most useful. It shows exactly which memories reached the
model, which is the thing most people assume rather than check.

Safety note: this module must never crash the program. The Windows console
cannot encode every character a model might return, so a plain print() of raw
model output can raise UnicodeEncodeError and take the server down with it.
Every write here goes through safe_write, which replaces characters the console
cannot handle instead of failing.
"""

import json
import sys

import config

WIDTH = 78


def _enabled():
    return bool(getattr(config, "DEBUG_LOG", False))


def safe_write(text):
    """
    Write a line to the console without ever raising.

    Falls back to replacing unencodable characters, and gives up silently if
    even that fails. Logging is never worth breaking the application for.
    """
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(encoding, "replace").decode(encoding) + "\n")
    except Exception:                                       # noqa: BLE001
        pass


def _shorten(text, limit=None):
    """Cut long text down so one huge prompt cannot flood the console."""
    limit = limit or getattr(config, "DEBUG_MAX_CHARS", 700)
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n      ... [%d more characters]" % (len(text) - limit)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
def turn_header(number, session_id, message):
    if not _enabled():
        return
    safe_write("")
    safe_write("=" * WIDTH)
    safe_write(" TURN %d   |   %s" % (number, session_id))
    safe_write(" user: %s" % _shorten(message, 160))
    safe_write("=" * WIDTH)


def step(number, title):
    if not _enabled():
        return
    label = " [%d] %s " % (number, title.upper())
    safe_write("")
    safe_write("--- " + label + "-" * max(0, WIDTH - len(label) - 4))


def field(name, value):
    if not _enabled():
        return
    safe_write("  %-14s %s" % (name, value))


def block(name, text):
    """Print a multi-line value, indented so it reads as one unit."""
    if not _enabled():
        return
    safe_write("  %s:" % name)
    for line in _shorten(text).split("\n"):
        safe_write("      " + line)


def as_json(name, obj):
    if not _enabled():
        return
    try:
        text = json.dumps(obj, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(obj)
    block(name, text)


def note(text):
    if not _enabled():
        return
    safe_write("  " + text)


# ---------------------------------------------------------------------------
# The specific things we log
# ---------------------------------------------------------------------------
def llm_request(purpose, model, temperature, max_tokens, messages):
    """The exact request going to the language model."""
    if not _enabled():
        return
    field("purpose", purpose)
    field("model", model)
    field("settings", "temperature=%s  max_tokens=%s" % (temperature, max_tokens))
    safe_write("  messages sent:")
    for m in messages:
        safe_write("    [%s]" % m["role"])
        for line in _shorten(m["content"]).split("\n"):
            safe_write("        " + line)


def llm_response(content, reasoning=None, usage=None, finish_reason=None):
    """What came back, including the model's internal reasoning if present."""
    if not _enabled():
        return
    if finish_reason:
        field("finish reason", finish_reason)

    # DeepSeek v4 Flash thinks before it answers. That thinking is billed and
    # is worth seeing, because it explains an empty answer when the token
    # budget runs out during it.
    if reasoning:
        block("model reasoning", reasoning)

    block("raw reply", content if content else "(empty)")

    if usage:
        parts = ["prompt=%s" % usage.get("prompt_tokens"),
                 "completion=%s" % usage.get("completion_tokens"),
                 "total=%s" % usage.get("total_tokens")]
        if usage.get("reasoning_tokens") is not None:
            parts.append("of which reasoning=%s" % usage["reasoning_tokens"])
        field("tokens", "  ".join(parts))


def retrieval(raw_query, clean_query, candidates, results, threshold):
    """The search, from query to final ranking."""
    if not _enabled():
        return

    field("query as typed", _shorten(raw_query, 160))
    if clean_query != raw_query:
        field("query searched", _shorten(clean_query, 160))
        note("(conversational padding removed before searching)")
    field("threshold", "%.2f" % threshold)

    safe_write("  candidates returned by the store, filtered to status=active:")
    if not candidates:
        safe_write("      (none, the store is empty)")
    for i, c in enumerate(candidates, 1):
        safe_write("      %2d. %-9s %-9s cos=%.4f  %s" % (
            i, c["id"], c["metadata"].get("type", "?"), c["similarity"],
            _shorten(c["text"], 44).replace("\n", " ")))

    safe_write("  after scoring (cosine + recency bonus + fact bonus):")
    if not results:
        safe_write("      (nothing cleared the threshold)")
    kept = {r["id"] for r in results}
    for i, r in enumerate(results, 1):
        safe_write("      %2d. %-9s cos=%.4f rec=%.4f -> %.4f  %s%s" % (
            i, r["id"], r["similarity"], r["recency"], r["score"],
            "USED", "  (weak match)" if r.get("low_confidence") else ""))
    dropped = [c for c in candidates if c["id"] not in kept]
    for c in dropped[:4]:
        safe_write("          dropped %-9s cos=%.4f  below threshold" % (
            c["id"], c["similarity"]))


def memory_write(record, replaced):
    """A fact being stored, and the older version it retired."""
    if not _enabled():
        return
    meta = record["metadata"]
    field("fact stored", "%s = %s   (%s)" % (meta["key"], meta["value"], record["id"]))
    if replaced is not None:
        old = replaced["metadata"]
        safe_write("  REPLACED       %s = %s   (%s now superseded by %s)" % (
            old["key"], old["value"], replaced["id"], record["id"]))


def privacy(items):
    if not _enabled() or not items:
        return
    field("privacy", "removed before saving: %s" % ", ".join(items))


def turn_footer(summary, pruned_count):
    if not _enabled():
        return
    safe_write("")
    safe_write("  store now: %s" % summary)
    if pruned_count:
        safe_write("  trimmed %d old message(s) to stay under the cap" % pruned_count)
    safe_write("=" * WIDTH)
    safe_write("")
