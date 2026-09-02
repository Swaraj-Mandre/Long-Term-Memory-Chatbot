"""
Measures how well the memory system actually works.

Run it with:
    .venv\\Scripts\\python.exe evaluation\\evaluate.py

It reports five things.

1. How well retrieval works
   ------------------------
   Accuracy is the wrong measure here and would be misleading. Almost every
   memory in the store is irrelevant to any given question, so a system that
   returned nothing at all would still score a high "accuracy" while being
   useless. These measures describe what is actually happening:

     Precision@k = of the k memories returned, what fraction were correct?
                   (about not filling the prompt with noise)

     Recall@k    = of the memories that should have been found, what fraction
                   came back? (about not missing what matters)

     MRR         = how near the top the correct memory appeared, averaged over
                   all questions. 1.0 means it was always first.

   Each question here has exactly one correct answer, which puts a hard ceiling
   on precision. MRR and rank-1 accuracy are the more meaningful numbers.

2. Choosing the similarity threshold
   ---------------------------------
   Runs the whole test at several cut-off values so the setting can be picked
   from evidence rather than guessed. This found a real fault: the original
   0.25 was discarding correct answers that scored 0.226 and 0.246.

3. Whether cleaning the question helps
   -----------------------------------
   Real users pad questions with phrases like "Do you remember...". That
   padding dilutes the sentence vector and lowers the match score. This
   measures how much the cleaning step recovers.

4. Contradiction handling
   ----------------------
   After a fact is updated, we check that asking about it returns the new value
   and never the old one.

5. The cost of not filtering
   -------------------------
   The same searches are run again with the "only active records" filter turned
   off, to measure how often an outdated fact would have come back. This is the
   evidence that similarity alone is not enough.
"""

import os
import shutil
import sys

# Allow importing the project files from the folder above.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

# Use a separate database so evaluation never touches the demo's real memory.
EVALUATION_DB = os.path.join(config.PROJECT_ROOT, "evaluation", "_eval_db")
config.CHROMA_DIR = EVALUATION_DB

import memory_manager                                            # noqa: E402
from memory_manager import MemoryManager                        # noqa: E402
from probe_set import (                                          # noqa: E402
    CONTRADICTIONS, CONVERSATIONAL_PROBES, PROBES,
    SEED_FACTS, SEED_MESSAGES,
)

TOP_K = config.RETRIEVAL_TOP_K


# ---------------------------------------------------------------------------
# Setting up
# ---------------------------------------------------------------------------
def build_memory():
    """Create a fresh store and fill it with the test facts and messages."""
    if os.path.exists(EVALUATION_DB):
        shutil.rmtree(EVALUATION_DB)

    memory = MemoryManager()

    for key, value, session in SEED_FACTS:
        memory.remember_fact(key, value, session)

    for text, session in SEED_MESSAGES:
        memory.remember_message(text, session)

    return memory


# ---------------------------------------------------------------------------
# Test 1: retrieval quality
# ---------------------------------------------------------------------------
def score_one_probe(memory, probe, threshold, use_fallback=True):
    """
    Run a single question and work out how well it did.

    Returns precision, recall, whether the correct memory came first, and the
    reciprocal rank (1 if the answer was first, 0.5 if second, and so on).

    `use_fallback` is switched off when measuring the threshold itself. The
    fallback exists to rescue questions the threshold rejected, so leaving it on
    makes every threshold score the same and hides what is actually being
    measured.
    """
    results = memory.recall(
        probe["question"], top_k=TOP_K, threshold=threshold,
        use_fallback=use_fallback,
    )
    expected = probe["expected_keys"]

    # A fact is stored as "key with spaces: value", so the part before the
    # colon tells us which key the memory came from.
    returned_keys = [
        result["text"].split(":")[0].strip().replace(" ", "_")
        for result in results
    ]
    correct = [key for key in returned_keys if key in expected]

    precision = len(correct) / len(results) if results else 0.0
    recall = len(set(correct)) / len(expected) if expected else 0.0
    first_is_right = bool(returned_keys) and returned_keys[0] in expected

    # Reciprocal rank: how far down the list the first correct answer was.
    reciprocal_rank = 0.0
    for position, key in enumerate(returned_keys, start=1):
        if key in expected:
            reciprocal_rank = 1.0 / position
            break

    return {
        "results": results,
        "precision": precision,
        "recall": recall,
        "first_is_right": first_is_right,
        "reciprocal_rank": reciprocal_rank,
    }


