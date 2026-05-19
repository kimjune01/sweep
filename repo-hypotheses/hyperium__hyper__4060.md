# Hyperium/hyper#4060 — Memory leak when forwarding `Response` h2→h1

**Issue**: When proxying H2-listener → H1-upstream, forwarding the `Response<_>` returned from the H1 client into the H2 server causes the resident set to grow without bound. The user's workaround — `parts.headers.drain()` followed by `HeaderValue::from_bytes(value.as_bytes())` for every value — fixes the leak immediately. No other listener/upstream combination leaks at the same magnitude.

## H₀ — Baseline observation

- **Hypothesis**: Memory growth is allocator fragmentation, not a real leak.
- **Perturbation**: User compared malloc vs jemalloc, single-arena jemalloc, captured under heaptrack on Fedora.
- **Result**: All allocators behave identically. Growth visible at heaptrack node `HeaderMap::try_reserve_one`, with smaller-but-present growth in pure h2 and even h1→h1.
- **Trajectory**: **Divergent against null** — the leak is structural in hyper, not allocator-side.
- **Edge**: Why does re-allocating each `HeaderValue` cure it? → H₁.

## H₁ — Shared `Bytes` from h1 parse pins the upstream connection read buffer

- **Reasoning mode**: deduction (read the parsing path).
- **Provenance**:
  - `src/proto/h1/role.rs:1070` — `let mut slice = buf.split_to(len);`
  - `src/proto/h1/role.rs:1083` — `let slice = slice.freeze();`
  - `src/proto/h1/role.rs:1107` — `let value = header_value!(slice.slice(header.value.0..header.value.1));`
  - `src/proto/h1/role.rs:47-52` — `header_value!` expands to `HeaderValue::from_maybe_shared_unchecked($bytes)`.
