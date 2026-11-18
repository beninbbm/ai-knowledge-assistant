"""Generate sample documents (one per supported format) for a fictional company.

    uv run python -m scripts.make_samples          # writes to ../samples/

The same builders are used by the tests to create small PDF/DOCX/Markdown files.
"""

from dataclasses import dataclass, field
from pathlib import Path

import docx
import pymupdf

from app.config import REPO_ROOT

# A block is ("h1"|"h2"|"h3", text), ("p", text), ("ul", [items]) or ("table", [rows]).
Block = tuple[str, object]


@dataclass
class SampleDoc:
    title: str
    blocks: list[Block] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def to_markdown(doc: SampleDoc) -> str:
    out = [f"# {doc.title}", ""]
    for kind, value in doc.blocks:
        if kind in ("h1", "h2", "h3"):
            # The title is the document's single H1, so shift section headings down one level.
            out += ["#" * (int(kind[1]) + 1) + f" {value}", ""]
        elif kind == "p":
            out += [str(value), ""]
        elif kind == "ul":
            out += [f"- {item}" for item in value] + [""]
        elif kind == "table":
            header, *rows = value
            out.append("| " + " | ".join(header) + " |")
            out.append("|" + "---|" * len(header))
            out += ["| " + " | ".join(r) + " |" for r in rows]
            out.append("")
    return "\n".join(out)


def write_docx(doc: SampleDoc, path: Path) -> None:
    document = docx.Document()
    document.add_heading(doc.title, level=0)  # style "Title"
    for kind, value in doc.blocks:
        if kind in ("h1", "h2", "h3"):
            document.add_heading(str(value), level=int(kind[1]) + 1)
        elif kind == "p":
            document.add_paragraph(str(value))
        elif kind == "ul":
            for item in value:
                document.add_paragraph(item, style="List Bullet")
        elif kind == "table":
            table = document.add_table(rows=0, cols=len(value[0]))
            table.style = "Table Grid"
            for row in value:
                cells = table.add_row().cells
                for cell, text in zip(cells, row, strict=True):
                    cell.text = text
    document.save(str(path))


def write_pdf(doc: SampleDoc, path: Path, with_bookmarks: bool = True) -> None:
    """Lay the document out as HTML with PyMuPDF's Story, then add bookmarks (a TOC)
    pointing at the page where each heading landed."""
    html = [f"<h1>{doc.title}</h1>"]
    for kind, value in doc.blocks:
        if kind in ("h1", "h2", "h3"):
            tag = f"h{int(kind[1]) + 1}"
            html.append(f"<{tag}>{value}</{tag}>")
        elif kind == "p":
            html.append(f"<p>{value}</p>")
        elif kind == "ul":
            html.append("<ul>" + "".join(f"<li>{i}</li>" for i in value) + "</ul>")
        elif kind == "table":
            rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in value)
            html.append(f"<table border='1'>{rows}</table>")

    story = pymupdf.Story(
        html="".join(html),
        user_css=(
            "body { font-size: 12pt; line-height: 1.4; }"
            "td { border: 1px solid #888; padding: 4px 8px; }"
        ),
    )
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    if not with_bookmarks:
        return
    pdf = pymupdf.open(path)
    toc: list[list] = [[1, doc.title, 1]]
    page_no = 0
    for kind, value in doc.blocks:
        if kind not in ("h1", "h2", "h3"):
            continue
        for candidate in range(page_no, pdf.page_count):
            if pdf[candidate].search_for(str(value)):
                page_no = candidate
                break
        toc.append([int(kind[1]) + 1, str(value), page_no + 1])
    pdf.set_toc(toc)
    pdf.saveIncr()
    pdf.close()


# ---------------------------------------------------------------------------
# Content (fictional company "Northwind Labs")
# ---------------------------------------------------------------------------

