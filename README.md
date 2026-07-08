# Media Story Compare Prototype

Prototype goal: compare several local media text files, detect when they seem to describe the same story, weight the sources, and ask the OpenAI API to produce a detailed neutral recap.

The recap format is designed for volatile details:

> Fire at a chemical factory near Lyon: (60%) 15 people were injured | (12%) 2 people died and 13 were injured. A large cloud of smoke spread around the area, nearby streets were evacuated, and authorities continued air-quality checks.

## What it does now

1. Reads only `.txt` files from a folder.
2. Detects the source from either metadata or the filename.
3. Groups similar files into story clusters using local text similarity.
4. Scores clusters using:
   - number of files,
   - number of distinct sources,
   - source trust and reach weights,
   - local similarity.
5. Calls the OpenAI Responses API to produce:
   - suggested headline,
   - most supported version,
   - detailed compiled recap body,
   - volatile elements as `(XX%) option 1 | (YY%) option 2`,
   - source notes.
6. Writes only a Markdown report.

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

`trust` matters more than `reach` in the prototype score.

## Notes and limitations

This is not fact-checking by itself. It compares the supplied texts and asks the model to synthesize them. For a real system, add:

- URLs and publication dates,
- deduplication by canonical URL,
- named entity extraction,
- embeddings-based clustering,
- source-specific trust profiles by topic,
- quote extraction,
- contradiction tracking,
- human review before publication.
