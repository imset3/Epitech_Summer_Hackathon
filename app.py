import os
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt includes python-dotenv
    load_dotenv = None

from media_compare.search import fetch_trending_news, extract_trending_keywords
from media_compare.fetcher import fetch_articles_from_apis
from media_compare.clustering import cluster_articles
from media_compare.llm import analyze_cluster
from media_compare.confidence import recap_confidence
from media_compare.sources import load_sources

app = FastAPI(title="News Search & Compare API")

# ── In-memory session config (overrides env vars when set from UI) ──────────
_session_config: dict = {
    "provider": None,     # "openai" | "gemini" | "local" | "dry-run"
    "api_key": None,      # API key entered via UI
    "model": None,        # model name (optional override)
}

VALID_PROVIDERS = {"openai", "gemini", "nim", "local", "dry-run"}

MODEL_ENV_BY_PROVIDER = {
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "nim": "NVIDIA_NIM_MODEL",
    "local": "LOCAL_LLM_MODEL",
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

if load_dotenv:
    load_dotenv(ENV_PATH)

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

    local_base_url = os.environ.get("LOCAL_LLM_BASE_URL")
    return provider, model, local_base_url


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
    limit: int = Query(8, description="Number of news articles to retrieve")
):
    print(f"Received search query: '{q}' (limit: {limit})")
    
    # 1. Search and scrape news articles using the same API pipeline as the CLI.
    sources = load_sources(CONFIG_PATH)
    articles, fetch_errors = fetch_articles_from_apis(
        q,
        sources,
        limit_per_api=limit,
        timeout=20,
        extractor="auto",
    )
    if not articles:
        return {"query": q, "provider": None, "model": None, "clusters": [], "warnings": fetch_errors}
        
    # 2. Cluster articles using text similarity
    clusters = cluster_articles(articles, threshold=0.22)
    
    # We will only analyze the top 5 clusters to avoid excessive LLM usage
    top_clusters = clusters[:5]
    
    provider, model, local_base_url = _resolve_llm_config()
    
    print(f"Running clustering and synthesis with provider: {provider}")
    
    results = []
    for cluster in top_clusters:
        # 3. Call synthesis (OpenAI, Local LLM, or Dry Run)
        analysis = _analyze_cluster_or_502(cluster, provider, model, local_base_url)
        
        # 4. Evaluate recap confidence
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
    
    # 1. Fetch trending news
    articles = fetch_trending_news(CONFIG_PATH, limit=limit)
    if not articles:
        return {"query": "Trending News", "clusters": []}
        
    # 2. Cluster articles
    clusters = cluster_articles(articles, threshold=0.22)
    top_clusters = clusters[:5]
    
    provider, model, local_base_url = _resolve_llm_config()
    
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
    keywords = extract_trending_keywords(limit=limit, num_keywords=num)
    return {"keywords": keywords}


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
    model = payload.model.strip()

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
    model = _session_config.get("model") or (os.environ.get(model_env) if model_env else "") or ""
    provider_key_env = KEY_ENV_BY_PROVIDER.get(provider)
    has_key = bool(_session_config.get("api_key")
                   or (os.environ.get(provider_key_env) if provider_key_env else provider in {"dry-run", "local"}))
    return {"provider": provider, "model": model, "has_key": has_key, "keys_present": _keys_present()}


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
