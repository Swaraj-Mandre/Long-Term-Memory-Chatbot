"""
Startup check. Run this first, before anything else.

It proves three things work before we build on top of them:
  1. the settings and API key are present
  2. the language model answers
  3. the local embedding model loads and produces sensible vectors

Run it with:   .venv\\Scripts\\python.exe test_connection.py
"""

import config


def check_settings():
    print("[1/3] Checking settings...")
    problems = config.check_configuration()
    if problems:
        for problem in problems:
            print("      FAILED:", problem)
        return False
    print("      OK   model    :", config.LLM_MODEL)
    print("      OK   endpoint :", config.LLM_BASE_URL)
    print("      OK   API key  : found (%d characters)" % len(config.LLM_API_KEY))
    return True


def check_language_model():
    print("[2/3] Calling the language model...")
    from llm_client import LLMClient, LLMError

    client = LLMClient()
    try:
        # No max_tokens limit passed here on purpose. This model thinks before
        # it answers, and that thinking is charged against the limit, so a small
        # value returns an empty answer. We use the generous default from
        # config.py instead.
        reply = client.chat(
            [{"role": "user", "content": "Reply with exactly the word: READY"}]
        )
    except LLMError as error:
        print("      FAILED:", error)
        return False

    print("      OK   reply    :", reply[:60])
    print("      OK   tokens   :", client.total_tokens)
    return True


def check_embedding_model():
    print("[3/3] Loading the local embedding model...")
    print("      (first run downloads about 90 MB, then it is cached)")
    from sentence_transformers import SentenceTransformer
    from numpy import dot

    model = SentenceTransformer(config.EMBEDDING_MODEL)

    # A quick sanity test of the whole idea behind the project: two sentences
    # that mean the same thing should score higher than two unrelated ones.
    vectors = model.encode(
        ["I live in Pune", "My home city is Pune", "I enjoy playing cricket"],
        normalize_embeddings=True,
    )
    similar = float(dot(vectors[0], vectors[1]))
    unrelated = float(dot(vectors[0], vectors[2]))

    print("      OK   dimensions            :", len(vectors[0]))
    print("      OK   same meaning score    : %.3f" % similar)
    print("      OK   unrelated score       : %.3f" % unrelated)

    if similar <= unrelated:
        print("      FAILED: embeddings are not separating meaning correctly")
        return False
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("  Startup check - Chatbot with Long-Term Memory")
    print("=" * 60)

    results = [
        check_settings(),
        check_language_model(),
        check_embedding_model(),
    ]

    print("=" * 60)
    if all(results):
        print("  ALL CHECKS PASSED - ready to build on.")
    else:
        print("  SOME CHECKS FAILED - fix the lines marked FAILED above.")
    print("=" * 60)
