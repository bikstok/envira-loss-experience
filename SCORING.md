# How we assess this test

We would rather you knew how this is marked than guessed at it. Knowing the criteria does not make the task easier — it just means you spend your two hours on the things we actually care about instead of the things you think we might.

## What we are measuring

Four things, in this order of importance:

1. **Correctness and verification** — are the numbers right, and do you know that they are right because you checked, rather than because the code ran?
2. **Scoping and judgement** — did you build a working core first and make defensible decisions about the rest?
3. **Ownership** — can you explain and change what you submitted, including the parts an AI tool wrote?
4. **Operability** — can another engineer clone it and run it?

## The scorecard

Each dimension is scored 1 to 5 and weighted:

| Dimension | Weight |
|---|---:|
| Correctness and verification | 30% |
| Scoping and engineering judgement | 25% |
| Running and operability | 15% |
| Live ownership and AI-assisted working | 15% |
| Code quality and tests | 10% |
| Communication | 5% |

Roughly what the ends of the scale look like:

**Correctness and verification.** A 5 produces output that is right under a clearly stated policy for handling the data, found the issues that actually change the answer, and can show how it knows the numbers are sensible. A 1 produces materially wrong output and never checks.

**Scoping and engineering judgement.** A 5 ships a small coherent core and then adds only work with obvious value, and explains the trade-offs in terms of the problem rather than the technology. A 1 attempts everything, finishes little, or builds infrastructure before the core is correct.

**Running and operability.** A 5 can be started from the README with minimal setup, and the documented interface works. A 1 cannot be run without substantial reconstruction.

**Live ownership and AI-assisted working.** Scored after the call. A 5 explains selected code precisely, treats AI as a tool rather than an oracle, checks changes, notices side effects, and completes the live change. A 1 cannot explain code they wrote two hours earlier.

**Code quality and tests.** A 5 has a simple structure, clear boundaries, useful tests around the data handling, and little unnecessary abstraction. A 1 is hard to follow, over-engineered, or leaves important behaviour untested.

**Communication.** A 5 has a short, candid `DECISIONS.md` in which the assumptions and the omissions are explicit. A 1 hides limitations or restates the brief.

## What helps

- Looking at the data before or alongside writing the code.
- Writing a small independent check that your output is plausible, separate from the code that produces it.
- Noticing when a figure is commercially implausible and chasing down why.
- Choosing an explicit policy for the awkward rows and writing it down, even when the policy is "excluded, here is why".
- Saying in `DECISIONS.md` why you did *not* build something.
- Keeping the implementation smaller than the AI proposed.

## What hurts

- Output that is materially wrong because of something in the data that was never examined.
- Rows silently lost or silently duplicated, with no sign that anyone noticed.
- Treating anything unexpected in the data as dirty and dropping it without a word.
- Building infrastructure — a database, a cache, a queue, a container stack — before the core answer is correct.
- Touching all eight backlog items and finishing none of them.
- Being unable to explain, at the call, code you submitted two hours earlier.

## About the data

It is synthetic, and it is deliberately not clean. There are quality problems in it of the kinds you would meet in a real book of business, and finding them is part of the task rather than an obstacle to it. We are not going to tell you how many there are or where they are — noticing is the exercise.

The volumes are small. Nothing here needs to be fast, and we do not score performance.

## About the two hours

The limit is honour-based and we do not try to infer it from your commit timestamps. Two hours is not enough to do everything in the brief, and it is not meant to be. If you spend the time well and stop, that is a good outcome; if you spend six hours and submit something large, we will find out at the call, and it will not help you.

## About AI tools

Use whatever you normally use. We are not testing whether you can write code without assistance — we are testing whether you direct the tools, review what comes back, discard the parts that are wrong, and stay accountable for the result. Expect to be asked which parts came from a tool, what you changed, and what you rejected.

## The call

Thirty minutes, screen shared:

- You run the service and show us the output.
- We pick a piece of the code and ask you to walk through it.
- We ask how you know your numbers are right.
- We ask you to make one small change while we watch.
- You ask us whatever you want.

The live change is a normal small change, not a puzzle. We are watching how you work, not whether you get it first time.
