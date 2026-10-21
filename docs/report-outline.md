# Report and demonstration checklist

Target: around 3,000 words, no more than six pages, IEEE/ACM proceedings format.
Abstract: at most 200 words.

| Section | Evidence to include |
|---|---|
| Abstract and motivation | Client failure problem, scoped contribution and actual findings |
| Related work | FedAvg, Flower timeout behaviour, Micro-FL; exact bibliographic references |
| System design | Four-pod diagram, message fields, locality and trust assumptions |
| Implementation | Early quorum, deadlines, version validation, bounded work and recovery |
| Evaluation | Fixed data splits, three seeds, failure scenarios, quality/time/resource graphs |
| Limitations and conclusion | Slow-bank exclusion bias, single coordinator, synthetic institutions, privacy limits |

The original proposal and brief are in `planning/`. Check the progress
presentation date against LMS: the brief's weekday and date disagree.

## Demonstration order

1. Show the coordinator and three bank pods.
2. Explain the baseline and the 2-of-3 rule.
3. Show a healthy run.
4. Slow a bank and show an early commit.
5. Show the corresponding stale reply being rejected.
6. Terminate a bank pod and show its replacement.
7. Show the replacement bank's first accepted update.
8. Compare timings, quality and participation using saved evidence.
9. State what is outside scope.

Final deliverables: source/image or repository URL, `GROUP18.pdf`,
`GROUP18_INSTRUCTIONS.pdf`, and a 10–15-minute video. Do not invent performance
numbers, cite synthetic software checks as ULB results, or describe quorum
aggregation as a new consensus algorithm.
