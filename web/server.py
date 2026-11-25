"""
The web server behind the interface.

It does two jobs:
  1. serves the three static files that make up the page
  2. answers the small set of API calls the page makes

Built on Python's built-in http.server rather than Flask or FastAPI. For a
single-user demo there is nothing a framework would add here, and using the
standard library means there is no extra dependency to install and nothing
hidden happening between the browser and our own code.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Allow importing the project files that live one folder up.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import safety
from web.visitors import Visitors, read_visitor_id

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# On your own computer this holds one chatbot. On the public link it holds one
# per visitor, so people never see each other's memories (see visitors.py).
VISITORS = Visitors()

# Larger requests are refused. A normal message is far smaller than this.
MAX_BODY_BYTES = 10000

# Which file to serve for which address, and what type each one is.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


def describe_tech_stack():
    """
    What each part of the system is and what it does.

    Shown in the "Tech stack" panel in the interface. Kept here rather than
    written into the page so it always reflects the real settings in config.py.
    """
    return [
        {
            "part": "Language model",
            "value": config.LLM_MODEL,
            "purpose": "Writes the replies in the chosen tone, and reads each "
                       "message for facts and emotion.",
        },
        {
            "part": "Emotion model",
            "value": config.EMOTION_MODEL.split("/")[-1],
            "purpose": "Scores every message against 7 emotions. Runs inside "
                       "the app and is cross-checked against the LLM.",
        },
        {
            "part": "Safety",
            "value": "fixed rules first",
            "purpose": "Crisis phrases trigger a fixed reply with helplines. "
                       "The LLM is never trusted to write that reply.",
        },
        {
            "part": "Model host",
            "value": config.LLM_BASE_URL,
            "purpose": "Where the model is served from. Uses the standard "
                       "chat-completions format.",
        },
        {
            "part": "Embeddings",
            "value": config.EMBEDDING_MODEL.split("/")[-1],
            "purpose": "Turns text into %d numbers so memories can be searched "
                       "by meaning. Runs inside the app, so no outside "
                       "service is used to search." % config.EMBEDDING_DIMENSIONS,
        },
        {
            "part": "Vector database",
            "value": "ChromaDB",
            "purpose": "Stores the memories and finds similar ones. Filters out "
                       "replaced facts during the search, not after it.",
        },
        {
            "part": "Retrieval",
            "value": "cosine + recency",
            "purpose": "Ranks by similarity, then favours newer memories. "
                       "Cut-off %.2f, top %d kept per message."
                       % (config.SIMILARITY_THRESHOLD, config.RETRIEVAL_TOP_K),
        },
        {
            "part": "Interface",
            "value": "Python http.server",
            "purpose": "Plain HTML, CSS and JavaScript with no framework. The "
                       "reply is streamed in as the model writes it.",
        },
    ]


def next_session_id(engine):
    """
    Work out the next session number.

    Session names are counted from what is already in the database rather than
    generated at random, so they run session-1, session-2, session-3 and stay
    correct even after the program is restarted.
    """
    # Sessions can appear in the memory store, the mood log, or both (a
    # crisis-only session stores no memories), so look in both places.
    names = [r.get("session_id", "") for r in engine.memory.all_memories_for_display()]
    names += [m.get("session_id", "") for m in engine.moods.entries]

    used_numbers = []
    for name in names:
        name = str(name)
        if name.startswith("session-"):
            tail = name.split("-", 1)[1]
            if tail.isdigit():
                used_numbers.append(int(tail))

    highest = max(used_numbers) if used_numbers else 0
    return "session-%d" % (highest + 1)


class RequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format_string, *args):
        """Silence the default request logging so the console stays readable."""
        pass

    # -- who is asking ------------------------------------------------------
    def find_visitor_id(self):
        """Read this visitor's id. New visitors are given one in a cookie."""
        self.new_cookie = None
        visitor_id = read_visitor_id(self.headers.get("Cookie"))
        if config.PUBLIC_MODE and visitor_id is None:
            visitor_id = VISITORS.new_id()
            self.new_cookie = (
                "visitor=%s; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax"
                % visitor_id
            )
        return visitor_id

    def end_headers(self):
        if getattr(self, "new_cookie", None):
            self.send_header("Set-Cookie", self.new_cookie)
            self.new_cookie = None
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    # -- small helpers ------------------------------------------------------
    def send_json(self, status_code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- sending a reply in pieces while it is still being written ----------
    # This uses Server-Sent Events, which is just a normal HTTP response that
    # we keep open and write into as text arrives. Each piece is written as:
    #
    #     data: {"type": "token", "text": "Hello"}\n\n
    #
    # The blank line is what tells the browser one event has ended. There is no
    # Content-Length header, because we do not know the length yet, so the
    # browser reads until the connection closes.
    def start_event_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        # Tells any proxy in between not to hold our pieces back and deliver
        # them in one lump, which would defeat the whole point.
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def send_event(self, payload):
        """Write one event and push it out immediately."""
        self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode("utf-8"))
        # Without this flush the pieces sit in a buffer and all arrive at once.
        self.wfile.flush()

    def send_file(self, filename, content_type):
        path = os.path.join(STATIC_DIR, filename)
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            return self.send_json(404, {"error": "file not found: " + filename})

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def read_message(self, data, visitor):
        """
        Get the chat message and check it may be answered.

        Returns (message, None) or (None, reason). A crisis message always
        goes through: it must be answered, and it does not use the LLM.
        """
        message = str(data.get("message") or "").strip()
        if not message:
            return None, "message was empty"
        if config.PUBLIC_MODE:
            message = message[:config.MAX_MESSAGE_CHARS]
        if not safety.find_crisis_words(message):
            reason = VISITORS.refuse_reason(visitor)
            if reason:
                return None, reason
        return message, None

    # -- GET ----------------------------------------------------------------
    def do_GET(self):
        if self.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[self.path]
            return self.send_file(filename, content_type)

        # Lets the host check the app is up without creating a visitor.
        if self.path == "/api/health":
            return self.send_json(200, {"ok": True})

        if self.path not in ("/api/memories", "/api/status"):
            return self.send_json(404, {"error": "unknown address"})

        engine = VISITORS.look(self.find_visitor_id())

        if self.path == "/api/memories":
            return self.send_json(200, {
                "memories": engine.memory.all_memories_for_display(),
                "summary": engine.memory.summary(),
                "moods": engine.moods.recent(),
            })

        if self.path == "/api/status":
            return self.send_json(200, {
                "session_id": engine.session_id,
                "api_key_present": bool(config.LLM_API_KEY),
                "summary": engine.memory.summary(),
                "stack": describe_tech_stack(),
                "public": config.PUBLIC_MODE,
            })

    # -- POST ---------------------------------------------------------------
    def do_POST(self):
        try:
            data = self.read_json_body()
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "request body was not valid JSON"})

        if not self.path.startswith("/api/"):
            return self.send_json(404, {"error": "unknown address"})

        # One request at a time for each visitor, so a double click cannot
        # mix two messages together.
        visitor = VISITORS.get(self.find_visitor_id())
        with visitor.lock:
            self.answer_post(data, visitor)

    def answer_post(self, data, visitor):
        engine = visitor.engine

        if self.path == "/api/chat":
            message, problem = self.read_message(data, visitor)
            if problem:
                return self.send_json(400, {"error": problem})
            reply, details = engine.send(message)
            return self.send_json(200, {"reply": reply, "details": details})

        if self.path == "/api/chat/stream":
            # Same turn as /api/chat, but the reply is sent out as it is
            # written instead of after it is finished. /api/chat is kept as
            # well, so the interface still works if streaming is switched off.
            message, problem = self.read_message(data, visitor)
            if problem:
                self.start_event_stream()
                return self.send_event({"type": "error", "error": problem})

            self.start_event_stream()
            try:
                for event in engine.send_stream(message):
                    self.send_event(event)
            except (BrokenPipeError, ConnectionResetError):
                # The user closed the tab or pressed reload mid-reply. Nothing
                # to report, and the turn was already saved to memory.
                pass
            except Exception as error:                      # noqa: BLE001
                # The connection is already open, so an error cannot be sent
                # as a normal HTTP status code. It goes down the stream instead
                # and the page shows it in the chat.
                try:
                    shown = "Something went wrong." if config.PUBLIC_MODE else str(error)
                    self.send_event({"type": "error", "error": shown})
                except OSError:
                    pass
            return

        if self.path == "/api/session/new":
            # Starting a new session clears the recent-messages list. Anything
            # the bot recalls after this came from the database.
            #
            # The number is worked out here rather than in the browser, because
            # only the server can see which sessions already exist.
            engine.start_new_session(next_session_id(engine))
            return self.send_json(200, {"session_id": engine.session_id})

        if self.path == "/api/forget":
            topic = str(data.get("topic") or "").strip()
            if not topic:
                return self.send_json(400, {"error": "no topic given"})
            removed = engine.memory.forget(topic)
            return self.send_json(200, {
                "removed": [
                    {"id": record["id"], "text": record["text"]}
                    for record in removed
                ],
                "summary": engine.memory.summary(),
            })

        if self.path == "/api/reset":
            count = engine.memory.wipe_everything()
            engine.moods.clear()
            engine.start_new_session("session-1")
            return self.send_json(200, {
                "deleted": count,
                "summary": engine.memory.summary(),
            })

        return self.send_json(404, {"error": "unknown address"})


