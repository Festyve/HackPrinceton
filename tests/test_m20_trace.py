"""The recorded trace states facts about the plan, the examinations and the delegations without over-claiming.

Pure unit tests on synthetic event lists: no orchestrator, no network, no model. Each list has the shape the
runner records (`{"seq", "ts", "type", "data"}`), and nothing here is a measurement of a model.
"""

from __future__ import annotations

from typing import Any

import pytest

from alibi import trace as trace_module
from alibi.trace import investigation_trace

LEAD = "lead-investigator"
UNNAMED = "unnamed finish event"
NOT_FINISHED = "not finished in the log"


def ev(seq: int, kind: str, **data: Any) -> dict[str, Any]:
    return {"seq": seq, "ts": f"2026-11-14T20:00:{seq:02d}Z", "type": kind, "data": data}


def started(seq: int, agent: str, task: str = "") -> dict[str, Any]:
    return ev(seq, "agent", agent=agent, status="started", task=task)


def finished(seq: int, agent: str, summary: str = "") -> dict[str, Any]:
    return ev(seq, "agent", agent=agent, status="finished", summary=summary)


def tool(seq: int, agent: str, name: str, summary: str = "ok") -> dict[str, Any]:
    return ev(seq, "tool", agent=agent, tool=name, args="{}", result_summary=summary, evidence_ids=[], ok=True, ms=3)


def plan(seq: int, *items: str | tuple[str, str]) -> dict[str, Any]:
    """One plan update. An item is its text, or (text, status)."""
    pairs = [i if isinstance(i, tuple) else (i, "pending") for i in items]
    return ev(seq, "todo", items=[{"text": text, "status": status} for text, status in pairs])


def span(tr: dict[str, Any], span_id: str) -> dict[str, Any]:
    return next(s for s in tr["spans"] if s["span_id"] == span_id)


# ---------------------------------------------------------------- delegations


def test_an_unnamed_finish_event_closes_the_oldest_open_delegation_and_says_so():
    """After a resume the runner no longer knows whose task returned, so the finish event says `subagent`."""
    events = [
        started(1, LEAD, "investigate"),
        started(2, "integrity-auditor", "run the checks"),
        started(3, "skeptic", "challenge the candidates"),
        tool(4, "integrity-auditor", "check_local_vs_collector", "2 lines absent"),
        finished(5, LEAD, "the run was cancelled"),
        ev(6, "stage", name="resume", status="started", info={"interrupted_by": "the run was cancelled"}),
        started(7, LEAD, "investigate"),
        finished(8, "subagent", "3 candidate finding(s) returned"),
        started(9, "skeptic", "challenge the candidates again"),
        finished(10, "skeptic", "3 verdict(s): 3 kept, 0 downgraded"),
        finished(11, "subagent", "2 verdict(s): 2 kept, 0 downgraded"),
        finished(12, "subagent", "nothing is open for this one"),
        finished(13, LEAD, "3 finding(s) submitted for review"),
    ]
    tr = investigation_trace(events)
    auditor, old_skeptic, new_skeptic = span(tr, "a2"), span(tr, "a3"), span(tr, "a9")
    # the oldest open delegation takes the first unnamed finish, and the inference is marked on the span
    assert (auditor["status"], auditor["end_seq"], auditor["result_summary"]) == ("finished", 8, "3 candidate finding(s) returned")
    assert auditor["closed_by"] == UNNAMED and auditor["end"] == "2026-11-14T20:00:08Z"
    # a finish event that names its agent closes that agent's span and carries no such mark
    assert (new_skeptic["status"], new_skeptic["end_seq"]) == ("finished", 10) and "closed_by" not in new_skeptic
    # the next unnamed finish takes the delegation that is now the oldest one still open
    assert (old_skeptic["status"], old_skeptic["end_seq"], old_skeptic["closed_by"]) == ("finished", 11, UNNAMED)
    # a third unnamed finish has nothing left to close and changes nothing
    assert all(s["end_seq"] != 12 for s in tr["spans"] if s["kind"] != "tool")
    assert [(d["to"], d["status"], d["result_summary"], d["closed_by"], d["tool_calls"]) for d in tr["behaviors"]["delegations"]] == [
        ("integrity-auditor", "finished", "3 candidate finding(s) returned", UNNAMED, 1),
        ("skeptic", "finished", "2 verdict(s): 2 kept, 0 downgraded", UNNAMED, 0),
        ("skeptic", "finished", "3 verdict(s): 3 kept, 0 downgraded", None, 0),
    ]
    assert tr["behaviors"]["resumed"]["times"] == 1