HANDBOOK = SampleDoc(
    "Northwind Labs Employee Handbook",
    [
        ("h1", "Working Hours"),
        (
            "p",
            "Our core collaboration hours are 10:00 to 15:00 in your local time zone. Outside "
            "core hours you may organise your day as you see fit, provided you work an average "
            "of 37.5 hours per week. Please keep your calendar up to date so colleagues know "
            "when you are available.",
        ),
        ("h1", "Leave Policy"),
        ("h2", "Annual Leave"),
        (
            "p",
            "Full-time employees receive 25 days of paid annual leave per calendar year, plus "
            "public holidays. Up to 5 unused days may be carried over into the first quarter of "
            "the following year; any remaining days expire on 31 March.",
        ),
        ("h2", "Parental Leave"),
        (
            "p",
            "Primary caregivers are entitled to 16 weeks of fully paid parental leave. Secondary "
            "caregivers are entitled to 6 weeks of fully paid leave, which can be taken in up to "
            "three separate blocks within the first year after the birth or adoption.",
        ),
        (
            "p",
            "Contractors are not eligible for paid parental leave, but may agree unpaid time off "
            "with their engagement manager.",
        ),
        ("h2", "Sick Leave"),
        (
            "p",
            "You may take up to 10 days of paid sick leave per year without a doctor's note. "
            "For absences longer than 3 consecutive days, please provide a note to People Ops.",
        ),
        ("h1", "Remote Work"),
        (
            "p",
            "Northwind Labs is remote-first. You may work from any country where we have a "
            "legal entity for up to 60 days per year without prior approval. Working from other "
            "countries requires approval from People Ops at least 4 weeks in advance.",
        ),
        (
            "ul",
            [
                "A one-off home office budget of $1,200 is available in your first 90 days.",
                "Internet costs are reimbursed up to $50 per month.",
                "Co-working memberships are reimbursed up to $250 per month with manager approval.",
            ],
        ),
        ("h1", "Code of Conduct"),
        (
            "p",
            "We expect everyone to treat colleagues, customers and partners with respect. "
            "Harassment, discrimination and retaliation are not tolerated. Concerns can be "
            "raised with your manager, People Ops, or anonymously through the ethics hotline.",
        ),
    ],
)

SECURITY = SampleDoc(
    "Northwind Labs IT Security Policy",
    [
        ("h1", "Passwords and Authentication"),
        (
            "p",
            "All accounts must be protected by a password manager-generated password and "
            "multi-factor authentication (MFA). Hardware security keys are required for "
            "administrators and anyone with access to production systems.",
        ),
        (
            "table",
            [
                ["Requirement", "Standard accounts", "Admin accounts"],
                ["Minimum password length", "14 characters", "20 characters"],
                ["MFA", "Authenticator app or security key", "Security key only"],
                ["Password rotation", "Only after suspected compromise", "Every 12 months"],
            ],
        ),
        ("h1", "Devices"),
        (
            "p",
            "Company laptops must have full-disk encryption enabled, automatic updates turned "
            "on, and a screen lock after 5 minutes of inactivity. Personal devices may be used "
            "for email and chat only, and must be enrolled in device management first.",
        ),
        ("h1", "Reporting Security Incidents"),
        (
            "p",
            "If you suspect a security incident, such as a lost laptop, a phishing email you "
            "clicked, or unexpected account activity, report it to security@northwind.example "
            "within 1 hour. Do not try to investigate on your own. Reporting quickly is always "
            "better than being certain.",
        ),
        ("h1", "Data Classification"),
        (
            "ul",
            [
                "Public: approved for anyone, e.g. marketing material.",
                "Internal: for employees only, e.g. this policy.",
                "Confidential: customer data and financials; share only with people who need it.",
                "Restricted: credentials and keys; never store outside the secrets vault.",
            ],
        ),
    ],
)

_REIMBURSEMENT = [
    "To be reimbursed, submit an expense claim in the finance portal within 30 days of the "
    "expense. Claims submitted later than 30 days require written approval from your "
    "department head and may be rejected. Each claim must include an itemised receipt; card "
    "statements on their own are not accepted as proof of purchase.",
    "Claims under $500 are approved by your direct manager. Claims of $500 or more also "
    "require approval from Finance. Approved claims are paid with the next monthly payroll "
    "run, provided they are approved by the 20th of the month. Claims approved after the 20th "
    "are paid in the following month's payroll.",
    "If you lose a receipt, complete a missing receipt declaration in the finance portal. "
    "Missing receipt declarations are accepted for expenses up to $75, and no more than three "
    "times in a calendar year. Repeated missing receipts will be raised with your manager.",
    "Expenses paid in a foreign currency are reimbursed in your home currency using the "
    "exchange rate shown on your card statement, or the published central bank rate on the "
    "date of the expense if you paid in cash. Bank fees for foreign transactions on personal "
    "cards are reimbursable when listed as a separate line item.",
    "Company cards may be used only for business expenses. Personal purchases on a company "
    "card, even if repaid, are a breach of this policy. Card holders must reconcile their "
    "card transactions in the finance portal by the 5th of each month.",
    "Mileage for business journeys in a personal car is reimbursed at $0.60 per mile. Record "
    "the start and end locations and the purpose of each journey in the claim. Commuting "
    "between your home and your usual place of work is not a business journey and cannot "
    "be claimed, even when you work outside normal hours.",
    "For trips longer than two weeks you may request a travel advance of up to 50% of the "
    "estimated costs. Advances must be requested at least 10 days before departure and are "
    "settled against your expense claim when you return. Any unspent advance must be repaid "
    "within 30 days of the end of the trip.",
]

