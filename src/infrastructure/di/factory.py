"""
DI Factory — Sprint 3 / Sprint 6 / Sprint 9
Wires all concrete implementations into the DIContainer.

Call `build_container()` once at app startup (e.g. in main.py lifespan).
The returned container has been validated — it will raise on missing bindings
before returning.
"""
from __future__ import annotations

import os

from src.domain.chunk import Chunk
from src.domain.chunk_strategy import ChunkStrategy
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore, MongoChunkStore
from src.infrastructure.rag.context_builder import ContextBuilder
from src.infrastructure.rag.embedding_providers import NgrokEmbeddingProvider, NoopEmbeddingProvider
from src.infrastructure.rag.reranker import IdentityReranker
from src.infrastructure.rag.vector_retriever import VectorRetriever
from src.infrastructure.storage.local_asset_storage import LocalAssetStorage
from src.infrastructure.workers.celery_job_dispatcher import CeleryJobDispatcher
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.workers.chunkers.chunker_factory import ChunkerFactory
from src.infrastructure.workers.dead_letter_repository import (
    InMemoryDeadLetterRepository,
    MongoDeadLetterRepository,
)
from src.infrastructure.workers.idempotency_store import (
    InMemoryIdempotencyStore,
    MongoIdempotencyStore,
)
from src.agents.hybrid_agent import HybridAgent
from src.agents.query_classifier_agent import QueryClassifierAgent
from src.agents.rag_agent import RAGAgent
from src.agents.sql_agent import SQLAgent
from src.infrastructure.erp.query_executor import QueryExecutor
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_validator import QueryValidator
from src.infrastructure.generation.gemini_llm_client import GeminiLLMClient
from src.infrastructure.generation.model_selector import ModelSelector
from src.infrastructure.generation.vllm_llm_client import vLLMLLMClient
from src.infrastructure.nlp.stub_classifier import StubClassifier
from src.observability.structured_logger import get_logger
from src.prompts.registry import PromptRegistry
from src.use_cases.auth_user import AuthUseCase
from src.use_cases.run_hybrid import RunHybridUseCase
from src.use_cases.run_rag import RunRAGUseCase
from src.use_cases.run_sql import RunSQLUseCase
from src.use_cases.route_query import RouteQueryUseCase
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase
from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase

logger = get_logger(__name__)


class _NullLLM(LLMPort):
    """No-op LLM placeholder — active only when no LLM provider is configured."""

    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        logger.warning("null_llm.complete.called — no LLM provider configured")
        return ""


def _build_model_selector() -> ModelSelector | _NullLLM:
    """Build a ModelSelector from available env-configured providers.

    Provider priority: Gemini (primary) → vLLM (fallback).
    Falls back to _NullLLM with a warning when no keys are present.
    Each call returns a fresh instance with its own circuit-breaker state.
    """
    providers: list[tuple[LLMPort, str]] = []

    if os.environ.get("GEMINI_API_KEY"):
        providers.append((GeminiLLMClient.from_env(), "gemini"))
        logger.info("factory.llm.gemini_enabled")

    if os.environ.get("VLLM_BASE_URL") and os.environ.get("VLLM_MODEL"):
        providers.append((vLLMLLMClient.from_env(), "vllm"))
        logger.info("factory.llm.vllm_enabled")

    if providers:
        return ModelSelector(providers=providers)

    logger.warning(
        "factory.llm.no_provider — set GEMINI_API_KEY or VLLM_BASE_URL+VLLM_MODEL "
        "to enable real LLM responses"
    )
    return _NullLLM()


def _select_embedder() -> EmbeddingPort:
    """Return NgrokEmbeddingProvider when NGROK_BASE_URL is set, else NoopEmbeddingProvider."""
    if os.environ.get("NGROK_BASE_URL"):
        logger.info("factory.embedder.ngrok_enabled", base_url=os.environ["NGROK_BASE_URL"])
        return NgrokEmbeddingProvider()
    logger.warning("factory.embedder.noop — set NGROK_BASE_URL to enable real embeddings")
    return NoopEmbeddingProvider()


