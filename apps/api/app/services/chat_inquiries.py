import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_inquiry import ChatInquiry
from app.schemas.chat_inquiries import ChatInquiryCreate, ChatInquiryRead
from app.services.chat_flows import available_flows
from app.services.leads import lock_lead_mobile, notify_lead_assignments, stage_direct_lead

logger = logging.getLogger(__name__)


class ChatInquiryInvalid(Exception):
    pass


async def create_chat_inquiry(db: AsyncSession, request: ChatInquiryCreate) -> UUID:
    # Serialize retries even when the two requests carry different mobile numbers.
    # The key is a private random token generated for one submission in the browser.
    await lock_lead_mobile(db, f"chat-inquiry:{request.idempotency_key}")
    existing = await db.scalar(
        select(ChatInquiry.reference).where(ChatInquiry.idempotency_key == request.idempotency_key)
    )
    if existing is not None:
        return existing

    flow = next((flow for flow in await available_flows(db) if flow.id == request.flow), None)
    if flow is None:
        raise ChatInquiryInvalid
    action = next((action for action in flow.actions if action.id == request.action), None)
    if action is None or any(
        answer not in question.options
        for question, answer in zip(flow.questions, request.answers, strict=True)
    ):
        raise ChatInquiryInvalid

    requirement = {"page": "site-chat", "product": flow.label}
    if flow.section != "real_estate":
        requirement["product_slug"] = flow.id
    lead, notice = await stage_direct_lead(
        db,
        request.mobile,
        name=request.name,
        business_line="real_estate" if flow.section == "real_estate" else "loans",
        requirement=requirement,
    )
    inquiry = ChatInquiry(
        idempotency_key=request.idempotency_key,
        lead_id=lead.id if lead is not None else None,
        service=flow.label,
        action=action.label,
        name=request.name if lead is not None else None,
        location=request.location if lead is not None else "",
        preferences={
            question.prompt: answer
            for question, answer in zip(flow.questions, request.answers, strict=True)
        }
        if lead is not None
        else {},
    )
    db.add(inquiry)
    await db.flush()
    await db.commit()
    if notice is not None:
        try:
            await notify_lead_assignments([notice])
        except SQLAlchemyError:
            logger.error("chat_inquiry.assignment_notification_failed")
    return inquiry.reference


async def list_chat_inquiries(
    db: AsyncSession, lead_id: UUID, *, include_name: bool = True
) -> list[ChatInquiryRead]:
    columns = (
        ChatInquiry.reference,
        ChatInquiry.service,
        ChatInquiry.action,
        ChatInquiry.location,
        ChatInquiry.preferences,
        ChatInquiry.created_at,
    )
    if include_name:
        columns += (ChatInquiry.name,)
    rows = await db.execute(
        select(*columns)
        .where(ChatInquiry.lead_id == lead_id)
        .order_by(ChatInquiry.created_at.desc(), ChatInquiry.reference)
    )
    return [ChatInquiryRead.model_validate(row) for row in rows.mappings()]
