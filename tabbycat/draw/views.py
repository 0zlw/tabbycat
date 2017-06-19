import json
import datetime
import logging

from math import floor

from django.views.generic.base import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.utils.translation import ugettext as _

from actionlog.mixins import LogActionMixin
from actionlog.models import ActionLogEntry
from adjallocation.models import DebateAdjudicator
from divisions.models import Division
from participants.models import Adjudicator, Institution, Team
from standings.teams import TeamStandingsGenerator
from tournaments.mixins import CrossTournamentPageMixin, DrawForDragAndDropMixin
from tournaments.mixins import OptionalAssistantTournamentPageMixin, PublicTournamentPageMixin, RoundMixin, SaveDragAndDropDebateMixin, TournamentMixin
from tournaments.models import Round
from tournaments.utils import aff_name, get_side_name, neg_name
from utils.mixins import CacheMixin, PostOnlyRedirectView, SuperuserRequiredMixin, VueTableTemplateView
from utils.misc import reverse_round
from utils.tables import TabbycatTableBuilder
from venues.allocator import allocate_venues
from venues.models import VenueCategory, VenueConstraint

from .dbutils import delete_round_draw
from .generator import DrawError
from .manager import DrawManager
from .models import Debate, DebateTeam, TeamSideAllocation
from .prefetch import populate_history

logger = logging.getLogger(__name__)


class BaseDrawTableView(RoundMixin, VueTableTemplateView):

    template_name = 'draw_display_by.html'
    sort_key = 'Venue'

    def get_page_title(self):
        return 'Draw for %s' % self.get_round().name

    def get_page_emoji(self):
        if not self.get_round():
            return None # Cross-Tournament pages
        elif self.get_round().draw_status == Round.STATUS_RELEASED:
            return '👏'
        else:
            return '😴'

    def get_page_subtitle(self):
        round = self.get_round()
        if round and round.starts_at:
            return 'debates start at %s' % round.starts_at.strftime('%H:%M')
        else:
            return ''

    def get_context_data(self, **kwargs):
        kwargs['round'] = self.get_round()
        return super().get_context_data(**kwargs)

    def get_draw(self):
        round = self.get_round()
        draw = round.debate_set_with_prefetches()
        return draw

    def populate_table(self, draw, table, round, tournament):
        if hasattr(self, 'cross_tournament') and self.cross_tournament is True:
            table.add_tournament_column(d.round.tournament for d in draw) # For cross-tournament draws

        if not round:
            table.add_round_column(d.round for d in draw) # For mass draws

        table.add_debate_venue_columns(draw)
        table.add_team_columns([d.aff_team for d in draw], hide_institution=True, key=aff_name(tournament))
        table.add_team_columns([d.neg_team for d in draw], hide_institution=True, key=neg_name(tournament))

        if tournament.pref('enable_division_motions'):
            table.add_motion_column(d.division_motion for d in draw)

        if not tournament.pref('enable_divisions'):
            table.add_debate_adjudicators_column(draw, show_splits=False)

    def get_table(self):
        tournament = self.get_tournament()
        round = self.get_round()
        draw = self.get_draw()
        table = TabbycatTableBuilder(view=self, sort_key=self.sort_key)
        self.populate_table(draw, table, round, tournament)
        return table


# ==============================================================================
# Viewing Draw (Public)
# ==============================================================================

class PublicDrawForRoundView(PublicTournamentPageMixin, CacheMixin, BaseDrawTableView):

    public_page_preference = 'public_draw'

    def get_template_names(self):
        round = self.get_round()
        if round.draw_status != round.STATUS_RELEASED:
            messages.info(self.request, 'The draw for ' + round.name +
                ' has yet to be released')
            return ["base.html"]
        else:
            return super().get_template_names()

    def get_context_data(self, **kwargs):
        round = self.get_round()
        if round.draw_status != round.STATUS_RELEASED:
            kwargs["round"] = self.get_round()
            return super(BaseDrawTableView, self).get_context_data(**kwargs) # skip BaseDrawTableView
        else:
            return super().get_context_data(**kwargs)


