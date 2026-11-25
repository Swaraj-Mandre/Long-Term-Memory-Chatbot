"""
Downloads the small models used by the deployed version (see light_models.py).

    python fetch_models.py

Not needed on your own computer. Each file is fixed to one exact version and
checked against a known fingerprint (SHA-256), so a changed or damaged download
stops the build instead of being used.
"""

import hashlib
import os
import sys
import urllib.request

import config

EMOTION = ("https://huggingface.co/onnx-community/emotion-english-distilroberta-base-ONNX"
           "/resolve/f4407dc20b99ae081ab2e4f089595e70c1609f59/")
EMBEDDING = ("https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
             "/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/")

# (saved as, downloaded from, SHA-256)
FILES = [
    ("emotion/model.onnx", EMOTION + "onnx/model_quantized.onnx",
     "bb7779bc1a2c8019e52446219c00ac183432298578bb240ac241653559be16a4"),
    ("emotion/tokenizer.json", EMOTION + "tokenizer.json",
     "4638eb0eae8b1e4dfd58155f9b2a798253ef06da7776a76d295e5c033f429f5a"),
    ("emotion/config.json", EMOTION + "config.json",
     "c7d066c43f9412da026b1517d3bc3b22317715e7c62340a255c6cccc268cfdfd"),
    ("embedding/model.onnx", EMBEDDING + "onnx/model_quint8_avx2.onnx",
     "b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21"),
    ("embedding/tokenizer.json", EMBEDDING + "tokenizer.json",
     "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
]


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    for name, url, expected in FILES:
        path = os.path.join(config.MODELS_DIR, *name.split("/"))
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            print("downloading", name)
            urllib.request.urlretrieve(url, path)

        if fingerprint(path) != expected:
            os.remove(path)
            sys.exit("FAILED: %s is not the expected file" % name)
        print("ok", name)


if __name__ == "__main__":
    main()
