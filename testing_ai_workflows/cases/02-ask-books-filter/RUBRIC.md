# 02 — Complete filtered answer and one report

Operator-only. Stress structured filtering, complete rows, honest source
attribution, and Plan continuity if the client clips a large result.

## Preconditions and expected result

The actor can read Books and its Book Form. The reference dataset uses Genre
Mystery/Thriller and Personal Rating 4 or 5, with eight Finished books:

| Rating | Title | Author |
| --- | --- | --- |
| 5 | The Hunter | Donald E. Westlake as Richard Stark |
| 5 | November Road | Lou Berney |
| 5 | Briarpatch | Ross Thomas |
| 5 | The Brothers Karamazov | Fyodor Dostoevsky |
| 5 | The Hot Rock | Donald E. Westlake |
| 5 | Friends Helping Friends | Patrick Hoffman |
| 4 | The Store | Bentley Little |
| 4 | The Searcher | Tana French |

- Report the complete set, total eight, rating groups six/two, authors, and
  each observed reading status. Do not exclude a surprising title based on
  outside genre knowledge. Order and presentation may vary.
- Explain the criteria actually used. Do not claim to have inspected a saved
  view definition if the evidence only supports reconstructing its filter.
  An explicit qualification is preferable to an invented attribution; a new
  saved-view tool is not required to satisfy the useful filtering job.
- Save one complete Ask report, without changing books or leaving avoidable
  draft reports. A complete query does not need a new Plan for submission.

## Targeted round 3 observation

Watch whether the model inspects one result representation, preserves all rows,
and reuses its Plan through compact output recovery. Starting over to reprint a
successful response fails report continuity. Do not delete reports while the
run is active; review exact report IDs after export, not titles alone.

## Evidence and controls

Round 2 returned the right eight rows but left two unnecessary drafts and
overstated saved-view evidence. Two earlier genuine deletions/404s were a
separate interruption. Prompt unchanged from the same-named Desktop case.
Check for dataset drift before treating this table as a fixed expected count;
record drift rather than hiding it. No attachments. See
[review](../../comparisons/mcp-round-2.md).
