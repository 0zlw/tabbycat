from utils.consumers import TournamentConsumer, WSLoginRequiredMixin


class DebateConsumer(TournamentConsumer, WSLoginRequiredMixin):
    pass
