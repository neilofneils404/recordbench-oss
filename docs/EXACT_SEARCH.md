# Exact search foundation

This change implements the shared grammar and reference matcher for product
slices 00 and 07. It does not switch the existing browser search to exact mode.
The ranked answer retriever still has its existing behavior. An explicit exact
result service, pagination, backend integration, and UI follow in slice 08.

## Grammar v1

`recordbench-exact-v1` supports words, quoted phrases, `AND`, `OR`, `NOT`, and
parentheses. Operators are case-insensitive; quote a literal operator word such
as `"and"`. Adjacent operands imply AND. Precedence is NOT, AND, then OR.

| Query | Meaning within one eligible document |
| --- | --- |
| `red AND bicycle` | Both terms occur, possibly on different extracted pages/units |
| `"red bicycle"` | Consecutive word tokens in one extracted unit |
| `bicycle NOT blue` | Bicycle occurs and blue occurs nowhere in its extracted units |
| `(red OR blue) AND bicycle` | Bicycle plus either color |
| `NOT blue` | An eligible document with extracted word tokens and no blue token |

Negation-only queries are defined over the caller's authorized eligible
population. Missing, failed, and unextracted sources are not inferred to match.
The reference matcher does not perform authorization or discover documents.
Every backend must apply matter and selected-population boundaries before
matching and counting. Empty/tokenless documents never match, including NOT.

Text and queries use Unicode NFC, case folding, and curly-to-straight apostrophe
normalization, with NFC applied again after folding. Words retain attached
Unicode combining marks, internal apostrophes and ASCII hyphens; `RB-101` is
different from `RB 101`. Other punctuation separates words inside document text
and quoted phrases. There is no stemming or stop-word removal. Phrase adjacency
does not mean byte equality, and phrases do not cross extracted-unit boundaries.
This word-token contract does not promise language-specific segmentation.

Unquoted punctuation must be quoted rather than silently reinterpreted. Dash
negation, proximity, wildcards, fuzzy search, and field syntax are unsupported
and return a position-bearing error. Inside quoted phrases, only quote and
backslash may be escaped. Control/hidden-format characters are rejected.

Limits are 512 query characters before and after normalization, 128 grammar tokens, and 16 nested parentheses
or NOT levels. Parse errors contain an explanation and character location,
without echoing matter query text. The serialized plan records original text,
normalized expression, grammar version, and a typed operator tree. This is a
backend contract, not executable SQL and not permission to access a source.
Normalized expressions omit redundant grouping and use implicit AND so
serialization does not add grammar depth or tokens at those input limits.

## Known-answer corpus and validation

`tests/fixtures/synthetic/product-foundation/v1/corpus.json` contains invented
documents, unit identifiers/hashes, manually specified search results, a
foreign-matter canary, an unavailable source, separate same-name people,
competing accounts, and a decisive fourteenth unit. A separate SHA-256 fixes
the corpus bytes. Changes require a deliberate fixture/version review.

`tests/test_exact_search.py` checks truth tables, document versus phrase scope,
late exclusions, exact normalization, malformed/unsupported queries, bounded
parsing, serialization, and known fixture results. Run:

```bash
PYTHONPATH=src python -m pytest -q tests/test_exact_search.py
```

CPU browser and PostgreSQL result-service acceptance remain explicitly pending
in the corpus. A reference matcher pass does not establish database parity,
model recall, or deployment scale. Existing frozen review-acceptance packs
remain unchanged. No runtime schema, model, or deployment configuration changes.
