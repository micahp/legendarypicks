# SLC-v2 D1 10,000-seed run

Run: BUF–MIN, seeds 200001–210000. The run manifest records SLC-v2 enabled with Model D1 and RNG v2. The base CLI profile is named v1_full_stack; the run's recorded profile is v1_full_stack+slc-v2. Source commit: 8a5d809ffaec720b3d7b8ddb487f33c55e5d0d0e.

The run completed 10,000 requested seeds. The compact renderer classified 9,991 as valid full games and 9 as simulation/validation errors. All nine full failure records are included. The per-seed compressed CSV retains all 10,000 seed outcomes and validity flags. The rendered team, player, quarter, and drive summaries use the valid complete-game box scores.

The frozen BUF–MIN snapshot was taken at 2026-11-09T20:28:32Z, before roster finalization. The run manifest records it as valid before roster finalization. This timing does not invalidate completed games. Player game-day eligibility remains unknown. The manifest also notes that the snap-count input was acquired after the snapshot; that is an input-provenance note, not a game-validity failure.

The 439 MB original worker directory remains on the fast host at /root/ot-sim-out/slc-v2-model-d1-10k-2026-11-10/workers. Its compressed artifact hashes are in inputs/manifest.json. This GitHub bundle keeps the compact per-seed results, rendered summaries, all failure replays, logs, and frozen small inputs. No individual bundled file exceeds 50 MB.
