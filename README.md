# keyprobe

Are the keys working? — and if not, **in which way**, because "down" is not a diagnosis.

## The taxonomy

The fleet already had this from characterizing the toolchain earlier in the session, and it
is the right instrument here. Three questions that a single "does it work?" cannot separate:

| verdict | meaning | what to do |
|---|---|---|
| `OK` | the request succeeded | — |
| `IDENTITY` | credential wrong, expired, out of scope, **or out of credit** | fix or stop. Retrying is pointless. |
| `SHAPE` | credential fine, request malformed for this gateway | fix the request, not the key |
| `LOAD` | credential and request both fine; throttling, queueing, or transient | retry with backoff |

Anything that reports "DOWN" without a classification is worse than no probe.

## It found a defect in itself, on the first run

The classifier had no success case, so it labelled **two working credentials** (HTTP 200
from GitHub and Typesafe) as `SHAPE`. An instrument that cannot report success is the same
failure as one that cannot report failure.

It also had the wrong env var names — `DEEPSEEK_API_KEY`, `ZAI_API_KEY`,
`ELEVENLABS_API_KEY` are all wrong; the real ones are `DEEPSEEK_TOKEN`, `ZAI_TOKEN`,
`ELEVENLABS_TOKEN`.

## Last run

```
credential        http  verdict    ms  note
github             200  OK        479  repo + workflow + admin:org scopes
cloudflare         200  OK        161  token active
typesafe/jev       200  OK        163  noul 0.95
groq               200  OK        100  gpt-oss-20b answers
mothquantum        200  OK       2616  32 engines
deepseek           200  OK       1399
zai                200  OK       3795  <- earlier tonight: 429 insufficient balance
elevenlabs         200  OK        154  33 voices, creator tier
gemini             200  OK        152  <- earlier tonight: 429
minimax            200  OK       1276
```

**All ten authenticate.** Two of them (ZAI, Gemini) were failing with 429 earlier in the
same session and are working now, which is worth recording as a lesson about reading a
single 429 as a durable property of a key.

## The one that is not really OK

**ElevenLabs authenticates and then refuses to synthesise.** The probe reports `OK` because
`/v1/user` and `/v1/voices` both succeed — 33 voices listed, subscription readable. But
`/v1/text-to-speech` returns:

```
401 {"code":"quota_exceeded","message":"This request exceeds your quota of 121105.
     You have 0 credi[t...]"}
```

`character_limit: 121105` is a **ceiling, not a balance.** The remaining balance is **0**.
This is why a probe that only checks "can I call the API" is not enough — a credential can
be perfectly valid and still unable to do its one job.

## The transient

MOTH and several other services returned `503 DNS cache overflow` on an earlier run and
`200` on the next. That is Cloudflare's DNS-cache guard, it is `LOAD`, and a single sample
of it would have produced a false "MOTH is down" report. The probe retries a `LOAD` verdict
three times before recording it.
