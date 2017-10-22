from django.contrib import admin, messages
from django.db.models import Prefetch
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext

from draw.models import DebateTeam

from .models import AdjudicatorFeedback, AdjudicatorFeedbackQuestion


# ==============================================================================
# Adjudicator Feedback Questions
# ==============================================================================

@admin.register(AdjudicatorFeedbackQuestion)
class AdjudicatorFeedbackQuestionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'text', 'seq', 'tournament', 'answer_type',
                    'required', 'from_adj', 'from_team')
    list_filter  = ('tournament',)
    ordering     = ('tournament', 'seq')


# ==============================================================================
# Adjudicator Feedback Answers
# ==============================================================================

class BaseAdjudicatorFeedbackAnswerInline(admin.TabularInline):
    model = None  # Must be set by subclasses
    fields = ('question', 'answer')
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "question":
            kwargs["queryset"] = AdjudicatorFeedbackQuestion.objects.filter(
                answer_type__in=AdjudicatorFeedbackQuestion.ANSWER_TYPE_CLASSES_REVERSE[self.model])
        return super(BaseAdjudicatorFeedbackAnswerInline, self).formfield_for_foreignkey(db_field, request, **kwargs)


class RoundListFilter(admin.SimpleListFilter):
    """Filters AdjudicatorFeedbacks by round."""
    title = "round"
    parameter_name = "round"

    def lookups(self, request, model_admin):
        from tournaments.models import Round
        return [(str(r.id), "[{}] {}".format(r.tournament.short_name, r.name)) for r in Round.objects.all()]

    def queryset(self, request, queryset):
        return queryset.filter(source_team__debate__round_id=self.value()) | queryset.filter(source_adjudicator__debate__round_id=self.value())


# ==============================================================================
# Adjudicator Feedbacks
# ==============================================================================

@admin.register(AdjudicatorFeedback)
class AdjudicatorFeedbackAdmin(admin.ModelAdmin):
    list_display  = ('adjudicator', 'confirmed', 'score', 'version', 'get_source')
    search_fields = ('adjudicator__name', 'adjudicator__institution__code',
            'score', 'source_adjudicator__adjudicator__name',
            'source_team__team__short_name', 'source_team__team__long_name')
    raw_id_fields = ('source_team',)
    list_filter   = (RoundListFilter, 'adjudicator')
    actions       = ('mark_as_confirmed', 'mark_as_unconfirmed')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'source_team__debate__round__tournament',
            'source_team__team',
            'source_adjudicator__debate__round__tournament',
            'source_adjudicator__adjudicator__institution',
            'adjudicator__institution',
        ).prefetch_related(
            Prefetch('source_team__debate__debateteam_set', queryset=DebateTeam.objects.select_related('team')),
            Prefetch('source_adjudicator__debate__debateteam_set', queryset=DebateTeam.objects.select_related('team')),
        )

    def get_source(self, obj):
        if obj.source_team and obj.source_adjudicator:
            return "<ERROR: both source team and source adjudicator>"
        else:
            return obj.source_team or obj.source_adjudicator
    get_source.short_description = _("Source")

    # Dynamically generate inline tables for different answer types
    inlines = []
    for _answer_type_class in AdjudicatorFeedbackQuestion.ANSWER_TYPE_CLASSES_REVERSE:
        _inline_class = type(
            _answer_type_class.__name__ + "Inline", (BaseAdjudicatorFeedbackAnswerInline,),
            {"model": _answer_type_class, "__module__": __name__})
        inlines.append(_inline_class)

    def mark_as_confirmed(self, request, queryset):
        original_count = queryset.count()
        for fb in queryset.order_by('version').all():
            fb.confirmed = True
            fb.save()
        final_count = queryset.filter(confirmed=True).count()

        message = ungettext(
            "1 feedback submission was marked as confirmed. Note that this may "
            "have caused other feedback to be marked as unconfirmed.",
            "%(count)d feedback submissions were marked as confirmed. Note that "
            "this may have caused other feedback to be marked as unconfirmed.",
            final_count
        ) % {'count': final_count}
        self.message_user(request, message)

        difference = original_count - final_count
        if difference > 0:
            message = ungettext(
                "1 feedback submission was not marked as confirmed, probably "
                "because other feedback that conflicts with it was also marked "
                "as confirmed.",
                "%(count)d feedback submissions were not marked as confirmed, "
                "probably because other feedback that conflicts with it was "
                "also marked as confirmed.",
                difference
            ) % {'count': difference}
            self.message_user(request, message, level=messages.WARNING)

    def mark_as_unconfirmed(self, request, queryset):
        count = queryset.update(confirmed=False)
        message = ungettext(
            "1 feedback submission was marked as unconfirmed.",
            "%(count)d feedback submissions were marked as unconfirmed.",
            count
        ) % {'count': count}
        self.message_user(request, message)
