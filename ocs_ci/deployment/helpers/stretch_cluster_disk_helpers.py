"""
Helper functions for creating disks with varied capacities for stretch cluster deployment.

This module provides utilities to simulate the DFBUGS-2885 scenario where disks from
different manufacturers have slight capacity variations, which previously caused
stretch cluster deployment failures due to CRUSH weight imbalance.
"""

import logging
from ocs_ci.framework import config
from ocs_ci.ocs import constants

logger = logging.getLogger(__name__)


def get_varied_disk_sizes_for_stretch_cluster(base_size=100, variation_percent=2.0):
    """
    Generate disk sizes with slight variations to simulate DFBUGS-2885 scenario.
    
    This function creates disk sizes that vary slightly to simulate the real-world
    scenario where ONE node in a zone has disks from a different manufacturer with
    slightly different capacity. This matches the actual DFBUGS-2885 bug scenario.
    
    Args:
        base_size (int): Base disk size in GB (default: 100)
        variation_percent (float): Percentage variation to apply (default: 2.0%)
    
    Returns:
        list: List of disk sizes with variations
        
    Example:
        For a stretch cluster with 3 nodes per zone, 1 disk per node, base_size=100:
        Zone 1 (data-1): [100, 100, 100]  # All same size
        Zone 2 (data-2): [100, 100, 102]  # Last node has different size (simulates DFBUGS-2885)
    
    """
    # Get number of zones (typically 2 data zones + 1 arbiter for stretch cluster)
    num_zones = len(constants.DATA_ZONE_LABELS)
    
    # Get number of nodes per zone and disks per node
    nodes_per_zone = config.ENV_DATA.get("worker_replicas", 3)
    disks_per_node = config.ENV_DATA.get("extra_disks", 1)
    
    logger.info(
        f"Generating varied disk sizes for stretch cluster (DFBUGS-2885 scenario): "
        f"{num_zones} zones, {nodes_per_zone} nodes per zone, "
        f"{disks_per_node} disks per node, "
        f"base size: {base_size}GB, variation: ±{variation_percent}%"
    )
    
    # Calculate variation
    variation_amount = int(base_size * (variation_percent / 100))
    varied_size = base_size + variation_amount
    
    # Create disk sizes - only ONE node in zone 2 will have different size
    # This simulates the real DFBUGS-2885 scenario
    all_disk_sizes = []
    
    for zone_idx in range(num_zones):
        zone_label = constants.DATA_ZONE_LABELS[zone_idx] if zone_idx < len(constants.DATA_ZONE_LABELS) else 'arbiter'
        zone_disks = []
        
        for node_idx in range(nodes_per_zone):
            # Only the last node in zone 2 (data-2) gets different disk size
            # This matches the DFBUGS-2885 scenario where one node had disks from different manufacturer
            if zone_idx == 1 and node_idx == nodes_per_zone - 1:
                # Last node in second zone: use varied size
                node_disks = [varied_size] * disks_per_node
                logger.info(
                    f"Zone {zone_idx + 1} ({zone_label}), Node {node_idx + 1}: "
                    f"{disks_per_node} disks of {varied_size}GB each (VARIED - simulates different manufacturer)"
                )
            else:
                # All other nodes: use base size
                node_disks = [base_size] * disks_per_node
                logger.info(
                    f"Zone {zone_idx + 1} ({zone_label}), Node {node_idx + 1}: "
                    f"{disks_per_node} disks of {base_size}GB each"
                )
            
            zone_disks.extend(node_disks)
        
        all_disk_sizes.extend(zone_disks)
    
    logger.info(f"Total disks to create: {len(all_disk_sizes)}")
    logger.info(f"Disk sizes: {all_disk_sizes}")
    logger.info(
        f"DFBUGS-2885 simulation: Only 1 node in zone-2 has {varied_size}GB disks, "
        f"all others have {base_size}GB disks"
    )
    
    return all_disk_sizes


def should_use_varied_disk_sizes():
    """
    Determine if varied disk sizes should be used for deployment.
    
    This checks configuration to see if we should simulate the DFBUGS-2885
    scenario with varied disk capacities.
    
    Returns:
        bool: True if varied disk sizes should be used, False otherwise
    
    """
    # Check if explicitly enabled in config
    use_varied_sizes = config.ENV_DATA.get("use_varied_disk_sizes_for_stretch", False)
    
    # Also check if we're testing DFBUGS-2885 specifically
    test_dfbugs_2885 = config.ENV_DATA.get("test_dfbugs_2885", False)
    
    return use_varied_sizes or test_dfbugs_2885


def get_disk_sizes_for_deployment(base_size=100):
    """
    Get disk sizes for deployment, either uniform or varied based on configuration.
    
    Args:
        base_size (int): Base disk size in GB (default: 100)
    
    Returns:
        list: List of disk sizes to use for deployment
    
    """
    if should_use_varied_disk_sizes():
        logger.info(
            "Using varied disk sizes for stretch cluster deployment "
            "(simulating DFBUGS-2885 scenario)"
        )
        variation_percent = config.ENV_DATA.get("disk_size_variation_percent", 2.0)
        return get_varied_disk_sizes_for_stretch_cluster(base_size, variation_percent)
    else:
        logger.info("Using uniform disk sizes for deployment")
        num_disks = config.ENV_DATA.get("extra_disks", 1)
        return [base_size] * num_disks


def log_disk_configuration_for_stretch_cluster():
    """
    Log the disk configuration that will be used for stretch cluster deployment.
    
    This is useful for debugging and verification purposes.
    """
    logger.info("=" * 80)
    logger.info("Stretch Cluster Disk Configuration")
    logger.info("=" * 80)
    
    base_size = config.ENV_DATA.get("device_size", 100)
    use_varied = should_use_varied_disk_sizes()
    
    logger.info(f"Base disk size: {base_size}GB")
    logger.info(f"Use varied disk sizes: {use_varied}")
    
    if use_varied:
        variation_percent = config.ENV_DATA.get("disk_size_variation_percent", 2.0)
        logger.info(f"Disk size variation: ±{variation_percent}%")
        logger.info(
            "This configuration simulates DFBUGS-2885 scenario where disks "
            "from different manufacturers have slight capacity variations"
        )
        
        disk_sizes = get_disk_sizes_for_deployment(base_size)
        logger.info(f"Disk sizes to be created: {disk_sizes}")
        
        # Calculate expected CRUSH weight variation
        min_size = min(disk_sizes)
        max_size = max(disk_sizes)
        weight_variation = ((max_size - min_size) / min_size) * 100
        logger.info(
            f"Expected CRUSH weight variation: ~{weight_variation:.2f}% "
            f"(from {min_size}GB to {max_size}GB disks)"
        )
    else:
        num_disks = config.ENV_DATA.get("extra_disks", 1)
        logger.info(f"Number of disks per node: {num_disks}")
        logger.info(f"All disks will be {base_size}GB (uniform size)")
    
    logger.info("=" * 80)

# Made with Bob
