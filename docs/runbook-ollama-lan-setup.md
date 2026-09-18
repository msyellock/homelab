# Runbook: Ollama LAN setup (multi-host inference)

## Goal
Let one host send inference requests to Ollama running on another host
over the LAN, instead of every model needing to live on the same
machine.

## Applies to
Any Linux host in the fleet that will host a model for another host to
call. Applied to `ubuntu` and `novo1`; briefly applied to `chromebook`,
since reverted in practice but not in config — see
`docs/decisions/009-llm-council-fleet-distribution.md`.

## Prerequisites
- Ollama installed:
  ```
  curl -fsSL https://ollama.com/install.sh | sudo sh
  ```
- UFW already active per `runbook-ufw-setup.md` (SSH-only baseline)
  before this runbook adds to it — this runbook widens an existing
  firewall, it doesn't set one up from scratch.

## Steps

1. Override Ollama's bind address. By default it only listens on
   `127.0.0.1` — reachable from the host itself, not the network.
   ```
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | \
     sudo tee /etc/systemd/system/ollama.service.d/override.conf
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   ```

2. Open the port — scoped to the LAN subnet, not the wider internet.
   ```
   sudo ufw allow from 192.168.1.0/24 to any port 11434 proto tcp
   ```

3. Pull whichever model this host is responsible for.
   ```
   ollama pull <model>
   ```

## Verification
From the calling host:
```
curl http://<host-ip>:11434
```
Expected: `Ollama is running`

Also confirm the bind address actually changed, not just the config
file:
```
ss -tlnp | grep 11434
```
Expected local address is `*:11434` (or `0.0.0.0:11434`), not
`127.0.0.1:11434`.

## Common failures

- **`0.0.0.0:11434` shows in `ss -tlnp` but a remote `curl` still hangs
  or refuses.** UFW is almost certainly the cause, not Ollama —
  `OLLAMA_HOST` controls what interface the process binds to, UFW
  controls what's actually allowed through. Check `sudo ufw status`
  for the `11434` rule before assuming the service itself is broken.
- **Response times look fine on one host and unusably slow on
  another, for the identical model.** Check `/proc/cpuinfo` for AVX2
  before assuming it's just weaker hardware in the abstract — llama.cpp
  (what Ollama runs under the hood) leans heavily on AVX2/FMA for its
  CPU path. A host without it can be slow enough, specifically under
  JSON-schema-constrained decoding, to look indistinguishable from a
  hang rather than merely "slow." See ADR 009 for a case where this
  actually happened (`chromebook`, no AVX2 at all).

## Notes
Ollama's API has no authentication of its own. Scoping the firewall
rule to `192.168.1.0/24` rather than `Anywhere` is the only thing
standing between "reachable from inside the LAN" and "reachable from
anywhere" — do not widen that rule without reconsidering the tradeoff.
Accepted here under the same single-operator trust model as ADR 007.
