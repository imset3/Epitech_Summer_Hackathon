import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt includes python-dotenv
    load_dotenv = None

from media_compare.search import fetch_trending_news, extract_trending_keywords_info
from media_compare.fetcher import fetch_articles_from_apis
from media_compare.clustering import cluster_articles
from media_compare.llm import analyze_cluster
from media_compare.confidence import recap_confidence
from media_compare.sources import load_sources

app = FastAPI(title="News Search & Compare API")

# ── In-memory session config (overrides env vars when set from UI) ──────────
# NOTE: _session_config is initialized AFTER load_dotenv below so .env values
# are available when _build_initial_session_config() reads os.environ.
def _build_initial_session_config() -> dict:
    provider_from_env = os.environ.get("LLM_PROVIDER", "")
    if provider_from_env not in {"openai", "gemini", "nim", "local", "dry-run"}:
        provider_from_env = None
    _model_env_map = {
        "openai": "OPENAI_MODEL",
        "gemini": "GEMINI_MODEL",
        "nim":    "NVIDIA_NIM_MODEL",
        "local":  "LOCAL_LLM_MODEL",
    }
    model_from_env = os.environ.get(_model_env_map.get(provider_from_env, ""), "") if provider_from_env else None
    return {
        "provider": provider_from_env or None,
        "api_key":  None,
        "model":    model_from_env or None,
    }

VALID_PROVIDERS = {"openai", "gemini", "nim", "local", "dry-run"}

MODEL_ENV_BY_PROVIDER = {
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "nim": "NVIDIA_NIM_MODEL",
    "local": "LOCAL_LLM_MODEL",
}

DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "nim": "meta/llama-3.1-8b-instruct",
    "local": "gemma4:e4b",
    "dry-run": "",
}

KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "nim": "NVIDIA_NIM_API_KEY",
}

# Setup paths
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config" / "sources.json"
ENV_PATH = BASE_DIR / ".env"
IMAGE_PROXY_MAX_BYTES = 5_000_000
IMAGE_PROXY_USER_AGENT = "media-compare-image-proxy/1.0"

if load_dotenv:
    load_dotenv(ENV_PATH)

# Initialize session config AFTER load_dotenv so .env values are visible in os.environ
_session_config: dict = _build_initial_session_config()

# Create static folder if it doesn't exist
STATIC_DIR.mkdir(exist_ok=True)


def _default_provider_from_env() -> str:
    provider = os.environ.get("LLM_PROVIDER")
    if provider in VALID_PROVIDERS:
        return provider
    for candidate, key_env in KEY_ENV_BY_PROVIDER.items():
        if os.environ.get(key_env):
            return candidate
    if os.environ.get("LOCAL_LLM_MODEL") or os.environ.get("LOCAL_LLM_BASE_URL"):
        return "local"
    return "dry-run"


def _format_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@+=,\-]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_env_values(values: dict[str, str]) -> None:
    """Update or create project .env values while preserving unrelated lines."""
    existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = dict(values)
    output_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        key_part = stripped[7:] if stripped.startswith("export ") else stripped
        key = key_part.split("=", 1)[0].strip() if "=" in key_part else ""
        if key in remaining:
            output_lines.append(f"{key}={_format_env_value(remaining.pop(key))}")
        else:
            output_lines.append(line)

    if output_lines and output_lines[-1].strip():
        output_lines.append("")
    for key, value in remaining.items():
        output_lines.append(f"{key}={_format_env_value(value)}")

    ENV_PATH.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def _persist_config_to_env(provider: str, api_key: str, model: str) -> None:
    values = {"LLM_PROVIDER": provider}
    key_env = KEY_ENV_BY_PROVIDER.get(provider)
    model_env = MODEL_ENV_BY_PROVIDER.get(provider)

    if api_key and key_env:
        values[key_env] = api_key
    if model and model_env:
        values[model_env] = model

    _write_env_values(values)


def _resolve_llm_config() -> tuple[str, str | None, str | None]:
    """Resolve the active provider without mixing model names across providers."""
    provider = _session_config.get("provider") or _default_provider_from_env()

    model = _session_config.get("model")
    if not model:
        model_env = MODEL_ENV_BY_PROVIDER.get(provider)
        model = os.environ.get(model_env) if model_env else None
    model = _model_for_provider(provider, model)

    local_base_url = os.environ.get("LOCAL_LLM_BASE_URL")
    return provider, model, local_base_url


def _model_matches_provider(provider: str, model: str | None) -> bool:
    if not model:
        return True
    if provider == "dry-run":
        return model == ""
    if provider == "openai":
        return model == "gpt-4o-mini"
    if provider == "gemini":
        return model.startswith("gemini-")
    if provider == "nim":
        return "/" in model or model.startswith("nvidia-")
    if provider == "local":
        return not model.startswith("gpt-") and not model.startswith("gemini-") and "/" not in model
    return True


def _model_for_provider(provider: str, model: str | None) -> str | None:
    if _model_matches_provider(provider, model):
        return model or DEFAULT_MODEL_BY_PROVIDER.get(provider) or None
    return DEFAULT_MODEL_BY_PROVIDER.get(provider) or None


