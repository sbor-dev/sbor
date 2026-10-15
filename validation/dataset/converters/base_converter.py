from abc import ABC, abstractmethod
from collections.abc import Iterable

from validation.dataset.common import ConvertedItem


class Converter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @abstractmethod
    def convert(self) -> Iterable[ConvertedItem]: ...
