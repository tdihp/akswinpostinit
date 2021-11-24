"""
Provides the context structure that's used in the Azure actions.
"""

from collections import namedtuple
from datetime import datetime
import logging
import json

from dateutil.parser import parse
from dateutil.tz import UTC
from azure.mgmt.core.tools import parse_resource_id, is_valid_resource_id
from kubernetes import client as kclient

logger = logging.getLogger(__name__)

FIELD_MANAGER = 'akswinpostinit'

AzureContext = namedtuple('AzureContext', ['v1', 'azure_client'])


def is_resource_detail_vmss(resource_detail):
    """resource_detail is supplied by parse_resource_id"""
    return resource_detail.get('type') == 'virtualMachineScaleSets' \
        and resource_detail.get('resource_type') == 'virtualMachines'


class VMSSNodeProxy(object):
    """A proxy V1Node that makes shorter repr for display sake.
    
    Note that currently it assumes the node object to be read only"""

    def __init__(self, node):
        assert isinstance(node, kclient.V1Node), 'assuming input to be V1node, got %r' % node
        self._node = node

    def __getattr__(self, name):
        return getattr(self._node, name)

    def __repr__(self):
        return 'VMSSNodeProxy(%s)' % self.metadata.name

    def get_resource_detail(self):
        """only returns if it is a valid vmss detail, otherwise returns None to skip"""
        provider_id = self.spec.provider_id
        azure_resource_id = provider_id[len('azure://'):]
        if provider_id.startswith('azure://') and is_valid_resource_id(azure_resource_id):
            detail = parse_resource_id(azure_resource_id)
            if is_resource_detail_vmss(detail):
                return detail

        logger.warning('%r.get_resource_detail: node has a unrecognized provider id %s', self, provider_id)
        return None


class DatetimeJsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()

        return super().default(o)


class ActionStatus(namedtuple('ActionStatus', ['start_time', 'success_time', 'attempt'])):
    __slots__ = ()

    def to_json(self):
        return json.dumps(self._asdict(), separators=(',', ':'), cls=DatetimeJsonEncoder)

    @staticmethod
    def from_json(s):
        data = json.loads(s)
        start_time = data.get('start_time', None) or None
        if start_time:
            start_time = parse(start_time)

        success_time = data.get('success_time', None) or None
        if success_time:
            success_time = parse(success_time)

        attempt = data.get('attempt', 0)
        return ActionStatus(start_time, success_time, attempt)


DEFAULT_ACTION_STATUS = ActionStatus(None, None, 0)


class RetryMixin(object):
    """ Common logic for a "retry" backoff """

    def _parse_status(self, node):
        status_str = node.metadata.annotations.get(self.annotation_key, '')
        if not status_str:
            return DEFAULT_ACTION_STATUS

        result = ActionStatus.from_json(status_str)
        creation_timestamp = node.metadata.creation_timestamp
        if result.start_time and result.start_time < creation_timestamp:
            logger.debug('invalid start_time for %r', ActionStatus)
            return DEFAULT_ACTION_STATUS

        if result.success_time and result.success_time < creation_timestamp:
            logger.debug('invalid success_time for %r', ActionStatus)
            return DEFAULT_ACTION_STATUS

        return result

    def get_delta_time_in_seconds(self, node):
        status = self._parse_status(node)
        now = datetime.now(UTC)
        if status.start_time is None:
            return None

        return (now - status.start_time).total_seconds()

    def is_done(self, node):
        if not node.get_resource_detail():
            logger.info('%r.is_done: skipping non-Azure VMSS node %r', self, node)
            return True

        status = self._parse_status(node)
        return bool(status.success_time)

    def get_attempt(self, node):
        status = self._parse_status(node)
        return status.attempt

    def execute_inner(self, resource_detail, ctx):
        raise NotImplementedError

    def execute(self, node, ctx):
        node_name = node.metadata.name
        now = datetime.now(UTC)
        status = self._parse_status(node)
        # increment attempt
        status = status._replace(attempt=status.attempt + 1, start_time=now)
        ctx.v1.patch_node(node_name, {
            'metadata': {
                'annotations': {
                    self.annotation_key: status.to_json() 
                }
            }
        })
        resource_detail = node.get_resource_detail()
        if not resource_detail:
            raise ValueError('Invalid Azure resource detail for node %r: %r' % (node, resource_detail))
        self.execute_inner(resource_detail, ctx)
        now = datetime.now(UTC)
        status = status._replace(success_time=now)
        # XXX: currently we rely on periodic scan, no need to report any failure.
        ctx.v1.patch_node(node_name, {
            'metadata': {
                'annotations': {
                    self.annotation_key: status.to_json(),
                }
            }
        })




