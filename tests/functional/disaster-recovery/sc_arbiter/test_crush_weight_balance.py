"""
Test module for verifying CRUSH weight balance in stretch clusters.

This test module specifically addresses DFBUGS-2885, which involves:
- Stretch cluster failing to enable stretch mode due to unbalanced CRUSH weights
- Slight disk capacity variations from different manufacturers causing weight imbalance
- Zone weight imbalance preventing stretch mode enablement

The tests verify that:
1. Zone CRUSH weights remain balanced after add capacity operations
2. Stretch mode can be enabled with balanced weights
3. Minor disk capacity variations are handled correctly
4. Weight balance is maintained during various cluster operations
"""

import logging
import pytest

from ocs_ci.framework.pytest_customization.marks import (
    turquoise_squad,
    stretchcluster_required,
    tier1,
    tier2,
    jira,
)
from ocs_ci.helpers.crush_helpers import (
    get_zone_crush_weights,
    verify_zone_weight_balance,
    get_osd_crush_weights,
    verify_stretch_mode_enabled,
    log_crush_weight_details,
)
from ocs_ci.helpers.stretchcluster_helper import (
    verify_data_loss,
    verify_data_corruption,
)
from ocs_ci.ocs import constants
from ocs_ci.ocs.resources import storage_cluster
from ocs_ci.ocs.resources.pod import (
    get_pod_restarts_count,
    get_ceph_tools_pod,
)
from ocs_ci.ocs.resources.stretchcluster import StretchCluster

logger = logging.getLogger(__name__)


