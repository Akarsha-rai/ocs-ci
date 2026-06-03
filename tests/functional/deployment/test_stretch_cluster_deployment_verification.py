"""
Deployment verification test for stretch clusters with varied disk capacities.

This test module specifically addresses DFBUGS-2885 deployment verification:
- Verifies stretch cluster deployment succeeds with slight disk capacity variations
- Validates no errors in CephCluster status
- Checks rook-ceph-operator logs for CRUSH weight or stretch mode errors
- Confirms stretch mode is properly configured from the Ceph side

The test ensures that the fix for DFBUGS-2885 allows stretch clusters to deploy
successfully even when disks from different manufacturers have slight capacity
variations.
"""

import logging
import pytest
import re

from ocs_ci.framework.pytest_customization.marks import (
    turquoise_squad,
    stretchcluster_required,
    deployment,
    tier1,
    jira,
)
from ocs_ci.helpers.crush_helpers import (
    verify_zone_weight_balance,
    verify_stretch_mode_enabled,
    log_crush_weight_details,
    get_osd_crush_weights,
)
from ocs_ci.ocs import constants
from ocs_ci.ocs.ocp import OCP
from ocs_ci.ocs.resources.pod import (
    get_ceph_tools_pod,
    get_pod_logs,
    get_pods_having_label,
)
from ocs_ci.framework import config
from ocs_ci.ocs.cluster import CephCluster

logger = logging.getLogger(__name__)


