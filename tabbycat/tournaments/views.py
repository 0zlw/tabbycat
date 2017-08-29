import logging
from threading import Lock

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import management
from django.core.urlresolvers import reverse_lazy
from django.http import Http404
from django.shortcuts import redirect, resolve_url
from django.utils.http import is_safe_url
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.views.generic.base import RedirectView, TemplateView
from django.views.generic.edit import CreateView, FormView, UpdateView

from actionlog.mixins import LogActionMixin
from actionlog.models import ActionLogEntry
from draw.models import Debate
from importer.management.commands import importtournament
from importer.base import TournamentDataImporterError
from tournaments.models import Round
from utils.forms import SuperuserCreationForm
from utils.misc import redirect_round, redirect_tournament, reverse_tournament
from utils.mixins import CacheMixin, PostOnlyRedirectView, TabbycatPageTitlesMixin, SuperuserRequiredMixin

from .forms import SetCurrentRoundForm, TournamentConfigureForm, TournamentStartForm
from .mixins import RoundMixin, TournamentMixin
from .models import Tournament

User = get_user_model()
logger = logging.getLogger(__name__)


class PublicSiteIndexView(TemplateView):
    template_name = 'site_index.html'

    def get(self, request, *args, **kwargs):
        tournaments = Tournament.objects.all()
        if request.GET.get('redirect', '') == 'false':
            return super().get(request, *args, **kwargs)
        if tournaments.count() == 1 and not request.user.is_authenticated:
            logger.debug('One tournament only, user is: %s, redirecting to tournament-public-index', request.user)
            return redirect_tournament('tournament-public-index', tournaments.first())
        elif not tournaments.exists() and not User.objects.exists():
            logger.debug('No users and no tournaments, redirecting to blank-site-start')
            return redirect('blank-site-start')
        else:
            return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['tournaments'] = Tournament.objects.all()
        return super().get_context_data(**kwargs)


class TournamentPublicHomeView(CacheMixin, TournamentMixin, TemplateView):
    template_name = 'public_tournament_index.html'
    cache_timeout = 10 # Set slower to show new indexes so it will show new pages


class TournamentAdminHomeView(LoginRequiredMixin, TournamentMixin, TemplateView):
    template_name = "tournament_index.html"

    def get_context_data(self, **kwargs):
        tournament = self.get_tournament()
        kwargs["round"] = tournament.current_round
        kwargs["readthedocs_version"] = settings.READTHEDOCS_VERSION
        kwargs["blank"] = not (tournament.team_set.exists() or tournament.adjudicator_set.exists() or tournament.venue_set.exists())
        return super().get_context_data(**kwargs)


