"""Local sentence-transformers embeddings behind the LangChain Embeddings interface."""
from __future__ import annotations

from langchain_core.embeddings import Embeddings


class LocalEmbeddings(Embeddings):
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._m = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._m.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
