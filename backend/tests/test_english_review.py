from __future__ import annotations

import asyncio

import pytest

from app import main
from app.models import Action, Deadline, DocumentRequirement, LabeledFact, NoticeData, SourceFact
from app.services import english_review
from app.services.coverage_repair import CoverageRepairResult
from app.services.english_verification import (
    EnglishSupportDecision, EnglishSupportResult, EnglishVerificationProviderError,
)
from app.services.pipeline import PipelineResult
from app.services.text import simplified_text


def test_final_review_withholds_repair_noise_without_removing_an_independent_supported_fact(monkeypatch):
    source = "접수 마감: 2027.5.10\n성울\n지원금: 2차는 결과보고서 제출 후 지급"
    notice = NoticeData(
        actions=[Action(step=2, action="Apply by May 10, 2027.", source_evidence=source.splitlines()[0], source_page=1)],
        key_details=[LabeledFact(text="Seong-ul.", source_evidence="성울", source_page=1)],
        financial_support=[
            LabeledFact(text="Both installments require a results report.", source_evidence=source.splitlines()[2], source_page=1),
            LabeledFact(text="The second installment is paid after submitting the results report.", source_evidence=source.splitlines()[2], source_page=1),
        ],
    )

    async def verify(fields, source_text, **kwargs):
        assert source_text == source
        assert kwargs["layout_context"] == "positioned source"
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(
                id=field.id,
                status="unsupported" if field.text.startswith("Both") else "insufficient" if field.text == "Seong-ul." else "supported",
                reason="The source does not establish this meaning." if field.text.startswith(("Both", "Seong")) else "",
            ) for field in fields
        ), requests=1, input_tokens=100, output_tokens=20, total_tokens=120,
           fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", verify)
    result = asyncio.run(english_review.review_notice_english(notice, source, layout_context="positioned source"))
    digest = simplified_text(result.notice)
    assert "Seong-ul" not in digest and "Both installments" not in digest
    assert "second installment" in digest and "Apply by May 10" in digest
    assert result.notice.actions[0].step == 1
    # The supported second-installment sentence covers the same source unit
    # as the rejected overbroad sentence; only the noisy caption remains a gap.
    assert result.has_verification_gaps and result.unverified_source_units == 1
    assert result.total_tokens == 120 and result.requests == 1
    assert notice.key_details[0].text == "Seong-ul."


def test_failed_final_review_retains_evidence_but_withholds_unchecked_instructions(monkeypatch):
    source = "접수 마감: 2027.5.10"
    notice = NoticeData(
        title="Application deadline", source_facts=[SourceFact(id="F001", kind="deadline", source_text=source)],
        actions=[Action(step=1, action="Apply by May 10, 2027.", source_evidence=source, source_fact_ids=["F001"])],
        ambiguities=["Applications end tomorrow."], unverified_items=["Pay KRW 50,000 before applying."],
    )

    async def unavailable(*args, **kwargs):
        raise EnglishVerificationProviderError("Unavailable", requests=1, usage_complete=False)

    monkeypatch.setattr(english_review, "verify_english_support", unavailable)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.actions == [] and result.notice.title == "Untitled notice"
    assert result.notice.source_facts[0].source_text == source
    assert result.requests == 1 and result.total_tokens == 0 and not result.usage_complete
    assert result.has_verification_gaps and result.unverified_source_units == 1
    assert "without Korean transcription" in result.notice.unverified_items[-1]
    assert "Pay KRW" not in simplified_text(result.notice)
    assert result.notice.ambiguities == []


