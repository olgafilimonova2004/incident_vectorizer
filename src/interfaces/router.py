from abc import ABC, abstractmethod
from enum import Enum

from fastapi import APIRouter


class BaseRouter(ABC):
    prefix = "/api/v1"
    tags: list[str | Enum] = ["incidents"]

    @property
    @abstractmethod
    def router(self) -> APIRouter:
        raise NotImplementedError
