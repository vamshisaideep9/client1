"""Contest read models (CS-027): participant pages and Admin standings.

Which contests a caller sees is decided on their own RLS session (role, line
and status by ``contests_select``), narrowed here to the teams they belong to
or manage. Standings need every participant's work, which no participant can
read, so they are computed (live) or read (snapshot) on the bypass session and
reduced to the minimized projection before leaving this module:

- a participant gets the rules, their own standing, and a leaderboard of
  display name (first name and last initial, or the team name), rank and
  achieved value; the Admin can hide other participants' names or amounts
  per role through field visibility (``contest_leaderboard``);
- a team member sees their team's standing and only their own contribution;
  the managing Sub Admin sees each member's contribution;
- the platform Admin's standings carry full names, progress, prizes and
  payment state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.contest import (
    Contest,
    ContestAudience,
    ContestMetric,
    ContestPaymentStatus,
    ContestResult,
    ContestResultKind,
    ContestStatus,
)
from app.models.field_visibility import FieldTargetRole, FieldVisibilityMode
from app.models.profile import AgentProfile, StaffProfile
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User
from app.schemas.contests import (
    ContestProgress,
    ContestStandingsResponse,
    LeaderboardEntry,
    MyContestDetail,
    MyContestSummary,
    MyStanding,
    StandingRow,
    TeamMemberStanding,
    TeamStanding,
)
from app.services.contest_scoring import Participant, compute_standings
from app.services.contests import ContestNotFound, parse_criteria, reads_for
from app.services.field_visibility import effective_modes

LEADERBOARD_SIZE = 10
_VISIBLE = (
    ContestStatus.APPROVED.value,
    ContestStatus.LIVE.value,
    ContestStatus.ENDED.value,
    ContestStatus.FINALIZED.value,
)
_SNAPSHOT = (ContestStatus.ENDED.value, ContestStatus.FINALIZED.value)


@dataclass
class Row:
    """One standing, from a live computation or a snapshot row."""

    kind: str
    agent_profile_uuid: uuid.UUID | None
    staff_profile_uuid: uuid.UUID | None
    team_uuid: uuid.UUID | None
    user_uuid: uuid.UUID | None
    first_name: str = ""
    last_name: str = ""
    team_name: str | None = None
    metric_value: int = 0
    count: int = 0
    amount_paise: int = 0
    progress: dict[str, int] = field(default_factory=dict)
    qualified: bool = False
    rank: int | None = None
    won: bool = False
    prize_paise: int = 0
    excluded_reason: str | None = None
    payment_status: str = ContestPaymentStatus.NONE.value
    result_id: uuid.UUID | None = None
    payout_uuid: uuid.UUID | None = None
    paid_reference: str | None = None
    paid_marked_at: datetime | None = None

    @property
    def display_name(self) -> str:
        if self.kind == ContestResultKind.TEAM:
            return self.team_name or "Team"
        initial = f" {self.last_name[:1].upper()}." if self.last_name else ""
        return f"{self.first_name}{initial}".strip() or "Participant"

    @property
    def full_name(self) -> str:
        if self.kind == ContestResultKind.TEAM:
            return self.team_name or "Team"
        return " ".join(part for part in (self.first_name, self.last_name) if part) or "—"


@dataclass
class Board:
    source: str  # live | snapshot | none
    computed_at: datetime | None
    ranked: list[Row]
    team_people: list[Row]


def _from_participant(person: Participant) -> Row:
    return Row(
        kind=person.kind,
        agent_profile_uuid=person.agent_profile_uuid,
        staff_profile_uuid=person.staff_profile_uuid,
        team_uuid=person.team_uuid,
        user_uuid=person.user_uuid,
        first_name=person.first_name,
        last_name=person.last_name,
        team_name=person.team_name,
        metric_value=person.metric_value,
        count=person.tally.count,
        amount_paise=person.tally.amount_paise,
        progress=dict(person.progress),
        qualified=person.qualified,
        rank=person.rank,
    )


async def _snapshot_rows(session: AsyncSession, contest: Contest) -> list[Row]:
    results = list(
        await session.scalars(select(ContestResult).where(ContestResult.contest_uuid == contest.id))
    )
    agent_ids = {r.agent_profile_uuid for r in results if r.agent_profile_uuid}
    staff_ids = {r.staff_profile_uuid for r in results if r.staff_profile_uuid}
    team_ids = {r.team_uuid for r in results if r.team_uuid}
    names: dict[uuid.UUID, tuple[str, str]] = {}
    if agent_ids:
        for row in await session.execute(
            select(AgentProfile.id, User.first_name, User.last_name)
            .join(User, User.id == AgentProfile.auth_user_uuid)
            .where(AgentProfile.id.in_(agent_ids))
        ):
            names[row.id] = (row.first_name or "", row.last_name or "")
    if staff_ids:
        for row in await session.execute(
            select(StaffProfile.id, User.first_name, User.last_name)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(StaffProfile.id.in_(staff_ids))
        ):
            names[row.id] = (row.first_name or "", row.last_name or "")
    team_names: dict[uuid.UUID, str] = {}
    if team_ids:
        for row in await session.execute(
            select(StaffTeam.id, StaffTeam.name).where(StaffTeam.id.in_(team_ids))
        ):
            team_names[row.id] = row.name
    rows = []
    for result in results:
        first, last = names.get(result.agent_profile_uuid or result.staff_profile_uuid, ("", ""))
        rows.append(
            Row(
                kind=result.kind,
                agent_profile_uuid=result.agent_profile_uuid,
                staff_profile_uuid=result.staff_profile_uuid,
                team_uuid=result.team_uuid,
                user_uuid=result.recipient_user_uuid,
                first_name=first,
                last_name=last,
                team_name=team_names.get(result.team_uuid) if result.team_uuid else None,
                metric_value=result.metric_value,
                count=result.achieved_count,
                amount_paise=result.achieved_amount_paise,
                progress=dict(result.progress or {}),
                qualified=result.qualified,
                rank=result.rank,
                won=result.won,
                prize_paise=result.prize_paise,
                excluded_reason=result.excluded_reason,
                payment_status=result.payment_status,
                result_id=result.id,
                payout_uuid=result.payout_uuid,
                paid_reference=result.paid_reference,
                paid_marked_at=result.paid_marked_at,
            )
        )
    return rows


def _rank_key(row: Row) -> tuple:
    return (row.rank is None, row.rank or 0, row.display_name.casefold())


async def load_board(contest: Contest) -> Board:
    """Live standings for a running contest, the snapshot once it has ended."""
    async with db_session.AsyncSessionLocal() as session:
        if contest.status in _SNAPSHOT:
            rows = await _snapshot_rows(session, contest)
            ranked = sorted(
                (
                    r
                    for r in rows
                    if r.kind in (ContestResultKind.INDIVIDUAL, ContestResultKind.TEAM)
                ),
                key=_rank_key,
            )
            people = [
                r
                for r in rows
                if r.kind in (ContestResultKind.TEAM_MANAGER, ContestResultKind.TEAM_MEMBER)
            ]
            return Board("snapshot", contest.ended_at, ranked, people)
        if contest.status in (ContestStatus.LIVE.value, ContestStatus.APPROVED.value):
            standings = await compute_standings(session, contest, parse_criteria(contest))
            return Board(
                "live" if contest.status == ContestStatus.LIVE.value else "none",
                standings.computed_at,
                [_from_participant(p) for p in standings.ranked],
                [_from_participant(p) for p in standings.team_people],
            )
    return Board("none", None, [], [])


def _progress(row: Row) -> ContestProgress:
    return ContestProgress(**row.progress)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


@dataclass
class Viewer:
    role: str
    profile_uuid: uuid.UUID | None
    member_teams: dict[uuid.UUID, tuple[str, str]]  # team -> (line, member role)
    managed_teams: dict[uuid.UUID, tuple[str, str]]


async def _viewer(user: CurrentUser) -> Viewer:
    profile = user.agent_profile_uuid if user.role == "agent" else user.staff_profile_uuid
    member_teams: dict[uuid.UUID, tuple[str, str]] = {}
    managed_teams: dict[uuid.UUID, tuple[str, str]] = {}
    if user.role in ("telecaller", "employee", "sub_admin") and profile is not None:
        # Team rows are not readable by members under RLS; only the caller's
        # own memberships and managed teams are looked up here.
        async with db_session.AsyncSessionLocal() as session:
            if user.role == "sub_admin":
                rows = await session.execute(
                    select(StaffTeam.id, StaffTeam.business_line, StaffTeam.member_role).where(
                        StaffTeam.manager_staff_profile_uuid == profile,
                        StaffTeam.archived_at.is_(None),
                    )
                )
                managed_teams = {row.id: (row.business_line, row.member_role) for row in rows}
            else:
                rows = await session.execute(
                    select(StaffTeam.id, StaffTeam.business_line, StaffTeam.member_role)
                    .join(StaffTeamMember, StaffTeamMember.team_uuid == StaffTeam.id)
                    .where(
                        StaffTeamMember.staff_profile_uuid == profile,
                        StaffTeam.archived_at.is_(None),
                    )
                )
                member_teams = {row.id: (row.business_line, row.member_role) for row in rows}
    return Viewer(user.role, profile, member_teams, managed_teams)


def _matching_teams(viewer: Viewer, contest: Contest) -> set[uuid.UUID]:
    pool = viewer.managed_teams if viewer.role == "sub_admin" else viewer.member_teams
    return {
        team
        for team, (line, member_role) in pool.items()
        if line == contest.business_line and member_role == contest.team_member_role
    }


def _role_in(viewer: Viewer, contest: Contest) -> str | None:
    """How the viewer takes part in this contest, or None if they do not."""
    if contest.audience == ContestAudience.TEAM:
        if not _matching_teams(viewer, contest):
            return None
        return "team_manager" if viewer.role == "sub_admin" else "team_member"
    if viewer.role == contest.audience:
        return "participant"
    return None


async def _visible_contests(db: AsyncSession, contest_id: uuid.UUID | None = None) -> list[Contest]:
    stmt = select(Contest).where(Contest.status.in_(_VISIBLE))
    if contest_id is not None:
        stmt = stmt.where(Contest.id == contest_id)
    stmt = stmt.order_by(Contest.starts_on.desc(), Contest.id)
    return list(await db.scalars(stmt))


def _mine(viewer: Viewer, contest: Contest, row: Row) -> bool:
    if contest.audience == ContestAudience.TEAM:
        return False
    if viewer.role == "agent":
        return row.agent_profile_uuid == viewer.profile_uuid
    return row.staff_profile_uuid == viewer.profile_uuid


def _standing(row: Row, prize_row: Row | None, finalized: bool) -> MyStanding:
    source = prize_row or row
    return MyStanding(
        rank=row.rank,
        metric_value=row.metric_value,
        progress=_progress(row),
        qualified=row.qualified,
        won=source.won if finalized else None,
        prize_paise=source.prize_paise if finalized else None,
        payment_status=source.payment_status if finalized else None,
        excluded_reason=source.excluded_reason if finalized else None,
    )


@dataclass
class _Context:
    contest: Contest
    role: str
    board: Board
    my_row: Row | None  # individual row, or the caller's team row
    my_prize_row: Row | None  # team manager / member prize row
    team_ids: set[uuid.UUID]


async def _context(viewer: Viewer, contest: Contest) -> _Context | None:
    role = _role_in(viewer, contest)
    if role is None:
        return None
    board = await load_board(contest)
    my_row: Row | None = None
    my_prize_row: Row | None = None
    team_ids: set[uuid.UUID] = set()
    if contest.audience == ContestAudience.TEAM:
        team_ids = _matching_teams(viewer, contest)
        my_row = next((r for r in board.ranked if r.team_uuid in team_ids), None)
        wanted_kind = (
            ContestResultKind.TEAM_MANAGER
            if role == "team_manager"
            else ContestResultKind.TEAM_MEMBER
        )
        my_prize_row = next(
            (
                r
                for r in board.team_people
                if r.kind == wanted_kind
                and r.team_uuid in team_ids
                and r.staff_profile_uuid == viewer.profile_uuid
            ),
            None,
        )
    else:
        my_row = next((r for r in board.ranked if _mine(viewer, contest, r)), None)
    return _Context(contest, role, board, my_row, my_prize_row, team_ids)


def _summary_fields(ctx: _Context) -> dict:
    contest = ctx.contest
    finalized = contest.status == ContestStatus.FINALIZED.value
    eligible = ctx.my_row is not None and (
        contest.audience != ContestAudience.TEAM or ctx.my_prize_row is not None
    )
    return {
        "id": contest.id,
        "title": contest.title,
        "business_line": contest.business_line,
        "audience": contest.audience,
        "team_member_role": contest.team_member_role,
        "metric": contest.metric,
        "win_mode": contest.win_mode,
        "top_n": contest.top_n,
        "prize_paise": contest.prize_paise,
        "manager_prize_paise": contest.manager_prize_paise,
        "member_prize_paise": contest.member_prize_paise,
        "member_min_contribution": contest.member_min_contribution,
        "starts_on": contest.starts_on,
        "ends_on": contest.ends_on,
        "status": contest.status,
        "my_role": ctx.role,
        "eligible": eligible,
        "participants": len(ctx.board.ranked) if ctx.board.source != "none" else None,
        "me": (
            _standing(ctx.my_row, ctx.my_prize_row, finalized)
            if ctx.my_row is not None and ctx.board.source != "none"
            else None
        ),
    }


async def list_my_contests(db: AsyncSession, user: CurrentUser) -> list[MyContestSummary]:
    viewer = await _viewer(user)
    summaries = []
    for contest in await _visible_contests(db):
        ctx = await _context(viewer, contest)
        if ctx is not None:
            summaries.append(MyContestSummary(**_summary_fields(ctx)))
    return summaries


async def _hidden(db: AsyncSession, role: str) -> tuple[bool, bool]:
    """(names hidden, amounts hidden) for other participants, per Admin rule."""
    try:
        target = FieldTargetRole(role)
    except ValueError:
        return False, False
    modes = await effective_modes(db, target)
    return (
        modes.get(("contest_leaderboard", "names")) == FieldVisibilityMode.DENY,
        modes.get(("contest_leaderboard", "amounts")) == FieldVisibilityMode.DENY,
    )


async def get_my_contest(
    db: AsyncSession, user: CurrentUser, contest_id: uuid.UUID
) -> MyContestDetail:
    viewer = await _viewer(user)
    contests = await _visible_contests(db, contest_id)
    ctx = await _context(viewer, contests[0]) if contests else None
    if ctx is None:
        raise ContestNotFound("Contest not found.")
    contest = ctx.contest
    finalized = contest.status == ContestStatus.FINALIZED.value
    role_for_rules = contest.team_member_role if user.role == "sub_admin" else user.role
    names_hidden, amounts_hidden = (
        (False, False) if user.role == "sub_admin" else await _hidden(db, role_for_rules or "")
    )
    hide_amount = amounts_hidden and contest.metric == ContestMetric.AMOUNT

    leaderboard: list[LeaderboardEntry] = []
    if ctx.board.source != "none":
        shown = ctx.board.ranked[:LEADERBOARD_SIZE]
        if ctx.my_row is not None and ctx.my_row not in shown:
            shown = [*shown, ctx.my_row]
        for row in shown:
            is_me = row is ctx.my_row
            leaderboard.append(
                LeaderboardEntry(
                    rank=row.rank,
                    name=row.display_name if is_me or not names_hidden else None,
                    achieved=row.metric_value if is_me or not hide_amount else None,
                    qualified=row.qualified,
                    is_me=is_me,
                )
            )

    team: TeamStanding | None = None
    if contest.audience == ContestAudience.TEAM and ctx.my_row is not None:
        members = [
            r
            for r in ctx.board.team_people
            if r.kind == ContestResultKind.TEAM_MEMBER and r.team_uuid == ctx.my_row.team_uuid
        ]
        if ctx.role == "team_member":
            members = [r for r in members if r.staff_profile_uuid == viewer.profile_uuid]
        minimum = contest.member_min_contribution
        team = TeamStanding(
            team_name=ctx.my_row.display_name,
            rank=ctx.my_row.rank,
            metric_value=ctx.my_row.metric_value,
            progress=_progress(ctx.my_row),
            qualified=ctx.my_row.qualified,
            won=ctx.my_row.won if finalized else None,
            members=[
                TeamMemberStanding(
                    name=r.full_name,
                    metric_value=r.metric_value,
                    progress=_progress(r),
                    meets_member_minimum=(r.metric_value >= minimum) if minimum else None,
                    won=r.won if finalized else None,
                    prize_paise=r.prize_paise if finalized else None,
                    payment_status=r.payment_status if finalized else None,
                    is_me=r.staff_profile_uuid == viewer.profile_uuid,
                )
                for r in sorted(members, key=lambda r: (-r.metric_value, r.full_name.casefold()))
            ],
        )

    return MyContestDetail(
        **_summary_fields(ctx),
        description=contest.description,
        terms=contest.terms,
        criteria=parse_criteria(contest),
        budget_cap_paise=contest.budget_cap_paise,
        computed_at=ctx.board.computed_at,
        leaderboard=leaderboard,
        team=team,
    )


# ---------------------------------------------------------------------------
# Admin standings
# ---------------------------------------------------------------------------


def _standing_row(row: Row) -> StandingRow:
    if row.kind == ContestResultKind.TEAM:
        participant_type = "team"
    elif row.agent_profile_uuid is not None:
        participant_type = "agent"
    else:
        participant_type = "staff"
    return StandingRow(
        result_id=row.result_id,
        kind=row.kind,
        participant_type=participant_type,
        name=row.full_name,
        team_name=row.team_name,
        rank=row.rank,
        metric_value=row.metric_value,
        achieved_count=row.count,
        achieved_amount_paise=row.amount_paise,
        progress=_progress(row),
        qualified=row.qualified,
        won=row.won,
        prize_paise=row.prize_paise,
        excluded_reason=row.excluded_reason,
        payment_status=row.payment_status,
        payout_uuid=row.payout_uuid,
        paid_reference=row.paid_reference,
        paid_marked_at=row.paid_marked_at,
    )


async def admin_standings(
    db: AsyncSession, contest_id: uuid.UUID, viewer_uuid: uuid.UUID
) -> ContestStandingsResponse:
    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise ContestNotFound("Contest not found.")
    board = await load_board(contest)
    prize_rows = [
        r
        for r in [*board.ranked, *board.team_people]
        if r.kind != ContestResultKind.TEAM and r.prize_paise > 0
    ]
    return ContestStandingsResponse(
        contest=(await reads_for([contest], viewer_uuid))[0],
        source=board.source,
        computed_at=board.computed_at,
        rows=[_standing_row(r) for r in board.ranked],
        team_people=[
            _standing_row(r)
            for r in sorted(
                board.team_people,
                key=lambda r: (
                    str(r.team_uuid),
                    r.kind != ContestResultKind.TEAM_MANAGER,
                    -r.metric_value,
                ),
            )
        ],
        winners=sum(1 for r in prize_rows if r.won),
        prize_total_paise=sum(r.prize_paise for r in prize_rows),
        paid_total_paise=sum(
            r.prize_paise for r in prize_rows if r.payment_status == ContestPaymentStatus.PAID.value
        ),
    )
