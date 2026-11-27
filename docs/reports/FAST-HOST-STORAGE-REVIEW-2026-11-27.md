# Fast-host storage footprint review

**Host:** vmi3108149.contaboserver.net
**Captured:** 2026-11-27 16:12 UTC (host clock: 17:12 CET)
**Scope:** Read-only filesystem inventory for long-term retention planning. No files were removed, moved, compressed, or rewritten; no services were restarted.

## Capacity snapshot

| Item | Observed |
|---|---:|
| Root filesystem | /dev/sda1, ext4, 96 GiB |
| Used / available | 95 GiB / 1.7 GiB |
| Utilization | 99% |
| Inodes used | 841,089 of 12,976,128 (7%) |
| Visible top-level files from du | about 90 GiB |
| Deleted-but-open file found | 4,362,108,928 bytes (about 4.06 GiB) |

This is a byte-capacity problem, not inode exhaustion. The approximately 5 GiB difference between df and visible du is largely explained by a deleted database still held open by Hermes, plus filesystem metadata and rounding. Ext4 reports zero reserved blocks.

**Important open-file finding:** lsof shows PID 2652045 (hermes) holding the unlinked inode for /root/.hermes/state.db (deleted), size 4,362,108,928 bytes, plus a deleted WAL of about 6 MB. Several file descriptors refer to the same database inode; do not add those repeated entries together. The pathname is already gone, but the space remains allocated while the process holds it. Closing it may reclaim space, but that requires an owner-approved Hermes lifecycle action. No process was touched.

## Filesystem layout

The main persistent volume is mounted at /. It contains /root, /tmp, /usr, /var, and /opt. **/tmp is on the same persistent root filesystem**, so temporary builds and databases there continue to consume the 96 GiB volume. By contrast, /dev/shm is a separate tmpfs; it was about 23 MB used of 5.9 GiB.

| Top-level path | Size | Notes |
|---|---:|---|
| /root | 58 GiB | Repositories/worktrees, run data, databases, caches and agent state |
| /usr | 24 GiB | System and locally installed software |
| /tmp | 4.6 GiB | Temporary builds, worktrees, portable artifacts and SQLite files; persistent on / |
| /var | 3.3 GiB | 2.6 GiB in /var/lib, including about 2.3 GiB of Snap packages; 505 MiB logs |
| /opt | 389 MiB | Installed software |
| /boot | Separate 881 MiB filesystem | 117 MiB used, 702 MiB available |
| /boot/efi | Separate 105 MiB filesystem | 6.2 MiB used |

## Large areas under /root

| Path | Size | Contents observed |
|---|---:|---|
| /root/runs | 13 GiB | Week 11: 9.5 GiB; week 12: 1.0 GiB; shm-archive-20261122: 2.3 GiB |
| /root/ot-sim-out | 7.6 GiB | GPIA inputs/runs and pinned LP/engine worktrees |
| /root/ot-sim-out-archives | 3.4 GiB | Compressed research-run archives |
| /root/prediction-market-trading | 3.3 GiB | About 3.2 GiB under data |
| /root/legendarypicks | 2.3 GiB | About 2.2 GiB under .git objects |
| /root/.cache | 1.5 GiB | Mostly /root/.cache/legendarypicks/slc-fits |
| /root/.local | 1.8 GiB | About 1.3 GiB under .local/share/claude/versions; 185 MiB under uv |
| /root/.codex | 1.3 GiB | About 1.1 GiB under packages |
| /root/gridiron-gpia01 and /root/gridiron-gpia01-run | 1.1 GiB each | Separate Gridiron GPIA workspaces |
| /root/envs | 596 MiB | Python environments |

### Simulation data and repeated artifacts

