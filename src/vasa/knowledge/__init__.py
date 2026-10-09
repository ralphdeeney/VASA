"""CPU knowledge processing primitives."""

from vasa.knowledge.embedding import IDENTITY, CPUEmbedder
from vasa.knowledge.processing import extract_document, process_text

__all__ = ["IDENTITY", "CPUEmbedder", "extract_document", "process_text"]
