#!/usr/bin/env python3
"""Fetch one AI-generated image from the free community AI Horde (anonymous key, no account) and save it.
usage: gen_art.py OUTFILE "prompt" [seed] [model] [source_image denoise]  (source image => img2img for pose consistency)"""
import sys, json, time, urllib.request
API = "https://stablehorde.net/api/v2"
HDR = {"apikey": "0000000000", "Client-Agent": "esp32-gadget:1:local", "Content-Type": "application/json"}
import os
NEG = os.environ.get("GEN_NEG") or "text, watermark, signature, human, hands, multiple characters, cropped, blurry, low quality, deformed, nsfw"
def call(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers=HDR)
    return json.load(urllib.request.urlopen(req, timeout=60))
def main():
    out, prompt = sys.argv[1], sys.argv[2]
    seed = sys.argv[3] if len(sys.argv) > 3 else "7"
    model = sys.argv[4] if len(sys.argv) > 4 else "Counterfeit"
    body = {"prompt": prompt + " ### " + NEG, "models": [model], "nsfw": False, "censor_nsfw": True, "r2": True,
            "params": {"width": 512, "height": 512, "steps": 25, "cfg_scale": 7, "sampler_name": "k_euler_a", "n": 1, "seed": seed}}
    if len(sys.argv) > 5:
        import base64
        body["source_image"] = base64.b64encode(open(sys.argv[5], "rb").read()).decode()
        body["source_processing"] = "img2img"
        body["params"]["denoising_strength"] = float(sys.argv[6]) if len(sys.argv) > 6 else 0.6
    job = call(API + "/generate/async", body)
    jid = job["id"]; print("queued", jid, job.get("kudos"), flush=True)
    t0 = time.time()
    while time.time() - t0 < 420:
        time.sleep(6)
        c = call(API + "/generate/check/" + jid)
        print("wait", int(time.time() - t0), "s: done", c.get("done"), "queue", c.get("queue_position"), "wait_time", c.get("wait_time"), flush=True)
        if c.get("done"): break
    else:
        print("TIMEOUT"); sys.exit(2)
    st = call(API + "/generate/status/" + jid)
    g = st["generations"][0]
    print("model", g.get("model"), "worker", g.get("worker_name"), "censored", g.get("censored"))
    data = urllib.request.urlopen(urllib.request.Request(g["img"], headers={"User-Agent": "esp32-gadget"}), timeout=60).read()
    open(out, "wb").write(data); print("saved", out, len(data), "bytes")
main()
