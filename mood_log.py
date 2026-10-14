"""
Remembers how the user felt, across sessions.

This is what joins Jury 1 (long-term memory) to Jury 2 (sentiment). A normal
sentiment bot only knows how you feel in this one message. Ours also knows you
were stressed about exams last week, so it can ask how they went.

Stored as a small JSON file next to the memory database, one entry per
message. A plain file was chosen over ChromaDB because nobody ever searches
moods by meaning; we only ever want "the last few", in order.

Privacy: we store the emotion and a short reason written by the LLM
("worried about exam results"), never the message itself. The reason also
goes through the same private-details filter as everything else.
"""

import json
import os
from datetime import datetime, timezone

import config
from memory_manager import remove_private_details


class MoodLog:
    def __init__(self, path=None):
        self.path = path or os.path.join(config.CHROMA_DIR, "mood_log.json")
        self.entries = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.entries, handle, indent=2)

    def add(self, session_id, mood, reason, safety_level):
        """Record one message's emotion. Returns the entry."""
        clean_reason, _ = remove_private_details(reason or "")
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "emotion": mood["emotion"],
            "confidence": mood["confidence"],
            "is_negative": mood["is_negative"],
            "reason": clean_reason[:120],
            "safety_level": safety_level,
        }
        self.entries.append(entry)
        self._save()
        return entry

    def this_session(self, session_id):
        """Every mood from the current session, oldest first."""
        return [e for e in self.entries if e["session_id"] == session_id]

    def earlier_sessions(self, session_id, limit=3):
        """
        The most recent moods from BEFORE this session, newest last.

        Only entries with a reason are useful to the model ("you were worried
        about your interview"), and neutral ones add nothing, so both are
        skipped.
        """
        earlier = [
            e for e in self.entries
            if e["session_id"] != session_id
            and e["emotion"] != "neutral"
            and e["reason"]
        ]
        return earlier[-limit:]

    def recent(self, limit=30):
        """The latest entries, for the mood timeline in the interface."""
        return self.entries[-limit:]

    def clear(self):
        count = len(self.entries)
        self.entries = []
        self._save()
        return count
