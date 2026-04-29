import os
import chromadb
from chromadb.utils import embedding_functions

chroma_client = chromadb.PersistentClient(path="./chroma_db")
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_or_create_collection(name="election_data", embedding_function=sentence_transformer_ef)

def chunk_text(text, size=400, overlap=80):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i:i+size]))
        i += size - overlap
    return chunks

def load_documents():
    data_dir = "election_data"
    documents, metadata, ids = [], [], []
    for filename in os.listdir(data_dir):
        if filename.endswith(".txt"):
            with open(os.path.join(data_dir, filename), 'r') as f:
                text = f.read()
            chunks = chunk_text(text)
            for idx, chunk in enumerate(chunks):
                documents.append(chunk)
                metadata.append({"source": filename})
                ids.append(f"{filename}_{idx}")
            print(f"Loaded {filename}: {len(chunks)} chunks")
    collection.add(documents=documents, metadatas=metadata, ids=ids)
    print(f"Done — {len(documents)} total chunks indexed.")

if __name__ == "__main__":
    load_documents()
