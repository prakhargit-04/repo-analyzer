# Evaluation Dataset Source Review Log

**Reviewed by:** assistant source review at the user's request  
**Review scope:** question wording, expected-file support, paraphrase labels, difficulty, and unanswerable labels  
**Important limitation:** this is not independent second-reviewer validation. Treat benchmark metrics as exploratory, not as a publication-grade gold set.

## Pinned revisions

- `pytest-dev/iniconfig` at `00e7d87c7353b1ffecc4cd55f19acfffedd5233e`
- `ljharb/qs` at `07b1d4d82c8f9301c105ea4b94fa2302cfd6e8b4`

## Question-by-question review

| ID | Decision / relevant source | Review note |
|---|---|---|
| `ini-01` | `src/iniconfig/__init__.py` | `IniConfig.__getitem__` returns a `SectionWrapper`; wording avoids that identifier, so paraphrase=true. |
| `ini-02` | `src/iniconfig/_parse.py` | `COMMENTCHARS = "#;"`; question now names `COMMENTCHARS`, so paraphrase=false. |
| `ini-03` | `src/iniconfig/_parse.py`, `src/iniconfig/exceptions.py` | Parsing raises `ParseError`, whose class and path/line/message fields are defined in `exceptions.py`; wording avoids the exact exception name. |
| `ini-04` | `src/iniconfig/__init__.py`, `src/iniconfig/_parse.py` | `IniConfig.parse()` passes `strip_inline_comments` to parsing functions; question names the option and API, so paraphrase=false. |
| `ini-05` | `src/iniconfig/__init__.py`, `src/iniconfig/_parse.py` | `_sources` maps `(section, key)` tuples to source line numbers; wording asks about the concept rather than the identifier. |
| `ini-06` | `src/iniconfig/__init__.py` | `IniConfig.lineof()` uses the `_sources` mapping and converts zero-based stored lines to one-based line numbers; exact method named, so paraphrase=false. |
| `ini-07` | `src/iniconfig/_parse.py` | `parse_lines()` and `_parseline()` convert text lines into parsed records; question does not name either function or file. |
| `ini-08` | Repository API surface; `src/iniconfig/__init__.py`, `src/iniconfig/_parse.py` | Unanswerable/absence query: the pinned package exposes synchronous parsing functions, not an asynchronous parsing API. This is an absence claim, so interpret cautiously. |
| `ini-09` | `src/iniconfig/__init__.py` | `SectionWrapper.__iter__()` sorts keys by `lineof`; class name is explicit, so paraphrase=false. |
| `ini-10` | `src/iniconfig/_parse.py`, `src/iniconfig/exceptions.py` | Duplicate sections are detected in `parse_ini_data()` and raise `ParseError`; expected files cover both implementation and exception definition. |
| `qs-01` | `lib/parse.js` | The parser default has `depth: 5`; question avoids the `defaults.depth` identifier. |
| `qs-02` | `lib/parse.js` | `defaults.parameterLimit = 1000`; question names the exact property and file, so paraphrase=false. |
| `qs-03` | `lib/formats.js` | Exports format names and formatters for RFC1738 and RFC3986; the revised wording names the relevant format identifiers, so paraphrase=false. |
| `qs-04` | `lib/utils.js` | `overflowChannel` from `side-channel` records maximum numeric indexes for array-limit overflow objects; question describes the mechanism without naming it. |
| `qs-05` | `lib/stringify.js` | `arrayPrefixGenerators` defines `brackets`, `comma`, `indices`, and `repeat`; question asks conceptually, without the identifier. |
| `qs-06` | `lib/index.js` | The public entry exports `formats`, `parse`, and `stringify`; question avoids listing these identifiers in its wording. |
| `qs-07` | `lib/stringify.js` | The default `serializeDate` calls `Date.prototype.toISOString`; question describes the behavior without naming the implementation identifier. |
| `qs-08` | Outside the pinned project's scope; empty expected-file list | Rewritten to ask about OAuth access-token refresh, a capability not implemented by this query-string parser. Unanswerable questions are scored by top-1 score distribution only. |
| `qs-09` | `lib/parse.js`, `lib/utils.js` | `parse.js` imports `./utils` and uses `utils.decode`; expected files cover the import and the helper's export. |
| `qs-10` | Outside the pinned project's scope; empty expected-file list | Session management and cookie handling are outside this query-string parser's implemented scope; used as an unanswerable query, not a claim that all repository text has been exhaustively machine-proven absent. |

## Dataset counts after review

- Total questions: 20
- Answerable: 17
- Answerable paraphrases: 11
- Answerable non-paraphrases: 6
- Unanswerable: 3 (`ini-08`, `qs-08`, `qs-10`)
- Status: all questions explicitly `reviewed`
- Reviewer field: `assistant-source-review`

## Known label limitations

- Unanswerable questions test absence of evidence, which is harder to label rigorously than positive file relevance. Their score distributions should be interpreted qualitatively.
- Relevance is judged at file level, not line level; a retrieved chunk from the correct file may not contain the exact supporting lines.
- Twenty questions are insufficient for high-confidence generalization.
- Assistant review of agent-drafted data is not an independent evaluation. If benchmark results will be used for external claims, have a second person review the labels before interpreting them as gold-standard results.
