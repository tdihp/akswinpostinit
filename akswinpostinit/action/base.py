import logging
import math

logger = logging.getLogger('akswinpostinit.action')


def backoff_until(min_v, max_v, steps, attempt):
    assert min_v < max_v
    assert 0 < steps < 1000  # Really doesn't seem appropriate to have that many steps
    diff = math.log(max_v) - math.log(min_v)
    stepv = diff / steps
    return min_v * math.exp(attempt * stepv)


class Backoff(object):
    def is_in_backoff(self, attempt, delta_time_in_seconds):
        raise NotImplementedError


class ExpBackoff(Backoff):
    """Exponential backoff implementation that uses actual exp math"""
    def __init__(self, min_v, max_v, steps):
        assert min_v < max_v
        assert 0 < steps < 1000  # Really doesn't seem appropriate to have that many steps
        self.min_v = min_v
        self.max_v = max_v
        self.steps = steps

    def is_in_backoff(self, attempt, delta_time_in_seconds):
        _backoff_until = backoff_until(self.min_v, self.max_v, self.steps, attempt)
        return delta_time_in_seconds <_backoff_until


class Action(object):
    backoff = None

    def get_backoff(self):
        return self.backoff

    def is_in_backoff(self, obj):
        backoff = self.get_backoff()
        if not backoff:
            return False

        attempt = self.get_attempt(obj)
        assert attempt >= 0
        delta_time_in_seconds = self.get_delta_time_in_seconds(obj)
        if delta_time_in_seconds is None:
            return False

        return backoff.is_in_backoff(attempt, delta_time_in_seconds)

    def is_done(self, obj):
        raise NotImplementedError

    def is_give_up(self, obj):
        """if respond true, the action chain should not proceed further"""
        return self.is_in_backoff(obj)

    def get_attempt(self, obj):
        raise NotImplementedError

    def get_delta_time_in_seconds(self, obj):
        raise NotImplementedError

    def get_backoff_in_seconds(self, obj):
        raise NotImplementedError

    def execute(self, obj, ctx):
        raise NotImplementedError


class ActionGenerator(object):
    """ Abstract interface for generating actions based on obj observation 
    """
    def get_action(self, obj):
        """return Action object"""
        raise NotImplementedError


class ActionChain(ActionGenerator):
    """action chain that suggests actions to move an object through a list of actions to the final one"""
    def get_action(self, obj):
        """walks through all actions in reverse order, the first done action marks its next action as current"""
        current_action = None
        for action in reversed(self.actions):
            logger.debug('ActionChain: inspecting action %r', action)
            if action.is_done(obj):
                break

            current_action = action

        if not current_action:
            logger.info('%r.get_action: full action chain completed', self)
            return None

        logger.info('%r.get_action: current action: %r', self, current_action)
        if current_action.is_give_up(obj):
            logger.info('%r.get_action: action %r currently cannot proceed', self, current_action)
            return None

        logger.info('%r.get_action: proceed with action %r', self, current_action)
        return current_action


class WrappedGeneratorMixin(object):
    """always prioritize the wrapping action, proceed generator only if this action is done"""

    def get_action(self, obj):
        for action in self.wrapping_actions:
            logger.debug('inspecting wrapping action %r', action)
            if action.is_done(obj):
                logger.debug('%r.get_action: warpping action %r done', self, action)
                continue

            if action.is_give_up(obj):
                logger.debug('%r.get_action: wrappping action %r is giving up', self, action)
                return None

            logger.info('%r.get_action: got wrapper action %r', self, action)
            return action
        return super().get_action(obj)