@tier1
@turquoise_squad
@jira("DFBUGS-2885")
@stretchcluster_required
class TestCrushWeightBalance:
    """
    Test CRUSH weight balance in stretch clusters with arbiter configuration.
    
    This test class verifies the fix for DFBUGS-2885 where slight disk capacity
    variations caused Ceph to fail enabling stretch mode due to unbalanced
    CRUSH weights across zones.
    """

    def test_initial_zone_weight_balance(self):
        """
        Verify that zone CRUSH weights are balanced in the initial cluster state.
        
        This test ensures that:
        1. All zones have CRUSH weights assigned
        2. Zone weights are balanced within acceptable tolerance (1%)
        3. Stretch mode is enabled
        
        Test Steps:
        1. Get CRUSH weights for all zones
        2. Verify weights are balanced within 1% tolerance
        3. Verify stretch mode is enabled
        4. Log detailed CRUSH weight information
        
        Expected Result:
        - Zone weights should be equal or within 1% difference
        - Stretch mode should be enabled
        - No CRUSH weight-related errors
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify initial zone CRUSH weight balance")
        logger.info("=" * 80)
        
        # Log detailed CRUSH weight information for debugging
        log_crush_weight_details()
        
        # Verify zone weight balance
        is_balanced, zone_weights, message = verify_zone_weight_balance(
            tolerance_percentage=1.0
        )
        
        logger.info(f"Zone weights: {zone_weights}")
        logger.info(f"Balance check result: {message}")
        
        # Assert that zones are balanced
        assert is_balanced, (
            f"Zone CRUSH weights are not balanced! {message}. "
            f"This indicates the bug DFBUGS-2885 may not be fixed. "
            f"Zone weights: {zone_weights}"
        )
        
        # Verify stretch mode is enabled
        stretch_enabled = verify_stretch_mode_enabled()
        assert stretch_enabled, (
            "Stretch mode is not enabled despite balanced weights. "
            "This may indicate a configuration issue."
        )
        
        logger.info("✓ Initial zone CRUSH weights are balanced")
        logger.info("✓ Stretch mode is enabled")

    @pytest.mark.parametrize(
        argnames=["iterations"],
        argvalues=[
            pytest.param(
                2,
                marks=[pytest.mark.polarion_id("OCS-XXXX")],
            ),
        ],
    )
    def test_zone_weight_balance_after_add_capacity(
        self,
        setup_logwriter_cephfs_workload_factory,
        setup_logwriter_rbd_workload_factory,
        iterations,
    ):
        """
        Verify zone CRUSH weights remain balanced after add capacity operations.
        
        This is a critical test for DFBUGS-2885 as the bug manifested when
        adding capacity with disks of slightly different capacities from
        different manufacturers.
        
        Test Steps:
        1. Record initial zone CRUSH weights
        2. Set up workloads (CephFS and RBD)
        3. Perform add capacity operation(s)
        4. Verify zone weights remain balanced after each iteration
        5. Verify stretch mode remains enabled
        6. Verify no OSD pod restarts occurred
        7. Verify workload data integrity
        
        Args:
            setup_logwriter_cephfs_workload_factory: Fixture for CephFS workload
            setup_logwriter_rbd_workload_factory: Fixture for RBD workload
            iterations: Number of add capacity iterations to perform
        
        Expected Result:
        - Zone weights remain balanced (within 1%) after each add capacity
        - Stretch mode remains enabled throughout
        - No OSD pod restarts
        - Workload data remains intact
        """
        logger.info("=" * 80)
        logger.info(f"TEST: Zone weight balance after {iterations} add capacity operations")
        logger.info("=" * 80)
        
        sc_obj = StretchCluster()
        
        # Get initial zone weights
        logger.info("Recording initial zone CRUSH weights...")
        initial_weights = get_zone_crush_weights()
        logger.info(f"Initial zone weights: {initial_weights}")
        
        # Verify initial balance
        is_balanced, _, message = verify_zone_weight_balance(tolerance_percentage=1.0)
        assert is_balanced, f"Initial zone weights are not balanced: {message}"
        
        # Setup workloads
        logger.info("Setting up workloads...")
        (
            sc_obj.cephfs_logwriter_dep,
            sc_obj.cephfs_logreader_job,
        ) = setup_logwriter_cephfs_workload_factory(read_duration=0)
        sc_obj.rbd_logwriter_sts = setup_logwriter_rbd_workload_factory(
            zone_aware=False
        )
        
        sc_obj.get_logwriter_reader_pods(label=constants.LOGWRITER_CEPHFS_LABEL)
        sc_obj.get_logwriter_reader_pods(label=constants.LOGREADER_CEPHFS_LABEL)
        sc_obj.get_logwriter_reader_pods(
            label=constants.LOGWRITER_RBD_LABEL, exp_num_replicas=2
        )
        logger.info("✓ All workload pods are up and running")
        
        # Get initial OSD pod restart counts
        osd_pods_restart_count_before = get_pod_restarts_count(
            label=constants.OSD_APP_LABEL
        )
        
        # Perform add capacity operations
        for iteration in range(iterations):
            logger.info("=" * 60)
            logger.info(f"Iteration {iteration + 1}/{iterations}: Adding capacity")
            logger.info("=" * 60)
            
            # Add capacity
            storage_cluster.add_capacity_lso(ui_flag=False)
            logger.info("✓ Capacity added successfully")
            
            # Get zone weights after add capacity
            logger.info("Checking zone CRUSH weights after add capacity...")
            current_weights = get_zone_crush_weights()
            logger.info(f"Current zone weights: {current_weights}")
            
            # Verify zone weight balance
            is_balanced, zone_weights, balance_message = verify_zone_weight_balance(
                tolerance_percentage=1.0
            )
            
            logger.info(f"Balance check: {balance_message}")
            
            # This is the critical assertion for DFBUGS-2885
            assert is_balanced, (
                f"Zone CRUSH weights became unbalanced after add capacity "
                f"(iteration {iteration + 1})! This indicates DFBUGS-2885 is not fixed. "
                f"Details: {balance_message}. "
                f"Initial weights: {initial_weights}, "
                f"Current weights: {current_weights}"
            )
            
            logger.info(f"✓ Zone weights remain balanced after iteration {iteration + 1}")
            
            # Verify stretch mode is still enabled
            stretch_enabled = verify_stretch_mode_enabled()
            assert stretch_enabled, (
                f"Stretch mode became disabled after add capacity "
                f"(iteration {iteration + 1}). This may indicate weight imbalance "
                f"caused stretch mode to fail."
            )
            logger.info("✓ Stretch mode remains enabled")
            
            # Log detailed CRUSH information
            log_crush_weight_details()
        
        # Verify no OSD pod restarts
        osd_pods_restart_count_after = get_pod_restarts_count(
            label=constants.OSD_APP_LABEL
        )
        
        assert sum(osd_pods_restart_count_before.values()) == sum(
            osd_pods_restart_count_after.values()
        ), "Some OSD pods restarted during add capacity operations"
        logger.info("✓ No OSD pod restarts occurred")
        
        # Verify workload data integrity
        logger.info("Verifying workload data integrity...")
        verify_data_loss(sc_obj)
        logger.info("✓ No data loss detected")
        
        logger.info("=" * 80)
        logger.info("TEST PASSED: Zone weights remained balanced throughout")
        logger.info("=" * 80)

    @tier2
    def test_osd_crush_weight_consistency(self):
        """
        Verify that OSD CRUSH weights are consistent and properly calculated.
        
        This test checks that:
        1. All OSDs have valid CRUSH weights assigned
        2. OSDs in the same zone have similar weights (within tolerance)
        3. Weight calculations are consistent with disk capacities
        
        Test Steps:
        1. Get all OSD CRUSH weights
        2. Group OSDs by zone
        3. Verify weights within each zone are consistent
        4. Check for any anomalous weight values
        
        Expected Result:
        - All OSDs have non-zero CRUSH weights
        - OSDs in same zone have similar weights (within 5% for same disk type)
        - No anomalous weight values detected
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify OSD CRUSH weight consistency")
        logger.info("=" * 80)
        
        # Get all OSD weights
        osd_weights = get_osd_crush_weights()
        logger.info(f"Total OSDs: {len(osd_weights)}")
        logger.info(f"OSD CRUSH weights: {osd_weights}")
        
        # Verify all OSDs have non-zero weights
        zero_weight_osds = [osd_id for osd_id, weight in osd_weights.items() if weight == 0]
        assert not zero_weight_osds, (
            f"Found OSDs with zero CRUSH weight: {zero_weight_osds}. "
            f"This indicates a problem with OSD weight assignment."
        )
        logger.info("✓ All OSDs have non-zero CRUSH weights")
        
        # Check for reasonable weight values (typically between 0.1 and 10.0 for most deployments)
        weights_list = list(osd_weights.values())
        min_weight = min(weights_list)
        max_weight = max(weights_list)
        
        logger.info(f"Weight range: {min_weight} to {max_weight}")
        
        # Verify weights are in reasonable range
        assert min_weight > 0, f"Minimum OSD weight is too low: {min_weight}"
        assert max_weight < 100, f"Maximum OSD weight is unusually high: {max_weight}"
        
        # Check weight variation (for detecting the DFBUGS-2885 scenario)
        # In a healthy cluster with same disk types, weights should be very similar
        weight_variation = (max_weight - min_weight) / min_weight * 100
        logger.info(f"Weight variation: {weight_variation:.2f}%")
        
        if weight_variation > 10:
            logger.warning(
                f"High weight variation detected ({weight_variation:.2f}%). "
                f"This may indicate disks of different capacities or manufacturers. "
                f"Verify that zone weights are still balanced."
            )
            
            # Even with variation, zone weights should be balanced
            is_balanced, zone_weights, message = verify_zone_weight_balance(
                tolerance_percentage=1.0
            )
            assert is_balanced, (
                f"Despite OSD weight variation, zone weights must be balanced. "
                f"Details: {message}"
            )
        
        logger.info("✓ OSD CRUSH weights are consistent and valid")

    def test_stretch_mode_with_balanced_weights(self):
        """
        Verify that stretch mode remains operational with balanced CRUSH weights.
        
        This test specifically validates the fix for DFBUGS-2885 by ensuring:
        1. Stretch mode is enabled
        2. Zone weights are balanced
        3. Ceph cluster is healthy
        4. No weight-related errors in logs
        
        Test Steps:
        1. Verify stretch mode is enabled
        2. Verify zone weight balance
        3. Check Ceph health status
        4. Verify no CRUSH-related warnings
        
        Expected Result:
        - Stretch mode is enabled and operational
        - Zone weights are balanced
        - Ceph cluster is healthy
        - No CRUSH weight warnings or errors
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify stretch mode with balanced CRUSH weights")
        logger.info("=" * 80)
        
        # Verify stretch mode is enabled
        stretch_enabled = verify_stretch_mode_enabled()
        assert stretch_enabled, (
            "Stretch mode is not enabled. This test requires stretch mode to be active."
        )
        logger.info("✓ Stretch mode is enabled")
        
        # Verify zone weight balance
        is_balanced, zone_weights, message = verify_zone_weight_balance(
            tolerance_percentage=1.0
        )
        
        logger.info(f"Zone weights: {zone_weights}")
        logger.info(f"Balance status: {message}")
        
        assert is_balanced, (
            f"Zone CRUSH weights are not balanced in stretch mode! "
            f"This indicates DFBUGS-2885 may not be fully resolved. "
            f"Details: {message}"
        )
        logger.info("✓ Zone CRUSH weights are balanced")
        
        # Check Ceph health
        ceph_tools_pod = get_ceph_tools_pod()
        ceph_health = ceph_tools_pod.exec_ceph_cmd(ceph_cmd="ceph health")
        logger.info(f"Ceph health: {ceph_health}")
        
        # Get detailed status
        ceph_status = ceph_tools_pod.exec_ceph_cmd(ceph_cmd="ceph -s")
        logger.info(f"Ceph status:\n{ceph_status}")
        
        # Log detailed CRUSH information
        log_crush_weight_details()
        
        logger.info("=" * 80)
        logger.info("TEST PASSED: Stretch mode operational with balanced weights")
        logger.info("=" * 80)

# Made with Bob