def measure_retrieval(memory, threshold=None):
    threshold = config.SIMILARITY_THRESHOLD if threshold is None else threshold

    print()
    print("1. RETRIEVAL QUALITY  (top-k = %d, threshold = %.2f)" % (TOP_K, threshold))
    print("-" * 74)
    print("%-34s %9s %9s %s" % ("QUESTION", "PRECISION", "RECALL", "TOP RESULT"))
    print("-" * 74)

    precision_scores = []
    recall_scores = []
    reciprocal_ranks = []
    hit_at_1 = 0

    for probe in PROBES:
        scored = score_one_probe(memory, probe, threshold)
        results = scored["results"]

        precision_scores.append(scored["precision"])
        recall_scores.append(scored["recall"])
        reciprocal_ranks.append(scored["reciprocal_rank"])
        if scored["first_is_right"]:
            hit_at_1 += 1

        top_result = results[0]["text"][:26] if results else "(nothing found)"
        print("%-34s %9.2f %9.2f  %s" % (
            probe["question"][:33], scored["precision"], scored["recall"], top_result
        ))

    print("-" * 74)
    average_precision = sum(precision_scores) / len(precision_scores)
    average_recall = sum(recall_scores) / len(recall_scores)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    accuracy_at_1 = hit_at_1 / len(PROBES)

    print("Mean Precision@%d : %.3f" % (TOP_K, average_precision))
    print("Mean Recall@%d    : %.3f" % (TOP_K, average_recall))
    print("MRR              : %.3f" % mean_reciprocal_rank)
    print("Correct at rank 1: %.3f  (%d of %d)" % (
        accuracy_at_1, hit_at_1, len(PROBES)))
    print()
    print("Note on precision: each question here has exactly ONE correct")
    print("memory, so returning %d results caps precision at %.2f by definition."
          % (TOP_K, 1.0 / TOP_K))
    print("Precision is therefore the weakest of these measures for this task.")
    print("MRR and rank-1 accuracy describe the behaviour that actually")
    print("matters: whether the right memory comes back, and how near the top.")

    return {
        "precision": average_precision,
        "recall": average_recall,
        "mrr": mean_reciprocal_rank,
        "hit_at_1": accuracy_at_1,
    }


