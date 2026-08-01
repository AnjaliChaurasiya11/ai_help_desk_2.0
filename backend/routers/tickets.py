"""
AI Help Desk — Tickets Router
===============================
OWNER: Person 2
The heaviest file in the project. Handles the full ticket lifecycle:

  POST /api/intakes          — Accept complaint, check repeats, call AI, return proposals
  POST /api/tickets/confirm  — Create ticket from confirmed proposal
  GET  /api/tickets          — List/filter tickets + mass-outage detection
  PATCH /api/tickets/{tn}    — Update status, enforce closure rules, log history

Requirement coverage: R-5, R-6, R-7, R-9, R-10, R-13, R-14, R-15,
                      R-16, R-18, R-19, R-20, R-20a, R-21, R-22, R-23
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, col, func, text, or_
import datetime as dt_lib
from datetime import timedelta, timezone
from typing import Optional

from database import get_session
from security import CurrentUser, get_current_user, require_operator, require_admin
from models import (
    Application,
    Intake,
    Ticket,
    TicketRelatedApp,
    TicketHistory,
    LearningExample,
)
from schemas import (
    IntakeRequest,
    IntakeResponse,
    ClarifyRequest,
    CandidateApp,
    DuplicateInfo,
    TicketConfirmRequest,
    TicketConfirmResponse,
    TicketConfirmItem,
    MultiTicketConfirmRequest,
    MultiTicketConfirmResponse,
    TicketResponse,
    TicketListResponse,
    TicketUpdateRequest,
    TicketUpdateResponse,
    TicketHistoryResponse,
    MassOutageAlert,
    SimilarResolution,
    VALID_FAULT_TYPES,
    VALID_SEVERITIES,
    VALID_STATUSES,
)

from services.embedder import TextEmbedder
from services.dependencies import ApplicationDependencyEngine
from services.pipeline import process_complaint
from services.ticket_service import create_ticket

import logging
from voice.session import session_manager
from voice.prompts import get_prompt_text

logger = logging.getLogger("routers.tickets")

# embedder: used by confirm_ticket & confirm_multi_ticket for R-22 learning examples.
# dependency_engine: used by list_tickets to resolve cascade dependencies per ticket.
# Both are kept here; the classification pipeline (intake) uses pipeline.py's singletons.
embedder = TextEmbedder()
dependency_engine = ApplicationDependencyEngine()

router = APIRouter()


# =====================================================================
# Ticket Number generation moved to services.ticket_service
# =====================================================================


# =====================================================================
# 1. POST /api/intakes — Accept complaint & return AI proposals
# =====================================================================
# Requirements: R-5 (Accept text), R-6 (Operator submits form),
#               R-7 (Record service number), R-9 (Ranked candidates),
#               R-10 (Dependency expansion), R-13 (Operator reviews),
#               R-20a (Repeat-caller detection)

@router.post("/intakes", response_model=IntakeResponse)
def create_intake(
    request: IntakeRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_operator),
):
    """
    Step 1 of the ticket creation flow.

    Thin adapter over services.pipeline.process_complaint().
    Accepts the raw complaint text, runs the shared AI pipeline,
    and returns a proposal for the operator to review.

    The pipeline owns guardrail validation, heuristic evaluation,
    retrieval, LLM classification, and intake persistence.
    """
    result = process_complaint(
        session                = session,
        complaint_text         = request.raw_text,
        complainant_service_no = request.complainant_service_no or "",
        operator_id            = current_user.service_no,
        complainant_name       = request.complainant_name  or "",
        complainant_unit       = request.complainant_unit  or "",
        complainant_rank       = request.complainant_rank  or "",
    )

    if result.status == "rejected":
        raise HTTPException(
            status_code=400,
            detail=result.state.followup_question or "Complaint was rejected.",
        )

    candidates: list[CandidateApp] = [
        CandidateApp(
            application_id   = c["application_id"],
            application_name = c["application_name"],
            confidence_score = round(c["confidence_score"], 4),
            is_primary       = c.get("is_primary", False),
            expansion_reason = c.get("expansion_reason"),
        )
        for c in result.candidates
    ]

    return IntakeResponse(
        intake_id            = result.intake_id,
        corrected_text       = result.corrected_text,
        is_repeat_caller     = result.is_repeat_caller,
        potential_duplicates = result.potential_duplicates,
        status               = result.status,
        fault_type_proposal  = result.fault_type or "other",
        severity_proposal    = result.severity   or "normal",
        candidates           = candidates,
        confidence           = result.state.confidence,
        suggested_resolution = result.state.suggested_resolution,
        needs_followup       = result.state.needs_followup,
        followup_question    = result.state.followup_question,
        followup_reason      = result.state.followup_reason,
        clarification_attempts = result.clarification_attempts,
    )


# =====================================================================
# 1b. POST /api/intakes/{intake_id}/clarify — Submit clarification answer
# =====================================================================
# Decision 5: dedicated clarification endpoint for structured multi-turn flow.
# The pipeline merges the answer with the original complaint and re-runs
# classification from the sufficiency check onward.

@router.post("/intakes/{intake_id}/clarify", response_model=IntakeResponse)
def clarify_intake(
    intake_id: int,
    request: ClarifyRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_operator),
):
    """
    Step 1b — Submit a clarification answer after a follow-up question.

    Loads the pending_clarification Intake, merges the clarification text
    with the original complaint, and re-runs process_complaint() to attempt
    full classification.  The Intake record is updated in-place (same ID).
    """
    from models import Intake as IntakeModel
    from services.conversation_state import ConversationManager, ConversationState

    intake = session.get(IntakeModel, intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail=f"Intake {intake_id} not found.")
    if intake.status != "pending_clarification":
        raise HTTPException(
            status_code=409,
            detail=f"Intake {intake_id} is not pending clarification (status={intake.status!r}).",
        )

    # Merge the clarification answer into the original complaint text
    merged_text = ConversationManager.merge_clarification(
        original_text  = intake.raw_text,
        clarification  = request.clarification_text,
        state          = ConversationState(),  # no prior state needed for merge
    )

    result = process_complaint(
        session                = session,
        complaint_text         = merged_text,
        complainant_service_no = intake.complainant_service_no or "",
        operator_id            = current_user.service_no,
        complainant_name       = intake.complainant_name  or "",
        complainant_unit       = intake.complainant_unit  or "",
        complainant_rank       = intake.complainant_rank  or "",
        existing_intake_id     = intake_id,  # update in-place
    )

    if result.status == "rejected":
        raise HTTPException(
            status_code=400,
            detail=result.state.followup_question or "Clarification was rejected.",
        )

    candidates: list[CandidateApp] = [
        CandidateApp(
            application_id   = c["application_id"],
            application_name = c["application_name"],
            confidence_score = round(c["confidence_score"], 4),
            is_primary       = c.get("is_primary", False),
            expansion_reason = c.get("expansion_reason"),
        )
        for c in result.candidates
    ]

    return IntakeResponse(
        intake_id            = result.intake_id,
        corrected_text       = result.corrected_text,
        is_repeat_caller     = result.is_repeat_caller,
        potential_duplicates = result.potential_duplicates,
        status               = result.status,
        fault_type_proposal  = result.fault_type or "other",
        severity_proposal    = result.severity   or "normal",
        candidates           = candidates,
        confidence           = result.state.confidence,
        suggested_resolution = result.state.suggested_resolution,
        needs_followup       = result.state.needs_followup,
        followup_question    = result.state.followup_question,
        followup_reason      = result.state.followup_reason,
        clarification_attempts = result.clarification_attempts,
    )


# =====================================================================
# 2. POST /api/tickets/confirm — Create ticket from confirmed proposal
# =====================================================================
# Requirements: R-14 (Create ticket), R-15 (Related apps junction),
#               R-16 (Route to owning team), R-22 (Save learning example)

@router.post("/tickets/confirm", response_model=TicketConfirmResponse)
def confirm_ticket(
    request: TicketConfirmRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_operator),
):
    """
    Step 2 of the ticket creation flow.
    Operator has reviewed the AI proposal, possibly corrected it,
    and clicked 'Confirm & Create Ticket'.
    """

    # -----------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------
    if request.confirmed_fault_type not in VALID_FAULT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fault_type: '{request.confirmed_fault_type}'. Must be one of {VALID_FAULT_TYPES}",
        )
    if request.confirmed_severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: '{request.confirmed_severity}'. Must be one of {VALID_SEVERITIES}",
        )

    # Look up the confirmed application. None means the operator rejected
    # every candidate (R-17) — route to triage instead of forcing a
    # wrong label; a captured miss is useful research data.
    app = None
    if request.confirmed_app_id is not None:
        app = session.get(Application, request.confirmed_app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"Application ID {request.confirmed_app_id} not found.")

    # -----------------------------------------------------------------
    # Create ticket via shared service
    # -----------------------------------------------------------------
    response_data = create_ticket(
        session=session,
        intake_id=request.intake_id,
        confirmed_app_id=request.confirmed_app_id,
        related_app_ids=request.related_app_ids,
        confirmed_fault_type=request.confirmed_fault_type,
        confirmed_severity=request.confirmed_severity,
        operator_notes=request.operator_notes,
        predicted_app_id=request.predicted_app_id,
        predicted_fault_type=request.predicted_fault_type,
        predicted_severity=request.predicted_severity,
        created_by_service_no=current_user.service_no,
        edited_raw_text=request.edited_raw_text,
        voice_session_id=request.voice_session_id,
        assigned_team=request.assigned_team,
    )

    return TicketConfirmResponse(**response_data)


# =====================================================================
# 3. GET /api/tickets — List / filter tickets + mass-outage detection
# =====================================================================
# Requirements: R-20 (Dashboard list), R-21 (Mass-Outage Detection)

@router.get("/tickets", response_model=TicketListResponse)
def list_tickets(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    app_id: Optional[int] = Query(None, description="Filter by primary application"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search keyword"),
    team: Optional[str] = Query(None, description="Filter by owning team name"),
    complainant_service_no: Optional[str] = Query(None, description="Filter by service number"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Returns a filtered list of tickets plus any mass-outage alerts.
    """

    # -----------------------------------------------------------------
    # Build filtered query
    # -----------------------------------------------------------------
    print(f"DEBUG FILTERS: status={status}, severity={severity}, app_id={app_id}, date_from={date_from}, date_to={date_to}, search={search}")
    statement = select(Ticket)

    # RBAC Enforcement: Admins only see their managed application
    if current_user.role == "admin" and current_user.managed_team:
        statement = statement.join(Application, Ticket.primary_application_id == Application.id)
        statement = statement.where(Application.owning_team == current_user.managed_team)

    if status:
        statement = statement.where(Ticket.status == status)
    if severity:
        statement = statement.where(Ticket.severity == severity)
    if app_id:
        statement = statement.where(Ticket.primary_application_id == app_id)
    if complainant_service_no:
        statement = statement.where(Ticket.complainant_service_no == complainant_service_no)

    # R-16: Filter by owning team (join to applications)
    if team:
        team_app_ids = session.exec(
            select(Application.id).where(col(Application.owning_team).ilike(f"%{team}%"))
        ).all()
        statement = statement.where(col(Ticket.primary_application_id).in_(team_app_ids))
    
    if date_from:
        try:
            df = dt_lib.datetime.strptime(date_from, "%Y-%m-%d")
            statement = statement.where(Ticket.created_at >= df)
        except ValueError:
            pass
            
    if date_to:
        try:
            # Add one day to include the whole end date
            dt_obj = dt_lib.datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            statement = statement.where(Ticket.created_at < dt_obj)
        except ValueError:
            pass

    if search:
        # Search across ticket number or complaint text
        statement = statement.outerjoin(Intake, Ticket.intake_id == Intake.id)
        statement = statement.where(
            or_(
                col(Ticket.ticket_number).ilike(f"%{search}%"),
                col(Intake.raw_text).ilike(f"%{search}%")
            )
        )

    # Get total count before pagination
    count_statement = select(func.count()).select_from(statement.subquery())
    total_count = session.exec(count_statement).one()

    # Apply pagination and ordering
    statement = statement.order_by(col(Ticket.created_at).desc()).offset(skip).limit(limit)
    tickets = session.exec(statement).all()

    # -----------------------------------------------------------------
    # Build ticket responses (resolve app name from FK)
    # -----------------------------------------------------------------
    ticket_responses = []
    for t in tickets:
        app_name = None
        if t.primary_application_id:
            app = session.get(Application, t.primary_application_id)
            app_name = app.name if app else None

        # Resolve original complaint text from the linked intake
        complaint_text = None
        if t.intake_id:
            intake = session.get(Intake, t.intake_id)
            complaint_text = intake.raw_text if intake else None

        # Resolve cascaded dependencies
        deps = []
        if t.primary_application_id and t.fault_type:
            dep_ids = dependency_engine.expand_dependencies(
                db_session=session,
                primary_app_id=t.primary_application_id,
                fault_type=t.fault_type,
            )
            for d_id in dep_ids:
                d_app = session.get(Application, d_id)
                if d_app:
                    deps.append({
                        "application_id": d_id,
                        "application_name": d_app.name,
                        "dependency_nature": t.fault_type
                    })

        ticket_responses.append(
            TicketResponse(
                ticket_number=t.ticket_number,
                complainant_service_no=t.complainant_service_no or "",
                complainant_rank=t.complainant_rank or "",
                complainant_unit=t.complainant_unit or "",
                primary_application_id=t.primary_application_id,
                primary_application_name=app_name,
                original_complaint_text=complaint_text,
                status=t.status or "open",
                fault_type=t.fault_type or "",
                severity=t.severity or "",
                assignee_id=t.assignee_id,
                assigned_team=t.assigned_team,
                dependencies=deps,
                created_at=t.created_at,
            )
        )

    # -----------------------------------------------------------------
    # R-21: MASS-OUTAGE DETECTION
    # Check if any single application has >10 tickets in the last hour.
    # -----------------------------------------------------------------
    one_hour_ago = dt_lib.datetime.now(timezone.utc) - timedelta(hours=1)

    outage_statement = (
        select(
            Ticket.primary_application_id,
            func.count(Ticket.ticket_number).label("ticket_count"),
        )
    )

    # Apply RBAC to mass outage detection as well
    if current_user.role == "admin" and current_user.managed_team:
        outage_statement = outage_statement.join(Application, Ticket.primary_application_id == Application.id)
        outage_statement = outage_statement.where(Application.owning_team == current_user.managed_team)

    outage_statement = (
        outage_statement
        .where(
            Ticket.created_at >= one_hour_ago,
            col(Ticket.status).in_(["open", "assigned", "in_progress"]),
            Ticket.primary_application_id.isnot(None),
        )
        .group_by(Ticket.primary_application_id)
        .having(func.count(Ticket.ticket_number) > 10)
    )
    
    outage_results = session.exec(outage_statement).all()

    mass_outage_alerts = []
    for app_id, count in outage_results:
        app = session.get(Application, app_id)
        if app:
            mass_outage_alerts.append(
                MassOutageAlert(
                    application_id=app_id,
                    application_name=app.name,
                    ticket_count=count,
                    time_window_minutes=60,
                    alert_message=(
                        f"⚠️ MASS OUTAGE DETECTED: {app.name} has {count} "
                        f"open tickets in the last 60 minutes. "
                        f"Contact {app.owning_team} immediately."
                    ),
                )
            )

    return TicketListResponse(
        tickets=ticket_responses,
        total_count=total_count,
        mass_outage_alerts=mass_outage_alerts,
    )


