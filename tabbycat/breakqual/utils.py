import logging

from django.db.models import Count, Sum
from django.db.models.expressions import RawSQL

from standings.teams import TeamStandingsGenerator

from .liveness import liveness_bp, liveness_twoteam

logger = logging.getLogger(__name__)


def get_breaking_teams(category, prefetch=(), rankings=('rank',)):
    """Returns a list of StandingInfo objects, one for each team, with one
    additional attribute populated: for each StandingInfo `tsi`,
    `tsi.break_rank` is the rank of the team out of those that are in the break.

    `prefetch` is passed to `prefetch_related()` in the Team query.
    `rankings` is passed to `rankings` in the TeamStandingsGenerator.
    """
    teams = category.breaking_teams.all().prefetch_related(*prefetch)
    metrics = category.tournament.pref('team_standings_precedence')
    generator = TeamStandingsGenerator(metrics, rankings)
    standings = generator.generate(teams)

    breakingteams_by_team_id = {bt.team_id: bt for bt in category.breakingteam_set.all()}

    for tsi in standings:

        bt = breakingteams_by_team_id[tsi.team.id]
        if bt.break_rank is None:
            if bt.remark:
                tsi.break_rank = "(" + bt.get_remark_display().lower() + ")"
            else:
                tsi.break_rank = "<no rank, no remark>"
        else:
            tsi.break_rank = bt.break_rank

    return standings


def get_scores(bc):
    teams = bc.team_set.filter(
        debateteam__teamscore__ballot_submission__confirmed=True
    ).annotate(score=Sum('debateteam__teamscore__points'))
    scores = sorted([team.score for team in teams], reverse=True)
    return scores


def breakcategories_with_counts(tournament):
    breaking = RawSQL("""
        SELECT DISTINCT COUNT(breakqual_breakingteam.id) FROM breakqual_breakingteam
        WHERE breakqual_breakcategory.id = breakqual_breakingteam.break_category_id
        AND breakqual_breakingteam.break_rank IS NOT NULL
    """, ())
    excluded = RawSQL("""
        SELECT DISTINCT COUNT(breakqual_breakingteam.id) FROM breakqual_breakingteam
        WHERE breakqual_breakcategory.id = breakqual_breakingteam.break_category_id
        AND breakqual_breakingteam.break_rank IS NULL
    """, ())
    categories = tournament.breakcategory_set.annotate(
        eligible=Count('team', distinct=True),
        breaking=breaking,
        excluded=excluded
    )
    for category in categories:
        category.nonbreaking = category.eligible - category.breaking
    return categories


def liveness(self, team, teams_count, prelims, current_round):
    live_info = {'text': team.wins_count, 'tooltip': ''}

    # The actual calculation should be shifed to be a cached method on
    # the relevant break category
    highest_liveness = 3
    for bc in team.break_categories.all():
        import random
        status = random.choice([1,2,3])
        highest_liveness = 3
        if status is 1:
            live_info['tooltip'] += 'Definitely in for the %s break<br>test' % bc.name
            if highest_liveness != 2:
                highest_liveness = 1  # Live not ins are the most important highlight
        elif status is 2:
            live_info['tooltip'] += 'Still live for the %s break<br>test' % bc.name
            highest_liveness = 2
        elif status is 3:
            live_info['tooltip'] += 'Cannot break in %s break<br>test' % bc.name

    if highest_liveness is 1:
        live_info['class'] = 'bg-success'
    elif highest_liveness is 2:
        live_info['class'] = 'bg-warning'

    return live_info


def determine_liveness(thresholds, points):
    """ Thresholds should be calculated using calculate_live_thresholds."""
    safe, dead = thresholds
    if points is None:
        points = 0 # For when a results-less team (i.e. swings) is subbing in

    if safe is None and dead is None:
        return '?'
    elif points >= safe:
        return 'safe'
    elif points <= dead:
        return 'dead'
    else:
        return 'live'


def calculate_live_thresholds(bc, tournament, round):
    total_teams = tournament.team_set.count()
    total_rounds = tournament.prelim_rounds().count()
    team_scores = get_scores(bc) if not bc.is_general else None

    if team_scores is not None and len(team_scores) == 0:
        return -1, -1 # First round; no scores to base calculations off
    elif bc.break_size <= 1:
        return None, None # Bad input
    elif bc.break_size >= bc.team_set.count():
        return 0, 0 # All teams break
    elif total_teams == 0:
        return None, None
    elif tournament.pref('teams_in_debate') == 'bp':
        safe, dead = liveness_bp(bc.is_general, round.seq, bc.break_size,
                            total_teams, total_rounds, team_scores)
    else:
        safe, dead = liveness_twoteam(bc.is_general, round.seq, bc.break_size,
                              total_teams, total_rounds, team_scores)

    logger.info("Liveness in %s R%d/%d with break size %d, %d teams: safe at %d, dead at %d",
        tournament.short_name, round.seq, total_rounds, bc.break_size, total_teams, safe, dead)
    return safe, dead
