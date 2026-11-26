"""Tests for the Gemini question generator and the website review/request code. Run: python -m pytest tests"""
import base64
import copy
import datetime
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "generator"))

import convert  # noqa: E402
import coverage  # noqa: E402
import extra_checks  # noqa: E402
import generate  # noqa: E402
import request_crypto  # noqa: E402
import review_apply  # noqa: E402
from schema import Draft  # noqa: E402

CFG = yaml.safe_load((ROOT / "generator.yaml").read_text())
SYL = {sid: {"id": sid, "level": "SL", "topic": sid.rsplit(".", 1)[0], "topic_title": "T", "text": "t",
             "term_index": 0} for sid in ["A1.1.3", "A1.1.4", "B1.1.5", "A2.1.1", "C1.2.3"]}
SYL["A3.2.1"] = dict(SYL["A1.1.3"], id="A3.2.1", level="HL", topic="A3.2")
CTS = {"State": {"marks": [1]}, "Outline": {"marks": [2]}, "Explain": {"marks": [3, 4]},
       "Evaluate": {"marks": [4]}, "Discuss": {"marks": [4]}}
TARGET = {"marks": 6, "difficulty": 2, "statements": ["A1.1.3", "A1.1.4"], "topics": ["A1.1"]}


def cov(**kw):
    c = coverage.coverage([], SYL)
    c.update(kw)
    return c


def good():
    return Draft.model_validate(json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text()))


def question(draft=None, qid="folding-camping-stool"):
    return convert.to_question(draft or good(), qid, target=TARGET, case_study=None, model="test-model")


def errors_for(q):
    return generate.validate(q, SYL, CTS, cov(), CFG)


def test_good_draft_passes_and_round_trips():
    q = question()
    assert errors_for(q) == []
    assert yaml.safe_load(convert.to_yaml(q)) == q
    assert q["status"] == "draft" and q["source"]["generated_by"] == "gemini"
    assert "&amp;" in q["stimulus"][0]["text"]            # bare & was escaped
    assert sum(q["stimulus"][1]["table"]["widths_mm"]) <= 161


@pytest.mark.parametrize("change, message", [
    (lambda d: d["parts"][2].update(command_term="Discuss", question="Discuss why prototype B is best, using Table 1."),
     "Discuss"),
    (lambda d: d["parts"][1].update(question="Outline one benefit of using a gearbox in the stool."), "HL-only"),
    (lambda d: d["parts"][2].update(marks=2), "mark pattern"),
    (lambda d: d["parts"][0].update(answers=["Anthropometric data"]), "more marking points"),
    (lambda d: d["stimulus"].insert(2, {"kind": "table", "table_caption": "Table 2: Prices",
                                        "table_rows": [["A", "B"], ["1", "2"]]}), "Table 2 is not referred"),
    (lambda d: d["parts"][0].update(syllabus=["A3.2.1"]), "HL only"),
    (lambda d: d["stimulus"].pop(3), "Data written for this practice paper"),
    (lambda d: d["stimulus"][0].update(text="Too short."), "words"),
])
def test_bad_drafts_are_caught(change, message):
    d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    change(d)
    errs = errors_for(question(Draft.model_validate(d)))
    assert any(message in e for e in errs), errs


def test_difficulty_3_needs_data_part():
    d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    d["difficulty"] = 3
    d["parts"][2]["question"] = "Explain why prototype B is the most appropriate design (Table 1 may help)."
    q = question(Draft.model_validate(d))
    q["parts"][2]["question"] = "Explain why prototype B is the most appropriate design."
    assert any("difficulty 3" in e for e in extra_checks.check(q))


def test_clean_markup():
    assert convert.clean("a & b <b>x</b> <sup>2</sup> <script>") == \
        "a &amp; b <b>x</b> <super>2</super> &lt;script&gt;"


def test_choose_target_and_case_study():
    c = cov()
    t = coverage.choose_target(c, SYL, CFG, marks=10, difficulty=3)
    assert t["marks"] == 10 and all(SYL[s]["level"] == "SL" for s in t["statements"])
    cat = [{"reference": "R1", "suits_topics": ["C1.2"]}, {"reference": "R2", "suits_topics": ["A1.1"]}]
    assert coverage.choose_case_study(cat, TARGET, c, 2)["reference"] == "R2"
    c["refs"]["R2"] = 2
    assert coverage.choose_case_study(cat, TARGET, c, 2)["reference"] == "R1"
    c["refs"]["R1"] = 2
    assert coverage.choose_case_study(cat, TARGET, c, 2) is None
    with pytest.raises(ValueError):
        coverage.choose_target(c, SYL, CFG, statements=["A3.2.1"])


class FakeGemini:
    """Replays canned replies, so the write/repair/review loop can be tested without the API."""
    model = "fake"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def ask(self, contents, schema, temperature=None):
        self.calls += 1
        r = self.replies.pop(0)
        return schema.model_validate(r)


def run_fake(replies):
    gem = FakeGemini(replies)
    log = {"steps": []}
    q, result = generate.write_one(gem, TARGET, None, [], cov(), SYL, CTS, CFG, "", [], log)
    return q, result, gem


def test_loop_repairs_then_passes_review():
    good_d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    bad = copy.deepcopy(good_d)
    bad["parts"][2]["marks"] = 2
    q, result, gem = run_fake([bad, good_d, {"passed": True, "problems": [], "fixes": []}])
    assert result == "passed" and q and gem.calls == 3


