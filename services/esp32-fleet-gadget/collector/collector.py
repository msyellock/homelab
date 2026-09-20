#!/usr/bin/env python3
"""Fleet health collector for the ESP32 'animal monitor' (personal project, NOT part of the homelab repo).
Read-only checks; writes ~/sysmon/status.json. No secrets are stored or printed."""
import json, subprocess, socket, time, datetime, concurrent.futures as cf, os, re

OUT = os.path.expanduser('~/sysmon/status.json')
NOTE10_KEY = os.path.expanduser('~/.ssh/note10_ed25519')
HOSTS = [  # name, animal, kind
    ("illntentpc", "owl", "windows"), ("ubuntu", "ox", "ssh"), ("novo1", "fox", "ssh"),
    ("chromebook", "meerkat", "ssh"), ("Note 10+", "hummingbird", "phone"),
]
LINUX_CMD = r'''
echo up=$(cut -d. -f1 /proc/uptime)
read l1 l5 l15 _ < /proc/loadavg; echo load=$l1; echo cores=$(nproc)
free -m | awk 'NR==2{printf "mem_used=%d\nmem_total=%d\n",$3,$2}'
df -P / | awk 'NR==2{gsub("%","",$5); print "disk_pct="$5}'
t=0; for z in /sys/class/thermal/thermal_zone*/temp; do v=$(cat $z 2>/dev/null); [ -n "$v" ] && [ "$v" -gt "$t" ] && t=$v; done; echo temp=$((t/1000))
[ -f /var/run/reboot-required ] && echo reboot=1 || echo reboot=0
echo kernel=$(uname -r)
echo failed=$(systemctl --failed --no-legend 2>/dev/null | grep -v -E 'not-found|smartd|smartmontools' | wc -l)
echo ssh_ok=$(systemctl is-active ssh 2>/dev/null)
echo ollama=$(systemctl is-active ollama 2>/dev/null)
'''
PHONE_CMD = r'''
echo up=$(cut -d. -f1 /proc/uptime)
read l1 _ < /proc/loadavg; echo load=$l1; echo cores=$(nproc)
free -m | awk 'NR==2{printf "mem_used=%d\nmem_total=%d\n",$3,$2}'
b=/sys/class/power_supply/battery
[ -r $b/capacity ] && echo battery=$(cat $b/capacity)
[ -r $b/temp ] && echo temp=$(( $(cat $b/temp)/10 ))
[ -r $b/status ] && echo charging=$(cat $b/status)
'''
def kv(text):
    d = {}
    for line in text.splitlines():
        if '=' in line:
            k, v = line.split('=', 1); d[k.strip()] = v.strip()
    return d
def num(d, k, cast=float):
    try: return cast(d[k])
    except Exception: return None
def tcp(host, port, t=2):
    try: socket.create_connection((host, port), t).close(); return True
    except Exception: return False
def run(cmd, timeout=25):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def probe_ssh(name):
    r = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", name, "sh -s"], 25) if False else \
        subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", name, "sh"], input=LINUX_CMD, capture_output=True, text=True, timeout=30)
    if r.returncode != 0 and not r.stdout: raise RuntimeError(r.stderr.strip()[:80] or "ssh failed")
    return kv(r.stdout)
def probe_phone():
    r = subprocess.run(["ssh", "-p", "8022", "-i", NOTE10_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                        "u0_a308@192.168.1.167", "sh"], input=PHONE_CMD, capture_output=True, text=True, timeout=30)
    d = kv(r.stdout) if r.stdout else {}
    d["servers_8080"] = tcp("192.168.1.167", 8080); d["servers_8081"] = tcp("192.168.1.167", 8081)
    if not r.stdout and not (d["servers_8080"] or d["servers_8081"]): raise RuntimeError("phone unreachable")
    return d
def probe_windows():
    ps = ("$o=Get-CimInstance Win32_OperatingSystem;$c=(Get-CimInstance Win32_Processor|Measure-Object LoadPercentage -Average).Average;"
          "$d=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\";"
          "$t=$null;try{$z=Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop|Select -First 1;$t=[math]::Round($z.CurrentTemperature/10-273.15)}catch{};"
          "'up='+[int]((Get-Date)-$o.LastBootUpTime).TotalSeconds;'cpu_pct='+$c;"
          "'mem_used='+[int](($o.TotalVisibleMemorySize-$o.FreePhysicalMemory)/1024);'mem_total='+[int]($o.TotalVisibleMemorySize/1024);"
          "'disk_pct='+[int](100-100*$d.FreeSpace/$d.Size);if($t){'temp='+$t}")
    r = run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-Command", ps], 40)
    d = kv(r.stdout.replace('\r', ''))
    d["kernel"] = subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip()
    return d

