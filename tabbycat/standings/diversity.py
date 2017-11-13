from django.db.models import Avg, Q

from adjallocation.models import DebateAdjudicator
from adjfeedback.models import AdjudicatorFeedback
from participants.models import Adjudicator, Person, Speaker, SpeakerCategory, Team
from participants.utils import regions_ordered
from results.models import SpeakerScore
from tournaments.models import Round


def compile_data(title, queryset, filter_source, filters, datum=False, **kwargs):
    """ Filter the queryset given filters and return a dictionary of results """

    data_set = []
    for item in filters:
        [(key, value)] = item.items()  # Get the key/value pairs

        # Use keywords to filter data sets; using Q for OR conditions
        if isinstance(value, list):
            filtered = queryset.filter(Q(**{filter_source: value[0]}) | Q(**{filter_source: value[1]}))
        else:
            filtered = queryset.filter(**{filter_source: value})

        # Return a structure ready to fit the Vue template
        data_set.append({
            'label': key,
            'count': calculate_result(filtered, kwargs),
        })

    if datum is not False:  # Get the overall number to use as baseline
        datum = calculate_result(queryset, kwargs)

    return {'title': title, 'data': data_set, 'datum': datum}


def calculate_result(queryset, keywords):
    if 'count' in keywords:
        return queryset.count()
    elif 'average' in keywords:
        return queryset.aggregate(Avg('score'))['score__avg']
    elif 'median' in keywords or 'lowerq' in keywords or 'upperq' in keywords:
        ordered_values = sorted(queryset.values_list('score', flat=True))
        if 'median' in keywords:
            return median_value(ordered_values)
        elif 'lowerq' in keywords:
            return quartile(ordered_values, lower=True)
        elif 'upperq' in keywords:
            return quartile(ordered_values, upper=True)


def median_value(ordered_values):
    if len(ordered_values) is 0:
        return None

    mid = len(ordered_values) / 2

    if (len(ordered_values) % 2 == 0):
        return (ordered_values[int(mid)-1] + ordered_values[int(mid)]) / 2.0
    else:
        return ordered_values[int(mid)]


def quartile(ordered_values, lower=False, upper=False):
    mid = len(ordered_values) / 2

    if (len(ordered_values) % 2 == 0):
        if upper:
            return median_value(ordered_values[int(mid):])
        elif lower:
            return median_value(ordered_values[:int(mid)])
    else:
        if upper:
            return median_value(ordered_values[int(mid)+1:])
        elif lower:
            return median_value(ordered_values[:int(mid)])


