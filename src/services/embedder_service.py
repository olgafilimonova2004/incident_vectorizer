import hashlib
import json
import math

import httpx

from src.common.config import EmbedderConfig
from src.common.errors import DependencyError


class EmbedderService:
    def __init__(self, config: EmbedderConfig):
        self.config = config
        headers = {}
        if config.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"
        self.client = httpx.Client(base_url=str(config.base_url).rstrip("/") + "/", headers=headers, timeout=config.timeout)

    @property
    def version(self) -> str:
        values = [str(self.config.base_url), self.config.model, self.config.dimensions, self.config.prefix]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self.config.batch_size):
            batch = texts[start:start + self.config.batch_size]
            response = self.client.post("embeddings", json={"model": self.config.model, "input": [self.config.prefix + text for text in batch]})
            response.raise_for_status()
            data = response.json()["data"]
            if len(data) != len(batch) or sorted(item["index"] for item in data) != list(range(len(batch))):
                raise DependencyError("Embedder вернул неверное количество или индексы векторов")
            for item in sorted(data, key=lambda item: item["index"]):
                vector = item["embedding"]
                if len(vector) != self.config.dimensions or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
                    raise DependencyError("Embedder вернул некорректный вектор")
                vectors.append(vector)
        return vectors

    def close(self) -> None:
        self.client.close()
