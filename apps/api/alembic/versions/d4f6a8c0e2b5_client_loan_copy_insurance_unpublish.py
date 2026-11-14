"""Publish client-approved Home/Personal Loan copy; unpublish insurance.

Revision ID: d4f6a8c0e2b5
Revises: c3e5a7b9d1f4

Data only (no DDL). loan_types already carries the public_* catalogue columns,
their grants and their row-level policies, so nothing here changes access.

1. home-loan and personal-loan: replace the generic seed copy from 73f4c2a91d6e
   with the client-approved drafts (2026-11-12). A row is updated only while it
   still holds the untouched seed description and summary, so copy an Admin has
   already edited is never overwritten. Every value fits the Admin validation
   limits (summary <= 280, list items 2-180 chars, <= 12 items, FAQ <= 10 with
   questions <= 180 and answers <= 800 chars).
2. Insurance (life, health, property, travel): unpublished until an IRDAI
   licence or a licensed tie-up is confirmed. homepage_featured is cleared in
   the same statement because ck_loan_types_homepage_featured_is_public forbids
   a featured row that is not public. Insurance calculators are unaffected.

Rollback: `alembic downgrade -1` restores the seed copy only where this
migration's copy is still in place, and republishes the four insurance rows
that still have their public summary and description (as 73f4c2a91d6e left
them); it does not re-feature them, matching that seed.
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "d4f6a8c0e2b5"
down_revision = "c3e5a7b9d1f4"
branch_labels = None
depends_on = None

SEED_SUMMARY_SQL = "label || ' with guided Dhanadhara support.'"
SEED = {
    "description": (
        "Understand the journey, review configured providers, and apply or enquire "
        "inside Dhanadhara. Provider terms are informational and subject to review."
    ),
    "highlights": ["Internal assisted journey", "Provider options in one place"],
    "eligibility": ["Eligibility and approval are assessed by the selected provider"],
    "documents": ["Documents are requested only during the secure application journey"],
    "faq": [
        {
            "question": "Is approval guaranteed?",
            "answer": (
                "No. The selected provider completes its own eligibility and credit assessment."
            ),
        }
    ],
}

COPY: dict[str, dict[str, object]] = {
    "home-loan": {
        "summary": (
            "Dhanadhara helps you compare home loan offers from public sector banks, private "
            "banks, housing finance companies and NBFCs for property in Hyderabad and "
            "Telangana. The service is free."
        ),
        "description": (
            "You apply online, an advisor calls you during working hours, and the lender you "
            "choose sets the final rate, tenure and approval."
        ),
        "highlights": [
            "Loan amount: from ₹1 lakh",
            "Who can apply: salaried and self-employed, income from ₹15,000 a month",
            "Property: flats, villas, open plots, under-construction and resale",
            "Fee to Dhanadhara: none",
        ],
        "eligibility": [
            "You are salaried or self-employed",
            "You earn ₹15,000 a month or more",
            "Meeting these doesn't mean approval: each lender sets its own minimum age, "
            "income and credit score",
        ],
        "documents": [
            "Identity and address: PAN card and Aadhaar",
            "Income, salaried: recent salary slips, Form 16 and bank statements",
            "Income, self-employed: income tax returns, business proof and bank statements",
            "Property: sale agreement or sale deed, title documents, approved building plan "
            "or layout approval, and an encumbrance certificate",
            "The exact list comes from your lender. You upload everything online; we don't "
            "collect documents in person",
        ],
        "faq": [
            {
                "question": "What interest rate will I get through Dhanadhara?",
                "answer": (
                    "The lender sets your rate, not Dhanadhara. It is based on your CIBIL score, "
                    "income, loan amount and property. We show you the lenders that match your "
                    "profile so you can compare their offers before you choose."
                ),
            },
            {
                "question": "Do I pay Dhanadhara anything?",
                "answer": (
                    "No. Dhanadhara charges customers nothing. The lender may charge a "
                    "processing fee, which appears in its loan offer before you accept, so you "
                    "can compare it across lenders."
                ),
            },
            {
                "question": "Can I get a loan with a CIBIL score below 650?",
                "answer": (
                    "Yes, you can enquire. Fewer lenders approve low scores, and those that do "
                    "usually charge a higher rate. Before you apply anywhere, we tell you which "
                    "lenders, if any, are likely to consider your profile."
                ),
            },
            {
                "question": "Is approval guaranteed?",
                "answer": (
                    "No. The lender runs its own credit, income and property checks and makes "
                    "the final decision. We apply only to lenders whose rules fit your profile, "
                    "so you avoid rejections from lenders you clearly don't qualify for."
                ),
            },
            {
                "question": "Can I get a loan for an open plot or a gram panchayat property?",
                "answer": (
                    "Yes, some lenders fund both. Each lender checks the layout approval (HMDA, "
                    "DTCP or gram panchayat) and the title before funding. Share the property "
                    "details with us and we will tell you which lenders accept it."
                ),
            },
            {
                "question": "Do I need to visit your office to apply?",
                "answer": (
                    "No. You apply, upload documents and track progress online, and an advisor "
                    "calls you Monday to Saturday, 10 AM to 6 PM. The lender may still send a "
                    "valuer to inspect the property."
                ),
            },
        ],
    },
    "personal-loan": {
        "summary": (
            "Dhanadhara helps salaried and self-employed people in Hyderabad and Telangana "
            "compare personal loan offers from banks and NBFCs, starting from ₹1 lakh."
        ),
        "description": (
            "You apply online and pay Dhanadhara nothing. The lender you choose decides the "
            "amount, interest rate and tenure."
        ),
        "highlights": [
            "Loan amount: from ₹1 lakh",
            "Who can apply: salaried and self-employed, income from ₹15,000 a month",
            "Process: fully online, with an advisor call during working hours",
            "Fee to Dhanadhara: none",
        ],
        "eligibility": [
            "You are salaried or self-employed",
            "You earn ₹15,000 a month or more",
            "Each lender then sets its own minimum age, income and credit score, and many ask "
            "for more for larger amounts",
        ],
        "documents": [
            "Identity and address: PAN card and Aadhaar",
            "Income, salaried: recent salary slips and bank statements",
            "Income, self-employed: income tax returns and bank statements",
            "The lender gives you the exact list. You upload it online; we don't collect "
            "documents in person",
        ],
        "faq": [
            {
                "question": "What is the minimum salary to apply through Dhanadhara?",
                "answer": (
                    "₹15,000 a month. We take enquiries from salaried and self-employed "
                    "applicants earning ₹15,000 or more. Each lender sets its own minimum, and "
                    "some ask for more, especially for larger loan amounts."
                ),
            },
            {
                "question": "Can I get a loan with a low CIBIL score?",
                "answer": (
                    "Yes, you can enquire. Fewer lenders consider low scores, and their rates are "
                    "usually higher. We check which lenders may accept your profile before you "
                    "apply anywhere."
                ),
            },
            {
                "question": "How fast will I get the money?",
                "answer": (
                    "Usually within a few days of approval. Timing varies by lender and by how "
                    "quickly you upload documents. Your advisor follows up during working hours "
                    "until the money reaches your bank account."
                ),
            },
            {
                "question": "Do I pay Dhanadhara any fee?",
                "answer": (
                    "No. Dhanadhara charges customers nothing. The lender may charge a "
                    "processing fee, which appears in its loan offer before you accept, so you "
                    "can compare total cost across lenders."
                ),
            },
            {
                "question": "Can self-employed people apply?",
                "answer": (
                    "Yes. Self-employed applicants can enquire if they earn ₹15,000 a month or "
                    "more. Lenders usually ask for income tax returns and bank statements "
                    "instead of salary slips."
                ),
            },
            {
                "question": "How much can I borrow?",
                "answer": (
                    "The minimum is ₹1 lakh. The lender sets your upper limit from your income "
                    "and the EMIs you already pay. Use our loan eligibility calculator for an "
                    "estimate before you apply."
                ),
            },
        ],
    },
}

INSURANCE = ("life-insurance", "health-insurance", "property-insurance", "travel-insurance")

_SET_COPY = """
    UPDATE loan_types
    SET public_summary = {summary},
        public_description = :description,
        public_highlights = CAST(:highlights AS jsonb),
        public_eligibility = CAST(:eligibility AS jsonb),
        public_documents = CAST(:documents AS jsonb),
        public_faq = CAST(:faq AS jsonb)
    WHERE name = :name AND {guard}
