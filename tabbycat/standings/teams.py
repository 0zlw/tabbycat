"""Standings generator for teams."""

import logging

from django.db.models import Prefetch, Sum
from django.db.models.expressions import RawSQL
from django.utils.translation import ugettext_lazy as _

from draw.models import DebateTeam
from draw.prefetch import populate_opponents
from tournaments.models import Round
from results.models import TeamScore

from .base import BaseStandingsGenerator
from .metrics import BaseMetricAnnotator, metricgetter, QuerySetMetricAnnotator, RepeatedMetricAnnotator
from .ranking import BasicRankAnnotator, DivisionRankAnnotator, RankFromInstitutionAnnotator, SubrankAnnotator

logger = logging.getLogger(__name__)


# ==============================================================================
# Metric annotators
# ==============================================================================

class TeamScoreQuerySetMetricAnnotator(QuerySetMetricAnnotator):
    """Base class for annotators that metrics based on conditional aggregations
    of TeamScore instances."""

    function = None  # must be set by subclasses
    field = None  # must be set by subclasses

    exclude_forfeits = False
    where_value = None

    @staticmethod
    def get_annotation_metric_query_str(field, function, round=None, exclude_forfeits=False, where_value=None):
        """Returns a string, being an SQL query that can be passed into RawSQL()."""
        # This is what might be more concisely expressed, if it were permissible
        # in Django, as:
        # teams = teams.annotate_if(
        #     models.Sum('debateteam__teamscore__{field:s}'),
        #     condition={"debateteam__teamscore__ballot_submission__confirmed": True,
        #         "debateteam__debate__round__stage": Round.STAGE_PRELIMINARY}
        # )
        #
        # That is, it adds up the relevant field on *confirmed* ballots for each
        # team and adds them as columns to the table it returns. The standings
        # include only preliminary rounds.

        query = """
            SELECT DISTINCT {function}({field:s})
            FROM results_teamscore
            JOIN results_ballotsubmission ON results_teamscore.ballot_submission_id = results_ballotsubmission.id
            JOIN draw_debateteam ON results_teamscore.debate_team_id = draw_debateteam.id
            JOIN draw_debate ON draw_debateteam.debate_id = draw_debate.id
            JOIN tournaments_round ON draw_debate.round_id = tournaments_round.id
            WHERE results_ballotsubmission.confirmed = TRUE
            AND draw_debateteam.team_id = participants_team.id
            AND tournaments_round.stage = '""" + str(Round.STAGE_PRELIMINARY) + "\'"

        if round is not None:
            query += """
            AND tournaments_round.seq <= {round:d}""".format(round=round.seq)

        if exclude_forfeits:
            query += """
            AND results_teamscore.forfeit = FALSE"""

        if where_value is not None:
            query += """
            AND {field:s} = """ + str(where_value)

        return query.format(field=field, function=function)

    def get_annotation_metric_query_args(self, round):
        return (self.field, self.function, round, self.exclude_forfeits, self.where_value)


class Points210MetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for team points using win = 2, loss = 1, loss by forfeit = 0."""
    key = "points210"
    name = _("points")
    abbr = _("Pts")

    choice_name = _("Points (2/1/0)")

    def annotate(self, queryset, standings, round=None):
        # Includes forfeits
        wins_query = self.get_annotation_metric_query_str("win", "COUNT", round, False, "TRUE")
        # Excludes forfeits
        losses_query = self.get_annotation_metric_query_str("win", "COUNT", round, True, "FALSE")
        query = "({wins}) * 2 + ({losses})".format(wins=wins_query, losses=losses_query)
        sql = RawSQL(query, ())
        logger.info("Running query: " + query)
        queryset = queryset.annotate(metric=sql).distinct()

        # Calculate bye debates
        bye_points = 2 # Byes worth 2 points for WADL
        from draw.models import Debate
        from participants.models import Team
        debates_with_byes = Debate.objects.filter(debateteam__team__type=Team.TYPE_BYE,
                                                  round__stage=Round.STAGE_PRELIMINARY)
        for item in queryset:
            byes = debates_with_byes.filter(debateteam__team=item).count()
            wins_including_byes = item.metric + byes * bye_points
            # Manually implement annotate_with_queryset()
            standings.add_metric(item, self.key, wins_including_byes)


class PointsMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for total number of points."""
    key = "points"
    name = _("points")
    abbr = _("Pts")

    function = "SUM"
    field = "points"


class WinsMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for total number of wins."""
    key = "wins"
    name = _("wins")
    abbr = _("Wins")

    function = "COUNT"
    field = "win"
    where_value = "TRUE"


class TotalSpeakerScoreMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for total speaker score."""
    key = "speaks_sum"
    name = _("total speaker score")
    abbr = _("Spk")

    function = "SUM"
    field = "score"


class AverageSpeakerScoreMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for total speaker score."""
    key = "speaks_avg"
    name = _("average speaker score")
    abbr = _("ASS")
    exclude_forfeits = True

    function = "AVG"
    field = "score"


class SumMarginMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for sum of margins."""
    key = "margin_sum"
    name = _("sum of margins")
    abbr = _("Marg")

    function = "SUM"
    field = "margin"


class AverageMarginMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for average margin, excluding forfeit ballots."""
    key = "margin_avg"
    name = _("average margin")
    abbr = _("AWM")

    function = "AVG"
    field = "margin"
    exclude_forfeits = True


class DrawStrengthMetricAnnotator(BaseMetricAnnotator):
    """Metric annotator for draw strength."""
    key = "draw_strength"
    name = _("draw strength")
    abbr = _("DS")

    def annotate(self, queryset, standings, round=None):
        if not queryset.exists():
            return

        logger.info("Running points query for draw strength:")
        points_queryset = TeamScoreQuerySetMetricAnnotator.get_annotated_queryset(
            queryset[0].tournament.team_set.all(), "points", "points", "SUM", round)

        if round is not None:
            prefetch_queryset = DebateTeam.objects.filter(debate__round__seq__lte=round.seq)
        else:
            prefetch_queryset = DebateTeam.objects.filter(debate__round__stage=Round.STAGE_PRELIMINARY)
        points_queryset = points_queryset.prefetch_related(Prefetch('debateteam_set',
                queryset=prefetch_queryset, to_attr='debateteams'))
        points_queryset_teams = {team.id: team for team in points_queryset}
        points_queryset_debateteams = {team.id: list(team.debateteams) for team in points_queryset}

        populate_opponents([dt for dts in points_queryset_debateteams.values() for dt in dts])

        for team in queryset:
            draw_strength = 0
            for dt in points_queryset_debateteams[team.id]:
                points = points_queryset_teams[dt.opponent.team_id].points
                if points is not None: # points is None when no debates have happened
                    draw_strength += points
            standings.add_metric(team, self.key, draw_strength)


class NumberOfAdjudicatorsMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    """Metric annotator for number of votes given by a panel.

    The metric normalizes each debate to an assumed typical panel size. For
    example, if `self.adjs_per_debate == 3`, but a particular debate has a panel
    of five, then for that debate, a team winning on a 4-1 split will earn
    "2.4 votes" for that debate."""

    key = "num_adjs"
    name = _("number of adjudicators who voted for this team")
    abbr = _("Ballots")
    choice_name = _("votes/ballots carried")
    function = "SUM"

    def __init__(self, adjs_per_debate=3):
        self.adjs_per_debate = 3

    @property
    def field(self):
        return "CAST(votes_given AS float) / NULLIF(votes_possible, 0) * {:d}".format(self.adjs_per_debate)

    def annotate(self, queryset, standings, round=None):
        super().annotate(queryset, standings, round)

        # If the number of ballots carried by every team is an integer, then
        # it's probably (though not certainly) the case that there are no
        # "weird" cases causing any fractional numbers of votes due to
        # normalization. In that case, convert all metrics to integers.
        if all(tsi.metrics[self.key] == int(tsi.metrics[self.key]) for tsi in standings.infoview()):
            for tsi in standings.infoview():
                tsi.metrics[self.key] = int(tsi.metrics[self.key])


class NumberOfFirstsMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    key = "firsts"
    name = _("number of firsts")
    abbr = _("1sts")

    function = "COUNT"
    field = "points"
    where_value = 3


class NumberOfSecondsMetricAnnotator(TeamScoreQuerySetMetricAnnotator):
    key = "seconds"
    name = _("number of seconds")
    abbr = _("2nds")

    function = "COUNT"
    field = "points"
    where_value = 2


class WhoBeatWhomMetricAnnotator(RepeatedMetricAnnotator):
    """Metric annotator for who-beat-whom. Use once for every who-beat-whom in
    the precedence."""

    key_prefix = "wbw"
    name_prefix = _("Who-beat-whom")
    abbr_prefix = _("WBW")
    choice_name = _("who-beat-whom")

    def __init__(self, index, keys):
        if len(keys) == 0:
            raise ValueError("keys must not be empty")
        super(WhoBeatWhomMetricAnnotator, self).__init__(index, keys)

    def get_team_scores(self, key, equal_teams, tsi, round):
        equal_teams.remove(tsi)
        other = equal_teams[0]
        ts = TeamScore.objects.filter(
            ballot_submission__confirmed=True,
            debate_team__team=tsi.team,
            debate_team__debate__debateteam__team=other.team)

        if round is not None:
            ts = ts.filter(debate_team__debate__round__seq__lte=round.seq)

        ts = ts.aggregate(Sum('points'))
        logger.info("who beat whom, %s %s vs %s %s: %s",
            tsi.team.short_name, key(tsi), other.team.short_name, key(other),
            ts["points__sum"])
        return ts

    def annotate(self, queryset, standings, round=None):
        key = metricgetter(*self.keys)

        def who_beat_whom(tsi):
            equal_teams = [x for x in standings.infoview() if key(x) == key(tsi)]
            if len(equal_teams) != 2:
                return "n/a"  # fail fast if attempt to compare with an int

            ts = self.get_team_scores(key, equal_teams, tsi, round)
            return ts["points__sum"] or 0

        for tsi in standings.infoview():
            wbw = who_beat_whom(tsi)
            tsi.add_metric(self.key, wbw)


class DivisionsWhoBeatWhomMetricAnnotator(WhoBeatWhomMetricAnnotator):
    """Metric annotator for who-beat-whom within divisions. Use once for
    every who-beat-whom in the precedence."""

    key_prefix = "wbwd"
    name_prefix = _("Who-beat-whom (in division)")
    abbr_prefix = _("WBWD")
    choice_name = _("who-beat-whom (in divisions)")

    def annotate(self, queryset, standings, round=None):
        key = metricgetter(*self.keys)

        def who_beat_whom_divisions(tsi):
            equal_teams = [x for x in standings.infoview() if key(x) == key(tsi) and x.team.division == tsi.team.division]
            if len(equal_teams) != 2:
                return 0  # Fail fast if attempt to compare with an int

            ts = self.get_team_scores(key, equal_teams, tsi, round)
            return ts["points__sum"] or 0

        for tsi in standings.infoview():
            wbwd = who_beat_whom_divisions(tsi)
            tsi.add_metric(self.key, wbwd)


# ==============================================================================
# Standings generator
# ==============================================================================

class TeamStandingsGenerator(BaseStandingsGenerator):
    """Class for generating standings. An instance is configured with metrics
    and rankings in the constructor, and an iterable of Team objects is passed
    to its `generate()` method to generate standings. Example:

        generator = TeamStandingsGenerator(('points', 'speaker_score'), ('rank',))
        standings = generator.generate(teams)

    The generate() method returns a TeamStandings object.
    """

    TIEBREAK_FUNCTIONS = BaseStandingsGenerator.TIEBREAK_FUNCTIONS.copy()
    TIEBREAK_FUNCTIONS["shortname"] = lambda x: x.sort(key=lambda y: y.team.short_name)
    TIEBREAK_FUNCTIONS["institution"] = lambda x: x.sort(key=lambda y: y.team.institution.name)

    metric_annotator_classes = {
        "points"        : PointsMetricAnnotator,
        "points210"     : Points210MetricAnnotator,
        "wins"          : WinsMetricAnnotator,
        "speaks_sum"    : TotalSpeakerScoreMetricAnnotator,
        "speaks_avg"    : AverageSpeakerScoreMetricAnnotator,
        "draw_strength" : DrawStrengthMetricAnnotator,
        "margin_sum"    : SumMarginMetricAnnotator,
        "margin_avg"    : AverageMarginMetricAnnotator,
        "num_adjs"      : NumberOfAdjudicatorsMetricAnnotator,
        "firsts"        : NumberOfFirstsMetricAnnotator,
        "seconds"       : NumberOfSecondsMetricAnnotator,
        "wbw"           : WhoBeatWhomMetricAnnotator,
        "wbwd"          : DivisionsWhoBeatWhomMetricAnnotator,
    }

    ranking_annotator_classes = {
        "rank"        : BasicRankAnnotator,
        "subrank"     : SubrankAnnotator,
        "division"    : DivisionRankAnnotator,
        "institution" : RankFromInstitutionAnnotator,
    }
