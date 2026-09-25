# Security

## Reporting a vulnerability

Report it privately through GitHub: the repository's **Security** tab, then **Report a
vulnerability**. Please include what is affected, how to reproduce it, and the impact you
expect. Do not open a public issue.

You will get an acknowledgement within five working days. A fix, or a plan for one, follows
once the problem is confirmed.

## What Poiesis is designed for today

Poiesis is built to run on one trusted machine:

- The control room and the orchestrator API have no sign-in. Keep them on localhost, or put
  them behind a reverse proxy with single sign-on.
- Generated applications are model-written code. They start bound to 127.0.0.1 and are not
  hardened for exposure to a network.
- Generated code runs in throwaway containers with no network by default, capped memory and
  CPU, and a hard timeout. The orchestrator mounts the Docker socket to start them, so
  anyone who controls the orchestrator controls the host's Docker.

Reports about these known limits are still welcome when they show a concrete way to exploit
them.
