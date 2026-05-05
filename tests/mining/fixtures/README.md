# Mining test fixtures

`gateway_metrics_sample.txt` is captured Prometheus output from a real
Pearl gateway run against the pinned Pearl ref. Re-capture by:

1. Run the Pearl Docker image on an H100 host per the spec §7.4 launch shape.
2. `curl http://127.0.0.1:8339/metrics > gateway_metrics_sample.txt` once
   the gateway is healthy and at least 10 shares have been submitted.
3. Strip any cardinality bombs (per-prompt or per-block-time histograms)
   that bloat the file.
4. Commit, citing the Pearl commit/tag the capture was taken against.

If Pearl renames metrics, update `mining/_metrics.py::PROM_*` constants and
re-capture.
