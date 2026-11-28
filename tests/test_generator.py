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


# ---------------------------------------------------------------- backup Gemini key
class _APIError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _fake_gemini(monkeypatch, behaviour):
    """A Gemini object whose client for each key follows behaviour[key]: 'ok' or 'credit'."""
    import types as pytypes
    import gemini
    from google.genai import errors

    class FakeClient:
        def __init__(self, key):
            self.key = key
            self.files = pytypes.SimpleNamespace(upload=self.upload)
            self.models = pytypes.SimpleNamespace(generate_content=self.generate)
            self.uploaded = []

        def upload(self, file, config):
            if behaviour[self.key] == "credit":
                raise _APIError(402, "Your prepayment credits are depleted.")
            self.uploaded.append(file)
            return f"{self.key}:{file}"

        def generate(self, model, contents, config):
            if behaviour[self.key] == "credit":
                raise errors.APIError(402, {"error": {"code": 402, "message": "Your prepayment credits are depleted.",
                                                      "status": "RESOURCE_EXHAUSTED"}})
            assert all(not str(c).startswith("main:") for c in contents if ":" in str(c) and "/" in str(c))
            usage = pytypes.SimpleNamespace(total_token_count=30, prompt_token_count=20, candidates_token_count=6,
                                            thoughts_token_count=4)
            return pytypes.SimpleNamespace(parsed={"passed": True, "problems": [], "fixes": []},
                                           usage_metadata=usage, contents=contents)

    monkeypatch.setenv("GEMINI_API_KEY", "main")
    monkeypatch.setenv("GEMINI_API_KEY2", "backup")
    monkeypatch.setattr(gemini.Gemini, "_make_client", lambda self, key: FakeClient(key))
    return gemini.Gemini("test-model")


def test_backup_key_used_when_main_key_out_of_credit(monkeypatch, tmp_path):
    from schema import Review
    gem = _fake_gemini(monkeypatch, {"main": "credit", "backup": "ok"})
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF")
    item = gem.upload(pdf)                       # main key refuses the upload -> switches to backup
    assert gem.key_name == "GEMINI_API_KEY2"
    result = gem.ask(["hello", item], Review)
    assert result == {"passed": True, "problems": [], "fixes": []}
    assert gem.input_tokens == 20 and gem.output_tokens == 10


def test_switches_key_mid_run_and_reuploads(monkeypatch, tmp_path):
    from schema import Review
    behaviour = {"main": "ok", "backup": "ok"}
    gem = _fake_gemini(monkeypatch, behaviour)
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF")
    item = gem.upload(pdf)
    assert gem.key_name == "GEMINI_API_KEY"
    behaviour["main"] = "credit"                 # credit runs out part-way through
    gem.ask(["hello", item], Review)
    assert gem.key_name == "GEMINI_API_KEY2" and gem.client.uploaded == [str(pdf)]


def test_quota_error_when_every_key_is_out_of_credit(monkeypatch):
    import gemini
    from schema import Review
    gem = _fake_gemini(monkeypatch, {"main": "credit", "backup": "credit"})
    with pytest.raises(gemini.QuotaError, match="every key"):
        gem.ask(["hello"], Review)


def test_backup_key_uses_backup_model_and_free_price(monkeypatch):
    from schema import Review
    import gemini
    monkeypatch.setenv("GEMINI_API_KEY", "main")
    monkeypatch.setenv("GEMINI_API_KEY2", "backup")
    gem = _fake_gemini(monkeypatch, {"main": "credit", "backup": "ok"})
    gem = gemini.Gemini("pro-model", backup_model="flash-model")
    assert gem.model == "pro-model"
    gem.ask(["hello"], Review)
    assert gem.model == "flash-model" and gem.key_name == "GEMINI_API_KEY2"
    assert gem.cost([{"input": 2, "output": 12}, {"input": 0, "output": 0}]) == 0