- **Week 11:** /root/runs/week-11 is 9.5 GiB. Inputs are 8.1 GiB, including an active-looking frozen picks database at 4,193,959,936 bytes, model-build sources at 1.4 GiB, and model-build artifacts at 1.6 GiB. Games use 1.4 GiB.
- **Week 12:** /root/runs/week-12 is 1.0 GiB: games 826 MiB, inputs 181 MiB, plus snapshots, summaries and a small v1-complete folder.
- **SHM archive:** /root/runs/shm-archive-20261122 is 2.3 GiB and contains several roughly 0.5 GiB SQLite histories, including v17 and portable-history variants.
- **GPIA outputs:** /root/ot-sim-out/gpia-01-fullgame is 46 MiB; GPIA snapshots, ratings, participation inputs and playbooks are 55 MiB. The larger database is a sibling file: /root/ot-sim-out/gpia-01-fullgame-inputs-2026-11-26-picks.dev.db at 4,538,216,448 bytes. It was last modified 2026-11-26 20:11 CET.
- **Pinned checkouts:** /root/ot-sim-out has eight LP GPIA worktrees at about 223 MiB each and four Gridiron engine worktrees at about 339–350 MiB each. Their overlap may be intentional for reproducibility; no content-level deduplication was performed.
- **Archives:** /root/ot-sim-out-archives contains 3.4 GiB of tarballs. The largest is week10-family-2026-11-15.tar.gz at 781 MB; several other run archives range from roughly 140–476 MB.
- **Portable/temp builds:** /tmp is 4.6 GiB. Major folders include slc-portable-build (1.1 GiB), slc-portable-artifacts (533 MiB), gridiron-kick-boundary-f1fbfab (350 MiB), slc-v1-week10-parity-20261119 (349 MiB), and slc-engine-v17 (308 MiB). It also contains temporary SQLite files such as h17.db (about 551 MiB).
- **Caches and tools:** /root/.cache/legendarypicks/slc-fits is 1.5 GiB. /usr/local is 17 GiB: about 7.5 GiB in the Hermes agent environment, 5.5 GiB in global Python 3.12, and 3.5 GiB in Ollama libraries. Similar library filenames occur in more than one environment, but package-level identity and runtime use were not audited.
- **Snap packages:** /var/lib/snapd/snaps uses about 2.3 GiB. /var/cache/apt is about 209 MiB.

## Largest individual visible files

| Size | Path |
|---:|---|
| 4.54 GB | /root/ot-sim-out/gpia-01-fullgame-inputs-2026-11-26-picks.dev.db |
| 4.19 GB | /root/runs/week-11/inputs/picks.frozen.db |
| 781 MB | /root/ot-sim-out-archives/week10-family-2026-11-15.tar.gz |
| 558 MB | Several SLC materialized-history SQLite files under week-11 model-build artifacts, shm-archive, and /tmp |
| 476 MB | /root/ot-sim-out-archives/slc-v2-model-d1-10k-2026-11-10.tar.gz |
| 410 MB | /root/ot-sim-out-archives/buf-min-10k-2026-11-09.tar.gz |

The similarly sized SQLite files may be different snapshots or duplicate builds. Their hashes, schema versions and whether they are reproducible were not compared; size alone is not evidence they can be removed.

## Review questions for a long-term policy

1. Which databases are canonical frozen inputs, and which are reproducible materializations or temporary copies? Define retention by source hash, model version and run manifest before deduplicating them.
2. How many week-specific run directories should remain on the fast host? Decide when completed weeks move to compressed archive or external storage, and whether archive contents need a local working copy.
3. Should per-arm worktrees be retained after the experiment is pinned, or can they be rebuilt from exact commits? Keep enough evidence to reproduce results.
4. Which caches are safe to regenerate, particularly slc-fits, portable builds, and tool caches? Confirm cache ownership and rebuild cost first.
5. What retention policy applies to /tmp? It is persistent storage, not a separate temporary volume; clean only after confirming no active consumer and preserving needed evidence.
6. Assign an owner to the deleted-but-open Hermes database. Reclaiming its space requires that process to close the deleted inode; do not remove or restart agent state without that owner’s decision.
7. Review old Snap revisions and duplicated Python/CUDA packages through their package managers rather than deleting library files manually.

This inventory is a review aid, not a cleanup authorization. No hashes were computed for same-sized databases or archive contents, and no candidates were deleted.
