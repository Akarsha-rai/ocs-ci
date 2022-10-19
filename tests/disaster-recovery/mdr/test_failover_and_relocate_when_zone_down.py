import logging
import pytest

# from ocs_ci.framework import config
from ocs_ci.ocs.constants import MDR_ZONE_YAML
from ocs_ci.framework.pytest_customization.marks import mdr_test
from ocs_ci.framework.testlib import ManageTest
from ocs_ci.ocs.node import (
    wait_for_nodes_status,
    # get_node_objs,
)
from ocs_ci.helpers.dr_helpers import (
    enable_fence,
    enable_unfence,
    get_fence_state,
    failover,
    relocate,
    set_current_primary_cluster_context,
    set_current_secondary_cluster_context,
    get_current_primary_cluster_name,
    get_current_secondary_cluster_name,
    wait_for_all_resources_creation,
    wait_for_all_resources_deletion,
    validate_data_integrity,
    gracefully_reboot_nodes,
)

# from ocs_ci.ocs import platform_nodes
from ocs_ci.utility import templating

logger = logging.getLogger(__name__)


@mdr_test
class TestFailoverAndRelocateWhenZoneDown(ManageTest):
    """
    Test Failover and Relocate actions for a busybox application

    """

    @pytest.fixture(autouse=True)
    def teardown(self, request, rdr_workload):
        """
        If fenced, unfence the cluster and reboot nodes
        """

        def finalizer():
            if self.drcluster_name and get_fence_state(self.drcluster_name) == "Fenced":
                enable_unfence(self.drcluster_name)
                gracefully_reboot_nodes(self.namespace, self.drcluster_name)

        request.addfinalizer(finalizer)

    @pytest.mark.parametrize(
        argnames=["zone_down"],
        argvalues=[
            pytest.param("b", marks=pytest.mark.polarion_id("OCS-xxxx"), id="zone_b"),
            pytest.param("c", marks=pytest.mark.polarion_id("OCS-xxxx"), id="zone_c"),
            pytest.param("a", marks=pytest.mark.polarion_id("OCS-xxxx"), id="zone_a"),
        ],
    )
    def test_failover_and_relocate_when_one_zone_down(
        self, zone_down, rdr_workload, nodes_multicluster, node_restart_teardown
    ):
        """
        Tests to verify application failover and relocate
        between managed clusters when one managed cluster down

        """

        # Create application on Primary managed cluster
        set_current_primary_cluster_context(rdr_workload.workload_namespace)
        primary_cluster_name = get_current_primary_cluster_name(
            namespace=rdr_workload.workload_namespace
        )
        self.drcluster_name = primary_cluster_name
        self.namespace = rdr_workload.workload_namespace

        # Make zone down
        zone_yaml_data = templating.load_yaml(MDR_ZONE_YAML)
        if "b" == zone_down:
            nodes = zone_yaml_data["b"]
        elif "c" == zone_down:
            nodes = zone_yaml_data["b"]
        else:
            nodes = zone_yaml_data["a"]

        # stop_nodes(nodes)

        # Fenced the primary managed cluster
        enable_fence(drcluster_name=self.drcluster_name)

        # Application Failover to Secondary managed cluster
        secondary_cluster_name = get_current_secondary_cluster_name(
            rdr_workload.workload_namespace
        )
        failover(
            failover_cluster=secondary_cluster_name,
            namespace=rdr_workload.workload_namespace,
        )

        # Verify application are running in other managedcluster
        # And not in previous cluster
        set_current_primary_cluster_context(rdr_workload.workload_namespace)
        wait_for_all_resources_creation(
            rdr_workload.workload_pvc_count,
            rdr_workload.workload_pod_count,
            rdr_workload.workload_namespace,
        )

        # Verify application are deleted from old cluster
        set_current_secondary_cluster_context(rdr_workload.workload_namespace)
        wait_for_all_resources_deletion(rdr_workload.workload_namespace)

        # ToDo: Validate same PV being used

        # Validate data integrity
        set_current_primary_cluster_context(rdr_workload.workload_namespace)
        validate_data_integrity(rdr_workload.workload_namespace)

        # Bring up zone which was down
        # start_nodes(nodes)
        wait_for_nodes_status([node.name for node in nodes])

        # Unfenced the managed cluster which was Fenced earlier
        enable_unfence(drcluster_name=self.drcluster_name)

        # Reboot the nodes which unfenced
        gracefully_reboot_nodes(rdr_workload.workload_namespace, self.drcluster_name)

        # ToDo: Validate PV is in Released state

        # Application Relocate to Primary managed cluster
        secondary_cluster_name = get_current_secondary_cluster_name(
            rdr_workload.workload_namespace
        )
        relocate(secondary_cluster_name, rdr_workload.workload_namespace)

        # Verify resources deletion from previous primary or current secondary cluster
        set_current_secondary_cluster_context(rdr_workload.workload_namespace)
        wait_for_all_resources_deletion(rdr_workload.workload_namespace)

        # Verify resources creation on preferredCluster
        set_current_primary_cluster_context(rdr_workload.workload_namespace)
        wait_for_all_resources_creation(
            rdr_workload.workload_pvc_count,
            rdr_workload.workload_pod_count,
            rdr_workload.workload_namespace,
        )

        # Validate data integrity
        set_current_primary_cluster_context(rdr_workload.workload_namespace)
        validate_data_integrity(rdr_workload.workload_namespace)
