import logging

from dateutil.parser import parse

from .base import Action
from .common import RetryMixin

logger = logging.getLogger(__name__)


class RebootNodeAction(RetryMixin, Action):
    def __init__(self, annotation_key, backoff):
        """ conditionTemplate is a V1NodeCondition object with type, status, reason and message properly set """
        self.annotation_key = annotation_key
        self.backoff = backoff

    def execute_inner(self, resource_detail, ctx):
        # XXX: currently doesn't validate if subscription is same as the client
        result = ctx.azure_client.reboot(
            resource_group=resource_detail['resource_group'], 
            vmss_name=resource_detail['name'], 
            instance_id=resource_detail['resource_name'])

        logger.info('%r.execute_innter: reboot succeeded', self)