TRAVEL = SampleDoc(
    "Northwind Labs Travel and Expense Policy",
    [
        ("h1", "Booking Travel"),
        (
            "p",
            "All business travel must be booked through the company travel portal at least "
            "14 days in advance where possible. Economy class is standard for flights under "
            "6 hours; premium economy may be booked for longer flights. Business class requires "
            "approval from a vice president.",
        ),
        ("h1", "Hotels and Daily Allowances"),
        (
            "p",
            "Hotel costs are capped per night. Choose hotels within walking distance or a "
            "short taxi ride of your meeting location. The daily allowance (per diem) covers "
            "meals and incidental expenses.",
        ),
        (
            "table",
            [
                ["Location", "Hotel cap per night", "Daily allowance"],
                ["Major cities (London, New York, Tokyo)", "$250", "$90"],
                ["Other cities", "$180", "$70"],
            ],
        ),
        ("h1", "Reimbursement Process"),
        *[("p", text) for text in _REIMBURSEMENT],
        ("h1", "Non-Reimbursable Items"),
        (
            "ul",
            [
                "Alcohol, except when hosting customers with manager approval.",
                "Traffic and parking fines.",
                "Upgrades to flights or hotel rooms paid for personally.",
                "Personal entertainment such as in-flight films, spa or gym fees.",
            ],
        ),
    ],
)

