from app.models import LabeledFact, NoticeData, ReviewState, SourceFact
from app.services.coverage import audit_coverage
from app.services.source_grounding import retain_source_grounded_items
from app.services.text import simplified_text


def test_invented_evidence_cannot_survive_beside_correct_repair() -> None:
    source = "휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외"
    notice = NoticeData(
        eligibility=[LabeledFact(
            text="Participants who are leaving students can join.",
            source_evidence=source.replace("휴학생", "미래세대"), source_fact_ids=["F001"],
        )],
        source_facts=[SourceFact(id="F001", kind="eligibility", source_text=source.replace("휴학생", "미래세대"))],
    )
    grounded = retain_source_grounded_items(notice, source)
    assert grounded.eligibility == []
    assert grounded.source_facts == []
    assert [unit.text for unit in audit_coverage(grounded, source).uncovered] == [source]
    assert len(notice.eligibility) == 1


def test_source_backed_item_regains_related_exact_evidence_without_invented_ids() -> None:
    source = "모집 대상: 학부 재학생\n세부 주제는 공고 확인 필수"
    notice = NoticeData(
        key_details=[LabeledFact(
            text="Check the announcement for detailed topics.", source_evidence="세부 주제는 공고 확인 필수",
            source_fact_ids=["F001", "F099"], source_page=1,
        )],
        source_facts=[SourceFact(id="F001", kind="audience", source_text="모집 대상: 학부 재학생")],
    )
    grounded = retain_source_grounded_items(notice, source)
    item = grounded.key_details[0]
    assert item.source_fact_ids == ["F002"]
    assert item.state == ReviewState.NEEDS_REVIEW
    assert grounded.source_facts[-1].source_text == item.source_evidence
    assert grounded.source_facts[-1].source_page == 1
    assert grounded.source_facts[0].id == "F001"


def test_exact_evidence_and_related_ids_survive_page_and_spacing_variation() -> None:
    source = "[Page 1]\n지원서 제출\n[Page 2]\n지원서 제출"
    notice = NoticeData(
        actions=[{"step": 1, "action": "Submit the application.", "source_evidence": "지원서  제출", "source_fact_ids": ["F001"]}],
        source_facts=[SourceFact(id="F001", kind="application", source_text="지원서 제출")],
    )
    grounded = retain_source_grounded_items(notice, source)
    assert grounded.actions[0].source_fact_ids == ["F001"]
    assert grounded.actions[0].source_page is None
    assert grounded.actions[0].state == ReviewState.VERIFIED
    assert len(grounded.source_facts) == 1


def test_missing_or_paraphrased_evidence_requires_a_fresh_source_audit() -> None:
    source = "세부 주제는 공고 확인 필수"
    notice = NoticeData(key_details=[
        LabeledFact(text="Check topics.", source_evidence="자세한 주제는 공고 확인 필수"),
        LabeledFact(text="Unsupported claim."),
    ])
    grounded = retain_source_grounded_items(notice, source)
    assert grounded.key_details == []
    assert audit_coverage(grounded, source).uncovered


def test_audited_application_detail_does_not_imply_no_action_is_required() -> None:
    notice = NoticeData(key_details=[LabeledFact(
        text="Submit the application through S Plus.", label="Application detail",
        source_evidence="지원서를 S Plus로 제출",
    )])
    digest = simplified_text(notice)
    assert "Submit the application through S Plus." in digest
    assert "No required action" not in digest
    assert "informational" not in digest


def test_rejected_invented_action_does_not_leave_a_gap_in_presentation_steps() -> None:
    notice = NoticeData(actions=[
        {"step": 1, "action": "Pay a fee.", "source_evidence": "수수료 납부"},
        {"step": 2, "action": "Submit the application.", "source_evidence": "지원서 제출"},
    ])
    grounded = retain_source_grounded_items(notice, "지원서 제출")
    assert len(grounded.actions) == 1
    assert grounded.actions[0].step == 1
    assert grounded.actions[0].action == "Submit the application."


def test_real_quote_on_the_wrong_page_cannot_ground_a_claim() -> None:
    source = "[Page 1]\n신청서 제출\n[Page 2]\n참가비 1만원"
    notice = NoticeData(
        fees=[LabeledFact(text="Pay KRW 99,000.", source_evidence="참가비 1만원", source_page=1)],
        source_facts=[SourceFact(id="F001", kind="fee", source_text="참가비 1만원", source_page=1)],
    )
    grounded = retain_source_grounded_items(notice, source)
    assert grounded.fees == []
    assert grounded.source_facts == []


def test_matching_page_quote_is_retained_without_borrowing_another_pages_fact_id() -> None:
    source = "[Page 1]\n신청서 제출\n[Page 2]\n신청서 제출"
    notice = NoticeData(
        key_details=[LabeledFact(text="Submit the application.", source_evidence="신청서 제출", source_page=2, source_fact_ids=["F001"])],
        source_facts=[SourceFact(id="F001", kind="application", source_text="신청서 제출", source_page=1)],
    )
    grounded = retain_source_grounded_items(notice, source)
    assert grounded.key_details[0].source_page == 2
    assert grounded.key_details[0].source_fact_ids == ["F002"]
    assert grounded.source_facts[-1].source_page == 2
