# Media Story Compare Prototype

Prototype goal: compare several media articles, detect when they seem to describe the same story, weight the sources, and ask OpenAI or a local LLM to produce a detailed neutral recap.

The normal input is now a URL list file:

```text
https://www.lemonde.fr/example/article.html
https://www.arte.tv/fr/example/story
https://www.brut.media/fr/videos/example/story
```

The project fetches each URL, extracts the visible article text, then sends article extracts to the selected LLM. This is important: most local LLMs cannot browse the web by themselves, so the Python project fetches the pages first instead of asking the model to magically read links.

The recap format is designed for volatile details:

> Fire at a chemical factory near Lyon: (60%) 15 people were injured | (12%) 2 people died and 13 were injured. A large cloud of smoke spread around the area, nearby streets were evacuated, and authorities continued air-quality checks.

## What it does now

1. Reads a `.txt` file containing one `http://` or `https://` article URL per line.
2. Fetches each article URL with a browser-like User-Agent.
3. Extracts title, metadata, publication-date hints, source/site name, and article body text. URL mode now tries schema.org JSON-LD article bodies first, then `newspaper3k`, then a stricter internal HTML parser. Extracted text is cleaned again to remove page furniture such as `SECTIONS`, `TOP STORIES`, newsletter blocks, and unrelated teaser lists.
4. Detects the source from the URL, site metadata, title, and extracted text.
5. Extracts lightweight date/time and location signals from metadata and article text.
6. Groups similar articles into story clusters using local text similarity plus date/location guardrails.
7. Blocks likely false merges when articles have the same or close date but different locations, or clearly incompatible dates.
8. Ranks clusters internally using source support, source diversity, similarity coverage, and date/location guardrail consistency. The internal prototype score is no longer printed in the report.
9. Calls the selected LLM provider to produce:
   - suggested headline,
   - most supported version,
   - detailed compiled recap body,
   - volatile elements as `(XX%) option 1 | (YY%) option 2`,
   - source notes.
10. Adds a recap-confidence metric that tells the reader whether the recap is probably usable or whether more data should be gathered.
11. Writes both a Markdown report and a website-friendly JSON report.

Legacy mode still works: if the input path is a folder, the project reads local `.txt` article files from that folder.

## Extraction quality notes

URL extraction is deliberately strict now. In `--extractor auto` mode the project tries, in order:

1. schema.org / JSON-LD `Article` or `NewsArticle` data, when the page exposes an `articleBody`;
2. `newspaper3k`;
3. the internal fallback parser, limited to likely article/main containers.

After extraction, the project removes common page furniture markers such as `SECTIONS`, `TOP STORIES`, `ADVERTISEMENT`, `RELATED STORIES`, `NEWSLETTER`, and `SUBSCRIBE`. If the remaining text still looks polluted or too short, the URL is reported as an extraction error instead of being sent to clustering or the LLM. The JSON report includes `extractor`, `extractor_fallback_reason`, and `body_char_count` per article for debugging.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional `.env` file:

```bash
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-5.5
LLM_PROVIDER=openai
```

For a local LLM:

```bash
LLM_PROVIDER=local
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_MODEL=gemma4:e4b
```

## Run with URLs

Create a URL list:

```bash
cat > sample.txt <<'EOF'
https://example.com/article-one
https://example.com/article-two
https://example.com/article-three
EOF
```

Dry run without an LLM:

```bash
python3 main.py sample.txt --dry-run
```

Use OpenAI:

```bash
python3 main.py sample.txt --provider openai
```

Use a local Ollama-compatible server:

```bash
python3 main.py sample.txt --provider local --model gemma4:e4b
```

If a site is slow:

```bash
python3 main.py sample.txt --provider local --fetch-timeout 40
```

Extractor options:

```bash
# Default: try newspaper3k first, then fallback parser
python3 main.py sample.txt --extractor auto --dry-run

# Force newspaper3k only, useful when debugging extraction quality
python3 main.py sample.txt --extractor newspaper --dry-run

# Use the older internal parser only
python3 main.py sample.txt --extractor fallback --dry-run
```

Reports are written to:

```text
reports/report.md
reports/report.json
```

Custom output paths:

```bash
python3 main.py sample.txt --provider local --out reports/url_test.md --json-out reports/url_test.json
```

## URL input format

The file can contain plain URLs, comments, or text around URLs. The first `http(s)://` URL found on each non-comment line is used.

