from django.test import TestCase

from utils.tests import ConditionalTableViewTest
from participants.models import Adjudicator, Speaker


class PublicParticipantsViewTestCase(ConditionalTableViewTest, TestCase):

    view_toggle = 'public_features__public_participants'
    view_name = 'public_participants'

    def table_data_a(self):
        # Check number of adjs matches
        return Adjudicator.objects.filter(tournament=self.t).count()

    def table_data_b(self):
        # Check number of speakers matches
        return Speaker.objects.filter(team__tournament=self.t).count()
