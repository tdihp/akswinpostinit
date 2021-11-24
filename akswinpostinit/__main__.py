# from threading import Thread
import logging
import copy
from datetime import datetime
from concurrent import futures
import threading
import time
import argparse

from kubernetes import client as kclient, config, watch
import urllib3

from .action import (
    ActionGenerator,
    ActionChain,
    VMSSNodeProxy,
    AzureContext,
    # MarkerAction,
    TainterAction,
    WrappedGeneratorMixin,
    ConditionMarkerAction,
    ReadyAction,
    RebootNodeAction,
    RunCommandAction,
    ExpBackoff,
)
from .azclient import AzureClient
from .utils import jsonpath_escape


logger = logging.getLogger('akswinpostinit.main')


class FuturesFollower(threading.Thread):
    def __init__(self):
        super().__init__(name='FuturesFollower', daemon=True)
        self.lock = threading.Lock()
        self.futures = set()

    def add_followup(self, f):
        with self.lock:
            self.futures.add(f)

    def run(self):
        while True:
            if not self.futures:
                time.sleep(1)
                continue

            with self.lock:
                done, self.futures = futures.wait(self.futures,
                    timeout=0, return_when=futures.FIRST_COMPLETED)

            for f in done:
                assert not f.running()
                try:
                    f.result()
                except Exception:
                    logger.exception('async run got exception')

            time.sleep(1)


class WinPostInitActionGenerator(WrappedGeneratorMixin, ActionChain):
    def __init__(self, script,
            need_reboot=True,
            annotation_prefix='github.com.tdihp.akswinpostinit/',
            runcommand_suffix='runcommand',
            reboot_suffix='reboot',
            condition_type='AKSWinPostInit',
            taint_key='AKSWinPostInit',
            taint_effect='NoSchedule',
            ):
        taint_template = kclient.V1Taint(
            key=taint_key,
            effect=taint_effect,
        )
        self.wrapping_actions = [TainterAction(condition_type=condition_type, taint_template=taint_template), ReadyAction()]
        actions = []
        init_condition_template = kclient.V1NodeCondition(
            type=condition_type,
            message="akswinpostinit is initializing the node",
            reason="AKSWinPostInitInitializing",
            status="False",
        )
        actions.append(ConditionMarkerAction(
            condition_template=init_condition_template
        ))
        # Make sure not is ready before proceed to any actions
        # actions.append(ReadyAction())
        actions.append(RunCommandAction(
            script=script,
            annotation_key=annotation_prefix + runcommand_suffix,
            backoff=ExpBackoff(120, 1200, 5),
        ))
        if need_reboot:
            actions.append(RebootNodeAction(
                annotation_key=annotation_prefix + reboot_suffix,
                backoff=ExpBackoff(300, 3600, 5),
            ))
        final_condition_template = kclient.V1NodeCondition(
            type=condition_type,
            message="akswinpostinit is done",
            reason="AKSWinPostInitDone",
            status="True",
        )
        actions.append(ConditionMarkerAction(
            condition_template=final_condition_template
        ))
        self.actions = actions


class NodeWatcher(object):
    def __init__(self, action_generator, azure_client,
            node_label_selector='kubernetes.io/os=windows',
            ):
        self.node_label_selector = node_label_selector
        self.triggering_events = frozenset(['ADDED', 'MODIFIED'])
        self.follower = FuturesFollower()
        self.executor = futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='action')
        self.action_generator = action_generator
        self.azure_client = azure_client
        self.ctx = AzureContext(v1=kclient.CoreV1Api(), azure_client=azure_client)
        self.follower.start()

    def node_events(self):
        v1 = kclient.CoreV1Api()
        w = watch.Watch()
        while True:
            try:
                for event in w.stream(
                        v1.list_node,
                        label_selector=self.node_label_selector, _request_timeout=120):
                    event_type = event['type']
                    node = event['object']
                    node_name = node.metadata.name
                    logger.debug('event: %s %s', event_type, node_name)
                    if event_type in self.triggering_events:
                        yield node
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.debug('ignoring error %s', e)
                continue

    def loop(self):
        with self.executor:
            for node in self.node_events():
                self.on_node_update(VMSSNodeProxy(node))

    def on_node_update(self, node):
        """
        Main logic of node update.
        """
        action = self.action_generator.get_action(node)
        if action:
            logger.info('fireing action %r for %r', action, node)
            f = self.executor.submit(action.execute, node, self.ctx)
            self.follower.add_followup(f)


