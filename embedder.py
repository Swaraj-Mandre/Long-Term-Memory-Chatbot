"""
Turns text into vectors.

A vector is just a list of numbers that represents the meaning of a sentence.
Sentences that mean similar things get similar vectors. That is what lets the
chatbot search its memory by meaning rather than by matching words.

Example: "I live in Pune" and "My home city is Pune" share almost no words, but
their vectors are very close together.

The model runs on this machine. Nothing in the memory store is ever sent over
the network to create these vectors.
"""

import numpy as np

import config


class Embedder:
    """
    Wraps the sentence-transformers model.

    The model is loaded the first time it is actually needed rather than at
    import time, so starting the program stays fast.
    """

    def __init__(self, model_name=None):
        self.model_name = model_name or config.EMBEDDING_MODEL
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts):
        """
        Convert a list of strings into a list of vectors.

        We normalise the vectors to length 1. That is a small but important
        detail: once vectors are normalised, the cosine similarity between two
        of them is just their dot product, which is fast and is exactly what
        Chroma compares when we ask it for similar memories.
        """
        if isinstance(texts, str):
            texts = [texts]

        vectors = self._load().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_one(self, text):
        """Convenience method for a single string."""
        return self.encode([text])[0]

    @staticmethod
    def cosine_similarity(vector_a, vector_b):
        """
        How similar two vectors are, from -1 (opposite) to 1 (identical).

        Because encode() already normalised both vectors, this is a plain dot
        product. It is written out here so the maths behind retrieval is visible
        in our own code rather than hidden inside the database.
        """
        return float(np.dot(vector_a, vector_b))
