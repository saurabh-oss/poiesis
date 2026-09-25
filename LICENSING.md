# Licensing

Poiesis is **source-available**, not open source in the OSI sense. Two licences apply,
split by what ends up inside the applications Poiesis builds.

| What | Licence | Where |
|---|---|---|
| The platform: orchestrator, control room, indexer, agent prompts, packs, scripts, site, docs | [Elastic License 2.0](LICENSE) | everything not listed below |
| What Poiesis copies into every generated application: the web-app scaffold, the enterprise kernel and the connectors | [Apache License 2.0](scaffolds/LICENSE) | `scaffolds/` and its copy in `services/orchestrator/scaffolds/` |

## What you may do

**With the platform (Elastic License 2.0):**

- Run Poiesis inside your company, for any purpose, including your company's business.
- Read, modify and redistribute the source, keeping the licence and its notices.
- Build applications with it and use them however you like.

You may **not** provide Poiesis to third parties as a hosted or managed service that gives
them access to a substantial part of its features. Running it for your own organisation is
fine; selling or offering it to others as a service is not.

**With the applications Poiesis generates (Apache License 2.0):** each generated app
carries `POIESIS-SCAFFOLD-LICENSE.txt`. The scaffold parts inside it are Apache-2.0, so you
may use, modify, host and sell the application, including as a service to your own
customers. The Elastic License's hosting limit does not follow the application.

## Third-party components

Poiesis starts other software as separate, unmodified containers. Each keeps its own
licence: PostgreSQL (PostgreSQL License), Qdrant (Apache-2.0), Neo4j Community (GPL-3.0),
Redis (RSALv2/SSPLv1 from 7.4), Grafana, MinIO and Plane (AGPL-3.0), Jaeger and Prometheus
(Apache-2.0), Ollama (MIT). The local models Poiesis pulls are licensed by their authors;
check each model's terms before use.

## Contributing

Contributions are welcome under the [Contributor Licence Agreement](CLA.md), which lets the
project offer your contribution under both licences above and under future commercial
terms. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Commercial use beyond these terms

To offer Poiesis as a service, or for any use these licences do not grant, contact the
maintainer through the repository's issues.