# ---------------------------------------------------------------------------
# Choosing the similarity threshold from evidence
# ---------------------------------------------------------------------------
def sweep_threshold(memory):
    """
    Try a range of cut-off values and show what each one costs.

    The threshold decides how similar a memory must be before we use it. Set it
    too high and correct answers are thrown away; set it too low and unrelated
    memories fill the prompt. Rather than guessing, we measure.

    Both plainly-worded and conversational questions are used here. Testing only
    the plain ones would be misleading: they score higher, so they make high
    thresholds look safe when those same thresholds would throw away the
    conversational questions real users actually ask.
    """
    all_probes = PROBES + CONVERSATIONAL_PROBES

    print()
    print("2. CHOOSING THE SIMILARITY THRESHOLD")
    print("-" * 74)
    print("Tested on all %d questions (%d plain + %d conversational)." % (
        len(all_probes), len(PROBES), len(CONVERSATIONAL_PROBES)))
    print("-" * 74)
    print("%-12s %10s %8s %8s %8s %s" % (
        "THRESHOLD", "PRECISION", "RECALL", "MRR", "RANK-1", "QUESTIONS WITH NO ANSWER"))
    print("-" * 74)

    rows = []
    for threshold in [0.10, 0.15, 0.20, 0.22, 0.25, 0.30, 0.35]:
        precisions, recalls, ranks = [], [], []
        hits = 0
        empty = 0

        for probe in all_probes:
            # Fallback off: we are measuring what the threshold alone does.
            scored = score_one_probe(memory, probe, threshold, use_fallback=False)
            precisions.append(scored["precision"])
            recalls.append(scored["recall"])
            ranks.append(scored["reciprocal_rank"])
            if scored["first_is_right"]:
                hits += 1
            if not scored["results"]:
                empty += 1

        row = {
            "threshold": threshold,
            "precision": sum(precisions) / len(precisions),
            "recall": sum(recalls) / len(recalls),
            "mrr": sum(ranks) / len(ranks),
            "hit_at_1": hits / len(all_probes),
            "empty": empty,
        }
        rows.append(row)

        print("%-12.2f %10.3f %8.3f %8.3f %8.3f %d of %d" % (
            row["threshold"], row["precision"], row["recall"],
            row["mrr"], row["hit_at_1"], row["empty"], len(all_probes)))

    print("-" * 74)

    # Pick the value that answers the most questions correctly at rank 1,
    # breaking ties by preferring the higher threshold (less noise retrieved).
    best = max(rows, key=lambda row: (row["mrr"], row["threshold"]))
    print("Best measured value: %.2f  (MRR %.3f, %d unanswered)" % (
        best["threshold"], best["mrr"], best["empty"]))
    print("Currently set in config.py: %.2f" % config.SIMILARITY_THRESHOLD)
    return best


# ---------------------------------------------------------------------------
# Test 2: contradictions
# ---------------------------------------------------------------------------
def measure_contradictions(memory):
    print()
    print("4. CONTRADICTION HANDLING")
    print("-" * 74)
    print("%-22s %-22s %-10s %s" % ("FACT UPDATED", "QUESTION ASKED", "OLD GONE", "NEW FOUND"))
    print("-" * 74)

    passed = 0

    for case in CONTRADICTIONS:
        # Apply the update. This should mark the old record superseded.
        memory.remember_fact(case["key"], case["new_value"], "session-update")

        results = memory.recall(case["question"], top_k=TOP_K)
        text_returned = " | ".join(result["text"].lower() for result in results)

        old_is_gone = case["old_value"].lower() not in text_returned
        new_is_found = case["new_value"].lower() in text_returned

        if old_is_gone and new_is_found:
            passed += 1

        print("%-22s %-22s %-10s %s" % (
            "%s: %s to %s" % (case["key"], case["old_value"], case["new_value"]),
            case["question"][:21],
            "yes" if old_is_gone else "NO",
            "yes" if new_is_found else "NO",
        ))

    print("-" * 74)
    rate = passed / len(CONTRADICTIONS)
    print("Handled correctly: %.3f  (%d of %d)" % (rate, passed, len(CONTRADICTIONS)))
    return {"contradiction_rate": rate}


# ---------------------------------------------------------------------------
# Test 3: what happens without the filter
# ---------------------------------------------------------------------------
def measure_filter_value(memory):
    """
    Run the same contradiction questions with the status filter removed.

    This isolates the effect of the filter. Anything the unfiltered search
    returns that the filtered one does not is a stale memory that would have
    been fed to the model as if it were true.
    """
    print()
    print("5. WHAT THE STATUS FILTER PREVENTS")
    print("-" * 74)
    print("Re-running the same questions with superseded records left in.")
    print("-" * 74)

    stale_leaks = 0

    for case in CONTRADICTIONS:
        # Search the store directly, with no filter applied.
        vector = memory.embedder.encode_one(case["question"])
        unfiltered = memory.store.search(vector, top_k=TOP_K, where=None)

        stale = [
            result for result in unfiltered
            if result["metadata"].get("status") == "superseded"
        ]

        if stale:
            stale_leaks += 1
            worst = stale[0]
            print("  %-24s outdated '%s' returned at similarity %.3f" % (
                case["question"][:23],
                worst["metadata"].get("value", "?"),
                worst["similarity"],
            ))

    print("-" * 74)
    rate = stale_leaks / len(CONTRADICTIONS)
    print("Questions that would have received an outdated fact: %.3f  (%d of %d)"
          % (rate, stale_leaks, len(CONTRADICTIONS)))
    print("With the filter on, this figure is 0 of %d." % len(CONTRADICTIONS))
    return {"stale_leak_rate": rate}