def get_diversity_data_sets(t, for_public):

    all_regions = regions_ordered(t)
    region_filters = [{r['seq']:r['name']} for r in all_regions]

    data_sets = {
        'speakers_gender': [],
        'speakers_region': [],
        'speakers_results': [],
        'speakers_categories': [],
        'detailed_speakers_results': [],
        'adjudicators_gender': [],
        'adjudicators_position': [],
        'adjudicators_region': [],
        'adjudicators_results': [],
        'detailed_adjudicators_results': [],
        'regions': all_regions  # For CSS
    }

    # ==========================================================================
    # Speakers Demographics
    # ==========================================================================

    gender_filters = [
        {'NM':       [Person.GENDER_FEMALE, Person.GENDER_OTHER]},
        {'Male':     Person.GENDER_MALE},
        {'Unknown':  None},
    ]
    subset_filters = [ # Remove unknown for small data sets
        {'NM':       [Person.GENDER_FEMALE, Person.GENDER_OTHER]},
        {'Male':     Person.GENDER_MALE},
    ]

    if Speaker.objects.filter(team__tournament=t).count() > 0:
        data_sets['speakers_gender'].append(compile_data(
            'All', Speaker.objects.filter(team__tournament=t),
            'gender', filters=gender_filters, count=True))

    if t.pref('public_breaking_teams') is True or for_public is False:
        if Speaker.objects.filter(team__tournament=t).filter(team__breakingteam__isnull=False).count() > 0:
            data_sets['speakers_gender'].append(compile_data(
                'Breaking', Speaker.objects.filter(team__tournament=t, team__breakingteam__isnull=False),
                'gender', filters=gender_filters, count=True))

    for sc in SpeakerCategory.objects.filter(tournament=t).order_by('seq'):
        if Speaker.objects.filter(categories=sc).count() > 0:
            data_sets['speakers_categories'].append(compile_data(
                sc.name, Speaker.objects.filter(team__tournament=t, categories=sc),
                'gender', filters=gender_filters, count=True))
            data_sets['speakers_categories'].append(compile_data(
                'Not ' + sc.name, Speaker.objects.filter(team__tournament=t).exclude(categories=sc),
                'gender', filters=gender_filters, count=True))

    if Team.objects.exclude(institution__region__isnull=True).count() > 0:
        data_sets['speakers_region'].append(compile_data(
            'All', Speaker.objects.filter(
                team__tournament=t), 'team__institution__region__name', filters=region_filters, count=True))
        if t.pref('public_breaking_teams') is True or for_public is False:
            data_sets['speakers_region'].append(compile_data(
                'Breaking', Speaker.objects.filter(team__tournament=t, team__breakingteam__isnull=False), 'team__institution__region__name',
                filters=region_filters, count=True))

    # ==========================================================================
    # Adjudicators Demographics
    # ==========================================================================

    if Adjudicator.objects.filter(tournament=t).count() > 0:
        data_sets['adjudicators_gender'].append(compile_data(
            'All', Adjudicator.objects.filter(tournament=t),
            'gender', filters=gender_filters, count=True))

    if Adjudicator.objects.filter(tournament=t).filter(independent=True).count() > 0:
        data_sets['adjudicators_gender'].append(compile_data(
            'Indies', Adjudicator.objects.filter(tournament=t, independent=True), 'gender',
            filters=gender_filters, count=True))

    if t.pref('public_breaking_adjs') is True or for_public is False:
        if Adjudicator.objects.filter(breaking=True).count() > 0:
            data_sets['adjudicators_gender'].append(compile_data(
                'Breaking', Adjudicator.objects.filter(tournament=t, breaking=True), 'gender',
                filters=gender_filters, count=True))

    if DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_CHAIR).count() > 0:
        data_sets['adjudicators_position'].append(compile_data(
            'Chairs', DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_CHAIR), 'adjudicator__gender',
            filters=gender_filters, count=True))

    if DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_PANEL).count() > 0:
        data_sets['adjudicators_position'].append(compile_data(
            'Panellists', DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_PANEL), 'adjudicator__gender',
            filters=gender_filters, count=True))

    if DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_TRAINEE).count() > 0:
        data_sets['adjudicators_position'].append(compile_data(
            'Trainees', DebateAdjudicator.objects.filter(adjudicator__tournament=t, type=DebateAdjudicator.TYPE_TRAINEE), 'adjudicator__gender',
            filters=gender_filters, count=True))

    if DebateAdjudicator.objects.exclude(adjudicator__institution__region__isnull=True).count() > 0:
        data_sets['adjudicators_region'].append(compile_data(
            'All', Adjudicator.objects.filter(tournament=t), 'institution__region__name',
            filters=region_filters, count=True))
        if t.pref('public_breaking_adjs') is True or for_public is False:
            data_sets['adjudicators_region'].append(compile_data(
                'Breaking', Adjudicator.objects.filter(tournament=t, breaking=True), 'institution__region__name',
                filters=region_filters, count=True))

    # ==========================================================================
    # Adjudicators Results
    # ==========================================================================

    # Don't show data if genders have not been set
    data_sets['gendered_adjudicators'] = Adjudicator.objects.filter(gender="M").count() + Adjudicator.objects.filter(gender="F").count()
    if data_sets['gendered_adjudicators'] > 0:

        data_sets['feedbacks_count'] = AdjudicatorFeedback.objects.filter(adjudicator__tournament=t).count()

        if data_sets['feedbacks_count'] > 0:
            data_sets['adjudicators_results'].append(compile_data(
                'Average Rating', AdjudicatorFeedback.objects.filter(adjudicator__tournament=t), 'adjudicator__gender',
                filters=subset_filters, average=True, datum=True))

            data_sets['adjudicators_results'].append(compile_data(
                'Median Rating', AdjudicatorFeedback.objects.filter(adjudicator__tournament=t), 'adjudicator__gender',
                filters=subset_filters, median=True, datum=True))

            data_sets['adjudicators_results'].append(compile_data(
                'Upper Quartile Rating', AdjudicatorFeedback.objects.filter(adjudicator__tournament=t), 'adjudicator__gender',
                filters=subset_filters, upperq=True, datum=True))

            data_sets['adjudicators_results'].append(compile_data(
                'Lower Quartile Rating', AdjudicatorFeedback.objects.filter(adjudicator__tournament=t), 'adjudicator__gender',
                filters=subset_filters, lowerq=True, datum=True))

            if AdjudicatorFeedback.objects.filter(adjudicator__tournament=t, source_adjudicator__isnull=False).count() > 0:
                data_sets['detailed_adjudicators_results'].append(compile_data(
                    'Average Rating Given by Teams', AdjudicatorFeedback.objects.filter(adjudicator__tournament=t, source_adjudicator__isnull=False),
                    'source_adjudicator__adjudicator__gender', filters=subset_filters, average=True, datum=True))

            if AdjudicatorFeedback.objects.filter(adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_CHAIR).count() > 0:
                data_sets['detailed_adjudicators_results'].append(compile_data(
                    'Average Rating Given by Chairs', AdjudicatorFeedback.objects.filter(
                        adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_CHAIR, source_adjudicator__isnull=False),
                    'source_adjudicator__adjudicator__gender', filters=subset_filters, average=True, datum=True))

            if AdjudicatorFeedback.objects.filter(adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_PANEL).count() > 0:
                data_sets['detailed_adjudicators_results'].append(compile_data(
                    'Average Rating Given by Panellists', AdjudicatorFeedback.objects.filter(
                        adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_PANEL, source_adjudicator__isnull=False),
                    'source_adjudicator__adjudicator__gender', filters=subset_filters, average=True, datum=True))

            if AdjudicatorFeedback.objects.filter(adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_TRAINEE).count() > 0:
                data_sets['detailed_adjudicators_results'].append(compile_data(
                    'Average Rating Given by Trainees', AdjudicatorFeedback.objects.filter(
                        adjudicator__tournament=t, source_adjudicator__type=DebateAdjudicator.TYPE_TRAINEE, source_adjudicator__isnull=False),
                    'source_adjudicator__adjudicator__gender', filters=subset_filters, average=True, datum=True))

    # ==========================================================================
    # Speakers Results
    # ==========================================================================

    # Don't show data if genders have not been set
    data_sets['gendered_speakers'] = Speaker.objects.filter(gender="M").count() + Speaker.objects.filter(gender="F").count()
    if data_sets['gendered_speakers'] > 0:

        data_sets['speaks_count'] = SpeakerScore.objects.filter(speaker__team__tournament=t).count()
        if data_sets['speaks_count'] > 0:
            data_sets['speakers_results'].append(compile_data(
                'Average Score', SpeakerScore.objects.filter(speaker__team__tournament=t).exclude(position=t.reply_position), 'speaker__gender',
                filters=subset_filters, average=True, datum=True))

            data_sets['speakers_results'].append(compile_data(
                'Median Score', SpeakerScore.objects.filter(speaker__team__tournament=t).exclude(position=t.reply_position), 'speaker__gender',
                filters=subset_filters, median=True, datum=True))

            data_sets['speakers_results'].append(compile_data(
                'Upper Quartile Score', SpeakerScore.objects.filter(speaker__team__tournament=t).exclude(position=t.reply_position), 'speaker__gender',
                filters=subset_filters, upperq=True, datum=True))

            data_sets['speakers_results'].append(compile_data(
                'Lower Quartile Score', SpeakerScore.objects.filter(speaker__team__tournament=t).exclude(position=t.reply_position), 'speaker__gender',
                filters=subset_filters, lowerq=True, datum=True))
            for i in range(1, t.pref('substantive_speakers') + 1):

                data_sets['detailed_speakers_results'].append(compile_data(
                    'Speaker ' + str(i) + ' Average', SpeakerScore.objects.filter(speaker__team__tournament=t, position=str(i)), 'speaker__gender',
                    filters=subset_filters, average=True, datum=True))

            if t.pref('reply_scores_enabled'):
                data_sets['detailed_speakers_results'].append(compile_data(
                    'Reply Speaker Average', SpeakerScore.objects.filter(speaker__team__tournament=t, position=t.reply_position), 'speaker__gender',
                    filters=subset_filters, average=True, datum=True))

            if SpeakerScore.objects.filter(speaker__team__tournament=t, debate_team__debate__round__stage=Round.STAGE_ELIMINATION).count() > 0:
                data_sets['detailed_speakers_results'].append(compile_data(
                    'Average Finals Score', SpeakerScore.objects.filter(debate_team__debate__round__stage=Round.STAGE_ELIMINATION).exclude(position=t.reply_position), 'speaker__gender',
                    filters=subset_filters, average=True, datum=True))

    return data_sets