def test_a_plan_version_after_an_unnamed_finish_names_what_the_log_named():
    """The `after` of a plan version repeats the event's own agent name: the log said `subagent`, so does the trace."""
    events = [
        started(1, LEAD), plan(2, "run the checks"), started(3, "integrity-auditor", "run the checks"),
        finished(4, "subagent", "3 candidate finding(s) returned"),
        plan(5, "run the checks", "Lead: two export records missing on the host"),
    ]
    tr = investigation_trace(events)
    assert span(tr, "a3")["closed_by"] == UNNAMED
    assert tr["plan"][1]["after"] == {"seq": 4, "what": "subagent returned", "summary": "3 candidate finding(s) returned"}


def test_a_delegation_still_open_at_the_end_of_the_log_is_not_called_running():
    events = [
        started(1, LEAD, "investigate"), started(2, "integrity-auditor", "run the checks"),
        tool(3, "integrity-auditor", "check_local_vs_collector"), finished(4, LEAD, "the run was cancelled"),
    ]
    tr = investigation_trace(events)
    auditor = span(tr, "a2")
    assert auditor["status"] == NOT_FINISHED
    assert auditor["end_seq"] is None and auditor["result_summary"] is None and "closed_by" not in auditor
    assert [(d["to"], d["status"], d["result_summary"]) for d in tr["behaviors"]["delegations"]] == [
        ("integrity-auditor", NOT_FINISHED, None)]


def test_an_open_delegation_is_running_only_when_the_caller_says_the_case_still_is():
    events = [
        started(1, LEAD, "investigate"), started(2, "integrity-auditor", "run the checks"),
        finished(3, "integrity-auditor", "3 candidates"), started(4, "skeptic", "challenge the candidates"),
    ]
    live = investigation_trace(events, still_running=True)
    assert [(d["to"], d["status"]) for d in live["behaviors"]["delegations"]] == [
        ("integrity-auditor", "finished"), ("skeptic", "running")]
    assert span(live, "a4")["status"] == "running"
    assert span(investigation_trace(events, still_running=False), "a4")["status"] == NOT_FINISHED


def test_the_leads_own_finish_event_never_closes_a_delegation():
    """A slice of a log can hold the lead's finish without its start. That summary is the lead's, not a specialist's."""
    events = [started(2, "integrity-auditor", "run the checks"), finished(3, LEAD, "3 finding(s) submitted for review")]
    auditor = span(investigation_trace(events), "a2")
    assert auditor["status"] == NOT_FINISHED and auditor["result_summary"] is None and "closed_by" not in auditor


def test_two_open_delegations_to_one_specialist_are_each_closed_by_its_named_finish():
    """Two tasks given to the same specialist in one turn: the name matches both times, so neither close is inferred."""
    events = [
        started(1, LEAD), started(2, "integrity-auditor", "host A"), started(3, "integrity-auditor", "host B"),
        finished(4, "integrity-auditor", "1 candidate"), finished(5, "integrity-auditor", "2 candidates"),
    ]
    tr = investigation_trace(events)
    assert [(s["span_id"], s["status"], s["end_seq"], s.get("closed_by")) for s in tr["spans"] if s["kind"] == "delegation"] == [
        ("a2", "finished", 5, None), ("a3", "finished", 4, None)]


# ---------------------------------------------------------------- plan and examination


@pytest.mark.parametrize("events, plan_recorded, examined, before", [
    pytest.param([started(1, LEAD), tool(2, LEAD, "get_case_brief")], False, False, None, id="no plan, nothing examined"),
    pytest.param([started(1, LEAD), tool(2, LEAD, "search_events")], False, True, None, id="no plan, examined"),
    pytest.param([started(1, LEAD), plan(2, "read the brief"), tool(3, LEAD, "get_case_brief"),
                  ev(4, "note", path="/case/notes.md", op="write_file", preview="Questions")],
                 True, False, None, id="plan, nothing examined"),
    pytest.param([started(1, LEAD), tool(2, LEAD, "check_local_vs_collector"), plan(3, "run the checks")],
                 True, True, False, id="plan after the first examination"),
    pytest.param([started(1, LEAD), plan(2, "run the checks"), tool(3, LEAD, "check_local_vs_collector")],
                 True, True, True, id="plan before the first examination"),
    pytest.param([started(1, LEAD), plan(2, "run the checks"), started(3, "integrity-auditor", "run the checks")],
                 True, True, True, id="plan before a delegation"),
    pytest.param([started(1, LEAD), started(2, "integrity-auditor", "run the checks"), plan(3, "run the checks")],
                 True, True, False, id="plan after a delegation"),
])
def test_plan_and_examination_are_three_separate_facts(events, plan_recorded, examined, before):
    b = investigation_trace(events)["behaviors"]
    # the old key stays for existing callers, and is true only when both exist and the plan came first in the log
    assert b["planned_before_examining"] is (before is True)
    assert b["plan_recorded"] is plan_recorded and b["examined"] is examined
    assert b["plan_recorded_before_first_examination"] is before


