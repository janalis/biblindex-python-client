# Changelog

## 0.3.0 (unreleased — cut with `make release part=minor`)

Hardening release. The theme: the API has several behaviours that produce a
plausible **wrong** answer rather than an error, and a caller cannot tell the
difference. Each is now either fixed or refused loudly.

All behaviour below was verified against the live API on 02/09/2026.

### Fixed

- **JSON-LD collections work again.** The client looked for prefixed Hydra keys
  (`hydra:member`, `hydra:view`, `hydra:totalItems`, `hydra:next`); API Platform
  4 serves them bare (`member`, `view`, `totalItems`, `next`). In the default
  `application/ld+json` mode `request()` returned a plain 7-key dict where a
  `LazyCollection` was expected, `len()` returned the key count, and iteration
  yielded key names. Both spellings are now read, at all six call sites —
  including the second-page path, which was a separate instance of the same bug.

  This changes what `request()` returns in ld+json mode: `len(result)` on
  `/api/quotations` goes from `7` to the real total.

- **`id` is backfilled from `@id`.** In ld+json the API omits `id` on `authors`,
  `work_editions` and `editions` while serving it in plain JSON. A join keyed on
  the missing field matched zero rows and raised nothing, because `str(None)` is
  a valid dict key. The value is now derived from the `@id` IRI, which carries
  the same identifier. Opt out with `backfillIds=False`.

- **Error bodies are read.** A 403 previously surfaced as a bare
  `403 Client Error: Forbidden`, discarding the server's own explanation.

### Added

- **Query parameter validation.** API Platform answers 200 and silently drops
  parameters an endpoint does not declare, so `request("/api/quotations",
  {"author": 42})` returned all 709,440 rows looking filtered. Undeclared
  parameters now raise `UndeclaredParameterError` before the request is sent.
  The vocabulary comes from `/api/docs.jsonopenapi`, fetched once per client and
  only when a call actually carries a filter, reinforced for free by the `search`
  block of each collection response. Opt out with `validateParams=False`, per
  client or per call.

- **`client.filtersFor(resource)`** — the declared filters for an endpoint, so a
  caller can ask instead of guessing. Raises rather than reporting "no filters"
  for an endpoint it could not read.

- **Exception hierarchy** rooted at `BiblIndexError`: `AccessDeniedError`,
  `AuthenticationError`, `BiblIndexHTTPError`, `UndeclaredParameterError`,
  `PageSizeError`, `PaginationLimitError`,
  `FilterVocabularyUnavailableError`. A 403 on a corpus endpoint names
  `ROLE_API_CLIENT` and states the evidence. The HTTP types also derive from
  `requests.HTTPError`, so existing handlers keep working.

- **Explicit paging**: `client.fetchAll()`, `client.iterCollection()`,
  `LazyCollection.fetchAll()` / `.iterAll()` / `.iterPages()`, and the
  `totalItems` / `isComplete` / `hasMore` properties.

- A non-JSON response body now raises `BiblIndexError` naming the content type,
  instead of a raw `JSONDecodeError`.

### Changed — breaking

- **`LazyResource` and `LazyCollection` are read-only** (`Mapping` and
  `Sequence`, not `MutableMapping` / `MutableSequence`). Writes only ever
  touched the in-memory copy and were never sent to the server, which reads as
  a successful save. Use `dict(resource)` or `list(collection)` for a mutable
  copy.

- **Implicit paging is capped** at `maxAutoPages` (default 50). `collection[-1]`
  and `list(collection)` previously walked every page — several thousand
  requests on `/api/quotations`. Use `fetchAll()` / `iterAll()` for a deliberate
  full walk, or raise the cap.

- **`itemsPerPage` above 100 raises `PageSizeError`.** The server silently
  serves 100 whatever is asked for; clamping it quietly would repeat the very
  failure this release exists to remove.

- `request()`'s `params` argument is now optional (widening only).

### Documentation

- Removed the warning that recommended `application/ld+json` over
  `application/json` on the grounds that ld+json gave accurate `len()` and
  pagination. Until this release the opposite was true, so anyone following the
  README landed directly on the broken path.
