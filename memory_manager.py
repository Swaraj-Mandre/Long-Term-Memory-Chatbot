"""
The brain of the project. Decides what gets remembered, what gets returned,
and what happens when the user contradicts something they said earlier.

Three kinds of memory
---------------------
1. Working memory  - the last few messages, kept word-for-word. Lives in the
                     chat engine, not here, and disappears when the program
                     closes.
2. Episodic memory - the raw things the user actually said. Stored here.
3. Semantic memory - short facts pulled out of those messages, such as
                     "city = Pune". Stored here, and this is the layer that
                     handles contradictions.

The important idea
------------------
When the user says something that contradicts an older fact, we do NOT delete
the old one and we do NOT keep both as equals. We mark the old one
"superseded" and leave it in the database. Searches only look at active
records, so the outdated fact can never be retrieved again, but the history is
still there if we want to show how a fact changed over time.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone

import config
import debug_log
from embedder import Embedder
from vector_store import ChromaVectorStore, utc_now


# ---------------------------------------------------------------------------
# Privacy: hide sensitive details before they are ever written to disk
# ---------------------------------------------------------------------------
# This runs on the way IN, not on the way out. That matters: the real phone
# number or email never reaches the database file at all, so even someone
# reading the raw files cannot recover it.

PII_PATTERNS = [
    (re.compile(r"\b[\w.\-]+@[\w\-]+\.\w{2,}\b"), "[EMAIL REMOVED]"),
    (re.compile(r"\b(?:\+91[\s\-]?)?[6-9]\d{9}\b"), "[PHONE REMOVED]"),
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "[ID NUMBER REMOVED]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN REMOVED]"),
]


def remove_private_details(text):
    """
    Replace anything that looks like personal data with a label.

    Returns the cleaned text and a list of what was found, so the interface can
    show the user exactly what was protected.
    """
    found = []
    cleaned = text
    for pattern, replacement in PII_PATTERNS:
        if pattern.search(cleaned):
            found.append(replacement.strip("[]"))
            cleaned = pattern.sub(replacement, cleaned)
    return cleaned, found


# ---------------------------------------------------------------------------
# Cleaning up the question before we search with it
# ---------------------------------------------------------------------------
# The embedding model turns a whole sentence into one vector, so every word in
# the question affects the result - including words that carry no meaning.
#
# Measured example, searching for the stored memory "city: Pune":
#
#     "where I live"                    scores 0.265
#     "Do you remember where I live?"   scores 0.159
#
# The two questions mean the same thing, but the polite opening drags the score
# down by about 40% and pushes it under the cut-off, so the correct memory is
# never found. Stripping these openings before searching fixes it.
#
# Note we only clean the text used for SEARCHING. The user's original message
# is what gets stored and what the model sees.

# IMPORTANT: these patterns must never remove a question word such as "where",
# "what", "who" or "which". Those carry the actual meaning of the question and
# are what the stored memory is matched against.
#
# An earlier version stripped them, and it made things worse rather than better:
#
#     "Can you tell me where I stay?"
#         stripped to "I stay"       -> score fell from 0.149 to 0.127
#         stripped to "where I stay" -> score rose  from 0.149 to 0.281
#
# Only genuinely empty words are removed below.

FILLER_PHRASES = [
    r"^(hey|hi|hello|ok|okay|so|and|but)\b[,\s]*",
    r"^(do|does|did)\s+you\s+(remember|know|recall)\s*(that|if)?\b",
    r"^can\s+you\s+(tell|remind|inform)\s+me\s*(about)?\b",
    r"^could\s+you\s+(tell|remind)\s+me\s*(about)?\b",
    r"^(please\s+)?tell\s+me\s*(about)?\b",
    r"^what\s+do\s+you\s+(know|remember)\s+about\b",
    r"^i\s+(want|need)\s+to\s+know\b",
    r"^remind\s+me\s*(about)?\b",
]

FILLER_REGEXES = [re.compile(pattern, re.IGNORECASE) for pattern in FILLER_PHRASES]

# Used only when the normal cut-off finds nothing at all. Anything weaker than
# this is genuinely unrelated and is better left out than guessed at.
RELAXED_THRESHOLD = 0.12


def clean_query(text):
    """
    Remove conversational padding from a question before searching with it.

    Applied repeatedly, because questions often stack two of these together,
    as in "Hey, do you remember where I live?".
    """
    cleaned = text.strip()

    for _ in range(3):                       # a few passes handles stacking
        before = cleaned
        for regex in FILLER_REGEXES:
            cleaned = regex.sub("", cleaned).strip()
        if cleaned == before:
            break

    cleaned = cleaned.strip(" ?.,!")

    # If stripping removed everything, the original was all padding, so fall
    # back to the original rather than searching with an empty string.
    return cleaned if cleaned else text.strip()


# ---------------------------------------------------------------------------
# The memory manager
# ---------------------------------------------------------------------------
class MemoryManager:
    def __init__(self, store=None, embedder=None):
        self.embedder = embedder or Embedder()
        self.store = store or ChromaVectorStore()

        # Memory ids are numbered in order (mem_0001, mem_0002, ...) because
        # readable ids make the demo far easier to follow than random strings.
        # The counter is kept in a small file so numbering continues correctly
        # after the program is restarted.
        self._counter_file = os.path.join(config.CHROMA_DIR, "id_counter.json")
        self._counter = self._load_counter()

    def _load_counter(self):
        try:
            with open(self._counter_file, "r", encoding="utf-8") as handle:
                return json.load(handle)["next_id"]
        except (OSError, KeyError, ValueError):
            return 1

    def _next_id(self):
        memory_id = "mem_%04d" % self._counter
        self._counter += 1
        os.makedirs(config.CHROMA_DIR, exist_ok=True)
        with open(self._counter_file, "w", encoding="utf-8") as handle:
            json.dump({"next_id": self._counter}, handle)
        return memory_id

    # -----------------------------------------------------------------------
    # Writing memories
    # -----------------------------------------------------------------------
    def remember_message(self, text, session_id):
        """
        Store something the user said, word for word (episodic memory).

        This is the raw record. It is useful for questions about the
        conversation itself, like "what did we discuss earlier?".
        """
        clean_text, private_items = remove_private_details(text)
        memory_id = self._next_id()

        self.store.add(
            memory_id=memory_id,
            text=clean_text,
            vector=self.embedder.encode_one(clean_text),
            metadata={
                "type": "episodic",
                "key": "",
                "value": "",
                "status": "active",
                "session_id": session_id,
                "created_at": utc_now(),
                "confidence": 1.0,
                "times_retrieved": 0,
                "privacy_filtered": private_items,
                "superseded_by": "",
            },
        )
        debug_log.privacy(private_items)
        return memory_id

    def remember_fact(self, key, value, session_id, confidence=0.9):
        """
        Store a fact about the user, replacing any earlier version of it.

        This is where contradictions are handled. Returns the new record and
        the old one it replaced (or None if this fact is new).

        Example: the user has "city = Pune" stored and then says they moved to
        Mumbai. The Pune record is marked superseded and a Mumbai record is
        added. Only Mumbai can be retrieved afterwards.
        """
        key = key.strip().lower().replace(" ", "_")
        clean_value, private_items = remove_private_details(str(value).strip())

        previous = self.get_current_fact(key)

        # If the user simply repeats a fact we already hold, there is nothing to
        # replace. We raise our confidence in it slightly and stop here, so the
        # database does not fill up with identical copies.
        if previous and previous["metadata"]["value"].lower() == clean_value.lower():
            new_confidence = min(1.0, float(previous["metadata"]["confidence"]) + 0.05)
            self.store.update_metadata(
                previous["id"],
                {"confidence": new_confidence, "reconfirmed_at": utc_now()},
            )
            return previous, None

        # Store the fact as a short readable sentence. Searching works better on
        # this than on a bare value, because "city: Mumbai" carries more meaning
        # to the embedding model than "Mumbai" alone.
        text = "%s: %s" % (key.replace("_", " "), clean_value)
        memory_id = self._next_id()

        self.store.add(
            memory_id=memory_id,
            text=text,
            vector=self.embedder.encode_one(text),
            metadata={
                "type": "semantic",
                "key": key,
                "value": clean_value,
                "status": "active",
                "session_id": session_id,
                "created_at": utc_now(),
                "confidence": confidence,
                "times_retrieved": 0,
                "privacy_filtered": private_items,
                "superseded_by": "",
            },
        )

        # Retire the old version. Note we only change its labels - the record
        # itself stays in the database as history.
        if previous:
            self.store.update_metadata(previous["id"], {
                "status": "superseded",
                "superseded_by": memory_id,
                "superseded_at": utc_now(),
            })

        written = self.store.get(memory_id)
        debug_log.memory_write(written, previous)
        debug_log.privacy(private_items)
        return written, previous

    # -----------------------------------------------------------------------
    # Reading memories
    # -----------------------------------------------------------------------
    def get_current_fact(self, key):
        """Find the one active fact stored under a key, or None."""
        matches = self.store.find({
            "$and": [
                {"key": key.strip().lower()},
                {"status": "active"},
                {"type": "semantic"},
            ]
        })
        return matches[0] if matches else None

    def recall(self, query, top_k=None, threshold=None, use_fallback=True):
        """
        Find the memories most worth showing the model for this message.

        Two stages:

        Stage 1 - ask Chroma for candidates that are similar in meaning, and
                  tell it to only consider active records. Superseded facts are
                  excluded by the database itself, so they can never win.

        Stage 2 - re-score those candidates ourselves. Similarity alone has a
                  real weakness: it has no sense of time. Two memories can be
                  equally relevant while one is months out of date. So we add a
                  small bonus for being recent, and a small bonus for being a
                  tidy extracted fact rather than a raw sentence.
        """
        top_k = top_k or config.RETRIEVAL_TOP_K

        # The cut-off can be overridden, which is what the evaluation script
        # uses to test several values and pick the best one from evidence.
        if threshold is None:
            threshold = config.SIMILARITY_THRESHOLD

        # Strip conversational padding first. See clean_query above for the
        # measurements showing why this matters.
        search_text = clean_query(query)

        # Ask for more than we need, so stage 2 has room to reorder things.
        candidates = self.store.search(
            vector=self.embedder.encode_one(search_text),
            top_k=top_k * 3,
            where={"status": "active"},
        )

        results = []
        for candidate in candidates:
            similarity = candidate["similarity"]

            # Ignore anything too unrelated to be useful.
            if similarity < threshold:
                continue

            recency = self._recency_score(candidate["metadata"].get("created_at"))
            fact_bonus = (
                config.FACT_BONUS
                if candidate["metadata"].get("type") == "semantic"
                else 0.0
            )

            final_score = (
                similarity
                + config.RECENCY_WEIGHT * recency
                + fact_bonus
            )

            results.append({
                "id": candidate["id"],
                "text": candidate["text"],
                "type": candidate["metadata"].get("type"),
                "similarity": round(similarity, 4),
                "recency": round(recency, 4),
                "score": round(final_score, 4),
                "created_at": candidate["metadata"].get("created_at", ""),
                "session_id": candidate["metadata"].get("session_id", ""),
            })

        # Safety net. If nothing cleared the cut-off but we do have candidates,
        # answering "I know nothing about you" is usually worse than offering
        # the closest thing we have. Rather than lowering the threshold for
        # everyone, we relax it only in this case and mark what comes back as
        # low confidence, so the interface can show it was a weak match.
        #
        # The evaluation script turns this off (use_fallback=False) when
        # measuring the threshold. With it on, every threshold looks equally
        # good, because the net rescues whatever the threshold rejected, and
        # the measurement becomes meaningless.
        if use_fallback and not results and candidates:
            for candidate in candidates[:top_k]:
                if candidate["similarity"] < RELAXED_THRESHOLD:
                    continue
                results.append({
                    "id": candidate["id"],
                    "text": candidate["text"],
                    "type": candidate["metadata"].get("type"),
                    "similarity": round(candidate["similarity"], 4),
                    "recency": round(
                        self._recency_score(candidate["metadata"].get("created_at")), 4
                    ),
                    "score": round(candidate["similarity"], 4),
                    "created_at": candidate["metadata"].get("created_at", ""),
                    "session_id": candidate["metadata"].get("session_id", ""),
                    "low_confidence": True,
                })

        # Best score first, then keep only as many as we asked for.
        results.sort(key=lambda item: item["score"], reverse=True)
        results = results[:top_k]

        # Print the whole search: what was asked, what the store offered, and
        # how each candidate scored. This is the answer to "how do you retrieve
        # the right memory", shown rather than described.
        debug_log.retrieval(query, search_text, candidates, results, threshold)

        # Record that these were used. The pruning step later keeps the
        # memories that keep proving useful and drops the ones that never do.
        for result in results:
            record = self.store.get(result["id"])
            if record:
                used = int(record["metadata"].get("times_retrieved", 0)) + 1
                self.store.update_metadata(result["id"], {"times_retrieved": used})

        return results

    @staticmethod
    def _recency_score(created_at):
        """
        Turn an age into a score between 0 and 1, where 1 means "just now".

        A memory from today scores near 1, one from a week ago scores about
        0.12, one from a year ago is near 0. The drop-off is steep at first and
        then flattens, which matches how people actually treat old information.
        """
        if not created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return 0.0

        age_in_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
        return 1.0 / (1.0 + max(age_in_days, 0.0))

    # -----------------------------------------------------------------------
    # Managing how much is stored
    # -----------------------------------------------------------------------
    def prune(self, limit=None):
        """
        Stop the store from growing without limit.

        Only raw conversation lines are dropped. Extracted facts are kept
        forever, because they are the condensed version of everything the raw
        lines contained.

        Memories are dropped worst-first: least often retrieved, then oldest.
        A memory that keeps being useful survives; one that has never once been
        retrieved is the first to go.

        Why bother: every extra memory is another candidate competing for the
        same few slots in the results, so an oversized store makes retrieval
        LESS accurate, not more.
        """
        limit = limit or config.MAX_EPISODIC_MEMORIES

        episodic = self.store.find({
            "$and": [{"type": "episodic"}, {"status": "active"}]
        })
        if len(episodic) <= limit:
            return []

        episodic.sort(key=lambda record: (
            int(record["metadata"].get("times_retrieved", 0)),
            record["metadata"].get("created_at", ""),
        ))

        to_drop = episodic[: len(episodic) - limit]
        for record in to_drop:
            self.store.update_metadata(record["id"], {"status": "pruned"})

        return [record["id"] for record in to_drop]

    def forget(self, topic):
        """
        Permanently delete everything about a topic, at the user's request.

        This is different from superseding. Superseding keeps history; this
        removes the records completely, which is what a genuine
        "delete my data" request has to do.
        """
        topic = topic.strip().lower()
        matching = [
            record for record in self.store.all_memories()
            if topic in record["text"].lower()
            or topic == str(record["metadata"].get("key", "")).lower()
        ]
        self.store.delete([record["id"] for record in matching])
        return matching

    def wipe_everything(self):
        """Delete the entire memory store and reset the id counter."""
        count = self.store.count()
        self.store.reset()
        self._counter = 1
        try:
            os.remove(self._counter_file)
        except OSError:
            pass
        return count

    # -----------------------------------------------------------------------
    # Information for the interface
    # -----------------------------------------------------------------------
    def summary(self):
        """Counts shown in the statistics panel."""
        everything = self.store.all_memories()

        def count_where(**conditions):
            return sum(
                1 for record in everything
                if all(record["metadata"].get(field) == value
                       for field, value in conditions.items())
            )

        return {
            "total": len(everything),
            "facts": count_where(type="semantic", status="active"),
            "messages": count_where(type="episodic", status="active"),
            "superseded": count_where(status="superseded"),
            "pruned": count_where(status="pruned"),
            "sessions": len({
                record["metadata"].get("session_id") for record in everything
            }),
        }

    def all_memories_for_display(self):
        """Every memory, newest first, ready for the interface to list."""
        everything = self.store.all_memories()
        rows = [
            {
                "id": record["id"],
                "text": record["text"],
                "type": record["metadata"].get("type", ""),
                "status": record["metadata"].get("status", ""),
                "key": record["metadata"].get("key", ""),
                "created_at": record["metadata"].get("created_at", ""),
                "session_id": record["metadata"].get("session_id", ""),
                "superseded_by": record["metadata"].get("superseded_by", ""),
                "privacy_filtered": record["metadata"].get("privacy_filtered", ""),
                "times_retrieved": record["metadata"].get("times_retrieved", 0),
            }
            for record in everything
        ]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return rows