def test_the_note_and_the_docstring_say_same_turn_order_is_the_logs_and_not_intent():
    note = investigation_trace([])["note"]
    sentence = "recorded from the same model turn are ordered by the log, not by intent"
    assert sentence in note and sentence in " ".join(trace_module.__doc__.split())
    assert "not a model's thoughts" in note and "does not claim a cause" in note


# ---------------------------------------------------------------- plan revisions

BRIEF_LONG, BRIEF_SHORT = "Get case brief (policies, source inventory)", "Get case brief"
CHECKS = "Run the integrity checks"
LEAD_ITEM = "Lead: two export records missing on the host"


def test_rewording_a_plan_item_is_not_a_revision():
    gaps, missing = "Check the host logs for gaps", "Check host logs for missing lines"
    events = [
        started(1, LEAD), plan(2, BRIEF_LONG, CHECKS, gaps), tool(3, LEAD, "get_case_brief", "brief read"),
        plan(4, (BRIEF_SHORT, "completed"), CHECKS, gaps),  # one normalised text begins with the other
        plan(5, (BRIEF_SHORT, "completed"), CHECKS, missing),  # 4 of the 8 different words are shared: exactly half
    ]
    tr = investigation_trace(events)
    assert tr["behaviors"]["plan_revisions"] == []
    first, shortened, reworded = tr["plan"]
    assert shortened["reworded"] == [{"from": BRIEF_LONG, "to": BRIEF_SHORT}] and shortened["added_new"] == []
    assert shortened["added"] == [BRIEF_SHORT] and shortened["removed"] == [BRIEF_LONG]  # the raw difference is kept
    assert reworded["reworded"] == [{"from": gaps, "to": missing}] and reworded["added_new"] == []
    assert (first["added"], first["added_new"], first["reworded"]) == ([], [], [])  # the first version revises nothing


def test_wording_that_shares_less_than_half_its_words_is_a_new_item():
    old, new = "Check the host logs for gaps", "Check the collector logs for late lines"  # 4 of 9 different words shared
    (revision,) = investigation_trace([started(1, LEAD), plan(2, old), plan(3, new)])["behaviors"]["plan_revisions"]
    assert (revision["added_new"], revision["reworded"], revision["removed"]) == ([new], [], [old])


def test_a_genuinely_new_plan_item_is_a_revision():
    events = [
        started(1, LEAD), plan(2, BRIEF_SHORT, CHECKS), started(3, "integrity-auditor", CHECKS),
        tool(4, "integrity-auditor", "check_local_vs_collector", "2 lines absent"),
        finished(5, "integrity-auditor", "3 candidates"),
        plan(6, (BRIEF_SHORT, "completed"), (CHECKS, "completed"), LEAD_ITEM),
    ]
    assert investigation_trace(events)["behaviors"]["plan_revisions"] == [{
        "seq": 6, "added": [LEAD_ITEM], "added_new": [LEAD_ITEM], "reworded": [], "removed": [],
        "after": {"seq": 5, "what": "integrity-auditor returned", "summary": "3 candidates"}}]


def test_an_item_swapped_for_an_unrelated_one_is_a_revision_and_the_old_item_is_reported_removed():
    events = [started(1, LEAD), plan(2, BRIEF_SHORT, CHECKS), plan(3, BRIEF_SHORT, "Interview the operator")]
    (revision,) = investigation_trace(events)["behaviors"]["plan_revisions"]
    assert (revision["added_new"], revision["reworded"], revision["removed"]) == (["Interview the operator"], [], [CHECKS])


def test_a_version_that_both_rewords_and_adds_reports_each():
    events = [
        started(1, LEAD), plan(2, BRIEF_LONG, CHECKS, "Draft the report"),
        tool(3, LEAD, "search_events", "5 rows"),
        plan(4, (BRIEF_SHORT, "completed"), CHECKS, LEAD_ITEM),
    ]
    tr = investigation_trace(events)
    (revision,) = tr["behaviors"]["plan_revisions"]
    assert revision["added_new"] == [LEAD_ITEM] and revision["added"] == revision["added_new"]
    assert revision["reworded"] == [{"from": BRIEF_LONG, "to": BRIEF_SHORT}]
    assert revision["removed"] == ["Draft the report"]  # dropped outright, not reworded into anything
    assert (revision["seq"], revision["after"]["seq"], revision["after"]["what"]) == (4, 3, "lead-investigator · search_events")
    version = tr["plan"][1]
    assert version["added"] == [BRIEF_SHORT, LEAD_ITEM] and version["removed"] == [BRIEF_LONG, "Draft the report"]  # raw
    assert version["added_new"] == [LEAD_ITEM] and version["reworded"] == revision["reworded"]