- **Mechanism**: Every parsed h1 response's `HeaderValue` is a `Bytes` slice into the same frozen chunk derived from the connection's `BytesMut` read buffer. `BytesMut::split_to` shares the underlying `Vec` allocation between the split-off `Bytes` and the remaining buffer via the internal ref-count. Until **every** slice from a given allocation is dropped, that allocation cannot be returned to the allocator.
- **Trajectory**: **Divergent for** — explains why a fresh `HeaderValue::from_bytes` copy fixes it (the copy doesn't reference the shared `Vec`).
- **Kill condition**: the user's workaround would not work if the leak source were elsewhere. It does work. Convergent.

## H₂ — h2's HPACK encoder dynamic table is what keeps the slices alive

- **Reasoning mode**: deduction (read the h2 crate).
- **Provenance** (h2 v0.4.14):
  - `src/hpack/header.rs:11-20` — `Header::Field { name, value: HeaderValue }` stored by value.
  - `src/hpack/encoder.rs:77` — `let index = self.table.index(header);` for each header on each response.
  - `src/hpack/table.rs:240, 305, 343` — non-sensitive headers are inserted into the dynamic table via `slots.push_front(Slot { hash, header, next })`.
  - Default dynamic table capacity: `Encoder::default() = Encoder::new(4096, 0)`.
- **Mechanism**: When hyper hands the H1-parsed `HeaderMap` to h2's `send_response`, h2 iterates each header into the HPACK encoder, which **inserts the `Header { value: HeaderValue }` into its dynamic table by value**. The `HeaderValue` still owns its `Bytes` handle, which still ref-counts hyper's h1 read buffer. The dynamic table evicts only when the encoder's *encoded-size* (per RFC 7541) exceeds 4096 bytes; in practice, response headers per connection often stay under that limit, so entries linger for the lifetime of the h2 connection.
- **Why H1→H1 doesn't leak as much**: hyper's h1 *write* path (`encode_headers`) does not maintain a long-lived structure that owns the `HeaderValue`s after the bytes are serialized. The HeaderMap is consumed once and dropped.
- **Why H1→H2 doesn't leak**: when the upstream is H2, headers entering the proxy were decoded by h2's HPACK *decoder* from h2's own framed buffers (allocated per-frame, smaller, and short-lived once decoded). The pin point is "where the `HeaderValue`'s `Bytes` originates," and h2-decoded values don't tie back to a long-lived connection read buffer in the same way.
- **Why H2→H2 doesn't leak**: same as above — the upstream `HeaderValue`s never reference a hyper-style h1 read buffer.
- **Trajectory**: **Convergent** — accounts for every cell in the four-way table the user reported.

## H₃ — Why the leak grows over time on a persistent upstream

- **Reasoning mode**: deduction.
- **Mechanism**: With keepalive on the h1 upstream connection, `buf: BytesMut` is reused across many responses. Each request the response is sliced off via `split_to(len).freeze()`. Both halves continue to share the original `Vec` allocation; once `buf` runs out of capacity it allocates a fresh `Vec` (`BytesMut` grow path) — but the prior `Vec` is kept alive by any still-cached `HeaderValue` in the downstream h2 HPACK table. Across N requests, each new buffer allocation N is pinned by any HPACK entry surviving from any prior request whose value is sliced from that buffer. The growth is bounded by HPACK table churn but unbounded in the worst case (small, highly varied header values that miss the HPACK table cache repeatedly while still landing in dynamic entries).
- **Kill condition predicted**: if you cap the h2 HPACK encoder dynamic table to size 0 (force "no indexing"), the leak should disappear *without* the user's workaround. (Not yet run — frontier edge.)

## H₄ — Why the user's `HeaderMap` growth visible at `try_reserve_one`

- **Reasoning mode**: abduction (lower confidence).
- The user observes in heaptrack that the leaking allocations are flagged at `HeaderMap::try_reserve_one`. That is the function inside the `http` crate that allocates the hash table slot for a new entry. The growth there is real but **secondary** — what's leaking is the *backing* `Bytes` ref-count holding the read buffer alive. The `HeaderMap` itself is the entry point through which the live `HeaderValue` is reachable; heaptrack reports the allocation site that's still resolvable, not the upstream pinning ref.
- **Confidence**: 65%. Could also indicate small-scale leakage in the http crate's `HeaderMap` growth path (the smaller h1→h1 leak the user later noticed). Not investigated.

## Provenance

- `slice.slice(range)` pattern dates back to the initial h1 parser rewrite — deliberate zero-copy design choice. Not an accident, not a regression.
- `header_value!` macro and `from_maybe_shared_unchecked` are explicit performance optimizations; the safety contract is that bytes were already validated by httparse, so the `_unchecked` is sound.
- No prior issue on hyperium/hyper specifically calls out this h2-encoder-pins-h1-read-buffer chain (search: "HeaderValue leak", "HeaderMap leak", "shared bytes"). Adjacent: hyperium/h2 has had several HPACK encoder size discussions but none about value lifetime.

## Where the fix belongs

This is a **two-crate structural issue**. Three plausible fixes, in increasing order of disruption:

1. **In h2's HPACK encoder** (recommended): when inserting a `Header` into the dynamic table, copy its `value` bytes into a freshly-owned `Bytes`. The HPACK table is supposed to own its own state anyway, and the table is bounded (default 4096B), so the copy cost is bounded per-insert and one-shot. This contains the fix to a single function in `h2/src/hpack/table.rs::insert` (or earlier, in `index`) and leaves hyper's zero-copy parsing intact.
2. **In hyper's h1 parser**: replace `header_value!(slice.slice(range))` with `HeaderValue::from_bytes(&slice[range])` in `role.rs`. Cures the leak universally but loses zero-copy for every h1 response, regardless of whether it's forwarded to h2. Performance regression on the common non-proxy case is real.
3. **In hyper's docs/example**: document the pinning behavior in the proxy example and recommend the user's workaround. Cheap but pushes the cost onto every proxy author.

Fix (1) preserves hyper's zero-copy design and fixes the leak for every downstream consumer of h2's encoder, not just hyper proxies. It's also the most defensible patch (a one-function change in the crate whose abstraction is actually being violated).

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| h1 parse uses shared `Bytes` for header values | Deduction (read code) | 99% |
| h2 HPACK encoder caches `HeaderValue` by value | Deduction (read code) | 99% |
| The chain explains the four-way table | Deduction + induction (user's experiments) | 95% |
| HPACK fix is the cleanest spot | Abduction | 75% |
| `try_reserve_one` heaptrack frame is secondary | Abduction | 65% |

## Frontier edges (not run)

- **E1**: Set the h2 encoder dynamic table size to 0 on the h2 server side and rerun the user's reproduction. Prediction: leak vanishes without the `HeaderValue::from_bytes` workaround. Decisive for H₃.
- **E2**: Patch h2's `table.rs::insert` to deep-copy `value` bytes, run the user's repro. Prediction: leak vanishes; throughput unchanged within noise.
- **E3**: Quantify the per-response pinned-bytes upper bound as a function of HPACK table size and average header-value length.

## Disposition

This is a **diagnostic report, not a PR**. The fix belongs in `hyperium/h2`, not `hyperium/hyper`. The right move is to post a tissue-style comment on issue #4060 explaining (a) the user's observation is correct and not a misconfiguration, (b) the root cause is h2's HPACK encoder retaining `HeaderValue` references that pin hyper's h1 read buffer, and (c) the recommended fix location is the h2 crate. Defer to maintainers on whether they want a separate h2 PR or a hyper-side workaround.

## Pruning log

- Allocator-fragmentation hypothesis: killed by user's malloc-vs-jemalloc check.
- "Body stream leaks": ruled out by user's own profiling before filing.
- "HeaderMap hash table leak": demoted to secondary (H₄) — fixing the value pin should drain the apparent leak at `try_reserve_one`.