def test_loop_gives_up_after_repairs():
    bad = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    bad["parts"][2]["marks"] = 2
    q, result, gem = run_fake([bad] * (CFG["repair_attempts"] + 1))
    assert q is None and result == "failed the checks" and gem.calls == CFG["repair_attempts"] + 1


def test_loop_rejected_twice_by_reviewer():
    good_d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    no = {"passed": False, "problems": ["too easy"], "fixes": ["add a judgement"]}
    q, result, _ = run_fake([good_d, no, good_d, no])
    assert q is None and result == "failed review"


# ---------------------------------------------------------------- website requests and reviews
SAMPLE = """id: x
title: X  # a comment
status: draft
parts:
- label: a
  question: >-
    State something.
"""


def test_review_apply_changes_only_status():
    out = review_apply.apply(SAMPLE, "rejected", "Alex", "Too easy", when=datetime.date(2026, 11, 25))
    assert "title: X  # a comment" in out and "status: rejected" in out
    d = yaml.safe_load(out)
    assert d["review_history"] == [{"date": "2026-11-25", "by": "Alex", "status": "rejected", "reason": "Too easy"}]
    out2 = review_apply.apply(out, "reviewed", "Sam")
    d2 = yaml.safe_load(out2)
    assert d2["status"] == "reviewed" and len(d2["review_history"]) == 2
    assert out2.count("review_history:") == 1
    with pytest.raises(ValueError):
        review_apply.apply(SAMPLE, "deleted", "Alex")


def test_request_round_trip_and_tamper():
    import time
    salt = os.urandom(16)
    req = {"kind": "review", "sent": time.time() * 1000, "by": "Alex", "items": []}
    text = request_crypto.seal_request(req, "pw-123456", salt, 100_000)
    assert request_crypto.open_request(text, "review", "pw-123456")["by"] == "Alex"
    for bad_pw, kind in (("wrong-pass", "review"), ("pw-123456", "generate")):
        with pytest.raises(request_crypto.BadRequest):
            request_crypto.open_request(text, kind, bad_pw)
    env = json.loads(base64.b64decode(text))
    blob = bytearray(base64.b64decode(env["data"]))
    blob[-1] ^= 1
    env["data"] = base64.b64encode(bytes(blob)).decode()
    with pytest.raises(request_crypto.BadRequest):
        request_crypto.open_request(base64.b64encode(json.dumps(env).encode()).decode(), "review", "pw-123456")
    old = request_crypto.seal_request(dict(req, sent=0), "pw-123456", salt, 100_000)
    with pytest.raises(request_crypto.BadRequest):
        request_crypto.open_request(old, "review", "pw-123456")


# ---------------------------------------------------------------- Drive sign-in
def test_drive_signs_in_as_person_when_oauth_secret_set(monkeypatch):
    import fetch_drive
    monkeypatch.setenv("DRIVE_FOLDER_ID", "folder123")
    monkeypatch.setenv("GDRIVE_OAUTH_JSON", json.dumps({"client_id": "id", "client_secret": "s", "refresh_token": "r"}))
    monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_JSON", raising=False)
    svc, folder, who = fetch_drive.service()
    assert folder == "folder123" and who == "your Google account"
    creds = svc._http.credentials
    assert creds.refresh_token == "r" and creds.client_id == "id"


def test_drive_oauth_secret_must_be_complete(monkeypatch):
    import fetch_drive
    monkeypatch.setenv("DRIVE_FOLDER_ID", "folder123")
    monkeypatch.setenv("GDRIVE_OAUTH_JSON", json.dumps({"client_id": "id"}))
    with pytest.raises(SystemExit):
        fetch_drive.service()


def test_catalogue_topic_ids_accepts_names_and_ids():
    import catalogue
    assert catalogue.topic_ids(["A1.1", "B2.1 The design process", "Inclusive design", "Ergonomics (A1.1)",
                                "A3.2", "nonsense"]) == ["A1.1", "B2.1", "C1.2"]


def test_out_of_credit_is_recognised():
    import gemini

    class FakeError(Exception):
        code = 402
    assert gemini.out_of_credit(FakeError("Your prepayment credits are depleted."))
    assert not gemini.out_of_credit(ValueError("404 model not found"))


class CreditGoneGemini(FakeGemini):
    def ask(self, contents, schema, temperature=None):
        import gemini
        raise gemini.QuotaError(gemini.CREDIT_MSG)


def test_loop_passes_credit_error_up():
    import gemini
    with pytest.raises(gemini.QuotaError):
        generate.write_one(CreditGoneGemini([]), TARGET, None, [], cov(), SYL, CTS, CFG, "", [], {"steps": []})


def test_specimen_attached_to_first_writer_call_only():
    good_d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    bad = copy.deepcopy(good_d)
    bad["parts"][2]["marks"] = 2
    no = {"passed": False, "problems": ["too easy"], "fixes": ["add a judgement"]}
    yes = {"passed": True, "problems": [], "fixes": []}

    class Recording(FakeGemini):
        def ask(self, contents, schema, temperature=None):
            self.seen = getattr(self, "seen", []) + [contents]
            return super().ask(contents, schema, temperature)

    gem = Recording([bad, good_d, no, good_d, yes])   # writer, repair, review, revision, review
    q, result = generate.write_one(gem, TARGET, None, [], cov(), SYL, CTS, CFG, "", ["SPECIMEN"], {"steps": []})
    assert result == "passed"
    with_specimen = ["SPECIMEN" in c for c in gem.seen]
    assert with_specimen == [True, False, False, False, False]
