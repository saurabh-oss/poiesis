# Contributing to Poiesis

Thank you for helping. Issues, sample briefs, packs, connectors, prompt improvements and
fixes are all welcome.

## Before you start

- **Licence.** Poiesis is source-available under the Elastic License 2.0; the scaffold
  copied into generated apps is Apache-2.0. See [LICENSING.md](LICENSING.md).
- **Contributor Licence Agreement.** Every pull request needs the [CLA](CLA.md). Tick the
  box in the pull request template; a check blocks the pull request until it is ticked.
- **Big changes.** Open an issue first, so we can agree the approach before you spend time
  on it.

## Setting up

Follow [docs/SETUP-WINDOWS.md](docs/SETUP-WINDOWS.md), then
[docs/FIRST-RUN.md](docs/FIRST-RUN.md). [docs/OPERATIONS.md](docs/OPERATIONS.md) lists the
self-tests.

## Making a change

1. Branch from `main`.
2. Keep the platform's copies in step: `packs/` and `scaffolds/` are mirrored under
   `services/orchestrator/` for the image.
3. Run the self-tests that cover what you touched:
   ```bash
   docker compose exec orchestrator python -m app.selftest_core
   docker compose exec orchestrator python -m app.selftest_enterprise
   ```
4. Explain in the pull request what changed and how you verified it. For a change to what
   generated apps look like or do, include a run id or screenshots.

## Where things live

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains the design;
[docs/AGENTS.md](docs/AGENTS.md) what each agent reads and produces;
[docs/CHECKS.md](docs/CHECKS.md) how an increment is verified. Agent behaviour is usually
changed in `services/orchestrator/app/agents/prompts/`, not in code.

## Reporting a security problem

Do not open a public issue. See [SECURITY.md](SECURITY.md).