def _local_llm_status(model: str | None = None, local_base_url: str | None = None) -> dict:
    selected_model = model or os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
    selected_base_url = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
    tags_url = f"{selected_base_url}/api/tags"
    try:
        request = urllib.request.Request(tags_url, headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = response.read().decode("utf-8", errors="replace")
        return {
            "connected": True,
            "base_url": selected_base_url,
            "model": selected_model,
            "message": "Local Ollama server is reachable.",
            "raw": payload[:500],
        }
    except Exception as exc:
        return {
            "connected": False,
            "base_url": selected_base_url,
            "model": selected_model,
            "message": f"Local Ollama server is not reachable: {exc}",
        }


def _keys_present() -> dict[str, bool]:
    return {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "nim": bool(os.environ.get("NVIDIA_NIM_API_KEY")),
        "local": True,
    }


def _client_is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _ensure_config_write_allowed(request: Request) -> None:
    token = os.environ.get("CONFIG_WRITE_TOKEN")
    if token:
        supplied = request.headers.get("X-Config-Token", "")
        if supplied != token:
            raise HTTPException(status_code=403, detail="Invalid or missing config write token.")
        return

    if not _client_is_local(request):
        raise HTTPException(
            status_code=403,
            detail="Writing .env from the web UI is allowed only from localhost unless CONFIG_WRITE_TOKEN is set.",
        )


def _analyze_cluster_or_502(cluster, provider: str, model: str | None, local_base_url: str | None):
    try:
        return analyze_cluster(
            cluster,
            provider=provider,
            model=model,
            local_base_url=local_base_url,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM analysis failed for provider '{provider}': {exc}",
        ) from exc


def _cluster_to_api_payload(cluster, analysis: dict, confidence: dict) -> dict:
    return {
        "cluster_id": cluster.cluster_id,
        "score": cluster.score,
        "avg_similarity": cluster.avg_similarity,
        "avg_best_similarity": cluster.avg_best_similarity,
        "similarity_coverage": cluster.similarity_coverage,
        "guardrail_score": cluster.guardrail_score,
        "guardrail_notes": cluster.guardrail_notes,
        "trust_status": cluster.trust_status,
        "trust_distribution": cluster.trust_distribution,
        "source_count": cluster.source_count,
        "articles": [
            {
                "article_id": a.article_id,
                "title": a.title,
                "url": a.metadata.get("url", ""),
                "publisher": a.metadata.get("publisher", a.metadata.get("source", a.source.name)),
                "date": a.metadata.get("date", ""),
                "bias": a.source.bias.lower(),
                "trust": a.source.trust,
                "reach": a.source.reach,
                "image_url": a.image_url,
            }
            for a in cluster.articles
        ],
        "analysis": analysis,
        "confidence": confidence,
    }


@app.get("/api/search")
async def search_and_analyze(
    q: str = Query(..., description="Search query for news stories"),
    limit: int = Query(12, description="Number of candidate articles to retrieve per API and query variant"),
    variants: int = Query(5, ge=1, le=8, description="Number of expanded search query variants to try"),
    max_articles: int = Query(60, ge=5, le=120, description="Maximum unique article URLs to scrape before clustering"),
    analysis_limit: int = Query(3, ge=1, le=10, description="Maximum story clusters to analyze with the selected LLM"),
    fetch_timeout: int = Query(12, ge=5, le=30, description="Seconds to wait for each article page fetch")
):
    print(f"Received search query: '{q}' (limit: {limit})")
    provider, model, local_base_url = _resolve_llm_config()
    if provider == "local":
        local_status = _local_llm_status(model=model, local_base_url=local_base_url)
        if not local_status["connected"]:
            raise HTTPException(status_code=502, detail=local_status["message"])
    
    # 1. Search and scrape news articles using the same API pipeline as the CLI.
    sources = load_sources(CONFIG_PATH)
    articles, fetch_errors = fetch_articles_from_apis(
        q,
        sources,
        limit_per_api=limit,
        timeout=fetch_timeout,
        extractor="auto",
        config_path=CONFIG_PATH,
        query_variants=variants,
        max_articles=max_articles,
        llm_provider=provider,
        llm_model=model,
        local_base_url=local_base_url,
    )
    if not articles:
        return {"query": q, "provider": None, "model": None, "clusters": [], "warnings": fetch_errors}
        
    # 2. Cluster articles using text similarity
    clusters = cluster_articles(articles, threshold=0.22)
    
    # Analyze a bounded number of clusters so broad article collection does not
    # leave the web UI waiting on many slow LLM calls.
    top_clusters = clusters[:analysis_limit]
    
    print(f"Running clustering and synthesis with provider: {provider}")

    # 3. For paid providers (openai/nim/gemini), translate only top-cluster articles
    #    now — not all 60 scraped articles — to minimise API call cost.
    if provider not in ("local", "dry-run"):
        from media_compare.translator import translate_to_english
        articles_to_translate = {
            article.article_id
            for cluster in top_clusters
            for article in (cluster.articles or [])
        }
        for cluster in top_clusters:
            for article in (cluster.articles or []):
                if article.article_id in articles_to_translate and not article.body_en:
                    article.body_en = translate_to_english(
                        article.body,
                        provider=provider,
                        model=model,
                        local_base_url=local_base_url,
                    )

    results = []
    for cluster in top_clusters:
        # 4. Call synthesis (OpenAI, Local LLM, or Dry Run)
        analysis = _analyze_cluster_or_502(cluster, provider, model, local_base_url)
        
        # 5. Evaluate recap confidence
        confidence = recap_confidence(cluster, analysis)
        
        results.append(_cluster_to_api_payload(cluster, analysis, confidence))
        
    return {
        "query": q,
        "provider": provider,
        "model": model,
        "warnings": fetch_errors,
        "clusters": results
    }


@app.get("/api/trending")
async def get_trending_news_analysis(
    limit: int = Query(10, description="Number of trending articles to retrieve")
):
    print(f"Analyzing trending news (limit: {limit})")
    provider, model, local_base_url = _resolve_llm_config()
    
    # 1. Fetch trending news
    articles = fetch_trending_news(
        CONFIG_PATH,
        limit=limit,
        llm_provider=provider,
        llm_model=model,
        local_base_url=local_base_url,
    )
    if not articles:
        return {"query": "Trending News", "clusters": []}
        
    # 2. Cluster articles
    clusters = cluster_articles(articles, threshold=0.22)
    top_clusters = clusters[:5]
    
    print(f"Running trending clustering with provider: {provider}")
    
    results = []
    for cluster in top_clusters:
        analysis = _analyze_cluster_or_502(cluster, provider, model, local_base_url)
        confidence = recap_confidence(cluster, analysis)
        
        results.append(_cluster_to_api_payload(cluster, analysis, confidence))
        
    return {
        "query": "Trending Right Now",
        "provider": provider,
        "model": model,
        "clusters": results
    }


@app.get("/api/trending-keywords")
async def get_trending_keywords(limit: int = 45, num: int = 10):
    """Retrieve top trending keywords based on real-time global news headlines."""
    return extract_trending_keywords_info(limit=limit, num_keywords=num)


@app.get("/api/sources")
async def get_sources():
    """Retrieve the registered source profiles and their bias configurations."""
    import json
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sources": []}


class ConfigPayload(BaseModel):
    provider: Literal["openai", "gemini", "nim", "local", "dry-run"]
    api_key: str = ""
    model: str = ""


@app.post("/api/config")
async def set_config(payload: ConfigPayload, request: Request):
    """Save AI provider + API key from the UI into the session config."""
    _ensure_config_write_allowed(request)
    provider = payload.provider
    api_key = payload.api_key.strip()
    model = _model_for_provider(provider, payload.model.strip()) or ""

    _session_config["provider"] = provider
    _session_config["api_key"] = api_key or None
    _session_config["model"] = model or None

    # Inject into environment so existing helpers pick it up seamlessly
    os.environ["LLM_PROVIDER"] = provider
    key_env = KEY_ENV_BY_PROVIDER.get(provider)
    model_env = MODEL_ENV_BY_PROVIDER.get(provider)
    if api_key and key_env:
        os.environ[key_env] = api_key
    if model and model_env:
        os.environ[model_env] = model

    _persist_config_to_env(provider, api_key, model)

    return {"status": "ok", "provider": provider, "model": model, "keys_present": _keys_present()}


@app.get("/api/config")
async def get_config():
    """Return current active provider (never expose the API key itself)."""
    provider = _session_config.get("provider") or _default_provider_from_env()
    model_env = MODEL_ENV_BY_PROVIDER.get(provider)
    model = _model_for_provider(
        provider,
        _session_config.get("model") or (os.environ.get(model_env) if model_env else "") or ""
    ) or ""
    provider_key_env = KEY_ENV_BY_PROVIDER.get(provider)
    has_key = bool(_session_config.get("api_key")
                   or (os.environ.get(provider_key_env) if provider_key_env else provider in {"dry-run", "local"}))
    return {"provider": provider, "model": model, "has_key": has_key, "keys_present": _keys_present()}


@app.get("/api/local-llm/status")
async def get_local_llm_status():
    provider, model, local_base_url = _resolve_llm_config()
    return {"provider": provider, **_local_llm_status(model=model, local_base_url=local_base_url)}


@app.get("/api/image-proxy")
async def proxy_image(url: str = Query(..., description="External image URL to fetch through the local API")):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Only absolute http(s) image URLs are supported.")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": IMAGE_PROXY_USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=415, detail="The remote URL did not return an image.")

            image_bytes = response.read(IMAGE_PROXY_MAX_BYTES + 1)
            if len(image_bytes) > IMAGE_PROXY_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Remote image is too large to proxy.")

            return Response(
                content=image_bytes,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )
    except HTTPException:
        raise
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Remote image request failed with HTTP {exc.code}.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not proxy remote image: {exc}") from exc


# HTML Frontend routing
@app.get("/")
async def get_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend index.html is missing. Please create it in the /static folder."}

# Mount static files (CSS, JS) after the root router to ensure root path is handled properly
app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    # Read port from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