def test_incomplete_review_keeps_independently_classified_fields_and_reports_gap(monkeypatch):
    source = "접수 마감: 2027.5.10\n신청서 제출"
    notice = NoticeData(actions=[
        Action(step=1, action="Apply by May 10, 2027.", source_evidence=source.splitlines()[0]),
        Action(step=2, action="Submit the application form.", source_evidence=source.splitlines()[1]),
    ])

    async def incomplete(fields, *args, **kwargs):
        assert kwargs["allow_partial"] is True
        return EnglishSupportResult(decisions=(
            EnglishSupportDecision(id=fields[0].id, status="supported", reason=""),
            EnglishSupportDecision(id=fields[1].id, status="insufficient", reason="Missing classification."),
        ), requests=1, partition_complete=False,
           fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", incomplete)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert [item.action for item in result.notice.actions] == ["Apply by May 10, 2027."]
    assert result.has_verification_gaps and result.unverified_source_units == 1
    assert "response was incomplete" in result.notice.unverified_items[-1]


def test_bare_table_cells_and_generic_noise_cannot_be_approved_as_complete_facts(monkeypatch):
    source = "팀100만원\n최우수상\n성울\n지원자 제출\n융합 주제"
    notice = NoticeData(
        financial_support=[
            LabeledFact(text="KRW 1,000,000 per team.", source_evidence="팀100만원"),
            LabeledFact(text="Grand prize.", source_evidence="최우수상"),
        ], key_details=[
            LabeledFact(text="Seong-ul.", label="Additional detail", source_evidence="성울"),
            LabeledFact(text="Applicants submit the documents.", label="Additional detail", source_evidence="지원자 제출"),
            LabeledFact(text="Convergence topic.", label="Topic or option", source_evidence="융합 주제"),
        ],
    )

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.financial_support == []
    assert [item.text for item in result.notice.key_details] == ["Applicants submit the documents.", "Convergence topic."]
    assert result.has_verification_gaps


def test_program_heading_and_unpaired_neighbor_schedule_do_not_gain_action_scope(monkeypatch):
    source = "2028-1학기\n매주화요일\n만족도 조사"
    notice = NoticeData(key_details=[
        LabeledFact(text="Application period: first semester of 2028.", label="Schedule", source_evidence="2028-1학기"),
        LabeledFact(text="Every Tuesday.", label="Schedule", source_evidence="매주화요일"),
        LabeledFact(text="Take the survey to win KRW 7,000.", label="Survey", source_evidence="만족도 조사"),
    ])

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.key_details == []
    assert result.unverified_source_units == 3


def test_common_schedule_with_reviewed_event_context_remains_available(monkeypatch):
    source = "한국어 회화 프로그램\n대상: 외국인 학생\n매주화요일\n강의실: A101"
    notice = NoticeData(key_details=[
        LabeledFact(text="Conversation sessions take place every Tuesday.", label="Schedule", source_evidence="매주화요일"),
    ])

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.key_details[0].text == "Conversation sessions take place every Tuesday."


def test_topic_label_cannot_bypass_uncertain_caption_transliteration(monkeypatch):
    source = "숫불고기집\n목여탕\n성울\n도서신청"
    notice = NoticeData(key_details=[
        LabeledFact(text="Sutbul Meat Restaurant", label="Topic or option", source_evidence="숫불고기집"),
        LabeledFact(text="Mokyeo Bathhouse", label="Topic or option", source_evidence="목여탕"),
        LabeledFact(text="Seong-ul", label="Topic or option", source_evidence="성울"),
        LabeledFact(text="Book request", label="Topic or option", source_evidence="도서신청"),
    ])

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert [item.text for item in result.notice.key_details] == ["Book request"]
    assert result.has_verification_gaps


def test_section_headers_and_unpaired_schedule_or_rating_cells_are_not_digest_facts(monkeypatch):
    source = "지원 금액\n모집 대상\n온라인 진행\n2B 이상\nIM3 이상\nTOEFL\n2027\nKOR101"
    notice = NoticeData(
        financial_support=[LabeledFact(text="Funding amounts.", source_evidence="지원 금액")],
        key_details=[
            LabeledFact(text="Target audience for the recruitment.", source_evidence="모집 대상"),
            LabeledFact(text="Conducted online", label="Additional detail", source_evidence="온라인 진행"),
            LabeledFact(text="Score of 2B or higher", source_evidence="2B 이상"),
            LabeledFact(text="Score of IM3 or higher", source_evidence="IM3 이상"),
            LabeledFact(text="TOEFL", label="Eligibility detail", source_evidence="TOEFL"),
            LabeledFact(text="2027", label="Additional detail", source_evidence="2027"),
            LabeledFact(text="KOR101", label="Course code", source_evidence="KOR101"),
        ],
    )

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.financial_support == []
    assert [item.text for item in result.notice.key_details] == ["KOR101"]
    assert result.has_verification_gaps


def test_preference_label_remains_visible_and_application_quote_cannot_move_interview_documents(monkeypatch):
    source = "우대사항\n컴퓨터활용능력 1급 소지자\n인터넷 접수\n증명서는 면접 시 제출\n지원서와 계획서를 온라인 제출\n신청 시 여권과 주민등록증 제출"
    notice = NoticeData(
        eligibility=[LabeledFact(text="Holders of Level 1 computer proficiency.", label="Preference Criteria", source_evidence="컴퓨터활용능력 1급 소지자")],
        actions=[
            Action(step=1, action="Apply online.", required_items=["Graduation certificate"], source_evidence="인터넷 접수"),
            Action(step=2, action="Submit the application and proposal online.", required_items=["Application", "Proposal"], source_evidence="지원서와 계획서를 온라인 제출"),
            Action(step=3, action="Submit identity documents when applying.", required_items=["Passport", "Resident registration card"], source_evidence="신청 시 여권과 주민등록증 제출"),
        ],
    )

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.eligibility == []
    assert result.notice.key_details[0].label == "Preference Criteria"
    assert result.notice.actions[0].required_items == []
    assert result.notice.actions[1].required_items == ["Application", "Proposal"]
    assert result.notice.actions[2].required_items == ["Passport", "Resident registration card"]
    assert result.has_verification_gaps


def test_empty_final_display_does_not_call_provider(monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("No English claims need another external call.")

    monkeypatch.setattr(english_review, "verify_english_support", unexpected)
    result = asyncio.run(english_review.review_notice_english(NoticeData(
        unverified_items=["Pay KRW 50,000 before applying."], ambiguities=["Applications end tomorrow."],
    ), "신청 안내"))
    assert result.requests == 0
    assert result.notice.ambiguities == []
    assert "Pay KRW" not in simplified_text(result.notice)
    assert result.has_verification_gaps and result.unverified_source_units == 1


def test_supported_partial_clause_does_not_certify_complete_source_meaning(monkeypatch):
    source = "신청서는 이메일로 제출하며 합격자는 전화로 통보"
    notice = NoticeData(actions=[Action(step=1, action="Submit the application by email.", source_evidence=source)])

    async def approve_claim_only(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, unverified_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve_claim_only)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.actions[0].action == "Submit the application by email."
    assert result.has_verification_gaps and result.unverified_source_units == 1


def test_correct_replacement_clears_stale_gap_from_rejected_candidate(monkeypatch):
    source = "지원금 2차 지급은 결과보고서 제출 후"
    notice = NoticeData(financial_support=[
        LabeledFact(text="All payments require a final report.", source_evidence=source),
        LabeledFact(text="The second payment is made after submitting the final report.", source_evidence=source),
    ])

    async def approve_correct(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="unsupported" if field.text.startswith("All") else "supported", reason="")
            for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve_correct)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert len(result.notice.financial_support) == 1
    assert not result.has_verification_gaps and result.unverified_source_units == 0
    assert result.notice.unverified_items == []


def test_source_completeness_reviews_the_final_locally_pruned_checklist(monkeypatch):
    source = "신청 시 신분증과 사진"
    notice = NoticeData(actions=[Action(
        step=1, action="Apply for the program.", required_items=["Identity card", "Photograph"], source_evidence=source,
    )])

    async def verify_actual_display(fields, *args, **kwargs):
        assert fields[0].text == "Apply for the program."
        assert "Identity card" not in fields[0].text
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, unverified_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
           source_partition_complete=True)

    monkeypatch.setattr(english_review, "verify_english_support", verify_actual_display)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.actions[0].required_items == []
    assert result.has_verification_gaps and result.unverified_source_units == 1
    assert notice.actions[0].required_items == ["Identity card", "Photograph"]


