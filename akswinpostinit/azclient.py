from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.core.tools import parse_resource_id, is_valid_resource_id


def is_resource_detail_vmss(resource_detail):
    """resource_detail is supplied by parse_resource_id"""
    return resource_detail.get('type') == 'virtualMachineScaleSets' \
        and resource_detail.get('resource_type') == 'virtualMachines'


class AzureClient(object):
    def __init__(self, subscription_id, credential=None):
        credential = credential or DefaultAzureCredential()
        self.compute_client = ComputeManagementClient(subscription_id=subscription_id, credential=credential)
        pass

    def reboot(self, resource_group, vmss_name, instance_id):
        poller = self.compute_client.virtual_machine_scale_set_vms.begin_restart(
            resource_group, vmss_name, instance_id)
        return poller.result()

    def run_powershell_script(self, resource_group, vmss_name, instance_id, script):
        """
        Runs powershell script, returns stdout and stderr
        """
        assert isinstance(script, str)
        command_spec = {
            'command_id': 'RunPowerShellScript',
            'script': [script],
        }
        poller = self.compute_client.virtual_machine_scale_set_vms.begin_run_command(
            resource_group, vmss_name, instance_id, command_spec)
        result = poller.result()
        stdout_status, stderr_status = result.value
        assert stdout_status.code == 'ComponentStatus/StdOut/succeeded'
        assert stderr_status.code == 'ComponentStatus/StdErr/succeeded'
        return stdout_status.message, stderr_status.message
