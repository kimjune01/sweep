"""Substrate gates — fabrication-resistant verification rules.

Modules in this package define WHAT a valid attestation looks like.
The producer modules (sweep.attestation_writer, sweep.activities.qa)
do NOT import from here. If they did, a future agent reading the
producer could learn the gate's shape and synthesize stdout that
passes it without running the test.

Visibility = gameability. Read this package only from gate-side
code (sweep.activities.submit, sweep.activities.respond).
"""