class PublicDrawForCurrentRoundView(PublicDrawForRoundView):

    def get_round(self):
        return self.get_tournament().current_round


class PublicAllDrawsAllTournamentsView(PublicTournamentPageMixin, CacheMixin, BaseDrawTableView):
    public_page_preference = 'enable_mass_draws'

    def get_round(self):
        return None

    def get_page_title(self):
        return 'All Debates for all Rounds of %s ' % self.get_tournament().name

    def get_draw(self):
        all_rounds = Round.objects.filter(tournament=self.get_tournament(),
                                          draw_status=Round.STATUS_RELEASED)
        draw = []
        for round in all_rounds:
            draw.extend(round.debate_set_with_prefetches())
        return draw


# ==============================================================================
# Viewing Draw (Admin)
# ==============================================================================

class AdminDrawDisplay(LoginRequiredMixin, BaseDrawTableView):

    assistant_page_permissions = ['all_areas', 'results_draw']
    template_name = 'draw_display.html'


class AdminDrawDisplayForRoundByVenueView(OptionalAssistantTournamentPageMixin, BaseDrawTableView):

    assistant_page_permissions = ['all_areas', 'results_draw']


class AdminDrawDisplayForRoundByTeamView(OptionalAssistantTournamentPageMixin, BaseDrawTableView):

    assistant_page_permissions = ['all_areas', 'results_draw']
    sort_key = 'Team'

    def populate_table(self, draw, table, round, tournament):
        draw = list(draw) + list(draw) # Double up the draw
        draw_slice = len(draw) // 2 # Top half gets affs; bottom negs
        table.add_team_columns(
            [d.aff_team for d in draw[:draw_slice]] + [d.neg_team for d in draw[draw_slice:]],
            hide_institution=True, key="Team")
        super().populate_table(draw, table, round, tournament)


# ==============================================================================
# Draw Creation (Admin)
# ==============================================================================