def test_busy_model_falls_back(monkeypatch):
    """Two 503 'high demand' replies on the backup key's model -> switch to its busy fallback and succeed."""
    import types as pytypes
    import gemini
    from google.genai import errors
    from schema import Review
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    calls = []

    class BusyClient:
        def __init__(self, key):
            self.models = pytypes.SimpleNamespace(generate_content=self.generate)
            self.files = pytypes.SimpleNamespace(upload=lambda **k: None)

        def generate(self, model, contents, config):
            calls.append(model)
            if model == "busy-flash":
                raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand",
                                                         "status": "UNAVAILABLE"}})
            usage = pytypes.SimpleNamespace(total_token_count=1, prompt_token_count=1, candidates_token_count=0,
                                            thoughts_token_count=0)
            return pytypes.SimpleNamespace(parsed={"passed": True, "problems": [], "fixes": []},
                                           usage_metadata=usage)

    monkeypatch.setenv("GEMINI_API_KEY", "main")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    monkeypatch.setattr(gemini.Gemini, "_make_client", lambda self, key: BusyClient(key))
    gem = gemini.Gemini("busy-flash", busy_fallback="older-flash")
    assert gem.ask(["hello"], Review)["passed"]
    assert calls == ["busy-flash", "busy-flash", "older-flash"] and gem.model == "older-flash"


# ---------------------------------------------------------------- call limit and reserve for the review
class CappedGemini(FakeGemini):
    """FakeGemini with a call cap, like the real wrapper's has_budget()."""

    def __init__(self, replies, max_calls):
        super().__init__(replies)
        self.max_calls = max_calls

    def has_budget(self, needed=1):
        return self.calls + needed <= self.max_calls


def test_repairs_stop_early_to_keep_a_call_for_the_review():
    good_d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    bad = copy.deepcopy(good_d)
    bad["parts"][2]["marks"] = 2
    gem = CappedGemini([bad, bad, good_d, {"passed": True, "problems": [], "fixes": []}], max_calls=3)
    log = {"steps": []}
    q, result = generate.write_one(gem, TARGET, None, [], cov(), SYL, CTS, CFG, "", [], log)
    # Old behaviour: a third call repaired it, then the review hit the cap and the good draft was lost.
    assert q is None and result == "failed the checks" and gem.calls == 2
    assert any(s["step"] == "budget" for s in log["steps"])


def test_draft_that_passes_always_gets_its_review():
    good_d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    bad = copy.deepcopy(good_d)
    bad["parts"][2]["marks"] = 2
    gem = CappedGemini([bad, good_d, {"passed": True, "problems": [], "fixes": []}], max_calls=3)
    q, result = generate.write_one(gem, TARGET, None, [], cov(), SYL, CTS, CFG, "", [], {"steps": []})
    assert result == "passed" and q and gem.calls == 3


def test_refusals_and_retries_do_not_count_towards_the_cap(monkeypatch):
    """A 402 on the main key and two 503s on the backup model are requests, not answered calls."""
    import types as pytypes
    import gemini
    from google.genai import errors
    from schema import Review
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    sent = []

    class Client:
        def __init__(self, key):
            self.key = key
            self.models = pytypes.SimpleNamespace(generate_content=self.generate)
            self.files = pytypes.SimpleNamespace(upload=lambda **k: None)

        def generate(self, model, contents, config):
            sent.append((self.key, model))
            if self.key == "main":
                raise errors.APIError(402, {"error": {"code": 402, "message": "Your prepayment credits are depleted.",
                                                      "status": "RESOURCE_EXHAUSTED"}})
            if model == "busy-flash":
                raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand",
                                                         "status": "UNAVAILABLE"}})
            usage = pytypes.SimpleNamespace(total_token_count=1, prompt_token_count=1, candidates_token_count=0,
                                            thoughts_token_count=0)
            return pytypes.SimpleNamespace(parsed={"passed": True, "problems": [], "fixes": []},
                                           usage_metadata=usage)

    monkeypatch.setenv("GEMINI_API_KEY", "main")
    monkeypatch.setenv("GEMINI_API_KEY2", "backup")
    monkeypatch.setattr(gemini.Gemini, "_make_client", lambda self, key: Client(key))
    gem = gemini.Gemini("pro", max_calls=1, backup_model="busy-flash", backup_busy_fallback="older-flash")
    assert gem.ask(["hello"], Review)["passed"]
    assert len(sent) == 4 and gem.attempts == 4 and gem.calls == 1
    assert not gem.has_budget(1)
    with pytest.raises(gemini.QuotaError, match="limit of 1"):
        gem.ask(["again"], Review)


