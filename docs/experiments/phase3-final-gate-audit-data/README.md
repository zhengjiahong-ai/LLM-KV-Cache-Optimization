# Phase 3 final gate audit data

This directory is a read-only derivative of the immutable Option F execution
archive. `gate-ledger.json` is the entry point. `nec-cells/` contains the 40
independent N/E/C reports. Files prefixed with `algorithm-` are the frozen
algorithm-exposure audit derivatives. `sha256-manifest.txt` binds every file.

The retrospective checks do not alter historical authorization or evidence.
In particular, `G1.execution_time_status` remains
`NOT_RECORDED_BEFORE_MAIN`, and the observed enqueue-order mismatch remains a
fail-closed result pending M1/M4 adjudication.
