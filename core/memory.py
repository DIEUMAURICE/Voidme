import chromadb
from chromadb.utils import embedding_functions
import os
import json
import uuid
from datetime import datetime

class MemoryManager:
    def __init__(self, persist_dir="./common/memory_db"):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_dir)
        # Utiliser un embedding function par défaut (all-MiniLM-L6-v2)
        try:
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
        except Exception as e:
            print(f"Warning: SentenceTransformer not available, using default embedding. {e}")
            self.embedding_fn = None  # ChromaDB utilisera l'embedding par défaut
        
        self.collection = self.client.get_or_create_collection(
            name="memories",
            embedding_function=self.embedding_fn
        )

    def add_memory(self, text, metadata=None):
        """Ajoute un souvenir avec des métadonnées (timestamp, type, source)"""
        if metadata is None:
            metadata = {}
        metadata["timestamp"] = datetime.now().isoformat()
        doc_id = str(uuid.uuid4())
        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id]
        )
        return doc_id

    def retrieve(self, query, top_k=5, filter_metadata=None):
        """Recherche les souvenirs les plus pertinents"""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                where=filter_metadata
            )
            memories = []
            if results and results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    memories.append({
                        'text': doc,
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {}
                    })
            return memories
        except Exception as e:
            print(f"Memory retrieval error: {e}")
            return []

    def get_all(self):
        """Récupère tous les souvenirs (pour export)"""
        return self.collection.get()