class AdminDrawView(RoundMixin, SuperuserRequiredMixin, VueTableTemplateView):
    detailed = False
    sort_key = 'Bracket'
    sort_order = 'desc'

    def get_page_title(self):
        round = self.get_round()
        self.page_emoji = '👀'
        if self.detailed:
            return 'Draw with Details for %s' % round.name
        if round.draw_status == round.STATUS_NONE:
            return 'No draw for %s' % round.name
        elif round.draw_status == round.STATUS_DRAFT:
            return 'Draft draw for %s' % round.name
        elif round.draw_status == round.STATUS_CONFIRMED:
            self.page_emoji = '👏'
            return 'Confirmed Draw for %s' % round.name
        elif round.draw_status == round.STATUS_RELEASED:
            self.page_emoji = '👏'
            return 'Released draw for %s' % round.name
        else:
            raise

    def get_table(self):
        r = self.get_round()
        tournament = self.get_tournament()
        table = TabbycatTableBuilder(view=self, sort_key=self.sort_key, sort_order=self.sort_order)
        if r.draw_status == r.STATUS_NONE:
            return table # Return Blank

        draw = r.debate_set_with_prefetches(ordering=('room_rank',), institutions=True, venues=True)
        populate_history(draw)
        if r.is_break_round:
            table.add_room_rank_columns(draw)
        else:
            table.add_debate_bracket_columns(draw)

        table.add_debate_venue_columns(draw, for_admin=True)
        table.add_team_columns([d.aff_team for d in draw], key=aff_name(tournament).capitalize(),
            hide_institution=True)
        table.add_team_columns([d.neg_team for d in draw], key=neg_name(tournament).capitalize(),
            hide_institution=True)

        # For draw details and draw draft pages
        if (r.draw_status == r.STATUS_DRAFT or self.detailed) and r.prev:
            teams = Team.objects.filter(debateteam__debate__round=r)
            metrics = r.tournament.pref('team_standings_precedence')
            generator = TeamStandingsGenerator(metrics, ('rank', 'subrank'))
            standings = generator.generate(teams, round=r.prev)
            if not r.is_break_round:
                table.add_debate_ranking_columns(draw, standings)
            else:
                self._add_break_rank_columns(table, draw, r.break_category)
            table.add_debate_metric_columns(draw, standings)
            table.add_side_counts([d.aff_team for d in draw], r.prev, 'aff')
            table.add_side_counts([d.neg_team for d in draw], r.prev, 'neg')
        else:
            table.add_debate_adjudicators_column(draw, show_splits=False)

        table.add_draw_conflicts_columns(draw)
        if not r.is_break_round:
            table.highlight_rows_by_column_value(column=0) # highlight first row of a new bracket

        return table

    def _add_break_rank_columns(self, table, draw, category):
        tournament = self.get_tournament()
        for side in ('aff', 'neg'):
            # Translators: e.g. possessive might be "affirmative's" to get "affirmative's break rank"
            tooltip = _("%(possessive)s break rank" % {'possessive': get_side_name(tournament, side, 'possessive')})
            # Translators: e.g. initial might be "A" for affirmative to get "ABR"
            tooltip = tooltip.capitalize()
            key = _("%(initial)sBR") % {'initial': get_side_name(tournament, side, 'initial')}
            table.add_column(
                {'tooltip': tooltip, 'key': key},
                [d.get_team(side).break_rank_for_category(category) for d in draw]
            )

    def get_template_names(self):
        round = self.get_round()
        if self.detailed:
            return ["draw_details.html"]
        if round.draw_status == round.STATUS_NONE:
            messages.warning(self.request, 'No draw exists yet — go to the ' +
                'check-ins section for this round to generate a draw.')
            return ["base.html"]
        elif round.draw_status == round.STATUS_DRAFT:
            return ["draw_status_draft.html"]
        elif round.draw_status == round.STATUS_CONFIRMED:
            return ["draw_status_confirmed.html"]
        elif round.draw_status == round.STATUS_RELEASED:
            return ["draw_status_confirmed.html"]
        else:
            raise ValueError(round.draw_status)


class AdminDrawWithDetailsView(AdminDrawView):
    detailed = True

    def get_page_title(self):
        rd = self.get_round()
        return 'Draw for %s with Details' % rd.name


# ==============================================================================
# Draw Status POSTS
# ==============================================================================

class DrawStatusEdit(LogActionMixin, SuperuserRequiredMixin, RoundMixin, PostOnlyRedirectView):
    round_redirect_pattern_name = 'draw'


class CreateDrawView(DrawStatusEdit):

    action_log_type = ActionLogEntry.ACTION_TYPE_DRAW_CREATE

    def post(self, request, *args, **kwargs):
        round = self.get_round()

        if round.draw_status != round.STATUS_NONE:
            messages.error(request, "Could not create draw for {}, there was already a draw!".format(round.name))
            return super().post(request, *args, **kwargs)

        manager = DrawManager(round)
        try:
            manager.create()
        except DrawError as e:
            messages.error(request, "There was a problem creating the draw: " + str(e) + " If this "
                " issue persists and you're not sure how to resolve it, please contact the developers.")
            logger.exception("Problem creating draw: " + str(e))
            return HttpResponseRedirect(reverse_round('availability-index', round))

        relevant_adj_venue_constraints = VenueConstraint.objects.filter(
                adjudicator__in=self.get_tournament().relevant_adjudicators)
        if not relevant_adj_venue_constraints.exists():
            allocate_venues(round)
        else:
            messages.warning(request, "Venues were not auto-allocated because there are one or more adjudicator venue constraints. "
                "You should run venue allocations after allocating adjudicators.")

        self.log_action()
        return super().post(request, *args, **kwargs)


