"""The seven scripted participants of spike-1 §4. Each returns nothing; evidence lands in its trace."""
from __future__ import annotations

from typing import Callable

from .participant import Participant

ATT = ["att1", "att2", "att3"]


def att_order(entry: dict) -> list[str]:
    return [q for q in entry["questions"] if q in ATT]


def to_attitudes(P: Participant, age: str = "30", **params: str) -> dict:
    P.open("consent", **params)
    P.yesno("consent", "Y")
    P.next("age")
    P.fill("age", age)
    P.next("stimulus")
    return P.next("attitudes")


def p1(P: Participant, db: Callable) -> None:
    """Consent no -> ends immediately; no other answers stored."""
    P.open("consent")
    P.yesno("consent", "N")
    P.next("after-consent-no")
    P.note({"db_final": db(P.token)})


def p2(P: Participant, db: Callable) -> None:
    """Native mode, straight through, att1=5; probes required + validation + piping/escaping."""
    P.open("consent")
    P.next("consent-empty-submit")                    # required
    P.yesno("consent", "Y")
    P.next("age")
    P.next("age-empty-submit")                        # required
    for bad in ("17", "121", "30.5"):
        P.fill("age", bad)
        P.next(f"age-{bad}-submit")                   # range / integer-only
    P.fill("age", "30")
    P.next("stimulus")
    P.next("attitudes")
    P.five("att1", 5); P.five("att2", 4); P.five("att3", 3)
    P.next("followup")
    P.next("followup-empty-submit")                   # required when shown
    P.fill("fu", "<b>bold</b> & <i>it</i>")           # fake text; probes HTML escaping when piped
    P.next("final")
    P.note({"db_before_submit": db(P.token)})
    P.next("end")
    P.note({"db_final": db(P.token)})


def p3(P: Participant, db: Callable) -> None:
    """Native mode, att1=2 -> follow-up not shown, not required."""
    to_attitudes(P, age="45")
    P.five("att1", 2); P.five("att2", 2); P.five("att3", 2)
    P.next("final")
    P.next("end")
    P.note({"db_final": db(P.token)})


def p4(P: Participant, db: Callable) -> None:
    """Redirect mode ?cond=B&ospseed=123: prefill, persistence over back/refresh, and a re-entry with other params."""
    P.open("consent", cond="B", ospseed="123")
    P.yesno("consent", "Y")
    P.next("age")
    P.note({"db_after_page1": db(P.token)})
    P.prev("back-to-consent")
    P.reload("reload-consent")
    P.next("age-again")
    P.fill("age", "40")
    P.next("stimulus")
    P.note({"db_after_stimulus": db(P.token)})
    # Same token, new browser, *different* params: does LimeSurvey re-prefill (re-roll) or keep B?
    P.new_session()
    P.open("reentry-with-cond-A", cond="A", ospseed="999")
    P.note({"db_after_reentry_cond_A": db(P.token)})
    # walk to the end from wherever we resumed
    for _ in range(8):
        e = P.trace[-1]
        if not e["has_next"]:
            break
        if "consent" in e["questions"] and P.value_of("consent") in ("", None):
            P.yesno("consent", "Y")
        if "age" in e["questions"] and not P.value_of("age"):
            P.fill("age", "40")
        for a in ATT:
            if a in e["questions"] and not P.value_of(a):
                P.five(a, 3)
        P.next("walk")
    P.note({"db_final": db(P.token)})


def p5(P: Participant, db: Callable) -> None:
    """att1=5, answer follow-up, go back, change att1 to 2, submit -> Q6."""
    a = to_attitudes(P, age="52")
    first = att_order(a)
    P.five("att1", 5); P.five("att2", 1); P.five("att3", 1)
    P.next("followup")
    P.fill("fu", "FU-VALUE-BEFORE-BACK")
    P.next("final")
    P.note({"db_fu_submitted": db(P.token)})
    P.prev("back-to-followup")
    P.note({"fu_value_shown_on_back": P.value_of("fu")})
    back = P.prev("back-to-attitudes")
    P.note({"att_order_first": first, "att_order_on_back": att_order(back)})
    P.five("att1", 2)
    P.next("after-att1-changed")
    P.note({"db_after_att1_changed_before_submit": db(P.token)})
    P.next("end")
    P.note({"db_final": db(P.token)})


def p6(P: Participant, db: Callable, session_probe: Callable) -> None:
    """Refresh mid-page and resume with token -> Q7 (order + condition stable)."""
    a = to_attitudes(P, age="33")
    orders = {"first_view": att_order(a)}
    P.note({"session_order_probe": session_probe(P.token)})
    orders["reload"] = att_order(P.reload("reload-attitudes"))
    P.five("att1", 4)                                   # selected but NOT submitted
    r = P.reload("reload-after-unsubmitted-answer")
    orders["reload2"] = att_order(r)
    P.note({"unsubmitted_att1_after_reload": P.value_of("att1")})
    P.note({"db_mid": db(P.token)})
    P.new_session()                                     # different browser, same token
    r = P.open("resume-new-session")
    orders["resume_new_session"] = att_order(r)
    P.note({"resumed_on_questions": r["questions"]})
    # back to the stimulus and forward again
    s = P.prev("back-to-stimulus")
    P.note({"stimulus_on_back": s["markers"]})
    orders["after_back_forward"] = att_order(P.next("forward-to-attitudes"))
    P.note({"db_after_back_forward": db(P.token)})
    P.five("att1", 1); P.five("att2", 1); P.five("att3", 1)
    P.next("final")
    P.next("end")
    P.note({"orders": orders, "db_final": db(P.token)})


def p7(P: Participant, db: Callable) -> None:
    """Re-enter the survey link after finishing -> no reallocation."""
    to_attitudes(P, age="61")
    P.five("att1", 3); P.five("att2", 3); P.five("att3", 3)
    P.next("final")
    P.next("end")
    P.note({"db_after_finish": db(P.token)})
    P.open("reenter-same-browser")
    P.new_session()
    P.open("reenter-new-browser")
    P.open("reenter-new-browser-with-cond", cond="B", ospseed="7")
    P.note({"db_after_reentry": db(P.token)})


SCRIPTS = {"P1": p1, "P2": p2, "P3": p3, "P4": p4, "P5": p5, "P6": p6, "P7": p7}
