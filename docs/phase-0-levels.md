# Phase 0 — Levels

Bandit-style. Each level has a **goal** and a **verification** command. If the
verification passes, you've cleared it.

No commands are given. Concepts and man pages only. If you find yourself
searching for "how to X on Ubuntu," you're doing it right — that's the same
thing you did for every Bandit level.

**Hosts**

| Alias | Address | Role |
|---|---|---|
| workstation | 192.168.1.161 | HP, Windows 11 — you work *from* here |
| node01 | 192.168.1.162 | T420s |
| node02 | 192.168.1.160 | B590 |
| svc01 | 192.168.1.153 | Chromebook |

---

## Level 0 → 1: Reach every host

**Goal.** Open an SSH session to all three Linux hosts from the workstation,
using passwords. Confirm each one is reachable and you know its username.

**Verification.** On each host, after connecting:

```
hostname && whoami
```

**Traps.** These are laptops. A closed lid suspends them — you fix that at
Level 6, so until then keep them open. If a connection is *refused*, something
answered and said no. If it *times out*, nothing answered. Those are different
problems.

---

## Level 1 → 2: Generate a keypair

**Goal.** Create an SSH keypair on the workstation. Nowhere else. Understand
which half is secret and which half you hand out.

**Verification.** Two files exist in your `.ssh` directory. One ends in
`.pub`. Read both. One should look like something you'd paste into a chat
window; the other should not.

**Concepts.** Public-key cryptography — what makes it asymmetric, and why that
means you can safely publish half of it. `man ssh-keygen`, particularly the
`-t` flag and what algorithms it accepts.

**Questions.** Why is ed25519 generally preferred over RSA now? What does the
passphrase protect against, given the key file is already on your own machine
— and what does it *not* protect against?

**Traps.** If a keypair already exists, do not blindly overwrite it. Anything
that trusts the old key stops working the moment you do.

---

## Level 2 → 3: Install the key on one host

**Goal.** Connect to `node02` without typing a password.

**Verification.**

```
ssh node02-address-here
```

connects with no password prompt.

**Concepts.** What `~/.ssh/authorized_keys` is, what format it expects, and
what permissions SSH demands on it. `man sshd` under AUTHORIZED_KEYS FILE
FORMAT.

**Questions.** You met this in Bandit 13 from the client side — SSH refused a
key whose permissions were too open. The server has the same rule about
`authorized_keys`. Why does the *server* care who else can write that file?
What could someone do if they could?

**Traps.** `ssh-copy-id` exists on Linux and macOS and does this in one
command. **Windows does not ship it.** You'll need to move the public key
across and append it yourself — which means understanding what the file is
rather than trusting a helper. That's not a disadvantage.

Append, do not overwrite. And `>` versus `>>` matters here in a way that will
cost you real time if you get it wrong.

---

## Level 3 → 4: Install on the remaining hosts

**Goal.** Passwordless connection to all three.

**Verification.** Three connections, no prompts.

**Questions.** Same key on all three, or a key per host? What's the argument
each way? What happens when you need to revoke access to one machine?

---

## Level 4 → 5: Stop typing addresses

**Goal.** Connect using short names instead of IPs and usernames.

**Verification.**

```
ssh node02
```

works, with no user, no address, no port.

**Concepts.** `man ssh_config`. Look at `Host`, `HostName`, `User`, and
`IdentityFile`.

**Questions.** This file lives on the client. Why there and not on the server?
What else can it set — and is there anything in it that would have saved you
time earlier in this list?

---

## Level 5 → 6: Close the password door

**Goal.** Password authentication disabled on all three hosts. Keys only.

**Verification.** From the workstation:

```
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no node02
```

This should be **rejected**. If it prompts for a password, you haven't
finished.

**Concepts.** `/etc/ssh/sshd_config`. `man sshd_config` — read
`PasswordAuthentication`, and check whether other directives in the same file
can override what you set.

**Traps.** This is the level that can lock you out. Before you restart the SSH
service, think about what you'd do if the new config were wrong — and note
that these machines are in the same room as you, which is the only reason this
is survivable.

Reloading a config and restarting a service are not the same thing. Know which
one you're doing and what happens to your current session.

**Questions.** Modern Ubuntu often ships a `sshd_config.d` directory whose
contents load *after* the main file. If you edit the main file and nothing
changes, that's why. What does that tell you about how config precedence
works, and where else you'll meet the same pattern?

---

## Level 6 → 7: Survive a closed lid

**Goal.** Closing the lid on any node does not suspend it or drop your SSH
session.

**Verification.** SSH in, close the lid, wait a minute, run a command in the
still-open session. It should respond.

**Concepts.** `man logind.conf`. Look at the several `HandleLidSwitch`
variants and work out why there is more than one.

**Questions.** Which variant applies when the machine is on AC power versus
battery, and docked versus not? Which one do you actually need? And after
editing, what has to happen for the change to take effect — is a reboot
required, and if not, what is?

---

## Level 7 → 8: Close the ports

**Goal.** A firewall active on each host, allowing SSH and nothing else.

**Verification.**

```
sudo ufw status verbose
```

Active, default deny incoming, one allow rule.

**Concepts.** `man ufw`. Understand default policies before you touch
individual rules.

**Traps.** Enabling a default-deny firewall over SSH is a classic way to
disconnect yourself permanently. Work out the ordering that makes this safe
*before* you enable anything.

**Questions.** UFW is a front end. What is it a front end *to*? What's
actually enforcing the rules? Worth knowing, because the thing underneath is
what you'll meet in job descriptions.

---

## Level 8 → 9: Name the machines

**Goal.** Hostnames changed to `node01`, `node02`, `svc01`.

**Verification.**

```
hostnamectl
```

reports the new name, and it survives a reboot.

**Concepts.** `man hostnamectl`. Note the distinction between static, pretty,
and transient hostnames.

**Traps.** There is a second file that also needs to agree, and if it doesn't,
`sudo` may hang for several seconds on every command. Find out which file and
why the mismatch causes that specific symptom — the reason is more interesting
than the fix.

---

## Level 9 → 10: Names, not numbers

**Goal.** Every host can reach every other host by name.

**Verification.** From `node02`:

```
ping -c1 node01
ssh node01
```

**Concepts.** `/etc/hosts` and how name resolution is ordered. Look at
`/etc/nsswitch.conf` and the `hosts:` line.

**Questions.** You already solved this on the client side at Level 4 with
`ssh_config`. Why isn't that enough? What's the difference between a name your
SSH client understands and a name the whole system understands?

**Trap.** You'll be editing the same file on three machines with the same
content. Notice how tedious that is. Hold onto the feeling — it's the entire
argument for Phase 1.

---

## Level 10: Prove it

**Goal.** Everything above is recorded in the repo.

**Verification.**

- `docs/hosts.md` — updated hostnames, all checkboxes ticked
- `docs/ssh-setup.md` — a runbook someone else could follow
- `docs/decisions/` — one ADR for a choice you made along the way

**Questions.** Could you rebuild any one of these machines from what you
wrote? If not, the runbook isn't finished. That's the standard — not "did I
write something down."

---

## Clearing conditions

Phase 0 is complete when:

- [ ] Three hosts reachable by short name from the workstation
- [ ] No passwords typed for SSH, anywhere
- [ ] Password authentication rejected on all three
- [ ] Firewalls active, SSH only
- [ ] Lids close without consequence
- [ ] Hostnames renamed and surviving reboot
- [ ] Hosts resolve each other by name
- [ ] Documented and committed

Then Phase 1, where you find out that everything you just did by hand three
times can be described once.
