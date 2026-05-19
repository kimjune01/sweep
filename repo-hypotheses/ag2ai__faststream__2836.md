# ag2ai/faststream#2836 — confluent publish_batch BufferError cascade

## Issue

`KafkaBroker.publish_batch` (confluent backend) opens an `anyio.TaskGroup` and `start_soon`s one `send()` per message. When the batch exceeds librdkafka's `queue.buffering.max.messages` (default 100 000), the overflow `produce()` raises `BufferError` synchronously inside one task. anyio escalates that to a TaskGroup-wide cancel of every sibling. The siblings were awaiting `result_future` from already-enqueued messages; once cancelled, the delivery callbacks fire `set_result` against dead futures → `InvalidStateError` per message. The entire batch is lost despite only one message exceeding capacity.

Reporter cloned faststream + confluent-kafka-python + librdkafka, traced the call chain, and supplied a runnable reproducer and a code sketch. This investigation is mostly verification + adaptation to the maintainer's conventions.

## H₀ — diagnosis already correct

- **Hypothesis**: the BufferError → TaskGroup cancel cascade matches the actual code at `faststream/confluent/helpers/client.py:161-181`.
- **Perturbation**: read `send_batch` in the cloned worktree; trace `produce()` BufferError path.
- **Trajectory**: divergent confirm. `send_batch` is exactly as described — single TaskGroup, no chunking, no per-task error capture. `send()` calls `self.producer.produce()` synchronously; confluent-kafka raises `BufferError` on `QUEUE_FULL`.
- **Edge**: take the reporter's proposed chunking fix.

## H₁ — chunking is the right shape (vs aioresult)

- **Hypothesis A (chunking only)**: pre-split by `queue.buffering.max.messages`, flush between chunks. No new deps. Resolves the reported cascade.
- **Hypothesis B (chunking + aioresult)**: also capture per-task results so a leftover BufferError (e.g. user-configured smaller queue, kbytes overflow) doesn't cascade.
- **Provenance check**: `aioresult` is not currently a faststream dep. Adding it would be scope creep beyond the reported bug. "Go with the flow" → ship chunking only, leave aioresult as a follow-up the reporter already framed as "Further improvement".
- **Kill condition for A**: large messages can still hit `queue.buffering.max.kbytes` before the message count limit. Documented in the reporter's own note. Accepted as out of scope for this PR.

## H₂ — config key access

- **Hypothesis**: `self.config` on `AsyncConfluentProducer` is the producer config dict (set in `__init__` as `config.producer_config`), so `self.config.get("queue.buffering.max.messages", 100000)` is the canonical access.
- **Perturbation**: read `client.py:64`.
- **Trajectory**: convergent. Matches the reporter's trace.

## Fix (shipped)

In `faststream/confluent/helpers/client.py::AsyncConfluentProducer.send_batch`:

```python
async def send_batch(self, batch, topic, *, partition, no_confirm=False):
    max_msgs = int(self.config.get("queue.buffering.max.messages", 100000))
    messages = batch._builder
    for start in range(0, len(messages), max_msgs):
        chunk = messages[start : start + max_msgs]
        async with anyio.create_task_group() as tg:
            for msg in chunk:
                tg.start_soon(self.send, topic, msg["value"], msg["key"],
                              partition, msg["timestamp_ms"], msg["headers"],
                              no_confirm)
        if start + max_msgs < len(messages):
            await self.flush()
```

Minimal change; preserves single-chunk semantics for the common case (batch fits in queue → no flush, identical behavior to today).

## Test

New unit test in `tests/brokers/confluent/test_publish.py` patterned after `test_lazy_logger_proxy.py` (no broker required). Mocks `AsyncConfluentProducer.send` and `flush` and asserts:

1. Single-chunk batches (≤ max_msgs) do not call `flush()`.
2. Multi-chunk batches call `flush()` between chunks (n-1 flushes for n chunks).
3. `send()` is invoked once per message regardless of chunk boundaries.

Master fails (no chunking → no flush calls). Fix passes.

## Frontier

- `queue.buffering.max.kbytes` overflow — not addressed; reporter flagged as known limitation.
- per-task error capture via `aioresult` — separate PR if maintainer wants it.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Cascade root cause | deduction (read code) | 98% |
| Chunking fixes the reported reproducer | induction (matches reporter's measured output) | 92% |
| `queue.buffering.max.messages` default = 100 000 | reference (librdkafka CONFIGURATION.md, stable since 0.9) | 99% |
| aioresult addition is scope creep | abduction (go-with-the-flow, no existing dep) | 80% |
