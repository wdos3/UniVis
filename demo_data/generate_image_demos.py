from __future__ import annotations

from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont


OUTPUT = Path(__file__).resolve().parent / "images"
FONT = Path("C:/Windows/Fonts/malgun.ttf")
BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = BOLD if bold else FONT
    return ImageFont.truetype(str(path), size=size)


def canvas(title: str, subtitle: str, accent: str = "#176b5b") -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    image = Image.new("RGB", (1400, 1900), "#f4f1e8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 70, 1320, 1830), radius=18, fill="white", outline="#c9d3cf", width=3)
    draw.rectangle((80, 70, 1320, 230), fill=accent)
    draw.text((125, 105), title, font=font(50, True), fill="white")
    draw.text((125, 255), subtitle, font=font(25, True), fill="#b95735")
    draw.text((1020, 1780), "가상 예시 · SYNTHETIC", font=font(20, True), fill="#687874")
    return image, draw, 330


def line(draw: ImageDraw.ImageDraw, y: int, heading: str, value: str, accent: str = "#176b5b") -> int:
    draw.text((135, y), heading, font=font(24, True), fill=accent)
    y += 45
    draw.multiline_text((135, y), value, font=font(29), fill="#17312e", spacing=14)
    return y + 105 + 42 * value.count("\n")


def save_clean_visa() -> Image.Image:
    image, draw, y = canvas("외국인 유학생 체류기간 연장", "Synthetic demonstration notice · 실제 정책이 아닙니다")
    y = line(draw, y, "대상 / ELIGIBILITY", "체류기간이 2026년 9월 30일에 만료되는 D-2 재학생")
    y = line(draw, y, "신청 기간 / DEADLINE", "2026년 9월 1일 ~ 9월 25일 17:00")
    y = line(draw, y, "필수 서류", "1. 여권\n2. 외국인등록증 (Residence Card)\n3. 재학증명서\n4. 체류지 입증서류")
    y = line(draw, y, "신청 방법", "하이코리아 방문 예약 → 서류 준비 → 한빛출입국사무소 방문")
    line(draw, y, "문의", "국제학생지원팀 02-1234-5678\nglobal@example.edu")
    image.save(OUTPUT / "clean-visa-notice.png")
    return image


def save_angle(source: Image.Image) -> None:
    wall = Image.new("RGB", (1700, 1500), "#c9c7bf")
    paper = source.resize((900, 1221), Image.Resampling.LANCZOS).rotate(-7, expand=True, fillcolor="#c9c7bf")
    wall.paste(paper, (360, 120))
    wall.save(OUTPUT / "angled-visa-notice.jpg", quality=91)


def save_table() -> None:
    image, draw, y = canvas("2027학년도 1학기 수강신청", "Synthetic table notice · 학생 유형별 날짜가 다릅니다", "#294f70")
    draw.text((135, y), "학생 유형", font=font(27, True), fill="#17312e")
    draw.text((700, y), "신청 기간", font=font(27, True), fill="#17312e")
    y += 55
    rows = [("재학생", "2월 15일 09:00 ~ 17일 17:00"), ("신입생", "2월 19일 09:00 ~ 17:00"), ("졸업예정자", "2월 20일 09:00 ~ 14:00")]
    for index, (group, period) in enumerate(rows):
        fill = "#edf3f6" if index % 2 == 0 else "#ffffff"
        draw.rectangle((120, y, 1280, y + 95), fill=fill, outline="#b8c8d0")
        draw.text((145, y + 26), group, font=font(25, True), fill="#17312e")
        draw.text((700, y + 26), period, font=font(25), fill="#17312e")
        y += 95
    y += 70
    line(draw, y, "신청", "수강신청 시스템에서 본인이 직접 신청하십시오.\n정원을 초과한 과목은 신청할 수 없습니다.", "#294f70")
    image.save(OUTPUT / "course-table-notice.png")


def save_mixed() -> None:
    image, draw, y = canvas("외국인등록증 발급 안내", "Residence Card Application · Synthetic demonstration", "#6a4f8a")
    y = line(draw, y, "준비물 / REQUIRED ITEMS", "여권 (Passport)\n재학증명서 (Certificate of Enrollment)\n증명사진 (ID Photo)", "#6a4f8a")
    y = line(draw, y, "장소 / LOCATION", "Global Lounge · 학생회관 K404", "#6a4f8a")
    line(draw, y, "시간 / HOURS", "2026.09.21–2026.09.25 · 10:00–16:00", "#6a4f8a")
    image.save(OUTPUT / "mixed-korean-english-notice.png")


def save_multi_page() -> None:
    first, draw, y = canvas("글로벌 리더 장학금", "1 / 2 · Synthetic demonstration", "#9a6130")
    y = line(draw, y, "신청 자격", "외국인 학부 재학생\n직전 학기 12학점 이상\n평점 3.5 이상", "#9a6130")
    line(draw, y, "신청 기간", "2026년 10월 5일 ~ 10월 16일 18:00", "#9a6130")
    first.save(OUTPUT / "multi-page-scholarship-1.png")

    second, draw, y = canvas("글로벌 리더 장학금", "2 / 2 · Synthetic demonstration", "#9a6130")
    y = line(draw, y, "필수 서류", "신청서\n성적증명서\n자기소개서", "#9a6130")
    y = line(draw, y, "선택 서류", "봉사활동 증명서 (선택)", "#9a6130")
    y = line(draw, y, "제출", "PDF 파일을 scholarship@example.edu로 제출", "#9a6130")
    line(draw, y, "제외", "교환학생은 신청할 수 없습니다.", "#9a6130")
    second.save(OUTPUT / "multi-page-scholarship-2.png")


def save_qr(source: Image.Image) -> None:
    image = source.copy()
    qr = qrcode.make("https://example.edu/synthetic-notice").convert("RGB").resize((270, 270))
    draw = ImageDraw.Draw(image)
    draw.rectangle((980, 1420, 1270, 1740), fill="white", outline="#17312e", width=2)
    image.paste(qr, (990, 1430))
    draw.text((1000, 1710), "QR CODE", font=font(19, True), fill="#17312e")
    image.save(OUTPUT / "qr-visa-notice.png")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    clean = save_clean_visa()
    save_angle(clean)
    save_table()
    save_mixed()
    save_multi_page()
    save_qr(clean)


if __name__ == "__main__":
    main()
