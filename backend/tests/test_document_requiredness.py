from __future__ import annotations

import pytest

from app.models import Action, DocumentRequirement, NoticeData, ReviewState
from app.services.semantic import normalize_notice
from app.services.text import simplified_text


def _notice(source: str, *, condition: str = "Required for application submission") -> NoticeData:
    return NoticeData(
        actions=[Action(
            step=1, action="Submit the application.", required_items=["Application form"], source_evidence=source,
        )],
        required_documents=[DocumentRequirement(
            name="Application form", required=False, condition=condition, source_evidence=source,
        )],
    )


def test_observed_four_required_documents_are_not_rendered_optional() -> None:
    source = (
        "신청 방법: 지원서, 학부연구생 지원금 신청서, 연구계획서, 개인정보 수집 및 이용 동의서를 "
        "비교과 통합 관리시스템(S plus)로 제출"
    )
    names = [
        "Application form", "Undergraduate research student grant application form", "Research plan",
        "Personal information collection and use consent form",
    ]
    notice = NoticeData(
        actions=[Action(step=1, action="Submit these documents.", required_items=names, source_evidence=source)],
        required_documents=[DocumentRequirement(
            name=name, required=False, condition="Required for application submission", source_evidence=source,
        ) for name in names],
    )

    normalized = normalize_notice(notice)

    assert [document.name for document in normalized.required_documents] == names
    assert all(document.required and document.state == ReviewState.NEEDS_REVIEW
               for document in normalized.required_documents)
    assert all(document.condition == "Required for application submission" for document in normalized.required_documents)
    assert all(document.source_evidence == source for document in normalized.required_documents)
    assert "optional" not in simplified_text(normalized)


@pytest.mark.parametrize(("source", "condition"), [
    ("지원서는 선택 제출", ""),
    ("희망자는 지원서를 제출", ""),
    ("해당자는 지원서를 제출", "If applicable"),
    ("필요 시 지원서를 제출", "When requested"),
    ("지원서를 제출할 수 있음", "Optional"),
    ("지원서를 제출하지 않아도 됨", ""),
    ("지원서는 필수 제출 아님", ""),
    ("필수 서류: 지원서, 필수는 아님", ""),
    ("외국인만 지원서를 제출", ""),
    ("외국인만 지원서를 제출", "For international students"),
    ("지원서를 제출", "If applying for additional support"),
    ("지원서를 제출", "Only when requested"),
    ("지원서를 제출", "Not required"),
    ("지원서를 제출", "Not mandatory"),
])
def test_optional_and_conditional_documents_are_preserved(source: str, condition: str) -> None:
    normalized = normalize_notice(_notice(source, condition=condition))

    assert normalized.required_documents[0].required is False
    assert normalized.required_documents[0].condition == condition


@pytest.mark.parametrize("mismatch", ["evidence", "name", "no_action"])
def test_requirement_is_not_inferred_without_exact_source_and_matching_action_item(mismatch: str) -> None:
    notice = _notice("지원서를 제출")
    if mismatch == "evidence":
        notice.actions[0].source_evidence = "신청서를 제출"
    elif mismatch == "name":
        notice.actions[0].required_items = ["Research plan"]
    else:
        notice.actions = []

    assert normalize_notice(notice).required_documents[0].required is False