def build_query_chain(container: DIContainer, prompts_dir: str | None = None) -> None:
    """Wire the hybrid query chain into *container*.

    Registers: query_classifier, vector_store, embedding_provider,
    vector_retriever, reranker, context_builder, prompt_registry,
    rag_agent, sql_agent, hybrid_agent, rag_use_case, hybrid_use_case,
    sql_use_case, route_query_use_case.

    Called by ``build_container()`` automatically.  Can also be called
    separately in tests to inject specific implementations.
    """
    _prompts_dir = prompts_dir or os.path.join(
        os.path.dirname(__file__), "..", "..", "prompts"
    )

    # --- PromptRegistry (built first — classifier depends on it) -----------
    prompt_registry = PromptRegistry(prompts_dir=_prompts_dir)
    container.register("prompt_registry", prompt_registry)

    # --- LLM (independent circuit breakers per use-site) -------------------
    agent_llm = _build_model_selector()       # RAGAgent + HybridAgent
    classifier_llm = _build_model_selector()  # QueryClassifierAgent — separate CB state

    # --- Classifier --------------------------------------------------------
    if isinstance(agent_llm, ModelSelector):
        classifier: QueryClassifierAgent | StubClassifier = QueryClassifierAgent(
            llm=classifier_llm, registry=prompt_registry
        )
        logger.info("factory.classifier.query_classifier_agent_enabled")
    else:
        classifier = StubClassifier()
        logger.warning("factory.classifier.stub — LLM not configured, using StubClassifier")
    container.register("query_classifier", classifier)

    # --- RAG retrieval chain -----------------------------------------------
    vector_store = InMemoryVectorStore()
    embedder = _select_embedder()
    retriever = VectorRetriever(store=vector_store, embedder=embedder)
    reranker = IdentityReranker()
    context_builder = ContextBuilder()

    container.register("vector_store", vector_store)
    container.register("embedding_provider", embedder)
    container.register("vector_retriever", retriever)
    container.register("reranker", reranker)
    container.register("context_builder", context_builder)

    # --- Agents ------------------------------------------------------------
    rag_agent = RAGAgent(
        retriever=retriever,
        reranker=reranker,
        context_builder=context_builder,
        llm=agent_llm,
        registry=prompt_registry,
    )
    sql_agent = SQLAgent(
        generator=QueryGenerator(),
        validator=QueryValidator(),
        executor=QueryExecutor(),
    )
    hybrid_agent = HybridAgent(
        rag_agent=rag_agent,
        sql_agent=sql_agent,
        llm=agent_llm,
        registry=prompt_registry,
    )

    container.register("rag_agent", rag_agent)
    container.register("sql_agent", sql_agent)
    container.register("hybrid_agent", hybrid_agent)

    # --- Use cases ---------------------------------------------------------
    rag_uc = RunRAGUseCase(rag_agent=rag_agent)
    sql_uc = RunSQLUseCase(sql_agent=sql_agent)
    hybrid_uc = RunHybridUseCase(hybrid_agent=hybrid_agent)
    route_uc = RouteQueryUseCase(
        classifier=classifier,
        rag_uc=rag_uc,
        sql_uc=sql_uc,
        hybrid_uc=hybrid_uc,
    )

    container.register("rag_use_case", rag_uc)
    container.register("sql_use_case", sql_uc)
    container.register("hybrid_use_case", hybrid_uc)
    container.register("route_query_use_case", route_uc)


def build_container() -> DIContainer:
    """Create and validate the DI container with all production bindings.

    Raises MissingBindingError at startup if a required port has no implementation.
    """
    container = DIContainer()

    # --- Auth -----------------------------------------------------------
    jwt_handler = JWTHandler()
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # --- Query chain (Sprint 7) ----------------------------------------
    build_query_chain(container)

    # --- Ingestion ports (Sprint 7 Task 20/21) -------------------------
    asset_storage_path = os.environ.get("ASSET_STORAGE_PATH", "/tmp/erp_rag_assets")
    container.register("asset_storage", LocalAssetStorage(base_path=asset_storage_path))
    container.register("job_dispatcher", CeleryJobDispatcher())

    # Validate before returning — app must not start with unbound ports
    container.validate()
    return container


