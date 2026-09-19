# Runbook: llama.cpp servers on the Note 10+ (Termux)

Turns a spare Samsung Galaxy Note 10+ 5G (`SM-N976V`, Verizon) into the LLM council's
inference node — see `decisions/009-llm-council-fleet-distribution.md` and the
"LLM inference node" section of `hosts.md`. Everything is driven from the
workstation. **No secrets belong in this repo:** API keys and SSH keys live in
`~/.config/council/` and `~/.ssh/` on the workstation and in files on the phone.

## 0. Constraints of this particular phone

- Verizon variant: bootloader **locked**, no root. Everything below works as the
  unprivileged adb `shell` user (uid 2000) or inside Termux.
- Snapdragon 855: NEON with dot-product, no `i8mm`/SVE, no usable NPU. CPU inference only.
- 12 GB RAM, one model at a time per server. Two servers at once share CPU and
  memory bandwidth (each runs at about 60–65% of solo speed), i.e. effectively serialized.

## 1. Reach the phone over Wi-Fi (adb)

Developer options -> Wireless debugging -> "Pair device with pairing code". From the workstation:

```
adb pair <phone-ip>:<pairing-port> <pairing-code>     # one-time code, port differs from the connect port
adb connect <phone-ip>:<connect-port>                 # the port shown on the main Wireless debugging screen
```
Wireless debugging switches itself off after a reboot or a Wi-Fi change, and the connect
port changes; re-pair when that happens. With USB attached first, `adb tcpip 5555` is
the alternative (it also resets on reboot).

## 2. Remove what isn't needed (reversible)

```
adb shell pm uninstall -k --user 0 <package>          # hides the app for the user; the system partition is untouched
adb shell cmd package install-existing <package>      # undo, or factory-reset the phone
```
About 190 packages were removed this way (Verizon and Samsung consumer apps, Knox/MDM,
Google Play Store and Play services). Batch in groups of ~40 and reboot between batches;
keep the launcher, SystemUI, Settings, telephony core, network stack, Wi-Fi, permission
controller and package installer. Confirm after each batch: boots, SystemUI is up,
Wi-Fi associates, `ping` works.

## 3. Termux and keeping it alive

Install the arm64 APK from the official GitHub release (check its SHA-256 against the
published sums file), then open it once so it unpacks its bootstrap:

```
adb install -r termux-app_<version>+github-debug_arm64-v8a.apk
```
Stop Android from killing Termux's child processes (phantom-process killer) and doze from
freezing it:

```
adb shell "device_config set_sync_disabled_for_tests persistent"
adb shell "device_config put activity_manager max_phantom_processes 2147483647"
adb shell "settings put global settings_enable_monitor_phantom_procs false"
adb shell "dumpsys deviceidle whitelist +com.termux"
```
The GitHub build is debuggable, so `adb shell run-as com.termux ...` can run commands as
Termux; once `sshd` is set up (step 5) use SSH instead.

## 4. Build llama.cpp for this CPU

The prebuilt Termux `llama-cpp` package works but is generic; building from source with
explicit flags was 2.3x faster on prompt processing and about 27% faster on generation.
In Termux: `pkg install cmake clang git make ninja`, clone `ggml-org/llama.cpp`, then:

```
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF \
  -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 -DLLAMA_CURL=OFF -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TOOLS=ON
cmake --build build -j5 --target llama-bench llama-cli llama-server
```
(about 15–20 minutes). Don't rely on `-DGGML_NATIVE=ON` here: big.LITTLE detection is
unreliable. Run binaries with `LD_LIBRARY_PATH=$PWD` from `build/bin`.

## 5. Key-only SSH into Termux

`pkg install openssh`, put the workstation's dedicated public key in `~/.ssh/authorized_keys`,
and set `PasswordAuthentication no`, `PubkeyAuthentication yes`, `Port 8022` in
`$PREFIX/etc/ssh/sshd_config`. Start it with `sshd`; connect as the Termux user
(`ssh -p 8022 -i <key> <user>@<phone-ip>`). Only a single-purpose key should be authorized.

## 6. Models and servers

GGUF Q4_K_M files from Hugging Face (verify the byte size against the `content-length` header):
Gemma 2 2B (about 1.7 GB) and Llama 3.2 3B (about 2.0 GB). One start script per server, chmod
700, with the key read from a file, not typed on a command line:

```
cd ~/llama.cpp/build/bin && export LD_LIBRARY_PATH=$PWD:$PREFIX/lib
exec ./llama-server -m ~/models/<model>.gguf -t 4 -c 2048 -np 1 --jinja \
  --host 0.0.0.0 --port <8080|8081> --api-key "$(cat ~/.llama_key_<port>)" -a <alias>
```
`-c 2048` (not 4096) leaves about 400 MB more free RAM across two servers and the council's
prompts fit. Launch detached: `setsid nohup ~/start-....sh >/dev/null 2>&1 </dev/null &`.
Verify from the workstation: `curl -H "Authorization: Bearer $KEY" http://<phone-ip>:<port>/v1/models`
returns 200, and without the header returns 401. The council reads the keys from
`~/.config/council/llama-server-<ip>-<port>.key` (mode 600) on the workstation.

## 7. Gotchas

- Servers and `sshd` do not survive a phone reboot; restart them from the start scripts.
- Inside an SSH command, `pkill -f llama-server` matches the SSH shell's own command line and
  kills the session. In Termux `pgrep -x` matches nothing; use `pgrep llama-server`, or
  select by `--port` with `ps`.
- Some models cannot initialize llama.cpp's JSON-grammar sampler (`Failed to initialize
  samplers`), which the council's schema-constrained calls need: Phi-3.5-mini is one.
- Sustained inference heats the phone, especially while it charges. A 35-minute run at 4
  threads on USB charging reached battery 45.8 °C / CPU 64 °C. Pause long runs above about
  42 °C battery and let it cool; Android's own throttle (thermal status) does not engage
  before that.
- Android has no firewall: the API key is the only gate on ports 8080/8081.
