import logging
import pytest
import time
import random

from ocs_ci.ocs import constants, ocp
from ocs_ci.framework.testlib import (
    E2ETest, workloads, ignore_leftovers
)
from tests.helpers import default_storage_class
from tests.sanity_helpers import Sanity
from ocs_ci.ocs.node import (
    wait_for_nodes_status, get_node_objs, get_typed_nodes
)
from ocs_ci.utility import templating
from ocs_ci.utility.retry import retry
from ocs_ci.ocs.exceptions import CommandFailed, ResourceWrongStatusException
from ocs_ci.ocs.resources.pod import get_all_pods
from ocs_ci.ocs.amq import get_node_objs_where_benchmark_pod_not_hosted


log = logging.getLogger(__name__)
POD = ocp.OCP(kind=constants.POD, namespace=constants.AMQ_NAMESPACE)
TILLER_NAMESPACE = "tiller"


@ignore_leftovers
@workloads
class TestAMQNodeReboot(E2ETest):
    """
    Test case to reboot or shutdown and recovery
    node when amq workload is running

    """

    @pytest.fixture(autouse=True)
    def init_sanity(self):
        """
        Initialize Sanity instance

        """
        self.sanity_helpers = Sanity()

    @pytest.fixture(autouse=True)
    def teardown(self, request, nodes):
        """
        Restart nodes that are in status NotReady
        for situations in which the test failed in between

        """

        def finalizer():

            # Validate all nodes are in READY state
            not_ready_nodes = [
                n for n in get_node_objs() if n
                .ocp.get_resource_status(n.name) == constants.NODE_NOT_READY
            ]
            log.warning(
                f"Nodes in NotReady status found: {[n.name for n in not_ready_nodes]}"
            )
            if not_ready_nodes:
                nodes.restart_nodes_by_stop_and_start(not_ready_nodes)
                wait_for_nodes_status()

            log.info("All nodes are in Ready status")

        request.addfinalizer(finalizer)

    @pytest.fixture()
    def amq_setup(self, amq_factory_fixture):
        """
        Creates amq cluster and run benchmarks
        """
        sc_name = default_storage_class(interface_type=constants.CEPHBLOCKPOOL)
        self.amq_workload_dict = templating.load_yaml(constants.AMQ_SIMPLE_WORKLOAD_YAML)
        self.amq, self.thread = amq_factory_fixture(
            sc_name=sc_name.name, tiller_namespace=TILLER_NAMESPACE,
            amq_workload_yaml=self.amq_workload_dict, run_in_bg=True
        )

    @pytest.mark.polarion_id("OCS-1281")
    def test_amq_after_rebooting_master_node(self, nodes, amq_setup):
        """
        Test case to validate rebooting master node shouldn't effect
        amq workloads running in background

        """
        # Get all amq pods
        pod_obj_list = get_all_pods(namespace=constants.AMQ_NAMESPACE)

        # Get the master node list
        master_nodes = get_typed_nodes(node_type='master')

        # Reboot one master nodes
        node = random.choice(master_nodes)
        nodes.restart_nodes([node], wait=False)

        # Wait some time after rebooting master
        waiting_time = 40
        log.info(f"Waiting {waiting_time} seconds...")
        time.sleep(waiting_time)

        # Validate all nodes and services are in READY state and up
        retry(
            (CommandFailed, TimeoutError, AssertionError, ResourceWrongStatusException),
            tries=60,
            delay=15)(
            ocp.wait_for_cluster_connectivity(tries=400)
        )
        retry(
            (CommandFailed, TimeoutError, AssertionError, ResourceWrongStatusException),
            tries=60,
            delay=15)(
            wait_for_nodes_status(timeout=1800)
        )

        # Check the node are Ready state and check cluster is health ok
        self.sanity_helpers.health_check()

        # Check all amq pods are up and running
        assert POD.wait_for_resource(
            condition='Running', resource_count=len(pod_obj_list), timeout=300
        )

        # Validate and collect the results
        log.info("Validate amq benchmark is run completely")
        result = self.thread.result(timeout=1800)
        log.info(result)
        assert self.amq.validate_amq_benchmark(
            result=result, amq_workload_yaml=self.amq_workload_dict
        ) is not None, (
            "Benchmark did not completely run or might failed in between"
        )

    @pytest.mark.polarion_id("OCS-1282")
    def test_amq_after_rebooting_worker_node(self, nodes, amq_setup):
        """
        Test case to validate rebooting worker node shouldn't effect
        amq workloads running in background

        """
        # Get all amq pods
        pod_obj_list = get_all_pods(namespace=constants.AMQ_NAMESPACE)

        # Get the worker node list such that benchmark pod not hosted on it
        node_list = get_node_objs_where_benchmark_pod_not_hosted(
            namespace=TILLER_NAMESPACE
        )

        # Reboot one worker nodes
        node = random.choice(node_list)
        nodes.restart_nodes([node], wait=False)

        # Validate all nodes are in READY state and up
        retry(
            (CommandFailed, TimeoutError, AssertionError, ResourceWrongStatusException),
            tries=30,
            delay=15)(
            wait_for_nodes_status(timeout=1800)
        )

        # Check the node are Ready state and check cluster is health ok
        self.sanity_helpers.health_check()

        # Check all amq pods are up and running
        assert POD.wait_for_resource(
            condition='Running', resource_count=len(pod_obj_list), timeout=300
        )

        # Validate and collect the results
        log.info("Validate amq benchmark is run completely")
        result = self.thread.result(timeout=1800)
        log.info(result)
        assert self.amq.validate_amq_benchmark(
            result=result, amq_workload_yaml=self.amq_workload_dict
        ) is not None, (
            "Benchmark did not completely run or might failed in between"
        )

    @pytest.mark.polarion_id("OCS-1278")
    def test_amq_after_shutdown_and_recovery_worker_node(self, nodes, amq_setup):
        """
        Test case to validate shutdown and recovery node
        shouldn't effect amq workloads running in background

        """
        # Get all amq pods
        pod_obj_list = get_all_pods(namespace=constants.AMQ_NAMESPACE)

        # Get the worker node list such that benchmark pod not hosted on it
        node_list = get_node_objs_where_benchmark_pod_not_hosted(
            namespace=TILLER_NAMESPACE
        )

        # Reboot one after one master nodes
        node = random.choice(node_list)
        nodes.stop_nodes([node], wait=False)

        waiting_time = 20
        log.info(f"Waiting for {waiting_time} seconds")
        time.sleep(waiting_time)

        nodes.start_nodes(nodes=[node])

        # Validate all nodes are in READY state and up
        retry(
            (CommandFailed, TimeoutError, AssertionError, ResourceWrongStatusException),
            tries=30,
            delay=15)(
            wait_for_nodes_status(timeout=1800)
        )

        # Check the node are Ready state and check cluster is health ok
        self.sanity_helpers.health_check()

        # Check all amq pods are up and running
        assert POD.wait_for_resource(
            condition='Running', resource_count=len(pod_obj_list), timeout=300
        )

        # Validate and collect the results
        log.info("Validate amq benchmark is run completely")
        result = self.thread.result(timeout=1800)
        log.info(result)
        assert self.amq.validate_amq_benchmark(
            result=result, amq_workload_yaml=self.amq_workload_dict
        ) is not None, (
            "Benchmark did not completely run or might failed in between"
        )
