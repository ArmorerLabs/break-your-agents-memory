# Product Brief: Edge Assistant, v2

The edge assistant v2 focuses on one goal: the launch demo is the on-device
flow, running fully offline. The latency target is 80 ms at p95 for the
full pipeline, measured on the reference hardware.

v1 shipped the cloud-sync flow; v2 keeps it as a fallback. The demo script
walks through on-device parsing, then memory recall, then the summary.
