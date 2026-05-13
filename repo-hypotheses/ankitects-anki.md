# Triage Graph: ankitects/anki

## Investigated

### fix/flipqa-quoted-hr-id (ready)
- **Issue**: flipQA (card template flip) fails silently when the `<hr>` separator uses quoted attributes (`id="answer"` or `id='answer'`), extra attributes, or different casing.
- **Root cause**: Regex `<hr id=answer>` is a literal match. Real card templates produced by Anki's own editor and third-party tools frequently quote the attribute.
- **Fix**: Replace with a robust regex that handles: quoted/unquoted `id`, case-insensitive tag/attribute matching, extra attributes on the `<hr>`.
- **Tests**: No new test files (Anki's card template tests are in rslib). The regex is self-documenting with named patterns.
- **Risk**: Medium. The regex is more complex but strictly more permissive -- it matches everything the old one matched plus valid HTML variants. The `(?is)` flags add case-insensitivity and dotall.
- **File**: `qt/aqt/clayout.py`

## Review signals
- Bug fix -- moderate merge probability. Anki is conservative about Qt-side changes.
- Tiny diff (1 file, 4 lines added, 1 removed).
- No issue number found -- may need to file one before PR.
