# Collection Log — WiFi + Cellular Dead-Zone Mapping

## Sessions collected

| Route | Session | Networks | Notes |
|---|---|---|---|
| Barak (hostel) | Afternoon (~1:30pm) | WiFi + cellular | Standard walkthrough |
| Umiam (hostel) | Afternoon (~1pm) | WiFi + cellular | Standard walkthrough |
| Umiam (hostel) | Evening (~6:30pm) | WiFi + cellular | Second session for time-of-day contrast |
| Hostel → Academic (route 1) | Evening | Cellular | Re-collected after logging cap incident (see below) |
| Academic → Hostel (route 2) | Evening | Cellular | Salvaged tail of original full-loop attempt after cap was hit |
| Academic complex | Evening (~6pm) | Cellular | Single snapshot only — see scope note below |
| Hostel + Academic full loop | Evening | WiFi | Continuous WiGLE log covering the entire loop (hostel → route 1 → academic → route 2 → hostel) in one file |

## Known issue: cellular logging cap

Network Cell Info Lite (Lite version) caps continuous logging at 201 readings per session. 
The original evening plan was one continuous cellular loop (hostel → academic → hostel). 
This cap was hit partway through, and the earlier portion of the loop was lost. The tail 
end (academic → hostel, route 2) was salvaged from that session. The hostel → academic 
leg (route 1) and the academic complex were then re-collected as separate, shorter sessions 
to stay under the 201-reading limit. WiFi logging (WiGLE) has no equivalent cap, so the WiFi 
data for this same walk remains one continuous file.

## Scope decisions (deliberate, not oversights)

- **No Barak evening session.** Only an afternoon session was collected for Barak; the 
  evening time-of-day comparison that exists for Umiam was not repeated for Barak due to 
  time constraints within the 48-hour window. Time-of-day contrast analysis is therefore 
  only available for Umiam and the hostel-academic loop, not for Barak specifically.
- **Academic complex has one snapshot only, no time-of-day contrast.** Collection weekend 
  fell on a Saturday/Sunday (institute holiday), so academic-complex foot traffic and usage 
  patterns were expected to be minimal and non-representative of a weekday. One evening 
  reading (~6pm) was taken as a baseline rather than investing in a multi-session comparison 
  that a holiday weekend wouldn't make meaningful.
- **Academic complex has no WiFi-specific route file.** Its WiFi coverage lives inside the 
  combined `hostel_academic_loop` file since that was one continuous walk; this is a 
  labeling/organization choice, not a coverage gap — the actual GPS points for that stretch 
  are all present in the merged dataset.

## Dataset locked

Final merged dataset frozen as of this collection round. See `docs/schema.md` for the 
unified schema and per-route/session row counts.
