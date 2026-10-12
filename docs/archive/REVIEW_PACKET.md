# Evaluation review packet (for an INDEPENDENT second reviewer)

Status today: every question carries `status: reviewed` / `reviewed_by: assistant-source-review`. That is a self-review by the same assistant that drafted the labels, **not** independent validation. Until a second person completes the sign-off below, treat all metrics as exploratory.

Pinned sources: `pytest-dev/iniconfig@00e7d87c7353b1ffecc4cd55f19acfffedd5233e`, `ljharb/qs@07b1d4d82c8f9301c105ea4b94fa2302cfd6e8b4`.

## How to review
1. `git clone <repo>`; `git checkout <sha>` for each pinned repo.
2. For each row: is the question unambiguous, are `expected_files` really where the answer lives, and is the answerable/unanswerable label right? (Unanswerable = confirm the capability is absent: search the checkout.)
3. Record Agree/Disagree and notes. **Do not edit `questions.json` to improve metrics.** Put proposed corrections in a separate PR/file.
4. Only after sign-off, replace `reviewed_by` with the reviewer's identifier and update `eval/REVIEW_LOG.md`.

| ID | Repo | Question | Expected files | Answerable | Paraphrase | Difficulty | Author's rationale | Reviewer: agree? / notes |
|---|---|---|---|---|---|---|---|---|
| ini-01 | iniconfig | What wrapper object is returned when indexing a parsed configuration by section name? | `src/iniconfig/__init__.py` | yes | True | lookup | src/iniconfig/__init__.py defines SectionWrapper, which wraps a single named section of an IniConfig instance. |  |
| ini-02 | iniconfig | What characters does `COMMENTCHARS` define as INI comment markers? | `src/iniconfig/_parse.py` | yes | False | lookup | `src/iniconfig/_parse.py` defines COMMENTCHARS = '#;', the characters treated as comment markers. |  |
| ini-03 | iniconfig | How does the library signal that a line in the ini file cannot be parsed? | `src/iniconfig/exceptions.py`, `src/iniconfig/_parse.py` | yes | True | explanation | exceptions.py defines ParseError with path/lineno/msg; _parse.py raises ParseError in parse_ini_data and parse_lines whenever it encounters invalid syntax. |  |
| ini-04 | iniconfig | What does `strip_inline_comments` control in `IniConfig.parse()`? | `src/iniconfig/_parse.py`, `src/iniconfig/__init__.py` | yes | False | lookup | `src/iniconfig/__init__.py` exposes strip_inline_comments in IniConfig.parse(), and `_parse.py` applies it while parsing values and continuation lines. |  |
| ini-05 | iniconfig | What is the data structure that maps a section name and key to the line number where it appears? | `src/iniconfig/__init__.py`, `src/iniconfig/_parse.py` | yes | True | explanation | __init__.py stores _sources: Mapping[tuple[str, str\|None], int]; _parse.py builds this as sources dict indexed by (section, name) tuples. |  |
| ini-06 | iniconfig | How does IniConfig.lineof() return the line number for a given section and key? | `src/iniconfig/__init__.py` | yes | False | explanation | IniConfig.lineof() in __init__.py looks up (section, name) in self._sources and returns lineno+1 (1-indexed), or None if not found. |  |
| ini-07 | iniconfig | Which module is responsible for tokenising raw ini text into parsed lines? | `src/iniconfig/_parse.py` | yes | True | lookup | src/iniconfig/_parse.py contains parse_lines() which iterates over raw text lines and calls _parseline() to produce ParsedLine tokens. |  |
| ini-08 | iniconfig | Does iniconfig expose an asynchronous API for parsing INI content? | - | no | False | explanation | The pinned source exposes synchronous parse/parse_ini_data/parse_lines functions and no asynchronous parsing API; this is an absence-of-capability question rather than a feature lookup. |  |
| ini-09 | iniconfig | What happens when SectionWrapper iterates over its keys — in what order are they yielded? | `src/iniconfig/__init__.py` | yes | False | explanation | SectionWrapper.__iter__ in __init__.py yields keys sorted by their line number using self.config.lineof(), preserving file order. |  |
| ini-10 | iniconfig | Where is duplicate section detection implemented and what error does it raise? | `src/iniconfig/_parse.py`, `src/iniconfig/exceptions.py` | yes | True | cross-file | _parse.py's parse_ini_data raises ParseError (defined in exceptions.py) with message 'duplicate section <name>' when the same section header appears twice. |  |
| qs-01 | qs | What is the default maximum nesting depth for parsing query strings? | `lib/parse.js` | yes | True | lookup | lib/parse.js defines defaults.depth = 5, which is the maximum object nesting depth before further nesting is treated as a key. |  |
| qs-02 | qs | What default value is assigned to `defaults.parameterLimit` in `lib/parse.js`? | `lib/parse.js` | yes | False | lookup | `lib/parse.js` declares defaults.parameterLimit = 1000 and normalization uses this value when no parameterLimit option is supplied. |  |
| qs-03 | qs | Which encoders are exposed as `Format.RFC1738` and `Format.RFC3986` in `lib/formats.js`? | `lib/formats.js` | yes | False | lookup | `lib/formats.js` defines RFC1738 and RFC3986 and exports matching formatters; RFC3986 is the default. |  |
| qs-04 | qs | What mechanism does the library use to track objects that were created due to an array-limit overflow? | `lib/utils.js` | yes | True | explanation | lib/utils.js uses a side-channel (overflowChannel = getSideChannel()) to store per-object max numeric index metadata without polluting object properties. |  |
| qs-05 | qs | What are the four array prefix formats available when stringifying arrays? | `lib/stringify.js` | yes | True | lookup | lib/stringify.js defines arrayPrefixGenerators with four entries: brackets, comma, indices, and repeat. |  |
| qs-06 | qs | How does the library expose its public API — which functions or objects are exported from the main entry point? | `lib/index.js` | yes | True | lookup | lib/index.js exports an object with three properties: formats, parse, and stringify — the entire public surface of the library. |  |
| qs-07 | qs | How are date values converted to strings by default when stringifying objects? | `lib/stringify.js` | yes | True | explanation | lib/stringify.js captures toISO = Date.prototype.toISOString and uses it as the default serializer for Date values; custom serializers can be provided via options. |  |
| qs-08 | qs | Does this repository implement automatic OAuth access-token refresh? | - | no | False | lookup | The pinned qs repository is a query-string parsing/stringifying library; its package metadata and source modules do not implement OAuth, access-token lifecycle, or token refresh. This tests retrieval on a topic outside the repository. |  |
| qs-09 | qs | Which helper module does the query string parser import, and what function does it use from it? | `lib/parse.js`, `lib/utils.js` | yes | True | cross-file | lib/parse.js requires './utils' and uses utils.decode as the default decoder; lib/utils.js exports that decode function. |  |
| qs-10 | qs | Does qs include server-side session management or cookie handling? | - | no | False | explanation | No session, cookie, or HTTP server code exists anywhere in lib/; qs is solely a querystring serialisation library. |  |

## Sign-off

Reviewer name: ____________  Date: ________  Verdict: [ ] all labels confirmed  [ ] corrections proposed (see separate file)
