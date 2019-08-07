import logging

import pytest

from ocs_ci.ocs import constants, ocp, defaults
from ocs_ci.framework.testlib import tier4, E2ETest
from tests.fixtures import (
    create_rbd_storageclass, create_ceph_block_pool,
    create_rbd_secret
)
from tests.helpers import create_pvc, create_pod, create_unique_resource_name
from ocs_ci.ocs.monitoring import (
    collected_metrics_for_created_pvc,
    check_used_size_of_prometheus_pod
)
from ocs_ci.ocs.resources import pvc, pod

logger = logging.getLogger(__name__)


@pytest.fixture()
def test_fixture(request):
    """
    Setup and teardown

    """
    self = request.node.cls

    def finalizer():
        teardown(self)
    request.addfinalizer(finalizer)
    setup(self)


def setup(self):
    """
    Create projects, pvcs and app pods

    """

    # Initializing
    self.namespace_list = []
    self.pvc_objs = []
    self.pod_objs = []

    assert create_project_and_pvc_and_check_metrics_are_collected(self)


def teardown(self):
    """
    Delete app pods and PVCs
    Delete project

    """
    # Delete created app pods and PVCs
    assert pod.delete_pods(self.pod_objs)
    assert pvc.delete_pvcs(self.pvc_objs)

    # Switch to default project
    ret = ocp.switch_to_default_rook_cluster_project()
    assert ret, 'Failed to switch to default rook cluster project'

    # Delete projects created
    for prj in self.namespace_list:
        prj_obj = ocp.OCP(kind='Project', namespace=prj)
        prj_obj.delete(resource_name=prj)


def create_project_and_pvc_and_check_metrics_are_collected(self):
    """
    Creates projects, pvcs and app pods

    """

    # Create new project
    self.namespace = create_unique_resource_name('test', 'namespace')
    self.project_obj = ocp.OCP(kind='Project', namespace=self.namespace)
    assert self.project_obj.new_project(self.namespace), (
        f'Failed to create new project {self.namespace}'
    )

    # Create PVCs
    self.pvc_obj = create_pvc(
        sc_name=self.sc_obj.name, namespace=self.namespace
    )

    # Create pod
    self.pod_obj = create_pod(
        interface_type=constants.CEPHBLOCKPOOL,
        pvc_name=self.pvc_obj.name, namespace=self.namespace
    )

    self.namespace_list.append(self.namespace)
    self.pvc_objs.append(self.pvc_obj)
    self.pod_objs.append(self.pod_obj)

    # Check for the created pvc metrics is collected
    for pvc_obj in self.pvc_objs:
        assert collected_metrics_for_created_pvc(pvc_obj.name), (
            f"On prometheus pod for created pvc {pvc_obj.name} related data is not collected"
        )
    return True


@pytest.mark.usefixtures(
    create_rbd_secret.__name__,
    create_ceph_block_pool.__name__,
    create_rbd_storageclass.__name__,
    test_fixture.__name__
)
@pytest.mark.polarion_id("OCS-576")
class TestRespinPrometheusPod(E2ETest):
    """
    Prometheus pod restart should not have any functional impact,
    i.e the data/metrics shouldn't be lost after the restart of prometheus pod.
    """

    @tier4
    def test_respinning_ceph_pods_and_interaction_with_prometheus_pod(self):
        """
        Test case to validate prometheus pod restart
        should not have any functional impact
        """

        # Get the prometheus pod
        pod_obj = pod.get_all_pods(namespace=defaults.OCS_MONITORING_NAMESPACE, selector=['prometheus'])

        # Get the pvc which mounted on prometheus[0] pod
        pod_info = pod_obj[0].get()
        pvc_name = pod_info['spec']['volumes'][0]['persistentVolumeClaim']['claimName']

        # Check the used space of prometheus[0] pod
        initial_used_size = check_used_size_of_prometheus_pod(pod_obj[0])

        # Respin one of the prometheus pod
        pod_obj[0].delete(force=True)
        POD = ocp.OCP(kind=constants.POD, namespace=defaults.OCS_MONITORING_NAMESPACE)
        assert POD.wait_for_resource(
            condition='Running', selector=f'app=prometheus', timeout=300
        )

        # Check the same pvc is mounted on new pod
        pod_info = pod_obj[0].get()
        assert pod_info['spec']['volumes'][0]['persistentVolumeClaim']['claimName'] in pvc_name

        # Check the used space of prometheus[0] pod should be equal or increased after respinning pod
        # i.e, the data/metrics should not be deleted which was collected before
        used_size_after_respin = check_used_size_of_prometheus_pod(pod_obj[0])
        assert used_size_after_respin >= initial_used_size

        # Check for the created pvc metrics after respinning ceph pods
        assert create_project_and_pvc_and_check_metrics_are_collected(self)
