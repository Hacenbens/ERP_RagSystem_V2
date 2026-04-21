"""
BPMNChunker — Business Process Model and Notation document chunker.

Strategy (in priority order):
  1. XML parse  — extract each task / gateway / event element as a chunk.
     Element text content + attributes are joined into a readable string.
  2. Tag-based  — regex-extract tags when xml.etree cannot parse the input.
  3. Recursive fallback — plain-text split for non-XML BPMN descriptions.

Each BPMN flow element (task, gateway, event, lane) becomes one chunk.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from src.domain.chunk import Chunk
from src.observability.structured_logger import get_logger
from src.infrastructure.workers.chunkers.base_chunker import BaseChunker

logger = get_logger(__name__)

# BPMN element local-names we care about
_BPMN_ELEMENTS = frozenset({
    "task", "userTask", "serviceTask", "sendTask", "receiveTask",
    "scriptTask", "manualTask", "callActivity", "subProcess",
    "exclusiveGateway", "inclusiveGateway", "parallelGateway",
    "eventBasedGateway", "complexGateway",
    "startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent",
    "boundaryEvent", "sequenceFlow", "lane", "participant",
})

# Fallback: match any XML-like tag
_TAG_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_:.-]*)[^>]*>([^<]*)</\1>", re.DOTALL)


def _local_name(tag: str) -> str:
    """Strip XML namespace prefix: {ns}localName → localName."""
    return tag.split("}")[-1] if "}" in tag else tag


def _element_to_text(elem: ET.Element) -> str:
    """Render a BPMN element as a human-readable string."""
    name = _local_name(elem.tag)
    attrs = {k.split("}")[-1]: v for k, v in elem.attrib.items()}
    label = attrs.get("name") or attrs.get("id") or name
    parts = [f"[{name}] {label}"]
    inner = (elem.text or "").strip()
    if inner:
        parts.append(inner)
    return " — ".join(parts)


class BPMNChunker(BaseChunker):
    """Chunk BPMN XML documents by flow element."""

    def chunk(self, text: str) -> list[Chunk]:
        """Return one chunk per BPMN flow element, falling back gracefully."""
        logger.debug("bpmn_chunker.start", text_length=len(text))

        if not text.strip():
            return []

        strings = self._try_xml_parse(text)
        if not strings:
            strings = self._try_tag_regex(text)
        if not strings:
            strings = self._recursive_split(text)

        result = [Chunk(text=c) for c in strings if c]
        logger.debug("bpmn_chunker.done", chunk_count=len(result))
        return result

    def _try_xml_parse(self, text: str) -> list[str]:
        """Parse XML and yield one string per relevant BPMN element."""
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []

        chunks: list[str] = []
        for elem in root.iter():
            if _local_name(elem.tag) in _BPMN_ELEMENTS:
                chunk_text = _element_to_text(elem).strip()
                if chunk_text:
                    chunks.append(chunk_text)
        return chunks

    def _try_tag_regex(self, text: str) -> list[str]:
        """Regex-based fallback for malformed XML."""
        return [
            f"[{m.group(1)}] {m.group(2).strip()}"
            for m in _TAG_RE.finditer(text)
            if m.group(2).strip()
        ]


__all__ = ["BPMNChunker"]