```text
# Factory fire cluster
https://www.lemonde.fr/example/article.html
ARTE: https://www.arte.tv/fr/example/story
see also https://www.brut.media/fr/videos/example/story
```

Only URLs are loaded from a URL list file. The old full-article `.txt` format is still supported only when you pass a folder instead of a file.

## Legacy local text mode

```bash
python3 main.py samples --dry-run
python3 main.py samples --provider local --model gemma4:e4b
```

A local article file can still look like this:

```text
SOURCE: Le Monde
TITLE: Explosion in city center leaves several injured
DATE: 2026-07-08
URL: https://example.com/story
LOCATION: Lyon

Full article text here...
```

## Adjust source trust

Edit `config/sources.json`.

Example:

```json
{
  "name": "Le Monde",
  "aliases": ["lemonde", "le_monde", "le monde", "lemonde.fr"],
  "trust": 0.92,
  "reach": 0.90
}
```

`trust` still matters more than `reach`, but both are kept in the support logic.

## Date/location guardrails

The prototype extracts simple signals such as:

```text
DATE: 2026-07-08
PUBLICATION_DATE: 2026-07-08
LOCATION: Lyon
PLACE: Lyon
CITY: Lyon
COUNTRY: France
```

For URLs, it tries to pull date signals from common metadata such as `article:published_time`, `date`, `dc.date`, and `datePublished`. It also scans extracted article text.

Metadata dates are treated as the primary date signal. Dates found inside the body are used only when metadata does not provide a usable date, because body dates are often background references rather than the event date.

The guardrail is conservative:

- same or close date + shared location can slightly help a merge,
- same or close date + different locations blocks a likely false merge,
- dates that are far apart block a likely false merge,
- missing date/location data does not block by itself.

The report also shows:

- `Average pair similarity`: the average similarity across every article pair in the cluster. This can go down as a cluster gets larger, even when all articles really are about the same story, because each outlet adds different context.
- `Similarity coverage`: the share of articles that have at least one good local neighbour in the cluster. This is usually more useful for larger clusters because each article only needs one strong bridge to the story.
- `Best-neighbour similarity`: the average of each article's strongest match inside the cluster.
- `Date/location guardrail score`,
- `Recap confidence`: High / Medium / Low with a recommendation to trust the recap or search for more data.

Raw date/location signal dumps are no longer printed in the Markdown report because they can be noisy when extraction fails. Per-article signals remain available in JSON for debugging and future website rendering.

## JSON report format

`reports/report.json` keeps the old website-oriented shape: the top level is a list of story clusters. Each cluster contains:

- cluster metrics: `cluster_id`, `avg_similarity`, `avg_best_similarity`, `similarity_coverage`, `guardrail_score`, `guardrail_notes`,
- source list: `sources`,
- article cards: `article_id`, `source`, `title`, `url`, `date`, `locations`, `extractor`,
- `analysis`: headline, compiled body, volatile elements, and source notes,
- `confidence`: score, label, recommendation, and factor breakdown.

This is meant to be easy to render later in a web app without parsing Markdown.

## Notes and limitations

This is not fact-checking by itself. It compares the fetched article extracts and asks the model to synthesize them.

URL extraction now uses `newspaper3k` first and a small internal parser as fallback. Some sites may still fail because of:

- paywalls,
- cookie walls,
- JavaScript-rendered article bodies,
- anti-bot protections,
- missing or messy metadata.

Those failures are shown as warnings and skipped. For a real system, add:

- source-specific extractors for outlets that block or heavily customize pages,
- canonical URLs and deduplication by canonical URL,
- production-grade named entity extraction for locations,
- embeddings-based clustering,
- source-specific trust profiles by topic,
- quote extraction,
- contradiction tracking,
- human review before publication.

## Quick local Ollama setup

Run with your own local Ollama server:

```bash
ollama pull gemma4:e4b
ollama serve
python3 main.py sample.txt --provider local --model gemma4:e4b
```

## Use an Ollama API running on another machine

By default Ollama listens on `localhost`, which only works on the same machine.
To let a teammate use the Ollama server running on your MacBook, start Ollama so it listens on the local network:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Then your teammate can point this project at your MacBook's LAN IP:

```bash
python3 main.py sample.txt --provider local --model gemma4:e4b --local-base-url http://YOUR_MACBOOK_IP:11434
```

Keep this on a trusted network only. If connection fails:

- confirm both machines are on the same network,
- confirm Ollama is running on the host machine,
- allow incoming connections for Ollama in the firewall,
- try `http://HOST_IP:11434/api/tags` in a browser or with `curl`.
