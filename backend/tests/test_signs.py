"""Warning signs: +10 trust each, at most +30, each a plain reason line."""
from app.services.corroboration import Evidence, score_evidence
from app.services.signs import clean, from_words


def test_each_sign_adds_ten_with_a_plain_reason():
    score, reasons = score_evidence(Evidence(signs=["crack", "sound"]))
    assert score == 20
    assert [r["text"] for r in reasons] == ["Villager saw new cracks in the ground or walls",
                                            "Villager saw rumbling or cracking sounds"]
    assert all(r["points"] == 10 for r in reasons)


def test_signs_are_capped_at_thirty():
    score, reasons = score_evidence(Evidence(signs=["crack", "spring", "tilt", "sound", "stones", "sinking"]))
    assert score == 30 and len(reasons) == 3


def test_unknown_and_repeated_signs_are_ignored():
    assert clean(["crack", "crack", "lava", "tilt"]) == ["crack", "tilt"]
    assert from_words(["Cracks", "near", "the", "ROCK"]) == ["crack"]


def test_one_persons_own_report_cannot_pass_sixty():
    score, reasons = score_evidence(Evidence(is_sos=True, has_photo=True, signs=["crack", "sound", "spring"]))
    assert score == 60                                        # 40 + 5 + 30 = 75, capped
    assert reasons[-1]["key"] == "self_cap" and reasons[-1]["points"] == -15
    # independent evidence still counts on top
    score, _ = score_evidence(Evidence(is_sos=True, has_photo=True, signs=["crack", "sound", "spring"],
                                       zone_severity="HIGH", zone_name="Z"))
    assert score == 90


def test_the_crowd_rule_needs_different_phones():
    from app.services.corroboration import CLUSTER_MIN_PHONES
    assert score_evidence(Evidence(independent_phones=CLUSTER_MIN_PHONES - 1))[0] == 0
    assert score_evidence(Evidence(independent_phones=CLUSTER_MIN_PHONES))[0] == 25
