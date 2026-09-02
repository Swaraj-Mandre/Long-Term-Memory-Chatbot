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
from chat_engine import ChatEngine

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# One shared chat engine for the whole server. The demo is single-user, so a
# single engine is correct here. Supporting several users at once would mean
# one engine per user, which is noted as a future extension.
ENGINE = ChatEngine()

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
            "purpose": "Writes the replies, and reads each message to pull out "
                       "lasting facts about the user.",
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
                       "by meaning. Runs on this machine, so stored memories "
                       "never leave it." % config.EMBEDDING_DIMENSIONS,
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


def next_session_id():
    """
    Work out the next session number.

    Session names are counted from what is already in the database rather than
    generated at random, so they run session-1, session-2, session-3 and stay
    correct even after the program is restarted.
    """
    used_numbers = []
    for record in ENGINE.memory.all_memories_for_display():
        name = str(record.get("session_id", ""))
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
        return json.loads(self.rfile.read(length))

    # -- GET ----------------------------------------------------------------
    def do_GET(self):
        if self.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[self.path]
            return self.send_file(filename, content_type)

        if self.path == "/api/memories":
            return self.send_json(200, {
                "memories": ENGINE.memory.all_memories_for_display(),
                "summary": ENGINE.memory.summary(),
            })

        if self.path == "/api/status":
            return self.send_json(200, {
                "session_id": ENGINE.session_id,
                "api_key_present": bool(config.LLM_API_KEY),
                "summary": ENGINE.memory.summary(),
                "stack": describe_tech_stack(),
            })

        return self.send_json(404, {"error": "unknown address"})

    # -- POST ---------------------------------------------------------------
    def do_POST(self):
        try:
            data = self.read_json_body()
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "request body was not valid JSON"})

        if self.path == "/api/chat":
            message = (data.get("message") or "").strip()
            if not message:
                return self.send_json(400, {"error": "message was empty"})
            reply, details = ENGINE.send(message)
            return self.send_json(200, {"reply": reply, "details": details})

        if self.path == "/api/chat/stream":
            # Same turn as /api/chat, but the reply is sent out as it is
            # written instead of after it is finished. /api/chat is kept as
            # well, so the interface still works if streaming is switched off.
            message = (data.get("message") or "").strip()
            if not message:
                return self.send_json(400, {"error": "message was empty"})

            self.start_event_stream()
            try:
                for event in ENGINE.send_stream(message):
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
                    self.send_event({"type": "error", "error": str(error)})
                except OSError:
                    pass
            return

        if self.path == "/api/session/new":
            # Starting a new session clears the recent-messages list. Anything
            # the bot recalls after this came from the database.
            #
            # The number is worked out here rather than in the browser, because
            # only the server can see which sessions already exist.
            ENGINE.start_new_session(next_session_id())
            return self.send_json(200, {"session_id": ENGINE.session_id})

        if self.path == "/api/forget":
            topic = (data.get("topic") or "").strip()
            if not topic:
                return self.send_json(400, {"error": "no topic given"})
            removed = ENGINE.memory.forget(topic)
            return self.send_json(200, {
                "removed": [
                    {"id": record["id"], "text": record["text"]}
                    for record in removed
                ],
                "summary": ENGINE.memory.summary(),
            })

        if self.path == "/api/reset":
            count = ENGINE.memory.wipe_everything()
            ENGINE.start_new_session("session-1")
            return self.send_json(200, {
                "deleted": count,
                "summary": ENGINE.memory.summary(),
            })

        return self.send_json(404, {"error": "unknown address"})


def run():
    problems = config.check_configuration()

    print("=" * 64)
    print("  Chatbot with Long-Term Memory")
    print("  Topic 192  |  Generative AI  |  Model Making")
    print("=" * 64)
    print("  Language model  :", config.LLM_MODEL)
    print("  Embedding model :", config.EMBEDDING_MODEL)
    print("  Memory database :", config.CHROMA_DIR)
    print("  Stored memories :", ENGINE.memory.summary())

    if problems:
        print("-" * 64)
        for problem in problems:
            print("  WARNING:", problem)
        print("  The interface will still open and memory will still work,")
        print("  but the bot cannot write replies without a key.")

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