"""


def _params(name: str, values: dict[str, object]) -> dict[str, object]:
    return {
        "name": name,
        "description": values["description"],
        "highlights": json.dumps(values["highlights"], ensure_ascii=False),
        "eligibility": json.dumps(values["eligibility"], ensure_ascii=False),
        "documents": json.dumps(values["documents"], ensure_ascii=False),
        "faq": json.dumps(values["faq"], ensure_ascii=False),
    }


def upgrade() -> None:
    # Untouched seed rows only: both the seed description and the seed summary
    # pattern must still be present.
    statement = sa.text(
        _SET_COPY.format(
            summary=":summary",
            guard=f"public_description = :seed_description AND public_summary = {SEED_SUMMARY_SQL}",
        )
    )
    for name, values in COPY.items():
        op.execute(
            statement.bindparams(
                **_params(name, values),
                summary=values["summary"],
                seed_description=SEED["description"],
            )
        )
    op.execute(
        sa.text(
            "UPDATE loan_types SET public_visible = false, homepage_featured = false "
            "WHERE name IN :names"
        ).bindparams(sa.bindparam("names", value=INSURANCE, expanding=True))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE loan_types SET public_visible = true "
            "WHERE name IN :names AND active = true "
            "AND public_summary IS NOT NULL AND public_description IS NOT NULL"
        ).bindparams(sa.bindparam("names", value=INSURANCE, expanding=True))
    )
    statement = sa.text(
        _SET_COPY.format(
            summary=SEED_SUMMARY_SQL,
            guard="public_description = :ours AND public_summary = :our_summary",
        )
    )
    for name, values in COPY.items():
        op.execute(
            statement.bindparams(
                **_params(name, SEED),
                ours=values["description"],
                our_summary=values["summary"],
            )
        )