# =====================================================================
# 4. GET /api/tickets/track/{ticket_number} — Public Ticket Tracking
# =====================================================================
# Allows complainants to check ticket status without full authentication.

@router.get("/tickets/track/{ticket_number}", response_model=TicketResponse)
def track_ticket(
    ticket_number: str,
    session: Session = Depends(get_session),
):
    """
    Publicly tracks a ticket by its exact ticket_number.
    Requires no authentication, but the ticket number must be known.
    """
    ticket = session.exec(
        select(Ticket).where(Ticket.ticket_number == ticket_number)
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    app_name = None
    if ticket.primary_application_id:
        app = session.get(Application, ticket.primary_application_id)
        app_name = app.name if app else None

    # Resolve original complaint text from the linked intake
    complaint_text = None
    if ticket.intake_id:
        intake = session.get(Intake, ticket.intake_id)
        complaint_text = intake.raw_text if intake else None

    # We reuse TicketResponse as it contains exactly what we need
    return TicketResponse(
        ticket_number=ticket.ticket_number,
        complainant_service_no=ticket.complainant_service_no or "",
        complainant_rank=ticket.complainant_rank or "",
        complainant_unit=ticket.complainant_unit or "",
        primary_application_id=ticket.primary_application_id,
        primary_application_name=app_name,
        original_complaint_text=complaint_text,
        status=ticket.status or "open",
        fault_type=ticket.fault_type or "",
        severity=ticket.severity or "",
        assignee_id=ticket.assignee_id,
        assigned_team=ticket.assigned_team,
        dependencies=[], # Keeping it simple for public view
        created_at=ticket.created_at,
    )


# =====================================================================
# 5. PATCH /api/tickets/{ticket_number} — Update status + audit trail
# =====================================================================
# Requirements: R-18 (Status transitions), R-19 (Closure requires notes),
#               R-23 (Log resolution into history)

@router.patch("/tickets/{ticket_number}", response_model=TicketUpdateResponse)
def update_ticket(
    ticket_number: str,
    request: TicketUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Updates a ticket's status. Enforces business rules:
      - Moving to 'closed' REQUIRES notes (R-19)
      - Every status change is logged to ticket_history (R-23)
    """

    # -----------------------------------------------------------------
    # Find the ticket
    # -----------------------------------------------------------------
    ticket = session.exec(
        select(Ticket).where(Ticket.ticket_number == ticket_number)
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_number} not found.")

    # -----------------------------------------------------------------
    # Validate new status
    # -----------------------------------------------------------------
    if request.new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: '{request.new_status}'. Must be one of {VALID_STATUSES}",
        )

    # Cannot update a ticket that is already closed
    if ticket.status == "closed":
        raise HTTPException(
            status_code=400,
            detail=f"Ticket {ticket_number} is already closed. Cannot update.",
        )

    # -----------------------------------------------------------------
    # R-19: Enforce that closing requires notes
    # -----------------------------------------------------------------
    if request.new_status == "closed" and not request.notes.strip():
        raise HTTPException(
            status_code=400,
            detail="Cannot close a ticket without providing resolution notes (R-19). "
                   "Please describe the resolving action in the 'notes' field.",
        )

    # -----------------------------------------------------------------
    # Save old status for audit trail
    # -----------------------------------------------------------------
    old_status = ticket.status
    old_assigned_team = ticket.assigned_team

    # -----------------------------------------------------------------
    # R-19: Apply assignee if provided
    # -----------------------------------------------------------------
    if request.assignee_id is not None:
        ticket.assignee_id = request.assignee_id
        
    if request.assigned_team is not None:
        ticket.assigned_team = request.assigned_team

    # -----------------------------------------------------------------
    # Update the ticket status
    # -----------------------------------------------------------------
    ticket.status = request.new_status
    session.add(ticket)

    # -----------------------------------------------------------------
    # R-23: Embed resolution notes when closing/resolving
    # -----------------------------------------------------------------
    resolution_embedding = None
    if request.new_status in ("resolved", "closed") and request.notes.strip():
        resolution_embedding = embedder.get_embedding(request.notes)

    # -----------------------------------------------------------------
    # Log the status change into ticket_history
    # -----------------------------------------------------------------
    final_notes = request.notes
    if request.assigned_team is not None and request.assigned_team != old_assigned_team:
        team_change_msg = f"Reassigned from {old_assigned_team or 'Unassigned'} to {request.assigned_team}."
        final_notes = f"{team_change_msg} {request.notes}".strip()

    history_entry = TicketHistory(
        ticket_number=ticket_number,
        changed_by=request.changed_by,
        old_status=old_status,
        new_status=request.new_status,
        notes=final_notes,
        resolution_embedding=resolution_embedding,
    )
    session.add(history_entry)

    session.commit()

    return TicketUpdateResponse(
        ticket_number=ticket_number,
        old_status=old_status,
        new_status=request.new_status,
        message=f"Ticket {ticket_number} updated: {old_status} → {request.new_status}",
    )


# =====================================================================
# 5. GET /api/tickets/{tn}/similar-resolutions — R-23
# =====================================================================

@router.get("/tickets/{ticket_number}/similar-resolutions", response_model=list[SimilarResolution])
def get_similar_resolutions(
    ticket_number: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    R-23: Complaint-to-Complaint matching.
    Steps:
      1. Get the embedding of the CURRENT ticket's complaint.
      2. Find past COMPLAINTS (in learning_examples) with similar embeddings.
         These past tickets must already be resolved/closed.
      3. For each matching past ticket, fetch the resolution note from ticket_history.
      4. Return those notes — telling Operator B "here's how a similar problem was fixed."
    """
    # Step 1: Get the current ticket's complaint embedding
    le = session.exec(
        select(LearningExample).where(LearningExample.ticket_number == ticket_number)
    ).first()

    if not le or le.text_embedding is None:
        return []

    embedding_str = "[" + ",".join(map(str, le.text_embedding)) + "]"

    # Step 2 & 3:
    # - Join learning_examples (for complaint similarity) with tickets (to check status)
    # - and ticket_history (to get resolution notes)
    # - Only match tickets that are actually resolved/closed (i.e., have a resolution note)
    # - Exclude the current ticket itself
    resolution_query = text("""
        SELECT
            le_past.ticket_number,
            th.notes,
            th.changed_by,
            th.changed_at,
            (le_past.text_embedding <=> :embedding) AS distance
        FROM learning_examples le_past
        JOIN tickets t ON t.ticket_number = le_past.ticket_number
        JOIN ticket_history th ON th.ticket_number = le_past.ticket_number
        WHERE le_past.text_embedding IS NOT NULL
          AND le_past.ticket_number != :current_tn
          AND t.status IN ('resolved', 'closed')
          AND th.notes IS NOT NULL
          AND th.notes != ''
          AND th.new_status IN ('resolved', 'closed')
        ORDER BY distance ASC
        LIMIT 3
    """)
    rows = session.execute(resolution_query, {
        "embedding": embedding_str,
        "current_tn": ticket_number
    }).fetchall()

    # Only return results that are meaningfully similar (distance < 0.12, i.e. >88% match)
    return [
        SimilarResolution(
            ticket_number=row.ticket_number,
            notes=row.notes,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
            similarity_score=round(max(0.0, 1.0 - float(row.distance)), 3),
        )
        for row in rows
        if float(row.distance) < 0.12
    ]


# =====================================================================
# 5b. GET /api/tickets/{tn}/history — Audit Trail
# =====================================================================

@router.get("/tickets/{ticket_number}/history", response_model=list[TicketHistoryResponse])
def get_ticket_history(
    ticket_number: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Returns the full chronological audit trail for a ticket.
    Includes all status changes and resolution notes.
    """
    ticket = session.exec(
        select(Ticket).where(Ticket.ticket_number == ticket_number)
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_number} not found.")

    history = session.exec(
        select(TicketHistory)
        .where(TicketHistory.ticket_number == ticket_number)
        .order_by(col(TicketHistory.changed_at).asc())
    ).all()

    return [
        TicketHistoryResponse(
            id=h.id,
            ticket_number=h.ticket_number,
            changed_by=h.changed_by,
            old_status=h.old_status,
            new_status=h.new_status,
            notes=h.notes,
            changed_at=h.changed_at,
        )
        for h in history
    ]


# =====================================================================
# 6. POST /api/tickets/confirm-multi — R-14a
# =====================================================================

@router.post("/tickets/confirm-multi", response_model=MultiTicketConfirmResponse)
def confirm_multi_ticket(
    request: MultiTicketConfirmRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_operator),
):
    """
    R-14a: Create multiple tickets from a single intake when the operator
    identifies genuinely separate faults in one complaint.
    """
    intake = session.get(Intake, request.intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail=f"Intake {request.intake_id} not found.")

    embedding = embedder.get_embedding(intake.raw_text)
    created = []

    for item in request.tickets:
        # Validate
        if item.confirmed_fault_type not in VALID_FAULT_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid fault_type: '{item.confirmed_fault_type}'")
        if item.confirmed_severity not in VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail=f"Invalid severity: '{item.confirmed_severity}'")

        app = session.get(Application, item.confirmed_app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"Application {item.confirmed_app_id} not found.")

        # -----------------------------------------------------------------
        # Create ticket via shared service
        # -----------------------------------------------------------------
        response_data = create_ticket(
            session=session,
            intake_id=request.intake_id,
            confirmed_app_id=item.confirmed_app_id,
            related_app_ids=item.related_app_ids,
            confirmed_fault_type=item.confirmed_fault_type,
            confirmed_severity=item.confirmed_severity,
            operator_notes=item.operator_notes,
            predicted_app_id=item.predicted_app_id,
            predicted_fault_type=item.predicted_fault_type,
            predicted_severity=item.predicted_severity,
            created_by_service_no=current_user.service_no,
            edited_raw_text=item.edited_raw_text,
            voice_session_id=None,  # Not applicable for multi-ticket
            assigned_team=item.assigned_team,
        )

        ticket_number = response_data["ticket_number"]
        routed_to = response_data["routed_to_team"]

        created.append(TicketConfirmResponse(
            ticket_number=ticket_number,
            status="open",
            primary_application_name=app.name,
            fault_type=item.confirmed_fault_type,
            severity=item.confirmed_severity,
            routed_to_team=app.owning_team,
            message=f"Ticket {ticket_number} created.",
        ))

    session.commit()
    return MultiTicketConfirmResponse(
        created_tickets=created,
        message=f"{len(created)} ticket(s) created from intake {request.intake_id}.",
    )