# A document on an unrelated topic, useful for checking that answers don't mix sources
# (questions about leave shouldn't pull from it, and vice versa). Facts as of 2025.
LEBRON = SampleDoc(
    "LeBron James: Player Profile",
    [
        ("h1", "Overview"),
        (
            "p",
            "LeBron Raymone James is an American professional basketball player, born on "
            '30 December 1984 in Akron, Ohio. Nicknamed "King James", he stands 6 ft 9 in '
            "(2.06 m) and plays mainly as a forward. He is widely regarded as one of the "
            "greatest basketball players of all time.",
        ),
        ("h1", "Early Life"),
        (
            "p",
            "James was raised in Akron by his mother, Gloria. He attended St. Vincent-St. Mary "
            "High School, where his games drew national television coverage and he appeared "
            "on the cover of Sports Illustrated as a junior. He entered the NBA straight from "
            "high school.",
        ),
        ("h1", "NBA Career"),
        ("h2", "Cleveland Cavaliers (2003-2010)"),
        (
            "p",
            "The Cleveland Cavaliers selected James with the first overall pick in the 2003 "
            "NBA draft. He won Rookie of the Year for the 2003-04 season and the league's Most "
            "Valuable Player award in 2009 and 2010. He led Cleveland to the 2007 NBA Finals, "
            "where they lost to the San Antonio Spurs.",
        ),
        ("h2", "Miami Heat (2010-2014)"),
        (
            "p",
            "In 2010 James joined the Miami Heat, announcing the move in a televised special "
            'known as "The Decision". Alongside Dwyane Wade and Chris Bosh he reached four '
            "straight NBA Finals and won championships in 2012 and 2013, earning the MVP and "
            "Finals MVP awards in both seasons.",
        ),
        ("h2", "Return to Cleveland (2014-2018)"),
        (
            "p",
            "James returned to the Cavaliers in 2014. In the 2016 NBA Finals, Cleveland came "
            "back from a 3-1 series deficit against the Golden State Warriors to win the "
            "city's first major professional sports title in 52 years. James was named "
            "Finals MVP.",
        ),
        ("h2", "Los Angeles Lakers (2018-present)"),
        (
            "p",
            "James signed with the Los Angeles Lakers in 2018. He won his fourth championship "
            'and fourth Finals MVP in 2020, in a season completed in a protected "bubble" '
            "near Orlando, Florida. On 7 February 2023 he passed Kareem Abdul-Jabbar to "
            "become the NBA's all-time leading scorer, and in March 2024 he became the first "
            "player to score 40,000 career points. In October 2024 he and his son Bronny "
            "became the first father and son to play in an NBA game together.",
        ),
        ("h1", "Career Highlights"),
        (
            "table",
            [
                ["Achievement", "Details"],
                ["NBA championships", "4 (2012, 2013, 2016, 2020)"],
                ["Finals MVP awards", "4 (2012, 2013, 2016, 2020)"],
                ["Regular-season MVP awards", "4 (2009, 2010, 2012, 2013)"],
                ["All-time scoring record", "Passed Kareem Abdul-Jabbar on 7 February 2023"],
                ["Olympic medals", "Gold in 2008, 2012 and 2024; bronze in 2004"],
            ],
        ),
        ("h1", "Finances"),
        (
            "p",
            "James is one of the wealthiest athletes in history. In 2022 Forbes reported that "
            "he had become the first active NBA player to be worth more than $1 billion. Most "
            "of his fortune comes from endorsements and business investments rather than his "
            "playing salary. Figures below are publicly reported estimates.",
        ),
        ("h2", "NBA Salary"),
        (
            "p",
            "James has earned more in NBA salary than any other player in league history. In "
            "July 2024 he signed a two-year contract with the Lakers reportedly worth about "
            "$101 million, slightly below the maximum he was eligible for, which helped the "
            "team stay under salary limits.",
        ),
        ("h2", "Endorsements"),
        (
            "p",
            "Before playing an NBA game, James signed a sneaker deal with Nike in 2003 reported "
            "at around $90 million over seven years. In 2015 he signed a lifetime contract with "
            "Nike, reportedly the first of its kind for the company, with a value widely "
            "estimated at more than $1 billion. He has also endorsed brands such as Coca-Cola "
            "(Sprite), Beats by Dre, AT&T and PepsiCo.",
        ),
        ("h2", "Business Investments"),
        (
            "table",
            [
                ["Investment", "Details"],
                [
                    "Beats by Dre",
                    "Took a small equity stake instead of a larger endorsement fee; Apple's "
                    "$3 billion purchase of Beats in 2014 reportedly earned him about $30 million",
                ],
                [
                    "Blaze Pizza",
                    "Invested less than $1 million in 2012 as an early backer of the chain",
                ],
                [
                    "Fenway Sports Group",
                    "Partner since 2011; the group owns Liverpool FC, the Boston Red Sox and "
                    "the Pittsburgh Penguins",
                ],
                [
                    "SpringHill",
                    "Media company he co-founded with Maverick Carter; valued at $725 million "
                    "when it sold a stake to investors in 2021",
                ],
            ],
        ),
        ("h2", "Philanthropy"),
        (
            "p",
            "In 2015 his foundation and the University of Akron announced that qualifying "
            "students in its programmes could receive four-year scholarships, a commitment "
            "reported to be worth more than $41 million. The I PROMISE School is funded jointly "
            "by the foundation and Akron Public Schools.",
        ),
        ("h1", "Off the Court"),
        (
            "p",
            "Through the LeBron James Family Foundation, James opened the I PROMISE School in "
            "Akron in 2018, a public school for at-risk children that also supports their "
            "families. He co-founded the media company SpringHill and has appeared in films "
            "including Trainwreck (2015) and Space Jam: A New Legacy (2021).",
        ),
        (
            "p",
            "James married his high-school sweetheart, Savannah Brinson, in 2013. They have "
            "three children: LeBron Jr. (Bronny), Bryce and Zhuri.",
        ),
    ],
)


def main() -> None:
    out = REPO_ROOT / "samples"
    out.mkdir(exist_ok=True)
    (out / "employee-handbook.md").write_text(to_markdown(HANDBOOK), encoding="utf-8")
    write_docx(SECURITY, out / "it-security-policy.docx")
    write_pdf(TRAVEL, out / "travel-expense-policy.pdf")
    (out / "lebron-james.md").write_text(to_markdown(LEBRON), encoding="utf-8")
    for path in sorted(out.iterdir()):
        print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
