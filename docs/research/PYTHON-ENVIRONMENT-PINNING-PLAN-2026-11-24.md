# Plan: one pinned Python environment per runner

Date: 2026-11-24. Status: plan only. Nothing is installed, removed or changed by this document.

## The problem, measured

Three Python stacks run our simulations today:

| where | Python | pandas | numpy | used by |
|---|---|---|---|---|
| this box (vmi2215705) | 3.8.10 | 1.5.3 | 1.24.4 | CEG research, local SLC tools |
| fast host, system Python `/usr/bin/python3.12` | 3.12.3 | 3.1.1 (in `/root/.local`, installed 2026-11-07) | 2.4.4 (`/usr/local`, 2026-05-09) | `run_portable_batch.py` (its `--python` default) |
| fast host, `/root/slc-week1-7/.venv` | 3.12.3 | 3.1.0 | 2.5.4 | the week 1-7 tooling |

Without the `/root/.local` install, the fast host's system Python has no pandas at all. The most likely reason it
was installed: an agent did not find the existing environment and installed its own. No record says which agent.

**Why it matters.** pandas 1.x and 3.x differ in string types, missing-value handling, groupby ordering and copy
rules. A frozen model rebuilt or rerun under another stack can give different numbers with no error. On
2026-11-24 a CEG smoke test gave identical draws on both hosts, but that is one check on one code path, not a
guarantee.

## The plan

1. **One environment per runner, in its own directory.**
   - SLC portable runtime on the fast host: `/root/lp-slc-portable-runtime/.venv`.
   - CEG research: `.venv` in its worktree, or one shared `/root/envs/ceg-research`.
   - No runner uses the system Python or `/root/.local` for its packages.
2. **A pinned requirements file with exact versions and hashes** (`requirements.lock`, `pip install --require-hashes`),
   committed with the runner's code. A frozen model's manifest names the lock file's sha256.
3. **Every run manifest records** the Python executable and version, and the pandas, numpy and pyarrow versions and
   paths.
4. **A preflight that refuses a mismatch.** Before a batch, the runner compares the live versions with the lock file
   and the frozen model's manifest. A mismatch stops the run with a named reason. It never warns and continues.
5. **A cross-host exact-match test** before a host is trusted for a model: the same small run (for example one game,
   few seeds) on the reference host and the new host, and every output compared. Recorded in the manifest.
6. **Agents do not install packages into the system Python or `/root/.local`.** If a package is missing, the agent
   stops and reports which environment it looked in. This rule goes in AGENTS.md on both hosts.
7. **Clean up only after 1 to 6 work.** Then remove the `/root/.local` pandas install, after checking that nothing still
   imports it (Micah's OK first).

## Order of work

1. Write the lock files from the stack the frozen models were validated with. First find which host and stack ran
   each frozen model's validation (the manifests and the CEG Phase 0 reproduction record it); that stack is the one
   to pin.
2. Build the SLC runtime venv on the fast host; run the frozen-pack reproduction (CEG Phase 0 check) inside it; it must
   match the existing results exactly.
3. Add the manifest fields and the preflight to `run_portable_batch.py` and the CEG runners.
4. Add the AGENTS.md rule.
5. Remove the stray install.

Each step needs Micah's OK before anything is installed or removed.
