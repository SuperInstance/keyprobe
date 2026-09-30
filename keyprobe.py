#!/usr/bin/env python3
"""
keyprobe.py — are the keys working, and if not, in which way?

The fleet already has a failure taxonomy from tonight's tool characterization, and it is
the right instrument here because a dead key and a rate-limited key look identical if you
only ask "does it work?":

  IDENTITY  the credential is wrong, expired, out of credit, or out of scope. Retrying is
            pointless. Fix or stop.
  SHAPE     the credential is fine; the REQUEST is malformed for this gateway. Fix the
            request, not the key.
  LOAD      the credential is fine and so is the request; the service is throttling,
            queueing, or transiently failing. Retry with backoff.

Anything that reports "DOWN" without a classification is a worse instrument than no probe.
"""
import os, json, time, urllib.request, urllib.error

CLASS = {"IDENTITY": "fix or stop", "SHAPE": "fix the request", "LOAD": "retry later"}

def _req(url, headers, data=None, timeout=25, method=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers=headers, method=method or ("POST" if data is not None else "GET"))
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except Exception as e:
        return 0, str(e).encode(), time.time() - t0

def classify(code, body: bytes) -> str:
    b = body.lower()
    if 200 <= code < 300:
        return "OK"                                     # IT WORKED
    if code == 0:
        return "LOAD"                                    # timeout / DNS / reset
    if code in (401, 403):
        if any(w in b for w in (b"scope", b"permission", b"forbidden", b"not authorized")):
            return "IDENTITY"
        if any(w in b for w in (b"credit", b"balance", b"quota_exceeded", b"insufficient")):
            return "IDENTITY"
        return "IDENTITY"
    if code == 402:
        return "IDENTITY"
    if code == 429:
        return "LOAD"
    if code in (400, 404, 422):
        return "SHAPE"
    if code == 503:
        return "LOAD"
    if 500 <= code < 600:
        return "LOAD"
    return "SHAPE"

# ---- one probe per credential -------------------------------------------------
def probe_github():
    t = os.environ.get("GITHUB_TOKEN", "")
    c, b, dt = _req("https://api.github.com/user", {"Authorization": f"Bearer {t}",
                   "Accept": "application/vnd.github+json", "User-Agent": "m"})
    scopes = ""
    if c == 200:
        try:
            import urllib.request as U
            r = U.urlopen(U.Request("https://api.github.com/user", headers={
                "Authorization": f"Bearer {t}", "User-Agent": "m"}), timeout=20)
            scopes = (r.headers.get("X-OAuth-Scopes") or "")[:80]
        except Exception: pass
    return "github", c, classify(c, b), dt, scopes

def probe_cloudflare():
    t = os.environ.get("CLOUDFLARE_TOKEN", "")
    c, b, dt = _req("https://api.cloudflare.com/client/v4/user/tokens/verify",
                    {"Authorization": f"Bearer {t}", "User-Agent": "m"})
    note = ""
    if c == 200:
        try: note = json.loads(b)["result"].get("status", "")
        except Exception: pass
    return "cloudflare", c, classify(c, b), dt, note

def probe_typesafe():
    t = os.environ.get("TYPESAFEAI_KEY", "")
    c, b, dt = _req("https://api.typesafe.ai/v1/systemone", {"Authorization": f"Bearer {t}",
                   "Content-Type": "application/json"},
                   {"model": "jev-latest", "state": "Entropy is maximised by a uniform distribution over a fixed support.",
                    "questions": {"q": {"type": "noul", "instructions": "Is this true?",
                    "criteria": {"true": "true.", "false": "false."}}}})
    note = ""
    if c == 200:
        try:
            note = str(json.loads(b)["answers"]["q"].get("noul"))
        except Exception: pass
    return "typesafe/jev", c, classify(c, b), dt, note

def probe_groq():
    t = os.environ.get("GROQ_TOKEN", "")
    ok_model = None
    for m in ("allam-2-7b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"):
        c, b, dt = _req("https://api.groq.com/openai/v1/chat/completions",
                        {"Authorization": f"Bearer {t}", "Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0"},
                        {"model": m, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 4})
        if c == 200:
            ok_model = m; break
    if ok_model: return "groq", 200, "OK", dt, f"model {ok_model} answers"
    return "groq", c, classify(c, b), dt, "no listed model answered"

