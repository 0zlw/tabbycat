from adjallocation.models import DebateAdjudicator
from draw.models import Debate, DebateTeam
from results.models import TeamScore
from standings.templatetags.standingsformat import metricformat, rankingformat
from utils.misc import reverse_tournament

from .mixins import SuperuserRequiredMixin


class BaseTableBuilder:
    """Class for building tables that can be easily inserted into Vue tables,
    Designed to be used with VueTableMixin.

    In the docstrings for this class:
    - A *header dict* is a dict that contains a value under `"key"` that is a
      string, and may optionally contain entries under `"tooltip"`, `"icon"`,
      `"visible-sm"`, `"visible-md"` and `"visible-lg"`.
    - A *cell dict* is a dict that contains a value under `"text"` that is a
      string, and may optionally contain entries under `"sort"`, `"icon"`,
      `"emoji"`, `"popover"` and `"link"`.

    """

    def __init__(self, **kwargs):
        self.headers = []
        self.data = []
        self.title = kwargs.get('title', "")
        self.table_class = kwargs.get('table_class', "")
        self.sort_key = kwargs.get('sort_key', '')
        self.sort_order = kwargs.get('sort_order', '')

    @staticmethod
    def _convert_header(header):
        return {'key': header} if isinstance(header, str) else header

    @staticmethod
    def _convert_cell(cell):
        if isinstance(cell, int) or isinstance(cell, float):
            return {'text': str(cell)}
        if isinstance(cell, str):
            return {'text': cell}
        return cell

    def add_column(self, header, data):
        """Adds a column to the table.

        - `header` must be either a string or a header dict (see class docstring).
        - `data` must be a list of cells (in the column). Each cell should
          either be a string or a cell dict (see class docstring). If this is
          not the first column, then there must be as many elements in `data` as
          there are in the existing columns.
        """
        if len(self.data) > 0 and len(data) != len(self.data):
            raise ValueError("data contains {new:d} rows, existing table has {existing:d}".format(
                new=len(data), existing=len(self.data)))

        header = self._convert_header(header)
        self.headers.append(header)

        data = map(self._convert_cell, data)
        if len(self.data) == 0:
            self.data = [[cell] for cell in data]
        else:
            for row, cell in zip(self.data, data):
                row.append(cell)

    def add_boolean_column(self, header, data):
        """Convenience function for adding a column based on boolean data.

        - `header` must be either a string or a header dict.
        - `data` must be an iterable of booleans.
        """
        cells = [{
            'icon': 'glyphicon-ok' if datum else '',
            'sort':  1 if datum else 2,
        } for datum in data]
        self.add_column(header, cells)

    def add_columns(self, headers, data):
        """Adds columns to the table.

        This method is intended for situations where it is easier to process
        data by row while adding it to the table, than it is to process data
        by column. In the latter case, use `add_column()` instead.

        - `headers` must be a list of strings or header dicts (or both).
        - `data` must be a list of lists of cells, where each cell is a string
          or cell dict. Each inner list corresponds to a row, and all inner
          lists must contain the same number of elements, which must also match
          the number of elements in `headers`. If there are no existing columns
          in the table, then there must be as many inner lists as there are
          existing columns.
        """
        if len(self.data) > 0 and len(data) != len(self.data):
            raise ValueError("data contains {new:d} rows, existing table has {existing:d}".format(
                new=len(data), existing=len(self.data)))

        headers = map(self._convert_header, headers)
        self.headers.extend(headers)

        if len(self.data) == 0:
            self.data = [[self._convert_cell(cell) for cell in row] for row in data]
        else:
            for row, cells in zip(self.data, data):
                cells = map(self._convert_cell, cells)
                row.extend(cells)

    def jsondict(self):
        """Returns the JSON dict for the table."""
        return {
            'head': self.headers,
            'data': self.data,
            'title': self.title,
            'class': self.table_class,
            'sort_key': self.sort_key,
            'sort_order': self.sort_order
        }