def test_ticking_items_off_is_not_a_revision():
    events = [
        started(1, LEAD), plan(2, (BRIEF_SHORT, "in_progress"), CHECKS), tool(3, LEAD, "get_case_brief"),
        plan(4, (BRIEF_SHORT, "completed"), (CHECKS, "in_progress")), plan(5, (BRIEF_SHORT, "completed"), (CHECKS, "completed")),
    ]
    tr = investigation_trace(events)
    assert tr["behaviors"]["plan_revisions"] == []
    assert [(p["added"], p["added_new"], p["reworded"], p["removed"]) for p in tr["plan"]] == [([], [], [], [])] * 3


def test_dropping_an_item_without_adding_one_is_not_a_revision():
    events = [started(1, LEAD), plan(2, BRIEF_SHORT, CHECKS, "Draft the report"), plan(3, BRIEF_SHORT, CHECKS)]
    tr = investigation_trace(events)
    assert tr["behaviors"]["plan_revisions"] == []
    assert tr["plan"][1]["removed"] == ["Draft the report"] and tr["plan"][1]["added_new"] == []


def test_one_removed_item_is_the_source_of_at_most_one_rewording():
    """One item becoming two is a plan that grew: the closer wording is the rewording, the other one is new."""
    events = [
        started(1, LEAD), plan(2, "Check the host logs"),
        plan(3, "Check the collector logs", "Check the host logs again"),
    ]
    (revision,) = investigation_trace(events)["behaviors"]["plan_revisions"]
    assert revision["reworded"] == [{"from": "Check the host logs", "to": "Check the host logs again"}]
    assert revision["added_new"] == ["Check the collector logs"] and revision["removed"] == []


def test_text_with_no_letters_or_digits_is_never_a_rewording():
    """An item that normalises to nothing would be a prefix of everything; it is treated as its own item."""
    events = [started(1, LEAD), plan(2, "???", CHECKS), plan(3, "Interview the operator", CHECKS)]
    (revision,) = investigation_trace(events)["behaviors"]["plan_revisions"]
    assert (revision["added_new"], revision["reworded"], revision["removed"]) == (["Interview the operator"], [], ["???"])


# ---------------------------------------------------------------- the rest is as it was


def test_the_rest_of_the_trace_is_unchanged_at_version_two():
    events = [
        started(1, LEAD, "investigate"), plan(2, "read the brief"),
        ev(3, "note", path="/case/case.md", op="write_file", preview="Questions"),
        started(4, "integrity-auditor", "run the checks"), tool(5, "integrity-auditor", "check_local_vs_collector"),
        finished(6, "integrity-auditor", "3 candidates"),
        ev(7, "stage", name="resume", status="started", info={"interrupted_by": "the run was cancelled", "process_id": 7}),
        tool(8, LEAD, "search_events"), ev(9, "note", path="/case/case.md", op="edit_file", preview="Answers"),
        ev(10, "note_read", path="/case/case.md"), ev(11, "note_read", path="/case/other.md"),
        ev(12, "usage", usage={"llm_calls": 4}), finished(13, LEAD, "1 finding(s) submitted for review"),
    ]
    tr = investigation_trace(events)
    b = tr["behaviors"]
    assert tr["version"] == trace_module.TRACE_VERSION == "trace/2"
    assert tr["usage"] == {"llm_calls": 4}
    assert [f["op"] for f in tr["case_file"]] == ["write", "edit", "read", "read"]
    assert b["case_file"] == {"writes": 2, "reads_after_a_write": 1, "paths": ["/case/case.md", "/case/other.md"]}
    assert b["resumed"] == {"times": 1, "tool_calls_after_resume": 1, "resumes": [
        {"seq": 7, "t": "2026-11-14T20:00:07Z", "interrupted_by": "the run was cancelled", "process_id": 7}]}
    run, auditor = span(tr, "a1"), span(tr, "a4")
    assert (run["kind"], run["parent_id"], run["status"], run["end_seq"]) == ("run", None, "finished", 13)
    assert (auditor["kind"], auditor["parent_id"], auditor["status"]) == ("delegation", "a1", "finished")
    assert (span(tr, "t5")["parent_id"], span(tr, "t8")["parent_id"]) == ("a4", "a1")
    assert [(d["to"], d["tool_calls"], d["status"], d["result_summary"]) for d in b["delegations"]] == [
        ("integrity-auditor", 1, "finished", "3 candidates")]
