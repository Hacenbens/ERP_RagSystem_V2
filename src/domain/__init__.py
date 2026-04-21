"""Domain layer — canonical enums and business-rule constants.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8
"""

from src.domain.user_role import UserRole
from src.domain.query_intent import QueryIntent
from src.domain.chunk_strategy import ChunkStrategy
from src.domain.erp_module import ErpModule
from src.domain.chunk import Chunk
from src.domain.table_element import TableElement

__all__ = [
    "UserRole",
    "QueryIntent",
    "ChunkStrategy",
    "ErpModule",
    "Chunk",
    "TableElement",
]