class TabbycatTableBuilder(BaseTableBuilder):
    """Extends TableBuilder to add convenience functions specific to
    Tabbycat."""

    ADJ_SYMBOLS = {
        DebateAdjudicator.TYPE_CHAIR: " Ⓒ",
        DebateAdjudicator.TYPE_PANEL: "",
        DebateAdjudicator.TYPE_TRAINEE: " Ⓣ",
    }

    ADJ_TYPES = {
        DebateAdjudicator.TYPE_CHAIR: "Chair",
        DebateAdjudicator.TYPE_PANEL: "Panellist",
        DebateAdjudicator.TYPE_TRAINEE: "Trainee",
    }

    def __init__(self, view=None, **kwargs):
        """Constructor.
        - If `tournament` is specified, it becomes the default tournament for
          the builder.
        - If `admin` is True (default is False), then relevant links will go
          to the admin version rather than the public version.
        - If `view` is specified, then `tournament` and `admin` are inferred
          from `view`. This option is provided for convenience.
        """
        if 'tournament' not in kwargs and hasattr(view, 'get_tournament'):
            self.tournament = view.get_tournament()
        else:
            self.tournament = kwargs.get('tournament')

        if 'admin' not in kwargs and isinstance(view, SuperuserRequiredMixin):
            self.admin = True
        else:
            self.admin = kwargs.get('admin', False)

        return super().__init__(**kwargs)

    @property
    def _show_record_links(self):
        return self.admin or self.tournament.pref('public_record')

    def _adjudicator_record_link(self, adj):
        adj_short_name = adj.name.split(" ")[0]
        if self.admin:
            return {
                'text': "View %s's Adjudication Record" % adj_short_name,
                'link': reverse_tournament('participants-adjudicator-record',
                    self.tournament, kwargs={'pk': adj.pk})
            }
        elif self.tournament.pref('public_record'):
            return {
                'text': "View %s's Adjudication Record" % adj_short_name,
                'link': reverse_tournament('participants-public-adjudicator-record',
                    self.tournament, kwargs={'pk': adj.pk})
            }
        else:
            return {'text': False, 'link': False}

    def _team_record_link(self, team):
        if self.admin:
            return {
                'text': "View %s's Team Record" % team.short_name,
                'link': reverse_tournament('participants-team-record', self.tournament, kwargs={'pk': team.pk})
            }
        elif self.tournament.pref('public_record'):
            return {
                'text': "View %s's Team Record" % team.short_name,
                'link': reverse_tournament('participants-public-team-record', self.tournament, kwargs={'pk': team.pk})
            }
        else:
            return {'text': False, 'link': False}

    def _result_cell(self, ts, compress=False, show_score=False, show_ballots=False):
        if not hasattr(ts, 'debate_team'):
            return {'text': '-'}

        opp = ts.debate_team.opposition.team
        result = {
            'text': " vs " + opp.emoji if compress else opp.short_name,
            'popover': {'content': [{'text': ''}]}
        }
        result_popover = result['popover']['content'][0]
        if ts.win is True:
            result['icon'] = "glyphicon-arrow-up text-success"
            result['sort'] = 1
            result_popover['text'] = "Won against " + opp.long_name
        elif ts.win is False:
            result['icon'] = "glyphicon-arrow-down text-danger"
            result['sort'] = 2
            result_popover['text'] = "Lost to " + opp.long_name
        else: # None
            result['icon'] = ""
            result['sort'] = 3
            result_popover['text'] = "No result for debate against " + opp.long_name

        if show_score:
            result['subtext'] = metricformat(ts.score)
            result['popover']['content'].append(
                {'text': 'Received %s team points' % metricformat(ts.score)})

        if show_ballots:
            result['popover']['content'].append(
                {'text': 'View Debate Ballot', 'link': reverse_tournament('public_ballots_view',
                    self.tournament, kwargs={'debate_id': ts.debate_team.debate.id})})

        if self._show_record_links:
            result['popover']['content'].append(
                self._team_record_link(opp))

        return result

    def add_round_column(self, rounds, key="Round"):
        data = [{
            'sort': round.seq,
            'text': round.abbreviation,
            'tooltip': round.name,
        } for round in rounds]
        self.add_column(key, data)

    def add_adjudicator_columns(self, adjudicators, hide_institution=False, subtext=None):

        adj_data = []
        for adj in adjudicators:
            cell = {'text': adj.name}
            if self._show_record_links:
                cell['popover'] = {'content' : [self._adjudicator_record_link(adj)]}
            if subtext is 'institution':
                cell['subtext'] = adj.institution.code
            adj_data.append(cell)
        self.add_column("Name", adj_data)

        if self.tournament.pref('show_institutions') and not hide_institution:
            self.add_column("Institution", [adj.institution.code for adj in adjudicators])

        adjcore_header = {
            'key': 'adjcore',
            'tooltip': "Member of the Adjudication Core",
            'icon': 'glyphicon-sunglasses',
        }
        self.add_boolean_column(adjcore_header, [adj.adj_core for adj in adjudicators])

        independent_header = {
            'key': 'independent',
            'tooltip': "Independent Adjudicator",
            'icon': 'glyphicon-knight',
        }
        self.add_boolean_column(independent_header, [adj.independent for adj in adjudicators])

        if self.tournament.pref('show_unaccredited'):
            accreddited_header = {
                'key': 'accredited',
                'tooltip': "Is Accredited",
                'icon': 'glyphicon-leaf',
            }
            self.add_boolean_column(accreddited_header, [adj.novice for adj in adjudicators])

    def add_debate_adjudicators_column(self, debates, key="Adjudicators", show_splits=False):
        da_data = []

        def construct_text(adjs_data):
            adjs_list = ["%s%s%s" % (
                a['adj'].name,
                self.ADJ_SYMBOLS[a['type']],
                "<span class='text-danger'>💢</span>" if hasattr(a, 'split') else ''
            ) for a in adjs_data]
            return ', '.join([str(ad) for ad in adjs_list])

        def construct_popover(adjs_data):
            popover_data = []
            for a in adjs_data:
                popover_data.append({
                    'text': "%s (%s%s; from %s)" % (
                        a['adj'].name,
                        "<span class='text-danger'>Split</span>; " if hasattr(a, 'split') else '',
                        self.ADJ_TYPES[a['type']],
                        a['adj'].institution.code)
                })
                if self._show_record_links:
                    popover_data.append(self._adjudicator_record_link(a['adj']))

            return popover_data

        for debate in debates:
            adjs_data = []
            if debate.confirmed_ballot and show_splits and (self.admin or self.tournament.pref('show_splitting_adjudicators')):
                for adjtype, adj, split in debate.confirmed_ballot.ballot_set.adjudicator_results:
                    adjs_data.append(
                        {'adj': adj, 'type': adjtype, 'split': True if split else False})
            else:
                for adjtype, adj in debate.adjudicators:
                    adjs_data.append(
                        {'adj': adj, 'type': adjtype, 'split': None})

            da_data.append({
                'text': construct_text(adjs_data),
                'popover': {
                    'title': 'Debate Adjudicators',
                    'content' : construct_popover(adjs_data)
                }
            })

        self.add_column(key, da_data)

    def add_motion_column(self, motions, key="Motion", show_order=False):
        if show_order and self.tournament.pref('enable_motions'):
            self.add_column("Order", [motion.seq for motion in motions])

        motion_data = [{
            'text': motion.reference,
            'popover': {'content' : [{'text': motion.text}]}
        } if motion else "—" for motion in motions]
        self.add_column(key, motion_data)

    def add_team_columns(self, teams, break_categories=False, show_speakers=False,
            hide_institution=False, hide_emoji=False, key="Team"):

        display_speakers = True if self.tournament.pref(
            'show_speakers_in_draw') or show_speakers else False

        team_data = [{
            'text': team.short_name,
            'emoji': team.emoji if self.tournament.pref('show_emoji') and not hide_emoji else None,
            'sort': team.short_name,
            'popover': {
                'title': team.long_name,
                'content' : [
                    {'text': [" " + s.name for s in team.speakers]} if display_speakers else None,
                    self._team_record_link(team)
                ]}
        } for team in teams]
        self.add_column(key, team_data)

        if break_categories:
            self.add_column("Categories", [", ".join(bc.name for bc in team.break_categories) for team in teams])

        if self.tournament.pref('show_institutions') and not hide_institution:
            self.add_column("Institution", [team.institution.code for team in teams])

    def add_team_pullup_columns(self, debates, standings):
        pullups_header = {
            'key': "Pullups",
            'text': 'Pull',
            'tooltip': "Whether or not a team was a pull-up",
        }
        pullups_data = []
        for debate in debates:
            a_team_standing = standings.get_standing(debate.aff_team)
            a_is_pullup = abs(a_team_standing.metrics["points"] - debate.bracket) >= 1
            n_team_standing = standings.get_standing(debate.neg_team)
            n_is_pullup = abs(n_team_standing.metrics["points"] - debate.bracket) >= 1
            text = 'Aff' if a_is_pullup else ''
            text += 'Neg' if n_is_pullup else ''
            pullups_data.append({
                'sort': 1 if a_is_pullup or n_is_pullup else 0,
                'text': text
            })
        self.add_column(pullups_header, pullups_data)

    def add_speaker_columns(self, speakers, key="Name"):
        self.add_column(key, [speaker.name for speaker in speakers])
        if self.tournament.pref('show_novices'):
            novice_header = {
                'key': "Novice",
                'icon': 'glyphicon-leaf',
                'tooltip': "Novice Status",
            }
            self.add_boolean_column(novice_header, [speaker.novice for speaker in speakers])

    def add_room_rank_columns(self, debates):
        header = {
            'key': "Room rank",
            'icon': 'glyphicon-stats',
            'tooltip': 'Room rank of this debate'
        }
        self.add_column(header, [debate.room_rank for debate in debates])

    def add_debate_bracket_columns(self, debates):
        header = {
            'key': "Bracket",
            'icon': 'glyphicon-stats',
            'tooltip': 'Bracket of this debate'
        }
        self.add_column(header, [debate.bracket for debate in debates])

    def add_debate_venue_columns(self, debates, with_times=False):
        if self.tournament.pref('enable_divisions'):
            divisions_header = {
                'key': 'Division',
                'icon': 'glyphicon-th-list',
                'tooltip': 'Division'
            }
            divisions_data = ['D' + d.division.name if d.division else '' for d in debates]
            self.add_column(divisions_header, divisions_data)

        venue_header = {
            'key': "Venue",
            'icon': 'glyphicon-map-marker',
        }
        if self.tournament.pref('enable_venue_groups'):
            venue_data = [
                debate.division.venue_group.short_name if debate.division
                else (debate.venue.group.short_name + debate.venue.name) if debate.venue
                else ''
                for debate in debates
            ]
        else:
            venue_data = [debate.venue.name if debate.venue else '' for debate in debates]
        self.add_column(venue_header, venue_data)

        if with_times and self.tournament.pref('enable_debate_scheduling'):
            times_headers = ["Date", "Time"]
            times_data = []
            for debate in debates:
                if debate.aff_team.type == Debate.TYPE_BYE or debate.neg_team.type == Debate.TYPE_BYE:
                    times_data.append(["", "Bye"])
                elif debate.result_status == Debate.STATUS_POSTPONED:
                    times_data.append(["", "Postponed"])
                elif debate.confirmed_ballot.forfeit:
                    times_data.append(["", "Forfeit"])
                else:
                    times_data.append([debate.time.strftime("D jS F"), debate.time.strftime("h:i A")])
            self.add_columns(times_headers, times_data)

    def add_draw_conflicts(self, draw):
        conflicts_header = {'key': "Conflicts/Flags"}
        conflicts_data = [{
            'text': debate.draw_conflicts + debate.flags_all,
            'class': 'text-danger small'
        } for debate in draw]
        self.add_column(conflicts_header, conflicts_data)

    def add_ranking_columns(self, standings, subset=None, prefix=' '):
        standings_list = standings.get_standings(subset) if subset is not None else standings
        headers = [{
            'key': prefix[0] + info['abbr'],
            'tooltip': prefix + info['name'].title(),
            'glyphicon': info['glyphicon'],
        } for info in standings.rankings_info()]
        data = []
        for standing in standings_list:
            data.append([{
                'text': rankingformat(ranking),
                'sort': ranking[0] or "99999",
            } for ranking in standing.iterrankings()])
        self.add_columns(headers, data)

    def add_debate_ranking_columns(self, draw, standings):
        # First half (ie all aff metrics) then second (ie all neg metrics)
        self.add_ranking_columns(standings, subset=[d.aff_team for d in draw], prefix="Aff's ")
        self.add_ranking_columns(standings, subset=[d.neg_team for d in draw], prefix="Neg's ")

    def add_metric_columns(self, standings, subset=None, prefix=' '):
        standings_list = standings.get_standings(subset) if subset is not None else standings
        headers = [{
            'key': prefix[0] + info['abbr'],
            'tooltip': prefix + info['name'].title(),
            'glyphicon': info['glyphicon'],
        } for info in standings.metrics_info()]
        data = [list(map(metricformat, s.itermetrics())) for s in standings_list]
        self.add_columns(headers, data)

    def add_debate_metric_columns(self, draw, standings):
        # First half (ie all aff metrics) then second (ie all neg metrics)
        self.add_metric_columns(standings, subset=[d.aff_team for d in draw], prefix="Aff's ")
        self.add_metric_columns(standings, subset=[d.neg_team for d in draw], prefix="Neg's ")

    def highlight_rows_by_column_value(self, column):
        highlighted_rows = [i for i in range(1, len(self.data))
                if self.data[i][column] != self.data[i-1][column]]
        for i in highlighted_rows:
            self.data[i] = [self._convert_cell(cell) for cell in self.data[i]]
            for cell in self.data[i]:
                cell['class'] = cell.get('class', '') + ' highlight-row'

    def add_affs_count(self, teams, round, team_type):
        affs_header = {
            'key':  'aaffs' if team_type is 'aff' else 'naffs',
            'tooltip': 'Number of times the current ' + team_type + ' has been in the affirmative position before'
        }
        affs_data = [{
            'text': t.get_aff_count(round.seq) if round.prev else '',
        } for t in teams]
        self.add_column(affs_header, affs_data)

    # def add_draw_metric_columns(self, teams, round, standings):
    #     aff_standings = [standings.get_standing(t) for t in teams]

    #     if round.is_break_round:
    #         self.add_breakrank_columns(teams, round)
    #     else:
    #         if "points" in standings.metric_keys:
    #             aff_is_pullup = abs(aff_standing.metrics["points"] - debate.bracket) >= 1

    #         aff_subrank = aff_standing.rankings["subrank"]

    #     # debate.metrics = [(a, n) for a, n in zip(aff_standing.itermetrics(), neg_standing.itermetrics())]

    def add_checkbox_columns(self, states, references, key):
        state_header = {'key': key}
        state_data = [{
            'sort': state,
            'class': 'checkbox-target',
            'text': '<input type="checkbox" class="vue-table-checkbox" data-target="%s" %s>' % (reference, 'checked' if state else ''),
        } for state, reference in zip(states, references)]
        self.add_column(state_header, state_data)

    def add_debate_ballot_link_column(self, debates):
        ballot_links_header = {'key': "Ballot", 'icon': 'glyphicon-search'}

        if self.admin:
            ballot_links_data = [{
                'text': "View/Edit Ballot",
                'link': reverse_tournament('edit_ballotset', self.tournament, kwargs={'ballotsub_id': debate.confirmed_ballot.id})
            } if debate.confirmed_ballot else "" for debate in debates]
            self.add_column(ballot_links_header, ballot_links_data)

        elif self.tournament.pref('ballots_released'):
            ballot_links_header = {'key': "Ballot", 'icon': 'glyphicon-search'}
            ballot_links_data = [{
                'text': "View Ballot",
                'link': reverse_tournament('public_ballots_view', self.tournament, kwargs={'debate_id': debate.id})
            } if debate else "" for debate in debates]
            self.add_column(ballot_links_header, ballot_links_data)

    def add_debate_result_by_team_columns(self, teamscores):
        """Takes an iterable of TeamScore objects."""

        results_data = [self._result_cell(ts) for ts in teamscores]
        self.add_column("Result", results_data)
        self.add_column("Side", [ts.debate_team.get_position_display() for ts in teamscores])

    def add_team_results_columns(self, teams, rounds):
        """ Takes an iterable of Teams, assumes their round_results match rounds"""
        for round_seq, round in enumerate(rounds):
            results = [self._result_cell(
                t.round_results[round_seq]) for t in teams]
            self.add_column(round.abbreviation, results)

    def add_debate_results_columns(self, debates):
        teamscores = TeamScore.objects.filter(debate_team__debate__in=debates)
        results = {}
        for ts in teamscores:
            results[(ts.debate_team.debate, ts.debate_team.position)] = ts
        results_data = []
        for debate in debates:
            aff_ts = results.get((debate, DebateTeam.POSITION_AFFIRMATIVE))
            neg_ts = results.get((debate, DebateTeam.POSITION_NEGATIVE))
            results_data.append([self._result_cell(ts) for ts in (aff_ts, neg_ts)])
        self.add_columns(["Affirmative", "Negative"], results_data)

    def add_standings_results_columns(self, standings, rounds, show_ballots):

        for round_seq, round in enumerate(rounds):
            results = [self._result_cell(
                s.round_results[round_seq],
                compress=True,
                show_score=True,
                show_ballots=show_ballots
            ) for s in standings]
            self.add_column(round.abbreviation, results)