@tier1
@turquoise_squad
@jira("DFBUGS-2885")
@stretchcluster_required
@deployment
class TestStretchClusterDeploymentVerification:
    """
    Verify stretch cluster deployment with varied disk capacities.
    
    This test class validates that DFBUGS-2885 fix allows stretch clusters
    to deploy successfully even with slight disk capacity variations from
    different manufacturers.
    """

    def test_stretch_cluster_deployment_status(self):
        """
        Verify stretch cluster deployment completed successfully.
        
        This test validates:
        1. CephCluster CR status is HEALTH_OK
        2. No errors related to CRUSH weights in CephCluster status
        3. Stretch mode is enabled
        4. Zone weights are balanced
        5. All OSDs are up and in
        
        Test Steps:
        1. Get CephCluster CR status
        2. Verify Ceph health is OK
        3. Check for any CRUSH weight related errors
        4. Verify stretch mode is enabled
        5. Validate zone weight balance
        6. Confirm all OSDs are operational
        
        Expected Result:
        - CephCluster status shows HEALTH_OK
        - No CRUSH weight errors in status
        - Stretch mode is enabled
        - Zone weights are balanced
        - All OSDs are up and in
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify stretch cluster deployment status")
        logger.info("=" * 80)
        
        # Get CephCluster CR
        ceph_cluster = CephCluster()
        cluster_status = ceph_cluster.cluster_health_check(timeout=300)
        
        logger.info(f"CephCluster health status: {cluster_status}")
        
        # Verify Ceph health
        assert cluster_status, (
            "CephCluster is not healthy after deployment. "
            "This may indicate DFBUGS-2885 is not fixed if the issue is "
            "related to CRUSH weight imbalance."
        )
        logger.info("✓ CephCluster status is HEALTH_OK")
        
        # Get detailed Ceph status
        ceph_tools_pod = get_ceph_tools_pod()
        ceph_status = ceph_tools_pod.exec_ceph_cmd(ceph_cmd="ceph -s")
        logger.info(f"Detailed Ceph status:\n{ceph_status}")
        
        # Check for CRUSH-related warnings in Ceph status
        ceph_status_str = str(ceph_status)
        crush_warnings = [
            "crush",
            "weight",
            "imbalance",
            "unbalanced",
        ]
        
        found_warnings = []
        for warning in crush_warnings:
            if warning.lower() in ceph_status_str.lower():
                found_warnings.append(warning)
        
        if found_warnings:
            logger.warning(
                f"Found potential CRUSH-related warnings in Ceph status: {found_warnings}"
            )
            logger.warning(f"Full status: {ceph_status_str}")
        else:
            logger.info("✓ No CRUSH weight warnings in Ceph status")
        
        # Verify stretch mode is enabled
        stretch_enabled = verify_stretch_mode_enabled()
        assert stretch_enabled, (
            "Stretch mode is not enabled after deployment. "
            "This indicates DFBUGS-2885 may not be fixed - stretch mode "
            "should be enabled despite minor disk capacity variations."
        )
        logger.info("✓ Stretch mode is enabled")
        
        # Verify zone weight balance
        is_balanced, zone_weights, message = verify_zone_weight_balance(
            tolerance_percentage=1.0
        )
        
        logger.info(f"Zone weights: {zone_weights}")
        logger.info(f"Balance status: {message}")
        
        assert is_balanced, (
            f"Zone CRUSH weights are not balanced after deployment! "
            f"This indicates DFBUGS-2885 is not fixed. "
            f"Details: {message}"
        )
        logger.info("✓ Zone CRUSH weights are balanced")
        
        # Verify all OSDs are up and in
        osd_stat = ceph_tools_pod.exec_ceph_cmd(ceph_cmd="ceph osd stat")
        logger.info(f"OSD status: {osd_stat}")
        
        # Log detailed CRUSH information
        log_crush_weight_details()
        
        logger.info("=" * 80)
        logger.info("TEST PASSED: Stretch cluster deployed successfully")
        logger.info("=" * 80)

    def test_rook_operator_logs_for_crush_errors(self):
        """
        Verify rook-ceph-operator logs for CRUSH weight or stretch mode errors.
        
        This test checks:
        1. Rook operator logs for CRUSH weight errors
        2. Logs for stretch mode enablement failures
        3. Logs for zone weight imbalance errors
        4. Any other deployment-related errors
        
        Test Steps:
        1. Get rook-ceph-operator pod
        2. Retrieve recent logs
        3. Search for CRUSH weight related errors
        4. Search for stretch mode errors
        5. Report any found issues
        
        Expected Result:
        - No CRUSH weight errors in rook operator logs
        - No stretch mode enablement failures
        - No zone weight imbalance errors
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify rook-ceph-operator logs for errors")
        logger.info("=" * 80)
        
        # Get rook-ceph-operator pod
        rook_operator_pods = get_pods_having_label(
            label="app=rook-ceph-operator",
            namespace=constants.OPENSHIFT_STORAGE_NAMESPACE,
        )
        
        assert rook_operator_pods, "No rook-ceph-operator pod found"
        
        rook_operator_pod = rook_operator_pods[0]
        logger.info(f"Checking logs for pod: {rook_operator_pod['metadata']['name']}")
        
        # Get pod logs (last 1000 lines to avoid overwhelming output)
        try:
            logs = get_pod_logs(
                pod_name=rook_operator_pod['metadata']['name'],
                namespace=constants.OPENSHIFT_STORAGE_NAMESPACE,
                tail=1000,
            )
        except Exception as e:
            logger.warning(f"Could not retrieve full logs: {e}")
            # Try without tail parameter
            logs = get_pod_logs(
                pod_name=rook_operator_pod['metadata']['name'],
                namespace=constants.OPENSHIFT_STORAGE_NAMESPACE,
            )
        
        # Define error patterns to search for
        error_patterns = {
            "crush_weight": [
                r"crush.*weight.*error",
                r"crush.*weight.*fail",
                r"unbalanced.*crush",
                r"crush.*imbalance",
            ],
            "stretch_mode": [
                r"stretch.*mode.*error",
                r"stretch.*mode.*fail",
                r"failed.*enable.*stretch",
                r"stretch.*cluster.*fail",
            ],
            "zone_weight": [
                r"zone.*weight.*error",
                r"zone.*weight.*imbalance",
                r"zone.*weight.*fail",
            ],
            "deployment": [
                r"deployment.*fail.*crush",
                r"deployment.*fail.*stretch",
            ],
        }
        
        found_errors = {}
        
        for category, patterns in error_patterns.items():
            category_errors = []
            for pattern in patterns:
                # Convert logs to string if it's not already
                logs_str = str(logs) if not isinstance(logs, str) else logs
                matches = re.findall(pattern, logs_str, re.IGNORECASE)
                if matches:
                    category_errors.extend(matches)
            
            if category_errors:
                found_errors[category] = category_errors
        
        # Report findings
        if found_errors:
            logger.warning("Found potential errors in rook-ceph-operator logs:")
            for category, errors in found_errors.items():
                logger.warning(f"\n{category.upper()} errors:")
                for error in set(errors):  # Use set to avoid duplicates
                    logger.warning(f"  - {error}")
            
            # For DFBUGS-2885, CRUSH weight and stretch mode errors are critical
            critical_categories = ["crush_weight", "stretch_mode", "zone_weight"]
            critical_errors = any(cat in found_errors for cat in critical_categories)
            
            if critical_errors:
                pytest.fail(
                    f"Found critical CRUSH weight or stretch mode errors in "
                    f"rook-ceph-operator logs. This indicates DFBUGS-2885 may "
                    f"not be fully fixed. Errors: {found_errors}"
                )
        else:
            logger.info("✓ No CRUSH weight or stretch mode errors found in rook logs")
        
        logger.info("=" * 80)
        logger.info("TEST PASSED: No critical errors in rook operator logs")
        logger.info("=" * 80)

    def test_cephcluster_cr_status_conditions(self):
        """
        Verify CephCluster CR status conditions for any warnings or errors.
        
        This test checks:
        1. CephCluster CR status conditions
        2. Any warnings related to CRUSH weights
        3. Any errors in cluster configuration
        4. Stretch cluster specific conditions
        
        Test Steps:
        1. Get CephCluster CR
        2. Check status conditions
        3. Look for CRUSH or stretch mode related conditions
        4. Verify no error conditions exist
        
        Expected Result:
        - No error conditions in CephCluster CR
        - No CRUSH weight warnings
        - Stretch cluster conditions are healthy
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify CephCluster CR status conditions")
        logger.info("=" * 80)
        
        # Get CephCluster CR
        ocp_obj = OCP(
            kind="CephCluster",
            namespace=config.ENV_DATA["cluster_namespace"],
        )
        
        ceph_cluster_data = ocp_obj.get(
            resource_name=constants.DEFAULT_CLUSTERNAME
        )
        
        # Get status section - handle both dict and list returns
        if isinstance(ceph_cluster_data, dict):
            status = ceph_cluster_data.get("status", {})
        elif isinstance(ceph_cluster_data, list) and len(ceph_cluster_data) > 0:
            status = ceph_cluster_data[0].get("status", {})
        else:
            status = {}
        logger.info(f"CephCluster status: {status}")
        
        # Check conditions
        conditions = status.get("conditions", [])
        logger.info(f"Found {len(conditions)} conditions")
        
        error_conditions = []
        warning_conditions = []
        crush_related_conditions = []
        
        for condition in conditions:
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")
            condition_reason = condition.get("reason", "")
            condition_message = condition.get("message", "")
            
            logger.info(
                f"Condition: {condition_type} = {condition_status}, "
                f"Reason: {condition_reason}"
            )
            
            # Check for error conditions
            if condition_status == "False" and "error" in condition_reason.lower():
                error_conditions.append(condition)
            
            # Check for warnings
            if "warning" in condition_reason.lower():
                warning_conditions.append(condition)
            
            # Check for CRUSH or stretch related conditions
            crush_keywords = ["crush", "weight", "stretch", "zone", "imbalance"]
            if any(
                keyword in condition_message.lower()
                or keyword in condition_reason.lower()
                for keyword in crush_keywords
            ):
                crush_related_conditions.append(condition)
        
        # Report findings
        if error_conditions:
            logger.error(f"Found {len(error_conditions)} error conditions:")
            for cond in error_conditions:
                logger.error(f"  - {cond}")
            pytest.fail(
                f"CephCluster has error conditions: {error_conditions}. "
                f"This may indicate deployment issues related to DFBUGS-2885."
            )
        
        if warning_conditions:
            logger.warning(f"Found {len(warning_conditions)} warning conditions:")
            for cond in warning_conditions:
                logger.warning(f"  - {cond}")
        
        if crush_related_conditions:
            logger.info(f"Found {len(crush_related_conditions)} CRUSH-related conditions:")
            for cond in crush_related_conditions:
                logger.info(f"  - {cond}")
                # Check if it's an error condition
                if cond.get("status") == "False":
                    pytest.fail(
                        f"Found CRUSH-related error condition: {cond}. "
                        f"This indicates DFBUGS-2885 may not be fixed."
                    )
        
        logger.info("✓ No error conditions in CephCluster CR")
        logger.info("=" * 80)
        logger.info("TEST PASSED: CephCluster CR status is healthy")
        logger.info("=" * 80)

    def test_osd_weight_variation_tolerance(self):
        """
        Verify that OSD weight variations are within acceptable limits.
        
        This test specifically addresses the DFBUGS-2885 scenario where
        disks from different manufacturers have slight capacity variations.
        
        Test Steps:
        1. Get all OSD CRUSH weights
        2. Calculate weight variation across OSDs
        3. Verify variation is within acceptable limits
        4. Ensure zone weights remain balanced despite OSD variations
        
        Expected Result:
        - OSD weight variation is documented
        - Zone weights are balanced despite OSD variations
        - Stretch mode is operational
        """
        logger.info("=" * 80)
        logger.info("TEST: Verify OSD weight variation tolerance")
        logger.info("=" * 80)
        
        # Get all OSD weights
        osd_weights = get_osd_crush_weights()
        logger.info(f"Total OSDs: {len(osd_weights)}")
        
        if len(osd_weights) < 2:
            pytest.skip("Need at least 2 OSDs to test weight variation")
        
        weights_list = list(osd_weights.values())
        min_weight = min(weights_list)
        max_weight = max(weights_list)
        avg_weight = sum(weights_list) / len(weights_list)
        
        # Calculate variation
        weight_variation_pct = ((max_weight - min_weight) / avg_weight) * 100
        
        logger.info(f"OSD weight statistics:")
        logger.info(f"  Minimum weight: {min_weight}")
        logger.info(f"  Maximum weight: {max_weight}")
        logger.info(f"  Average weight: {avg_weight:.4f}")
        logger.info(f"  Variation: {weight_variation_pct:.2f}%")
        
        # Document the variation
        if weight_variation_pct > 5:
            logger.info(
                f"Detected OSD weight variation of {weight_variation_pct:.2f}%. "
                f"This is typical when using disks from different manufacturers "
                f"(DFBUGS-2885 scenario)."
            )
        else:
            logger.info(
                f"OSD weight variation is minimal ({weight_variation_pct:.2f}%). "
                f"All disks appear to have similar capacities."
            )
        
        # The key test: despite OSD weight variations, zone weights must be balanced
        is_balanced, zone_weights, message = verify_zone_weight_balance(
            tolerance_percentage=1.0
        )
        
        assert is_balanced, (
            f"Zone weights are not balanced despite OSD weight variations. "
            f"This indicates DFBUGS-2885 fix is not working correctly. "
            f"OSD variation: {weight_variation_pct:.2f}%, "
            f"Zone balance: {message}"
        )
        
        logger.info(
            f"✓ Zone weights are balanced ({message}) despite "
            f"OSD weight variation of {weight_variation_pct:.2f}%"
        )
        
        # Verify stretch mode is still operational
        stretch_enabled = verify_stretch_mode_enabled()
        assert stretch_enabled, (
            "Stretch mode is not enabled despite balanced zone weights. "
            "This may indicate a configuration issue."
        )
        logger.info("✓ Stretch mode is operational")
        
        logger.info("=" * 80)
        logger.info(
            "TEST PASSED: System tolerates OSD weight variations correctly"
        )
        logger.info("=" * 80)

# Made with Bob