def probe_moth():
    t = os.environ.get("MOTH_API_KEY", "")
    c, b, dt = _req("https://api.mothquantum.com/api/v1/engines", {"Authorization": f"Bearer {t}", "User-Agent": "m"})
    n = 0; role = ""
    if c == 200:
        try:
            d = json.loads(b); n = len(d.get("engines", []))
        except Exception: pass
        c2, b2, _ = _req("https://api.mothquantum.com/api/v1/me", {"Authorization": f"Bearer {t}", "User-Agent": "m"})
        if c2 == 200:
            try: role = json.loads(b2).get("platform_role", "")
            except Exception: pass
    return "mothquantum", c, classify(c, b), dt, f"{n} engines, role={role or '?'}"

def probe_deepseek():
    t = os.environ.get("DEEPSEEK_TOKEN", "")
    if not t: return "deepseek", 0, "IDENTITY", 0.0, "no DEEPSEEK_TOKEN in env"
    c, b, dt = _req("https://api.deepseek.com/chat/completions",
                    {"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                    {"model": "deepseek-chat", "messages": [{"role": "user", "content": "ok"}], "max_tokens": 4})
    return "deepseek", c, classify(c, b), dt, b[:60].decode("utf-8", "replace")

def probe_zai():
    t = os.environ.get("ZAI_TOKEN", "")
    if not t: return "zai", 0, "IDENTITY", 0.0, "no ZAI_TOKEN in env"
    c, b, dt = _req("https://api.z.ai/api/paas/v4/chat/completions",
                    {"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                    {"model": "glm-4.5-flash", "messages": [{"role": "user", "content": "ok"}], "max_tokens": 8})
    return "zai", c, classify(c, b), dt, b[:60].decode("utf-8", "replace")

def probe_elevenlabs():
    t = os.environ.get("ELEVENLABS_TOKEN", "")
    if not t: return "elevenlabs", 0, "IDENTITY", 0.0, "no ELEVENLABS_TOKEN in env"
    c, b, dt = _req("https://api.elevenlabs.io/v1/user", {"xi-api-key": t, "User-Agent": "m"})
    return "elevenlabs", c, classify(c, b), dt, b[:60].decode("utf-8", "replace")

def probe_gemini():
    t = os.environ.get("GEMINI_TOKEN", "")
    if not t: return "gemini", 0, "IDENTITY", 0.0, "no GEMINI_TOKEN in env"
    c, b, dt = _req("https://generativelanguage.googleapis.com/v1beta/models",
                    {"x-goog-api-key": t, "User-Agent": "m"})
    return "gemini", c, classify(c, b), dt, b[:50].decode("utf-8", "replace")

def probe_minimax():
    t = os.environ.get("MINIMAX_KEY", "")
    if not t: return "minimax", 0, "IDENTITY", 0.0, "no MINIMAX_KEY in env"
    c, b, dt = _req("https://api.minimax.chat/v1/text/chatcompletion_v2",
                    {"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                    {"model": "MiniMax-Text-01", "messages": [{"role": "user", "content": "ok"}]})
    return "minimax", c, classify(c, b), dt, b[:50].decode("utf-8", "replace")

PROBES = [probe_github, probe_cloudflare, probe_typesafe, probe_groq, probe_moth,
          probe_deepseek, probe_zai, probe_elevenlabs, probe_gemini, probe_minimax]

if __name__ == "__main__":
    print(f"  {'credential':16} {'http':>5} {'verdict':9} {'ms':>6}  note")
    print("  " + "-" * 78)
    rows = []
    tries = 3
    for p in PROBES:
        name = code = verdict = note = None
        dt = 0.0
        for attempt in range(tries):
            try:
                name, code, verdict, dt, note = p()
            except Exception as e:
                name = getattr(p, "__name__", "?"); code = 0
                verdict = "IDENTITY"; dt = 0.0; note = f"probe raised {e}"
            if verdict != "LOAD":
                break
            time.sleep(1.5 * (attempt + 1))
        rows.append((name, code, verdict, note))
        print(f"  {name:16} {code:>5} {verdict:9} {dt*1000:>6.0f}  {str(note)[:44]}")
    json.dump([{"name": n, "http": c, "verdict": v, "note": s} for n, c, v, s in rows],
              open("/workspace/projects/keyprobe/last_run.json", "w"), indent=1)
    print()
    print(f"  usable now : {[n for n,_,v,_ in rows if v=='OK']}")
    print(f"  identity   : {[(n,s[:30]) for n,_,v,s in rows if v=='IDENTITY']}")
    print(f"  shape      : {[(n,s[:30]) for n,_,v,s in rows if v=='SHAPE']}")
    print(f"  load       : {[(n,s[:30]) for n,_,v,s in rows if v=='LOAD']}")
