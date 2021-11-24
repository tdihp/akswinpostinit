import logging
import copy
from datetime import datetime

from kubernetes import client as kclient
from dateutil.tz import UTC

from .base import Action
from .common import FIELD_MANAGER
from ..utils import jsonpath_escape

logger = logging.getLogger(__name__)


class ConditionMarkerAction(Action):
    def __init__(self, condition_template):
        assert isinstance(condition_template, kclient.V1NodeCondition)
        self.condition_template = condition_template

    def is_done(self, node):
        condition_template = self.condition_template
        condition_same = any(
            (condition.type == condition_template.type and condition.status == condition_template.status) 
            for condition in node.status.conditions)
        # same_list = list((condition.type == condition_template.type and condition.status == condition_template.status) 
            # for condition in node.status.conditions)
        # logger.debug('condition_template: %r, node_conditions: %r, %r, condition_same: %r', condition_template, node.status.conditions, same_list, condition_same)
        return condition_same

    def execute(self, node, ctx):
        assert not self.is_done(node)
        now = datetime.now(UTC)
        new_condition = copy.copy(self.condition_template)
        new_condition.last_heartbeat_time = now
        new_condition.last_transition_time = now
        patch = {
            'status': {'conditions': [new_condition]}
        }
        rtn = ctx.v1.patch_node_status(node.metadata.name, patch, field_manager=FIELD_MANAGER)
        assert self.is_done(rtn)


class TainterAction(Action):
    """Tainter is a special action that takes both on and off condition template
    Action Generator should always consider tainter action, if it is ever needed.
    """
    def __init__(self, condition_type, taint_template, condition_off_status='True'):
        self.condition_type = condition_type
        self.taint_template = taint_template
        self.condition_off_status = condition_off_status

    def is_taint_on(self, node):
        return any(taint.key == self.taint_template.key for taint in (node.spec.taints or []))

    def is_condition_off(self, node):
        for condition in node.status.conditions:
            if condition.type == self.condition_type and condition.status == self.condition_off_status:
                return True

        return False

    def decision(self, node):
        """None for no action, True for on and False for off"""
        taint_on = self.is_taint_on(node)
        condition_off = self.is_condition_off(node)
        logger.debug('%r.decision: node: %r, taint_on: %r, condition_off: %r', self, node, taint_on, condition_off)
        turn_taint_off = taint_on and condition_off
        turn_taint_on = (not taint_on) and (not condition_off)
        if not (turn_taint_off or turn_taint_on):
            return None

        return turn_taint_on

    def is_done(self, node):
        if self.decision(node) is None:
            return True

        return False

    def execute(self, node, ctx):
        decision = self.decision(node)
        assert decision is not None
        taints = [taint for taint in (node.spec.taints or []) if taint.key != self.taint_template.key]
        if decision: # add taint
            taint = copy.copy(self.taint_template)
            now = datetime.now(UTC)
            taint.time_added = now
            taints.append(taint)

        patch = {'spec': {'taints': taints}}
        rtn = ctx.v1.patch_node(node.metadata.name, patch, field_manager=FIELD_MANAGER)
        assert self.is_done(rtn)
