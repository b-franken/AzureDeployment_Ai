from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx
import numpy as np
import structlog

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = structlog.get_logger(__name__)


class TfidfVectorizerProtocol(Protocol):
    """Protocol for sklearn TfidfVectorizer to avoid import errors.

    This protocol defines the minimal interface needed for TF-IDF vectorization.
    It's designed to be compatible with sklearn's TfidfVectorizer while allowing
    for type safety without requiring sklearn as a hard dependency.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with flexible keyword arguments to match sklearn interface."""
        ...

    def fit_transform(self, texts: Sequence[str]) -> Any:
        """Fit and transform texts to TF-IDF matrix."""
        ...


def _get_tfidf_vectorizer() -> type[TfidfVectorizerProtocol] | None:
    """Get TfidfVectorizer with proper error handling and logging.

    Returns:
        TfidfVectorizer class if sklearn is available, None otherwise.
        The return type is cast to match our protocol interface.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        logger.debug(
            "sklearn_tfidf_vectorizer_loaded",
            vectorizer_class=TfidfVectorizer.__name__,
            module=TfidfVectorizer.__module__,
        )
        # Type cast to our protocol - sklearn's TfidfVectorizer implements our protocol
        # but with additional parameters that don't break compatibility
        return cast(type[TfidfVectorizerProtocol], TfidfVectorizer)

    except ImportError as e:
        logger.warning(
            "sklearn_not_available_fallback_mode",
            error=str(e),
            fallback_method="hash_based_embeddings",
        )
        return None
    except Exception as e:
        logger.error(
            "unexpected_error_loading_sklearn",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


class EmbeddingClient:
    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        raise NotImplementedError


def _chunks(xs: Sequence[str], n: int) -> Iterable[Sequence[str]]:
    m = max(1, int(n))
    for i in range(0, len(xs), m):
        yield xs[i : i + m]


class _AADTokenProvider:
    def __init__(self, scope: str = "https://cognitiveservices.azure.com/.default") -> None:
        from azure.identity import DefaultAzureCredential

        self._cred = DefaultAzureCredential()
        self._scope = scope
        self._token: str | None = None
        self._exp: float = 0.0

    def get(self) -> str:
        now = time.time()
        if not self._token or now > self._exp - 60:
            t = self._cred.get_token(self._scope)
            self._token = t.token
            self._exp = float(t.expires_on)
        return self._token or ""


class AzureOpenAIClient(EmbeddingClient):
    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        dimensions: int | None = None,
        auth: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        ep_env = os.getenv("AZURE_OPENAI_ENDPOINT") or ""
        ep_base = endpoint if endpoint is not None else ep_env
        self.endpoint: str = (ep_base or "").rstrip("/")

        dep_env = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT") or ""
        self.deployment: str = deployment if deployment is not None else dep_env

        key_env = os.getenv("AZURE_OPENAI_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env

        ver_env = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-10-21"
        self.api_version: str = api_version if api_version is not None else ver_env

        self.dimensions: int | None = int(dimensions) if dimensions is not None else None
        self.timeout: float = float(timeout)

        auth_env = os.getenv("AZURE_OPENAI_AUTH") or "key"
        self.auth: str = (auth if auth is not None else auth_env).lower()
        self._aad: _AADTokenProvider | None = (
            _AADTokenProvider() if self.auth == "aad" or not self.key else None
        )

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings"
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"input": list(chunk)}
                    if self.dimensions is not None:
                        payload["dimensions"] = int(self.dimensions)
                    params = {"api-version": self.api_version}
                    headers: dict[str, str] = {"Content-Type": "application/json"}
                    if self._aad:
                        headers["Authorization"] = f"Bearer {self._aad.get()}"
                    else:
                        headers["api-key"] = self.key
                    r = s.post(url, headers=headers, params=params, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"azure embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class OpenAIClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "text-embedding-3-large",
        api_key: str | None = None,
        base_url: str | None = None,
        dimensions: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("OPENAI_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        base_env = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        base = base_url if base_url is not None else base_env
        self.base_url: str = (base or "https://api.openai.com/v1").rstrip("/")
        self.dimensions: int | None = int(dimensions) if dimensions is not None else None
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    if self.dimensions is not None:
                        payload["dimensions"] = int(self.dimensions)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"openai embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class CohereClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "embed-v4.0",
        api_key: str | None = None,
        output_dimension: int | None = None,
        input_type: str | None = "search_document",
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("COHERE_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.output_dimension: int | None = (
            int(output_dimension) if output_dimension is not None else None
        )
        self.input_type: str | None = input_type
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.cohere.com/v2/embed"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "texts": list(chunk)}
                    if self.input_type:
                        payload["input_type"] = self.input_type
                    if self.output_dimension is not None:
                        payload["output_dimension"] = int(self.output_dimension)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    emb_container = data.get("embeddings", {})
                    vecs: object
                    if isinstance(emb_container, dict):
                        vecs = emb_container.get("float") or emb_container.get("embeddings")
                    else:
                        vecs = emb_container
                    if vecs is None:
                        raise RuntimeError("invalid embeddings response from Cohere")
                    out.extend(cast("list[list[float]]", vecs))
        except Exception as e:
            raise RuntimeError(f"cohere embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class VoyageClient(EmbeddingClient):
    def __init__(
        self,
        model: str = "voyage-3-large",
        api_key: str | None = None,
        output_dimension: int | None = None,
        input_type: str | None = "document",
        timeout: float = 60.0,
    ) -> None:
        self.model: str = model
        key_env = os.getenv("VOYAGE_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.output_dimension: int | None = (
            int(output_dimension) if output_dimension is not None else None
        )
        self.input_type: str | None = input_type
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.voyageai.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    if self.input_type:
                        payload["input_type"] = self.input_type
                    if self.output_dimension is not None:
                        payload["output_dimension"] = int(self.output_dimension)
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    if "data" in data and "embeddings" in data["data"][0]:
                        out.extend(cast("list[list[float]]", data["data"][0]["embeddings"]))
                    else:
                        out.extend(cast("list[list[float]]", data["embeddings"]))
        except Exception as e:
            raise RuntimeError(f"voyage embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class MistralClient(EmbeddingClient):
    def __init__(
        self, model: str = "mistral-embed", api_key: str | None = None, timeout: float = 60.0
    ) -> None:
        self.model: str = model
        key_env = os.getenv("MISTRAL_API_KEY") or ""
        self.key: str = api_key if api_key is not None else key_env
        self.timeout: float = float(timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        url = "https://api.mistral.ai/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as s:
                for chunk in _chunks(texts, batch_size):
                    payload: dict[str, object] = {"model": self.model, "input": list(chunk)}
                    r = s.post(url, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    out.extend([cast("list[float]", d["embedding"]) for d in data["data"]])
        except Exception as e:
            raise RuntimeError(f"mistral embeddings request failed: {e}") from e
        return np.asarray(out, dtype=np.float32)


class LocalEmbeddingClient(EmbeddingClient):
    """Lightweight local embedding client using TF-IDF or hash-based embeddings.

    This client provides a fallback mechanism for embedding generation when
    external APIs are unavailable or for lightweight local processing.
    """

    def __init__(self, model_name: str = "tfidf") -> None:
        self.model_name = model_name
        self._vectorizer: TfidfVectorizerProtocol | None = None
        self._fallback_dim = 384  # Standard embedding dimension
        self._initialization_attempted = False

        logger.debug(
            "local_embedding_client_initialized",
            model_name=model_name,
            fallback_dimension=self._fallback_dim,
        )

    def _ensure_vectorizer(self) -> None:
        """Ensure vectorizer is initialized with comprehensive error handling."""
        if self._vectorizer is not None or self._initialization_attempted:
            return

        self._initialization_attempted = True
        vectorizer_class = _get_tfidf_vectorizer()

        if vectorizer_class is None:
            logger.info(
                "sklearn_unavailable_using_hash_fallback",
                model_name=self.model_name,
                fallback_method="hash_based_embeddings",
            )
            return

        try:
            # Configure TF-IDF vectorizer with sensible defaults for embeddings
            vectorizer_config = {
                "max_features": self._fallback_dim,
                "stop_words": "english",
                "lowercase": True,
                "ngram_range": (1, 2),
                "min_df": 1,
                "max_df": 0.95,
                "sublinear_tf": True,  # Use sublinear TF scaling
                "norm": "l2",  # L2 normalization
            }

            self._vectorizer = vectorizer_class(**vectorizer_config)

            logger.info(
                "tfidf_vectorizer_initialized_successfully",
                model_name=self.model_name,
                config=vectorizer_config,
            )

        except Exception as e:
            logger.error(
                "failed_to_initialize_tfidf_vectorizer",
                error=str(e),
                error_type=type(e).__name__,
                model_name=self.model_name,
                fallback_method="hash_based_embeddings",
            )
            self._vectorizer = None

    def _simple_hash_embedding(self, text: str, dim: int = 384) -> list[float]:
        """Ultra-lightweight hash-based embedding as fallback.

        This method generates embeddings using a combination of hash functions
        and positional weighting to create a reasonable approximation of semantic
        similarity for basic text classification tasks.

        Args:
            text: Input text to embed
            dim: Embedding dimension

        Returns:
            Normalized embedding vector as list of floats
        """
        import hashlib

        if not text or not text.strip():
            logger.debug("empty_text_provided_for_hash_embedding")
            return [0.0] * dim

        try:
            # Create multiple hash features with different strategies
            features = [0.0] * dim
            text_cleaned = text.lower().strip()
            words = text_cleaned.split()

            if not words:
                logger.debug("no_words_found_after_preprocessing", text_length=len(text))
                return [0.0] * dim

            # Multiple hash strategies for robustness
            def word_hash(word: str, seed: int) -> str:
                return f"{word}_{seed}"

            def bigram_hash(word: str, seed: int) -> str:
                try:
                    next_word = words[(words.index(word) + 1) % len(words)]
                    return f"{word}_{next_word}_{seed}"
                except (ValueError, IndexError):
                    return f"{word}_solo_{seed}"

            def position_hash(word: str, seed: int) -> str:
                try:
                    pos = words.index(word) % 10
                    return f"{word}_{pos}_{seed}"
                except ValueError:
                    return f"{word}_nopos_{seed}"

            hash_strategies = [
                ("word_hash", word_hash),
                ("bigram_hash", bigram_hash),
                ("position_hash", position_hash),
            ]

            for i, word in enumerate(words[:50]):  # Limit to first 50 words for performance
                for strategy_name, hash_func in hash_strategies:
                    for seed in range(2):  # Reduced seeds for performance
                        try:
                            hash_input = hash_func(word, seed)
                            hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
                            idx = hash_val % dim

                            # Position-based weighting with decay
                            weight = 1.0 / (i + 1) ** 0.5
                            features[idx] += weight

                        except (ValueError, IndexError) as e:
                            logger.debug(
                                "hash_computation_error_skipped",
                                error=str(e),
                                word=word,
                                strategy=strategy_name,
                            )
                            continue

            # L2 normalization for consistency with TF-IDF
            norm = sum(f * f for f in features) ** 0.5
            if norm > 0:
                features = [f / norm for f in features]
            else:
                logger.debug("zero_norm_vector_using_uniform_fallback", text_length=len(text))
                # Uniform fallback for zero vectors
                uniform_value = 1.0 / (dim**0.5)
                features = [uniform_value] * dim

            return features

        except Exception as e:
            logger.error(
                "hash_embedding_generation_failed",
                error=str(e),
                error_type=type(e).__name__,
                text_length=len(text),
                dimension=dim,
            )
            # Return zero vector on failure
            return [0.0] * dim

    def encode(self, texts: Sequence[str], batch_size: int = 256) -> NDArray[np.float32]:
        """Encode texts to embeddings using TF-IDF or hash-based fallback.

        Args:
            texts: Sequence of texts to embed
            batch_size: Batch size (ignored for local processing)

        Returns:
            NumPy array of embeddings with shape (len(texts), embedding_dim)
        """
        if not texts:
            logger.debug("empty_texts_provided_returning_empty_array")
            return np.empty((0, 0), dtype=np.float32)

        start_time = time.time()
        text_count = len(texts)

        logger.info(
            "local_embedding_encoding_started",
            text_count=text_count,
            model_name=self.model_name,
            batch_size=batch_size,
        )

        # Ensure vectorizer is initialized
        self._ensure_vectorizer()

        # Try TF-IDF if sklearn is available
        if self._vectorizer is not None:
            try:
                logger.debug("using_tfidf_vectorizer_for_encoding")

                # Fit and transform texts using TF-IDF
                tfidf_matrix = self._vectorizer.fit_transform(texts)

                # Handle scipy sparse matrix or numpy array
                if hasattr(tfidf_matrix, "toarray"):
                    # Cast scipy sparse matrix result
                    sparse_array = tfidf_matrix.toarray()
                    embeddings = sparse_array.astype(np.float32)
                else:
                    embeddings = np.asarray(tfidf_matrix, dtype=np.float32)

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    "tfidf_encoding_completed_successfully",
                    text_count=text_count,
                    embedding_shape=embeddings.shape,
                    duration_ms=duration_ms,
                    method="sklearn_tfidf",
                )

                return cast("NDArray[np.float32]", embeddings)

            except Exception as e:
                logger.warning(
                    "tfidf_encoding_failed_using_hash_fallback",
                    error=str(e),
                    error_type=type(e).__name__,
                    text_count=text_count,
                    fallback_method="hash_based_embeddings",
                )

        # Ultra-lightweight fallback: hash-based embeddings
        logger.info(
            "using_hash_based_embedding_fallback",
            text_count=text_count,
            embedding_dimension=self._fallback_dim,
        )

        try:
            embeddings = []
            failed_count = 0

            for i, text in enumerate(texts):
                try:
                    embedding = self._simple_hash_embedding(text, self._fallback_dim)
                    embeddings.append(embedding)
                except Exception as e:
                    logger.debug(
                        "individual_text_embedding_failed",
                        text_index=i,
                        error=str(e),
                        text_preview=text[:50] if text else "empty",
                    )
                    failed_count += 1
                    # Use zero vector for failed embeddings
                    embeddings.append([0.0] * self._fallback_dim)

            result = np.asarray(embeddings, dtype=np.float32)
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "hash_based_encoding_completed",
                text_count=text_count,
                failed_count=failed_count,
                success_rate=1.0 - (failed_count / text_count) if text_count > 0 else 1.0,
                embedding_shape=result.shape,
                duration_ms=duration_ms,
                method="hash_based",
            )

            return result

        except Exception as e:
            logger.error(
                "hash_based_encoding_completely_failed",
                error=str(e),
                error_type=type(e).__name__,
                text_count=text_count,
            )
            # Return zero matrix as ultimate fallback
            fallback_shape = (text_count, self._fallback_dim)
            logger.warning(
                "returning_zero_matrix_as_ultimate_fallback",
                shape=fallback_shape,
            )
            return np.zeros(fallback_shape, dtype=np.float32)


def get_embedding_client(provider: str | None = None) -> EmbeddingClient:
    """Get an embedding client based on the specified provider.

    Args:
        provider: Embedding provider name. If None, uses EMBEDDINGS_PROVIDER env var
                 or defaults to 'azure'.

    Returns:
        Configured embedding client instance

    Raises:
        ValueError: If provider is unknown
        RuntimeError: If client initialization fails
    """
    base = provider if provider is not None else (os.getenv("EMBEDDINGS_PROVIDER") or "azure")
    p = base.lower().strip()

    # Parse optional dimensions
    dims_str = os.getenv("EMBEDDINGS_DIMENSIONS")
    dims = None
    if dims_str:
        try:
            dims = int(dims_str)
            if dims <= 0:
                logger.warning(
                    "invalid_embedding_dimensions_ignoring",
                    dimensions_str=dims_str,
                    parsed_value=dims,
                )
                dims = None
        except ValueError as e:
            logger.warning(
                "failed_to_parse_embedding_dimensions",
                dimensions_str=dims_str,
                error=str(e),
            )
            dims = None

    logger.info(
        "initializing_embedding_client",
        provider=p,
        dimensions=dims,
        env_provider=os.getenv("EMBEDDINGS_PROVIDER"),
    )

    try:
        client: EmbeddingClient
        if p == "azure":
            client = AzureOpenAIClient(dimensions=dims)
        elif p == "openai":
            client = OpenAIClient(dimensions=dims)
        elif p == "cohere":
            client = CohereClient(output_dimension=dims)
        elif p == "voyage":
            client = VoyageClient(output_dimension=dims)
        elif p == "mistral":
            client = MistralClient()
        elif p == "local":
            model_name = os.getenv("LOCAL_EMBEDDING_MODEL", "tfidf")
            client = LocalEmbeddingClient(model_name)
        else:
            available_providers = ["azure", "openai", "cohere", "voyage", "mistral", "local"]
            logger.error(
                "unknown_embeddings_provider",
                requested_provider=provider,
                available_providers=available_providers,
            )
            raise ValueError(f"Unknown embeddings provider: {provider}")

        logger.info(
            "embedding_client_initialized_successfully",
            provider=p,
            client_type=type(client).__name__,
            dimensions=dims,
        )

        return client

    except Exception as e:
        logger.error(
            "failed_to_initialize_embedding_client",
            provider=p,
            error=str(e),
            error_type=type(e).__name__,
        )
        if isinstance(e, ValueError):
            raise
        raise RuntimeError(f"Failed to initialize {p} embedding client: {e}") from e
