# Shared participation candidate — 2026-11-26

Port of PR #56 HE bench-entry weighting only. PBV1 coupling is deliberately excluded: current V2 rejects simultaneous PBV1/field and the branch must not bypass the personnel-first contract. This candidate does not change the frozen V2 package. With HE explicitly disabled, the bench draw still uses Field.rate. With HE enabled, earlier active-game snap share is used; missing prior active games fall back to rate. Entry and leave weights remain distinct. No forecast scores or calibration runs performed by the author. Verify field hashes, cutoff, entry/exit and replay before grading.


## HE default decision (November 26)

For this new research candidate, current-season bench entry is enabled by default when its player participation path is active. A missing required snap-count artifact is an error, not a silent fallback; a player with no earlier active game still uses the historical rate. The explicit negative flag is the matched ablation control. Frozen pre-existing packages, model identities, and historical results are unchanged. Default selection is an owner-directed candidate policy, not established held-out superiority. Record exact source and artifact hashes; run preflight and compare on/off with identical inputs.

Use `--no-participation-entry-current` with the same snap-count input to isolate HE from the other snap-count updates.