def test_changed_protected_phrase_is_withheld_before_source_verification(monkeypatch):
    source = '주제: "(happy memories)"'
    notice = NoticeData(key_details=[LabeledFact(text="Topic: fond memories.", source_evidence=source)])

    async def verify(fields, *args, **kwargs):
        assert fields == []
        return EnglishSupportResult(decisions=(), requests=0,
                                   unverified_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", verify)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.key_details == [] and result.has_verification_gaps


def test_protected_phrase_across_source_lines_must_survive_in_english(monkeypatch):
    source = "과제 (Minimum Value\nPrototyping)\n신청서 제출"
    notice = NoticeData(key_details=[
        LabeledFact(text="Minimum viable", label="Topic", source_evidence=source.splitlines()[0]),
        LabeledFact(text="Prototyping", label="Topic", source_evidence=source.splitlines()[1]),
        LabeledFact(text="Submit the application form.", label="Application", source_evidence=source.splitlines()[2]),
    ])

    async def approve(fields, *args, **kwargs):
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
           source_partition_complete=True)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.has_verification_gaps and result.unverified_source_units == 2
    assert any(item.text == "Submit the application form." for item in result.notice.key_details)


def test_shared_quotation_preserves_independent_deadline_and_literal_topic(monkeypatch):
    source = '신청 마감 2029.10.17; 주제 "AI is Everywhere"'
    notice = NoticeData(
        deadlines=[Deadline(date="2029-10-17", description="Application deadline", source_evidence=source)],
        key_details=[LabeledFact(text="Research topic: AI is Everywhere.", source_evidence=source)],
    )

    async def approve(fields, *args, **kwargs):
        assert len(fields) == 2
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
           source_partition_complete=True)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.deadlines[0].date == "2029-10-17"
    assert result.notice.key_details[0].text == "Research topic: AI is Everywhere."
    assert not result.has_verification_gaps


