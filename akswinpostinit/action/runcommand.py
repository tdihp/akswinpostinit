import logging 
from datetime import datetime

from dateutil.parser import parse

from .base import Action
from .common import RetryMixin

logger = logging.getLogger(__name__)


class RunCommandAction(RetryMixin, Action):
    def __init__(self, script, annotation_key, backoff):
        self.script = script
        self.annotation_key = annotation_key
        self.backoff = backoff

    def execute_inner(self, resource_detail, ctx):
        # XXX: currently doesn't validate if subscription is same as the client
        result_stdout, result_stderr = ctx.azure_client.run_powershell_script(
            resource_group=resource_detail['resource_group'], 
            vmss_name=resource_detail['name'], 
            instance_id=resource_detail['resource_name'], 
            script=self.script)

        logger.info('%r.execute_innter: script succeeded with stdout: %r, stderr: %r',
            self, result_stdout, result_stderr)
