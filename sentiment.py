"""
Works out how the user feels from their message.

Two readers look at every message:

  1. A local emotion model (DistilRoBERTa, fine-tuned on emotion data).
     Fast, free, and gives the same answer every time, so we can measure it.
     Its weakness: it reads words, not situations. "Great, I failed again"
     contains the word "great" and can come out as joy.

  2. The LLM, which reads the same message in the same call that pulls out
     facts (see chat_engine.py). It understands sarcasm and context, but it
     can be slow, it costs tokens, and the network can fail.

We then combine the two:

  - both agree             -> use it, we are confident
  - they disagree          -> use the LLM, because it read the context,
                              and mark the result as "disagree" so the
                              interface shows it honestly
  - LLM not available      -> use the local model alone, or "neutral" if it
                              is not confident enough

Neither reader alone is enough. Using both, and being open about when they
disagree, is our answer to "how do you detect sentiment reliably?".
"""

import config

EMOTIONS = ["joy", "sadness", "anger", "fear", "surprise", "disgust", "neutral"]

# Emotions that suggest the user is having a hard time. Used for the
# "several bad messages in a row" check and the colour of the mood timeline.
NEGATIVE_EMOTIONS = {"sadness", "anger", "fear", "disgust"}


class EmotionClassifier:
    """The local emotion model. Loaded once, on first use."""

    def __init__(self, model_name=None):
        self.model_name = model_name or config.EMOTION_MODEL
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            # Imported here so the rest of the project still starts quickly
            # even if this model is never used.
            from transformers import pipeline
            self._pipeline = pipeline(
                "text-classification",
                model=self.model_name,
                top_k=None,          # return a score for every emotion
            )
        return self._pipeline

    def classify(self, text):
        """
        Score one message.

        Returns {"label": "sadness", "score": 0.97, "scores": {...all 7...}}
        or None if the model could not be loaded.
        """
        try:
            results = self._load()(text[:512])[0]
        except Exception as error:                          # noqa: BLE001
            print("  emotion model unavailable:", error)
            return None

        scores = {item["label"]: round(item["score"], 4) for item in results}
        best = max(scores, key=scores.get)
        return {"label": best, "score": scores[best], "scores": scores}


def clean_llm_emotion(value):
    """The LLM may answer "Sad" or "sadness." - bring it to one of our labels."""
    if not value:
        return None
    value = str(value).strip().lower().rstrip(".")
    aliases = {"happy": "joy", "happiness": "joy", "sad": "sadness",
               "angry": "anger", "scared": "fear", "afraid": "fear",
               "anxious": "fear", "surprised": "surprise", "disgusted": "disgust"}
    value = aliases.get(value, value)
    return value if value in EMOTIONS else None


def combine(classifier_result, llm_emotion):
    """
    Decide the final emotion from the two readers. See the top of this file.

    Returns a dictionary the interface can show directly:
        emotion      the final label
        confidence   how sure we are, 0 to 1
        agreement    "agree", "disagree", "local only" or "llm only"
        local        what the local model said (label and score)
        llm          what the LLM said
    """
    llm_emotion = clean_llm_emotion(llm_emotion)
    local_label = classifier_result["label"] if classifier_result else None
    local_score = classifier_result["score"] if classifier_result else 0.0

    if local_label and llm_emotion:
        if local_label == llm_emotion:
            emotion, agreement = local_label, "agree"
            confidence = local_score
        else:
            emotion, agreement = llm_emotion, "disagree"
            # Lower confidence on purpose: the two readers did not agree.
            confidence = classifier_result["scores"].get(llm_emotion, 0.0)
            confidence = max(confidence, 0.5)

    elif local_label:
        agreement = "local only"
        if local_score >= config.EMOTION_MIN_CONFIDENCE:
            emotion, confidence = local_label, local_score
        else:
            emotion, confidence = "neutral", local_score

    elif llm_emotion:
        emotion, agreement, confidence = llm_emotion, "llm only", 0.6

    else:
        emotion, agreement, confidence = "neutral", "none", 0.0

    return {
        "emotion": emotion,
        "confidence": round(confidence, 2),
        "agreement": agreement,
        "local": {"label": local_label, "score": round(local_score, 2)},
        "llm": llm_emotion,
        "is_negative": emotion in NEGATIVE_EMOTIONS,
    }