def test_wrong_date_is_withheld_but_valid_range_endpoints_remain(monkeypatch):
    source = "접수 기간: 2029.10.01~2029.10.17"
    notice = NoticeData(deadlines=[
        Deadline(date="2029-10-15", description="Deadline", source_evidence=source),
        Deadline(date="2029-10-01", description="Application opens", source_evidence=source),
        Deadline(date="2029-10-17", description="Application closes", source_evidence=source),
    ])

    async def approve_valid(fields, *args, **kwargs):
        assert len(fields) == 2 and all("2029-10-15" not in field.text for field in fields)
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
           source_partition_complete=True)

    monkeypatch.setattr(english_review, "verify_english_support", approve_valid)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert [deadline.date for deadline in result.notice.deadlines] == ["2029-10-01", "2029-10-17"]
    assert not result.has_verification_gaps


def test_photo_pipeline_reports_final_review_usage_and_partial_status(monkeypatch):
    async def repair(notice, source_text, **kwargs):
        return CoverageRepairResult(notice=notice, requests=1, total_tokens=30)

    async def review(notice, source_text, **kwargs):
        assert source_text == "신청 안내"
        return english_review.EnglishNoticeReview(
            notice=notice, requests=1, input_tokens=80, output_tokens=20, total_tokens=100,
            has_verification_gaps=True, unverified_source_units=1,
        )

    monkeypatch.setattr(main, "repair_coverage", repair)
    monkeypatch.setattr(main, "review_notice_english", review)
    pipeline = PipelineResult(source_text="신청 안내", translation="", notice=NoticeData(), provider="test",
                              translation_provider="test", translation_requests=0,
                              semantic_provider="openai-semantic:gpt-4o-mini", semantic_requests=1,
                              semantic_input_tokens=10, semantic_output_tokens=0, semantic_total_tokens=10)
    result = asyncio.run(main._complete_english_coverage(pipeline, allow_partial=True))
    assert result.semantic_requests == 3 and result.semantic_total_tokens == 140
    assert result.english_coverage_status == "partial" and result.unverified_source_units == 1


def test_final_verified_candidate_clears_previous_audit_gap_without_publishing_early(monkeypatch):
    candidate = NoticeData(actions=[Action(step=1, action="Submit the form.", source_evidence="신청서 제출")])

    async def repair(notice, source_text, **kwargs):
        return CoverageRepairResult(notice=NoticeData(), review_candidates=candidate, requests=1, has_verification_gaps=True)

    async def review(notice, source_text, **kwargs):
        assert notice is candidate
        return english_review.EnglishNoticeReview(notice=candidate, requests=1)

    monkeypatch.setattr(main, "repair_coverage", repair)
    monkeypatch.setattr(main, "review_notice_english", review)
    pipeline = PipelineResult(source_text="신청서 제출", translation="", notice=NoticeData(), provider="test",
                              translation_provider="test", translation_requests=0,
                              semantic_provider="openai-semantic:gpt-4o-mini", semantic_requests=1,
                              semantic_input_tokens=10, semantic_output_tokens=0, semantic_total_tokens=10)
    result = asyncio.run(main._complete_english_coverage(pipeline, allow_partial=True))
    assert result.notice.actions[0].action == "Submit the form."
    assert result.english_coverage_status == "audited" and result.unverified_source_units == 0


@pytest.mark.parametrize("name,condition", [
    ("Graduation Certificate", ""),
    ("Degree certificate", "Submit during the interview."),
    ("Expected graduation certificate", "Submit at the interview."),
    ("Graduation or expected graduation certificate", ""),
])
def test_document_omitted_alternative_or_interview_stage_is_withheld_before_review(monkeypatch, name, condition):
    source = "졸업(예정)증명서, 성적증명서는 면접전형 시 제출"
    notice = NoticeData(required_documents=[DocumentRequirement(
        name=name, condition=condition, source_evidence="졸업(예정)증명서", source_page=1,
    )])

    async def unexpected(*args, **kwargs):
        pytest.fail("The incomplete document field must not reach semantic certification.")

    monkeypatch.setattr(english_review, "verify_english_support", unexpected)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.required_documents == []
    assert result.has_verification_gaps
    assert notice.required_documents[0].name == name


