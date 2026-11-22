"""Guided public enquiry questions. These collect preferences for advisors."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat_inquiries import ChatAction, ChatFlow, ChatQuestion, ChatSection
from app.services.financial_catalog import published_product_names

_AMOUNT = (
    "How much funding do you need?",
    "Under ₹5 lakh",
    "₹5 lakh to under ₹25 lakh",
    "₹25 lakh to under ₹1 crore",
    "₹1 crore or more",
)
_TIMING = ("When do you need it?", "This month", "In 1–3 months", "In more than 3 months")
_HOME_BUDGET = (
    "What is your property budget?",
    "Under ₹60 lakh",
    "₹60 lakh to ₹1.5 crore",
    "Above ₹1.5 crore",
)
_COVER = (
    "Who would you like to cover?",
    "Self only",
    "Self and family",
    "Parents or senior citizens",
)
_AGE = (
    "How old is the eldest person to be covered?",
    "18–35 years",
    "36–50 years",
    "Over 50 years",
)


def _flow(
    slug: str,
    section: ChatSection,
    label: str,
    questions: tuple[tuple[str, ...], ...],
    *actions: tuple[str, str],
) -> ChatFlow:
    return ChatFlow(
        id=slug,
        section=section,
        label=label,
        questions=[
            ChatQuestion(prompt=prompt, options=[*options, "Not sure yet"])
            for prompt, *options in questions
        ],
        actions=[ChatAction(id=key, label=text) for key, text in actions],
        browse_href=(
            "/real-estate#property-results" if section == "real_estate" else f"/loans/{slug}"
        ),
    )


_LOAN_ADVISOR = ("advisor", "Talk to a loan advisor")
_QUOTE = ("quote", "Request a quote")
_CALLBACK = ("callback", "Request a callback")
_VISIT = ("visit", "Request a site visit")
FLOWS = {
    flow.id: flow
    for flow in (
        _flow(
            "personal-loan",
            "loans",
            "Personal Loan",
            (
                (
                    "What is the loan for?",
                    "Planned purchase",
                    "Medical or family expense",
                    "Other expense",
                ),
                _AMOUNT,
                _TIMING,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "business-loan",
            "loans",
            "Business Loan",
            (
                ("What is the funding for?", "Working capital", "Expansion", "Equipment"),
                _AMOUNT,
                _TIMING,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "home-loan",
            "loans",
            "Home Loan",
            (
                (
                    "What are you planning?",
                    "Buy a home",
                    "Build a home",
                    "Transfer a home loan",
                    "Buy a plot",
                ),
                _HOME_BUDGET,
                _TIMING,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "loan-against-property",
            "loans",
            "Loan Against Property / Mortgage",
            (
                ("What property do you own?", "Residential", "Commercial", "Land"),
                (
                    "How will you use the funds?",
                    "Business needs",
                    "Personal expenses",
                    "Other purpose",
                ),
                _AMOUNT,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "car-loan",
            "loans",
            "Car / Auto Loan",
            (
                ("Which vehicle are you considering?", "New car", "Used car"),
                (
                    "What is your vehicle budget?",
                    "Under ₹10 lakh",
                    "₹10 lakh to ₹25 lakh",
                    "Above ₹25 lakh",
                ),
                _TIMING,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "professional-loan",
            "loans",
            "Professional Loan (Doctors/CAs)",
            (
                (
                    "What is your profession?",
                    "Doctor",
                    "Chartered accountant",
                    "Other professional",
                ),
                (
                    "What is the funding for?",
                    "Set up a practice",
                    "Expand a practice",
                    "Working capital",
                ),
                _AMOUNT,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "education-loan",
            "loans",
            "Education Loan",
            (
                ("Where do you plan to study?", "India", "Abroad"),
                _AMOUNT,
                ("What stage are you at?", "Exploring courses", "Applied", "Admission confirmed"),
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "equipment-financing",
            "loans",
            "Equipment / Machinery Loan",
            (
                (
                    "What will the equipment be used for?",
                    "Manufacturing",
                    "Professional practice",
                    "Other business use",
                ),
                (
                    "What is your equipment budget?",
                    "Under ₹10 lakh",
                    "₹10 lakh to ₹50 lakh",
                    "Above ₹50 lakh",
                ),
                _TIMING,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "project-funding",
            "loans",
            "Real Estate Project Funding",
            (
                ("What type of project is it?", "Residential", "Commercial", "Mixed use"),
                (
                    "What stage is the project at?",
                    "Planning",
                    "Approvals in progress",
                    "Construction underway",
                ),
                _AMOUNT,
            ),
            _LOAN_ADVISOR,
        ),
        _flow(
            "credit-card",
            "credit_cards",
            "Credit Cards",
            (
                (
                    "What is your primary purpose?",
                    "Cashback & Shopping",
                    "Travel & Lounge Access",
                    "Fuel & Rewards",
                ),
                ("What is your employment profile?", "Salaried", "Self-employed / Business"),
                (
                    "What is your approximate monthly income?",
                    "₹25,000 to under ₹50,000",
                    "₹50,000 to ₹1 lakh",
                    "Above ₹1 lakh",
                    "Under ₹25,000",
                ),
            ),
            ("advisor", "Talk to a card advisor"),
        ),
        _flow(
            "health-insurance",
            "insurance",
            "Health Insurance",
            (
                _COVER,
                _AGE,
                (
                    "What would you like to compare?",
                    "Individual cover",
                    "Family floater",
                    "Top-up cover",
                ),
            ),
            _QUOTE,
            _CALLBACK,
        ),
        _flow(
            "life-insurance",
            "insurance",
            "Term Life Insurance",
            (
                _COVER,
                _AGE,
                (
                    "What is your coverage goal?",
                    "Family protection",
                    "Cover a loan",
                    "Review existing cover",
                ),
            ),
            _QUOTE,
            _CALLBACK,
        ),
        _flow(
            "motor-insurance",
            "insurance",
            "Motor / Vehicle Insurance",
            (
                (
                    "Which vehicle would you like to cover?",
                    "Car",
                    "Two-wheeler",
                    "Commercial vehicle",
                ),
                ("Which cover are you considering?", "Third-party cover", "Comprehensive cover"),
                ("Is this a new policy or renewal?", "New policy", "Renewal"),
            ),
            _QUOTE,
            _CALLBACK,
        ),
        _flow(
            "residential",
            "real_estate",
            "Residential Properties",
            (
                ("Are you looking to buy or rent?", "Buy property", "Rent / Lease"),
                (
                    "What type of home do you prefer?",
                    "1 / 2 BHK apartment",
                    "3 / 4 BHK apartment",
                    "Independent villa",
                ),
                _HOME_BUDGET,
            ),
            ("brochure", "Request property brochures"),
            _VISIT,
        ),
        _flow(
            "commercial",
            "real_estate",
            "Commercial Properties",
            (
                ("What are you looking for?", "Buy commercial space", "Lease / Rent space"),
                (
                    "What type of commercial space do you need?",
                    "Office space / IT park",
                    "Retail shop / Showroom",
                    "Warehouse / Industrial",
                ),
                (
                    "What is your approximate budget?",
                    "Under ₹50 lakh",
                    "₹50 lakh to under ₹2 crore",
                    "₹2 crore to ₹10 crore",
                    "Above ₹10 crore",
                ),
            ),
            ("advisor", "Talk to a commercial expert"),
        ),
        _flow(
            "plots",
            "real_estate",
            "Plots & Lands",
            (
                (
                    "What type of land are you looking for?",
                    "Residential open plot",
                    "Agricultural / Farm land",
                    "Commercial / Industrial land",
                ),
                (
                    "What size do you prefer?",
                    "150 to under 300 sq yd",
                    "300 to 1,000 sq yd",
                    "Acres / Bulk land",
                ),
                (
                    "What is your approximate budget?",
                    "Under ₹30 lakh",
                    "₹30 lakh to ₹1 crore",
                    "Above ₹1 crore",
                ),
            ),
            ("layout", "Request layout maps"),
            _VISIT,
        ),
    )
}

_CATEGORIES = {"loans": "loan", "credit_cards": "credit_card", "insurance": "insurance"}


async def available_flows(db: AsyncSession) -> list[ChatFlow]:
    financial_names = {flow.id for flow in FLOWS.values() if flow.section != "real_estate"}
    financial_names.add("credit-cards")  # legacy catalog slug
    published = await published_product_names(db, financial_names)
    if published.get("credit-cards") == "credit_card":
        published.setdefault("credit-card", "credit_card")
    return [
        flow
        for flow in FLOWS.values()
        if flow.section == "real_estate" or published.get(flow.id) == _CATEGORIES[flow.section]
    ]