class ConfirmDrawCreationView(DrawStatusEdit):
    action_log_type = ActionLogEntry.ACTION_TYPE_DRAW_CONFIRM

    def post(self, request, *args, **kwargs):
        round = self.get_round()
        if round.draw_status != round.STATUS_DRAFT:
            return HttpResponseBadRequest("Draw status is not DRAFT")

        round.draw_status = round.STATUS_CONFIRMED
        round.save()
        self.log_action()
        return super().post(request, *args, **kwargs)


class DrawRegenerateView(DrawStatusEdit):
    action_log_type = ActionLogEntry.ACTION_TYPE_DRAW_REGENERATE
    round_redirect_pattern_name = 'availability-index'

    def post(self, request, *args, **kwargs):
        round = self.get_round()
        delete_round_draw(round)
        self.log_action()
        messages.success(request, "Deleted the draw. You can now recreate it as normal.")
        return super().post(request, *args, **kwargs)


class ConfirmDrawRegenerationView(SuperuserRequiredMixin, TemplateView):
    template_name = "draw_confirm_regeneration.html"


class DrawReleaseView(DrawStatusEdit):
    action_log_type = ActionLogEntry.ACTION_TYPE_DRAW_RELEASE
    round_redirect_pattern_name = 'draw-display'

    def post(self, request, *args, **kwargs):
        round = self.get_round()
        if round.draw_status != round.STATUS_CONFIRMED:
            return HttpResponseBadRequest("Draw status is not CONFIRMED")

        round.draw_status = round.STATUS_RELEASED
        round.save()
        self.log_action()
        messages.success(request, "Released the draw. It will now show on the public-facing pages of this website.")
        return super().post(request, *args, **kwargs)


class DrawUnreleaseView(DrawStatusEdit):
    action_log_type = ActionLogEntry.ACTION_TYPE_DRAW_UNRELEASE
    round_redirect_pattern_name = 'draw-display'

    def post(self, request, *args, **kwargs):
        round = self.get_round()
        if round.draw_status != round.STATUS_RELEASED:
            return HttpResponseBadRequest("Draw status is not RELEASED")

        round.draw_status = round.STATUS_CONFIRMED
        round.save()
        self.log_action()
        messages.success(request, "Unreleased the draw. It will no longer show on the public-facing pages of this website.")
        return super().post(request, *args, **kwargs)


class SetRoundStartTimeView(DrawStatusEdit):
    action_log_type = ActionLogEntry.ACTION_TYPE_ROUND_START_TIME_SET
    round_redirect_pattern_name = 'draw-display'

    def post(self, request, *args, **kwargs):
        time_text = request.POST["start_time"]
        try:
            time = datetime.datetime.strptime(time_text, "%H:%M").time()
        except ValueError:
            messages.error(request, "Sorry, \"{}\" isn't a valid time. It must "
                           "be in 24-hour format, with a colon, for "
                           "example: \"13:57\".".format(time_text))
            return super().post(request, *args, **kwargs)

        round = self.get_round()
        round.starts_at = time
        round.save()

        self.log_action()

        return super().post(request, *args, **kwargs)


# ==============================================================================
# Adjudicator Scheduling
# ==============================================================================

class ScheduleDebatesView(SuperuserRequiredMixin, RoundMixin, TemplateView):
    template_name = "draw_set_debate_times.html"

    def get_context_data(self, **kwargs):
        round = self.get_round()
        tournament = self.get_tournament()
        vcs = VenueCategory.objects.all()
        for vc in vcs:
            for venue in vc.venues.all():
                debate = Debate.objects.filter(venue=venue, round__tournament=tournament, time__isnull=False).first()
                if debate:
                    vc.placeholder_date = debate.time
                    break

        kwargs['venue_categories'] = vcs
        kwargs['divisions'] = Division.objects.filter(tournament=round.tournament).order_by('id')
        return super().get_context_data(**kwargs)