def test_document_alternatives_and_stages_survive_without_contaminating_other_documents(monkeypatch):
    source = "졸업(예정)증명서, 성적증명서는 면접전형 시 제출\n졸업증명서는 신청 시 제출"
    notice = NoticeData(required_documents=[
        DocumentRequirement(name="Graduation or expected graduation certificate", condition="Submit during the interview process.",
                            source_evidence="졸업(예정)증명서", source_page=1),
        DocumentRequirement(name="Transcript", condition="Submit at the interview.", source_evidence=source.splitlines()[0], source_page=1),
        DocumentRequirement(name="Graduation certificate", condition="Submit with the application.", source_evidence=source.splitlines()[1], source_page=1),
    ])

    async def approve(fields, *args, **kwargs):
        assert len(fields) == 3
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1, fully_covered_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
           source_partition_complete=True)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert len(result.notice.required_documents) == 3


def test_document_stage_context_does_not_cross_pages(monkeypatch):
    source = "[Page 1]\n신청 시 성적증명서 제출\n[Page 2]\n성적증명서는 면접 시 제출"
    notice = NoticeData(required_documents=[DocumentRequirement(
        name="Transcript", condition="Submit with the application.", source_evidence="성적증명서", source_page=1,
    )])

    async def approve(fields, *args, **kwargs):
        assert len(fields) == 1
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert len(result.notice.required_documents) == 1


@pytest.mark.parametrize("source,condition,kept", [
    ("신분증은 면접 전 제출", "Submit before the interview.", True),
    ("신분증은 면접 후 제출", "Submit after the interview.", True),
    ("신분증은 면접 전 제출", "Submit during the interview.", False),
    ("신분증은 면접 후 제출", "Submit before the interview.", False),
])
def test_document_interview_timing_preserves_before_and_after(source, condition, kept):
    notice = NoticeData(required_documents=[DocumentRequirement(name="Identity document", condition=condition, source_evidence=source)])
    prepared, gaps = english_review._prepare_review_notice(notice, source)
    assert bool(prepared.required_documents) is kept
    assert gaps is not kept


def test_expense_noun_fragment_cannot_become_a_restriction(monkeypatch):
    source = "교통비를 제외한 숙박 비용\n지원금은 인쇄비에만 사용 가능\n인쇄비 외 사용 금지"
    notice = NoticeData(key_details=[
        LabeledFact(text="Accommodation costs excluding transportation.", label="Restriction", source_evidence=source.splitlines()[0]),
        LabeledFact(text="Funding can be used only for printing expenses.", label="Restriction", source_evidence=source.splitlines()[1]),
        LabeledFact(text="Use for costs other than printing is prohibited.", label="Restriction", source_evidence=source.splitlines()[2]),
    ])

    async def approve(fields, *args, **kwargs):
        assert len(fields) == 2 and all("Accommodation" not in field.text for field in fields)
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert [item.text for item in result.notice.key_details] == [item.text for item in notice.key_details[1:]]


@pytest.mark.parametrize("source,text,label", [
    ("4.16(수) 오후", "April 16 (Wed), afternoon.", "Additional detail"),
    ("2033.08.12", "August 12, 2033", "Schedule"),
    ("14:30", "14:30", "Additional detail"),
    ("오후 2시", "2 PM", "Schedule"),
    ("7문항 내외", "Approximately 7 questions", "Additional detail"),
    ("총 5문제", "5 questions in total", "Additional detail"),
])
def test_detached_date_time_and_question_cells_are_withheld(monkeypatch, source, text, label):
    notice = NoticeData(key_details=[LabeledFact(text=text, label=label, source_evidence=source)])

    async def approve(fields, *args, **kwargs):
        assert fields == []
        return EnglishSupportResult(decisions=(), requests=0,
                                   unverified_source_ids=frozenset(unit.id for unit in kwargs["source_units"]))

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert result.notice.key_details == [] and result.has_verification_gaps


def test_complete_exam_event_and_named_schedule_remain_reviewable(monkeypatch):
    source = "논술시험:2033.08.12오후,7문항내외\n면접일:2033.08.16오전10:00"
    notice = NoticeData(key_details=[
        LabeledFact(text="The essay exam is on August 12, 2033, in the afternoon, with approximately 7 questions.",
                    label="Schedule", source_evidence=source.splitlines()[0]),
        LabeledFact(text="August 16, 2033, at 10:00 AM", label="Interview date", source_evidence=source.splitlines()[1]),
    ])

    async def approve(fields, *args, **kwargs):
        assert len(fields) == 2
        return EnglishSupportResult(decisions=tuple(
            EnglishSupportDecision(id=field.id, status="supported", reason="") for field in fields
        ), requests=1)

    monkeypatch.setattr(english_review, "verify_english_support", approve)
    result = asyncio.run(english_review.review_notice_english(notice, source))
    assert len(result.notice.key_details) == 2