def build_worker_container() -> DIContainer:
    """Create and validate a DI container for the Celery worker process.

    Wires all worker-specific dependencies (dead-letter repo, idempotency
    store, ingest use case, embed use case) in addition to the shared auth
    bindings.

    Raises MissingBindingError at startup if a required worker port is unbound.

    The choice between in-memory and MongoDB implementations is driven by the
    ``MONGODB_URI`` environment variable — present in production, absent in CI.
    """
    container = DIContainer()

    # --- Auth (shared with API process) ----------------------------------
    jwt_handler = JWTHandler()
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # --- Worker dependencies ---------------------------------------------
    mongo_uri = os.environ.get("MONGODB_URI", "")
    asset_storage_path = os.environ.get("ASSET_STORAGE_PATH", "/tmp/erp_rag_assets")

    dead_letter_repo: InMemoryDeadLetterRepository | MongoDeadLetterRepository
    idempotency_store: InMemoryIdempotencyStore | MongoIdempotencyStore
    chunk_store: InMemoryChunkStore | MongoChunkStore

    if mongo_uri:
        import pymongo  # type: ignore
        client = pymongo.MongoClient(mongo_uri)
        dead_letter_repo = MongoDeadLetterRepository(
            client["erp_rag"]["failed_tasks"]
        )
        idempotency_store = MongoIdempotencyStore(
            client["erp_rag"]["processed_assets"]
        )
        chunk_store = MongoChunkStore(client["erp_rag"]["chunks"])
        from src.infrastructure.vector_store.mongo_vector_store import MongoVectorStore
        vector_store: InMemoryVectorStore | MongoVectorStore = MongoVectorStore(
            client["erp_rag"]["embedded_assets"]
        )
    else:
        dead_letter_repo = InMemoryDeadLetterRepository()
        idempotency_store = InMemoryIdempotencyStore()
        chunk_store = InMemoryChunkStore()
        vector_store = InMemoryVectorStore()

    asset_storage = LocalAssetStorage(base_path=asset_storage_path)
    embedding_port = _select_embedder()

    _chunker_factory = ChunkerFactory()

    def _chunker(content: bytes, chunk_strategy: str) -> list[Chunk]:
        strategy = ChunkStrategy(chunk_strategy)
        chunker = _chunker_factory.get_chunker(strategy)
        text = content.decode("utf-8", errors="replace")
        chunks = chunker.chunk(text)
        return chunks if chunks else [Chunk(text=text)]

    ingest_use_case = IngestAssetUseCase(
        idempotency_store=idempotency_store,
        asset_storage=asset_storage,
        chunk_store=chunk_store,
        chunker=_chunker,
    )

    embed_use_case = EmbedAssetUseCase(
        vector_store=vector_store,
        chunk_store=chunk_store,
        embedding_port=embedding_port,
    )

    container.register("dead_letter_repository", dead_letter_repo)
    container.register("idempotency_store", idempotency_store)
    container.register("chunk_store", chunk_store)
    container.register("asset_storage", asset_storage)
    container.register("ingest_use_case", ingest_use_case)
    container.register("vector_store", vector_store)
    container.register("embed_use_case", embed_use_case)

    # Validate worker ports before returning
    container.validate_worker()
    return container


# ---------------------------------------------------------------------------
# Worker container singleton — one instance per worker process
# ---------------------------------------------------------------------------

_worker_container: DIContainer | None = None


def get_worker_container() -> DIContainer:
    """Return the worker DI container, building it on first call.

    Lazy singleton — safe to import at module level in task files because the
    container is only constructed when the first task runs, not at import time.
    """
    global _worker_container
    if _worker_container is None:
        _worker_container = build_worker_container()
    return _worker_container


__all__ = ["build_container", "build_worker_container", "get_worker_container"]