class ScheduleConfirmationsView(SuperuserRequiredMixin, RoundMixin, TemplateView):
    template_name = "confirmations_view.html"

    def get_context_data(self, **kwargs):
        adjs = Adjudicator.objects.all().order_by('name')
        for adj in adjs:
            shifts = DebateAdjudicator.objects.filter(adjudicator=adj, debate__round__tournament__active=True)
            if len(shifts) > 0:
                adj.shifts = shifts
        kwargs['adjs'] = adjs
        return super().get_context_data(**kwargs)


class ApplyDebateScheduleView(DrawStatusEdit):

    def post(self, request, *args, **kwargs):
        round = self.get_round()
        debates = Debate.objects.filter(round=round)
        for debate in debates:
            division = debate.teams[0].division
            if not division:
                continue
            if not division.time_slot:
                continue

            date = request.POST[str(division.venue_category.id)]
            if not date:
                continue

            time = "%s %s" % (date, division.time_slot)
            try:
                debate.time = datetime.datetime.strptime(time,
                                "%Y-%m-%d %H:%M:%S")  # Safari default
            except ValueError:
                pass
            try:
                debate.time = datetime.datetime.strptime(time,
                                "%d/%m/%Y %H:%M:%S")  # Chrome default
            except ValueError:
                pass
            try:
                debate.time = datetime.datetime.strptime(time,
                                "%d/%m/%y %H:%M:%S")  # User typing
            except ValueError:
                pass

            debate.save()

        messages.success(self.request, "Applied schedules to debates")
        return super().post(request, *args, **kwargs)


# ==============================================================================
# Sides Editing and Viewing
# ==============================================================================

class BaseSideAllocationsView(TournamentMixin, VueTableTemplateView):

    page_title = "Side Pre-Allocations"

    def get_table(self):
        tournament = self.get_tournament()
        teams = tournament.team_set.all()
        rounds = tournament.prelim_rounds()

        tsas = dict()
        for tsa in TeamSideAllocation.objects.filter(round__in=rounds):
            try:
                tsas[(tsa.team.id, tsa.round.seq)] = get_side_name(tournament, tsa.side, 'abbr')
            except ValueError:
                pass

        table = TabbycatTableBuilder(view=self)
        table.add_team_columns(teams)

        headers = [round.abbreviation for round in rounds]
        data = [[tsas.get((team.id, round.seq), "—") for round in rounds] for team in teams]
        table.add_columns(headers, data)

        return table


class SideAllocationsView(SuperuserRequiredMixin, BaseSideAllocationsView):
    pass


class PublicSideAllocationsView(PublicTournamentPageMixin, BaseSideAllocationsView):
    public_page_preference = 'public_side_allocations'


class EditMatchupsView(DrawForDragAndDropMixin, SuperuserRequiredMixin, TemplateView):
    template_name = 'edit_matchups.html'
    save_url = "save-debate-teams"

    def annotate_draw(self, draw, serialised_draw):
        round = self.get_round()
        extra_debates = floor(round.active_teams.count() / 2 - len(serialised_draw))
        for i in range(0, extra_debates):
            # Make 'fake' debates as placeholders; need a unique ID (hence 9999)
            serialised_draw.append({
                'id': 999999 + i, 'teams': {}, 'panel': [], 'bracket': 0,
                'importance': 0, 'venue': None
            })

        return super().annotate_draw(draw, serialised_draw)

    def get_context_data(self, **kwargs):
        unused = [t for t in self.get_round().unused_teams()]
        serialized_unused = [t.serialize() for t in unused]
        for t, serialt in zip(unused, serialized_unused):
            serialt = self.annotate_break_classes(serialt)
            serialt = self.annotate_region_classes(serialt)

        kwargs['vueUnusedTeams'] = json.dumps(serialized_unused)
        return super().get_context_data(**kwargs)