class RoundAdvanceConfirmView(SuperuserRequiredMixin, RoundMixin, TemplateView):
    template_name = 'round_advance_check.html'

    def get(self, request, *args, **kwargs):
        round = self.get_round()
        current_round = self.get_tournament().current_round
        if round != current_round:
            messages.error(self.request, "You are trying to advance from {this_round} but "
                "the current round is {current_round} — advance to {this_round} first!".format(
                    this_round=round.name, current_round=current_round.name))
            return redirect_round('results-round-list', self.get_tournament().current_round)
        else:
            return super().get(self, request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs['num_unconfirmed'] = self.get_round().debate_set.filter(
            result_status__in=[Debate.STATUS_NONE, Debate.STATUS_DRAFT]).count()
        kwargs['increment_ok'] = kwargs['num_unconfirmed'] == 0
        return super().get_context_data(**kwargs)


class RoundAdvanceView(RoundMixin, SuperuserRequiredMixin, LogActionMixin, PostOnlyRedirectView):

    action_log_type = ActionLogEntry.ACTION_TYPE_ROUND_ADVANCE
    round_redirect_pattern_name = 'results-round-list' # standard redirect is only on error

    def post(self, request, *args, **kwargs):
        tournament = self.get_tournament()

        # Advance relative to the round of the view, not the current round, so
        # that in times of confusion, going back then clicking again won't advance
        # twice.
        next_round = tournament.round_set.filter(seq__gt=self.get_round().seq).order_by('seq').first()

        if next_round:
            tournament.current_round = next_round
            tournament.save()
            self.log_action(round=next_round, content_object=next_round)

            if (next_round.stage == Round.STAGE_ELIMINATION and
                    self.get_round().stage == Round.STAGE_PRELIMINARY):
                messages.success(request, _("The current round has been advanced to %(round)s. "
                        "You've made it to the end of the preliminary rounds! Congratulations! "
                        "The next step is to generate the break.") % {'round': next_round.name})
                return redirect_tournament('breakqual-index', tournament)
            else:
                messages.success(request, _("The current round has been advanced to %(round)s. "
                    "Woohoo! Keep it up!") % {'round': next_round.name})
                return redirect_round('availability-index', next_round)

        else:
            messages.error(request, _("Whoops! Could not advance round, because there's no round "
                "after this round!"))
            return super().post(request, *args, **kwargs)


class BlankSiteStartView(FormView):
    """This view is presented to the user when there are no tournaments and no
    user accounts. It prompts the user to create a first superuser. It rejects
    all requests, GET or POST, if there exists any user account in the
    system."""

    form_class = SuperuserCreationForm
    template_name = "blank_site_start.html"
    lock = Lock()
    success_url = reverse_lazy('tabbycat-index')

    def get(self, request):
        if User.objects.exists():
            logger.warning("Tried to get the blank-site-start view when a user account already exists.")
            return redirect('tabbycat-index')

        return super().get(request)

    def post(self, request):
        with self.lock:
            if User.objects.exists():
                logger.warning("Tried to post the blank-site-start view when a user account already exists.")
                messages.error(request, "Whoops! It looks like someone's already created the first user account. Please log in.")
                return redirect('login')

            return super().post(request)

    def form_valid(self, form):
        form.save()
        user = authenticate(username=self.request.POST['username'], password=self.request.POST['password1'])
        login(self.request, user)
        messages.info(self.request, "Welcome! You've created an account for %s." % user.username)

        return super().form_valid(form)


class CreateTournamentView(SuperuserRequiredMixin, CreateView):
    """This view allows a logged-in superuser to create a new tournament."""

    model = Tournament
    form_class = TournamentStartForm
    template_name = "create_tournament.html"

    def get_context_data(self, **kwargs):
        kwargs["preexisting_small_demo"] = Tournament.objects.filter(slug="demo_simple").exists()
        kwargs["preexisting_large_demo"] = Tournament.objects.filter(slug="demo").exists()
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        t = Tournament.objects.last()
        return reverse_tournament('tournament-configure', tournament=t)


class LoadDemoView(SuperuserRequiredMixin, PostOnlyRedirectView):

    def post(self, request, *args, **kwargs):
        source = request.POST.get("source", "")

        try:
            management.call_command(importtournament.Command(), source,
                                    force=True, strict=False)
        except TournamentDataImporterError as e:
            messages.error(self.request, mark_safe("<p>There were one or more errors creating the demo tournament. "
                "Before retrying, please delete the existing demo tournament <strong>and</strong> "
                "the institutions in the Edit Database Area.</p><p><i>Technical information: The errors are as follows:"
                "<ul>" + "".join("<li>{}</li>".format(message) for message in e.itermessages()) + "</ul></i></p>"))
            logger.error("Error importing demo tournament: " + str(e))
        else:
            messages.success(self.request, "Created new demo tournament. You "
                "can now configure it below.")

        new_tournament = Tournament.objects.last()
        return redirect(reverse_tournament('tournament-configure', tournament=new_tournament))


class ConfigureTournamentView(SuperuserRequiredMixin, UpdateView, TournamentMixin):
    model = Tournament
    form_class = TournamentConfigureForm
    template_name = "configure_tournament.html"
    slug_url_kwarg = 'tournament_slug'

    def get_success_url(self):
        t = self.get_tournament()
        return reverse_tournament('tournament-admin-home', tournament=t)


class SetCurrentRoundView(SuperuserRequiredMixin, UpdateView):
    model = Tournament
    form_class = SetCurrentRoundForm
    template_name = 'set_current_round.html'
    slug_url_kwarg = 'tournament_slug'
    redirect_field_name = 'next'

    def get_redirect_to(self, use_default=True):
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name, '')
        )
        if not redirect_to and use_default:
            return reverse_tournament('tournament-admin-home', tournament=self.object)
        else:
            return redirect_to

    def get_success_url(self):
        # Copied from django.contrib.auth.views.LoginView.get_success_url
        redirect_to = self.get_redirect_to(use_default=True)
        url_is_safe = is_safe_url(
            url=redirect_to,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        )
        if not url_is_safe:
            return resolve_url(settings.LOGIN_REDIRECT_URL)
        return redirect_to

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            self.redirect_field_name: self.get_redirect_to(use_default=False),
        })
        return context


class TournamentPermanentRedirectView(RedirectView):
    """Redirect old-style /t/<slug>/... URLs to new-style /<slug>/... URLs."""

    url = "/%(slug)s/%(page)s"
    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        slug = kwargs['slug']
        if not Tournament.objects.filter(slug=slug).exists():
            logger.warning("Tried to redirect non-existent tournament slug '%s'" % slug)
            raise Http404("There isn't a tournament with slug '%s'." % slug)
        return super().get_redirect_url(*args, **kwargs)


class DonationsView(CacheMixin, TemplateView):
    template_name = 'donations.html'


class TournamentDonationsView(TournamentMixin, TemplateView):
    template_name = 'donations.html'


class StyleGuideView(TemplateView, TabbycatPageTitlesMixin):
    template_name = 'style_guide.html'
    page_subtitle = 'Contextual sub title'