def run():
    engine = VISITORS.shared
    problems = config.check_configuration()

    print("=" * 64)
    print("  Sentiment-Aware Chatbot with Long-Term Memory")
    print("  PS 96  |  Generative AI  |  Jury 2")
    print("=" * 64)
    print("  Language model  :", config.LLM_MODEL)
    print("  Embedding model :", config.EMBEDDING_MODEL)
    print("  Emotion model   :", config.EMOTION_MODEL)
    print("  Memory database :", config.CHROMA_DIR)
    print("  Stored memories :", engine.memory.summary())

    if problems:
        print("-" * 64)
        for problem in problems:
            print("  WARNING:", problem)
        print("  The interface will still open and memory will still work,")
        print("  but the bot cannot write replies without a key.")

    # Every start of the program is a new conversation. Without this, a
    # restart would carry on as "session-1" and mix with that session's moods.
    engine.start_new_session(next_session_id(engine))
    print("  Session         :", engine.session_id)

    # Load the local models now, so the first message is not slow.
    print("  Loading the local models...")
    engine.emotion_model.classify("hello")
    engine.memory.embedder.encode_one("hello")

    print("=" * 64)
    print("  Open http://%s:%d" % (config.WEB_HOST, config.WEB_PORT))
    print("  Press Ctrl+C to stop")
    print("=" * 64)

    server = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    run()