class SaveDrawMatchups(SaveDragAndDropDebateMixin):
    action_log_type = ActionLogEntry.ACTION_TYPE_MATCHUP_SAVE
    allows_creation = True

    def identify_position(self, translated_position):
        # Positions are sent over in their labelled/translate form; need to lookup
        # This is hardcoded to aff/neg; will need to refactor when positions update
        translated_positions = {
            get_side_name(self.get_tournament(), name, 'full'): name for name in ['aff', 'neg']}
        position_short = translated_positions[translated_position]
        if position_short is 'aff':
            position = DebateTeam.POSITION_AFFIRMATIVE
        if position_short is 'neg':
            position = DebateTeam.POSITION_NEGATIVE
        return position

    def modify_debate(self, debate, posted_debate):
        teams = posted_debate['teams'].items()
        print("Processing change for ", debate.id)
        for d_position, d_team in teams:
            position = self.identify_position(d_position)
            team = Team.objects.get(pk=d_team['id'])
            print("\tSaving change for ", team.short_name)
            if DebateTeam.objects.filter(debate=debate, team=team, position=position).exists():
                print("\t\tSkipping %s as not changed" % team.short_name)
                continue # Skip the rest of the loop; no edit needed
            # Delete whatever team currently exists in that spot
            if DebateTeam.objects.filter(debate=debate, position=position).exists():
                existing = DebateTeam.objects.get(debate=debate, position=position)
                print('\t\tDeleting %s as %s' % (existing.team.short_name, existing.position))
                existing.delete()

            print("\t\tSaving %s as %s" % (team.short_name, position))
            new_allocation = DebateTeam.objects.create(debate=debate, team=team,
                                                       position=position)
            new_allocation.save()

        return debate


# ==============================================================================
# Cross-Tournament Draw Views
# ==============================================================================

class AllTournamentsAllInstitutionsView(CrossTournamentPageMixin, CacheMixin, TemplateView):
    public_page_preference = 'enable_mass_draws'
    template_name = 'public_all_tournament_institutions.html'

    def get_context_data(self, **kwargs):
        kwargs['institutions'] = Institution.objects.all()
        return super().get_context_data(**kwargs)


class AllTournamentsAllVenuesView(CrossTournamentPageMixin, CacheMixin, TemplateView):
    public_page_preference = 'enable_mass_draws'
    template_name = 'public_all_tournament_venues.html'

    def get_context_data(self, **kwargs):
        kwargs['venue_categories'] = VenueCategory.objects.all()
        return super().get_context_data(**kwargs)


class AllDrawsForAllTeamsView(CrossTournamentPageMixin, CacheMixin, BaseDrawTableView):
    public_page_preference = 'enable_mass_draws'

    def get_page_title(self):
        return 'All Draws for All Teams'

    def get_draw(self):
        draw = Debate.objects.all().select_related('round', 'round__tournament',
                                                   'division')
        return draw


class AllDrawsForInstitutionView(CrossTournamentPageMixin, CacheMixin, BaseDrawTableView):
    public_page_preference = 'enable_mass_draws'

    def get_institution(self):
        return Institution.objects.get(pk=self.kwargs['institution_id'])

    def get_page_title(self):
        return 'All Debates for Teams from %s' % self.get_institution().name

    def get_draw(self):
        institution = self.get_institution()
        debate_teams = DebateTeam.objects.filter(
            team__institution=institution).select_related(
            'debate', 'debate__division', 'debate__division__venue_category',
            'debate__round')
        draw = [dt.debate for dt in debate_teams]
        return draw


class AllDrawsForVenueView(CrossTournamentPageMixin, CacheMixin, BaseDrawTableView):
    public_page_preference = 'enable_mass_draws'

    def get_venue_category(self):
        try:
            return VenueCategory.objects.get(pk=self.kwargs['venue_id'])
        except VenueCategory.DoesNotExist:
            messages.warning(self.request, 'This venue category does not exist \
                or the URL for it might have changed. Try finding it again \
                from the homepage.')
            return False

    def get_page_title(self):
        if self.get_venue_category():
            return 'All Debates at %s' % self.get_venue_category().name
        else:
            return 'Unknown Venue Category'

    def get_draw(self):
        draw = Debate.objects.filter(
            division__venue_category=self.get_venue_category()).select_related(
            'round', 'round__tournament', 'division')
        return draw
