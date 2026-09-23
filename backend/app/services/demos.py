from __future__ import annotations

from dataclasses import dataclass

from app.models import (
    Action,
    Contact,
    Deadline,
    DemoQuestion,
    DocumentRequirement,
    LabeledFact,
    NoticeData,
    SourceFact,
)


@dataclass(frozen=True)
class DemoNotice:
    id: str
    original_text: str
    translation: str
    notice: NoticeData
    questions: list[DemoQuestion]


def fact(fact_id: str, kind: str, source: str, critical: bool = True) -> SourceFact:
    return SourceFact(id=fact_id, kind=kind, source_text=source, critical=critical)


def labeled(text: str, evidence: str, fact_id: str, label: str = "") -> LabeledFact:
    return LabeledFact(text=text, label=label, source_evidence=evidence, source_fact_ids=[fact_id])


DEMOS: list[DemoNotice] = [
    DemoNotice(
        id="demo-visa-2026",
        original_text="""[가상 예시] 외국인 유학생 체류기간 연장 안내
대상: 체류기간이 2026년 9월 30일에 만료되는 D-2 재학생
신청 기간: 2026년 9월 1일(화) ~ 9월 25일(금) 17:00
제출 서류: 여권, 외국인등록증, 재학증명서, 체류지 입증서류
신청 방법: 1. 하이코리아에서 방문 예약 2. 서류 준비 3. 예약일에 한빛출입국사무소 방문
주의: 휴학생은 학교 담당자에게 먼저 문의하십시오.
문의: 국제학생지원팀 02-1234-5678, global@example.edu""",
        translation="""[Fictional example] Notice on Extension of Stay for International Students
Eligible students: Enrolled D-2 students whose period of stay expires on September 30, 2026.
Application period: September 1, 2026 (Tuesday) to September 25, 2026 (Friday), 5:00 p.m.
Documents to submit: passport, Residence Card, certificate of enrollment, and proof of residence.
How to apply: 1. Reserve a visit through HiKorea. 2. Prepare the documents. 3. Visit Hanbit Immigration Office on the reserved date.
Note: Students on a leave of absence must first contact the university staff member.
Contact: International Student Support Team, 02-1234-5678, global@example.edu""",
        notice=NoticeData(
            title="Extension of Stay for International Students",
            notice_type="Visa / immigration",
            audience=[labeled("Enrolled D-2 students whose stay expires on September 30, 2026", "체류기간이 2026년 9월 30일에 만료되는 D-2 재학생", "F001")],
            purpose="Explain how eligible D-2 students can extend their period of stay.",
            summary="Apply for an extension of stay before the application period closes.",
            deadlines=[Deadline(date="September 1–25, 2026", time="By 5:00 p.m. on September 25", description="Application period", source_evidence="신청 기간: 2026년 9월 1일(화) ~ 9월 25일(금) 17:00", source_fact_ids=["F002"])],
            required_documents=[
                DocumentRequirement(name="Passport", source_evidence="여권", source_fact_ids=["F003"]),
                DocumentRequirement(name="Residence Card", source_evidence="외국인등록증", source_fact_ids=["F004"]),
                DocumentRequirement(name="Certificate of enrollment", source_evidence="재학증명서", source_fact_ids=["F005"]),
                DocumentRequirement(name="Proof of residence", source_evidence="체류지 입증서류", source_fact_ids=["F006"]),
            ],
            actions=[
                Action(step=1, action="Reserve a visit through HiKorea.", source_evidence="하이코리아에서 방문 예약", source_fact_ids=["F007"]),
                Action(step=2, action="Prepare all required documents.", required_items=["Passport", "Residence Card", "Certificate of enrollment", "Proof of residence"], source_evidence="서류 준비", source_fact_ids=["F008"]),
                Action(step=3, action="Visit Hanbit Immigration Office on your reserved date.", location="Hanbit Immigration Office", source_evidence="예약일에 한빛출입국사무소 방문", source_fact_ids=["F009"]),
            ],
            exceptions=[labeled("If you are on a leave of absence, contact the university staff member first.", "휴학생은 학교 담당자에게 먼저 문의하십시오", "F010")],
            locations=[labeled("Hanbit Immigration Office", "한빛출입국사무소", "F011")],
            contacts=[Contact(name="International Student Support Team", phone="02-1234-5678", email="global@example.edu", source_evidence="국제학생지원팀 02-1234-5678, global@example.edu", source_fact_ids=["F012"])],
            source_facts=[
                fact("F001", "audience", "체류기간이 2026년 9월 30일에 만료되는 D-2 재학생"), fact("F002", "deadline", "2026년 9월 1일(화) ~ 9월 25일(금) 17:00"),
                fact("F003", "document", "여권"), fact("F004", "document", "외국인등록증"), fact("F005", "document", "재학증명서"), fact("F006", "document", "체류지 입증서류"),
                fact("F007", "action", "하이코리아에서 방문 예약"), fact("F008", "action", "서류 준비"), fact("F009", "action", "예약일에 한빛출입국사무소 방문"),
                fact("F010", "exception", "휴학생은 학교 담당자에게 먼저 문의하십시오"), fact("F011", "location", "한빛출입국사무소", False), fact("F012", "contact", "국제학생지원팀 02-1234-5678, global@example.edu", False),
            ],
        ),
        questions=[
            DemoQuestion(id="q1", prompt="When does the application period close?", expected_answer="September 25, 2026 at 5:00 p.m.", critical_fact_id="F002"),
            DemoQuestion(id="q2", prompt="Who is this notice for?", expected_answer="Enrolled D-2 students whose stay expires September 30, 2026", critical_fact_id="F001"),
            DemoQuestion(id="q3", prompt="Where must the student visit?", expected_answer="Hanbit Immigration Office", critical_fact_id="F009"),
        ],
    ),
    DemoNotice(
        id="demo-tuition-2026",
        original_text="""[가상 예시] 2026학년도 2학기 등록금 납부 안내
대상: 2026학년도 2학기 재학생
납부 기간: 2026년 8월 24일(월) 09:00 ~ 8월 28일(금) 16:00
납부 방법: 학생포털에서 고지서를 확인한 후 지정된 가상계좌로 이체
분할 납부 신청자는 1차 금액만 납부하십시오.
기한 내 미납 시 수강신청이 취소될 수 있습니다.
문의: 재무팀 02-2345-6789""",
        translation="""[Fictional example] Fall 2026 Tuition Payment Notice
Eligible students: Students enrolled in the fall 2026 semester.
Payment period: August 24, 2026 at 9:00 a.m. through August 28, 2026 at 4:00 p.m.
Payment method: Check the bill in the student portal, then transfer payment to the assigned virtual account.
Students approved for installment payments should pay only the first installment.
Failure to pay by the deadline may result in course registration being canceled.
Contact: Finance Team, 02-2345-6789.""",
        notice=NoticeData(
            title="Fall 2026 Tuition Payment",
            notice_type="Tuition payment",
            audience=[labeled("Students enrolled in the fall 2026 semester", "2026학년도 2학기 재학생", "F001")],
            purpose="Explain the tuition payment period and method.",
            summary="Check your tuition bill and pay the assigned virtual account by the deadline.",
            deadlines=[Deadline(date="August 24–28, 2026", time="9:00 a.m. opening; 4:00 p.m. closing", description="Tuition payment period", source_evidence="2026년 8월 24일(월) 09:00 ~ 8월 28일(금) 16:00", source_fact_ids=["F002"])],
            actions=[
                Action(step=1, action="Check your tuition bill in the student portal.", source_evidence="학생포털에서 고지서를 확인", source_fact_ids=["F003"]),
                Action(step=2, action="Transfer the payment to the assigned virtual account.", deadline="August 28, 2026 at 4:00 p.m.", source_evidence="지정된 가상계좌로 이체", source_fact_ids=["F004"]),
            ],
            exceptions=[labeled("If you are approved for installment payments, pay only the first installment.", "분할 납부 신청자는 1차 금액만 납부하십시오", "F005")],
            consequences=[labeled("Course registration may be canceled if payment is late.", "기한 내 미납 시 수강신청이 취소될 수 있습니다", "F006")],
            contacts=[Contact(name="Finance Team", phone="02-2345-6789", source_evidence="재무팀 02-2345-6789", source_fact_ids=["F007"])],
            source_facts=[fact("F001", "audience", "2026학년도 2학기 재학생"), fact("F002", "deadline", "2026년 8월 24일(월) 09:00 ~ 8월 28일(금) 16:00"), fact("F003", "action", "학생포털에서 고지서를 확인"), fact("F004", "action", "지정된 가상계좌로 이체"), fact("F005", "exception", "분할 납부 신청자는 1차 금액만 납부하십시오"), fact("F006", "consequence", "기한 내 미납 시 수강신청이 취소될 수 있습니다"), fact("F007", "contact", "재무팀 02-2345-6789", False)],
        ),
        questions=[DemoQuestion(id="q1", prompt="What is the payment deadline?", expected_answer="August 28, 2026 at 4:00 p.m.", critical_fact_id="F002"), DemoQuestion(id="q2", prompt="What may happen after late payment?", expected_answer="Course registration may be canceled", critical_fact_id="F006")],
    ),
    DemoNotice(
        id="demo-scholarship-2026",
        original_text="""[가상 예시] 글로벌 리더 장학금 신청
신청 자격: 직전 학기 12학점 이상 이수하고 평점 3.5 이상인 외국인 학부 재학생
신청 기간: 2026년 10월 5일 ~ 10월 16일 18:00
필수 서류: 신청서, 성적증명서, 자기소개서
선택 서류: 봉사활동 증명서
이메일 scholarship@example.edu로 PDF 파일을 제출하십시오.
교환학생은 신청할 수 없습니다.""",
        translation="""[Fictional example] Global Leader Scholarship Application
Eligibility: International undergraduate students who completed at least 12 credits in the previous semester and have a GPA of 3.5 or higher.
Application period: October 5 through October 16, 2026 at 6:00 p.m.
Required documents: application form, academic transcript, and personal statement.
Optional document: volunteer service certificate.
Submit PDF files to scholarship@example.edu.
Exchange students may not apply.""",
        notice=NoticeData(
            title="Global Leader Scholarship Application", notice_type="Scholarship",
            audience=[labeled("International undergraduate students", "외국인 학부 재학생", "F001")],
            purpose="Invite eligible international undergraduate students to apply for a scholarship.", summary="Eligible students can submit a PDF application by email.",
            eligibility=[labeled("You must have completed at least 12 credits in the previous semester and have a GPA of 3.5 or higher.", "직전 학기 12학점 이상 이수하고 평점 3.5 이상", "F002")],
            deadlines=[Deadline(date="October 16, 2026", time="6:00 p.m.", description="Application deadline", source_evidence="2026년 10월 5일 ~ 10월 16일 18:00", source_fact_ids=["F003"])],
            required_documents=[
                DocumentRequirement(name="Application form", source_evidence="신청서", source_fact_ids=["F004"]), DocumentRequirement(name="Academic transcript", source_evidence="성적증명서", source_fact_ids=["F005"]), DocumentRequirement(name="Personal statement", source_evidence="자기소개서", source_fact_ids=["F006"]),
                DocumentRequirement(name="Volunteer service certificate", required=False, condition="Optional", source_evidence="선택 서류: 봉사활동 증명서", source_fact_ids=["F007"]),
            ],
            actions=[Action(step=1, action="Prepare the required documents as PDF files.", source_evidence="PDF 파일", source_fact_ids=["F008"]), Action(step=2, action="Email the files to scholarship@example.edu.", deadline="October 16, 2026 at 6:00 p.m.", source_evidence="이메일 scholarship@example.edu로 PDF 파일을 제출", source_fact_ids=["F009"])],
            exceptions=[labeled("Exchange students cannot apply.", "교환학생은 신청할 수 없습니다", "F010")],
            contacts=[Contact(email="scholarship@example.edu", source_evidence="scholarship@example.edu", source_fact_ids=["F011"])],
            source_facts=[fact("F001", "audience", "외국인 학부 재학생"), fact("F002", "eligibility", "직전 학기 12학점 이상 이수하고 평점 3.5 이상"), fact("F003", "deadline", "2026년 10월 5일 ~ 10월 16일 18:00"), fact("F004", "document", "신청서"), fact("F005", "document", "성적증명서"), fact("F006", "document", "자기소개서"), fact("F007", "document_optional", "선택 서류: 봉사활동 증명서"), fact("F008", "format", "PDF 파일", False), fact("F009", "action", "이메일 scholarship@example.edu로 PDF 파일을 제출"), fact("F010", "exception", "교환학생은 신청할 수 없습니다"), fact("F011", "contact", "scholarship@example.edu", False)],
        ),
        questions=[DemoQuestion(id="q1", prompt="What is the minimum GPA?", expected_answer="3.5", critical_fact_id="F002"), DemoQuestion(id="q2", prompt="Is the volunteer certificate required?", expected_answer="No, it is optional", critical_fact_id="F007"), DemoQuestion(id="q3", prompt="Who cannot apply?", expected_answer="Exchange students", critical_fact_id="F010")],
    ),
    DemoNotice(
        id="demo-dormitory-2027",
        original_text="""[가상 예시] 2027학년도 1학기 기숙사 신청 안내
대상: 신입 외국인 학생 및 현재 기숙사에 거주하지 않는 재학생
신청: 2026년 12월 7일 10:00 ~ 12월 11일 15:00
학생포털 > 생활관 > 입사신청에서 신청하십시오.
신입생은 여권 사본을, 재학생은 결핵검사 결과서를 제출해야 합니다.
결과 발표: 2026년 12월 18일 14:00 학생포털
기한 후 신청은 받지 않습니다.""",
        translation="""[Fictional example] Spring 2027 Dormitory Application Notice
Eligible students: New international students and enrolled students who do not currently live in the dormitory.
Apply from December 7, 2026 at 10:00 a.m. to December 11, 2026 at 3:00 p.m.
Apply through Student Portal > Dormitory > Residence Application.
New students must submit a passport copy. Enrolled students must submit tuberculosis test results.
Results will be posted in the student portal on December 18, 2026 at 2:00 p.m.
Late applications are not accepted.""",
        notice=NoticeData(
            title="Spring 2027 Dormitory Application", notice_type="Dormitory",
            audience=[labeled("New international students and enrolled students who do not currently live in the dormitory", "신입 외국인 학생 및 현재 기숙사에 거주하지 않는 재학생", "F001")],
            purpose="Explain how eligible students can apply for the dormitory.", summary="Apply through the student portal and submit the document required for your student status.",
            deadlines=[Deadline(date="December 7–11, 2026", time="10:00 a.m. opening; 3:00 p.m. closing", description="Application period", source_evidence="2026년 12월 7일 10:00 ~ 12월 11일 15:00", source_fact_ids=["F002"]), Deadline(date="December 18, 2026", time="2:00 p.m.", description="Results posted in student portal", source_evidence="결과 발표: 2026년 12월 18일 14:00 학생포털", source_fact_ids=["F003"])],
            required_documents=[DocumentRequirement(name="Passport copy", condition="Required for new students", source_evidence="신입생은 여권 사본", source_fact_ids=["F004"]), DocumentRequirement(name="Tuberculosis test results", condition="Required for enrolled students", source_evidence="재학생은 결핵검사 결과서", source_fact_ids=["F005"])],
            eligibility=[labeled("If you are an enrolled student, you must not currently live in the dormitory.", "현재 기숙사에 거주하지 않는 재학생", "F006")],
            actions=[Action(step=1, action="Open Student Portal > Dormitory > Residence Application.", source_evidence="학생포털 > 생활관 > 입사신청", source_fact_ids=["F007"]), Action(step=2, action="Complete the application and submit the document for your student status.", deadline="December 11, 2026 at 3:00 p.m.", source_evidence="신청하십시오", source_fact_ids=["F008"])],
            warnings=[labeled("Late applications are not accepted.", "기한 후 신청은 받지 않습니다", "F009")],
            source_facts=[fact("F001", "audience", "신입 외국인 학생 및 현재 기숙사에 거주하지 않는 재학생"), fact("F002", "deadline", "2026년 12월 7일 10:00 ~ 12월 11일 15:00"), fact("F003", "date", "2026년 12월 18일 14:00 학생포털"), fact("F004", "document_conditional", "신입생은 여권 사본"), fact("F005", "document_conditional", "재학생은 결핵검사 결과서"), fact("F006", "eligibility", "현재 기숙사에 거주하지 않는 재학생"), fact("F007", "action", "학생포털 > 생활관 > 입사신청"), fact("F008", "action", "신청하십시오"), fact("F009", "warning", "기한 후 신청은 받지 않습니다")],
        ),
        questions=[DemoQuestion(id="q1", prompt="When does the application close?", expected_answer="December 11, 2026 at 3:00 p.m.", critical_fact_id="F002"), DemoQuestion(id="q2", prompt="What document must a new student submit?", expected_answer="A passport copy", critical_fact_id="F004")],
    ),
    DemoNotice(
        id="demo-courses-2027",
        original_text="""[가상 예시] 2027학년도 1학기 수강신청 일정
재학생 신청: 2027년 2월 15일 09:00 ~ 2월 17일 17:00
신입생 신청: 2027년 2월 19일 09:00 ~ 17:00
정정 기간: 2027년 3월 2일 09:00 ~ 3월 5일 18:00
수강신청 시스템에서 본인이 직접 신청하십시오.
수강 정원을 초과한 과목은 신청할 수 없습니다.
문의: 학사지원팀 registrar@example.edu""",
        translation="""[Fictional example] Spring 2027 Course Registration Schedule
Enrolled-student registration: February 15, 2027 at 9:00 a.m. through February 17 at 5:00 p.m.
New-student registration: February 19, 2027 from 9:00 a.m. to 5:00 p.m.
Add/drop period: March 2, 2027 at 9:00 a.m. through March 5 at 6:00 p.m.
Register by yourself in the course registration system.
You cannot register for a course that has reached capacity.
Contact: Academic Affairs Support Team, registrar@example.edu.""",
        notice=NoticeData(
            title="Spring 2027 Course Registration", notice_type="Course registration", purpose="Provide course registration dates for new and enrolled students.", summary="Use the course registration system during the period for your student status.",
            deadlines=[Deadline(date="February 15–17, 2027", time="9:00 a.m. opening; 5:00 p.m. closing", description="Enrolled-student registration", source_evidence="재학생 신청: 2027년 2월 15일 09:00 ~ 2월 17일 17:00", source_fact_ids=["F001"]), Deadline(date="February 19, 2027", time="9:00 a.m.–5:00 p.m.", description="New-student registration", source_evidence="신입생 신청: 2027년 2월 19일 09:00 ~ 17:00", source_fact_ids=["F002"]), Deadline(date="March 2–5, 2027", time="9:00 a.m. opening; 6:00 p.m. closing", description="Add/drop period", source_evidence="정정 기간: 2027년 3월 2일 09:00 ~ 3월 5일 18:00", source_fact_ids=["F003"])],
            actions=[Action(step=1, action="Identify the registration period for your student status.", source_evidence="재학생 신청 / 신입생 신청", source_fact_ids=["F004"]), Action(step=2, action="Register in the course registration system yourself.", source_evidence="수강신청 시스템에서 본인이 직접 신청", source_fact_ids=["F005"])],
            warnings=[labeled("You cannot register for a course that has reached capacity.", "수강 정원을 초과한 과목은 신청할 수 없습니다", "F006")],
            contacts=[Contact(name="Academic Affairs Support Team", email="registrar@example.edu", source_evidence="학사지원팀 registrar@example.edu", source_fact_ids=["F007"])],
            source_facts=[fact("F001", "deadline", "재학생 신청: 2027년 2월 15일 09:00 ~ 2월 17일 17:00"), fact("F002", "deadline", "신입생 신청: 2027년 2월 19일 09:00 ~ 17:00"), fact("F003", "deadline", "정정 기간: 2027년 3월 2일 09:00 ~ 3월 5일 18:00"), fact("F004", "action", "재학생 신청 / 신입생 신청"), fact("F005", "action", "수강신청 시스템에서 본인이 직접 신청"), fact("F006", "warning", "수강 정원을 초과한 과목은 신청할 수 없습니다"), fact("F007", "contact", "학사지원팀 registrar@example.edu", False)],
        ),
        questions=[DemoQuestion(id="q1", prompt="When do new students register?", expected_answer="February 19, 2027 from 9:00 a.m. to 5:00 p.m.", critical_fact_id="F002"), DemoQuestion(id="q2", prompt="Can a student register for a full course?", expected_answer="No", critical_fact_id="F006")],
    ),
]


def get_demo(demo_id: str) -> DemoNotice | None:
    return next((demo for demo in DEMOS if demo.id == demo_id), None)


def match_demo(text: str) -> DemoNotice | None:
    normalized = " ".join(text.split())
    return next(
        (
            demo
            for demo in DEMOS
            if normalized == " ".join(demo.original_text.split())
            or demo.notice.title.lower() in normalized.lower()
            or " ".join(demo.original_text.split())[:40] in normalized
        ),
        None,
    )
