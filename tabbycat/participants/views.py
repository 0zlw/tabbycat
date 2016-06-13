import json

from django.conf import settings
from django.contrib import messages
from django.forms.models import modelformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_page

from adjallocation.models import DebateAdjudicator
from tournaments.mixins import PublicTournamentPageMixin
from utils.views import public_optional_tournament_view, tournament_view
from utils.mixins import HeadlessTemplateView, PublicCacheMixin, VueTableMixin

from .models import Adjudicator, Institution, Speaker, Team


@cache_page(settings.TAB_PAGES_CACHE_TIMEOUT)
@tournament_view
def team_speakers(request, t, team_id):
    team = Team.objects.get(pk=team_id)
    speakers = team.speakers
    data = {}
    for i, speaker in enumerate(speakers):
        data[i] = "<li>" + speaker.name + "</li>"

    return JsonResponse(data, safe=False)


class PublicParticipants(PublicTournamentPageMixin, VueTableMixin, PublicCacheMixin, HeadlessTemplateView):

    public_page_preference = 'public_participants'
    template_name = 'base_double_vue_table.html'
    page_title = 'Participants'
    page_emoji = '🚌'
    sort_key = 'Name'

    def get_context_data(self, **kwargs):
        t = self.get_tournament()

        adjs_data = []
        adjudicators = Adjudicator.objects.filter(tournament=t).select_related('institution')
        for adjudicator in adjudicators:
            ddict = self.adj_cells(adjudicator, t)
            adjs_data.append(ddict)

        kwargs["table_a_title"] = "Adjudicators"
        kwargs["tableDataA"] = json.dumps(adjs_data)

        speakers_data = []
        speakers = Speaker.objects.filter(team__tournament=t).select_related('team', 'team__institution')
        for speaker in speakers:
            ddict = self.speaker_cells(speaker, t)
            ddict.extend(self.team_cells(speaker.team, t))
            speakers_data.append(ddict)

        kwargs["table_b_title"] = "Speakers"
        kwargs["tableDataB"] = json.dumps(speakers_data)

        return super().get_context_data(**kwargs)


@cache_page(settings.PUBLIC_PAGE_CACHE_TIMEOUT)
@tournament_view
def all_tournaments_all_institutions(request, t):
    institutions = Institution.objects.all()
    return render(request, 'public_all_tournament_institutions.html', dict(
        institutions=institutions))


@cache_page(settings.PUBLIC_PAGE_CACHE_TIMEOUT)
@tournament_view
def all_tournaments_all_teams(request, t):
    teams = Team.objects.filter(tournament__active=True).select_related('tournament').prefetch_related('division')
    return render(request, 'public_all_tournament_teams.html', dict(
        teams=teams))


# Scheduling

@public_optional_tournament_view('allocation_confirmations')
def public_confirm_shift_key(request, t, url_key):
    adj = get_object_or_404(Adjudicator, url_key=url_key)
    adj_debates = DebateAdjudicator.objects.filter(adjudicator=adj)

    shifts_formset = modelformset_factory(DebateAdjudicator, can_delete=False,
                                          extra=0, fields=['timing_confirmed'])

    if request.method == 'POST':
        formset = shifts_formset(request.POST, request.FILES)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Your shift check-ins have been saved")
    else:
        formset = shifts_formset(queryset=adj_debates)

    return render(request, 'confirm_shifts.html', dict(formset=formset, adjudicator=adj))
