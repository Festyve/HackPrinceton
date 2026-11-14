# Devpost copy

Current-build copy. After phase two, update it only with features and results supported by the final release.

## Inspiration

A stolen credential can make an innocent person's account appear in an incident. A missing log can look like a cover-up—or an ordinary retention policy. We wanted a way to test whether an investigator can distinguish those explanations instead of simply repeating the name in a log.

## What it does

ALIBI is a practice range for digital investigations. A scripted incident runs inside a synthetic clinic. The system freezes the evidence and seals what actually happened. An AI investigator reconstructs the incident, cites its sources, and separates account activity from human identity.

The central interaction compares a workstation's log with an independent collector. One entry is missing locally; the collector still has it. A human reviews and locks the report before the answer is revealed and scored.

## How we built it

The backend uses Python, FastAPI, Pydantic and read-only DuckDB. A seeded simulator generates evidence with hashes and exact-line provenance. Deterministic checks compare sources and test explanations such as rotation, approved transfers and collection gaps.

LangChain deepagents supplies a lead investigator, an integrity auditor, a skeptic, case notes and a resumable human review gate. The React interface makes findings inspectable. A saved real-model investigation replays offline without consuming API credit.

## What we learned

Our twelve-case simulated suite found a clear limitation in a fixed keyword recipe: it missed all four removed-log cases. The contradiction checks recovered all four.

The AI pilot gave a more surprising result. A single agent and the three-agent system had equal accuracy on four cases, while the single agent was faster and cheaper. We report that result rather than claiming delegation automatically helps.

The current incident generator is scripted and the evidence is simulated. The results measure the modeled cases, not real-world forensic accuracy. An account name is never treated as proof of a person's responsibility.

## What comes next

Test the same pipeline on captured Linux artifacts, let investigators ask cited questions, and measure which conclusions survive when an evidence source is removed. These are the next implementation steps, not claims about the current build.

## Submission fields

Use the final public repository URL, final video URL, all four team members and their Discord usernames. Choose Science & Discovery as the single main track, plus the relevant special tracks. Replace this administrative section with the actual Devpost fields; it is not part of the project story.
