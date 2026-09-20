# CoDE project workflow

- This directory is the canonical workspace for the user's CoDE-Stop reproduction and related research. Keep older reasoning experiments outside this project.
- GitHub destination: https://github.com/Ericzhy0716/CoDE, default branch `main`. The user has authorized ongoing synchronization of relevant code and documents. Commit and push meaningful, verified changes when completing related work; preserve remote history and do not force-push.
- Keep `upstream/CoDE-Stop` as the pinned original reference. Put our implementations or patches in `src/` and `scripts/`, and document differences from the paper and upstream code.
- Never stage model weights, credentials, machine-specific authorization, raw datasets, or unreviewed run output. Put raw output in ignored `runs/`; share curated reports in `results/`.
- Use `docs/CODESTOP_NOVELTY_ASSESSMENT_20260920.md` for current research scope, and the reproduction requirements document for technical setup. Do not describe static checks, planned work or offline replay as completed GPU experiments or measured online speedups.