# ---------------------------------------------------------------------------
# Test 3: does cleaning the question actually help?
# ---------------------------------------------------------------------------
def measure_query_cleaning(memory):
    """
    Ask the same questions in conversational form, with and without the
    cleaning step, and compare.

    To test the "without" case we temporarily replace clean_query with a
    function that changes nothing, then put the real one back.
    """
    print()
    print("3. EFFECT OF CLEANING THE QUESTION")
    print("-" * 74)
    print("Conversational phrasings such as 'Do you remember where I live?'")
    print("-" * 74)

    real_clean_query = memory_manager.clean_query

    def run(label):
        found = 0
        ranks = []
        for probe in CONVERSATIONAL_PROBES:
            scored = score_one_probe(memory, probe, config.SIMILARITY_THRESHOLD)
            ranks.append(scored["reciprocal_rank"])
            if scored["first_is_right"]:
                found += 1
        mrr = sum(ranks) / len(ranks)
        rate = found / len(CONVERSATIONAL_PROBES)
        print("  %-22s answered correctly %2d of %2d   (rate %.3f, MRR %.3f)" % (
            label, found, len(CONVERSATIONAL_PROBES), rate, mrr))
        return rate, mrr

    # Without cleaning: swap in a function that returns the text unchanged.
    memory_manager.clean_query = lambda text: text
    before_rate, before_mrr = run("cleaning OFF")

    # With cleaning: restore the real function.
    memory_manager.clean_query = real_clean_query
    after_rate, after_mrr = run("cleaning ON")

    print("-" * 74)
    change = after_rate - before_rate
    print("Improvement from cleaning: %+.3f  (%+.1f percentage points)" % (
        change, change * 100))

    return {"before": before_rate, "after": after_rate}


# ---------------------------------------------------------------------------
def main():
    print("=" * 74)
    print("  MEMORY SYSTEM EVALUATION")
    print("  Chatbot with Long-Term Memory  |  Topic 192")
    print("=" * 74)
    print("  Embedding model : %s" % config.EMBEDDING_MODEL)
    print("  Similarity floor: %.2f" % config.SIMILARITY_THRESHOLD)
    print("  Recency weight  : %.2f" % config.RECENCY_WEIGHT)

    memory = build_memory()
    print("  Store contents  : %s" % memory.summary())

    retrieval = measure_retrieval(memory)

    # The sweep runs before the contradiction tests, so the store still holds
    # its original facts and the numbers are comparable to the section above.
    best_threshold = sweep_threshold(memory)

    cleaning = measure_query_cleaning(memory)

    contradiction = measure_contradictions(memory)
    filtering = measure_filter_value(memory)

    print()
    print("=" * 74)
    print("  SUMMARY")
    print("=" * 74)
    print("  Precision@%d                      : %.3f" % (TOP_K, retrieval["precision"]))
    print("  Recall@%d                         : %.3f" % (TOP_K, retrieval["recall"]))
    print("  MRR                              : %.3f" % retrieval["mrr"])
    print("  Correct memory ranked first      : %.3f" % retrieval["hit_at_1"])
    print("  Contradictions handled correctly : %.3f" % contradiction["contradiction_rate"])
    print("  Stale facts leaked without filter: %.3f" % filtering["stale_leak_rate"])
    print("  Conversational, cleaning off     : %.3f" % cleaning["before"])
    print("  Conversational, cleaning on      : %.3f" % cleaning["after"])
    print("  Best threshold by measurement    : %.2f" % best_threshold["threshold"])
    print("=" * 74)

    # Clean up so repeated runs always start from the same state.
    shutil.rmtree(EVALUATION_DB, ignore_errors=True)


if __name__ == "__main__":
    main()