def test_writer_prompt_states_the_checker_limits():
    t10 = dict(TARGET, marks=10)
    text = generate.writer_prompt(t10, None, [], cov(), SYL, "")
    lo, hi = extra_checks.WORDS[10]
    assert f"between {lo} and {hi} words" in text
    assert "never" in text and '"Calculate"' in text
    assert "[4] needs 5 or more" in text


# ---------------------------------------------------------------- product photo and command terms
def _jpeg(path, size=(400, 300)):
    from PIL import Image
    Image.new("RGB", size, (200, 120, 40)).save(path, "JPEG")
    return path


def _photo(tmp_path):
    import hashlib
    path = _jpeg(tmp_path / "photo.jpg")
    return {"path": path, "upload": "PHOTO", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "note": "A camping stool made by the students", "credit": "Photo: A. Teacher"}


def _photo_draft():
    d = json.loads((ROOT / "tests" / "fixtures" / "good_draft.json").read_text())
    d["figure_caption"] = "The folding stool in use"
    d["parts"][1]["question"] = "Outline one benefit of testing the stool shown in Figure 1 with users at a campsite."
    return d


def test_photo_round_trip_and_swap_refused():
    import hashlib
    import time
    salt = os.urandom(16)
    data = b"\xff\xd8 not really a jpeg"
    req = {"kind": "generate", "sent": time.time() * 1000, "photo": {"sha256": hashlib.sha256(data).hexdigest()}}
    text = request_crypto.seal_request(req, "pw-123456", salt, 100_000)
    photo = request_crypto.seal_photo(data, "pw-123456", salt, 100_000)
    opened = request_crypto.open_request(text, "generate", "pw-123456")
    assert request_crypto.open_photo(photo, text, opened["photo"]["sha256"], "pw-123456") == data
    other = request_crypto.seal_photo(b"another photo", "pw-123456", salt, 100_000)
    with pytest.raises(request_crypto.BadRequest):
        request_crypto.open_photo(other, text, opened["photo"]["sha256"], "pw-123456")
    with pytest.raises(request_crypto.BadRequest):
        request_crypto.open_photo(photo, text, opened["photo"]["sha256"], "wrong-pass")


def test_photo_becomes_figure_1(tmp_path):
    photo = _photo(tmp_path)
    q = convert.to_question(Draft.model_validate(_photo_draft()), "stool", target=TARGET, case_study=None,
                            model="m", photo=photo)
    assert [list(b)[0] for b in q["stimulus"]][:2] == ["text", "figure"]
    fig = q["stimulus"][1]
    assert fig["figure"] == "photo.jpg" and fig["caption"] == "Figure 1: The folding stool in use"
    assert fig["credit"] == "Photo: A. Teacher" and q["source"]["photo"] == photo["sha256"][:16]
    assert convert.photo_caption("Figure 1 - a drill") == "Figure 1: A drill"
    assert convert.photo_caption(None) == "Figure 1: The product"
    assert generate.validate(q, SYL, CTS, cov(), CFG, {"photo.jpg": photo["path"]}) == []
    assert "figure file photo.jpg is missing" in " ".join(generate.validate(q, SYL, CTS, cov(), CFG))


def test_photo_question_must_refer_to_figure(tmp_path):
    photo = _photo(tmp_path)
    d = _photo_draft()
    d["parts"][1]["question"] = "Outline one benefit of testing the prototypes with users at a campsite."
    q = convert.to_question(Draft.model_validate(d), "stool", target=TARGET, case_study=None, model="m", photo=photo)
    assert any("Figure 1 is not referred to" in e for e in
               generate.validate(q, SYL, CTS, cov(), CFG, {"photo.jpg": photo["path"]}))


