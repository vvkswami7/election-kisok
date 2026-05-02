import argparse
import logging
import os
from typing import Any

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from backend import CHROMA_COLLECTION_NAME, EMBEDDING_MODEL, load_election_data


logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def build_collection(chroma_path: str, embedding_model: str) -> Any:
    chroma_client = chromadb.PersistentClient(
        path=chroma_path,
        settings=Settings(anonymized_telemetry=False),
    )
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=embedding_model
    )
    return chroma_client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_fn,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Index local election data into ChromaDB.")
    parser.add_argument(
        "--chroma-path",
        default=os.getenv("CHROMA_PATH", "./chroma_db"),
        help="Directory for the persistent ChromaDB store.",
    )
    parser.add_argument(
        "--embedding-model",
        default=EMBEDDING_MODEL,
        help="SentenceTransformer model used for local embeddings.",
    )
    args = parser.parse_args()

    collection = build_collection(args.chroma_path, args.embedding_model)
    before_count = collection.count()
    load_election_data(collection)
    after_count = collection.count()

    print(
        f"Indexed election data into '{CHROMA_COLLECTION_NAME}': "
        f"{before_count} -> {after_count} chunks."
    )


if __name__ == "__main__":
    main()
