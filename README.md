# Media Story Compare Prototype

Prototype goal: compare several local media text files, detect when they seem to describe the same story, weight the sources, and ask OpenAI or a local LLM to produce a detailed neutral recap.

The recap format is designed for volatile details:

> Fire at a chemical factory near Lyon: (60%) 15 people were injured | (12%) 2 people died and 13 were injured. A large cloud of smoke spread around the area, nearby streets were evacuated, and authorities continued air-quality checks.

## What it does now

1. Reads only `.txt` files from a folder.
2. Detects the source from either metadata or the filename.
3. Extracts lightweight date/time and location signals from metadata and article text.
4. Groups similar files into story clusters using local text similarity plus date/location guardrails.
5. Blocks likely false merges when articles have the same or close date but different locations, or clearly incompatible dates.
6. Scores clusters using:
   - number of files,
   - number of distinct sources,
   - source trust and reach weights,
   - local similarity,
   - similarity coverage, which is safer than average similarity on larger clusters,
   - date/location guardrail consistency.
7. Calls the selected LLM provider to produce:
   - suggested headline,
   - most supported version,
   - detailed compiled recap body,
   - volatile elements as `(XX%) option 1 | (YY%) option 2`,
   - source notes.
8. Adds a recap-confidence metric that tells the reader whether the recap is probably usable or whether more data should be gathered.
9. Writes only a Markdown report.

## Run

Dry run without any LLM:

```bash
python3 main.py samples --dry-run
```

Use OpenAI:

```bash
LLM_PROVIDER=openai OPENAI_API_KEY=your_key python3 main.py samples
```

Use a local Ollama-compatible server:

```bash
LLM_PROVIDER=local LOCAL_LLM_MODEL=gemma4:e4b python3 main.py samples
```

You can also pass the provider directly:

```bash
python3 main.py samples --provider local --model gemma4:e4b
```

## Local LLM server for teammates

By default Ollama listens on `localhost`, which only works on the same machine.
To let a teammate use the Ollama server running on your MacBook, start Ollama so it listens on the local network:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Then your teammate can point this project at your MacBook's LAN IP:

```bash
LLM_PROVIDER=local LOCAL_LLM_BASE_URL=http://YOUR_MACBOOK_IP:11434 LOCAL_LLM_MODEL=gemma4:e4b python3 main.py samples
```

Keep this on a trusted network only. If the Mac firewall blocks access, allow incoming connections for Ollama or use each teammate's own local Ollama server.

## Source input

```text
SOURCE: Le Monde
TITLE: Explosion in city center leaves several injured
DATE: 2026-07-08
URL: https://example.com/story

Full article text here...
```

If no `SOURCE:` is given, the source is guessed from the filename, for example:

```text
lemonde_explosion.txt
arte_explosion.txt
brut_explosion.txt
```

## Adjust source trust

Edit `config/sources.json`.

Example:

```json
{
  "name": "Le Monde",
  "aliases": ["lemonde", "le_monde", "le monde"],
  "trust": 0.92,
  "reach": 0.90
}
```

`trust` still matters more than `reach`, but both are kept in the support logic.


## Date/location guardrails

The prototype now extracts simple signals such as:

```text
DATE: 2026-07-08
PUBLICATION_DATE: 2026-07-08
LOCATION: Lyon
PLACE: Lyon
CITY: Lyon
COUNTRY: France
```

Metadata dates are treated as the primary date signal. Dates found inside the body are used only when metadata does not provide a usable date, because body dates are often background references rather than the event date.

The guardrail is conservative:

- same or close date + shared location can slightly help a merge,
- same or close date + different locations blocks a likely false merge,
- dates that are far apart block a likely false merge,
- missing date/location data does not block by itself.

The report also shows:

- `Similarity coverage`: whether each article has at least one good local neighbour in the cluster,
- `Best-neighbour similarity`: a less fragile metric than all-pair average similarity,
- `Date/location guardrail score`,
- `Recap confidence`: High / Medium / Low with a recommendation to trust the recap or search for more data.

## Notes and limitations

This is not fact-checking by itself. It compares the supplied texts and asks the model to synthesize them. For a real system, add:

- canonical URLs and better publication/event-date separation,
- deduplication by canonical URL,
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
python3 main.py samples --provider local --model gemma4:e4b
```

The report is written to:

```text
reports/report.md
```

If you want to write to another file:

```bash
python3 main.py samples --provider local --model gemma4:e4b --out reports/local_test.md
```

## Use the Ollama API running on Seth's MacBook

If Seth's MacBook is already running Ollama, teammates can use that Ollama API instead of running their own local model.

On Seth's MacBook, expose Ollama on the local network:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

On a teammate's machine, run this project by pointing `--local-base-url` to Seth's MacBook:

```bash
python3 main.py samples --provider local --model gemma4:e4b --local-base-url http://10.68.247.29:11434
```

Current Seth MacBook local IP:

```text
10.68.247.29
```

If the network changes, re-check Seth's MacBook IP with:

```bash
ifconfig en0
```

The teammate does not need to pull `gemma4:e4b` locally in this setup. The model runs on Seth's MacBook, and this project sends requests to that MacBook's Ollama API.

If connection fails:

- confirm both machines are on the same network,
- confirm Ollama is running on Seth's MacBook,
- allow incoming connections for Ollama in macOS firewall settings,
- try `http://10.68.247.29:11434/api/tags` in a browser or with `curl`.
