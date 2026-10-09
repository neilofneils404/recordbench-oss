# Exact search foundation

This change implements the shared grammar and reference matcher for product
slices 00 and 07. It does not switch the existing browser search to exact mode.
The ranked answer retriever still has its existing behavior. Slice 08 adds a
separate [exact result service and UI](EXACT_SEARCH_RESULTS.md), using this grammar
for complete, scoped document enumeration with bounded scans.

## Grammar versions

The current default is `recordbench-exact-v2`, adding [word proximity](EXACT_SEARCH_PROXIMITY.md).
Explicit `parse_query(..., grammar_version="recordbench-exact-v1")` retains the
original grammar and rejects proximity.

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
negation, wildcards, fuzzy search, and field syntax are unsupported
and return a position-bearing error. Inside quoted phrases, only quote and
backslash may be escaped. Control/hidden-format characters are rejected.

Limits are 512 query characters before and after normalization, 128 grammar tokens, and 16 nested parentheses
or NOT levels. Parse errors contain an explanation and character location,
without echoing matter query text. The serialized plan records original text,
normalized expression, grammar version, tokenizer version (`recordbench-words-v1`),
and a typed operator tree. This is a
backend contract, not executable SQL and not permission to access a source.
Normalized expressions omit redundant grouping and use implicit AND so
serialization does not add grammar depth or tokens at those input limits.

## Ask intent classification

`case_intelligence.ask_router.classify(text)` is a pure helper for a future
shared Ask entry point. It returns a frozen `RouteDecision(kind, reason)` with
one short reviewer-facing explanation. It performs no search, model call or I/O,
and is not connected to a UI or HTTP route.

Routing precedence is:

1. `exact` when the trimmed input successfully parses and its structure contains
   a quoted phrase, uppercase Boolean operator (`AND`, `OR`, `NOT`) or proximity
   expression. Adjacent plain words and grouping alone remain questions. The
   router detects uppercase operator tokens outside quoted phrases in the original
   text because the parser retains explicit `AND` provenance but not operator case.
   Exact-search parsing and matching semantics remain case-insensitive and unchanged.
2. `every_source` for case-insensitive positive requests to enumerate matching
   records, such as `find every email`, `list all`, `show me all of the reports`,
   `check every source`, or `I need to find all records mentioning bicycles`. Retrieval
   verbs must begin the request, optionally with `please` before or after
   `can/could/would/will you`; `review` and `enumerate` are also supported.
   `I need` and `I want` can introduce a population directly only when it ends
   the request. Filtered populations require a retrieval verb, including forms
   such as `I need to find` or `I want you to list`. This avoids guessing whether
   a suffix requests collection or another operation: `I need all documents
   about bicycles deleted` remains a question. Populations include generic
   records, media nouns and every extension advertised by the source upload UI,
   including forms such as `all audio files`, `every matching PDF document`,
   `all DOCX files`, `every .xlsx file`, and `all PNGs`.
   A bare population
   must stand alone (`all documents`, `every report?`). Filtered bare phrases
   such as `all documents about bicycles` remain questions: without a retrieval
   verb, they cannot reliably be distinguished from the subject of a
   statement such as `All documents about bicycles agree`. This conservative
   boundary avoids guessing from a verb list; add `List` or `I need to find` to request
   enumeration. Casual uses of `all`, interrogative wrappers, negations, and
   conditional mentions do not qualify through an incidental retrieval phrase.
3. `question` otherwise, including empty input, whose reason says nothing was
   typed. Parse failures fall through to these natural-language rules, so an
   unbalanced quote alone does not select exact search.

The existing parser is the sole authority on exact syntax, including its limits
and punctuation rules. For example, `What does "red bicycle" mean` is `exact`,
but `What does "red bicycle" mean?` is `question` because the whole input fails
to parse. `list all documents with "red` is `every_source` after parsing fails.
The helper does not extract or repair fragments of a malformed query.
Lowercase or mixed-case `and`, `or` and `not` do not establish exact intent in
Ask. `Did Smith and Jones meet on Tuesday` is `question` with or without `?`;
`show me all the texts between Dana and Lee` and `List each and every document`
are `every_source` with or without `?`. `Smith AND Jones` and `Smith NOT Jones`
are `exact` when the whole input parses. Quoted phrases and proximity expressions
still establish exact intent, including inside lowercase Boolean expressions.
For example, `"red AND blue" and green` selects exact search because of its quoted
phrase; the uppercase `AND` inside that phrase is literal text, not an operator.

`tests/test_ask_router.py` covers synthetic intent examples, ambiguous inputs,
precedence, immutable decisions and explanations. This foundation does not
claim that enumeration, source coverage or cited answers have run.

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
