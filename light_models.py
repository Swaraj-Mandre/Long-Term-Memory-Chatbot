"""
Small versions of the two local models, for servers with little memory.

The normal versions run on PyTorch, which needs about 1 GB of memory. The free
server we deploy on has 512 MB. ONNX is a compact format that runs the same
models without PyTorch, and "quantised" means each number is stored in 8 bits
instead of 32. The models are the same, the scores differ very slightly.

Used only when LIGHT_MODELS=true (see config.py). The files are downloaded by
fetch_models.py into the models/ folder.

Each class copies the one call we use from the normal library, so embedder.py
and sentiment.py do not need to know which version they were given.
"""

import json
import os

import numpy as np

import config


def load_model(name, max_tokens):
    """Open one model and its tokenizer from models/<name>."""
    import onnxruntime
    from tokenizers import Tokenizer

    folder = os.path.join(config.MODELS_DIR, name)

    # One thread, and no large memory pool: the server has a tenth of a CPU.
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False

    session = onnxruntime.InferenceSession(
        os.path.join(folder, "model.onnx"), options,
        providers=["CPUExecutionProvider"],
    )
    tokenizer = Tokenizer.from_file(os.path.join(folder, "tokenizer.json"))
    tokenizer.enable_truncation(max_length=max_tokens)
    tokenizer.no_padding()
    return session, tokenizer


def run_model(session, encoded):
    """Run the model on one tokenized text and return its first output."""
    inputs = {
        "input_ids": np.array([encoded.ids], dtype=np.int64),
        "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
    }
    if any(item.name == "token_type_ids" for item in session.get_inputs()):
        inputs["token_type_ids"] = np.array([encoded.type_ids], dtype=np.int64)
    return session.run(None, inputs)[0][0]


class LightEmbeddingModel:
    """Stands in for SentenceTransformer (all-MiniLM-L6-v2)."""

    def __init__(self):
        self.session, self.tokenizer = load_model("embedding", max_tokens=256)

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        vectors = []
        for text in texts:
            # The model gives one vector per word piece. The sentence vector
            # is their average, then scaled to length 1.
            word_vectors = run_model(self.session, self.tokenizer.encode(text))
            vector = word_vectors.mean(axis=0)
            if normalize_embeddings:
                vector = vector / max(np.linalg.norm(vector), 1e-12)
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


class LightEmotionModel:
    """Stands in for the transformers pipeline (DistilRoBERTa, 7 emotions)."""

    def __init__(self):
        self.session, self.tokenizer = load_model("emotion", max_tokens=512)
        path = os.path.join(config.MODELS_DIR, "emotion", "config.json")
        with open(path, "r", encoding="utf-8") as handle:
            self.labels = json.load(handle)["id2label"]

    def __call__(self, text):
        raw = run_model(self.session, self.tokenizer.encode(text))
        # Softmax: turns the raw scores into probabilities that add up to 1.
        exp = np.exp(raw - raw.max())
        scores = exp / exp.sum()
        return [[
            {"label": self.labels[str(i)], "score": float(score)}
            for i, score in enumerate(scores)
        ]]
