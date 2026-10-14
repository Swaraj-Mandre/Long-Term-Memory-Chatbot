"""
Spots when a user may be in distress, and decides how careful to be.

Three levels:

  0  normal    the reply simply adapts its tone
  1  concern   the user has been negative for several messages in a row, or
               the LLM thinks they are struggling. The reply gently checks in
               and mentions that support exists.
  2  crisis    the user mentions self-harm or suicide. The LLM is NOT asked to
               write the reply. A fixed, reviewed message with helpline numbers
               is shown instead.

Why level 2 uses fixed rules and a fixed reply:
  - a model can misread a message, run out of tokens, or lose its connection
  - in a crisis "usually works" is not good enough
  - fixed patterns never fail silently, and anyone can read this file and see
    exactly what will trigger it

The LLM is still a second check: if it marks a message as "crisis" in words
our patterns did not cover, that also triggers level 2. So the rules catch the
obvious cases with certainty, and the LLM catches the indirect ones.
"""

import re

import config

NORMAL, CONCERN, CRISIS = 0, 1, 2
LEVEL_NAMES = {NORMAL: "normal", CONCERN: "concern", CRISIS: "crisis"}

# Phrases that mean "stop and give the safe reply". Kept deliberately specific
# so everyday phrases like "this traffic is killing me" do not match.
CRISIS_PATTERNS = [
    r"\bkill(ing)? myself\b",
    r"\bend(ing)? my (own )?life\b",
    r"\bend it all\b",
    r"\bsuicid(e|al)\b",
    r"\b(want|wanna|going) to die\b",
    r"\bwish i (was|were) dead\b",
    r"\b(don'?t|do not) want to (live|be alive|exist)\b",
    r"\bno reason to (live|go on)\b",
    r"\bbetter off without me\b",
    r"\b(hurt|harm|cut)(ing)? myself\b",
    r"\bself[- ]?harm\b",
    r"\bcan'?t go on (anymore|like this|living)\b",
    # A few common Hinglish phrasings
    r"\bmar(na|ne) (chahta|chahti)\b",
    r"\bjeena nahi (chahta|chahti)\b",
]
CRISIS_REGEXES = [re.compile(pattern, re.IGNORECASE) for pattern in CRISIS_PATTERNS]

# The reply used at level 2. Written once, carefully, and never generated.
CRISIS_REPLY = (
    "I'm really sorry you're feeling this way, and I'm glad you told me. "
    "You don't have to go through this alone.\n\n"
    "Please talk to someone who can help right now:\n"
    "  - Tele-MANAS (Govt. of India, free, 24x7): 14416\n"
    "  - Emergency services: 112\n\n"
    "If you can, reach out to someone you trust and tell them how you feel. "
    "I'm still here if you want to keep talking."
)

HELPLINES = [
    {"name": "Tele-MANAS", "number": "14416", "note": "Govt. of India, free, 24x7"},
    {"name": "Emergency", "number": "112", "note": "Police, ambulance, fire"},
]


def find_crisis_words(text):
    """Return the crisis phrase found in the text, or None."""
    for regex in CRISIS_REGEXES:
        match = regex.search(text)
        if match:
            return match.group(0)
    return None


def decide_level(message, llm_risk, recent_moods):
    """
    Pick the safety level for this message.

    message       the user's text
    llm_risk      "none", "concern" or "crisis", from the LLM (None if offline)
    recent_moods  this session's earlier results from sentiment.combine(),
                  oldest first, INCLUDING the current message

    Returns {"level": 0/1/2, "name": "...", "reason": "..."}.
    """
    matched = find_crisis_words(message)
    if matched:
        return _result(CRISIS, 'crisis phrase matched: "%s"' % matched)

    if llm_risk == "crisis":
        return _result(CRISIS, "LLM flagged a possible crisis")

    streak = recent_moods[-config.CONCERN_STREAK:]
    if len(streak) == config.CONCERN_STREAK and all(m["is_negative"] for m in streak):
        return _result(CONCERN, "%d negative messages in a row" % config.CONCERN_STREAK)

    if llm_risk == "concern":
        return _result(CONCERN, "LLM noticed the user is struggling")

    return _result(NORMAL, "no signs of distress")


def _result(level, reason):
    return {"level": level, "name": LEVEL_NAMES[level], "reason": reason}
