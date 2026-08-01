import logging
import datetime as dt_lib
from datetime import timezone
from typing import Optional, List
from sqlmodel import Session, select, col
from sqlalchemy import text

from models import (
    Ticket,
    TicketHistory,
    TicketRelatedApp,
    LearningExample,
    Intake,
    Application
)
from services.embedder import TextEmbedder
from voice.session import session_manager
from voice.prompts import get_prompt_text

logger = logging.getLogger("services.ticket_service")

# Note: We lazily instantiate the embedder or inject it if needed.
# Since embedder is lightweight, we can just instantiate it.
_embedder = TextEmbedder()

def _generate_ticket_number(session: Session) -> str:
    """
    Generates the next sequential ticket number in the format TIC-YYYYMM-XXXX.
    Acquires a PostgreSQL transaction-level advisory lock to prevent race conditions.
    """
    now = dt_lib.datetime.now(timezone.utc)
    prefix = f"TIC-{now.strftime('%Y%m')}-"

    session.execute(text("SELECT pg_advisory_xact_lock(7483921)"))

    statement = (
        select(Ticket.ticket_number)
        .where(col(Ticket.ticket_number).startswith(prefix))
        .order_by(col(Ticket.ticket_number).desc())
    )
    result = session.exec(statement).first()

    if result:
        last_seq = int(result.split("-")[-1])
        next_seq = last_seq + 1
    else:
        next_seq = 1

    return f"{prefix}{next_seq:04d}"

def create_ticket(
    session: Session,
    intake_id: int,
    confirmed_app_id: Optional[int],
    related_app_ids: List[int],
    confirmed_fault_type: str,
    confirmed_severity: str,
    operator_notes: str,
    predicted_app_id: Optional[int],
    predicted_fault_type: Optional[str],
    predicted_severity: Optional[str],
    created_by_service_no: str,
    edited_raw_text: Optional[str] = None,
    voice_session_id: Optional[str] = None,
    assigned_team: Optional[str] = None,
) -> dict:
    """
    Core business logic for creating a ticket, logging history, adding to learning examples,
    and routing to the appropriate team.
    
    Returns a dictionary matching TicketConfirmResponse payload.
    """
    # 1. Fetch related records
    app = None
    if confirmed_app_id is not None:
        app = session.get(Application, confirmed_app_id)
        if not app:
            raise ValueError(f"Application ID {confirmed_app_id} not found.")

    intake = session.get(Intake, intake_id)
    if not intake:
        raise ValueError(f"Intake ID {intake_id} not found.")

    # 2. Determine Routing and Status
    # - If assigned_team is explicitly provided, use it and set status to "assigned"
    # - Otherwise, fallback to the application's owning team
    routed_to = "Unassigned"
    ticket_status = "triage"

    if assigned_team:
        routed_to = assigned_team
        ticket_status = "assigned"
    elif app:
        routed_to = app.owning_team or "Unassigned"
        ticket_status = "assigned" if app.owning_team else "open"

    # 3. Generate Ticket Number
    ticket_number = _generate_ticket_number(session)

    # 4. Insert Ticket
    ticket = Ticket(
        ticket_number=ticket_number,
        intake_id=intake.id,
        primary_application_id=confirmed_app_id,
        status=ticket_status,
        fault_type=confirmed_fault_type,
        severity=confirmed_severity,
        complainant_service_no=intake.complainant_service_no,
        complainant_rank=intake.complainant_rank,
        complainant_unit=intake.complainant_unit,
        assigned_team=routed_to if routed_to != "Unassigned" else None,
        created_by_service_no=created_by_service_no,
    )
    session.add(ticket)
    session.flush()

    # 5. Insert Related Apps
    for related_id in related_app_ids:
        if related_id != confirmed_app_id:
            related_app = session.get(Application, related_id)
            if related_app:
                rel = TicketRelatedApp(
                    ticket_number=ticket_number,
                    related_application_id=related_id,
                )
                session.add(rel)

    # 6. Insert Learning Example
    final_text = edited_raw_text if edited_raw_text else intake.raw_text
    if edited_raw_text and edited_raw_text != intake.raw_text:
        intake.raw_text = edited_raw_text
        session.add(intake)
        
    embedding = _embedder.get_embedding(final_text)
    learning_entry = LearningExample(
        ticket_number=ticket_number,
        raw_text=final_text,
        text_embedding=embedding,
        predicted_app_id=predicted_app_id,
        confirmed_app_id=confirmed_app_id,
        predicted_fault_type=predicted_fault_type,
        confirmed_fault_type=confirmed_fault_type,
        predicted_severity=predicted_severity,
        confirmed_severity=confirmed_severity,
    )
    session.add(learning_entry)

    # 7. Ticket History (Routing note)
    base_note = f"Ticket created. Routed to {routed_to}." if routed_to != "Unassigned" else \
        "Ticket created. No matching application / team — sent to triage."
    
    notes = f"{base_note} Operator notes: {operator_notes}" if operator_notes else base_note

    history = TicketHistory(
        ticket_number=ticket_number,
        changed_by=created_by_service_no,
        old_status="",
        new_status=ticket_status,
        notes=notes,
    )
    session.add(history)

    session.commit()

    # 8. Advance Voice FSM (if applicable)
    voice_next_state = None
    voice_prompt_text = None
    if voice_session_id:
        try:
            session_manager.complete_ticket_and_ask_again(
                voice_session_id, ticket_number,
            )
            voice_next_state = "ASK_ANOTHER_COMPLAINT"
            voice_prompt_text = get_prompt_text("ask_another_complaint")
        except ValueError as exc:
            logger.warning(
                "Could not advance voice session %s to ASK_ANOTHER_COMPLAINT: %s",
                voice_session_id, exc,
            )

    return {
        "ticket_number": ticket_number,
        "status": ticket_status,
        "primary_application_name": app.name if app else "Unclassified",
        "fault_type": confirmed_fault_type,
        "severity": confirmed_severity,
        "routed_to_team": routed_to,
        "message": base_note,
        "voice_session_id": voice_session_id if voice_next_state else None,
        "voice_next_state": voice_next_state,
        "voice_prompt_text": voice_prompt_text,
    }
