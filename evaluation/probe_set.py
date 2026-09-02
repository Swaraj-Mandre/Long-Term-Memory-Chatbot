"""
The test data used to measure how well memory retrieval works.

Why this file exists
--------------------
Showing that a demo "works" proves nothing measurable. To say anything honest
about retrieval quality we need a fixed set of memories, a fixed set of
questions, and a written-down answer for which memories SHOULD come back for
each question. That is what this file holds.

The answers were decided by hand before running anything, so the system is
being measured against an expectation rather than being marked on its own work.
"""

# ---------------------------------------------------------------------------
# The facts the chatbot is given before testing starts
# ---------------------------------------------------------------------------
# Each entry is (key, value, session). Sessions are included so the test covers
# facts learned at different times, not all at once.

SEED_FACTS = [
    ("name",              "Swaraj",                 "session-1"),
    ("city",              "Pune",                   "session-1"),
    ("college",           "MIT ADT University",     "session-1"),
    ("course",            "Artificial Intelligence","session-1"),
    ("favourite_food",    "misal pav",              "session-1"),
    ("hobby",             "playing cricket",        "session-2"),
    ("pet",               "a dog named Bruno",      "session-2"),
    ("favourite_sport",   "football",               "session-2"),
    ("language",          "Marathi",                "session-2"),
    ("goal",              "to become an AI engineer","session-3"),
    ("employer",          "Infosys",                "session-3"),
    ("dietary_preference","vegetarian",             "session-3"),
]

# ---------------------------------------------------------------------------
# Raw conversation lines, stored alongside the facts
# ---------------------------------------------------------------------------
# These exist to make the test realistic. A store holding only clean facts is
# far easier to search than a real one, so we add ordinary chatter that the
# retrieval step has to see past.

SEED_MESSAGES = [
    ("I was thinking about what to cook this weekend.",        "session-1"),
    ("The traffic near the campus was terrible yesterday.",    "session-1"),
    ("I watched a really good documentary last night.",        "session-2"),
    ("My laptop has been running slowly lately.",              "session-2"),
    ("It has been raining a lot this week.",                   "session-3"),
    ("I need to finish my assignment before Friday.",          "session-3"),
]

# ---------------------------------------------------------------------------
# The questions, and which memory each one should find
# ---------------------------------------------------------------------------
# "expected_keys" lists the fact keys a correct system should retrieve. Written
# before testing, and not adjusted afterwards to make results look better.

PROBES = [
    {"question": "Where do I live?",                  "expected_keys": ["city"]},
    {"question": "What is my name?",                  "expected_keys": ["name"]},
    {"question": "Which college do I attend?",        "expected_keys": ["college"]},
    {"question": "What food do I like?",              "expected_keys": ["favourite_food"]},
    {"question": "Do I have any pets?",               "expected_keys": ["pet"]},
    {"question": "What sport do I follow?",           "expected_keys": ["favourite_sport"]},
    {"question": "What do I do in my free time?",     "expected_keys": ["hobby"]},
    {"question": "Where do I work?",                  "expected_keys": ["employer"]},
    {"question": "What language do I speak?",         "expected_keys": ["language"]},
    {"question": "What am I studying?",               "expected_keys": ["course"]},
    {"question": "What is my career goal?",           "expected_keys": ["goal"]},
    {"question": "Can I eat chicken?",                "expected_keys": ["dietary_preference"]},
]

# ---------------------------------------------------------------------------
# The same questions, asked the way people actually talk
# ---------------------------------------------------------------------------
# The questions above are written plainly. Real users pad their questions with
# polite openings, and that padding measurably hurts retrieval, because the
# embedding model turns the WHOLE sentence into a single vector and the empty
# words dilute it.
#
# These probes exist to measure that effect and to check that the query
# cleaning step in memory_manager.py actually helps.

CONVERSATIONAL_PROBES = [
    {"question": "Do you remember where I live?",        "expected_keys": ["city"]},
    {"question": "Can you tell me my name?",             "expected_keys": ["name"]},
    {"question": "Do you know which college I go to?",   "expected_keys": ["college"]},
    {"question": "Remind me what food I like",           "expected_keys": ["favourite_food"]},
    {"question": "Hey, do you remember my pet?",         "expected_keys": ["pet"]},
    {"question": "What do you know about my hobby?",     "expected_keys": ["hobby"]},
    {"question": "Can you tell me where I work?",        "expected_keys": ["employer"]},
    {"question": "Do you remember what I am studying?",  "expected_keys": ["course"]},
    {"question": "Tell me about my career goal",         "expected_keys": ["goal"]},
    {"question": "Do you recall what language I speak?", "expected_keys": ["language"]},
]


# ---------------------------------------------------------------------------
# Contradiction tests
# ---------------------------------------------------------------------------
# Each pair updates a fact that already exists. After the update, asking the
# question must return the new value and must NOT return the old one.

CONTRADICTIONS = [
    {
        "key": "city",
        "old_value": "Pune",
        "new_value": "Mumbai",
        "question": "Which city am I living in?",
    },
    {
        "key": "employer",
        "old_value": "Infosys",
        "new_value": "TCS",
        "question": "Who do I work for?",
    },
    {
        "key": "favourite_sport",
        "old_value": "football",
        "new_value": "badminton",
        "question": "What sport do I like most?",
    },
    {
        "key": "dietary_preference",
        "old_value": "vegetarian",
        "new_value": "vegan",
        "question": "What do I eat?",
    },
]
