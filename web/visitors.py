"""
Gives every visitor their own chatbot, and limits how much it can be used.

On your own computer there is one user, so there is one chatbot and no limit.

On the public link (PUBLIC_MODE=true) many people can open the page. Without
this file they would all share one memory: one person could read what another
said, or wipe it. So each visitor gets a random id in a cookie, and that id
picks their own memories and mood log. The models are shared, because they are
large and hold nothing about the user.

The limits protect the API credit, since every message costs a little.
"""

import os
import re
import secrets
import shutil
import threading
import time
from collections import OrderedDict, deque

import config
from chat_engine import ChatEngine
from memory_manager import MemoryManager
from mood_log import MoodLog
from vector_store import ChromaVectorStore

LOCAL_ID = "local"
VALID_ID = re.compile(r"^[0-9a-f]{32}$")


class Visitor:
    """One person's chatbot. The lock makes their messages run one at a time."""

    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.Lock()
        self.recent = deque()       # times of their latest messages


class Visitors:
    def __init__(self):
        # The first engine loads the models. Every visitor reuses them.
        self.shared = ChatEngine()
        self.visitors = OrderedDict()
        self.lock = threading.Lock()
        self.day = None
        self.today_count = 0

        if not config.PUBLIC_MODE:
            self.visitors[LOCAL_ID] = Visitor(self.shared)

    @staticmethod
    def new_id():
        return secrets.token_hex(16)

    def look(self, visitor_id):
        """
        The chatbot to read from, for a page that is only being opened.

        Someone who has not sent anything yet has no chatbot of their own, so
        they see the shared one, which is always empty in PUBLIC_MODE. This
        way opening the page many times cannot push real visitors out.
        """
        with self.lock:
            visitor = self.visitors.get(visitor_id)
        if visitor is None:
            return self.shared
        return visitor.engine

    def get(self, visitor_id):
        """The visitor's chatbot, made the first time they send something."""
        if not config.PUBLIC_MODE:
            return self.visitors[LOCAL_ID]

        with self.lock:
            if visitor_id not in self.visitors:
                # Make room by forgetting whoever has been away the longest.
                while len(self.visitors) >= config.MAX_VISITORS:
                    old_id, old = self.visitors.popitem(last=False)
                    self._delete(old_id, old)
                self.visitors[visitor_id] = Visitor(self._make_engine(visitor_id))
            self.visitors.move_to_end(visitor_id)
            return self.visitors[visitor_id]

    def _folder(self, visitor_id):
        return os.path.join(config.CHROMA_DIR, "visitors", visitor_id)

    def _make_engine(self, visitor_id):
        folder = self._folder(visitor_id)
        os.makedirs(folder, exist_ok=True)
        return ChatEngine(
            memory=MemoryManager(
                store=ChromaVectorStore(collection_name="visitor_" + visitor_id),
                embedder=self.shared.memory.embedder,
                counter_file=os.path.join(folder, "id_counter.json"),
            ),
            llm=self.shared.llm,
            emotion_model=self.shared.emotion_model,
            moods=MoodLog(os.path.join(folder, "mood_log.json")),
        )

    def _delete(self, visitor_id, visitor):
        visitor.engine.memory.wipe_everything()
        shutil.rmtree(self._folder(visitor_id), ignore_errors=True)

    def refuse_reason(self, visitor):
        """
        Why this message cannot be answered right now, or None if it can.

        Counts the message when it is allowed. Crisis messages never come
        here: they cost nothing and must always be answered (see server.py).
        """
        if not config.PUBLIC_MODE:
            return None

        with self.lock:
            now = time.time()
            while visitor.recent and now - visitor.recent[0] > 60:
                visitor.recent.popleft()
            if len(visitor.recent) >= config.MESSAGES_PER_MINUTE:
                return "You are sending messages very quickly. Please wait a minute."

            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            if today != self.day:
                self.day, self.today_count = today, 0
            if self.today_count >= config.MESSAGES_PER_DAY:
                return "This free demo has reached its message limit for today. Please try again tomorrow."

            visitor.recent.append(now)
            self.today_count += 1
            return None


def read_visitor_id(cookie_header):
    """Find our id in the browser's cookies. Anything malformed is ignored."""
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "visitor" and VALID_ID.match(value):
            return value
    return None
