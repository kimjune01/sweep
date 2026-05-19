# Hypothesis Graph: mattgodbolt/xania#306 — NAWS misparsed when 255 byte present

## Issue
RFC 1073 NAWS subnegotiation requires any data byte of value 255 to be doubled (escaped) to disambiguate from the IAC byte. `TelnetProtocol::on_subcommand` (src/doorman/TelnetProtocol.cpp:113) ignores this. Two concrete bugs reported:

1. **NAWS width/height misdecoded.** A 255×80 window arrives as `IAC SB NAWS 0 255 255 0 80 IAC SE`. Current code reads `body[0..3] = {0, 255, 255, 0}` → width=255, height=65280.
2. **Subneg end falsely detected.** `std::search(body, IAC_SE)` finds the literal byte-pair `{255, 240}` even when the 255 is an escaped data byte (the next byte just happens to be 240 = `SE`). Example: `IAC SB NAWS 255 255 0 240 IAC SE`. The search hits at offset 1 (`255 240`), truncating body to `{255}`, dropping the real payload.

## H₀ — Read the code, the bugs are present as described

- **Mode**: deduction (read the source).
- **Perturbation**: read src/doorman/TelnetProtocol.cpp lines 113–141.
- **Trajectory**: divergent-confirming.
  - `iac_se_it = std::search(body.begin(), body.end(), {IAC, SE})` — line 118. No escape awareness.
  - `body[0..3]` decoded as raw bytes — lines 132–135. No unescape.
- **Confidence**: 99% (the code is right here).
- **Kill condition**: none — both bugs as reported.

## H₁ — Existing tests do not cover escaped 255

- **Mode**: induction (grep + read test file).
- **Perturbation**: read src/doorman/test/TelnetProtocolTest.cpp window-size cases.
- **Result**: only `0, 80, 0, 40` and `0x12, 0x34, 0x45, 0x56` are tested — neither contains 255.
- **Trajectory**: divergent-confirming. No existing coverage. New tests will fail-on-master / pass-on-fix.

## H₂ — Fix shape: unescape body before SE-search and before NAWS decode

- **Mode**: abduction → deduction.
- **Proposal**: replace the `std::search` + raw indexing with a single scan that walks `command_sequence` from the option byte onward, copying bytes into an `unescaped` buffer, treating `IAC IAC` as a single literal 255, and stopping on unescaped `IAC SE`. NAWS then reads `unescaped[0..3]`. TTYPE reads `unescaped.substr(1)` as before.
- **Return value**: total bytes consumed from the original input (must account for doubled IACs and the terminating IAC SE).
- **If terminator not found**: return 0 (need more data), matching existing semantics.
- **Other IAC-prefixed bytes inside a subneg**: RFC 854 reserves them for embedded telnet commands. The existing code doesn't handle them either; preserve that — pass through the second byte literally and keep scanning. This matches "go with the flow" — minimal change.

## H₃ — fail-on-master / pass-on-fix tests

Two new test cases:
- `NAWS with escaped 255 width`: `IAC SB NAWS 0 255 255 0 80 IAC SE` → `on_terminal_size(255, 80)`. Master: gets `(255, 65280)`. Fix: passes.
- `NAWS with 255 followed by 240 in payload`: `IAC SB NAWS 255 255 0 240 IAC SE` → `on_terminal_size(65280, 240)`. Master: search collapses at offset 1, decodes garbage / fails length check. Fix: passes.

## Plan

1. Rewrite `on_subcommand` (src/doorman/TelnetProtocol.cpp:113-141) to scan with IAC-doubling awareness.
2. Add the two tests in src/doorman/test/TelnetProtocolTest.cpp under "window sizes".
3. Verify the existing TTYPE / NAWS tests still pass (no 255 bytes, behavior identical).

## Frontier

- TTYPE payloads with embedded 255: theoretically possible but practically nonexistent (terminal-type strings are ASCII). Same fix benefits TTYPE automatically since unescape happens before the substring is extracted.
- `interpret_iacs()` (line 35) treats IAC IAC as a 2-byte no-op outside subneg context — leave it.