def cleanup_node(v1, node, annotation_prefix, condition_type, taint_key):
    status_patch = []
    for i, condition in enumerate(node.status.conditions):
        if (condition.type == condition_type):
            status_patch.append({'op': 'remove', 'path': '/status/conditions/%d' % i})

    if status_patch:
        node = v1.patch_node_status(node.metadata.name, status_patch)

    patch = []
    for annotation in node.metadata.annotations or []:
        if annotation.startswith(annotation_prefix):
            patch.append({'op': 'remove', 'path': '/metadata/annotations/%s' % jsonpath_escape(annotation)})

    for i, taint in enumerate(node.spec.taints or []):
        if taint.key == taint_key:
            patch.append({'op': 'remove', 'path': '/spec/taints/%d' % i})

    if patch:
        node = v1.patch_node(node.metadata.name, patch)


def cleanup(annotation_prefix='github.com.tdihp.akswinpostinit/',
            condition_type='AKSWinPostInit',
            taint_key='AKSWinPostInit',
        ):
    """remove annotations, conditions and taints on all nodes"""
    v1 = kclient.CoreV1Api()
    nodes = v1.list_node()
    for node in nodes.items:
        logger.info('cleanup node %s', node.metadata.name)
        cleanup_node(v1, node, annotation_prefix, condition_type, taint_key)


def main():
    from akswinpostinit import __version__
    import argparse
    parser = argparse.ArgumentParser(description='AKS Windows node post provision initialization')
    parser.add_argument(
        '--cleanup', action='store_true',
        help='Instead of running the controller, run cleanup to remove all info such as annotations and condition')
    parser.add_argument(
        '--version', action='version', version=__version__,
        help='print version and exit')
    parser.add_argument(
        '-v', '--verbose', action='count', default=0,
        help='Increase verbosity. WARNING --> INFO --> DEBUG')
    parser.add_argument(
        '--subscription',
        help='Azure subscription for Azure client to operate on VMSS instance')
    parser.add_argument(
        '--script',
        help='Powershell script used to initialize node')
    parser.add_argument(
        '--no-reboot', dest='reboot', action='store_false',
        help='Powershell script used to initialize node')
    parser.add_argument(
        '--node-selector', default='kubernetes.io/os=windows',
        help='Node selector for finding all nodes that needs the initialization. Defaults to "kubernetes.io/os=windows"')
    parser.add_argument(
        '--condition-type', default='AKSWinPostInit',
        help='node condition type that marks the initiation status. Default: "AKSWinPostInit"'
    )
    parser.add_argument(
        '--annotation-prefix', default='github.com.tdihp.akswinpostinit/',
        help='Annotation prefix for annotations used. Default: "github.com.tdihp.akswinpostinit/"')
    parser.add_argument(
        '--taint-key', default='AKSWinPostInit',
        help='Taint key used to taint node during initialization. Default: "AKSWinPostInit"')
    parser.add_argument(
        '--taint-effect', default='NoSchedule',
        help='Effect of taint. Default: "NoSchedule"')

    args = parser.parse_args()

    log_level = {0: logging.WARNING, 1: logging.INFO}.get(args.verbose, logging.DEBUG) 
    logging.basicConfig(level=log_level)

    config.load_config()
    if args.cleanup:
        cleanup(
            condition_type=args.condition_type,
            annotation_prefix=args.annotation_prefix,
            taint_key=args.taint_key,
        )
        logger.info('cleanup done')
        parser.exit()

    if not args.script:
        raise parser.error('"--script" is required')

    if not args.subscription:
        raise parser.error('"--subscription" is required')

    azure_client = AzureClient(args.subscription)
    action_generator = WinPostInitActionGenerator(
        script=args.script,
        need_reboot=args.reboot,
        annotation_prefix=args.annotation_prefix,
        condition_type=args.condition_type,
        taint_key=args.taint_key,
        taint_effect=args.taint_effect,
    )
    node_watcher = NodeWatcher(action_generator, azure_client)
    logger.info('all components initiated, starting watch loop')
    node_watcher.loop()


def testmain():
    sub = 'd01a6635-c359-4a26-a459-554e3b6d3b46'
    config.load_config()
    azure_client = AzureClient(sub)
    action_generator = WinPostInitActionGenerator(script='[System.Environment]::OSVersion.Version')
    NodeWatcher(action_generator, azure_client).loop()
    pass


if __name__ == '__main__':
    main()
