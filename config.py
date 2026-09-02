"""
All project settings live here, in one place.

Nothing else in the project hard-codes a model name, a file path, or a tuning
number. If you want to change how the system behaves, change it here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Read the .env file sitting next to this file, so secrets never live in code.
PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# 1. Language model (AtlasCloud, serving DeepSeek v4 Flash)
# ---------------------------------------------------------------------------
# AtlasCloud speaks the standard OpenAI chat-completions format, so the client
# we write against it would also work with other providers later.

LLM_API_KEY = os.getenv("ATLASCLOUD_API_KEY", "")
LLM_BASE_URL = os.getenv("ATLASCLOUD_BASE_URL", "https://api.atlascloud.ai/v1")
LLM_MODEL = os.getenv("ATLASCLOUD_MODEL", "deepseek-ai/deepseek-v4-flash")

# IMPORTANT: DeepSeek v4 Flash is a "reasoning" model. Before it writes the
# answer, it thinks through the problem internally, and that thinking is
# charged against max_tokens. The response separates the two:
#
#     reasoning_content -> the internal thinking (we do not show this)
#     content           -> the actual answer
#
# So max_tokens has to cover BOTH. Setting it too low is dangerous, because the
# reasoning uses up the whole budget and `content` comes back EMPTY with no
# error to warn you. A test asking for one word with max_tokens=10 returned
# nothing at all: 42 tokens of reasoning, 0 tokens of answer.
#
# The values below are generous for this reason. We call for two different
# jobs, so each gets its own settings.

# Job A - writing a reply to the user. A little creativity reads better.
CHAT_TEMPERATURE = 0.3
CHAT_MAX_TOKENS = 3000

# Job B - pulling facts out of a message as JSON. We want the SAME answer every
# time for the same input, so temperature is 0. Creativity here would only
# invent facts the user never said.
EXTRACT_TEMPERATURE = 0.0
EXTRACT_MAX_TOKENS = 3000

LLM_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# 2. Embedding model (runs locally on this machine)
# ---------------------------------------------------------------------------
# This model turns a sentence into a list of 384 numbers (a "vector"). Sentences
# with similar meaning get similar vectors, which is what lets us search memory
# by meaning instead of by keyword.
#
# We run it locally on purpose: the memory store never leaves the laptop. Only
# the current message and the few memories we retrieve are sent to the API.

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


# ---------------------------------------------------------------------------
# 3. Vector database (ChromaDB, stored on disk)
# ---------------------------------------------------------------------------
# Chroma saves to a folder, so memories survive after the program closes. That
# is what makes the memory "long-term" rather than just chat history.

CHROMA_DIR = str(PROJECT_ROOT / "memory_data")
CHROMA_COLLECTION = "long_term_memory"


# ---------------------------------------------------------------------------
# 4. Memory behaviour
# ---------------------------------------------------------------------------

# Layer 1 - how many recent messages we keep word-for-word in the prompt.
WORKING_MEMORY_TURNS = 6

# How many memories we pull from the database for each new message.
RETRIEVAL_TOP_K = 4

# A memory must be at least this similar to the question before we use it.
# Below this, results are usually unrelated and would only confuse the model.
#
# This value was chosen by measurement, not by guessing. Running
# evaluation/evaluate.py tries a range of values and reports what each costs.
#
# It was tuned twice, and the history is worth knowing:
#
#   - 0.25 was the first guess. It silently discarded two correct answers that
#     scored 0.226 and 0.246, so the sweep moved it down to 0.22.
#
#   - Query cleaning was added later (see clean_query in memory_manager.py),
#     which raised the score of every conversational question. With those
#     scores lifted, 0.25 became correct after all: it answers all 22 test
#     questions and returns about 21% less irrelevant material than 0.22.
#
# The lesson is that this number depends on the rest of the pipeline, so re-run
# the sweep whenever the embedding model, the query handling, or the kind of
# stored data changes.
SIMILARITY_THRESHOLD = 0.25

# How much a memory's age counts against it. Two memories can be equally
# relevant, but the newer one is usually the one the user means.
RECENCY_WEIGHT = 0.15

# Facts are worth slightly more than raw conversation lines, because a fact has
# already been cleaned up and condensed.
FACT_BONUS = 0.05

# Once we hold more than this many raw conversation lines, we start dropping the
# least useful ones. Extracted facts are never dropped.
MAX_EPISODIC_MEMORIES = 100


# ---------------------------------------------------------------------------
# 5. Web interface
# ---------------------------------------------------------------------------

WEB_HOST = "127.0.0.1"
WEB_PORT = int(os.getenv("PORT", "8000"))


def check_configuration():
    """
    Check the settings are usable and return a list of problems found.
    Called at startup so failures show up immediately with a clear message,
    instead of as a confusing error later on.
    """
    problems = []

    if not LLM_API_KEY:
        problems.append(
            "ATLASCLOUD_API_KEY is not set. Copy .env.example to .env and "
            "put your key in it."
        )

    if not LLM_BASE_URL.startswith("http"):
        problems.append("ATLASCLOUD_BASE_URL does not look like a URL.")

    return problems
