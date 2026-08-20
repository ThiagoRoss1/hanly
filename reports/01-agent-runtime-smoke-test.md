# Agent Runtime Smoke Test

- **Requested topology:** Sol → Terra → two Luna workers, with both Luna workers requested at `xhigh` reasoning.
- **Actual topology:** `/root` → `/root/terra_smoke_lead` → `/root/terra_smoke_lead/luna_a` and `/root/terra_smoke_lead/luna_b`. Both workers returned their required unique tokens: `LUNA-A-OK` and `LUNA-B-OK`. Actual runtime model/reasoning metadata was not exposed.
- **Two distinct Luna workers created:** Yes.
- **xhigh verified:** UNVERIFIED. Both workers were explicitly requested as `gpt-5.6-luna` with `xhigh` reasoning, but actual runtime model/reasoning metadata was unavailable.
- **Fallback occurred:** No.
- **Final result:** UNVERIFIED.
