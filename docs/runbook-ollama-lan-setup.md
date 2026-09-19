# Runbook: Ollama LAN setup (multi-host inference)

## Goal
Let one host send inference requests to Ollama running on another host
over the LAN, instead of every model needing to live on the same
machine.

## Applies to
Any Linux host in the fleet that will host a model for another host to
call. Applied to `ubuntu`, `novo1` and (briefly) `chromebook`. As of
2026-09-19 it is still in place only on `ubuntu` (the council's fallback
host); it was removed from `chromebook` and from `novo1` — see "Undoing this
runbook" below and
`docs/decisions/009-llm-council-fleet-distribution.md`. The council's main
inference now runs on the Note 10+ instead (`runbook-note10-llama-server.md`).

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

## Undoing this runbook
Used on `chromebook` and `novo1` to return them to the SSH-only baseline
(check `ollama list` and note the model sizes first, and make sure nothing
still points at the host):
```
sudo systemctl disable --now ollama
sudo rm -f /etc/systemd/system/ollama.service \
  /etc/systemd/system/ollama.service.d/override.conf
sudo rmdir /etc/systemd/system/ollama.service.d
sudo systemctl daemon-reload
sudo rm -f /usr/local/bin/ollama
sudo rm -rf /usr/local/lib/ollama /usr/share/ollama     # binary libraries and downloaded models
sudo ufw delete allow from 192.168.1.0/24 to any port 11434 proto tcp
sudo userdel ollama; sudo groupdel ollama
```
Then confirm: `systemctl is-active ollama` is `inactive`, nothing shows in
`ss -ltn | grep 11434`, `sudo ufw status` lists only `22/tcp`, and the port is
unreachable from another host. On `novo1` this freed about 3.4 GB of models.

## Notes
Ollama's API has no authentication of its own. Scoping the firewall
rule to `192.168.1.0/24` rather than `Anywhere` is the only thing
standing between "reachable from inside the LAN" and "reachable from
anywhere" — do not widen that rule without reconsidering the tradeoff.
Accepted here under the same single-operator trust model as ADR 007.
