# Reference notes

Checked November 14, 2026. The event rules come from the supplied **F26 Onsite Hacker Packet (1).docx**, not a guessed public schedule: Sunday November 15, 08:00 ET submission; presentation/video maximum two minutes; one main track plus compatible specials. Rayan selected Science & Discovery, Arlequin, Amazon and LangChain. The current user instruction authorizes the configured $20 cumulative API cap.

## Visual references

- [Omar Farook's redesign reel](https://www.instagram.com/reel/DfqWmHCmU9p/): inspected in a browser, including the later frosted graphite/earth-colored workspace over landscape wallpaper. Typography, hierarchy, unified surfaces, consolidated actions, folded secondary information and command navigation are the transferable design steps. Do not copy its finance data or branding.
- [UITOP investigation workspace](https://dribbble.com/shots/27869206-AI-Security-Agent-Investigation-UX-for-Evidence-and-Severity): inspected its image and description. Use the investigation heading, source/evidence grouping and explainable findings hierarchy. Its warm paper palette is a secondary reference, not a reason to override the reel's material treatment.
- [21st Agent Trace](https://21st.dev/@n1m4mz/components/agent-trace): public page describes nested spans, replay and inspectable calls; MIT is shown. Full source may require sign-in. Verify the actual source/license before vendoring; original implementation of the behavior is fine.
- [21st task list](https://21st.dev/@kvnkld/components/task-list): use visible task states and collapse behavior. Do not assume source access or licensing from a preview.
- [React Bits animated list](https://reactbits.dev/components/animated-list): restrained selectable/keyboard-navigable rows. Preserve the app's existing stack instead of adding a CSS framework just for one component.

## Engineering references

Use the lockfile's DeepAgents version and installed signatures as the implementation authority. Official [subagent documentation](https://docs.langchain.com/oss/python/deepagents/subagents) explains specialist delegation and context isolation. Official [memory documentation](https://docs.langchain.com/oss/python/deepagents/memory) distinguishes checkpointed within-thread state from cross-thread memory. The proposed case file needs the former; global memory would risk carrying case answers into later experiments.

[NIST CFReDS](https://cfreds.nist.gov/) is the sponsor's suggested source of reference datasets. Our brief/evidence/truth structure is inspired by forensic evaluation practice; the synthetic lab is not a NIST-validated dataset. No external download is required for the release.

Repository evidence: [source audit](STATUS.md), [current API](../api.md), [UI integration brief](../ui-integration-brief.md), [measured results](../evaluation-summary.md). These take precedence over stale claims in older handoffs.