def test_photo_sent_with_first_draft_and_every_review(tmp_path):
    photo = _photo(tmp_path)
    no = {"passed": False, "problems": ["too easy"], "fixes": ["add a judgement"]}
    yes = {"passed": True, "problems": [], "fixes": []}

    class Recording(FakeGemini):
        def ask(self, contents, schema, temperature=None):
            self.seen = getattr(self, "seen", []) + [contents]
            return super().ask(contents, schema, temperature)

    gem = Recording([_photo_draft(), no, _photo_draft(), yes])   # writer, review, revision, review
    q, result = generate.write_one(gem, TARGET, None, [], cov(), SYL, CTS, CFG, "", ["SPECIMEN"], {"steps": []},
                                   photo)
    assert result == "passed" and q["stimulus"][1]["figure"] == "photo.jpg"
    assert ["PHOTO" in c for c in gem.seen] == [True, True, False, True]
    assert "PRODUCT IN THE ATTACHED PHOTOGRAPH" in gem.seen[0][-1] and "camping stool made by" in gem.seen[0][-1]
    assert "do not add a figure block" in gem.seen[0][-1]


def test_command_terms_target_and_check():
    t = coverage.choose_target(cov(), SYL, CFG, marks=6, command_terms=["explain", "State"],
                               allowed_terms=["Explain", "Outline", "State"])
    assert t["command_terms"] == ["Explain", "State"] and "suggested_terms" not in t
    with pytest.raises(ValueError):
        coverage.choose_target(cov(), SYL, CFG, command_terms=["Discuss"], allowed_terms=["Explain"])
    with pytest.raises(ValueError):
        coverage.choose_target(cov(), SYL, CFG, command_terms=["A", "B", "C", "D"], allowed_terms=list("ABCD"))
    c = cov()
    c["terms"].update({"Explain": 5, "State": 2})
    t2 = coverage.choose_target(c, SYL, CFG, allowed_terms=["Explain", "Outline", "State", "Analyse"])
    assert t2["suggested_terms"] == ["Analyse", "Outline", "State"]
    assert "the bank has few questions using Analyse" in generate.writer_prompt(t2, None, [], c, SYL, "")

    q = question()                                     # parts use State, Outline, Explain
    assert generate.validate(q, SYL, CTS, cov(), CFG, target=dict(TARGET, command_terms=["Explain"])) == []
    errs = generate.validate(q, SYL, CTS, cov(), CFG, target=dict(TARGET, command_terms=["Evaluate"]))
    assert any("asked for the command term 'Evaluate'" in e for e in errs)
    assert "Start at least one part with each of them" in generate.writer_prompt(
        dict(TARGET, command_terms=["Evaluate"]), None, [], cov(), SYL, "")
    assert "Discuss" not in generate.allowed_terms(CTS) and "Analyse" in generate.allowed_terms(CTS)


def test_options_from_request_with_photo(tmp_path, monkeypatch):
    import argparse
    import hashlib
    import time
    salt = os.urandom(16)
    data = _jpeg(tmp_path / "in.jpg").read_bytes()
    req = {"kind": "generate", "sent": time.time() * 1000, "by": "Alex", "count": 2, "command_terms": "Explain,State",
           "case_study": "IGNORED", "photo": {"sha256": hashlib.sha256(data).hexdigest(), "note": "n", "credit": None}}
    monkeypatch.setenv("SITE_PASSWORD", "pw-123456")
    monkeypatch.setenv("PHOTO", request_crypto.seal_photo(data, "pw-123456", salt, 100_000))
    args = argparse.Namespace(request=request_crypto.seal_request(req, "pw-123456", salt, 100_000))
    work = tmp_path / "work"
    work.mkdir()
    assert generate.options_from_request(args, work) == "Alex"
    assert Path(args.photo).read_bytes() == data and args.case_study is None and args.count == 2
    assert args.command_terms == "Explain,State" and args.product_note == "n" and args.photo_credit is None
    monkeypatch.setenv("PHOTO", "")
    with pytest.raises(ValueError):
        generate.options_from_request(argparse.Namespace(request=args.request), work)
