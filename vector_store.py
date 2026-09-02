"""
Stores memories and searches them by meaning.

This file is deliberately split into two parts:

  VectorStore      - an interface describing WHAT a memory store must be able
                     to do, without saying how.
  ChromaVectorStore - the actual implementation, using ChromaDB.

Splitting it this way means swapping ChromaDB for a different database later
(Qdrant, for example) needs one new class here and no changes anywhere else in
the project. That is planned as a future extension.

Why ChromaDB was chosen:
  - it saves to a folder on disk, so memories survive closing the program
  - it runs inside our program, with no separate server to start
  - it can filter by metadata DURING the search, which is the important one:
    we can ask for "similar memories WHERE status is active", so outdated
    facts are excluded before the results are ranked, not after.
"""

from datetime import datetime, timezone

import config


def utc_now():
    """Current time as a readable string, e.g. 2026-09-02T04:15:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------
class VectorStore:
    """
    What any memory store must be able to do.

    Every method raises NotImplementedError so that a half-finished replacement
    fails loudly instead of silently doing nothing.
    """

    def add(self, memory_id, text, vector, metadata):
        raise NotImplementedError

    def search(self, vector, top_k, where=None):
        raise NotImplementedError

    def get(self, memory_id):
        raise NotImplementedError

    def find(self, where):
        raise NotImplementedError

    def update_metadata(self, memory_id, changes):
        raise NotImplementedError

    def delete(self, memory_ids):
        raise NotImplementedError

    def count(self):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# The ChromaDB implementation
# ---------------------------------------------------------------------------
class ChromaVectorStore(VectorStore):
    def __init__(self, directory=None, collection_name=None):
        import chromadb

        self.directory = directory or config.CHROMA_DIR
        self.collection_name = collection_name or config.CHROMA_COLLECTION

        # PersistentClient writes to the given folder. Using it instead of the
        # in-memory client is what makes memory survive across sessions.
        self.client = chromadb.PersistentClient(path=self.directory)

        # "cosine" tells Chroma to compare vectors by angle rather than by
        # straight-line distance, which is the right measure for text meaning.
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # -- writing ------------------------------------------------------------
    def add(self, memory_id, text, vector, metadata):
        """
        Save one memory.

        We pass our own vector rather than letting Chroma create one, so the
        embedding model stays under our control and is the same everywhere.
        """
        self.collection.add(
            ids=[memory_id],
            documents=[text],
            embeddings=[vector.tolist()],
            metadatas=[clean_metadata(metadata)],
        )

    def update_metadata(self, memory_id, changes):
        """
        Change the labels on an existing memory without touching its text.

        This is how a fact gets marked as superseded: the record stays exactly
        where it is, and only its status label changes.
        """
        existing = self.get(memory_id)
        if existing is None:
            return False

        merged = dict(existing["metadata"])
        merged.update(changes)
        self.collection.update(
            ids=[memory_id],
            metadatas=[clean_metadata(merged)],
        )
        return True

    def delete(self, memory_ids):
        """Permanently remove memories. Used by the 'forget' feature."""
        if not memory_ids:
            return 0
        self.collection.delete(ids=list(memory_ids))
        return len(memory_ids)

    # -- reading ------------------------------------------------------------
    def search(self, vector, top_k, where=None):
        """
        Find the memories closest in meaning to the given vector.

        The optional `where` filter is applied by the database as part of the
        search. Passing {"status": "active"} means superseded memories are
        never candidates in the first place.

        Returns a list of dicts, each with an id, text, metadata and a
        similarity score between 0 and 1 (higher is more similar).
        """
        if self.count() == 0:
            return []

        results = self.collection.query(
            query_embeddings=[vector.tolist()],
            n_results=min(top_k, self.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        found = []
        # Chroma returns a list-of-lists because it supports several queries at
        # once. We only ever send one, so we read index 0.
        ids = results["ids"][0]
        for position, memory_id in enumerate(ids):
            distance = results["distances"][0][position]
            found.append({
                "id": memory_id,
                "text": results["documents"][0][position],
                "metadata": results["metadatas"][0][position],
                # Chroma gives cosine DISTANCE (0 = identical). Similarity is
                # the opposite, so we subtract from 1 to get the familiar
                # "1 means identical" score.
                "similarity": round(1.0 - float(distance), 4),
            })
        return found

    def get(self, memory_id):
        """Fetch one memory by its id, or None if it does not exist."""
        result = self.collection.get(
            ids=[memory_id], include=["documents", "metadatas"]
        )
        if not result["ids"]:
            return None
        return {
            "id": result["ids"][0],
            "text": result["documents"][0],
            "metadata": result["metadatas"][0],
        }

    def find(self, where):
        """
        Fetch every memory matching a metadata filter, ignoring similarity.

        Used for questions like "give me the active fact for the key 'city'".
        """
        result = self.collection.get(
            where=where, include=["documents", "metadatas"]
        )
        return [
            {
                "id": result["ids"][index],
                "text": result["documents"][index],
                "metadata": result["metadatas"][index],
            }
            for index in range(len(result["ids"]))
        ]

    def all_memories(self):
        """Everything in the store, used by the interface's memory browser."""
        result = self.collection.get(include=["documents", "metadatas"])
        return [
            {
                "id": result["ids"][index],
                "text": result["documents"][index],
                "metadata": result["metadatas"][index],
            }
            for index in range(len(result["ids"]))
        ]

    def count(self):
        return self.collection.count()

    def reset(self):
        """Delete the whole collection and start again. Used by 'wipe memory'."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )


def clean_metadata(metadata):
    """
    Make metadata safe for Chroma to store.

    Chroma only accepts text, numbers and true/false as metadata values.
    Anything else (a list, or None) is converted to a string first, otherwise
    the write fails.
    """
    cleaned = {}
    for key, value in metadata.items():
        if value is None:
            cleaned[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple)):
            cleaned[key] = ",".join(str(item) for item in value)
        else:
            cleaned[key] = str(value)
    return cleaned