def assess(kind, d):
    alerts, state = [], "ok"
    cores = num(d, "cores", int) or 1
    load = num(d, "load"); cpu = num(d, "cpu_pct"); temp = num(d, "temp")
    memp = (100 * num(d, "mem_used") / num(d, "mem_total")) if num(d, "mem_total") else None
    disk = num(d, "disk_pct")
    busy = (load is not None and load / cores >= 0.8) or (cpu is not None and cpu >= 80)
    if temp is not None and temp >= 75: alerts.append(f"hot {temp:.0f}C"); state = "hot"
    if disk is not None and disk >= 85: alerts.append(f"disk {disk:.0f}%")
    if memp is not None and memp >= 92 and kind != "phone": alerts.append(f"memory {memp:.0f}%")
    if d.get("reboot") == "1": alerts.append("reboot pending")
    if num(d, "failed", int): alerts.append(f"{d['failed']} failed unit(s)")
    if kind == "ssh" and d.get("ssh_ok") not in (None, "active"): alerts.append("ssh down")
    if kind == "phone":
        if not d.get("servers_8080"): alerts.append("gemma server down")
        if not d.get("servers_8081"): alerts.append("llama server down")
        if temp is not None and temp >= 42: alerts.append(f"battery {temp:.0f}C")
    if state == "ok" and alerts: state = "warn"
    if state == "ok" and busy: state = "busy"
    return state, alerts, memp

def collect_one(h):
    name, animal, kind = h
    t0 = time.time()
    try:
        d = probe_windows() if kind == "windows" else probe_phone() if kind == "phone" else probe_ssh(name)
        state, alerts, memp = assess(kind, d)
        return {"name": name, "animal": animal, "state": state, "alerts": alerts,
                "uptime_h": round(num(d, "up") / 3600, 1) if num(d, "up") is not None else None,
                "load": num(d, "load"), "cpu_pct": num(d, "cpu_pct"), "temp_c": num(d, "temp"),
                "mem_pct": round(memp) if memp is not None else None, "disk_pct": num(d, "disk_pct"),
                "kernel": d.get("kernel"), "battery_pct": num(d, "battery"), "charging": d.get("charging"),
                "llama_servers": {"8080": d.get("servers_8080"), "8081": d.get("servers_8081")} if kind == "phone" else None,
                "ollama": d.get("ollama") if kind == "ssh" else None, "took_s": round(time.time() - t0, 1)}
    except Exception as e:
        return {"name": name, "animal": animal, "state": "offline", "alerts": [f"unreachable: {str(e)[:60]}"], "took_s": round(time.time() - t0, 1)}

def push_to_ubuntu(tmp_doc):
    """Copy status.json to ubuntu (served read-only on LAN port 8090). Atomic: write a temp file then rename."""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "ubuntu",
                            "cat > ~/status/.status.tmp && mv ~/status/.status.tmp ~/status/status.json"],
                           input=json.dumps(tmp_doc), capture_output=True, text=True, timeout=20)
        if r.returncode != 0: print("push failed:", r.stderr.strip()[:80])
    except Exception as e:
        print("push failed:", str(e)[:80])

def find_agent():
    """The fleet key has a passphrase, so SSH only works through an ssh-agent that already holds it.
    Cron has no agent of its own: look for a running one that has keys loaded. Returns True if found."""
    import glob
    cands = ([os.environ["SSH_AUTH_SOCK"]] if os.environ.get("SSH_AUTH_SOCK") else []) + sorted(glob.glob("/tmp/ssh-*/agent.*"))
    for sock in cands:
        env = dict(os.environ, SSH_AUTH_SOCK=sock)
        try:
            r = subprocess.run(["ssh-add", "-l"], env=env, capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        if r.returncode == 0 and "SHA256" in r.stdout:
            os.environ["SSH_AUTH_SOCK"] = sock
            return True
    return False

def main():
    if not find_agent():
        print("SKIPPED: no ssh-agent with the fleet key loaded (open a WSL shell and add the key); status.json left as it was")
        return
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        hosts = list(ex.map(collect_one, HOSTS))
    doc = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "collector": "illntentpc", "hosts": hosts}
    tmp = OUT + ".tmp"; json.dump(doc, open(tmp, "w"), indent=1); os.replace(tmp, OUT)
    push_to_ubuntu(tmp_doc=doc)
    for h in hosts:
        print(f"{h['animal']:12} {h['name']:11} {h['state']:8} temp={h.get('temp_c')} load={h.get('load')} cpu={h.get('cpu_pct')} mem={h.get('mem_pct')}% disk={h.get('disk_pct')}% up={h.get('uptime_h')}h {h['alerts']}")
if __name__ == "__main__": main()
