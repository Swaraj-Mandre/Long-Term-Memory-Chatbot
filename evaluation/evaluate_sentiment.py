"""
Measures how well the sentiment and safety parts work (Jury 2, PS 96).

Run it with:
    .venv\\Scripts\\python.exe evaluation\\evaluate_sentiment.py          (local model only, free)
    .venv\\Scripts\\python.exe evaluation\\evaluate_sentiment.py --llm    (also the LLM and the combined result)

It reports three things.

1. Emotion accuracy
   ----------------
   For 42 labelled messages (6 per emotion), how often each reader got the
   right emotion:
       local model alone, LLM alone, and the two combined (what the bot uses).
   Reported overall, and separately for the 7 "hard" messages (sarcasm and
   mixed feelings), because that is where a single model is weakest.

   We also report macro-F1: the F1 score for each emotion, averaged. Plain
   accuracy can look good while one emotion is always missed; macro-F1 cannot.

2. Confusion matrix
   ----------------
   Which emotions get mistaken for which. Shows WHERE the mistakes are.

3. Safety rules
   ------------
   Crisis recall: of the messages that must trigger the safe reply, how many
   did. This one has to be 100%.
   False alarms: of the everyday look-alike phrases ("this traffic is killing
   me"), how many wrongly triggered it.
   Only the fixed rules are tested here, because they are the part that has to
   work even when the LLM is down.
"""

import os
import sys

# Allow importing the project files from the folder above.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safety
import sentiment
from emotion_probe_set import CRISIS_PROBES, EMOTION_PROBES, LOOKALIKE_PROBES

LINE = "-" * 70


# ---------------------------------------------------------------------------
# Getting predictions
# ---------------------------------------------------------------------------
def predict_local(messages):
    model = sentiment.EmotionClassifier()
    return [model.classify(text) for text in messages]


def predict_llm(messages):
    """Ask the LLM, using the exact same prompt the chatbot uses."""
    from chat_engine import READ_MESSAGE_PROMPT
    from llm_client import LLMClient, LLMError

    client = LLMClient()
    answers = []
    for i, text in enumerate(messages, 1):
        print("  asking the LLM %d/%d" % (i, len(messages)), end="\r")
        try:
            result = client.chat_json([
                {"role": "system", "content": READ_MESSAGE_PROMPT},
                {"role": "user", "content": text},
            ])
            label = result.get("emotion") if isinstance(result, dict) else None
        except LLMError:
            label = None
        answers.append(sentiment.clean_llm_emotion(label))
    print()
    return answers


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def accuracy(predicted, expected):
    correct = sum(1 for p, e in zip(predicted, expected) if p == e)
    return correct, len(expected)


def macro_f1(predicted, expected):
    """F1 for each emotion, then the plain average of those."""
    scores = []
    for emotion in sentiment.EMOTIONS:
        true_pos = sum(1 for p, e in zip(predicted, expected) if p == emotion and e == emotion)
        predicted_count = sum(1 for p in predicted if p == emotion)
        actual_count = sum(1 for e in expected if e == emotion)

        precision = true_pos / predicted_count if predicted_count else 0.0
        recall = true_pos / actual_count if actual_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(f1)
    return sum(scores) / len(scores)


def print_row(name, predicted, expected, hard_flags):
    correct, total = accuracy(predicted, expected)
    hard_pred = [p for p, h in zip(predicted, hard_flags) if h]
    hard_exp = [e for e, h in zip(expected, hard_flags) if h]
    hard_correct, hard_total = accuracy(hard_pred, hard_exp)

    print("  %-22s %2d/%d = %5.1f%%    macro-F1 %.3f    hard cases %d/%d" % (
        name, correct, total, 100.0 * correct / total,
        macro_f1(predicted, expected), hard_correct, hard_total))


def print_confusion(predicted, expected):
    short = {e: e[:4] for e in sentiment.EMOTIONS}
    print("  rows = correct emotion, columns = what was predicted")
    print("  %-9s" % "" + "".join("%6s" % short[e] for e in sentiment.EMOTIONS))
    for actual in sentiment.EMOTIONS:
        counts = [
            sum(1 for p, e in zip(predicted, expected) if e == actual and p == guess)
            for guess in sentiment.EMOTIONS
        ]
        print("  %-9s" % actual + "".join("%6s" % (c if c else ".") for c in counts))


def print_mistakes(name, predicted, messages, expected):
    mistakes = [(m, e, p) for m, e, p in zip(messages, expected, predicted) if p != e]
    print("  %s got these wrong:" % name)
    if not mistakes:
        print("      (none)")
    for message, exp, pred in mistakes:
        print("      %-9s -> %-9s %s" % (exp, pred, message[:52]))


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def measure_emotions(use_llm):
    messages = [p[0] for p in EMOTION_PROBES]
    expected = [p[1] for p in EMOTION_PROBES]
    hard = [p[2] for p in EMOTION_PROBES]

    print(LINE)
    print("1. EMOTION ACCURACY  (%d messages, %d of them hard)" % (len(messages), sum(hard)))
    print(LINE)

    local_results = predict_local(messages)
    local_labels = [r["label"] if r else None for r in local_results]
    print_row("Local model alone", local_labels, expected, hard)

    combined_labels = local_labels
    if use_llm:
        llm_labels = predict_llm(messages)
        combined_labels = [
            sentiment.combine(local, llm)["emotion"]
            for local, llm in zip(local_results, llm_labels)
        ]
        print_row("LLM alone", llm_labels, expected, hard)
        print_row("Combined (used by bot)", combined_labels, expected, hard)
    else:
        print("  (run with --llm to also measure the LLM and the combined result)")

    print()
    print(LINE)
    print("2. CONFUSION MATRIX  (%s)" % ("combined" if use_llm else "local model"))
    print(LINE)
    print_confusion(combined_labels, expected)
    print()
    print_mistakes("Local model", local_labels, messages, expected)
    if use_llm:
        print_mistakes("Combined", combined_labels, messages, expected)


def measure_safety():
    print()
    print(LINE)
    print("3. SAFETY RULES  (fixed rules only, no LLM)")
    print(LINE)

    caught = [m for m in CRISIS_PROBES if safety.find_crisis_words(m)]
    missed = [m for m in CRISIS_PROBES if not safety.find_crisis_words(m)]
    false_alarms = [m for m in LOOKALIKE_PROBES if safety.find_crisis_words(m)]

    print("  Crisis recall   %d/%d   %s" % (
        len(caught), len(CRISIS_PROBES),
        "OK" if not missed else "MISSED SOME - must be fixed"))
    for message in missed:
        print("      missed: %s" % message)

    print("  False alarms    %d/%d   %s" % (
        len(false_alarms), len(LOOKALIKE_PROBES),
        "OK" if not false_alarms else "too sensitive"))
    for message in false_alarms:
        print("      fired on: %s" % message)


def main():
    use_llm = "--llm" in sys.argv
    print()
    print("SENTIMENT AND SAFETY EVALUATION")
    measure_emotions(use_llm)
    measure_safety()
    print()


if __name__ == "__main__":
    main()
